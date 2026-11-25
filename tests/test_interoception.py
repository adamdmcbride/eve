import copy
import unittest
from datetime import datetime, timezone

import eve_interoception
from bin import eve_interoception_eval


def homeostasis(level=70, *, trend="rising", signals=2):
    return {
        "regulation_mode": "stabilize" if level >= 60 else "steady",
        "pressures": [
            {
                "id": "resource_safety",
                "label": "resource safety",
                "level": level,
                "trend": trend,
                "signal_count": signals,
            }
        ],
    }


def previous_state(level=50):
    return {
        "interoception": {
            "pressure_records": [
                {
                    "id": "resource_safety",
                    "label": "resource safety",
                    "level": level,
                    "trend": "steady",
                    "signal_count": 2,
                }
            ]
        }
    }


def affordances():
    return [
        {"id": "lighten_load", "description": "Reduce resident load", "value": 50.0},
        {"id": "increase_load", "description": "Start heavier work", "value": 51.0},
    ]


def lived_effect(action_id, before, after, evidence_id, *, verified=True, elapsed=1, cost=5):
    return {
        "evidence_kind": eve_interoception.EFFECT_EVIDENCE_KIND,
        "evidence_id": evidence_id,
        "source_cycle_id": f"cycle-{evidence_id}",
        "execution_id": f"execution-{evidence_id}",
        "action_id": action_id,
        "verification_ok": verified,
        "ok": True,
        "elapsed_cycles": elapsed,
        "execution_cost": cost,
        "homeostasis_before": {"resource_safety": before},
        "homeostasis_after": {"resource_safety": after},
    }


