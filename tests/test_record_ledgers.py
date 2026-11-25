import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import eve_commitments
import eve_evidence
import eve_experience
import eve_store


class RecordLedgerContractTests(unittest.TestCase):
    def test_shared_text_contract_is_consistent_across_ledgers(self):
        value = "  Eve\n  keeps   one   voice  "

        for module in (eve_commitments, eve_evidence, eve_experience):
            with self.subTest(module=module.__name__):
                self.assertEqual("Eve keeps one voice", module.normalize_text(value))
                self.assertEqual("ab...", module.normalize_text("abcdef", limit=5))
                self.assertEqual(
                    ["Fast", "Observer"],
                    module.normalize_text_list([" Fast ", "fast", "Observer"], limit=2),
                )

    def test_unfiltered_bounded_reads_use_the_tail_path(self):
        cases = (
            (
                eve_commitments.read_commitment_records,
                {"created_at": "2026-01-01T00:00:00+00:00", "text": "older"},
            ),
            (
                eve_evidence.read_evidence_records,
                {"observed_at": "2026-01-01T00:00:00+00:00", "claim": "older"},
            ),
            (
                eve_experience.read_experience_events,
                {"timestamp": "2026-01-01T00:00:00+00:00", "summary": "older"},
            ),
        )

        for reader, record in cases:
            with self.subTest(reader=reader.__name__), patch.object(
                eve_store, "read_jsonl_tail_records", return_value=[record]
            ) as read_tail, patch.object(
                eve_store, "read_jsonl_records", side_effect=AssertionError("full scan used")
            ):
                result = reader(Path("unused.jsonl"), limit=1)

            self.assertEqual(1, len(result))
            read_tail.assert_called_once_with(Path("unused.jsonl"), 1)

    def test_filtered_reads_scan_then_filter_and_sort_newest_first(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            commitments_path = root / "commitments.jsonl"
            eve_store.write_jsonl_records(
                commitments_path,
                [
                    {
                        "id": "c-old",
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "source": "chat",
                        "status": "completed",
                        "text": "old",
                    },
                    {
                        "id": "c-new",
                        "created_at": "2026-01-02T00:00:00+00:00",
                        "source": "chat",
                        "status": "completed",
                        "text": "new",
                    },
                    {
                        "id": "c-other",
                        "created_at": "2026-01-03T00:00:00+00:00",
                        "source": "daemon",
                        "status": "completed",
                        "text": "other",
                    },
                ],
            )
            commitments = eve_commitments.read_commitment_records(
                commitments_path, limit=2, status="completed", source="chat"
            )
            self.assertEqual(["c-new", "c-old"], [item["id"] for item in commitments])

            evidence_path = root / "evidence.jsonl"
            eve_store.write_jsonl_records(
                evidence_path,
                [
                    {
                        "id": "e-old",
                        "observed_at": "2026-01-01T00:00:00+00:00",
                        "source": "sensor",
                        "kind": "runtime",
                        "claim": "old",
                    },
                    {
                        "id": "e-new",
                        "observed_at": "2026-01-02T00:00:00+00:00",
                        "source": "sensor",
                        "kind": "runtime",
                        "claim": "new",
                    },
                    {
                        "id": "e-other",
                        "observed_at": "2026-01-03T00:00:00+00:00",
                        "source": "sensor",
                        "kind": "relationship",
                        "claim": "other",
                    },
                ],
            )
            evidence = eve_evidence.read_evidence_records(
                evidence_path, limit=2, source="sensor", kind="runtime"
            )
            self.assertEqual(["e-new", "e-old"], [item["id"] for item in evidence])

            experience_path = root / "experience.jsonl"
            eve_store.write_jsonl_records(
                experience_path,
                [
                    {
                        "id": "x-old",
                        "timestamp": "2026-01-01T00:00:00+00:00",
                        "source": "chat",
                        "event_type": "user_signal",
                        "summary": "old",
                    },
                    {
                        "id": "x-new",
                        "timestamp": "2026-01-02T00:00:00+00:00",
                        "source": "chat",
                        "event_type": "user_signal",
                        "summary": "new",
                    },
                    {
                        "id": "x-other",
                        "timestamp": "2026-01-03T00:00:00+00:00",
                        "source": "daemon",
                        "event_type": "user_signal",
                        "summary": "other",
                    },
                ],
            )
            experience = eve_experience.read_experience_events(
                experience_path, limit=2, event_type="user_signal", source="chat"
            )
            self.assertEqual(["x-new", "x-old"], [item["id"] for item in experience])

    def test_append_paths_persist_the_normalized_public_schema(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            commitment = eve_commitments.append_commitment_record(
                root / "commitments.jsonl", {"status": "not-valid", "text": "  keep   going "}
            )
            evidence = eve_evidence.append_evidence_record(
                root / "evidence.jsonl", {"status": "not-valid", "claim": "  observed   state "}
            )
            experience = eve_experience.append_experience_event(
                root / "experience.jsonl", {"event_type": "not-valid", "summary": "  lived   event "}
            )

            self.assertEqual(("proposed", "keep going"), (commitment["status"], commitment["text"]))
            self.assertEqual(("active", "observed state"), (evidence["status"], evidence["claim"]))
            self.assertEqual(("percept", "lived event"), (experience["event_type"], experience["summary"]))


if __name__ == "__main__":
    unittest.main()
