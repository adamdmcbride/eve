from datetime import datetime, timedelta, timezone
import copy
import unittest

from bin import eve_hot1_eval as evaluator
import eve_perceptual_inference as inference
import eve_sensory


OBSERVED = {"feature_modality": "visual", "motion_percent": 10.0}
PREDICTED = {"feature_modality": "visual", "motion_percent": 90.0}


def infer(*, sensory=20, prior=80, lesioned=False, observed=None, predicted=None):
    return inference.infer_hypothesis(
        observed or OBSERVED,
        predicted or PREDICTED,
        sensory_precision=sensory,
        prior_precision=prior,
        feature_limits=eve_sensory.FEATURE_LIMITS,
        feature_enums=eve_sensory.FEATURE_ENUMS,
        lesioned=lesioned,
    )


def private_spec():
    cases = []
    for index, values in enumerate(
        [
            (10, 90, 20, 80, "top_down", True, False),
            (80, 20, 25, 75, "top_down", True, False),
            (25, 75, 30, 80, "top_down", True, False),
            (70, 10, 20, 70, "top_down", True, False),
            (10, 90, 50, 50, "balanced", True, False),
            (90, 10, 45, 45, "balanced", True, False),
            (95, 10, 90, 30, "bottom_up", False, True),
            (40, 40, 80, 0, "bottom_up_only", False, False),
        ],
        start=1,
    ):
        observed, predicted, sensory, prior, dominance, sampling, override = values
        cases.append(
            {
                "id": f"private-{index}",
                "observed_features": {
                    "feature_modality": "visual",
                    "motion_percent": observed,
                },
                "predicted_features": {
                    "feature_modality": "visual",
                    "motion_percent": predicted,
                },
                "sensory_precision": sensory,
                "prior_precision": prior,
                "expected_dominance": dominance,
                "expected_sampling": sampling,
                "expected_sensory_override": override,
            }
        )
    return {"schema_id": evaluator.SPEC_SCHEMA_ID, "cases": cases}


def visual_event(value, second, *, precision=95, goal_relevance=80):
    observed_at = f"2026-08-23T22:00:{second:02d}+00:00"
    return eve_sensory.normalize_adapter_event(
        {
            "modality": "visual",
            "permission_granted": True,
            "observed_at": observed_at,
            "features": {"motion_percent": value, "scene_state": "movement"},
            "precision": precision,
            "goal_relevance": goal_relevance,
            "intensity": 1,
            "novelty": 1,
            "change": 1,
            "urgency": 1,
        },
        allowed_modalities=["visual"],
        session_id="hot1-perceptual-inference-test",
        now=observed_at,
    ), observed_at


class PerceptualInferenceTests(unittest.TestCase):
    def test_low_precision_sensation_is_shifted_toward_higher_precision_prior(self):
        result = infer()

        self.assertEqual("top_down", result["dominance"])
        self.assertTrue(result["needs_active_sampling"])
        posterior = result["posterior_features"]["motion_percent"]
        self.assertLess(abs(posterior - 90.0), abs(posterior - 10.0))
        self.assertEqual(OBSERVED, result["observed_features"])
        self.assertFalse(result["observation_rewritten"])
        self.assertTrue(result["proposal_only"])

    def test_high_precision_contradiction_overrides_prior(self):
        result = infer(sensory=90, prior=30)

        self.assertEqual("bottom_up", result["dominance"])
        self.assertTrue(result["sensory_override"])
        self.assertFalse(result["needs_active_sampling"])
        posterior = result["posterior_features"]["motion_percent"]
        self.assertLess(abs(posterior - 10.0), abs(posterior - 90.0))

    def test_zero_confidence_prediction_is_not_called_an_override_or_ambiguity(self):
        result = infer(sensory=20, prior=0)

        self.assertEqual("bottom_up_only", result["dominance"])
        self.assertFalse(result["sensory_override"])
        self.assertFalse(result["needs_active_sampling"])
        self.assertEqual("no_top_down_prediction", result["status"])

    def test_lesion_removes_top_down_causal_effect_without_removing_observation(self):
        result = infer(lesioned=True)

        self.assertEqual("lesioned", result["status"])
        self.assertEqual("bottom_up_only", result["dominance"])
        self.assertEqual(OBSERVED, result["posterior_features"])
        self.assertFalse(result["needs_active_sampling"])
        self.assertFalse(result["sensory_override"])

    def test_mismatched_modality_fails_closed(self):
        result = infer(
            predicted={"feature_modality": "auditory", "motion_percent": 90.0}
        )

        self.assertFalse(result["comparable"])
        self.assertEqual({}, result["predicted_features"])
        self.assertEqual(OBSERVED, result["posterior_features"])

    def test_categorical_hypothesis_uses_precision_without_inventing_a_value(self):
        result = infer(
            sensory=25,
            prior=75,
            observed={"feature_modality": "visual", "scene_state": "stable"},
            predicted={"feature_modality": "visual", "scene_state": "movement"},
        )

        self.assertEqual("movement", result["posterior_features"]["scene_state"])
        self.assertEqual("stable", result["observed_features"]["scene_state"])
        self.assertEqual("top_down", result["dominance"])

    def test_sensory_frame_uses_recurrent_forecast_as_a_bounded_prior(self):
        frame = {}
        for value, second, precision in ((10, 0, 95), (20, 10, 95), (5, 20, 20)):
            event, observed_at = visual_event(value, second, precision=precision)
            frame = eve_sensory.build_frame(
                [event],
                prior_frame=frame,
                now=observed_at,
                orient_threshold=80,
            )

        hypothesis = frame["winner"]["perceptual_hypothesis"]
        self.assertEqual("top_down", hypothesis["dominance"])
        self.assertTrue(hypothesis["needs_active_sampling"])
        self.assertEqual("look_for_more_evidence", frame["orienting_request"]["recommended_action"])
        self.assertEqual("proposal_only", frame["orienting_request"]["authority"])
        self.assertLess(frame["winner"]["attention_score"], 80)

    def test_sensory_lesion_preserves_feature_observation_but_removes_prior_effect(self):
        frame = {}
        for value, second, precision in ((10, 0, 95), (20, 10, 95)):
            event, observed_at = visual_event(value, second, precision=precision)
            frame = eve_sensory.build_frame([event], prior_frame=frame, now=observed_at)
        event, observed_at = visual_event(5, 20, precision=20)
        lesion = eve_sensory.build_frame(
            [event],
            prior_frame=frame,
            now=observed_at,
            generative_perception_enabled=False,
        )

        hypothesis = lesion["winner"]["perceptual_hypothesis"]
        self.assertTrue(lesion["generative_perception"]["lesioned"])
        self.assertEqual("bottom_up_only", hypothesis["dominance"])
        self.assertEqual(hypothesis["observed_features"], hypothesis["posterior_features"])
        self.assertEqual({}, lesion["orienting_request"])

    def test_public_frame_is_feature_only_and_grants_no_new_authority(self):
        event, observed_at = visual_event(10, 0)
        public = eve_sensory.public_frame(
            eve_sensory.build_frame([event], now=observed_at)
        )

        self.assertEqual(inference.SCHEMA_ID, public["generative_perception"]["schema_version"])
        self.assertTrue(public["generative_perception"]["proposal_only"])
        self.assertFalse(public["generative_perception"]["observation_rewritten"])
        rendered = str(public).lower()
        for token in ("raw_payload", "transcript", "pixels", "audio_bytes"):
            self.assertNotIn(token, rendered)
        self.assertEqual([], eve_sensory.forbidden_ingest_paths(public))


