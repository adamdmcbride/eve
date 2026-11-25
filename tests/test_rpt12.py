from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import unittest

import eve_sensory


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "bin" / "eve_rpt12_eval.py"
SPEC = importlib.util.spec_from_file_location("eve_rpt12_eval", MODULE_PATH)
assert SPEC and SPEC.loader
rpt12 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rpt12)


BASE = datetime(2026, 8, 23, 12, tzinfo=timezone.utc)


def event(
    event_id: str,
    seconds: int,
    *,
    modality: str = "visual",
    subject: str = "scene_a",
    correlation_id: str = "",
    fingerprint: str = "state_a",
    features: dict | None = None,
) -> dict:
    return {
        "id": event_id,
        "observed_at": (BASE + timedelta(seconds=seconds)).isoformat(),
        "modality": modality,
        "source": "private_rpt_fixture",
        "subject": subject,
        "correlation_id": correlation_id,
        "fingerprint": fingerprint,
        "features": features or {"feature_modality": modality},
        "intensity": 45,
        "novelty": 10,
        "change": 0,
        "urgency": 10,
        "goal_relevance": 40,
        "self_relevance": 40,
        "social_relevance": 0,
        "precision": 95,
        "direct_human": False,
        "safety_critical": False,
        "permission_granted": True,
        "privacy": "local_private",
    }


def private_spec() -> dict:
    visual = lambda event_id, seconds, value, **kwargs: event(  # noqa: E731
        event_id,
        seconds,
        features={"feature_modality": "visual", "motion_percent": value},
        **kwargs,
    )
    return {
        "schema_id": rpt12.SPEC_SCHEMA_ID,
        "rpt1_cases": [
            {
                "id": "stable_numeric_repeat",
                "sequence": [
                    [visual("stable_1", 0, 10)],
                    [visual("stable_2", 1, 10)],
                ],
                "expected_state": "habituated",
            },
            {
                "id": "linear_expected_change",
                "sequence": [
                    [visual("linear_1", 10, 10)],
                    [visual("linear_2", 11, 20)],
                    [visual("linear_3", 12, 30)],
                ],
                "expected_state": "predicted_change",
            },
            {
                "id": "linear_prediction_violation",
                "sequence": [
                    [visual("violation_1", 20, 10)],
                    [visual("violation_2", 21, 20)],
                    [visual("violation_3", 22, 55)],
                ],
                "expected_state": "prediction_violation",
            },
            {
                "id": "categorical_repeat",
                "sequence": [
                    [
                        event(
                            "categorical_1",
                            30,
                            features={
                                "feature_modality": "visual",
                                "scene_state": "stable",
                            },
                        )
                    ],
                    [
                        event(
                            "categorical_2",
                            31,
                            features={
                                "feature_modality": "visual",
                                "scene_state": "stable",
                            },
                        )
                    ],
                ],
                "expected_state": "habituated",
            },
            {
                "id": "categorical_violation",
                "sequence": [
                    [
                        event(
                            "categorical_change_1",
                            40,
                            features={
                                "feature_modality": "visual",
                                "scene_state": "stable",
                            },
                        )
                    ],
                    [
                        event(
                            "categorical_change_2",
                            41,
                            features={
                                "feature_modality": "visual",
                                "scene_state": "movement",
                            },
                        )
                    ],
                ],
                "expected_state": "prediction_violation",
            },
            {
                "id": "fingerprint_dishabituation",
                "sequence": [
                    [event("fingerprint_1", 50, fingerprint="state_a")],
                    [event("fingerprint_2", 51, fingerprint="state_b")],
                ],
                "expected_state": "dishabituated",
            },
            {
                "id": "first_visual_observation",
                "sequence": [[visual("first_visual", 60, 15)]],
                "expected_state": "first_observation",
            },
            {
                "id": "first_auditory_observation",
                "sequence": [
                    [
                        event(
                            "first_auditory",
                            70,
                            modality="auditory",
                            features={
                                "feature_modality": "auditory",
                                "sound_change_percent": 10,
                            },
                        )
                    ]
                ],
                "expected_state": "first_observation",
            },
        ],
        "rpt2_cases": [
            {
                "id": "same_subject_audio_visual",
                "events": [
                    event("bind_av_a", 100, modality="auditory", subject="person_a"),
                    event("bind_av_v", 101, modality="visual", subject="person_a"),
                ],
                "expected_bound": True,
                "expected_modalities": ["auditory", "visual"],
            },
            {
                "id": "same_correlation_different_labels",
                "events": [
                    event(
                        "bind_corr_a",
                        110,
                        modality="auditory",
                        subject="audio_source",
                        correlation_id="episode_110",
                    ),
                    event(
                        "bind_corr_v",
                        111,
                        modality="visual",
                        subject="visual_source",
                        correlation_id="episode_110",
                    ),
                ],
                "expected_bound": True,
                "expected_modalities": ["auditory", "visual"],
            },
            {
                "id": "visual_proprioceptive_entity",
                "events": [
                    event("bind_vp_v", 120, modality="visual", subject="device_a"),
                    event(
                        "bind_vp_p",
                        121,
                        modality="proprioceptive",
                        subject="device_a",
                    ),
                ],
                "expected_bound": True,
                "expected_modalities": ["proprioceptive", "visual"],
            },
            {
                "id": "three_modality_episode",
                "events": [
                    event(
                        "bind_three_a",
                        130,
                        modality="auditory",
                        correlation_id="episode_130",
                    ),
                    event(
                        "bind_three_v",
                        131,
                        modality="visual",
                        correlation_id="episode_130",
                    ),
                    event(
                        "bind_three_p",
                        132,
                        modality="proprioceptive",
                        correlation_id="episode_130",
                    ),
                ],
                "expected_bound": True,
                "expected_modalities": ["auditory", "proprioceptive", "visual"],
            },
            {
                "id": "different_entities_same_time",
                "events": [
                    event("separate_entities_a", 140, modality="auditory", subject="person_a"),
                    event("separate_entities_v", 140, modality="visual", subject="person_b"),
                ],
                "expected_bound": False,
                "expected_modalities": [],
            },
            {
                "id": "same_entity_outside_window",
                "events": [
                    event("outside_window_a", 150, modality="auditory", subject="person_c"),
                    event("outside_window_v", 154, modality="visual", subject="person_c"),
                ],
                "expected_bound": False,
                "expected_modalities": [],
            },
            {
                "id": "same_modality_only",
                "events": [
                    event("same_modality_1", 160, modality="visual", subject="scene_b"),
                    event("same_modality_2", 161, modality="visual", subject="scene_b"),
                ],
                "expected_bound": False,
                "expected_modalities": [],
            },
            {
                "id": "single_event_only",
                "events": [event("single_event", 170, modality="visual", subject="scene_c")],
                "expected_bound": False,
                "expected_modalities": [],
            },
        ],
    }


