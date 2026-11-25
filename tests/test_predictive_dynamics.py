import json
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

import eve_predictive_dynamics as dynamics


ROOT = Path(__file__).resolve().parents[1]
EVAL_PATH = ROOT / "bin" / "eve_predictive_dynamics_eval.py"
SPEC = importlib.util.spec_from_file_location("eve_predictive_dynamics_eval", EVAL_PATH)
assert SPEC and SPEC.loader
evaluator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluator)


def small_manifest():
    material = {
        "schema_version": evaluator.MANIFEST_SCHEMA,
        "seed": 1,
        "feature_limit": 100,
        "error_threshold": 8,
        "frozen_before_evidence": True,
        "scenarios": [
            {
                "id": "periodic-expected",
                "kind": "numeric",
                "history": [20, 60, 20, 60, 20],
                "actual": 60,
                "source_precision": 100,
                "expected_surprise": False,
            },
            {
                "id": "periodic-break",
                "kind": "numeric",
                "history": [20, 60, 20, 60, 20],
                "actual": 20,
                "source_precision": 100,
                "expected_surprise": True,
            },
        ],
    }
    digest = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {**material, "manifest_digest": digest}


class PredictiveDynamicsTests(unittest.TestCase):
    def test_selects_velocity_for_a_linear_history(self):
        forecast = dynamics.forecast_numeric([10, 20, 30, 40], limit=100)

        self.assertEqual("velocity", forecast["selected_expert"])
        self.assertEqual(50.0, forecast["prediction"])
        self.assertGreater(forecast["forecast_precision"], 80)

    def test_selects_acceleration_from_prospective_errors(self):
        forecast = dynamics.forecast_numeric([0, 1, 11, 30, 58], limit=100)

        self.assertEqual("acceleration", forecast["selected_expert"])
        self.assertEqual(95.0, forecast["prediction"])
        self.assertFalse(dynamics.evaluate_observation(95, forecast)["surprising"])

    def test_selects_period_two_only_after_identifiable_history(self):
        forecast = dynamics.forecast_numeric([20, 60, 20, 60, 20], limit=100)

        self.assertEqual("period_2", forecast["selected_expert"])
        self.assertEqual(60.0, forecast["prediction"])
        self.assertFalse(dynamics.evaluate_observation(60, forecast)["surprising"])
        self.assertTrue(dynamics.evaluate_observation(20, forecast)["surprising"])

    def test_stable_history_prefers_simpler_persistence(self):
        forecast = dynamics.forecast_numeric([40, 40, 40, 40], limit=100)

        self.assertEqual("persistence", forecast["selected_expert"])
        self.assertEqual(40.0, forecast["prediction"])

    def test_source_and_model_uncertainty_bound_prediction_error(self):
        high = dynamics.forecast_numeric([10, 20, 30, 40], limit=100, source_precision=100)
        low = dynamics.forecast_numeric([10, 20, 30, 40], limit=100, source_precision=10)

        self.assertTrue(dynamics.evaluate_observation(80, high)["surprising"])
        self.assertFalse(dynamics.evaluate_observation(80, low)["surprising"])
        self.assertEqual(10.0, low["forecast_precision"])

    def test_categorical_periodicity_and_persistence_are_bounded(self):
        alternating = dynamics.forecast_feature_history(["a", "b", "a", "b"])
        stable = dynamics.forecast_feature_history(["quiet", "quiet", "quiet"])
        lesion = dynamics.forecast_categorical(
            ["a", "b", "a", "b"], periodic_enabled=False
        )

        self.assertEqual("period_2", alternating["selected_expert"])
        self.assertEqual("a", alternating["prediction"])
        self.assertEqual("persistence", stable["selected_expert"])
        self.assertEqual("persistence", lesion["selected_expert"])
        self.assertFalse(dynamics.evaluate_observation("quiet", stable)["surprising"])

    def test_invalid_or_raw_shaped_histories_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "at least two"):
            dynamics.forecast_numeric([1], limit=100)
        with self.assertRaisesRegex(ValueError, "finite"):
            dynamics.forecast_numeric([1, float("nan")], limit=100)
        with self.assertRaisesRegex(ValueError, "exceeds"):
            dynamics.forecast_numeric([1, 101], limit=100)
        with self.assertRaisesRegex(ValueError, "bounded"):
            dynamics.forecast_categorical(["a" * 65, "b"])
        with self.assertRaisesRegex(ValueError, "mix"):
            dynamics.forecast_categorical([True, "true"])
        with self.assertRaisesRegex(ValueError, "finite"):
            dynamics.forecast_numeric([1, 2], limit=100, source_precision=float("inf"))

    def test_forecast_is_json_safe_and_has_no_action_authority(self):
        forecast = dynamics.forecast_numeric([10, 20, 30, 40], limit=100)
        rendered = json.dumps(forecast, sort_keys=True)

        self.assertIn(dynamics.SCHEMA, rendered)
        self.assertFalse(forecast["raw_media_retained"])
        self.assertFalse(forecast["action_authority"])
        self.assertIn("not a claim", forecast["boundary"])

    def test_holdout_manifest_is_digest_locked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            payload = small_manifest()
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(payload["manifest_digest"], evaluator.load_manifest(path)["manifest_digest"])
            payload["scenarios"][0]["actual"] = 99
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                evaluator.load_manifest(path)

    def test_holdout_evaluator_causally_separates_multi_hypothesis_selection(self):
        report = evaluator.run_evaluation(
            small_manifest(), evaluated_at="2026-08-23T20:00:00+00:00"
        )

        self.assertEqual(100.0, report["intact_accuracy_percent"])
        self.assertEqual(0.0, report["lesion_accuracy_percent"])
        self.assertEqual([], report["intact_failure_ids"])
        self.assertFalse(report["consciousness_proven"])


if __name__ == "__main__":
    unittest.main()