class Hot1EvaluatorTests(unittest.TestCase):
    def registration(self, spec=None):
        return evaluator.preregister(
            registered_at=(datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
            evaluator_id="independent-hot1-test",
            spec=spec or private_spec(),
        )

    def test_private_matched_lesion_supports_only_the_functional_indicator(self):
        spec = private_spec()
        result = evaluator.evaluate_cases(
            self.registration(spec),
            spec,
            evidence_started_at=datetime.now(timezone.utc).isoformat(),
            scored_by="independent-hot1-scorer",
        )

        trial = result["protocol_report"]["results"][0]
        self.assertEqual("HOT-1", trial["indicator_id"])
        self.assertEqual("supported", trial["status"])
        self.assertEqual(100.0, trial["intact_mean"])
        self.assertGreaterEqual(trial["directional_effect"], 40.0)
        self.assertFalse(result["runtime_mutated"])
        self.assertFalse(result["resident_behavior_established"])
        self.assertFalse(result["learned_generative_world_model_established"])
        self.assertFalse(result["consciousness_proven"])

    def test_wrong_expectations_remain_inconclusive_instead_of_being_repaired(self):
        spec = private_spec()
        for case in spec["cases"]:
            case["expected_dominance"] = "bottom_up_only"
            case["expected_sampling"] = False
            case["expected_sensory_override"] = False
        result = evaluator.evaluate_cases(
            self.registration(spec),
            spec,
            evidence_started_at=datetime.now(timezone.utc).isoformat(),
            scored_by="independent-hot1-scorer",
        )

        trial = result["protocol_report"]["results"][0]
        self.assertNotEqual("supported", trial["status"])
        self.assertLess(trial["intact_mean"], 100.0)

    def test_private_spec_rejects_raw_or_unknown_content(self):
        for key, value in (("transcript", "hidden answer"), ("embedding", [1, 2, 3])):
            spec = private_spec()
            spec["cases"][0]["observed_features"][key] = value
            with self.assertRaises(ValueError):
                evaluator.validate_spec(spec)

    def test_spec_change_after_registration_fails_closed(self):
        spec = private_spec()
        registration = self.registration(spec)
        changed = copy.deepcopy(spec)
        changed["cases"][0]["sensory_precision"] = 21
        with self.assertRaises(ValueError):
            evaluator.validate_registration(registration, changed)

    def test_registration_trial_tamper_fails_closed(self):
        spec = private_spec()
        registration = self.registration(spec)
        registration["trials"][0]["minimum_effect"] = 1.0
        with self.assertRaises(ValueError):
            evaluator.validate_registration(registration, spec)


if __name__ == "__main__":
    unittest.main()