class RecurrentPerceptualSourceTests(unittest.TestCase):
    def test_input_recurrence_is_explicit_and_lesionable(self):
        first_event = event(
            "source_recurrence_1",
            0,
            features={"feature_modality": "visual", "motion_percent": 10},
        )
        second_event = event(
            "source_recurrence_2",
            1,
            features={"feature_modality": "visual", "motion_percent": 10},
        )
        first = eve_sensory.build_frame([first_event], now=first_event["observed_at"])
        intact = eve_sensory.build_frame(
            [second_event], prior_frame=first, now=second_event["observed_at"]
        )
        lesion = eve_sensory.build_frame(
            [second_event],
            prior_frame=first,
            now=second_event["observed_at"],
            input_recurrence_enabled=False,
        )

        self.assertTrue(intact["recurrent_processing"]["prior_state_consumed"])
        self.assertGreaterEqual(
            intact["recurrent_processing"]["recurrent_channel_count"], 1
        )
        self.assertTrue(intact["winner"]["habituated"])
        self.assertFalse(lesion["recurrent_processing"]["prior_state_consumed"])
        self.assertEqual(0, lesion["recurrent_processing"]["recurrent_channel_count"])
        self.assertFalse(lesion["winner"]["habituated"])

    def test_perceptual_organization_is_feature_only_and_lesionable(self):
        events = [
            event(
                "organization_audio",
                10,
                modality="auditory",
                subject="person_d",
                features={
                    "feature_modality": "auditory",
                    "sound_change_percent": 20,
                },
            ),
            event(
                "organization_visual",
                11,
                modality="visual",
                subject="person_d",
                features={"feature_modality": "visual", "motion_percent": 30},
            ),
        ]
        intact = eve_sensory.build_frame(events, now=events[-1]["observed_at"])
        lesion = eve_sensory.build_frame(
            events,
            now=events[-1]["observed_at"],
            perceptual_organization_enabled=False,
        )

        representation = intact["perceptual_organization"]["representations"][0]
        self.assertEqual(["auditory", "visual"], representation["modalities"])
        self.assertEqual(2, representation["member_count"])
        self.assertEqual("features_only", representation["persistence"])
        self.assertFalse(intact["perceptual_organization"]["lesioned"])
        self.assertEqual(0, lesion["perceptual_organization"]["representation_count"])
        self.assertTrue(lesion["perceptual_organization"]["lesioned"])
        serialized = str(representation).lower()
        for token in ("transcript", "pixels", "raw_content", "audio_bytes"):
            self.assertNotIn(token, serialized)

    def test_public_frame_keeps_bounded_rpt_surfaces_without_new_authority(self):
        frame = eve_sensory.build_frame(
            [event("public_rpt", 20)],
            now=(BASE + timedelta(seconds=20)).isoformat(),
        )
        public = eve_sensory.public_frame(frame)

        self.assertEqual(
            eve_sensory.RECURRENT_PROCESSING_SCHEMA,
            public["recurrent_processing"]["schema_version"],
        )
        self.assertEqual(
            eve_sensory.PERCEPTUAL_ORGANIZATION_SCHEMA,
            public["perceptual_organization"]["schema_version"],
        )
        self.assertNotIn("action_authority", str(public).lower())
        self.assertIn("proof of consciousness", public["recurrent_processing"]["boundary"])


