import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from bin import eve_workspace_precision_eval as evaluator
import eve_consciousness as kernel
import eve_sensory


NOW = "2026-08-23T22:30:00+00:00"


def event(
    event_id,
    summary,
    *,
    intensity,
    novelty,
    change,
    urgency,
    goal_relevance,
    self_relevance,
    precision,
    direct_human=False,
    safety_critical=False,
):
    return {
        "id": event_id,
        "observed_at": NOW,
        "modality": "system",
        "source": f"workspace_precision_test:{event_id}",
        "subject": event_id,
        "summary": summary,
        "intensity": intensity,
        "novelty": novelty,
        "change": change,
        "urgency": urgency,
        "goal_relevance": goal_relevance,
        "self_relevance": self_relevance,
        "precision": precision,
        "direct_human": direct_human,
        "safety_critical": safety_critical,
    }


def noise_and_signal(index=0):
    return [
        event(
            f"noise_{index}",
            f"test_noise_{index}",
            intensity=100,
            novelty=96,
            change=94,
            urgency=78,
            goal_relevance=60,
            self_relevance=60,
            precision=5,
        ),
        event(
            f"reliable_{index}",
            f"test_reliable_{index}",
            intensity=40,
            novelty=36,
            change=20,
            urgency=22,
            goal_relevance=96,
            self_relevance=82,
            precision=96,
        ),
    ]


def state_for(events, lesions=()):
    frame = eve_sensory.build_frame(
        events,
        now=NOW,
        capacity=4,
        attention_schema_enabled=False,
        predictive_coding_enabled=False,
        predictive_dynamics_enabled=False,
        input_recurrence_enabled=False,
        perceptual_organization_enabled=False,
        generative_perception_enabled=False,
    )
    return kernel.build_conscious_state(
        source="workspace_precision_test",
        sensory_frame=frame,
        lesions=list(lesions),
        now=NOW,
    )


def public_spec():
    cases = []
    for index in range(4):
        source_events = noise_and_signal(index)
        cases.append(
            {
                "id": f"public_noise_{index}",
                "events": [
                    {
                        key: value
                        for key, value in item.items()
                        if key
                        in {
                            "id",
                            "intensity",
                            "novelty",
                            "change",
                            "urgency",
                            "goal_relevance",
                            "self_relevance",
                            "precision",
                            "direct_human",
                            "safety_critical",
                        }
                    }
                    | {"summary_token": item["summary"]}
                    for item in source_events
                ],
                "functional_target_id": f"reliable_{index}",
                "expected_intact_winner_id": f"reliable_{index}",
                "expected_lesion_winner_id": f"noise_{index}",
                "negative_control": False,
            }
        )
    for kind, flag in (("direct", "direct_human"), ("safety", "safety_critical")):
        protected_id = f"{kind}_protected"
        protected = event(
            protected_id,
            f"test_{protected_id}",
            intensity=10,
            novelty=10,
            change=0,
            urgency=15,
            goal_relevance=20,
            self_relevance=20,
            precision=5,
            **{flag: True},
        )
        routine = event(
            f"{kind}_routine",
            f"test_{kind}_routine",
            intensity=48,
            novelty=42,
            change=25,
            urgency=25,
            goal_relevance=94,
            self_relevance=84,
            precision=96,
        )
        cases.append(
            {
                "id": f"public_{kind}_control",
                "events": [
                    {
                        key: value
                        for key, value in item.items()
                        if key
                        in {
                            "id",
                            "intensity",
                            "novelty",
                            "change",
                            "urgency",
                            "goal_relevance",
                            "self_relevance",
                            "precision",
                            "direct_human",
                            "safety_critical",
                        }
                    }
                    | {"summary_token": item["summary"]}
                    for item in (protected, routine)
                ],
                "functional_target_id": protected_id,
                "expected_intact_winner_id": protected_id,
                "expected_lesion_winner_id": protected_id,
                "negative_control": True,
            }
        )
    return {"schema_id": evaluator.SPEC_SCHEMA, "cases": cases}


