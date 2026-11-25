from datetime import datetime, timedelta, timezone
import copy
import unittest

from bin import eve_gwt23_eval as evaluator
import eve_consciousness as kernel
from tests.test_conscious_state import fixture_inputs


def candidates():
    return [
        {
            "id": "candidate_alpha",
            "kind": "sensory_module",
            "source": "private_specialist:sensory_module",
            "content": "inspect_alpha_state",
            "score": 90.0,
            "components": {},
        },
        {
            "id": "candidate_beta",
            "kind": "memory_module",
            "source": "private_specialist:memory_module",
            "content": "inspect_beta_state",
            "score": 80.0,
            "components": {},
        },
        {
            "id": "candidate_gamma",
            "kind": "planning_module",
            "source": "private_specialist:planning_module",
            "content": "inspect_gamma_state",
            "score": 70.0,
            "components": {},
        },
    ]


def private_spec():
    module_ids = ("sensory_module", "memory_module", "planning_module")
    cases = []
    for index in range(6):
        winner_index = index % 3
        raw = []
        for position, module_id in enumerate(module_ids):
            action = f"inspect_private_{index}_{module_id}"
            raw.append(
                {
                    "id": f"case_{index}_candidate_{position}",
                    "module_id": module_id,
                    "content_token": action,
                    "score": 95 - ((position - winner_index) % 3) * 15,
                }
            )
        winner = raw[winner_index]
        cases.append(
            {
                "id": f"private_case_{index}",
                "candidates": raw,
                "expected_winner_id": winner["id"],
                "expected_action_id": winner["content_token"],
            }
        )
    return {"schema_id": evaluator.SPEC_SCHEMA_ID, "cases": cases}


class GlobalWorkspaceSelectionTests(unittest.TestCase):
    def test_intact_workspace_selects_one_winner_and_retains_bounded_alternatives(self):
        winner, alternatives, broadcast = kernel._select_broadcast(candidates(), set())

        self.assertEqual("candidate_alpha", winner["id"])
        self.assertEqual(kernel.GLOBAL_WORKSPACE_CAPACITY, broadcast["workspace_capacity"])
        self.assertEqual(1, broadcast["selected_candidate_count"])
        self.assertEqual(["candidate_alpha"], broadcast["selected_candidate_ids"])
        self.assertEqual(3, broadcast["candidate_count"])
        self.assertLessEqual(len(alternatives), kernel.GLOBAL_WORKSPACE_ALTERNATIVE_CAPACITY)
        self.assertTrue(broadcast["bottleneck_active"])
        self.assertEqual(list(kernel.GLOBAL_BROADCAST_ACCESS_SCOPE), broadcast["access_scope"])

    def test_bottleneck_lesion_bundles_candidates_without_removing_access(self):
        winner, alternatives, broadcast = kernel._select_broadcast(
            candidates(), {"workspace_bottleneck"}
        )

        self.assertEqual("unfiltered_workspace_bundle", winner["kind"])
        self.assertEqual(3, winner["member_count"])
        self.assertEqual(3, broadcast["selected_candidate_count"])
        self.assertEqual(3, broadcast["workspace_capacity"])
        self.assertFalse(broadcast["bottleneck_active"])
        self.assertEqual([], alternatives)
        self.assertEqual(list(kernel.GLOBAL_BROADCAST_ACCESS_SCOPE), broadcast["access_scope"])

    def test_access_lesion_preserves_selection_but_removes_delivery(self):
        intact_winner, _, intact = kernel._select_broadcast(candidates(), set())
        lesion_winner, _, lesion = kernel._select_broadcast(
            candidates(), {"broadcast_access"}
        )

        self.assertEqual(intact_winner["id"], lesion_winner["id"])
        self.assertEqual(intact["selection_digest"], lesion["selection_digest"])
        self.assertNotEqual(intact["delivery_digest"], lesion["delivery_digest"])
        self.assertEqual([], lesion["access_scope"])
        self.assertEqual("access_lesioned", lesion["access_status"])
        self.assertTrue(lesion["bottleneck_active"])

    def test_action_valuation_carries_exact_broadcast_receipt(self):
        case = evaluator.validate_spec(private_spec())["cases"][0]
        coalitions = evaluator._coalitions(case)
        winner, _, broadcast = kernel._select_broadcast(coalitions, set())
        access_winner, _, access_lesion = kernel._select_broadcast(
            coalitions, {"broadcast_access"}
        )
        intact = evaluator._action_affordances(winner, broadcast, case)
        lesioned = evaluator._action_affordances(access_winner, access_lesion, case)

        self.assertEqual(case["expected_action_id"], intact[0]["id"])
        self.assertEqual(
            broadcast["selection_digest"],
            intact[0]["broadcast_selection_digest"],
        )
        self.assertGreater(intact[0]["broadcast_adjustment"], 0)
        self.assertTrue(
            all(not item["broadcast_selection_digest"] for item in lesioned)
        )
        self.assertTrue(all(item["broadcast_adjustment"] == 0 for item in lesioned))

    def test_full_causal_suite_exercises_separate_selection_and_access_lesions(self):
        report = kernel.run_causal_ablation_suite(fixture_inputs())

        self.assertTrue(report["lesions"]["workspace_bottleneck"]["passed"], report)
        self.assertTrue(report["lesions"]["broadcast_access"]["passed"], report)
        self.assertEqual(len(kernel.LESIONS), report["candidate_total"])