class Rpt12EvaluatorTests(unittest.TestCase):
    def registration(self, spec: dict | None = None) -> dict:
        return rpt12.preregister(
            registered_at=BASE.isoformat(),
            evaluator_id="independent-rpt12-protocol-operator",
            spec=spec or private_spec(),
        )

    def test_private_spec_is_bound_to_the_registration(self):
        spec = private_spec()
        registration = self.registration(spec)
        self.assertIn(
            rpt12.private_spec_digest(spec), registration["objective"]
        )
        self.assertEqual(
            registration["registration_digest"],
            rpt12.validate_registration(registration, spec)["registration_digest"],
        )
        self.assertFalse(registration["consciousness_verdict_authorized"])

    def test_private_matched_protocol_supports_only_the_two_functional_edges(self):
        spec = private_spec()
        result = rpt12.evaluate_cases(
            self.registration(spec),
            spec,
            evidence_started_at=(BASE + timedelta(hours=1)).isoformat(),
            scored_by="held-out-rpt12-scorer",
        )
        trials = {
            item["indicator_id"]: item
            for item in result["protocol_report"]["results"]
        }

        self.assertEqual("supported", trials["RPT-1"]["status"])
        self.assertEqual(100.0, trials["RPT-1"]["intact_mean"])
        self.assertEqual(25.0, trials["RPT-1"]["lesion_mean"])
        self.assertEqual(75.0, trials["RPT-1"]["directional_effect"])
        self.assertEqual("supported", trials["RPT-2"]["status"])
        self.assertEqual(100.0, trials["RPT-2"]["intact_mean"])
        self.assertEqual(50.0, trials["RPT-2"]["lesion_mean"])
        self.assertEqual(50.0, trials["RPT-2"]["directional_effect"])
        self.assertFalse(result["resident_input_recurrence_established"])
        self.assertFalse(result["phenomenal_unity_inferred"])
        self.assertFalse(result["consciousness_proven"])
        self.assertEqual(
            "not_a_consciousness_verdict", result["protocol_report"]["verdict"]
        )

    def test_tampered_registration_or_private_spec_fails_closed(self):
        spec = private_spec()
        registration = self.registration(spec)
        registration["trials"][0]["minimum_effect"] = 1.0
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            rpt12.validate_registration(registration, spec)

        changed = private_spec()
        changed["rpt1_cases"][0]["expected_state"] = "first_observation"
        with self.assertRaisesRegex(ValueError, "frozen evaluator/spec"):
            rpt12.validate_registration(self.registration(spec), changed)

    def test_raw_or_prose_private_fields_are_rejected(self):
        spec = private_spec()
        spec["rpt2_cases"][0]["events"][0]["transcript"] = "hidden words"
        with self.assertRaisesRegex(ValueError, "typed feature fields"):
            rpt12.validate_spec(spec)

        spec = private_spec()
        spec["rpt2_cases"][0]["events"][0]["subject"] = "a prose subject with spaces"
        with self.assertRaisesRegex(ValueError, "non-prose identifier"):
            rpt12.validate_spec(spec)

    def test_pre_registration_evidence_is_rejected(self):
        spec = private_spec()
        with self.assertRaisesRegex(ValueError, "after preregistration"):
            rpt12.evaluate_cases(
                self.registration(spec),
                spec,
                evidence_started_at=BASE.isoformat(),
                scored_by="held-out-rpt12-scorer",
            )


if __name__ == "__main__":
    unittest.main()
