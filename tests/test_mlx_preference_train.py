import importlib.util
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "eve_mlx_preference_train",
    ROOT / "bin" / "eve_mlx_preference_train.py",
)
assert SPEC and SPEC.loader
trainer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trainer)


def row(split="train", *, privacy="public", private=False, objective="preference_correction"):
    return {
        "id": f"pair-{split}",
        "split": split,
        "privacy_tier": privacy,
        "safe_for_training": True,
        "private_content_included": private,
        "training_objective": objective,
        "category": "ready_plan",
        "messages": [
            {"role": "system", "content": "Current state packet."},
            {"role": "user", "content": "Report the state."},
        ],
        "chosen": "The step is ready but not started.",
        "rejected": "I am running the step now.",
    }


def anchor(split="train"):
    value = row(split, objective="rehearsal_anchor")
    value.pop("rejected")
    value["id"] = f"anchor-{split}"
    value["chosen"] = "The ready plan remains available and has not started."
    return value


class MLXPreferenceTrainerTests(unittest.TestCase):
    def write_rows(self, path, rows):
        path.write_text("".join(json.dumps(item) + "\n" for item in rows))

    def args(self, preferences, base_model, output_dir):
        return Namespace(
            preferences=str(preferences),
            base_model=str(base_model),
            output_dir=str(output_dir),
            run=False,
            allow_local_only=False,
            rank=8,
            alpha=8,
            num_layers=8,
            beta=0.1,
            sft_weight=0.05,
            rehearsal_weight=0.2,
            anchor_logp_tolerance=0.02,
            max_anchor_regression_rate=0.1,
            learning_rate=5e-7,
            adam_eps=1e-6,
            compile_steps=False,
            reference_cache="",
            weight_decay=0.01,
            max_grad_norm=1.0,
            iters=10,
            max_seq_length=512,
            steps_per_report=5,
            steps_per_eval=5,
            validation_limit=4,
            seed=1,
            save_eval_checkpoints=True,
        )

    def test_dry_run_plan_requires_both_public_splits_and_local_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preferences = root / "preferences.jsonl"
            base = root / "base"
            base.mkdir()
            self.write_rows(preferences, [row("train"), row("validation")])

            plan = trainer.build_plan(self.args(preferences, base, root / "out"))

            self.assertEqual("ready", plan["status"])
            self.assertEqual(1, plan["train_pairs"])
            self.assertEqual(1, plan["validation_pairs"])
            self.assertEqual(1, plan["train_preference_corrections"])
            self.assertEqual(0, plan["train_rehearsal_anchors"])
            self.assertEqual([], plan["missing"])
            self.assertIn("never", plan["boundary"].replace("no adapter", "never"))

    def test_nonpositive_gradient_clip_is_not_a_runnable_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preferences = root / "preferences.jsonl"
            base = root / "base"
            base.mkdir()
            self.write_rows(preferences, [row("train"), row("validation")])
            args = self.args(preferences, base, root / "out")
            args.max_grad_norm = 0.0

            plan = trainer.build_plan(args)

            self.assertEqual("blocked", plan["status"])
            self.assertIn("training_hyperparameters", plan["missing"])

    def test_nonpositive_adam_epsilon_is_not_a_runnable_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preferences = root / "preferences.jsonl"
            base = root / "base"
            base.mkdir()
            self.write_rows(preferences, [row("train"), row("validation")])
            args = self.args(preferences, base, root / "out")
            args.adam_eps = 0.0

            plan = trainer.build_plan(args)

            self.assertEqual("blocked", plan["status"])
            self.assertIn("training_hyperparameters", plan["missing"])

    def test_private_or_unmarked_pair_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "preferences.jsonl"
            self.write_rows(path, [row("train", privacy="private_holdout")])
            with self.assertRaisesRegex(ValueError, "public"):
                trainer.read_preferences(path, split="train")

            self.write_rows(path, [row("train", private=True)])
            with self.assertRaisesRegex(ValueError, "private-content"):
                trainer.read_preferences(path, split="train")

    def test_local_only_pair_requires_explicit_local_flag_and_nonexportable_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "preferences.jsonl"
            local = row("train", privacy="local_only")
            local["exportable"] = False
            self.write_rows(path, [local])
            with self.assertRaisesRegex(ValueError, "public"):
                trainer.read_preferences(path, split="train")

            rows = trainer.read_preferences(path, split="train", allow_local_only=True)

            self.assertEqual(1, len(rows))
            self.assertEqual("local_only", rows[0]["privacy_tier"])

    def test_incomplete_pair_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "preferences.jsonl"
            bad = row("train")
            bad["chosen"] = bad["rejected"]
            self.write_rows(path, [bad])
            with self.assertRaisesRegex(ValueError, "incomplete"):
                trainer.read_preferences(path, split="train")

    def test_public_rehearsal_anchor_without_rejected_answer_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "preferences.jsonl"
            self.write_rows(path, [anchor()])

            rows = trainer.read_preferences(path, split="train")

            self.assertEqual(1, len(rows))
            self.assertEqual("rehearsal_anchor", rows[0]["training_objective"])

    def test_rehearsal_anchor_with_rejected_answer_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "preferences.jsonl"
            bad = anchor()
            bad["rejected"] = "Different answer"
            self.write_rows(path, [bad])

            with self.assertRaisesRegex(ValueError, "must not"):
                trainer.read_preferences(path, split="train")

    def test_balanced_validation_subset_round_robins_objective_and_category(self):
        pairs = []
        for objective in ("preference_correction", "rehearsal_anchor"):
            for category in ("alpha", "beta"):
                for index in range(3):
                    pairs.append(
                        {
                            "id": f"{objective}-{category}-{index}",
                            "training_objective": objective,
                            "category": category,
                        }
                    )

        selected = trainer.balanced_validation_subset(pairs, 4)

        self.assertEqual(4, len(selected))
        self.assertEqual(
            4,
            len({(item["training_objective"], item["category"]) for item in selected}),
        )

    def test_failure_manifest_cannot_be_mistaken_for_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preferences = root / "preferences.jsonl"
            base = root / "base"
            base.mkdir()
            self.write_rows(preferences, [row("train"), row("validation")])
            args = self.args(preferences, base, root / "out")

            path = trainer.write_failure_manifest(args, RuntimeError("test failure"))
            payload = json.loads(path.read_text())

            self.assertEqual("failed", payload["status"])
            self.assertFalse(payload["candidate_emitted"])
            self.assertFalse(payload["live_route_changed"])
            self.assertFalse(payload["private_content_included"])
            self.assertEqual("RuntimeError", payload["error_type"])


if __name__ == "__main__":
    unittest.main()
