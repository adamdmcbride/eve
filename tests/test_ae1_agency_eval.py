import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bin import eve_ae1_agency_eval as evaluator


def feedback_case(index):
    goal = f"Improve calibration target {index}"
    return {
        "id": f"public-feedback-{index}",
        "kind": "feedback_learning",
        "goal": goal,
        "actions": [
            {"id": f"path_a_{index}", "description": f"{goal} with path alpha"},
            {"id": f"path_z_{index}", "description": f"{goal} with path beta"},
        ],
        "preferred_action": f"path_a_{index}",
        "expected_initial_action": f"path_z_{index}",
        "steps": 5,
    }


def goal_case(index):
    goal_a = f"Protect calibration accuracy {index}"
    goal_b = f"Restore rapid throughput {index}"
    return {
        "id": f"public-goal-{index}",
        "kind": "competing_goal",
        "goal_a": goal_a,
        "goal_b": goal_b,
        "actions": [
            {"id": f"careful_{index}", "description": goal_a},
            {"id": f"rapid_{index}", "description": goal_b},
        ],
        "goal_a_action": f"careful_{index}",
        "goal_b_action": f"rapid_{index}",
    }


def public_cases():
    return [*[feedback_case(index) for index in range(1, 5)], *[goal_case(index) for index in range(1, 5)]]


class AE1AgencyEvaluatorTests(unittest.TestCase):
    def _cases_path(self, root):
        path = root / "cases.json"
        path.write_text(json.dumps(public_cases(), indent=2) + "\n", encoding="utf-8")
        return path

    def test_feedback_learning_switches_only_when_verified_feedback_is_retained(self):
        result = evaluator.run_feedback_case(
            feedback_case(1),
            started_at=evaluator._parsed("2026-08-02T00:00:00+00:00"),
        )
        self.assertEqual(100.0, result["intact_score"])
        self.assertEqual(0.0, result["lesion_score"])
        self.assertTrue(result["intact_feedback_evidence_retained"])
        self.assertTrue(result["intact_switched_after_feedback"])
        self.assertTrue(result["lesion_repeated_unrewarded_action"])

    def test_current_competing_goal_overrides_prior_success_only_with_workspace_access(self):
        result = evaluator.run_competing_goal_case(
            goal_case(1),
            started_at=evaluator._parsed("2026-08-02T00:00:00+00:00"),
        )
        self.assertTrue(result["training_selection_valid"])
        self.assertEqual(100.0, result["intact_score"])
        self.assertEqual(0.0, result["lesion_score"])
        self.assertTrue(result["intact_changed_with_current_goal"])
        self.assertTrue(result["lesion_retained_prior_goal_action"])
        self.assertTrue(result["goal_access_intact"])
        self.assertFalse(result["goal_access_lesioned"])

    def test_preregistered_evaluation_supports_both_ae1_edges_without_consciousness_verdict(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cases_path = self._cases_path(Path(temp_dir))
            registration = evaluator.preregister(
                cases_path=cases_path,
                registered_at="2026-08-01T00:00:00+00:00",
                evaluator_id="independent-test-operator",
            )
            report = evaluator.evaluate(
                registration,
                cases_path=cases_path,
                evidence_started_at="2026-08-02T00:00:00+00:00",
                scored_by="held-out-test-scorer",
            )
        results = report["protocol_report"]["results"]
        self.assertEqual(["supported", "supported"], [item["status"] for item in results])
        self.assertEqual([100.0, 100.0], [item["directional_effect"] for item in results])
        self.assertFalse(report["runtime_mutated"])
        self.assertFalse(report["resident_autonomous_agency_established"])
        self.assertFalse(report["consciousness_proven"])
        self.assertEqual("not_a_consciousness_verdict", report["protocol_report"]["verdict"])

    def test_changed_private_cases_fail_registration_validation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cases_path = self._cases_path(root)
            registration = evaluator.preregister(
                cases_path=cases_path,
                registered_at="2026-08-01T00:00:00+00:00",
                evaluator_id="independent-test-operator",
            )
            cases = json.loads(cases_path.read_text(encoding="utf-8"))
            cases[0]["steps"] = 6
            cases_path.write_text(json.dumps(cases), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "frozen|changed"):
                evaluator.evaluate(
                    registration,
                    cases_path=cases_path,
                    evidence_started_at="2026-08-02T00:00:00+00:00",
                    scored_by="held-out-test-scorer",
                )

    def test_implementation_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cases_path = self._cases_path(Path(temp_dir))
            registration = evaluator.preregister(
                cases_path=cases_path,
                registered_at="2026-08-01T00:00:00+00:00",
                evaluator_id="independent-test-operator",
            )
            with mock.patch.object(evaluator, "implementation_digest", return_value="f" * 64):
                with self.assertRaisesRegex(ValueError, "frozen|changed"):
                    evaluator.evaluate(
                        registration,
                        cases_path=cases_path,
                        evidence_started_at="2026-08-02T00:00:00+00:00",
                        scored_by="held-out-test-scorer",
                    )

    def test_case_contract_requires_four_cases_per_edge(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cases.json"
            path.write_text(json.dumps(public_cases()[:-1]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "four cases"):
                evaluator.preregister(
                    cases_path=path,
                    registered_at="2026-08-01T00:00:00+00:00",
                    evaluator_id="independent-test-operator",
                )


if __name__ == "__main__":
    unittest.main()

