"""Presence cycle on the compact tick (rearchitecture task 1.4).

The daemon's hourly presence cycle calls ``run_mind_tick`` with
``source="presence_cycle:daemon"``.  That must take the same compact
background path as a plain ``daemon`` tick (one budgeted planner call) and
never convene the five-lane mind-stream council, its revision round or its
synthesis.  A manual ``presence cycle`` (``presence_cycle:manual``) keeps the
council so it can still be evaluated by hand.
"""

import json
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import eve
import eve_db


COUNCIL_FUNCTIONS = (
    "run_mind_stream",
    "admit_mind_stream_packets",
    "evaluate_mind_stream_packets_grounding",
    "run_mind_stream_revision_round",
    "budgeted_mind_stream_model_synthesis",
    "deterministic_mind_stream_synthesis_payload",
)


class PresenceCompactTickTests(unittest.TestCase):
    def sample_active_mind(self):
        return {
            **eve.default_active_mind(),
            "updated_at": "2026-04-21T03:04:00+00:00",
            "source": "test",
            "model": "test-model",
            "summary": "Stay with the relay and keep the next move concrete.",
            "current_focus": "Stay with the relay.",
            "live_concerns": ["Do not drift into performance."],
            "active_threads": ["Ongoing relay"],
            "next_step": "Reply in a way that leaves room for the user to keep moving.",
        }

    def sample_human_context(self):
        return {
            "updated_at": "2026-04-21T03:00:00+00:00",
            "source": "test",
            "self_model": {
                "identity_statement": "Eve is learning a steadier, evidence-backed presence.",
                "current_preoccupations": ["Keep the current loop grounded"],
            },
            "relationship_memory": {
                "user_overview": "the user wants continuity, honesty, and concrete follow-through.",
                "open_loops": ["Keep the relay grounded"],
            },
        }

    def sample_state(self):
        return {
            "current_focus": "Figure out what is actually moving in Eve right now.",
            "active_thread_count": 1,
            "last_human_context_at": "2026-04-21T03:00:00+00:00",
            "last_thought_at": "2026-04-21T02:50:00+00:00",
        }

    def sample_threads(self):
        return [
            {
                "thread_id": "t1",
                "status": "awaiting_user",
                "subject": "Ongoing relay",
                "latest_preview": "Keep the relay grounded in what is actually changing.",
                "latest_sender": "eve",
                "latest_timestamp": "2026-04-21T03:00:47+00:00",
                "unread_count": 1,
                "message_count": 12,
            }
        ]

    def sample_messages(self):
        return [
            {
                "id": "m1",
                "timestamp": "2026-04-21T03:00:47+00:00",
                "sender": "user",
                "recipient": "eve",
                "subject": "Re: Ongoing relay",
                "body": "Keep going, but stay concrete.",
            }
        ]

    def sample_entries(self):
        return [
            {
                "id": "e1",
                "timestamp": "2026-04-21T02:58:00+00:00",
                "kind": "reflection",
                "text": "Reliability matters more than theatrical insight.",
            }
        ]

    def _common_patches(self, stack):
        stack.enter_context(patch.object(eve, "load_active_mind", return_value=self.sample_active_mind()))
        stack.enter_context(patch.object(eve, "load_human_context", return_value=self.sample_human_context()))
        stack.enter_context(
            patch.object(
                eve,
                "load_autonomy_state",
                return_value={"stage": "verified", "source": "manual", "note": "test"},
            )
        )
        stack.enter_context(patch.object(eve, "load_state", return_value=self.sample_state()))
        stack.enter_context(patch.object(eve, "load_system_snapshot", return_value={"load_state": "normal"}))
        stack.enter_context(patch.object(eve, "read_thread_summaries", return_value=self.sample_threads()))
        stack.enter_context(patch.object(eve, "read_messages", return_value=self.sample_messages()))
        stack.enter_context(patch.object(eve, "read_salient_entries", return_value=self.sample_entries()))
        stack.enter_context(patch.object(eve, "active_mind_organ_signals", return_value=[]))
        stack.enter_context(patch.object(eve, "objective_reanchor_from_agenda", return_value={}))
        stack.enter_context(patch.object(eve, "live_operational_reanchor", return_value={}))
        stack.enter_context(patch.object(eve, "focus_needs_live_reanchor", return_value=False))
        stack.enter_context(patch.object(eve, "system_background_gate_reason", return_value=None))
        stack.enter_context(patch.object(eve, "build_supporting_system_messages", return_value=[]))
        stack.enter_context(patch.object(eve, "build_system_grounding_messages", return_value=[]))
        # Keep the test hermetic: the council path ledgers packets and perf
        # events into the checkout's .eve store even with EVE_RUNTIME_DIR set.
        stack.enter_context(patch.object(eve, "append_mind_stream_packet", return_value={}))
        stack.enter_context(patch.object(eve, "append_perf_event", return_value=None))
        # system_resource_alerts re-loads config and load_conscious_state goes
        # through the JSON repository; both run ensure_store, which opens the
        # checkout's operational sqlite store.  Keep the store closed in tests.
        stack.enter_context(patch.object(eve, "system_resource_alerts", return_value=[]))
        stack.enter_context(
            patch.object(eve, "load_conscious_state", return_value=eve.default_conscious_state())
        )
        stack.enter_context(patch.object(eve, "load_homeostasis", return_value={}))
        stack.enter_context(patch.object(eve, "load_config", return_value=dict(eve.DEFAULT_CONFIG)))
        stack.enter_context(patch.object(eve, "read_active_mind_audit_log", return_value=[]))
        # The shared store-read layer (resolve_store_read_path -> ensure_store)
        # still reaches the sqlite schema check; stop it at the eve_db seam so
        # the test never opens the checkout's operational store.
        stack.enter_context(patch.object(eve_db, "initialize_database", return_value=None))

    def test_mind_tick_source_is_background_matches_daemon_and_daemon_presence_only(self):
        self.assertTrue(eve.mind_tick_source_is_background("daemon"))
        self.assertTrue(eve.mind_tick_source_is_background("daemon_autonomy"))
        self.assertTrue(eve.mind_tick_source_is_background("presence_cycle:daemon"))
        self.assertFalse(eve.mind_tick_source_is_background("presence_cycle:manual"))
        self.assertFalse(eve.mind_tick_source_is_background("presence_cycle:cli"))
        self.assertFalse(eve.mind_tick_source_is_background("manual"))
        self.assertFalse(eve.mind_tick_source_is_background("test"))
        self.assertFalse(eve.mind_tick_source_is_background(""))
        self.assertFalse(eve.mind_tick_source_is_background(None))

    def test_daemon_presence_cycle_takes_compact_path_and_never_convenes_council(self):
        config = dict(eve.DEFAULT_CONFIG)
        config["daemon_model_mind_tick_enabled"] = True
        generated = {
            **self.sample_active_mind(),
            "summary": "A compact background update noticed a real change.",
            "current_focus": "Track the real change without manufacturing motion.",
        }
        captured = {}

        def fake_model_chat(*args, **kwargs):
            captured.update(kwargs)
            return json.dumps(generated)

        council = {}
        with ExitStack() as stack:
            self._common_patches(stack)
            for name in COUNCIL_FUNCTIONS:
                council[name] = stack.enter_context(patch.object(eve, name))
            model_chat = stack.enter_context(patch.object(eve, "model_chat", side_effect=fake_model_chat))
            record = eve.generate_mind_tick(config, source="presence_cycle:daemon", max_tokens=120)

        self.assertTrue(record["background_model_tick"], record.get("fallback_reason"))
        self.assertFalse(record["used_fallback"], record.get("fallback_reason"))
        self.assertEqual("daemon_model_mind_tick", captured["operation"])
        self.assertEqual(1, model_chat.call_count)
        self.assertEqual(generated["current_focus"], record["mind"]["current_focus"])
        self.assertEqual("presence_cycle:daemon_model", record["mind"]["source"])
        for name, mock in council.items():
            mock.assert_not_called()

    def test_daemon_presence_cycle_compact_path_stays_deterministic_when_gated(self):
        config = dict(eve.DEFAULT_CONFIG)
        council = {}
        with ExitStack() as stack:
            self._common_patches(stack)
            stack.enter_context(
                patch.object(eve, "system_background_gate_reason", return_value="machine is hot")
            )
            for name in COUNCIL_FUNCTIONS:
                council[name] = stack.enter_context(patch.object(eve, name))
            model_chat = stack.enter_context(patch.object(eve, "model_chat"))
            record = eve.generate_mind_tick(config, source="presence_cycle:daemon", max_tokens=120)

        self.assertFalse(record["background_model_tick"])
        self.assertTrue(record["used_fallback"])
        self.assertEqual("deterministic", record["model"])
        self.assertIn("machine is hot", record["fallback_reason"])
        model_chat.assert_not_called()
        for name, mock in council.items():
            mock.assert_not_called()

    def test_manual_presence_cycle_still_convenes_council(self):
        config = dict(eve.DEFAULT_CONFIG)
        config["mind_stream_parallel_enabled"] = False
        config["mind_tick_timeout_seconds"] = 5
        model_chat = Mock(return_value="{}")

        with ExitStack() as stack:
            self._common_patches(stack)
            run_mind_stream = stack.enter_context(
                patch.object(eve, "run_mind_stream", side_effect=SystemExit("lane timeout"))
            )
            stack.enter_context(patch.object(eve, "model_chat", model_chat))
            record = eve.generate_mind_tick(config, source="presence_cycle:manual", max_tokens=120)

        # The council ran: one lane call per mind-stream lane, and no compact
        # background planner call was made in its place.
        self.assertGreaterEqual(run_mind_stream.call_count, 5)
        lanes = sorted({call.args[1] for call in run_mind_stream.call_args_list})
        self.assertEqual(["grounding", "observer", "planner", "relationship", "self_check"], lanes)
        self.assertFalse(record.get("background_model_tick", False))
        self.assertNotEqual("presence_cycle:manual_model", record["mind"]["source"])
        for call in model_chat.call_args_list:
            self.assertNotEqual("daemon_model_mind_tick", call.kwargs.get("operation"))


if __name__ == "__main__":
    unittest.main()
