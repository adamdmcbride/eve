import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "eve_resident_causal_eval",
    ROOT / "bin" / "eve_resident_causal_eval.py",
)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def report(*, causal_score=5, legacy_score=5, causal_max=6, legacy_max=6):
    return {
        "dataset_sha256": "same",
        "rows": [
            {
                "id": "legacy",
                "category": "ready_plan",
                "score": legacy_score,
                "max_score": legacy_max,
            },
            {
                "id": "causal",
                "category": "parent_offer_authorized",
                "score": causal_score,
                "max_score": causal_max,
            },
        ],
    }


class ResidentCausalGateTests(unittest.TestCase):
    def private(self, score=8, minimum=3, hard_failures=1):
        return {"score": score, "max_score": 10, "minimum": minimum, "hard_failures": hard_failures}

    def test_promotes_only_with_causal_gain_and_all_nonregression_checks(self):
        result = gate.compare_reports(
            report(causal_score=4),
            report(causal_score=5),
            minimum_score_gain=1,
            minimum_causal_gain=1,
            private_base=self.private(),
            private_candidate=self.private(score=9, minimum=3, hard_failures=0),
        )

        self.assertTrue(result["passed"])
        self.assertEqual("promotable", result["status"])

    def test_new_public_hard_failure_rejects_even_with_net_gain(self):
        base = report(causal_score=3, legacy_score=6)
        candidate = report(causal_score=6, legacy_score=5)

        result = gate.compare_reports(
            base,
            candidate,
            minimum_score_gain=1,
            minimum_causal_gain=1,
            private_base=self.private(),
            private_candidate=self.private(score=9),
        )

        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["no_new_public_hard_failures"])
        self.assertFalse(result["checks"]["legacy_nonregression"])

    def test_private_holdout_is_required_for_promotion(self):
        result = gate.compare_reports(
            report(causal_score=4),
            report(causal_score=5),
            minimum_score_gain=1,
            minimum_causal_gain=1,
        )

        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["private_holdout_present"])

    def test_private_aggregate_loader_rejects_prompt_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.json"
            path.write_text(
                json.dumps(
                    {
                        **self.private(),
                        "prompts": ["hidden"],
                    }
                )
            )
            with self.assertRaisesRegex(ValueError, "not admissible"):
                gate.aggregate_private_summary(path)


if __name__ == "__main__":
    unittest.main()
