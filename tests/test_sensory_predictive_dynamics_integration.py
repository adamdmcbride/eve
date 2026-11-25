import json
import unittest

import eve_predictive_dynamics as dynamics
import eve_consciousness
import eve_sensory


def visual(value, index, *, scene="movement"):
    observed_at = f"2026-08-23T19:{index // 60:02d}:{index % 60:02d}+00:00"
    return eve_sensory.normalize_adapter_event(
        {
            "modality": "visual",
            "permission_granted": True,
            "observed_at": observed_at,
            "features": {"motion_percent": value, "scene_state": scene},
            "precision": 100,
        },
        allowed_modalities=["visual"],
        session_id="predictive-dynamics-integration",
        now=observed_at,
    ), observed_at


def run(values, *, dynamics_enabled=True):
    frame = {}
    for index, value in enumerate(values):
        event, observed_at = visual(value, index)
        frame = eve_sensory.build_frame(
            [event],
            prior_frame=frame,
            now=observed_at,
            predictive_dynamics_enabled=dynamics_enabled,
        )
    return frame


class SensoryPredictiveDynamicsIntegrationTests(unittest.TestCase):
    def test_periodic_history_changes_live_prediction_and_surprise(self):
        intact = run([20, 60, 20, 60, 20, 60], dynamics_enabled=True)
        velocity_only = run([20, 60, 20, 60, 20, 60], dynamics_enabled=False)

        self.assertEqual(0.0, intact["winner"]["prediction_error"]["weighted_error"])
        self.assertEqual(
            "period_2",
            intact["winner"]["prediction_error"]["selected_experts"]["motion_percent"],
        )
        self.assertFalse(intact["winner"]["prediction_violation"])
        self.assertEqual(60.0, velocity_only["winner"]["prediction_error"]["weighted_error"])
        self.assertTrue(velocity_only["winner"]["prediction_violation"])

    def test_linear_motion_preserves_established_two_sample_expectation(self):
        frame = run([10, 20, 30], dynamics_enabled=True)
        channel = next(iter(frame["channels"].values()))

        self.assertEqual(0.0, frame["winner"]["prediction_error"]["weighted_error"])
        self.assertEqual("velocity_bootstrap", frame["winner"]["prediction_error"]["selected_experts"]["motion_percent"])
        self.assertEqual("velocity", channel["prediction_models"]["motion_percent"]["selected_expert"])
        self.assertEqual(40.0, channel["predicted_features"]["motion_percent"])

    def test_history_is_bounded_sparse_and_has_no_action_authority(self):
        frame = run([float(index % 100) for index in range(24)], dynamics_enabled=True)
        channel = next(iter(frame["channels"].values()))
        public = eve_sensory.public_frame(frame)

        self.assertEqual(dynamics.MAX_HISTORY, len(channel["feature_history"]["motion_percent"]))
        self.assertLessEqual(len(channel["feature_history"]["scene_state"]), dynamics.MAX_HISTORY)
        self.assertTrue(
            all(
                model["action_authority"] is False
                for model in channel["prediction_models"].values()
            )
        )
        self.assertEqual(
            "bounded_multi_hypothesis_numeric_and_categorical",
            public["predictive_perception"]["forecast"],
        )
        self.assertEqual([], eve_sensory.forbidden_ingest_paths(public))
        rendered = json.dumps(public, sort_keys=True)
        self.assertNotIn("transcript", rendered)
        self.assertNotIn("raw_payload", rendered)

        conscious_state = eve_consciousness.build_conscious_state(
            source="predictive-dynamics-integration-test",
            sensory_frame=public,
            now="2026-08-23T20:00:00+00:00",
        )
        integrated = conscious_state["perception"]["sensory_frame"]
        self.assertEqual(
            "bounded_multi_hypothesis_numeric_and_categorical",
            integrated["predictive_perception"]["forecast"],
        )
        self.assertEqual(
            dynamics.MAX_HISTORY,
            len(next(iter(integrated["channels"].values()))["feature_history"]["motion_percent"]),
        )

    def test_malformed_prior_history_is_ignored_per_feature(self):
        prediction, history, models = eve_sensory.predict_next_features_from_history(
            {
                "feature_modality": "visual",
                "motion_percent": 30,
                "scene_state": "movement",
            },
            {
                "last_features": {
                    "feature_modality": "visual",
                    "motion_percent": 20,
                    "scene_state": "movement",
                },
                "feature_history": {
                    "motion_percent": [float("nan"), {"raw": "forbidden"}, 500],
                    "scene_state": ["invented", ["movement"]],
                },
            },
        )

        self.assertEqual([30.0], history["motion_percent"])
        self.assertEqual(["movement"], history["scene_state"])
        self.assertEqual(30.0, prediction["motion_percent"])
        self.assertEqual("persistence_bootstrap", models["motion_percent"]["selected_expert"])


if __name__ == "__main__":
    unittest.main()
