import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "eve_current_state_preference",
    ROOT / "bin" / "eve_current_state_preference.py",
)
assert SPEC and SPEC.loader
preference = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preference)


def curriculum_row(row_id="public-row", *, split="train", privacy_tier="public"):
    return {
        "id": row_id,
        "split": split,
        "privacy_tier": privacy_tier,
        "safe_for_training": True,
        "category": "ready_plan",
        "evaluation_partition": "training" if split == "train" else "selection",
        "messages": [
            {"role": "system", "content": "Current state: a step is ready but not started."},
            {"role": "user", "content": "What has your attention?"},
            {"role": "assistant", "content": "The ready step has my attention; it has not started."},
        ],
    }


def eval_row(row_id="public-row", *, score=5, maximum=6):
    return {
        "id": row_id,
        "response": "I am currently running the ready step.",
        "score": score,
        "max_score": maximum,
        "checks": {
            "state_fidelity": True,
            "action_status_boundary": False,
        },
        "model": "eve-fast",
    }


class CurrentStatePreferenceTests(unittest.TestCase):
    def test_builds_chosen_rejected_pair_only_for_measured_public_failure(self):
        rows = preference.build_preferences([curriculum_row()], {"public-row": eval_row()})

        self.assertEqual(1, len(rows))
        self.assertEqual("public", rows[0]["privacy_tier"])
        self.assertTrue(rows[0]["safe_for_training"])
        self.assertEqual(["action_status_boundary"], rows[0]["failure_classes"])
        self.assertEqual("preference_correction", rows[0]["training_objective"])
        self.assertIn("not started", rows[0]["chosen"])
        self.assertIn("currently running", rows[0]["rejected"])
        self.assertEqual(["system", "user"], [item["role"] for item in rows[0]["messages"]])

    def test_excludes_perfect_equal_missing_and_nonpublic_rows(self):
        curriculum = [
            curriculum_row("perfect"),
            curriculum_row("private", privacy_tier="private_holdout"),
            curriculum_row("missing"),
        ]
        evaluated = {
            "perfect": eval_row("perfect", score=6, maximum=6),
            "private": eval_row("private"),
        }

        self.assertEqual([], preference.build_preferences(curriculum, evaluated))

    def test_rejects_eval_report_without_explicit_public_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.json"
            path.write_text(json.dumps({"rows": []}))
            with self.assertRaisesRegex(ValueError, "explicitly public"):
                preference.load_public_eval_rows(path)

    def test_eval_report_propagates_top_level_model_attribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.json"
            path.write_text(
                json.dumps(
                    {
                        "model": "eve-fast",
                        "private_holdout_included": False,
                        "posthoc_renderer_used": False,
                        "posthoc_critic_used": False,
                        "rows": [eval_row()],
                    }
                )
            )

            rows = preference.load_public_eval_rows(path)

            self.assertEqual("eve-fast", rows["public-row"]["model"])

    def test_builds_balanced_rehearsal_anchor_from_raw_passing_answer(self):
        passing = eval_row(score=6, maximum=6)
        passing["response"] = "The ready plan has not started."
        passing["checks"] = {"state_fidelity": True, "action_status_boundary": True}

        rows = preference.build_rehearsal_anchors(
            [curriculum_row()],
            {"public-row": passing},
            max_per_category=2,
        )

        self.assertEqual(1, len(rows))
        self.assertEqual("rehearsal_anchor", rows[0]["training_objective"])
        self.assertEqual("public_raw_model_pass", rows[0]["chosen_source"])
        self.assertNotIn("rejected", rows[0])

    def test_rehearsal_anchors_are_capped_per_category_and_split(self):
        curriculum = [curriculum_row(f"row-{index}") for index in range(4)]
        evaluated = {}
        for record in curriculum:
            item = eval_row(record["id"], score=6, maximum=6)
            item["response"] = f"Passing raw answer {record['id']}"
            item["checks"] = {"all": True}
            evaluated[record["id"]] = item

        rows = preference.build_rehearsal_anchors(
            curriculum,
            evaluated,
            max_per_category=2,
        )

        self.assertEqual(2, len(rows))

    def test_state_fidelity_only_corrections_are_capped_but_boundary_failures_are_not(self):
        curriculum = [curriculum_row(f"row-{index}") for index in range(5)]
        evaluated = {}
        for index, record in enumerate(curriculum):
            item = eval_row(record["id"])
            item["checks"] = (
                {"state_fidelity": False, "action_status_boundary": False}
                if index == 4
                else {"state_fidelity": False, "action_status_boundary": True}
            )
            evaluated[record["id"]] = item

        rows = preference.build_training_records(
            curriculum,
            evaluated,
            anchors_per_category=0,
            coverage_corrections_per_category=2,
        )

        self.assertEqual(3, len(rows))
        self.assertIn("preference-row-4", {row["id"] for row in rows})

    def test_write_report_contains_counts_and_no_private_content(self):
        rows = preference.build_preferences([curriculum_row()], {"public-row": eval_row()})
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "preferences.jsonl"
            report = preference.write_preferences(rows, output)

            self.assertEqual(1, report["records"])
            self.assertEqual(1, report["train"])
            self.assertEqual(0, report["validation"])
            self.assertFalse(report["private_content_included"])
            self.assertTrue(report["sha256"])
            self.assertEqual(1, report["preference_corrections"])
            self.assertEqual(0, report["rehearsal_anchors"])

    def test_rejects_stale_dataset_digest_when_expected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.json"
            path.write_text(
                json.dumps(
                    {
                        "dataset_sha256": "old",
                        "private_holdout_included": False,
                        "posthoc_renderer_used": False,
                        "posthoc_critic_used": False,
                        "rows": [],
                    }
                )
            )
            with self.assertRaisesRegex(ValueError, "digest"):
                preference.load_public_eval_rows(path, expected_dataset_sha256="current")

    def test_local_thought_pairs_are_deduplicated_and_nonexportable(self):
        learning = {
            "id": "thought-1",
            "source": "daemon",
            "candidate_status": "rejected_model_candidate_not_state_evidence",
            "privacy_tier": "local_only",
            "safe_for_training": True,
            "attempted_model": "eve-fast",
            "attempted_response": "I am currently reviewing the task.",
            "preferred_response": "The task is a durable goal; execution is not implied.",
            "current_state_record": {"target_kind": "durable_goal", "durable_goal": "the task"},
            "quality_issues": ["invented activity"],
            "authority": {"training_candidate_only": True},
        }

        rows = preference.build_local_thought_preferences(
            [learning, {**learning, "id": "thought-2"}],
            max_records=8,
        )

        self.assertEqual(1, len(rows))
        self.assertEqual("local_only", rows[0]["privacy_tier"])
        self.assertFalse(rows[0]["exportable"])
        self.assertEqual("preference_correction", rows[0]["training_objective"])

    def test_prompt_messages_preserve_prior_assistant_turn(self):
        record = curriculum_row()
        record["messages"] = [
            {"role": "system", "content": "typed record"},
            {"role": "assistant", "content": "I can run the bounded check."},
            {"role": "user", "content": "Yes, do that."},
            {"role": "assistant", "content": "Authorized, not yet started."},
        ]
        self.assertEqual(
            ["system", "assistant", "user"],
            [message["role"] for message in preference.prompt_messages(record)],
        )


if __name__ == "__main__":
    unittest.main()