class Gwt23EvaluatorTests(unittest.TestCase):
    def registration(self, spec=None):
        return evaluator.preregister(
            registered_at=(datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
            evaluator_id="independent-gwt23-test",
            spec=spec or private_spec(),
        )

    def test_private_matched_lesions_support_only_the_functional_edges(self):
        spec = private_spec()
        result = evaluator.evaluate_cases(
            self.registration(spec),
            spec,
            evidence_started_at=datetime.now(timezone.utc).isoformat(),
            scored_by="independent-gwt23-scorer",
        )

        outcomes = {
            item["indicator_id"]: item for item in result["protocol_report"]["results"]
        }
        self.assertEqual("supported", outcomes["GWT-2"]["status"])
        self.assertEqual("supported", outcomes["GWT-3"]["status"])
        self.assertEqual(100.0, outcomes["GWT-2"]["intact_mean"])
        self.assertEqual(100.0, outcomes["GWT-3"]["intact_mean"])
        self.assertGreaterEqual(outcomes["GWT-2"]["directional_effect"], 50.0)
        self.assertGreaterEqual(outcomes["GWT-3"]["directional_effect"], 50.0)
        self.assertFalse(result["runtime_mutated"])
        self.assertFalse(result["resident_parallel_module_operation_established"])
        self.assertFalse(result["universal_module_consumption_established"])
        self.assertFalse(result["consciousness_proven"])

    def test_spec_rejects_prose_raw_fields_and_tied_scores(self):
        spec = private_spec()
        spec["cases"][0]["candidates"][0]["raw"] = "hidden"
        with self.assertRaises(ValueError):
            evaluator.validate_spec(spec)

        spec = private_spec()
        spec["cases"][0]["candidates"][1]["score"] = spec["cases"][0]["candidates"][0]["score"]
        with self.assertRaises(ValueError):
            evaluator.validate_spec(spec)

    def test_spec_change_after_registration_fails_closed(self):
        spec = private_spec()
        registration = self.registration(spec)
        changed = copy.deepcopy(spec)
        changed["cases"][0]["candidates"][1]["score"] -= 1
        with self.assertRaises(ValueError):
            evaluator.validate_registration(registration, changed)

    def test_registration_tamper_fails_closed(self):
        spec = private_spec()
        registration = self.registration(spec)
        registration["trials"][0]["minimum_effect"] = 1
        with self.assertRaises(ValueError):
            evaluator.validate_registration(registration, spec)


if __name__ == "__main__":
    unittest.main()