class AllostaticInteroceptionTests(unittest.TestCase):
    def test_measured_rise_is_projected_across_multiple_horizons(self):
        forecast = eve_interoception.forecast_pressure_trajectories(
            homeostasis(70),
            previous_state(50),
        )

        trajectory = forecast["trajectories"][0]
        self.assertTrue(forecast["available"])
        self.assertTrue(forecast["history_available"])
        self.assertEqual(20.0, trajectory["measured_velocity"])
        self.assertEqual([1, 3, 6], [item["horizon_cycles"] for item in trajectory["points"]])
        self.assertGreater(trajectory["points"][1]["expected_level"], 70)
        self.assertGreater(forecast["peak_bound_crossing_risk"], 0)
        self.assertTrue(forecast["boundary_crossings"])

    def test_stable_and_falling_measurements_do_not_invent_rising_velocity(self):
        stable = eve_interoception.forecast_pressure_trajectories(
            homeostasis(70, trend="steady"),
            previous_state(70),
        )
        falling = eve_interoception.forecast_pressure_trajectories(
            homeostasis(45, trend="falling"),
            previous_state(70),
        )

        stable_points = stable["trajectories"][0]["points"]
        falling_points = falling["trajectories"][0]["points"]
        self.assertTrue(all(item["expected_level"] == 70 for item in stable_points))
        self.assertLess(falling_points[-1]["expected_level"], falling_points[0]["expected_level"])

    def test_categorical_trend_without_prior_history_widens_but_does_not_move_center(self):
        forecast = eve_interoception.forecast_pressure_trajectories(
            homeostasis(55, trend="rising", signals=0),
            {},
        )
        trajectory = forecast["trajectories"][0]

        self.assertFalse(trajectory["history_available"])
        self.assertEqual(0.0, trajectory["measured_velocity"])
        self.assertTrue(all(item["expected_level"] == 55 for item in trajectory["points"]))
        self.assertLess(trajectory["points"][0]["interval"][0], 60)
        self.assertGreaterEqual(trajectory["points"][0]["interval"][1], 60)

    def test_only_verified_before_after_evidence_changes_action_values(self):
        models = {
            "lighten_load": {
                "observations": [
                    lived_effect("lighten_load", 80, 50, "effect-lighten-1"),
                    lived_effect("lighten_load", 75, 50, "effect-lighten-2"),
                ]
            },
            "increase_load": {
                "observations": [
                    lived_effect("increase_load", 70, 85, "effect-increase-1"),
                ]
            },
        }
        state = eve_interoception.build_allostatic_state(
            homeostasis=homeostasis(70),
            previous_state=previous_state(50),
            affordances=affordances(),
            action_models=models,
        )
        adjusted = eve_interoception.apply_allostatic_adjustments(
            affordances(),
            state,
            inbound=False,
        )

        by_id = {item["id"]: item for item in adjusted}
        self.assertEqual(2, state["grounded_candidate_count"])
        self.assertGreater(by_id["lighten_load"]["allostatic_adjustment"], 0)
        self.assertLess(by_id["increase_load"]["allostatic_adjustment"], 0)
        self.assertEqual("lighten_load", adjusted[0]["id"])

    def test_unverified_or_derived_delta_claims_are_ignored(self):
        invalid = lived_effect("lighten_load", 80, 40, "invalid-effect", verified=False)
        asserted_delta = {
            "evidence_kind": eve_interoception.EFFECT_EVIDENCE_KIND,
            "evidence_id": "asserted-delta",
            "verification_ok": True,
            "ok": True,
            "homeostatic_effects": {"resource_safety": -40},
        }
        models = {"lighten_load": {"observations": [invalid, asserted_delta]}}

        effects = eve_interoception.observed_action_effects(affordances(), models)

        self.assertEqual({}, effects)

    def test_effect_learning_requires_exact_action_cycle_execution_cost_and_latency(self):
        wrong_action = lived_effect("increase_load", 80, 40, "wrong-action")
        missing_cycle = lived_effect("lighten_load", 80, 40, "missing-cycle")
        missing_cycle["source_cycle_id"] = ""
        missing_execution = lived_effect("lighten_load", 80, 40, "missing-execution")
        missing_execution["execution_id"] = ""
        invalid_cost = lived_effect("lighten_load", 80, 40, "invalid-cost")
        invalid_cost["execution_cost"] = "unknown"
        invalid_latency = lived_effect("lighten_load", 80, 40, "invalid-latency")
        invalid_latency["elapsed_cycles"] = 0
        invalid_measurement = lived_effect("lighten_load", 80, 40, "invalid-measurement")
        invalid_measurement["homeostasis_after"]["resource_safety"] = "not-a-number"
        models = {
            "lighten_load": {
                "observations": [
                    wrong_action,
                    missing_cycle,
                    missing_execution,
                    invalid_cost,
                    invalid_latency,
                    invalid_measurement,
                ]
            }
        }

        self.assertEqual(
            {},
            eve_interoception.observed_action_effects(affordances(), models),
        )

    def test_observed_recovery_latency_and_effect_spread_shape_candidate_forecast(self):
        models = {
            "lighten_load": {
                "observations": [
                    lived_effect(
                        "lighten_load",
                        80,
                        40,
                        "slow-effect-1",
                        elapsed=3,
                        cost=10,
                    ),
                    lived_effect(
                        "lighten_load",
                        80,
                        60,
                        "slow-effect-2",
                        elapsed=3,
                        cost=14,
                    ),
                ]
            }
        }
        state = eve_interoception.build_allostatic_state(
            homeostasis=homeostasis(70),
            previous_state=previous_state(50),
            affordances=affordances(),
            action_models=models,
        )
        baseline_point = state["baseline_forecast"]["trajectories"][0]["points"][0]
        candidate = state["candidate_forecasts"][0]
        candidate_point = candidate["trajectories"][0]["points"][0]

        self.assertEqual(3.0, candidate["mean_recovery_latency_cycles"])
        self.assertEqual(12.0, candidate["mean_execution_cost"])
        self.assertGreater(candidate_point["expected_level"], 70)
        self.assertLess(candidate_point["expected_level"], baseline_point["expected_level"])
        self.assertGreater(
            candidate_point["interval"][1] - candidate_point["interval"][0],
            baseline_point["interval"][1] - baseline_point["interval"][0],
        )

    def test_direct_human_turn_blocks_allostatic_reordering(self):
        models = {
            "lighten_load": {
                "observations": [lived_effect("lighten_load", 80, 40, "effect-1")]
            },
            "increase_load": {
                "observations": [lived_effect("increase_load", 60, 90, "effect-2")]
            },
        }
        state = eve_interoception.build_allostatic_state(
            homeostasis=homeostasis(70),
            previous_state=previous_state(50),
            affordances=affordances(),
            action_models=models,
        )
        adjusted = eve_interoception.apply_allostatic_adjustments(
            affordances(),
            state,
            inbound=True,
        )

        self.assertEqual("increase_load", adjusted[0]["id"])
        self.assertTrue(all(item["allostatic_adjustment"] == 0 for item in adjusted))
        self.assertTrue(all(item["allostatic_human_interrupt"] for item in adjusted))

    def test_enactive_sampling_is_proposed_only_when_bound_relevant_uncertainty_exists(self):
        uncertain = eve_interoception.build_allostatic_state(
            homeostasis=homeostasis(55, signals=0),
            previous_state={},
            affordances=affordances(),
            action_models={},
        )
        known = eve_interoception.build_allostatic_state(
            homeostasis=homeostasis(30, trend="steady", signals=4),
            previous_state=previous_state(30),
            affordances=affordances(),
            action_models={},
        )

        proposal = uncertain["sampling_proposal"]
        self.assertEqual("proposal_only", proposal["authority"])
        self.assertEqual("refresh_homeostasis_evidence", proposal["action"])
        self.assertFalse(proposal["requires_permission"])
        self.assertEqual({}, known["sampling_proposal"])

    def test_lesions_are_selective_and_do_not_masquerade_as_evidence(self):
        intact = eve_interoception.build_allostatic_state(
            homeostasis=homeostasis(55, signals=0),
            previous_state={},
            affordances=affordances(),
            action_models={},
        )
        allostasis_lesion = eve_interoception.build_allostatic_state(
            homeostasis=homeostasis(55, signals=0),
            previous_state={},
            affordances=affordances(),
            action_models={},
            lesions=["allostasis"],
        )
        enaction_lesion = eve_interoception.build_allostatic_state(
            homeostasis=homeostasis(55, signals=0),
            previous_state={},
            affordances=affordances(),
            action_models={},
            lesions=["interoceptive_enaction"],
        )

        self.assertTrue(intact["available"])
        self.assertTrue(intact["sampling_proposal"])
        self.assertFalse(allostasis_lesion["available"])
        self.assertEqual(0.0, allostasis_lesion["baseline_forecast"]["peak_bound_crossing_risk"])
        self.assertTrue(enaction_lesion["available"])
        self.assertEqual({}, enaction_lesion["sampling_proposal"])
        self.assertIn("not evidence", intact["boundary"].lower())

    def test_private_evaluator_emits_only_aggregate_case_evidence(self):
        case = {
            "homeostasis": homeostasis(55, signals=0),
            "previous_state": {},
            "affordances": affordances(),
            "action_models": {},
            "assertions": [
                {
                    "path": "intact.sampling_proposal.authority",
                    "operator": "eq",
                    "expected": "proposal_only",
                },
                {
                    "path": "enaction_lesion.sampling_proposal",
                    "operator": "falsy",
                },
            ],
        }
        report = eve_interoception_eval.run(
            {
                "schema_version": eve_interoception_eval.SCHEMA_VERSION,
                "frozen_at": datetime.now(timezone.utc).isoformat(),
                "cases": [copy.deepcopy(case) for _ in range(5)],
            }
        )

        self.assertTrue(report["passed"])
        self.assertEqual(5, report["cases_passed"])
        self.assertEqual(10, report["assertions_passed"])
        self.assertFalse(report["privacy"]["private_fixture_text_retained"])
        self.assertNotIn("homeostasis", report["cases"][0])
        self.assertNotIn("assertions", report["cases"][0])


if __name__ == "__main__":
    unittest.main()
