"""Reflection and proposals draw on lived journal rows, never on telemetry.

Program task 1.2 (docs/architecture/EVE_REARCHITECTURE_PROGRAM_2026_09_17.md):
``generate_reflection``, ``suggest_proposal`` and ``refresh_human_context``
read the journal with ``exclude_kinds=TELEMETRY_ENTRY_KINDS``; the reflection
metadata reports ``lived_kinds`` and ``excluded_telemetry``; the prompt the
model receives is capped at ``LIVED_EVIDENCE_PROMPT_MAX_TOKENS`` through
``eve_prompt_budget``. Python 3.9 compatible; no network, no runtime dir.
"""
import contextlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import eve
import eve_prompt_budget

LIVED_ROWS = [
    ("thought", "I keep circling the relay question without landing it."),
    ("reflection", "Last week the fly work pulled attention from the mailbox."),
    ("message", "The user asked whether the connectome run had finished."),
    ("outcome_logged", "message:abcd1234 -> positive/relief"),
    ("action_executed", "Ran the memory sweep and archived two stale threads."),
]


def write_journal(path, lived_rows, telemetry_count=60):
    now = datetime.now(timezone.utc)
    rows = []
    for index in range(telemetry_count):
        kind = eve.TELEMETRY_ENTRY_KINDS[index % len(eve.TELEMETRY_ENTRY_KINDS)]
        rows.append(
            {
                "id": "telemetry-%d" % index,
                "timestamp": (now - timedelta(minutes=telemetry_count + 20 - index)).isoformat(),
                "kind": kind,
                "text": "telemetry row %d for %s" % (index, kind),
                "tags": [],
                "metadata": {"source": "daemon"},
            }
        )
    for index, (kind, text) in enumerate(lived_rows):
        rows.append(
            {
                "id": "lived-%d" % index,
                "timestamp": (now - timedelta(minutes=len(lived_rows) + 1 - index)).isoformat(),
                "kind": kind,
                "text": text,
                "tags": [],
                "metadata": {},
            }
        )
    rows.sort(key=lambda row: row["timestamp"])
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return rows


def fake_measure_prompt(host, messages, *, fallback_context_tokens=0, timeout=3.0):
    normalized = eve_prompt_budget.normalize_messages(messages)
    rendered = "\n\n".join("<%s>\n%s" % (item["role"], item["content"]) for item in normalized)
    return eve_prompt_budget.PromptMeasurement(
        context_tokens=32768,
        prompt_tokens=eve_prompt_budget.conservative_token_estimate(rendered),
        exact=False,
        source="test_estimate",
    )


def prompt_text(messages):
    return "\n".join(str(message.get("content") or "") for message in messages)


def telemetry_markers_in(text):
    return [kind for kind in eve.TELEMETRY_ENTRY_KINDS if "[%s]" % kind in text]


class ReflectionContextTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(json.dumps(eve.DEFAULT_CONFIG))
        self.captured = []

    def fake_model_chat(self, config, model, messages, **kwargs):
        self.captured.append([dict(message) for message in messages])
        return "A reflection on lived days."

    @contextlib.contextmanager
    def model_patches(self, entries_path):
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(eve, "ENTRIES_PATH", entries_path))
            stack.enter_context(patch.object(eve, "ensure_store"))
            stack.enter_context(patch.object(eve, "ensure_version_snapshot", return_value={}))
            stack.enter_context(patch.object(eve, "ensure_human_context", return_value={}))
            stack.enter_context(patch.object(eve, "load_active_mind", return_value={}))
            stack.enter_context(
                patch.object(
                    eve,
                    "build_eve_identity_system_messages",
                    return_value=[{"role": "system", "content": "You are Eve."}],
                )
            )
            stack.enter_context(patch.object(eve, "build_inner_state_brief_message", return_value=None))
            stack.enter_context(patch.object(eve, "build_supporting_system_messages", return_value=[]))
            stack.enter_context(patch.object(eve, "active_mind_retrieval_query", return_value=None))
            stack.enter_context(patch.object(eve, "load_prompt", return_value="Reflect on the journal."))
            stack.enter_context(patch.object(eve, "read_tensions", return_value=[]))
            stack.enter_context(patch.object(eve, "read_experiments", return_value=[]))
            stack.enter_context(patch.object(eve, "read_proposals", return_value=[]))
            stack.enter_context(patch.object(eve, "resolve_model", return_value="test-model"))
            stack.enter_context(patch.object(eve, "configured_model_host", return_value="http://127.0.0.1:9"))
            stack.enter_context(patch.object(eve, "llama_cpp_prompt_fallback_context_tokens", return_value=8192))
            stack.enter_context(patch.object(eve_prompt_budget, "measure_prompt", side_effect=fake_measure_prompt))
            stack.enter_context(patch.object(eve, "model_chat", side_effect=self.fake_model_chat))
            yield stack

    def test_read_lived_entries_reports_kinds_and_excluded_telemetry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            entries_path = Path(temp_dir) / "entries.jsonl"
            write_journal(entries_path, LIVED_ROWS, telemetry_count=60)
            with patch.object(eve, "ENTRIES_PATH", entries_path), patch.object(eve, "ensure_store"):
                lived, evidence = eve.read_lived_entries(limit=40, since_days=30)

        self.assertEqual(5, len(lived))
        self.assertEqual(
            {"action_executed": 1, "message": 1, "outcome_logged": 1, "reflection": 1, "thought": 1},
            evidence["lived_kinds"],
        )
        self.assertEqual(60, evidence["excluded_telemetry"])
        self.assertFalse(set(entry["kind"] for entry in lived) & set(eve.TELEMETRY_ENTRY_KINDS))

    def test_reflection_prompt_contains_no_telemetry_and_metadata_reports_lived_kinds(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            entries_path = Path(temp_dir) / "entries.jsonl"
            write_journal(entries_path, LIVED_ROWS, telemetry_count=60)
            with self.model_patches(entries_path):
                result = eve.generate_reflection(self.config, days=30, context_limit=40, max_tokens=420)

        self.assertEqual("A reflection on lived days.", result["response"])
        self.assertEqual(5, result["source_entries"])
        self.assertEqual(1, len(self.captured))
        text = prompt_text(self.captured[0])
        self.assertEqual([], telemetry_markers_in(text))
        self.assertNotIn("telemetry row", text)
        for kind, lived_text in LIVED_ROWS:
            self.assertIn("[%s] %s" % (kind, lived_text), text)
        for message in self.captured[0]:
            self.assertNotIn(eve.PROMPT_OPTIONAL_PRIORITY_FIELD, message)

        evidence = result["evidence"]
        self.assertEqual(
            {"action_executed": 1, "message": 1, "outcome_logged": 1, "reflection": 1, "thought": 1},
            evidence["lived_kinds"],
        )
        self.assertEqual(60, evidence["excluded_telemetry"])
        self.assertGreater(evidence["prompt_tokens"], 0)
        self.assertLessEqual(evidence["prompt_tokens"], eve.LIVED_EVIDENCE_PROMPT_MAX_TOKENS)
        self.assertEqual(eve.LIVED_EVIDENCE_PROMPT_MAX_TOKENS, evidence["prompt_cap_tokens"])
        self.assertEqual("fit", evidence["prompt_fit_status"])

    def test_reflection_prompt_is_capped_at_the_lived_evidence_budget(self):
        long_rows = [("thought", ("lived thought %d " % index) * 120) for index in range(40)]
        with tempfile.TemporaryDirectory() as temp_dir:
            entries_path = Path(temp_dir) / "entries.jsonl"
            write_journal(entries_path, long_rows, telemetry_count=60)
            with self.model_patches(entries_path):
                result = eve.generate_reflection(self.config, days=30, context_limit=60, max_tokens=420)

        evidence = result["evidence"]
        self.assertEqual(40, result["source_entries"])
        self.assertGreater(evidence["prompt_tokens_before"], eve.LIVED_EVIDENCE_PROMPT_MAX_TOKENS)
        self.assertLessEqual(evidence["prompt_tokens"], eve.LIVED_EVIDENCE_PROMPT_MAX_TOKENS)
        self.assertEqual("trimmed", evidence["prompt_fit_status"])
        received = fake_measure_prompt("http://127.0.0.1:9", self.captured[0]).prompt_tokens
        self.assertLessEqual(received, eve.LIVED_EVIDENCE_PROMPT_MAX_TOKENS)
        text = prompt_text(self.captured[0])
        self.assertIn("[thought]", text)
        self.assertEqual([], telemetry_markers_in(text))

    def test_proposal_prompt_contains_no_telemetry_and_records_lived_kinds(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            entries_path = Path(temp_dir) / "entries.jsonl"
            write_journal(entries_path, LIVED_ROWS, telemetry_count=60)
            with self.model_patches(entries_path) as stack:
                append_entry = stack.enter_context(patch.object(eve, "append_entry"))
                stack.enter_context(patch.object(eve, "append_jsonl_record"))
                record = eve.suggest_proposal(self.config, source="manual", max_tokens=520)

        self.assertEqual("draft", record["status"])
        text = prompt_text(self.captured[0])
        self.assertEqual([], telemetry_markers_in(text))
        self.assertNotIn("telemetry row", text)
        self.assertIn("[thought] I keep circling the relay question", text)
        append_entry.assert_called_once()
        metadata = append_entry.call_args.kwargs["metadata"]
        self.assertEqual("proposal_drafted", append_entry.call_args.args[0])
        self.assertEqual(60, metadata["excluded_telemetry"])
        self.assertEqual(5, sum(metadata["lived_kinds"].values()))
        self.assertGreater(metadata["prompt_tokens"], 0)
        self.assertLessEqual(metadata["prompt_tokens"], eve.LIVED_EVIDENCE_PROMPT_MAX_TOKENS)

    def test_refresh_human_context_excludes_telemetry_kinds(self):
        calls = []

        def fake_read_entries(limit=None, since_days=None, kinds=None, exclude_kinds=None):
            calls.append({"limit": limit, "since_days": since_days, "kinds": kinds, "exclude_kinds": exclude_kinds})
            return []

        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(eve, "ensure_version_snapshot", return_value={}))
            stack.enter_context(patch.object(eve, "resolve_model", return_value="test-model"))
            stack.enter_context(patch.object(eve, "load_project_memory", return_value=""))
            stack.enter_context(patch.object(eve, "read_entries", side_effect=fake_read_entries))
            stack.enter_context(patch.object(eve, "read_entries_by_kind", return_value=[]))
            stack.enter_context(patch.object(eve, "read_thread_summaries", return_value=[]))
            stack.enter_context(patch.object(eve, "read_lived_messages", return_value=[]))
            stack.enter_context(patch.object(eve, "load_human_context", return_value={}))
            stack.enter_context(patch.object(eve, "load_state", return_value={}))
            stack.enter_context(patch.object(eve, "save_state"))
            model_chat = stack.enter_context(patch.object(eve, "model_chat"))
            with self.assertRaises(SystemExit):
                eve.refresh_human_context(self.config, source="manual", max_tokens=320)

        model_chat.assert_not_called()
        self.assertEqual(1, len(calls))
        excluded = set(calls[0]["exclude_kinds"] or [])
        self.assertTrue(set(eve.TELEMETRY_ENTRY_KINDS) <= excluded)
        self.assertIn("thought", excluded)
        self.assertEqual(int(self.config["reflection_days"]), calls[0]["since_days"])


if __name__ == "__main__":
    unittest.main()
