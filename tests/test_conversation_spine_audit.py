import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "bin" / "eve_conversation_spine_audit.py"
SPEC = importlib.util.spec_from_file_location("eve_conversation_spine_audit", SCRIPT_PATH)
audit = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(audit)


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


class ConversationSpineAuditTests(unittest.TestCase):
    def test_detects_synthetic_prompt_and_council_abstention(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            eve_dir = Path(tmp)
            write_jsonl(
                eve_dir / "experience_events.jsonl",
                [
                    {
                        "timestamp": "2026-05-06T19:34:50+00:00",
                        "event_type": "user_signal",
                        "summary": "Keep going.",
                        "metadata": {"kind": "user_message"},
                    }
                ],
            )
            write_jsonl(
                eve_dir / "messages.jsonl",
                [{"created_at": "2026-04-29T00:00:00+00:00", "body": "old"}],
            )
            write_jsonl(
                eve_dir / "reply_turn_replays.jsonl",
                [
                    {
                        "created_at": "2026-05-06T19:34:51+00:00",
                        "thread_id": "thread-1",
                        "source_message_id": "msg-1",
                        "inbound_preview": "What is the next grounded runtime step here?",
                        "reply_preview": "The next grounded step is to stay with the live thread.",
                        "turn_contract": {"latest_message": "What is the next grounded runtime step here?"},
                    }
                ],
            )
            write_jsonl(
                eve_dir / "reply_council_turns.jsonl",
                [
                    {
                        "created_at": "2026-05-06T19:34:51+00:00",
                        "thread_id": "thread-1",
                        "source_message_id": "msg-1",
                        "inbound_preview": "What is the next grounded runtime step here?",
                        "reply_preview": "The next grounded step is to stay with the live thread.",
                        "used_model": "gemma4:31b",
                        "synthesis_model": "gemma4:31b",
                        "active_lanes": [],
                        "abstained_lanes": ["fast", "observer"],
                        "reason": "only fast lane pressure was high enough",
                    }
                ],
            )

            report = audit.build_report(eve_dir)

            finding_ids = {finding["id"] for finding in report["findings"]}
            self.assertEqual(report["status"], "degraded")
            self.assertIn("canonical_message_ledger_stale", finding_ids)
            self.assertIn("only_synthetic_reply_replays_available", finding_ids)

    def test_unmarked_synthetic_prompt_still_counts_as_contamination_with_real_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            eve_dir = Path(tmp)
            write_jsonl(
                eve_dir / "experience_events.jsonl",
                [
                    {
                        "timestamp": "2026-05-06T19:34:50+00:00",
                        "event_type": "user_signal",
                        "summary": "Keep going.",
                        "metadata": {"kind": "user_message"},
                    }
                ],
            )
            write_jsonl(
                eve_dir / "messages.jsonl",
                [{"created_at": "2026-05-06T19:34:50+00:00", "body": "Keep going."}],
            )
            write_jsonl(
                eve_dir / "reply_turn_replays.jsonl",
                [
                    {
                        "created_at": "2026-05-06T19:34:51+00:00",
                        "thread_id": "real-thread",
                        "source_message_id": "real-message",
                        "inbound_preview": "What is the next grounded runtime step here?",
                        "reply_preview": "The next grounded step is to stay with the live thread.",
                    }
                ],
            )
            write_jsonl(eve_dir / "reply_council_turns.jsonl", [])

            report = audit.build_report(eve_dir)

            finding_ids = {finding["id"] for finding in report["findings"]}
            self.assertIn("reply_replay_not_grounded_to_latest_user_signal", finding_ids)
            self.assertIn("synthetic_prompt_contamination", finding_ids)

    def test_visible_reply_downgrades_stale_reply_replay_to_instrumentation_lag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            eve_dir = Path(tmp)
            write_jsonl(
                eve_dir / "experience_events.jsonl",
                [
                    {
                        "timestamp": "2026-05-06T20:33:36+00:00",
                        "event_type": "user_signal",
                        "summary": "how old are you?",
                        "metadata": {"kind": "user_message", "message_id": "user-1", "thread_id": "thread-1"},
                    }
                ],
            )
            write_jsonl(
                eve_dir / "messages.jsonl",
                [
                    {
                        "id": "reply-1",
                        "timestamp": "2026-05-06T20:36:18+00:00",
                        "thread_id": "thread-1",
                        "sender": "eve",
                        "recipient": "user",
                        "reply_to": "user-1",
                        "body": "I am active in this current local runtime session.",
                    }
                ],
            )
            write_jsonl(
                eve_dir / "conversation_spine.jsonl",
                [
                    {
                        "timestamp": "2026-05-06T20:36:18+00:00",
                        "thread_id": "thread-1",
                        "message_id": "reply-1",
                        "reply_to": "user-1",
                        "role": "assistant",
                        "direction": "outbound",
                        "body_preview": "I am active in this current local runtime session.",
                    }
                ],
            )
            write_jsonl(
                eve_dir / "reply_turn_replays.jsonl",
                [
                    {
                        "created_at": "2026-05-06T20:21:16+00:00",
                        "inbound_preview": "Runtime verification 4",
                        "reply_preview": "Older reply",
                    }
                ],
            )
            write_jsonl(eve_dir / "reply_council_turns.jsonl", [])

            report = audit.build_report(eve_dir)

            finding_ids = {finding["id"] for finding in report["findings"]}
            self.assertIn("reply_replay_lagging_latest_visible_reply", finding_ids)
            self.assertNotIn("reply_replay_not_grounded_to_latest_user_signal", finding_ids)

    def test_historical_replay_repetition_is_low_after_latest_turn_moves_on(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            eve_dir = Path(tmp)
            write_jsonl(eve_dir / "messages.jsonl", [])
            write_jsonl(
                eve_dir / "experience_events.jsonl",
                [
                    {
                        "timestamp": "2026-05-06T21:15:46+00:00",
                        "event_type": "user_signal",
                        "summary": "Do you see the logic error?",
                        "metadata": {"kind": "user_message", "message_id": "new-user"},
                    }
                ],
            )
            write_jsonl(
                eve_dir / "reply_turn_replays.jsonl",
                [
                    {
                        "created_at": f"2026-05-06T21:0{index}:00+00:00",
                        "source_message_id": f"old-{index}",
                        "inbound_preview": "how old are you?",
                        "reply_preview": "older repeated reply",
                    }
                    for index in range(3)
                ]
                + [
                    {
                        "created_at": "2026-05-06T21:16:06+00:00",
                        "source_message_id": "new-user",
                        "inbound_preview": "Do you see the logic error?",
                        "reply_preview": "Yes. That was a logic error.",
                    }
                ],
            )
            write_jsonl(eve_dir / "reply_council_turns.jsonl", [])

            report = audit.build_report(eve_dir)

        finding = next(finding for finding in report["findings"] if finding["id"] == "reply_replay_repetition_loop")
        self.assertEqual("low", finding["severity"])
        self.assertFalse(finding["evidence"]["current_repetition"])

    def test_auto_selects_newer_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / ".eve"
            runtime = root / "runtime" / ".eve"
            source.mkdir(parents=True)
            runtime.mkdir(parents=True)
            write_jsonl(source / "messages.jsonl", [{"timestamp": "2026-05-06T19:00:00+00:00"}])
            write_jsonl(runtime / "messages.jsonl", [{"timestamp": "2026-05-06T20:00:00+00:00"}])

            original_runtime = audit.DEFAULT_RUNTIME_EVE_DIR
            audit.DEFAULT_RUNTIME_EVE_DIR = runtime
            try:
                selected, state_source, selection = audit.select_analysis_eve_dir(source, "auto")
            finally:
                audit.DEFAULT_RUNTIME_EVE_DIR = original_runtime

            self.assertEqual(runtime, selected)
            self.assertEqual("runtime_auto_newer", state_source)
            self.assertEqual(str(source), selection["requested_eve_dir"])

    def test_auto_selects_runtime_when_source_lacks_conversation_spine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / ".eve"
            runtime = root / "runtime" / ".eve"
            source.mkdir(parents=True)
            runtime.mkdir(parents=True)
            write_jsonl(runtime / "messages.jsonl", [{"timestamp": "2026-05-06T20:00:00+00:00"}])
            write_jsonl(runtime / "conversation_spine.jsonl", [{"timestamp": "2026-05-06T20:00:00+00:00"}])
            write_jsonl(source / "messages.jsonl", [{"timestamp": "2026-05-06T20:01:00+00:00"}])

            original_runtime = audit.DEFAULT_RUNTIME_EVE_DIR
            audit.DEFAULT_RUNTIME_EVE_DIR = runtime
            try:
                selected, state_source, selection = audit.select_analysis_eve_dir(source, "auto")
            finally:
                audit.DEFAULT_RUNTIME_EVE_DIR = original_runtime

            self.assertEqual(runtime, selected)
            self.assertEqual("runtime_auto_has_spine", state_source)
            self.assertFalse(selection["requested_has_conversation_spine"])
            self.assertTrue(selection["runtime_has_conversation_spine"])

    def test_detects_timestamp_mismatch_and_zero_duration_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            eve_dir = Path(tmp)
            write_jsonl(
                eve_dir / "experience_events.jsonl",
                [
                    {
                        "timestamp": "2026-05-06T19:34:50+00:00",
                        "event_type": "user_signal",
                        "summary": "Keep going.",
                        "metadata": {"kind": "user_message"},
                    }
                ],
            )
            write_jsonl(eve_dir / "messages.jsonl", [])
            write_jsonl(eve_dir / "reply_turn_replays.jsonl", [])
            write_jsonl(eve_dir / "reply_council_turns.jsonl", [])
            write_jsonl(
                eve_dir / "presence_cycles.jsonl",
                [
                    {
                        "id": "cycle-1",
                        "timestamp": "2026-05-06T19:34:00+00:00",
                        "presence_after": {"generated_at": "2026-04-21T03:05:00+00:00"},
                    }
                ],
            )
            write_jsonl(
                eve_dir / "event_ledger.jsonl",
                [
                    {
                        "id": "evt-1",
                        "timestamp": "2026-05-06T19:34:00+00:00",
                        "type": "PresencePulseEvent",
                        "payload": {"generated_at": "2026-04-21T03:05:00+00:00"},
                    }
                ],
            )
            (eve_dir / "reply_progress.json").write_text(
                json.dumps(
                    {
                        "jobs": [
                            {
                                "id": "job-1",
                                "status": "completed",
                                "started_at": "2026-05-06T19:34:51+00:00",
                                "finished_at": "2026-05-06T19:34:51+00:00",
                                "notes": [
                                    {"timestamp": "2026-05-06T19:34:51+00:00", "phase": str(index)}
                                    for index in range(6)
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = audit.build_report(eve_dir)

            finding_ids = {finding["id"] for finding in report["findings"]}
            self.assertIn("runtime_timestamp_provenance_mismatch", finding_ids)
            self.assertIn("reply_progress_zero_duration_theater", finding_ids)

    def test_historical_timestamp_mismatch_is_low_severity_debt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            eve_dir = Path(tmp)
            write_jsonl(eve_dir / "experience_events.jsonl", [])
            write_jsonl(eve_dir / "messages.jsonl", [])
            write_jsonl(eve_dir / "reply_turn_replays.jsonl", [])
            write_jsonl(eve_dir / "reply_council_turns.jsonl", [])
            write_jsonl(
                eve_dir / "presence_cycles.jsonl",
                [
                    {
                        "id": "cycle-old",
                        "timestamp": "2026-05-06T19:34:00+00:00",
                        "presence_after": {"generated_at": "2026-04-21T03:05:00+00:00"},
                    },
                    {
                        "id": "cycle-new",
                        "timestamp": "2026-05-06T20:34:00+00:00",
                        "presence_after": {"generated_at": "2026-05-06T20:34:00+00:00"},
                    },
                ],
            )
            write_jsonl(
                eve_dir / "event_ledger.jsonl",
                [
                    {
                        "id": "evt-old",
                        "timestamp": "2026-05-06T19:34:00+00:00",
                        "type": "PresencePulseEvent",
                        "payload": {"generated_at": "2026-04-21T03:05:00+00:00"},
                    },
                    {
                        "id": "evt-new",
                        "timestamp": "2026-05-06T20:34:00+00:00",
                        "type": "PresencePulseEvent",
                        "payload": {"generated_at": "2026-05-06T20:34:00+00:00"},
                    },
                ],
            )

            report = audit.build_report(eve_dir)

        finding = next(
            finding
            for finding in report["findings"]
            if finding["id"] == "historical_runtime_timestamp_provenance_mismatch"
        )
        self.assertEqual("low", finding["severity"])
        self.assertEqual("passed", report["status"])


if __name__ == "__main__":
    unittest.main()
