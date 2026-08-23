import json
import unittest

import eve_sensory


NOW = "2026-08-23T14:00:00+00:00"


def visual(motion: float, observed_at: str, *, scene: str = "movement"):
    return eve_sensory.normalize_adapter_event(
        {
            "modality": "visual",
            "permission_granted": True,
            "observed_at": observed_at,
            "features": {"motion_percent": motion, "scene_state": scene},
        },
        allowed_modalities=["visual"],
        session_id="quality-space-session",
        now=observed_at,
    )


class SensoryQualitySpaceTests(unittest.TestCase):
    def test_distance_is_zero_for_same_percept_and_smooth_for_numeric_change(self):
        same = eve_sensory.feature_quality_distance(
            {"feature_modality": "visual", "motion_percent": 20.0},
            {"feature_modality": "visual", "motion_percent": 20.0},
        )
        near = eve_sensory.feature_quality_distance(
            {"feature_modality": "visual", "motion_percent": 25.0},
            {"feature_modality": "visual", "motion_percent": 20.0},
        )
        far = eve_sensory.feature_quality_distance(
            {"feature_modality": "visual", "motion_percent": 80.0},
            {"feature_modality": "visual", "motion_percent": 20.0},
        )
        self.assertEqual(0.0, same["rms_distance"])
        self.assertLess(near["rms_distance"], far["rms_distance"])
        self.assertEqual(5.0, near["maximum_distance"])
        self.assertEqual(60.0, far["maximum_distance"])

    def test_bin_boundary_jitter_does_not_create_false_dishabituation(self):
        first = eve_sensory.build_frame(
            [visual(24, NOW)],
            now=NOW,
            predictive_coding_enabled=False,
        )
        intact = eve_sensory.build_frame(
            [visual(26, "2026-08-23T14:00:10+00:00")],
            prior_frame=first,
            now="2026-08-23T14:00:10+00:00",
            predictive_coding_enabled=False,
        )
        lesioned = eve_sensory.build_frame(
            [visual(26, "2026-08-23T14:00:10+00:00")],
            prior_frame=first,
            now="2026-08-23T14:00:10+00:00",
            quality_space_enabled=False,
            predictive_coding_enabled=False,
        )
        self.assertNotEqual(first["winner"]["fingerprint"], intact["winner"]["fingerprint"])
        self.assertFalse(intact["winner"]["dishabituated"])
        self.assertTrue(intact["winner"]["habituated"])
        self.assertTrue(lesioned["winner"]["dishabituated"])
        self.assertEqual(2.0, intact["winner"]["quality_distance"]["maximum_distance"])

    def test_large_and_categorical_changes_dishabituate(self):
        first = eve_sensory.build_frame([visual(20, NOW)], now=NOW)
        far = eve_sensory.build_frame(
            [visual(80, "2026-08-23T14:00:10+00:00")],
            prior_frame=first,
            now="2026-08-23T14:00:10+00:00",
        )
        categorical = eve_sensory.build_frame(
            [visual(80, "2026-08-23T14:00:20+00:00", scene="stable")],
            prior_frame=far,
            now="2026-08-23T14:00:20+00:00",
        )
        self.assertTrue(far["winner"]["dishabituated"])
        self.assertGreater(far["winner"]["change"], 80)
        self.assertTrue(categorical["winner"]["dishabituated"])
        self.assertEqual(100.0, categorical["winner"]["quality_distance"]["maximum_distance"])

    def test_low_coverage_and_cross_modality_fail_closed(self):
        missing = eve_sensory.feature_quality_distance(
            {"feature_modality": "visual", "motion_percent": 20.0},
            {"feature_modality": "visual", "luminance_percent": 20.0},
        )
        cross_modal = eve_sensory.feature_quality_distance(
            {"feature_modality": "visual", "motion_percent": 20.0},
            {"feature_modality": "auditory", "motion_percent": 20.0},
        )
        self.assertFalse(missing["comparable"])
        self.assertFalse(cross_modal["comparable"])

    def test_public_frame_retains_only_sparse_quality_evidence(self):
        first = eve_sensory.build_frame([visual(20, NOW)], now=NOW)
        second = eve_sensory.build_frame(
            [visual(30, "2026-08-23T14:00:10+00:00")],
            prior_frame=first,
            now="2026-08-23T14:00:10+00:00",
        )
        public = eve_sensory.public_frame(second)
        rendered = json.dumps(public, sort_keys=True)
        self.assertEqual(eve_sensory.QUALITY_SPACE_SCHEMA, public["quality_space"]["schema_version"])
        self.assertEqual("normalized_sparse_features", public["quality_space"]["representation"])
        self.assertEqual([], eve_sensory.forbidden_ingest_paths(public))
        for forbidden in ("pixels", "transcript", "feature_vector"):
            self.assertNotIn(forbidden, rendered)


if __name__ == "__main__":
    unittest.main()
