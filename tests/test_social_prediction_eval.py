import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "eve_social_prediction_eval",
    ROOT / "bin" / "eve_social_prediction_eval.py",
)
assert SPEC and SPEC.loader
evaluator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluator)


def private_spec():
    return {
        "schema_version": evaluator.SPEC_SCHEMA,
        "frozen_at": "2026-08-23T20:00:00+00:00",
        "minimum_mean_brier_improvement": 0.05,
        "cases": [
            {
                "reply_text": "What changed after the restart?",
                "inbound_text": "Help me diagnose this.",
                "observed_text": "The gateway recovered.",
                "expected_observed_class": "answer",
            },
            {
                "reply_text": "I completed the bounded change.",
                "observed_text": "Great, thank you.",
                "explicit_acceptance": True,
                "expected_observed_class": "acceptance",
            },
            {
                "reply_text": "I completed the requested change.",
                "observed_text": "No, that is not what I asked.",
                "explicit_correction": True,
                "expected_observed_class": "correction",
            },
            {
                "reply_text": "Here is the verified result.",
                "observed_text": "Keep going with the next item.",
                "expected_observed_class": "continuation",
            },
            {
                "reply_text": "The evidence supports that conclusion.",
                "observed_text": "Why does that follow?",
                "expected_observed_class": "follow_up_question",
            },
            {
                "reply_text": "That closes this task. Anything else?",
                "observed_text": "New question: which model is live?",
                "expected_observed_class": "topic_shift",
            },
        ],
    }


class ObservableSocialPredictionEvaluatorTests(unittest.TestCase):
    def test_matched_intervention_is_aggregate_and_text_free(self):
        result = evaluator.run(private_spec())

        self.assertTrue(result["passed"], result)
        self.assertEqual(6, result["cases_passed"])
        self.assertGreaterEqual(result["mean_brier_improvement"], 0.05)
        self.assertEqual(6, result["feedback_evidence_count"])
        self.assertEqual(0, result["feedback_lesion_evidence_count"])
        self.assertFalse(result["privacy"]["private_fixture_text_retained"])
        self.assertNotIn("The gateway recovered", str(result))

    def test_requires_enough_cases(self):
        spec = private_spec()
        spec["cases"] = spec["cases"][:5]

        with self.assertRaisesRegex(ValueError, "at least six"):
            evaluator.run(spec)


if __name__ == "__main__":
    unittest.main()
