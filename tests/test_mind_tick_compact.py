"""Compact daemon mind tick (rearchitecture task 1.3).

The daemon path asks a background lane for a short structured answer
(summary, current_focus, live_concerns[<=3], live_threads[<=3], next_step),
carries the five lane strings forward from the previous active mind, and
builds a prompt of at most 2,000 tokens without the full identity stack or
the supporting system messages.
"""

import json
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import eve
import eve_prompt_budget
from tests import test_mind_tick as mind_tick_tests


COMPACT_RESPONSE = {
    "summary": "The relay is still waiting on the user; nothing new arrived.",
    "current_focus": "Hold the relay until the user answers.",
    "live_concerns": ["Do not manufacture motion while waiting."],
    "live_threads": [
        {
            "title": "Ongoing relay",
            "detail": "This conversation is waiting on the user.",
            "kind": "conversation",
            "status": "waiting",
        }
    ],
    "next_step": "Wait for the user's next real signal before forcing a move.",
}


class CompactDaemonMindTickTests(unittest.TestCase):
    def setUp(self):
        self.fixture = mind_tick_tests.MindTickTests("test_daemon_mind_tick_uses_load_gated_model_instead_of_hardcoded_text")

    def run_daemon_tick(self, response_payload, *, config=None):
        """Run generate_mind_tick on the fixture state with a fake llama answer."""
        fixture = self.fixture
        config = dict(config or eve.DEFAULT_CONFIG)
        config["daemon_model_mind_tick_enabled"] = True
        captured = {}

        def fake_model_chat(_config, model, messages, **kwargs):
            captured["model"] = model
            captured["messages"] = messages
            captured.update(kwargs)
            return json.dumps(response_payload)

        supporting = Mock(return_value=[])
        with ExitStack() as stack:
            stack.enter_context(patch.object(eve, "load_active_mind", return_value=fixture.sample_active_mind()))
            stack.enter_context(patch.object(eve, "load_human_context", return_value=fixture.sample_human_context()))
            stack.enter_context(patch.object(eve, "load_autonomy_state", return_value=fixture.sample_autonomy_state()))
            stack.enter_context(patch.object(eve, "load_state", return_value=fixture.sample_state()))
            stack.enter_context(patch.object(eve, "load_system_snapshot", return_value={"load_state": "normal"}))
            stack.enter_context(patch.object(eve, "read_thread_summaries", return_value=fixture.sample_threads()))
            stack.enter_context(patch.object(eve, "read_messages", return_value=fixture.sample_messages()))
            stack.enter_context(patch.object(eve, "read_salient_entries", return_value=fixture.sample_entries()))
            stack.enter_context(patch.object(eve, "system_background_gate_reason", return_value=None))
            stack.enter_context(patch.object(eve, "build_supporting_system_messages", supporting))
            # Keep the measurement offline: the conservative fallback is the
            # strictest count, and the test never touches a live lane.
            stack.enter_context(
                patch.object(eve_prompt_budget, "live_context_tokens", side_effect=OSError("offline"))
            )
            stack.enter_context(patch.object(eve, "model_chat", side_effect=fake_model_chat))
            record = eve.generate_mind_tick(config, source="daemon", max_tokens=120)
        captured["supporting_system_messages"] = supporting
        return record, captured

    def test_compact_schema_drops_lanes_and_caps_lists(self):
        compact = eve.mind_tick_response_schema(compact=True)
        self.assertEqual(
            ["current_focus", "live_concerns", "live_threads", "next_step", "summary"],
            sorted(compact["properties"].keys()),
        )
        self.assertEqual(3, compact["properties"]["live_concerns"]["maxItems"])
        self.assertEqual(3, compact["properties"]["live_threads"]["maxItems"])
        full = eve.mind_tick_response_schema()
        self.assertIn("lanes", full["properties"])
        self.assertIn("active_threads", full["properties"])

    def test_compact_tokens_follow_daemon_budget_and_default_is_untouched(self):
        config = dict(eve.DEFAULT_CONFIG)
        self.assertEqual(640, eve.DEFAULT_CONFIG["daemon_model_mind_tick_max_tokens"])
        self.assertEqual(640, eve.structured_mind_tick_tokens(config, None, compact=True))
        self.assertEqual(
            eve.structured_mind_tick_tokens(config, 120),
            eve.structured_mind_tick_tokens(config, 120, compact=False),
        )

    def test_compact_json_response_is_accepted_without_fallback(self):
        record, captured = self.run_daemon_tick(COMPACT_RESPONSE)

        self.assertFalse(record["used_fallback"])
        self.assertTrue(record["background_model_tick"])
        self.assertEqual("", record["fallback_reason"])
        self.assertNotEqual("deterministic", record["model"])
        self.assertEqual("daemon_model_mind_tick", captured["operation"])
        self.assertEqual(640, captured["max_tokens"])
        self.assertNotIn("lanes", captured["response_schema"]["properties"])
        self.assertEqual(COMPACT_RESPONSE["current_focus"], record["mind"]["current_focus"])
        self.assertEqual(COMPACT_RESPONSE["next_step"], record["mind"]["next_step"])
        self.assertIn(COMPACT_RESPONSE["live_concerns"][0], record["mind"]["live_concerns"])

    def test_response_without_lanes_keeps_previous_lanes(self):
        previous_lanes = self.fixture.sample_active_mind()["lanes"]
        record, _captured = self.run_daemon_tick(COMPACT_RESPONSE)

        self.assertEqual(previous_lanes, record["mind"]["lanes"])
        for lane in ("observer", "planner", "relationship", "grounding", "self_check"):
            self.assertTrue(record["mind"]["lanes"][lane])

    def test_merge_active_mind_carries_missing_lanes_forward(self):
        previous = self.fixture.sample_active_mind()
        merged = eve.merge_active_mind(previous, {**COMPACT_RESPONSE, "updated_at": "2026-04-21T03:05:00+00:00"})
        self.assertEqual(previous["lanes"], merged["lanes"])

    def test_daemon_prompt_is_compact_and_under_two_thousand_tokens(self):
        record, captured = self.run_daemon_tick(COMPACT_RESPONSE)
        messages = captured["messages"]

        # No supporting system messages and no full identity stack on the daemon path.
        captured["supporting_system_messages"].assert_not_called()
        contents = [str(message["content"]) for message in messages]
        self.assertEqual(eve.build_interaction_identity_message(), contents[0])
        self.assertNotIn(eve.load_prompt("core_identity.md"), contents)
        self.assertIn(eve.load_prompt("mind_tick_compact.md"), contents)
        self.assertEqual("user", messages[-1]["role"])
        self.assertIn("CURRENT SOURCE-OWNED EVIDENCE", messages[-1]["content"])

        # The measurement is recorded on the tick and stays under the cap even
        # with the conservative character fallback.
        self.assertEqual("conservative_character_fallback", record["prompt_measurement_source"])
        self.assertFalse(record["prompt_tokens_exact"])
        self.assertFalse(record["prompt_trimmed"])
        self.assertEqual(2000, record["prompt_token_cap"])
        self.assertEqual(len(messages), record["prompt_message_count"])
        self.assertLess(record["prompt_tokens"], 2000)
        conservative_total = sum(eve_prompt_budget.conservative_token_estimate(content) for content in contents)
        self.assertLess(conservative_total, 2000)

    def test_daemon_prompt_drops_continuity_when_over_cap(self):
        measurements = []

        def fake_measure(_config, _model, messages):
            has_continuity = any(eve.PROMPT_OPTIONAL_PRIORITY_FIELD in message for message in messages)
            measurement = {
                "prompt_tokens": 2600 if has_continuity else 1200,
                "prompt_tokens_exact": True,
                "prompt_measurement_source": "test",
                "prompt_context_tokens": 8192,
                "prompt_message_count": len(messages),
            }
            measurements.append(measurement)
            return measurement

        with patch.object(eve, "measure_daemon_mind_tick_prompt", side_effect=fake_measure):
            record, captured = self.run_daemon_tick(COMPACT_RESPONSE)

        self.assertEqual(2, len(measurements))
        self.assertTrue(record["prompt_trimmed"])
        self.assertEqual(1200, record["prompt_tokens"])
        self.assertFalse(record["used_fallback"])
        self.assertFalse(any(eve.PROMPT_OPTIONAL_PRIORITY_FIELD in message for message in captured["messages"]))

    def test_run_mind_tick_records_prompt_tokens_in_journal_metadata(self):
        fixture = self.fixture
        config = dict(eve.DEFAULT_CONFIG)
        generated = {
            "mind": {**fixture.sample_active_mind(), "updated_at": "2026-04-21T03:05:00+00:00"},
            "model": "eve-fast",
            "used_fallback": False,
            "fallback_reason": "",
            "background_model_tick": True,
            "prompt_tokens": 1718,
            "prompt_tokens_exact": False,
            "prompt_trimmed": False,
        }
        with ExitStack() as stack:
            stack.enter_context(patch.object(eve, "load_active_mind", return_value=fixture.sample_active_mind()))
            stack.enter_context(patch.object(eve, "load_human_context", return_value=fixture.sample_human_context()))
            stack.enter_context(patch.object(eve, "load_autonomy_state", return_value=fixture.sample_autonomy_state()))
            stack.enter_context(patch.object(eve, "load_state", return_value=fixture.sample_state()))
            stack.enter_context(patch.object(eve, "read_thread_summaries", return_value=fixture.sample_threads()))
            stack.enter_context(patch.object(eve, "read_messages", return_value=fixture.sample_messages()))
            stack.enter_context(patch.object(eve, "active_mind_novelty_gate", return_value={"noop": False}))
            stack.enter_context(patch.object(eve, "generate_mind_tick", return_value=generated))
            stack.enter_context(patch.object(eve, "save_active_mind"))
            stack.enter_context(patch.object(eve, "save_state"))
            stack.enter_context(patch.object(eve, "refresh_global_workspace", return_value={}))
            append_entry = stack.enter_context(patch.object(eve, "append_entry"))
            eve.run_mind_tick(config, source="daemon", max_tokens=120)

        self.assertEqual("mind_tick", append_entry.call_args.args[0])
        metadata = append_entry.call_args.kwargs["metadata"]
        self.assertEqual(1718, metadata["prompt_tokens"])
        self.assertFalse(metadata["prompt_tokens_exact"])
        self.assertFalse(metadata["prompt_trimmed"])
        self.assertTrue(metadata["background_model_tick"])
        self.assertFalse(metadata["used_fallback"])


if __name__ == "__main__":
    unittest.main()
