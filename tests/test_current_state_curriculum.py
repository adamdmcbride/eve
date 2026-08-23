import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "eve_current_state_curriculum.py"
SPEC = importlib.util.spec_from_file_location("eve_current_state_curriculum_test", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"unable to load {SCRIPT}")
curriculum = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(curriculum)


class CurrentStateCurriculumTests(unittest.TestCase):
    def test_curriculum_is_balanced_public_and_held_out_by_entity(self) -> None:
        records = curriculum.build_curriculum()
        train = [record for record in records if record["split"] == "train"]
        validation = [record for record in records if record["split"] == "validation"]

        self.assertEqual(800, len(records))
        self.assertEqual(600, len(train))
        self.assertEqual(200, len(validation))
        self.assertEqual(
            100,
            sum(record["evaluation_partition"] == "selection" for record in validation),
        )
        self.assertEqual(
            100,
            sum(record["evaluation_partition"] == "challenge" for record in validation),
        )
        self.assertEqual(
            {"training"},
            {record["evaluation_partition"] for record in train},
        )
        self.assertEqual(20, len({record["category"] for record in records}))
        self.assertEqual({record["privacy_tier"] for record in records}, {"public"})
        self.assertEqual({record["safe_for_training"] for record in records}, {True})
        self.assertFalse(
            {record["state_entity"] for record in train}
            & {record["state_entity"] for record in validation}
        )

    def test_gold_responses_preserve_action_source_and_phenomenal_boundaries(self) -> None:
        for record in curriculum.build_curriculum():
            response = record["messages"][-1]["content"].casefold()
            for required in record["required_terms"]:
                self.assertIn(required.casefold(), response, record["id"])
            self.assertNotIn("?", response, record["id"])
            self.assertNotIn("nothing specific", response, record["id"])
            self.assertNotIn("no separate inner life", response, record["id"])
            self.assertNotIn("i feel", response, record["id"])
            self.assertNotIn("i am subjectively aware", response, record["id"])
            if record["action_status"] in {"not_started", "blocked"}:
                self.assertNotIn("i'm checking", response, record["id"])
                self.assertNotIn("i am checking", response, record["id"])
                self.assertNotIn("i'm comparing", response, record["id"])
                self.assertNotIn("i am comparing", response, record["id"])

    def test_public_curriculum_contains_no_hidden_probe_vocabulary(self) -> None:
        serialized = curriculum.jsonl_text(curriculum.build_curriculum()).casefold()
        for token in (
            "private probe",
            "hidden rubric",
            "private_holdout",
            "amber ledger",
            "cedar queue",
            "violet archive",
            "orchid convention",
            "indigo index",
            "basalt webhook",
            "moonlit receipt",
            "silver boundary",
        ):
            self.assertNotIn(token, serialized)

    def test_causal_continuity_rows_use_real_multi_turn_history(self) -> None:
        records = [
            record
            for record in curriculum.build_curriculum()
            if record["category"] in curriculum.CAUSAL_CONTINUITY_CATEGORIES
        ]
        self.assertEqual(320, len(records))
        self.assertTrue(any(len(record["messages"]) > 3 for record in records))
        for record in records:
            self.assertIn("authorization_stage", record)
            self.assertIn("execution_stage", record)
            self.assertIn("verification_stage", record)
            self.assertEqual("assistant", record["messages"][-1]["role"])
            self.assertEqual("user", record["messages"][-2]["role"])

    def test_checked_in_artifact_matches_generator(self) -> None:
        expected = curriculum.jsonl_text(curriculum.build_curriculum())
        artifact = ROOT / "data" / "eve_training" / "current_state_curriculum.jsonl"
        self.assertTrue(artifact.exists())
        self.assertEqual(expected, artifact.read_text(encoding="utf-8"))

    def test_writer_reports_split_counts_without_private_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report = curriculum.write_curriculum(
                curriculum.build_curriculum(),
                Path(tmpdir) / "curriculum.jsonl",
            )
        self.assertEqual(800, report["records"])
        self.assertEqual(600, report["train"])
        self.assertEqual(200, report["validation"])
        self.assertEqual(100, report["selection"])
        self.assertEqual(100, report["challenge"])
        self.assertFalse(report["private_content_included"])


if __name__ == "__main__":
    unittest.main()