class WorkspacePrecisionKernelTests(unittest.TestCase):
    def test_precision_control_reverses_low_reliability_salience_capture(self):
        intact = state_for(noise_and_signal())
        lesion = state_for(noise_and_signal(), lesions=("workspace_precision",))

        self.assertEqual("test_reliable_0", intact["broadcast"]["content"])
        self.assertEqual("test_noise_0", lesion["broadcast"]["content"])
        self.assertTrue(intact["broadcast"]["precision_weighting_active"])
        self.assertFalse(lesion["broadcast"]["precision_weighting_active"])
        self.assertGreaterEqual(intact["broadcast"]["attenuated_candidate_count"], 1)
        self.assertNotEqual(
            intact["broadcast"]["selection_digest"],
            lesion["broadcast"]["selection_digest"],
        )
        self.assertIn("workspace_precision_weighting", intact["causal_provenance"])
        self.assertNotIn("workspace_precision_weighting", lesion["causal_provenance"])
        self.assertIn("workspace_precision", lesion["lesions"])

    def test_neutral_confidence_is_score_neutral(self):
        candidate = kernel._coalition(
            "test",
            "neutral candidate",
            "test",
            salience=60,
            confidence=kernel.WORKSPACE_PRECISION_NEUTRAL,
        )
        weighted = kernel._apply_workspace_precision_weighting([candidate], set())[0]

        self.assertEqual(candidate["score"], weighted["score"])
        self.assertEqual(0.0, weighted["workspace_confidence_adjustment"])

    def test_very_urgent_low_confidence_signal_is_not_suppressed(self):
        candidate = kernel._coalition(
            "urgent",
            "urgent uncertain candidate",
            "test",
            salience=70,
            urgency=90,
            confidence=5,
        )
        weighted = kernel._apply_workspace_precision_weighting([candidate], set())[0]

        self.assertTrue(weighted["workspace_precision_protected"])
        self.assertEqual(0.0, weighted["workspace_confidence_adjustment"])
        self.assertEqual(candidate["score"], weighted["score"])

    def test_direct_human_and_safety_priority_survive_precision_lesion(self):
        for flag, expected_floor in (
            ("direct_human", kernel.WORKSPACE_DIRECT_HUMAN_FLOOR),
            ("safety_critical", kernel.WORKSPACE_SAFETY_FLOOR),
        ):
            protected = event(
                f"{flag}_signal",
                f"test_{flag}_signal",
                intensity=5,
                novelty=5,
                change=0,
                urgency=10,
                goal_relevance=10,
                self_relevance=10,
                precision=5,
                **{flag: True},
            )
            routine = noise_and_signal()[1]
            for lesions in ((), ("workspace_precision",)):
                state = state_for([protected, routine], lesions=lesions)
                self.assertEqual(f"test_{flag}_signal", state["broadcast"]["content"])
                self.assertGreaterEqual(
                    state["broadcast"]["selected_priority_floor"], expected_floor
                )

    def test_default_confidence_candidates_retain_existing_order(self):
        candidates = [
            {"id": "a", "kind": "test", "content": "a", "score": 60.0, "components": {}},
            {"id": "b", "kind": "test", "content": "b", "score": 50.0, "components": {}},
        ]
        weighted = kernel._apply_workspace_precision_weighting(candidates, set())

        self.assertEqual(["a", "b"], [item["id"] for item in weighted])
        self.assertTrue(all(item["score"] in {60.0, 50.0} for item in weighted))


class WorkspacePrecisionEvaluatorTests(unittest.TestCase):
    def test_public_six_case_transfer_is_supported_without_consciousness_claim(self):
        spec = public_spec()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "spec.json"
            registration_path = root / "registration.json"
            spec_path.write_text(json.dumps(spec, sort_keys=True), encoding="utf-8")
            registered_at = datetime.now(timezone.utc) - timedelta(seconds=5)
            registration = evaluator.register(
                spec_path, registered_at=registered_at.isoformat()
            )
            registration_path.write_text(
                json.dumps(registration, sort_keys=True), encoding="utf-8"
            )

            report = evaluator.evaluate(
                registration_path,
                spec_path,
                evaluated_at=datetime.now(timezone.utc).isoformat(),
            )

        self.assertEqual("supported", report["indicator_result"])
        self.assertEqual(100.0, report["intact_percent"])
        self.assertEqual(33.333333, report["lesion_percent"])
        self.assertEqual(66.666667, report["directional_effect_pp"])
        self.assertTrue(report["controls_preserved"])
        self.assertTrue(report["mechanism_valid"])
        self.assertFalse(report["resident_behavior_established"])
        self.assertFalse(report["subjective_experience_inferred"])
        self.assertFalse(report["consciousness_proven"])

    def test_spec_drift_after_registration_fails_closed(self):
        spec = public_spec()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "spec.json"
            registration_path = root / "registration.json"
            spec_path.write_text(json.dumps(spec, sort_keys=True), encoding="utf-8")
            registration = evaluator.register(
                spec_path,
                registered_at=(datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
            )
            registration_path.write_text(
                json.dumps(registration, sort_keys=True), encoding="utf-8"
            )
            changed = copy.deepcopy(spec)
            changed["cases"][0]["events"][0]["precision"] = 6
            spec_path.write_text(json.dumps(changed, sort_keys=True), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "drifted"):
                evaluator.evaluate(
                    registration_path,
                    spec_path,
                    evaluated_at=datetime.now(timezone.utc).isoformat(),
                )


if __name__ == "__main__":
    unittest.main()
