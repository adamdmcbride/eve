import json
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import eve


NOW = "2026-09-17T02:00:00+00:00"


def quiet_cycle_config(**overrides):
    config = dict(eve.DEFAULT_CONFIG)
    config.update(
        {
            "ambient_thought_enabled": False,
            "component_update_check_enabled": False,
            "agent_capability_scout_enabled": False,
            "agent_capability_integration_enabled": False,
            "presence_cycle_enabled": False,
            "developmental_cycle_enabled": False,
            "workspace_tick_interval_seconds": 0,
            "quiet_consolidation_enabled": False,
            "openclaw_repair_enabled": False,
            "openclaw_routines_enabled": False,
            "self_awareness_perturbation_enabled": False,
            "episode_extraction_enabled": False,
            "beads_bridge_enabled": False,
        }
    )
    config.update(overrides)
    return config


def quiet_cycle_state(**overrides):
    state = {
        "last_human_context_at": NOW,
        "last_mind_tick_at": NOW,
        "last_failure_review_at": NOW,
        "last_self_awareness_test_at": NOW,
        "last_thought_at": NOW,
        "last_heartbeat_at": NOW,
        "last_reflection_at": NOW,
        "last_proposal_at": NOW,
        "last_outreach_check_at": NOW,
        "last_daemon_digest_at": NOW,
    }
    state.update(overrides)
    return state


class DaemonDigestBufferTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.buffer_path = Path(self.tmpdir.name) / "daemon_digest_buffer.jsonl"
        self.create_message = Mock(return_value={"id": "digest-1", "kind": eve.DAEMON_DIGEST_MESSAGE_KIND})
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(eve, "DAEMON_DIGEST_BUFFER_PATH", self.buffer_path))
        self.stack.enter_context(patch.object(eve, "ensure_store"))
        self.stack.enter_context(patch.object(eve, "create_message", self.create_message))

    def buffered_rows(self):
        if not self.buffer_path.exists():
            return []
        return [json.loads(line) for line in self.buffer_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_default_digest_kinds_match_the_program(self):
        self.assertEqual(
            [
                "upgrade_review_update",
                "capability_intelligence_change",
                "capability_adoption_cycle",
                "openclaw_repair_update",
                "component_update_check",
                "self_awareness_update",
                "agent_capability_scout",
                "codex_bridge",
            ],
            eve.DEFAULT_CONFIG["daemon_digest_kinds"],
        )
        self.assertEqual(1440, eve.DEFAULT_CONFIG["daemon_digest_interval_minutes"])
        self.assertIn(eve.DAEMON_DIGEST_MESSAGE_KIND, eve.BACKGROUND_CONTEXT_MESSAGE_KINDS)

    def test_buffered_kinds_do_not_create_mailbox_rows(self):
        config = dict(eve.DEFAULT_CONFIG)
        record = eve.create_daemon_message(
            subject="Eve noticed an upgrade and found drift",
            body="details",
            kind="upgrade_review_update",
            metadata={"source": "daemon", "snapshot_id": "snap-1"},
            config=config,
        )
        eve.create_daemon_message(
            subject="Eve found component update signals",
            body="details",
            kind="component_update_check",
            config=config,
        )

        self.create_message.assert_not_called()
        self.assertEqual("buffered", record["status"])
        rows = self.buffered_rows()
        self.assertEqual(["upgrade_review_update", "component_update_check"], [row["kind"] for row in rows])
        self.assertEqual("snap-1", rows[0]["metadata"]["snapshot_id"])

    def test_unlisted_kinds_go_direct(self):
        config = dict(eve.DEFAULT_CONFIG)
        for kind in ["reflection_update", "proposal_update", "self_change", "proactive_outreach", "failure_review_update"]:
            eve.create_daemon_message(subject=f"{kind} subject", body="body", kind=kind, config=config)

        self.assertEqual(5, self.create_message.call_count)
        self.assertEqual(
            ["reflection_update", "proposal_update", "self_change", "proactive_outreach", "failure_review_update"],
            [call.kwargs["kind"] for call in self.create_message.call_args_list],
        )
        self.assertFalse(self.buffer_path.exists())

    def test_empty_digest_kinds_disables_buffering(self):
        config = dict(eve.DEFAULT_CONFIG)
        config["daemon_digest_kinds"] = []
        eve.create_daemon_message(subject="drift", body="body", kind="upgrade_review_update", config=config)

        self.create_message.assert_called_once()
        self.assertEqual("upgrade_review_update", self.create_message.call_args.kwargs["kind"])
        self.assertFalse(self.buffer_path.exists())

    def test_create_daemon_message_reads_live_config_when_none_is_given(self):
        with patch.object(eve, "load_config", return_value=dict(eve.DEFAULT_CONFIG)) as load_config:
            eve.create_daemon_message(subject="drift", body="body", kind="self_awareness_update")

        load_config.assert_called_once()
        self.create_message.assert_not_called()
        self.assertEqual(["self_awareness_update"], [row["kind"] for row in self.buffered_rows()])

    def test_digest_sends_exactly_one_message_and_empties_the_buffer(self):
        config = dict(eve.DEFAULT_CONFIG)
        eve.create_daemon_message(subject="first drift", body="b", kind="upgrade_review_update", config=config)
        eve.create_daemon_message(subject="second drift", body="b", kind="upgrade_review_update", config=config)
        eve.create_daemon_message(subject="update signals", body="b", kind="component_update_check", config=config)
        self.assertEqual(3, len(self.buffered_rows()))

        message = eve.send_daemon_digest(config)

        self.assertIsNotNone(message)
        self.create_message.assert_called_once()
        kwargs = self.create_message.call_args.kwargs
        self.assertEqual(eve.DAEMON_DIGEST_MESSAGE_KIND, kwargs["kind"])
        self.assertEqual("eve", kwargs["sender"])
        self.assertEqual("user", kwargs["recipient"])
        self.assertIn("3 background updates", kwargs["subject"])
        self.assertIn("- upgrade_review_update: 2 (last: second drift)", kwargs["body"])
        self.assertIn("- component_update_check: 1 (last: update signals)", kwargs["body"])
        self.assertEqual(3, kwargs["metadata"]["digest"]["total"])
        self.assertEqual(
            [("upgrade_review_update", 2), ("component_update_check", 1)],
            [(item["kind"], item["count"]) for item in kwargs["metadata"]["digest"]["kinds"]],
        )
        self.assertTrue(self.buffer_path.exists())
        self.assertEqual([], self.buffered_rows())

    def test_digest_with_empty_buffer_sends_nothing(self):
        self.assertIsNone(eve.send_daemon_digest(dict(eve.DEFAULT_CONFIG)))
        self.create_message.assert_not_called()
        self.assertFalse(self.buffer_path.exists())

    def test_digest_flushes_even_when_buffering_is_disabled(self):
        self.buffer_path.write_text(
            json.dumps({"kind": "codex_bridge", "subject": "bridge note", "timestamp": NOW}) + "\n",
            encoding="utf-8",
        )
        config = dict(eve.DEFAULT_CONFIG)
        config["daemon_digest_kinds"] = []

        self.assertIsNotNone(eve.send_daemon_digest(config))
        self.create_message.assert_called_once()
        self.assertIn("- codex_bridge: 1 (last: bridge note)", self.create_message.call_args.kwargs["body"])
        self.assertEqual([], self.buffered_rows())

    def test_digest_keeps_the_buffer_when_the_message_cannot_be_created(self):
        config = dict(eve.DEFAULT_CONFIG)
        eve.create_daemon_message(subject="drift", body="b", kind="upgrade_review_update", config=config)
        self.create_message.side_effect = RuntimeError("mailbox locked")

        with self.assertRaisesRegex(RuntimeError, "mailbox locked"):
            eve.send_daemon_digest(config)

        self.assertEqual(1, len(self.buffered_rows()))


class DaemonDigestCycleTests(unittest.TestCase):
    def run_cycle(self, config, state, extra_patches=None):
        with ExitStack() as stack:
            stack.enter_context(patch.object(eve, "utc_now", return_value=NOW))
            stack.enter_context(patch.object(eve, "read_thread_summaries", return_value=[]))
            stack.enter_context(patch.object(eve, "ensure_version_snapshot", return_value={}))
            stack.enter_context(patch.object(eve, "load_system_snapshot", return_value={}))
            stack.enter_context(patch.object(eve, "human_context_refresh_due", return_value=False))
            stack.enter_context(
                patch.object(eve, "interval_due", side_effect=lambda timestamp, minutes: timestamp is None)
            )
            stack.enter_context(patch.object(eve, "run_mind_tick"))
            stack.enter_context(patch.object(eve, "save_state"))
            stack.enter_context(patch.object(eve, "append_entry"))
            for name, value in (extra_patches or {}).items():
                stack.enter_context(patch.object(eve, name, value))
            return eve.run_daemon_cycle(config, state, force=False)

    def test_digest_job_runs_when_due_and_stamps_state(self):
        send_daemon_digest = Mock(return_value={"id": "digest-1"})
        config = quiet_cycle_config()
        state = quiet_cycle_state(last_daemon_digest_at=None)

        completed = self.run_cycle(config, state, {"send_daemon_digest": send_daemon_digest})

        send_daemon_digest.assert_called_once_with(config)
        self.assertIn("daemon_digest", completed)
        self.assertEqual(NOW, state["last_daemon_digest_at"])

    def test_digest_job_waits_for_its_interval(self):
        send_daemon_digest = Mock(return_value={"id": "digest-1"})
        config = quiet_cycle_config()
        state = quiet_cycle_state()

        completed = self.run_cycle(config, state, {"send_daemon_digest": send_daemon_digest})

        send_daemon_digest.assert_not_called()
        self.assertNotIn("daemon_digest", completed)

    def test_empty_digest_does_not_count_as_a_completed_job(self):
        send_daemon_digest = Mock(return_value=None)
        config = quiet_cycle_config()
        state = quiet_cycle_state(last_daemon_digest_at=None)

        completed = self.run_cycle(config, state, {"send_daemon_digest": send_daemon_digest})

        send_daemon_digest.assert_called_once_with(config)
        self.assertNotIn("daemon_digest", completed)
        self.assertEqual(NOW, state["last_daemon_digest_at"])


class UpgradeReviewCapTests(unittest.TestCase):
    def run_cycle(self, config, state, snapshot, run_self_awareness_test, append_entry):
        with ExitStack() as stack:
            stack.enter_context(patch.object(eve, "utc_now", return_value=NOW))
            stack.enter_context(patch.object(eve, "read_thread_summaries", return_value=[]))
            stack.enter_context(patch.object(eve, "ensure_version_snapshot", return_value=snapshot))
            stack.enter_context(patch.object(eve, "load_system_snapshot", return_value={}))
            stack.enter_context(patch.object(eve, "human_context_refresh_due", return_value=False))
            stack.enter_context(
                patch.object(eve, "interval_due", side_effect=lambda timestamp, minutes: timestamp is None)
            )
            stack.enter_context(patch.object(eve, "run_mind_tick"))
            stack.enter_context(patch.object(eve, "upgrade_review_disposition", return_value="review"))
            stack.enter_context(patch.object(eve, "run_self_awareness_test", run_self_awareness_test))
            stack.enter_context(patch.object(eve, "create_daemon_message"))
            stack.enter_context(patch.object(eve, "send_daemon_digest", return_value=None))
            stack.enter_context(patch.object(eve, "save_state"))
            stack.enter_context(patch.object(eve, "append_entry", append_entry))
            return eve.run_daemon_cycle(config, state, force=False)

    def test_two_upgrade_snapshots_within_the_interval_run_one_review(self):
        run_self_awareness_test = Mock(return_value={"passed": True, "problems": [], "tested_at": NOW})
        append_entry = Mock()
        config = quiet_cycle_config()
        state = quiet_cycle_state(last_self_awareness_test_at=None)

        first = self.run_cycle(
            config,
            state,
            {"id": "snap-1", "summary": "eve.py changed", "changed_components": ["eve.py"]},
            run_self_awareness_test,
            append_entry,
        )
        self.assertIn("upgrade_review", first)
        self.assertEqual(1, run_self_awareness_test.call_count)
        self.assertEqual(NOW, state["last_upgrade_review_attempt_at"])
        self.assertEqual("snap-1", state["last_upgrade_reviewed_snapshot_id"])

        second = self.run_cycle(
            config,
            state,
            {"id": "snap-2", "summary": "eve.py changed again", "changed_components": ["eve.py"]},
            run_self_awareness_test,
            append_entry,
        )

        self.assertNotIn("upgrade_review", second)
        self.assertEqual(1, run_self_awareness_test.call_count)
        self.assertEqual("snap-1", state["last_upgrade_reviewed_snapshot_id"])
        self.assertEqual("snap-1", state["last_upgrade_review_attempt_snapshot_id"])
        self.assertEqual("snap-2", state["last_upgrade_review_cap_snapshot_id"])
        cap_skips = [
            call
            for call in append_entry.call_args_list
            if call.args[0] == "cycle_skipped" and call.kwargs.get("metadata", {}).get("gate") == "upgrade_review_cap"
        ]
        self.assertEqual(1, len(cap_skips))
        self.assertEqual("snap-2", cap_skips[0].kwargs["metadata"]["snapshot_id"])
        upgrade_detected = [call for call in append_entry.call_args_list if call.args[0] == "upgrade_detected"]
        self.assertEqual(1, len(upgrade_detected))

        # The cap skip is logged once per snapshot, not once per cycle.
        third = self.run_cycle(
            config,
            state,
            {"id": "snap-2", "summary": "eve.py changed again", "changed_components": ["eve.py"]},
            run_self_awareness_test,
            append_entry,
        )
        self.assertNotIn("upgrade_review", third)
        self.assertEqual(1, run_self_awareness_test.call_count)
        cap_skips = [
            call
            for call in append_entry.call_args_list
            if call.args[0] == "cycle_skipped" and call.kwargs.get("metadata", {}).get("gate") == "upgrade_review_cap"
        ]
        self.assertEqual(1, len(cap_skips))

    def test_review_runs_again_once_the_interval_has_elapsed(self):
        run_self_awareness_test = Mock(return_value={"passed": True, "problems": [], "tested_at": NOW})
        append_entry = Mock()
        config = quiet_cycle_config()
        state = quiet_cycle_state(
            last_upgrade_review_attempt_at=None,
            last_upgrade_review_attempt_snapshot_id="snap-1",
            last_upgrade_reviewed_snapshot_id="snap-1",
        )

        completed = self.run_cycle(
            config,
            state,
            {"id": "snap-2", "summary": "eve.py changed", "changed_components": ["eve.py"]},
            run_self_awareness_test,
            append_entry,
        )

        self.assertIn("upgrade_review", completed)
        self.assertEqual(1, run_self_awareness_test.call_count)
        self.assertEqual("snap-2", state["last_upgrade_reviewed_snapshot_id"])


if __name__ == "__main__":
    unittest.main()
