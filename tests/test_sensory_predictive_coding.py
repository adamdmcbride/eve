import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import eve_sensory


ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-08-23T18:30:00+00:00"


def visual(features, observed_at=NOW, *, precision=100):
    return eve_sensory.normalize_adapter_event(
        {
            "modality": "visual",
            "permission_granted": True,
            "observed_at": observed_at,
            "features": features,
            "precision": precision,
        },
        allowed_modalities=["visual"],
        session_id="predictive-perception-test",
        now=observed_at,
    )


def run_motion(values, *, enabled=True, precision=100):
    frame = {}
    for index, value in enumerate(values):
        observed_at = f"2026-08-23T18:30:{index * 10:02d}+00:00"
        frame = eve_sensory.build_frame(
            [
                visual(
                    {"motion_percent": value, "scene_state": "movement"},
                    observed_at,
                    precision=precision,
                )
            ],
            prior_frame=frame,
            now=observed_at,
            predictive_coding_enabled=enabled,
        )
    return frame


class SensoryPredictiveCodingTests(unittest.TestCase):
    def test_next_feature_projection_is_sparse_clipped_and_categorical(self):
        prediction = eve_sensory.predict_next_features(
            {
                "feature_modality": "visual",
                "motion_percent": 70,
                "scene_state": "movement",
            },
            {
                "feature_modality": "visual",
                "motion_percent": 45,
                "scene_state": "stable",
            },
        )

        self.assertEqual(95.0, prediction["motion_percent"])
        self.assertEqual("movement", prediction["scene_state"])
        clipped = eve_sensory.predict_next_features(
            {"feature_modality": "visual", "motion_percent": 95},
            {"feature_modality": "visual", "motion_percent": 70},
        )
        self.assertEqual(100.0, clipped["motion_percent"])

    def test_expected_linear_change_is_suppressed_but_lesion_calls_it_novel(self):
        intact = run_motion([10, 20, 30], enabled=True)
        lesioned = run_motion([10, 20, 30], enabled=False)

        self.assertFalse(intact["winner"]["dishabituated"])
        self.assertTrue(intact["winner"]["predicted_change"])
        self.assertEqual(0.0, intact["winner"]["prediction_error"]["weighted_error"])
        self.assertTrue(lesioned["winner"]["dishabituated"])

    def test_unexpected_value_and_omitted_change_produce_prediction_error(self):
        violation = run_motion([10, 20, 55], enabled=True)
        omission = run_motion([10, 20, 20], enabled=True)

        self.assertTrue(violation["winner"]["dishabituated"])
        self.assertTrue(violation["winner"]["prediction_violation"])
        self.assertEqual(25.0, violation["winner"]["prediction_error"]["weighted_error"])
        self.assertTrue(omission["winner"]["dishabituated"])
        self.assertEqual(10.0, omission["winner"]["prediction_error"]["weighted_error"])
        self.assertEqual(0.0, omission["winner"]["quality_distance"]["maximum_distance"])

    def test_prediction_error_is_precision_weighted(self):
        high = eve_sensory.feature_prediction_error(
            {"feature_modality": "visual", "motion_percent": 40},
            {"feature_modality": "visual", "motion_percent": 20},
            precision=100,
        )
        low = eve_sensory.feature_prediction_error(
            {"feature_modality": "visual", "motion_percent": 40},
            {"feature_modality": "visual", "motion_percent": 20},
            precision=20,
        )

        self.assertTrue(high["surprising"])
        self.assertFalse(low["surprising"])
        self.assertEqual(20.0, high["weighted_error"])
        self.assertEqual(4.0, low["weighted_error"])

    def test_public_frame_keeps_only_feature_predictions_and_honest_boundary(self):
        frame = run_motion([10, 20, 30], enabled=True)
        public = eve_sensory.public_frame(frame)

        self.assertEqual(
            eve_sensory.PREDICTIVE_PERCEPTION_SCHEMA,
            public["predictive_perception"]["schema_version"],
        )
        self.assertEqual(1, public["predictive_perception"]["expected_change_suppressed_count"])
        self.assertIn("not a claim", public["predictive_perception"]["boundary"])
        self.assertEqual([], eve_sensory.forbidden_ingest_paths(public))

    def test_repeatable_cli_evaluation_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "predictive-perception.json"
            evidence = Path(tmp) / "evidence.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "bin" / "eve_predictive_perception_eval.py"),
                    "--output",
                    str(output),
                    "--evidence-output",
                    str(evidence),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("passed", payload["status"])
            self.assertEqual(100.0, payload["intact_accuracy_percent"])
            self.assertGreaterEqual(payload["directional_effect"], 20.0)
            self.assertEqual(12, len(json.loads(evidence.read_text(encoding="utf-8"))))


if __name__ == "__main__":
    unittest.main()
