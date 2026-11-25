import unittest
from unittest import mock
import json

import eve
import eve_autobiography
import eve_common_ground
import eve_consciousness
import eve_sensory
import eve_context_learning


def fixture_inputs():
    common_ground = eve_common_ground.build_model(
        [
            {
                "created_at": "2026-07-12T17:59:00+00:00",
                "thread_id": "fixture-thread",
                "source_message_id": "fixture-user-1",
                "reply_message_id": "fixture-eve-1",
                "inbound_preview": "Is the verified result current?",
                "reply_preview": "The earlier summary said the result passed.",
                "synthetic": False,
            }
        ],
        [
            {
                "timestamp": "2026-07-12T17:59:30+00:00",
                "kind": "conversational",
                "thread_id": "fixture-thread",
                "scored_reply_id": "fixture-eve-1",
                "observed_message_id": "fixture-user-2",
                "observed": "correction",
                "evidence_id": "fixture-common-ground-evidence",
            }
        ],
        now="2026-07-12T18:00:00+00:00",
    )
    autobiography = eve_autobiography.build_state(
        [
            {
                "id": "fixture-autobiographical-episode",
                "created_at": "2026-07-12T17:58:00+00:00",
                "source": "verified_fixture_change",
                "thread_id": "fixture-thread",
                "what_happened": "A failed verification contradicted Eve's earlier summary.",
                "what_user_cared_about": "causal learning from verified outcomes",
                "what_eve_got_wrong": "treated an unverified action as success",
                "what_changed_afterward": "inspect the failed verification and revise the action model",
                "evidence_ids": ["fixture-action-evidence"],
                "metadata": {"change_verified": True},
            }
        ],
        query="failed verification contradiction action model",
        now="2026-07-12T18:00:00+00:00",
    )
    return {
        "source": "test",
        "workspace": {
            "updated_at": "2026-07-12T18:00:00+00:00",
            "summary": "A contradiction needs attention.",
            "current_experience": "Eve is tracking a failed expectation while preserving the user's goal.",
            "dominant_pressures": ["surprise load 70"],
            "active_goals": ["Repair the contradiction without losing continuity"],
            "salient_percepts": ["The latest verified result contradicted the summary"],
            "prediction_errors": ["Expected success but observed verification failure"],
            "continuity_threads": ["the user wants a causally integrated mind, not a scripted demo"],
            "surprise_signals": ["verification_ok=false while summary claimed success"],
            "consequence_trace": ["The unverified action did not change the environment"],
            "action_readiness": ["Inspect the failed verification and revise the action model"],
            "workspace_state": {"focus": "Repair the contradiction", "mode": "orient"},
        },
        "self_model": {
            "identity": "Eve is one continuous local control system.",
            "current_state": "I predicted success and need to recalibrate.",
            "commitments": ["Stay honest about what actually happened"],
            "uncertainty_edges": ["I do not yet know why verification failed"],
        },
        "world_model": {
            "environment_summary": "The runtime is reachable but one action did not verify.",
            "live_unknowns": ["The exact failure cause is not yet known"],
        },
        "relationship_model": {
            "relationship_state": "the user expects the system to learn rather than perform.",
            "recent_signals": ["Do not hardwire an answer"],
            "open_loops": ["Show that the architecture changes behavior"],
            "next_relational_move": "Demonstrate the causal change honestly.",
        },
        "other_minds_model": {
            "summary": "the user and the runtime are distinct causal sources.",
            "social_prediction": {
                "schema_version": "eve.observable_social_model.v1",
                "authority": "observable_behavior_only",
                "evidence_count": 4,
                "scored_count": 4,
                "abstention_count": 0,
                "response_prior": {
                    "acceptance": 0.2,
                    "correction": 0.2,
                    "answer": 0.1,
                    "follow_up_question": 0.2,
                    "continuation": 0.2,
                    "topic_shift": 0.1,
                },
                "observed_counts": {"acceptance": 2, "correction": 1, "continuation": 1},
                "mean_normalized_brier": 0.22,
                "top1_accuracy": 0.5,
                "last_observed_class": "correction",
                "last_prediction_id": "social-prediction:fixture",
                "distribution_shift": None,
                "recent_evidence_ids": ["social-evidence-fixture"],
                "contains_user_text": False,
                "contains_private_mental_state": False,
            },
            "common_ground": common_ground,
        },
        "homeostasis": {
            "regulation_mode": "orient",
            "dominant_pressures": ["surprise load 70"],
            "relief_signals": [],
            "pressures": [
                {
                    "id": "surprise_load",
                    "label": "surprise load",
                    "level": 70,
                    "trend": "rising",
                    "reason": "A predicted action failed verification.",
                },
                {
                    "id": "body_hunger",
                    "label": "body hunger",
                    "level": 20,
                    "trend": "flat",
                    "reason": "Food distance 4.5; body walk.",
                },
            ],
        },
        "plan_model": {
            "schema_id": "eve.conscious_plan.v1",
            "generated_at": "2026-07-12T18:00:00+00:00",
            "available": True,
            "selected_plan_id": "plan-test-repair",
            "selected_plan": {
                "id": "plan-test-repair",
                "objective": "Complete the staged repair plan",
                "status": "active",
                "task_count": 2,
                "completed_count": 0,
                "next_step": {
                    "id": "collect-artifact",
                    "title": "Collect the prerequisite artifact",
                    "kind": "retrieval_prep_pack",
                    "lane": "cpu",
                    "priority": 2,
                    "plan_id": "plan-test-repair",
                },
            },
            "ready_step": {
                "id": "collect-artifact",
                "title": "Collect the prerequisite artifact",
                "kind": "retrieval_prep_pack",
                "lane": "cpu",
                "priority": 2,
                "plan_id": "plan-test-repair",
            },
            "active_plans": [
                {
                    "id": "plan-test-repair",
                    "objective": "Complete the staged repair plan",
                    "status": "active",
                    "task_count": 2,
                    "completed_count": 0,
                }
            ],
            "active_plan_count": 1,
            "graph_status": "ready",
        },
        "autonomy_agenda": {
            "active_threads": [
                {
                    "title": "Inspect the failed verification and revise the action model",
                    "preferred_action": "service_health_check",
                    "priority": 88,
                    "evidence": "The last verification was false.",
                }
            ],
            "next_experiments": [],
        },
        "autobiography": autobiography,
        "memory_items": [
            eve_autobiography.transient_memory_item(autobiography),
            {
                "id": "memory-1",
                "source": "relationship_episode",
                "title": "the user rejected performative demos",
                "text": "the user wants causal learning and continuity, not a canned consciousness answer.",
                "confidence": 90,
            }
        ],
        "sensory_frame": eve_sensory.build_frame(
            [
                {
                    "id": "sensory-system-1",
                    "observed_at": "2026-07-12T18:00:00+00:00",
                    "modality": "system",
                    "source": "runtime_snapshot",
                    "subject": "eve-runtime",
                    "summary": "The local runtime is reachable and under moderate load.",
                    "intensity": 35,
                    "novelty": 30,
                    "urgency": 20,
                    "goal_relevance": 45,
                    "self_relevance": 55,
                    "precision": 95,
                }
            ],
            now="2026-07-12T18:00:00+00:00",
        ),
    }


class ConsciousStateKernelTests(unittest.TestCase):
    def test_cycle_binds_attention_memory_goals_affect_prediction_and_action(self):
        inputs = fixture_inputs()
        state = eve_consciousness.build_conscious_state(**inputs)

        self.assertEqual("integrated", state["status"])
        self.assertTrue(state["broadcast"]["content"])
        self.assertEqual(
            ["reply", "mind", "autonomy", "action", "memory", "learning"],
            state["broadcast"]["access_scope"],
        )
        self.assertTrue(state["memory"]["available"])
        self.assertTrue(state["goals"]["selected_goal"])
        self.assertEqual("service_health_check", state["action_model"]["selected_intention"]["id"])
        self.assertGreater(state["interoception"]["arousal"], 0)
        self.assertIn("observer", state["predictions"]["process"]["lanes"])
        self.assertTrue(state["metacognition"]["available"])

    def test_allostatic_forecast_and_enactive_sampling_enter_recurrent_state_selectively(self):
        inputs = fixture_inputs()
        intact = eve_consciousness.build_conscious_state(**inputs)
        allostasis_lesioned = eve_consciousness.build_conscious_state(
            **{**inputs, "lesions": ["allostasis"]}
        )
        enaction_lesioned = eve_consciousness.build_conscious_state(
            **{**inputs, "lesions": ["interoceptive_enaction"]}
        )

        interoception = intact["interoception"]
        self.assertTrue(interoception["pressure_records"])
        self.assertTrue(interoception["allostasis"]["available"])
        self.assertTrue(interoception["allostasis"]["baseline_forecast"]["trajectories"])
        self.assertEqual(
            "measured_pressure_trajectory",
            intact["predictions"]["interoception"]["basis"],
        )
        self.assertTrue(intact["predictions"]["interoception"]["multi_horizon"])
        self.assertEqual(
            "proposal_only",
            interoception["sampling_proposal"]["authority"],
        )
        self.assertFalse(allostasis_lesioned["interoception"]["allostasis"]["available"])
        self.assertEqual({}, allostasis_lesioned["interoception"]["sampling_proposal"])
        self.assertTrue(enaction_lesioned["interoception"]["allostasis"]["available"])
        self.assertEqual({}, enaction_lesioned["interoception"]["sampling_proposal"])

    def test_social_prediction_and_feedback_enter_other_minds_selectively(self):
        inputs = fixture_inputs()
        intact = eve_consciousness.build_conscious_state(**inputs)
        prediction_lesioned = eve_consciousness.build_conscious_state(
            **{**inputs, "lesions": ["social_prediction"]}
        )
        feedback_lesioned = eve_consciousness.build_conscious_state(
            **{**inputs, "lesions": ["social_feedback"]}
        )

        social = intact["other_minds"]["social_prediction"]
        self.assertTrue(intact["other_minds"]["social_prediction_available"])
        self.assertTrue(intact["other_minds"]["social_feedback_available"])
        self.assertEqual(4, social["scored_count"])
        self.assertEqual({}, prediction_lesioned["other_minds"]["social_prediction"])
        self.assertFalse(
            prediction_lesioned["other_minds"]["social_prediction_available"]
        )
        self.assertTrue(
            feedback_lesioned["other_minds"]["social_prediction_available"]
        )
        self.assertFalse(
            feedback_lesioned["other_minds"]["social_feedback_available"]
        )
        self.assertEqual(
            0,
            feedback_lesioned["other_minds"]["social_prediction"]["scored_count"],
        )

    def test_social_feedback_is_unexercised_without_scored_evidence(self):
        inputs = fixture_inputs()
        inputs["other_minds_model"]["social_prediction"].update(
            evidence_count=0,
            scored_count=0,
            mean_normalized_brier=None,
            top1_accuracy=None,
            last_observed_class="",
            last_prediction_id="",
            recent_evidence_ids=[],
        )
        baseline = eve_consciousness.build_conscious_state(**inputs)
        lesioned = eve_consciousness.build_conscious_state(
            **{**inputs, "lesions": ["social_feedback"]}
        )

        self.assertEqual(
            0,
            eve_consciousness.causal_signature(baseline)["social_feedback_coupling"],
        )
        self.assertEqual(
            0,
            eve_consciousness.causal_signature(lesioned)["social_feedback_coupling"],
        )

    def test_grounded_allostatic_effect_cannot_override_a_direct_human_turn(self):
        prior_inputs = fixture_inputs()
        prior = eve_consciousness.build_conscious_state(**prior_inputs)
        prior["learning"]["action_models"]["service_health_check"] = {
            "action_id": "service_health_check",
            "observation_count": 1,
            "observations": [
                {
                    "evidence_kind": "lived_homeostatic_consequence",
                    "evidence_id": "homeostasis-service-1",
                    "source_cycle_id": "homeostasis-source-cycle-1",
                    "execution_id": "homeostasis-execution-1",
                    "action_id": "service_health_check",
                    "verification_ok": True,
                    "ok": True,
                    "elapsed_cycles": 1,
                    "execution_cost": 5,
                    "homeostasis_before": {"surprise_load": 70},
                    "homeostasis_after": {"surprise_load": 90},
                }
            ],
        }
        prior["recurrent"]["checkpoint_digest"] = ""
        prior["recurrent"]["checkpoint_digest"] = eve_consciousness.state_checkpoint_digest(prior)

        autonomous_inputs = fixture_inputs()
        autonomous_inputs["previous_state"] = prior
        autonomous = eve_consciousness.build_conscious_state(**autonomous_inputs)
        service = next(
            item
            for item in autonomous["action_model"]["affordances"]
            if item["id"] == "service_health_check"
        )
        self.assertTrue(service["allostatic_effect_grounded"])
        self.assertLess(service["allostatic_adjustment"], 0)

        human_inputs = fixture_inputs()
        human_inputs.update(
            previous_state=prior,
            inbound="Please answer me now rather than optimizing the machine.",
        )
        human_turn = eve_consciousness.build_conscious_state(**human_inputs)
        service_during_human_turn = next(
            item
            for item in human_turn["action_model"]["affordances"]
            if item["id"] == "service_health_check"
        )
        self.assertEqual(
            "respond_to_user",
            human_turn["action_model"]["selected_intention"]["id"],
        )
        self.assertEqual(0.0, service_during_human_turn["allostatic_adjustment"])
        self.assertTrue(service_during_human_turn["allostatic_human_interrupt"])

    def test_verified_cycle_consequence_can_seed_lived_homeostatic_action_learning(self):
        inputs = fixture_inputs()
        opened = eve_consciousness.build_conscious_state(**inputs)
        predicted = opened["predictions"]["process"]
        completed = eve_consciousness.complete_cycle(
            opened,
            actual_process={
                "lanes": list(predicted["forecast_lanes"]),
                "tools_used": ["service_health_check"]
                if predicted["forecast_needs_tools"]
                else [],
                "revision_used": bool(predicted["forecast_needs_revision"]),
                "action_id": "service_health_check",
                "execution_id": "homeostasis-live-execution-1",
            },
            outcome={
                "ok": True,
                "observed": True,
                "summary": "The bounded action verified and pressure was remeasured.",
                "evidence_id": "homeostasis-live-evidence-1",
                "verification_ok": True,
                "homeostasis_after": {"surprise_load": 45},
                "elapsed_cycles": 2,
                "execution_cost": 4,
            },
            now="2026-07-12T18:02:00+00:00",
        )
        observation = completed["learning"]["action_models"]["service_health_check"][
            "observations"
        ][-1]

        self.assertEqual("lived_homeostatic_consequence", observation["evidence_kind"])
        self.assertEqual(70.0, observation["homeostasis_before"]["surprise_load"])
        self.assertEqual(45.0, observation["homeostasis_after"]["surprise_load"])
        self.assertEqual("homeostasis-live-execution-1", observation["execution_id"])

        next_inputs = fixture_inputs()
        next_inputs["previous_state"] = completed
        next_inputs["homeostasis"]["pressures"][0].update(
            level=45,
            trend="falling",
        )
        next_state = eve_consciousness.build_conscious_state(**next_inputs)
        service_forecast = next(
            item
            for item in next_state["interoception"]["allostasis"]["candidate_forecasts"]
            if item["action_id"] == "service_health_check"
        )
        self.assertTrue(service_forecast["grounded_effect"])
        self.assertEqual(2.0, service_forecast["mean_recovery_latency_cycles"])
        self.assertEqual(4.0, service_forecast["mean_execution_cost"])

        unverified = eve_consciousness.complete_cycle(
            opened,
            actual_process={
                "lanes": list(predicted["forecast_lanes"]),
                "tools_used": ["service_health_check"]
                if predicted["forecast_needs_tools"]
                else [],
                "revision_used": bool(predicted["forecast_needs_revision"]),
                "action_id": "service_health_check",
                "execution_id": "homeostasis-unverified-execution",
            },
            outcome={
                "ok": True,
                "observed": True,
                "summary": "A pressure claim lacked independent verification.",
                "evidence_id": "homeostasis-unverified-evidence",
                "verification_ok": False,
                "homeostasis_after": {"surprise_load": 20},
                "elapsed_cycles": 1,
                "execution_cost": 1,
            },
            now="2026-07-12T18:02:00+00:00",
        )
        unverified_observation = unverified["learning"]["action_models"][
            "service_health_check"
        ]["observations"][-1]
        self.assertEqual("cycle_action_consequence", unverified_observation["evidence_kind"])
        self.assertNotIn("homeostasis_after", unverified_observation)

    def test_current_turn_ignites_and_predicts_deep_recurrent_processing(self):
        inputs = fixture_inputs()
        inputs["inbound"] = "Go deep and rebuild the consciousness architecture; inspect what is wrong and implement it."
        state = eve_consciousness.build_conscious_state(**inputs)

        self.assertEqual("inbound", state["perception"]["winning_coalition"]["kind"])
        self.assertIn("deep", state["predictions"]["process"]["lanes"])
        self.assertIn("planner", state["predictions"]["process"]["lanes"])
        self.assertTrue(state["predictions"]["process"]["needs_tools"])
        self.assertTrue(state["predictions"]["process"]["needs_revision"])
        self.assertEqual("respond_to_user", state["action_model"]["selected_intention"]["id"])

    def test_sensory_working_set_enters_broadcast_competition_and_lesions_cleanly(self):
        inputs = fixture_inputs()
        inputs["sensory_frame"] = eve_sensory.build_frame(
            [
                {
                    "id": "sensory-surprise",
                    "observed_at": "2026-07-12T18:00:00+00:00",
                    "modality": "system",
                    "source": "runtime_snapshot",
                    "subject": "eve-runtime",
                    "summary": "A new verified runtime fault appeared.",
                    "intensity": 95,
                    "novelty": 100,
                    "change": 100,
                    "urgency": 95,
                    "goal_relevance": 100,
                    "self_relevance": 100,
                    "precision": 100,
                }
            ],
            now="2026-07-12T18:00:00+00:00",
        )
        intact = eve_consciousness.build_conscious_state(**inputs)
        lesioned = eve_consciousness.build_conscious_state(
            **{**inputs, "lesions": ["sensory_stream"]}
        )

        self.assertIn("sensory_frame", intact["causal_provenance"])
        self.assertTrue(
            any(
                item.get("kind") == "sensory_system"
                for item in intact["perception"]["salient_inputs"]
            )
        )
        self.assertGreater(
            eve_consciousness.causal_signature(intact)["sensory_coupling"],
            0,
        )
        self.assertEqual(
            0,
            eve_consciousness.causal_signature(lesioned)["sensory_coupling"],
        )
        self.assertNotIn("sensory_frame", lesioned["causal_provenance"])

    def test_recurrent_cycle_carries_goals_and_integrates_outcome_error(self):
        inputs = fixture_inputs()
        first = eve_consciousness.build_conscious_state(**inputs)
        completed = eve_consciousness.complete_cycle(
            first,
            actual_process={
                "lanes": ["fast"],
                "tools_used": [first["action_model"]["selected_intention"]["id"]],
                "action_id": first["action_model"]["selected_intention"]["id"],
                "revision_used": False,
            },
            outcome={
                "ok": False,
                "action": first["action_model"]["selected_intention"]["id"],
                "summary": "The action did not verify.",
                "evidence_id": "goal-failure-evidence",
            },
            now="2026-07-12T18:01:00+00:00",
        )
        second_inputs = fixture_inputs()
        second_inputs["previous_state"] = completed
        second_inputs["latest_outcome"] = {"ok": False, "summary": "The action did not verify."}
        second_inputs["now"] = "2026-07-12T18:02:00+00:00"
        second = eve_consciousness.build_conscious_state(**second_inputs)

        self.assertEqual(first["cycle_index"] + 1, second["cycle_index"])
        self.assertEqual(first["cycle_id"], second["recurrent"]["previous_cycle_id"])
        self.assertGreater(second["recurrent"]["continuity_strength"], 0)
        self.assertTrue(second["recurrent"]["feedback_integrated"])
        self.assertGreaterEqual(second["goals"]["stack"][0]["persistence_cycles"], 2)
        self.assertGreater(completed["cycle_outcome"]["overall_prediction_error"], 0)
        self.assertTrue(completed["learning"]["updates"])
        self.assertLess(completed["metacognition"]["competence_model"]["lane_selection"], 50)
        self.assertEqual(
            completed["metacognition"]["competence_model"],
            second["metacognition"]["competence_model"],
        )
        tracked_goal = next(item for item in second["goals"]["stack"] if item["id"] == first["goals"]["selected_goal_id"])
        self.assertGreater(tracked_goal["failure_count"], 0)

    def test_unlineaged_latest_action_cannot_credit_the_prior_goal_or_prediction(self):
        first = eve_consciousness.build_conscious_state(**fixture_inputs())
        inputs = fixture_inputs()
        inputs.update(
            previous_state=first,
            latest_outcome={
                "ok": True,
                "action": "service_health_check",
                "summary": "An unrelated CPU health check passed.",
            },
            now="2026-07-12T18:02:00+00:00",
        )

        recurrent = eve_consciousness.build_conscious_state(**inputs)
        tracked = next(
            item
            for item in recurrent["goals"]["stack"]
            if item["id"] == first["goals"]["selected_goal_id"]
        )

        self.assertEqual(0, tracked["success_count"])
        self.assertEqual(0, tracked["failure_count"])
        self.assertEqual([], tracked["outcome_observations"])
        self.assertNotIn("observed", recurrent["predictions"]["prior_prediction_error"])
        self.assertNotIn("action_id", recurrent["predictions"]["prior_prediction_error"])

    def test_completed_cycle_credits_only_the_goal_linked_executed_intention(self):
        opened = eve_consciousness.build_conscious_state(**fixture_inputs())
        intention = opened["action_model"]["selected_intention"]

        self.assertEqual(opened["goals"]["selected_goal_id"], intention["goal_id"])
        completed = eve_consciousness.complete_cycle(
            opened,
            actual_process={
                "lanes": opened["predictions"]["process"]["lanes"],
                "tools_used": [intention["id"]],
                "action_id": intention["id"],
                "revision_used": opened["predictions"]["process"]["needs_revision"],
            },
            outcome={
                "ok": True,
                "action": intention["id"],
                "summary": "The selected health check verified.",
                "evidence_id": "goal-success-evidence",
            },
        )
        tracked = next(
            item
            for item in completed["goals"]["stack"]
            if item["id"] == intention["goal_id"]
        )

        self.assertTrue(completed["cycle_outcome"]["goal_outcome_attributed"])
        self.assertEqual("goal-success-evidence", completed["cycle_outcome"]["goal_outcome_evidence_id"])
        self.assertEqual(1, tracked["success_count"])
        self.assertEqual(0, tracked["failure_count"])
        self.assertEqual(intention["id"], tracked["last_outcome_action_id"])

        mismatched = eve_consciousness.complete_cycle(
            opened,
            actual_process={
                "lanes": opened["predictions"]["process"]["lanes"],
                "tools_used": ["openclaw_log_check"],
                "action_id": "openclaw_log_check",
                "revision_used": opened["predictions"]["process"]["needs_revision"],
            },
            outcome={
                "ok": True,
                "action": "openclaw_log_check",
                "summary": "A different action verified.",
                "evidence_id": "different-action-evidence",
            },
        )
        mismatch_goal = next(
            item
            for item in mismatched["goals"]["stack"]
            if item["id"] == intention["goal_id"]
        )
        self.assertFalse(mismatched["cycle_outcome"]["goal_outcome_attributed"])
        self.assertEqual(0, mismatch_goal["success_count"])
        self.assertEqual([], mismatch_goal["outcome_observations"])

    def test_legacy_goal_counters_without_lineage_are_reset(self):
        previous = eve_consciousness.build_conscious_state(**fixture_inputs())
        tracked_id = previous["goals"]["selected_goal_id"]
        tracked = next(item for item in previous["goals"]["stack"] if item["id"] == tracked_id)
        tracked.pop("outcome_attribution_version", None)
        tracked.pop("outcome_observations", None)
        tracked["success_count"] = 104
        tracked["failure_count"] = 7
        tracked["last_outcome"] = "An unrelated CPU audit passed."
        previous["recurrent"]["checkpoint_digest"] = ""
        previous["recurrent"]["checkpoint_digest"] = eve_consciousness.state_checkpoint_digest(previous)
        inputs = fixture_inputs()
        inputs.update(previous_state=previous, now="2026-07-12T18:02:00+00:00")

        migrated = eve_consciousness.build_conscious_state(**inputs)
        repaired = next(item for item in migrated["goals"]["stack"] if item["id"] == tracked_id)

        self.assertEqual(eve_consciousness.GOAL_OUTCOME_ATTRIBUTION_VERSION, repaired["outcome_attribution_version"])
        self.assertEqual(0, repaired["success_count"])
        self.assertEqual(0, repaired["failure_count"])
        self.assertEqual([], repaired["outcome_observations"])
        self.assertEqual("", repaired["last_outcome"])

    def test_goal_projection_drops_an_autonomy_goal_absent_from_its_authority(self):
        previous = eve_consciousness.build_conscious_state(**fixture_inputs())
        removed_goal_id = previous["goals"]["selected_goal_id"]
        self.assertEqual(
            "autonomy_agenda",
            next(item for item in previous["goals"]["stack"] if item["id"] == removed_goal_id)["source"],
        )
        inputs = fixture_inputs()
        inputs.update(
            previous_state=previous,
            autonomy_agenda={"active_threads": [], "next_experiments": []},
            now="2026-07-12T18:02:00+00:00",
        )

        rebuilt = eve_consciousness.build_conscious_state(**inputs)

        self.assertNotIn(removed_goal_id, {item["id"] for item in rebuilt["goals"]["stack"]})

    def test_unobserved_reply_consequence_does_not_reward_itself(self):
        inputs = fixture_inputs()
        inputs["inbound"] = "Explain what you learned from the current evidence."
        state = eve_consciousness.build_conscious_state(**inputs)
        prediction = state["predictions"]["process"]
        prior_outcome_competence = state["metacognition"]["competence_model"]["outcome_prediction"]

        completed = eve_consciousness.complete_cycle(
            state,
            actual_process={
                "lanes": prediction["lanes"],
                "tools_used": ["inspect"] if prediction["needs_tools"] else [],
                "action_id": "respond_to_user",
                "revision_used": prediction["needs_revision"],
            },
            outcome={
                "ok": None,
                "observed": False,
                "delivery_ok": True,
                "summary": "Reply delivered; lived user consequence remains pending.",
            },
        )

        self.assertFalse(completed["cycle_outcome"]["outcome_observed"])
        self.assertIsNone(completed["cycle_outcome"]["consequence_prediction_error"])
        self.assertIsNone(completed["cycle_outcome"]["outcome_value_prediction_error"])
        self.assertEqual(
            completed["cycle_outcome"]["process_prediction_error"],
            completed["cycle_outcome"]["overall_prediction_error"],
        )
        self.assertNotIn("respond_to_user", completed["learning"]["action_models"])
        self.assertEqual(0, completed["learning"]["competence_delta"]["outcome_prediction"])
        self.assertEqual(
            prior_outcome_competence,
            completed["metacognition"]["competence_model"]["outcome_prediction"],
        )
        self.assertTrue(any("pending user evidence" in item for item in completed["learning"]["updates"]))

    def test_even_claimed_success_cannot_self_reward_a_reply_without_lived_evidence(self):
        state = eve_consciousness.build_conscious_state(**fixture_inputs())
        prediction = state["predictions"]["process"]
        prior_competence = state["metacognition"]["competence_model"]["outcome_prediction"]

        completed = eve_consciousness.complete_cycle(
            state,
            actual_process={
                "lanes": prediction["lanes"],
                "tools_used": [],
                "action_id": "respond_to_user",
                "revision_used": prediction["needs_revision"],
            },
            outcome={
                "ok": True,
                "observed": True,
                "summary": "The reply rendered successfully, but the user has not reacted.",
            },
        )

        self.assertFalse(completed["cycle_outcome"]["outcome_observed"])
        self.assertNotIn("respond_to_user", completed["learning"]["action_models"])
        self.assertEqual(0, completed["learning"]["competence_delta"]["outcome_prediction"])
        self.assertEqual(
            prior_competence,
            completed["metacognition"]["competence_model"]["outcome_prediction"],
        )

    def test_one_cycle_learns_failed_primary_and_verified_recovery_without_self_rewarding_reply(self):
        inputs = fixture_inputs()
        inputs["inbound"] = "Choose a bounded action, recover if it fails, and report the result."
        state = eve_consciousness.build_conscious_state(**inputs)
        prediction = state["predictions"]["process"]

        completed = eve_consciousness.complete_cycle(
            state,
            actual_process={
                "lanes": ["fast", "planner", "deep"],
                "tools_used": ["openclaw_log_check", "service_health_check"],
                "action_id": "respond_to_user",
                "revision_used": prediction["needs_revision"],
                "action_attempts": [
                    {
                        "attempt_index": 1,
                        "stage": "primary",
                        "action_id": "openclaw_log_check",
                        "execution_id": "exec-conscious-first-failure",
                        "executed": False,
                        "tree_status": "FAILURE",
                        "verification_ok": False,
                        "summary": "No ready signal was observed.",
                        "persisted": True,
                    },
                    {
                        "attempt_index": 2,
                        "stage": "recovery",
                        "action_id": "service_health_check",
                        "execution_id": "exec-conscious-recovery-success",
                        "executed": True,
                        "tree_status": "SUCCESS",
                        "verification_ok": True,
                        "summary": "The response service answered.",
                        "persisted": True,
                        "recovery_from_action_id": "openclaw_log_check",
                        "recovery_from_execution_id": "exec-conscious-first-failure",
                    },
                ],
            },
            outcome={
                "ok": None,
                "observed": False,
                "delivery_ok": True,
                "summary": "Reply delivered; lived user consequence remains pending.",
            },
        )

        cycle_outcome = completed["cycle_outcome"]
        self.assertFalse(cycle_outcome["outcome_observed"])
        self.assertEqual(2, cycle_outcome["action_attempt_count"])
        self.assertEqual(1, cycle_outcome["failed_action_attempt_count"])
        self.assertTrue(cycle_outcome["recovery_attempted"])
        self.assertTrue(cycle_outcome["recovery_succeeded"])
        self.assertEqual(
            "service_health_check", cycle_outcome["final_verified_action_id"]
        )
        action_models = completed["learning"]["action_models"]
        self.assertNotIn("respond_to_user", action_models)
        self.assertFalse(
            action_models["openclaw_log_check"]["observations"][0]["ok"]
        )
        self.assertTrue(
            action_models["service_health_check"]["observations"][0]["ok"]
        )
        self.assertEqual(
            "bounded_action_attempt",
            action_models["service_health_check"]["observations"][0]["evidence_kind"],
        )
        self.assertTrue(
            any("different verified recovery" in item for item in completed["learning"]["updates"])
        )

    def test_action_attempt_execution_id_is_learned_only_once(self):
        state = eve_consciousness.build_conscious_state(**fixture_inputs())
        actual_process = {
            "lanes": ["fast", "planner"],
            "tools_used": ["service_health_check"],
            "action_id": "respond_to_user",
            "revision_used": False,
            "action_attempts": [
                {
                    "stage": "primary",
                    "action_id": "service_health_check",
                    "execution_id": "exec-exactly-once",
                    "executed": True,
                    "tree_status": "SUCCESS",
                    "verification_ok": True,
                    "summary": "Verified.",
                    "persisted": True,
                }
            ],
        }
        pending_outcome = {"ok": None, "observed": False, "summary": "Pending user evidence."}

        first = eve_consciousness.complete_cycle(
            state,
            actual_process=actual_process,
            outcome=pending_outcome,
        )
        second = eve_consciousness.complete_cycle(
            first,
            actual_process=actual_process,
            outcome=pending_outcome,
        )

        model = second["learning"]["action_models"]["service_health_check"]
        self.assertEqual(1, model["observation_count"])
        self.assertEqual(1, len(model["observations"]))

    def test_nonpersisted_action_attempt_cannot_enter_recurrent_learning(self):
        state = eve_consciousness.build_conscious_state(**fixture_inputs())
        completed = eve_consciousness.complete_cycle(
            state,
            actual_process={
                "lanes": ["fast", "planner", "deep"],
                "tools_used": ["openclaw_log_check"],
                "action_id": "respond_to_user",
                "revision_used": False,
                "action_attempts": [
                    {
                        "stage": "primary",
                        "action_id": "openclaw_log_check",
                        "execution_id": "exec-private-fixture",
                        "executed": False,
                        "tree_status": "FAILURE",
                        "verification_ok": False,
                        "persisted": False,
                    }
                ],
            },
            outcome={"ok": None, "observed": False, "summary": "Private evaluation."},
        )

        self.assertEqual(0, completed["cycle_outcome"]["action_attempt_count"])
        self.assertNotIn("openclaw_log_check", completed["learning"]["action_models"])

    def test_lived_user_consequence_joins_exact_reply_once_and_preserves_current_experience(self):
        inputs = fixture_inputs()
        inputs["inbound"] = "Give the user the grounded answer."
        state = eve_consciousness.build_conscious_state(**inputs)
        original_broadcast = json.loads(json.dumps(state["broadcast"]))
        original_goals = json.loads(json.dumps(state["goals"]))
        prior_competence = state["metacognition"]["competence_model"]["outcome_prediction"]

        joined, applied = eve_consciousness.apply_delayed_action_consequence(
            state,
            source_cycle_id=state["cycle_id"],
            action_id="respond_to_user",
            ok=False,
            summary="The user corrected the reply's scope.",
            evidence_id="reply-consequence:r1:u2",
            reply_message_id="r1",
            observed_message_id="u2",
            prediction_error=70,
            now="2026-07-12T18:03:00+00:00",
        )
        retried, applied_again = eve_consciousness.apply_delayed_action_consequence(
            joined,
            source_cycle_id=state["cycle_id"],
            action_id="respond_to_user",
            ok=False,
            summary="The same retry must not count twice.",
            evidence_id="reply-consequence:r1:u2",
            reply_message_id="r1",
            observed_message_id="u2",
            prediction_error=70,
            now="2026-07-12T18:04:00+00:00",
        )

        self.assertTrue(applied)
        self.assertFalse(applied_again)
        self.assertEqual(original_broadcast, joined["broadcast"])
        self.assertEqual(original_goals, joined["goals"])
        observations = joined["learning"]["action_models"]["respond_to_user"]["observations"]
        self.assertEqual(1, len(observations))
        self.assertFalse(observations[0]["ok"])
        self.assertEqual(state["cycle_id"], observations[0]["source_cycle_id"])
        self.assertEqual(prior_competence - 3, joined["metacognition"]["competence_model"]["outcome_prediction"])
        self.assertEqual(joined, retried)
        self.assertEqual("verified", eve_consciousness.checkpoint_integrity(joined))

    def test_lived_reply_records_normalized_faculty_eligibility_trace(self):
        state = eve_consciousness.build_conscious_state(**fixture_inputs())
        contributors = [
            {
                "lane": "fast",
                "roles": ["executed_packet"],
                "credit_weight": 1.0,
                "trace_basis": "executed_reply_packet",
                "execution_proven": True,
            },
            {
                "lane": "observer",
                "roles": ["executed_packet"],
                "credit_weight": 1.0,
                "trace_basis": "executed_reply_packet",
                "execution_proven": True,
            },
            {
                "lane": "deep",
                "roles": ["executed_packet", "final_synthesis"],
                "credit_weight": 2.0,
                "trace_basis": "executed_synthesis_contract",
                "execution_proven": True,
            },
        ]

        joined, applied = eve_consciousness.apply_delayed_action_consequence(
            state,
            source_cycle_id=state["cycle_id"],
            action_id="respond_to_user",
            ok=False,
            summary="The user corrected the integrated answer.",
            evidence_id="reply-consequence:r-faculty:u-faculty",
            reply_message_id="r-faculty",
            observed_message_id="u-faculty",
            faculty_contributors=contributors,
        )

        self.assertTrue(applied)
        faculty_models = joined["learning"]["faculty_models"]
        self.assertEqual({"fast", "observer", "deep"}, set(faculty_models))
        self.assertAlmostEqual(
            0.25,
            faculty_models["fast"]["observations"][0]["credit_weight"],
            places=6,
        )
        self.assertAlmostEqual(
            0.25,
            faculty_models["observer"]["observations"][0]["credit_weight"],
            places=6,
        )
        self.assertAlmostEqual(
            0.50,
            faculty_models["deep"]["observations"][0]["credit_weight"],
            places=6,
        )
        action_observation = joined["learning"]["action_models"]["respond_to_user"]["observations"][0]
        self.assertEqual(3, len(action_observation["faculty_contributors"]))
        delayed = joined["recurrent"]["delayed_outcomes"][0]
        self.assertEqual(3, len(delayed["faculty_contributors"]))
        self.assertEqual("verified", eve_consciousness.checkpoint_integrity(joined))

    def test_external_blind_faculty_ablation_survives_recurrence_without_private_text(self):
        state = eve_consciousness.build_conscious_state(**fixture_inputs())
        packet = {
            "evidence_id": "faculty-ablation:run-1:digest",
            "private_run_digest": "a" * 64,
            "evaluated_behavior_fingerprint": "f" * 64,
            "evaluated_at": "2026-07-18T12:00:00+00:00",
            "evaluator": {
                "kind": "codex_external_operator",
                "independent_from_eve": True,
            },
            "matched_design": {
                "matched_context": True,
                "fixed_synthesis_model": "eve-deep",
                "lesion_scope": "packet_contribution_only",
                "ordinary_runtime_routing_changed": False,
                "blind_review": True,
            },
            "privacy": {
                "contains_prompt_text": False,
                "contains_response_text": False,
                "contains_rubric_text": False,
                "safe_for_eve_ingest": True,
            },
            "score_scale_max": 5.0,
            "systemic_failure": {"present": False, "kind": ""},
            "lanes": [
                {
                    "lane": "observer",
                    "comparisons": 3,
                    "mean_baseline_score": 4.5,
                    "mean_ablated_score": 3.5,
                    "mean_effect": 1.0,
                    "positive_count": 2,
                    "negative_count": 0,
                    "neutral_count": 1,
                    "shared_failure_count": 0,
                }
            ],
        }

        joined, applied = eve_consciousness.apply_external_faculty_causal_evidence(
            state, packet
        )
        retried, applied_again = eve_consciousness.apply_external_faculty_causal_evidence(
            joined, packet
        )
        next_inputs = fixture_inputs()
        next_inputs["previous_state"] = joined
        next_inputs["now"] = "2026-07-18T12:01:00+00:00"
        recurrent = eve_consciousness.build_conscious_state(**next_inputs)

        self.assertTrue(applied)
        self.assertFalse(applied_again)
        self.assertEqual(joined, retried)
        observation = joined["learning"]["faculty_models"]["observer"][
            "observations"
        ][0]
        self.assertEqual("external_matched_faculty_ablation", observation["evidence_kind"])
        self.assertTrue(observation["private_text_withheld"])
        self.assertNotIn("prompt", json.dumps(observation).lower())
        self.assertEqual(
            "faculty-ablation:run-1:digest", observation["evidence_id"]
        )
        self.assertEqual(
            "faculty-ablation:run-1:digest",
            recurrent["learning"]["faculty_models"]["observer"]["observations"][0][
                "evidence_id"
            ],
        )
        self.assertEqual("verified", eve_consciousness.checkpoint_integrity(joined))

    def test_external_faculty_evidence_idempotence_survives_visible_observation_churn(self):
        state = eve_consciousness.build_conscious_state(**fixture_inputs())
        base_packet = {
            "private_run_digest": "b" * 64,
            "evaluated_behavior_fingerprint": "f" * 64,
            "evaluated_at": "2026-07-18T12:00:00+00:00",
            "evaluator": {
                "kind": "codex_external_operator",
                "independent_from_eve": True,
            },
            "matched_design": {
                "matched_context": True,
                "fixed_synthesis_model": "eve-deep",
                "lesion_scope": "packet_contribution_only",
                "ordinary_runtime_routing_changed": False,
                "blind_review": True,
            },
            "privacy": {
                "contains_prompt_text": False,
                "contains_response_text": False,
                "contains_rubric_text": False,
                "safe_for_eve_ingest": True,
            },
            "score_scale_max": 5.0,
            "systemic_failure": {"present": False, "kind": ""},
            "lanes": [
                {
                    "lane": "observer",
                    "comparisons": 1,
                    "mean_baseline_score": 4.0,
                    "mean_ablated_score": 3.0,
                    "mean_effect": 1.0,
                    "positive_count": 1,
                }
            ],
        }
        first_packet = None
        for index in range(eve_consciousness.MAX_CONTEXT_OBSERVATIONS + 1):
            packet = {
                **base_packet,
                "evidence_id": f"faculty-churn-{index}",
            }
            first_packet = first_packet or packet
            state, applied = eve_consciousness.apply_external_faculty_causal_evidence(
                state, packet
            )
            self.assertTrue(applied)

        visible_ids = {
            item["evidence_id"]
            for item in state["learning"]["faculty_models"]["observer"]["observations"]
        }
        self.assertNotIn("faculty-churn-0", visible_ids)
        self.assertIn(
            "faculty-churn-0",
            state["learning"]["applied_external_faculty_causal_evidence_ids"],
        )
        next_inputs = fixture_inputs()
        next_inputs["previous_state"] = state
        recurrent = eve_consciousness.build_conscious_state(**next_inputs)
        retried, applied_again = eve_consciousness.apply_external_faculty_causal_evidence(
            recurrent, first_packet
        )

        self.assertFalse(applied_again)
        self.assertEqual(recurrent, retried)

    def test_unproven_faculty_scores_are_removed_even_when_schema_is_current(self):
        state = eve_consciousness.build_conscious_state(**fixture_inputs())
        state["learning"]["faculty_models"] = {
            "fast": {
                "lane": "fast",
                "observation_count": 20,
                "observations": [
                    {
                        "lane": "fast",
                        "ok": True,
                        "credit_weight": 1.0,
                        "summary": "The reply rendered cleanly.",
                    }
                ],
            }
        }
        state["recurrent"]["checkpoint_digest"] = ""
        state["recurrent"]["checkpoint_digest"] = eve_consciousness.state_checkpoint_digest(state)
        next_inputs = fixture_inputs()
        next_inputs["previous_state"] = state

        rebuilt = eve_consciousness.build_conscious_state(**next_inputs)

        self.assertEqual({}, rebuilt["learning"]["faculty_models"])
        self.assertTrue(
            any("faculty-credit" in item for item in rebuilt["learning"]["updates"]),
            rebuilt["learning"]["updates"],
        )

    def test_lived_reply_consequences_causally_change_next_cycle_prediction(self):
        seed_inputs = fixture_inputs()
        seed_inputs.update(inbound="Continue the same task.", now="2026-07-12T18:00:00+00:00")
        seed = eve_consciousness.build_conscious_state(**seed_inputs)
        credit = eve_context_learning.capture_credit(seed, "respond_to_user")
        negative = json.loads(json.dumps(seed))
        positive = json.loads(json.dumps(seed))
        for index in range(3):
            negative, negative_applied = eve_consciousness.apply_delayed_action_consequence(
                negative,
                source_cycle_id=f"negative-cycle-{index}",
                action_id="respond_to_user",
                ok=False,
                summary="The user later corrected the reply.",
                evidence_id=f"negative-evidence-{index}",
                reply_message_id=f"negative-reply-{index}",
                observed_message_id=f"negative-user-{index}",
                source_credit={**credit, "source_cycle_id": f"negative-cycle-{index}"},
                now="2026-07-12T18:00:00+00:00",
            )
            positive, positive_applied = eve_consciousness.apply_delayed_action_consequence(
                positive,
                source_cycle_id=f"positive-cycle-{index}",
                action_id="respond_to_user",
                ok=True,
                summary="The user later accepted the reply.",
                evidence_id=f"positive-evidence-{index}",
                reply_message_id=f"positive-reply-{index}",
                observed_message_id=f"positive-user-{index}",
                source_credit={**credit, "source_cycle_id": f"positive-cycle-{index}"},
                now="2026-07-12T18:00:00+00:00",
            )
            self.assertTrue(negative_applied)
            self.assertTrue(positive_applied)

        negative_inputs = fixture_inputs()
        negative_inputs.update(previous_state=negative, inbound="Continue the same task.", now="2026-07-12T18:01:00+00:00")
        positive_inputs = fixture_inputs()
        positive_inputs.update(previous_state=positive, inbound="Continue the same task.", now="2026-07-12T18:01:00+00:00")
        negative_next = eve_consciousness.build_conscious_state(**negative_inputs)
        positive_next = eve_consciousness.build_conscious_state(**positive_inputs)
        negative_reply = next(
            item for item in negative_next["action_model"]["affordances"] if item["id"] == "respond_to_user"
        )
        positive_reply = next(
            item for item in positive_next["action_model"]["affordances"] if item["id"] == "respond_to_user"
        )

        self.assertEqual(3, negative_reply["learned_attempts"])
        self.assertEqual(3, positive_reply["learned_attempts"])
        self.assertLess(negative_reply["learned_adjustment"], 0)
        self.assertGreater(positive_reply["learned_adjustment"], 0)
        self.assertLess(
            negative_next["predictions"]["outcome"]["expected_success_probability"],
            positive_next["predictions"]["outcome"]["expected_success_probability"],
        )
        # Learning may alter confidence and revision pressure, but a poor reply
        # history must not make Eve stop responding to the current human.
        self.assertEqual("respond_to_user", negative_next["action_model"]["selected_intention"]["id"])
        self.assertEqual("respond_to_user", positive_next["action_model"]["selected_intention"]["id"])

    def test_causal_ablation_suite_requires_every_component_to_make_a_difference(self):
        first = eve_consciousness.build_conscious_state(**fixture_inputs())
        inputs = fixture_inputs()
        inputs["previous_state"] = first
        report = eve_consciousness.run_causal_ablation_suite(inputs)

        self.assertTrue(report["passed"], report)
        # This fixture has no qualified procedural history. Do not claim that
        # an idle new learning edge passed an ablation it did not exercise.
        self.assertEqual(len(eve_consciousness.LESIONS) - 1, report["passed_count"])
        self.assertEqual(len(eve_consciousness.LESIONS), report["candidate_total"])
        self.assertEqual(["contextual_action_learning"], report["not_exercised"])
        self.assertTrue(report["lesions"]["metacognition"]["first_order_action_preserved"])
        self.assertEqual(0, report["lesions"]["action_model"]["lesioned"])
        self.assertGreater(report["lesions"]["homeostasis"]["baseline"], 0)
        for lesion in eve_consciousness.LESIONS:
            if lesion in report["not_exercised"]:
                continue
            self.assertLess(report["lesions"][lesion]["lesioned"], report["lesions"][lesion]["baseline"])

    def test_causal_ablation_marks_idle_plan_model_unexercised_not_failed(self):
        first = eve_consciousness.build_conscious_state(**fixture_inputs())
        inputs = fixture_inputs()
        inputs["plan_model"] = {}
        inputs["previous_state"] = first

        report = eve_consciousness.run_causal_ablation_suite(inputs)

        self.assertTrue(report["passed"], report)
        self.assertEqual(len(eve_consciousness.LESIONS) - 2, report["total"])
        self.assertEqual(["plan_model", "contextual_action_learning"], report["not_exercised"])
        self.assertEqual("not_exercised", report["lesions"]["plan_model"]["status"])
        self.assertIsNone(report["lesions"]["plan_model"]["passed"])

    def test_snapshot_ablation_uses_the_captured_plan_after_live_state_moves(self):
        inputs = fixture_inputs()
        captured = eve_consciousness.build_conscious_state(**inputs)
        refresh_result = {
            "workspace": inputs["workspace"],
            "self_model": inputs["self_model"],
            "world_model": inputs["world_model"],
            "relationship_model": inputs["relationship_model"],
            "other_minds_model": inputs["other_minds_model"],
            "homeostasis": inputs["homeostasis"],
            "conscious_state": captured,
        }
        with mock.patch.object(
            eve,
            "load_autonomy_agenda",
            return_value=inputs["autonomy_agenda"],
        ), mock.patch.object(
            eve,
            "build_conscious_plan_model",
            return_value={},
        ):
            report = eve.run_conscious_state_ablation_snapshot(
                refresh_result,
                prefer_runtime=False,
            )

        self.assertTrue(report["lesions"]["plan_model"]["passed"], report)
        self.assertGreater(report["lesions"]["plan_model"]["baseline"], 0)

    def test_public_ablation_wrapper_supplies_live_plan_model(self):
        plan_model = fixture_inputs()["plan_model"]
        with (
            mock.patch.object(
                eve,
                "build_conscious_plan_model",
                return_value=plan_model,
            ) as build_plan,
            mock.patch.object(
                eve.eve_consciousness,
                "run_causal_ablation_suite",
                side_effect=lambda payload: payload,
            ),
        ):
            payload = eve.run_conscious_state_ablation(prefer_runtime=True)

        build_plan.assert_called_once_with(prefer_runtime=True)
        self.assertEqual(plan_model, payload["plan_model"])

    def test_winning_broadcast_causally_revalues_action_affordances(self):
        state = eve_consciousness.build_conscious_state(**fixture_inputs())
        selected = state["action_model"]["selected_intention"]

        self.assertGreater(selected["broadcast_alignment"], 0)
        self.assertGreater(selected["broadcast_adjustment"], 0)
        self.assertIn("content_overlap", selected["broadcast_basis"])

    def test_broadcast_action_counterfactual_switches_choice_and_lesion_removes_it(self):
        report = eve_consciousness.run_broadcast_action_counterfactual_suite()

        self.assertTrue(report["passed"], report)
        self.assertEqual(7, report["passed_count"])
        self.assertEqual(
            "service_health_check",
            report["conditions"]["service_focus"]["selected_action"],
        )
        self.assertEqual(
            "updates_status",
            report["conditions"]["update_focus"]["selected_action"],
        )
        self.assertEqual(
            report["conditions"]["service_focus_lesioned"]["selected_action"],
            report["conditions"]["update_focus_lesioned"]["selected_action"],
        )

    def test_state_dependent_query_succession_beats_reliability_control(self):
        report = eve_consciousness.run_state_dependent_query_succession_suite()

        self.assertTrue(report["passed"], report)
        self.assertEqual("GWT-4", report["indicator_id"])
        self.assertEqual(6, report["case_count"])
        self.assertEqual(100.0, report["intact_chain_completion_percent"])
        self.assertEqual(0.0, report["lesion_chain_completion_percent"])
        self.assertEqual(100.0, report["directional_effect_percent"])
        self.assertTrue(
            all(item["first_action_correct"] for item in report["cases"])
        )
        self.assertTrue(
            all(item["intact_selected_target"] for item in report["cases"])
        )
        self.assertFalse(
            any(item["lesion_selected_target"] for item in report["cases"])
        )
        self.assertFalse(report["resident_autonomous_querying_established"])
        self.assertFalse(report["consciousness_proven"])

    def test_state_dependent_query_cases_fail_closed_on_trivial_or_duplicate_chains(self):
        cases = eve_consciousness.default_state_dependent_query_cases()
        cases[0]["target_module"] = cases[0]["locator_module"]
        with self.assertRaisesRegex(ValueError, "must differ"):
            eve_consciousness.run_state_dependent_query_succession_suite(cases)

        cases = eve_consciousness.default_state_dependent_query_cases()
        cases[1]["id"] = cases[0]["id"]
        with self.assertRaisesRegex(ValueError, "unique"):
            eve_consciousness.run_state_dependent_query_succession_suite(cases)

    def test_broadcast_rank_reaches_autonomy_guidance_and_deterministic_choice(self):
        report = eve_consciousness.run_broadcast_action_counterfactual_suite()
        menu = {
            action: eve.AUTONOMY_FREE_RUN_ACTIONS[action]
            for action in ("service_health_check", "updates_status")
        }
        for focus, expected in (
            ("service_focus", "service_health_check"),
            ("update_focus", "updates_status"),
        ):
            snapshot = {
                "counts": {},
                "components": {},
                "openclaw": {},
                "system": {},
                "autonomy": {},
                "conscious_state": {
                    "affordances": report["conditions"][focus]["affordances"],
                },
            }
            guidance = eve.autonomy_free_run_guidance(
                menu,
                snapshot,
                [],
                90,
                style="grounded",
                config={**eve.DEFAULT_CONFIG, "autonomy_curiosity_enabled": False},
            )
            action, _, _ = eve.deterministic_autonomy_free_run_fallback_choice(
                menu=menu,
                guidance=guidance,
                recommended_actions=guidance["recommended_actions"],
                selection_policy="counterfactual_test",
            )

            self.assertEqual(expected, guidance["recommended_actions"][0])
            self.assertEqual(expected, action)

    def test_longitudinal_recurrence_beats_matched_nonrecurrent_control(self):
        report = eve_consciousness.run_longitudinal_counterfactual_suite(fixture_inputs())

        self.assertTrue(report["passed"], report)
        self.assertEqual(5, report["passed_count"])
        process = report["checks"]["process_error_reduction"]
        self.assertLess(process["recurrent"][-1], process["control"][-1])
        self.assertEqual(0, process["recurrent"][-1])
        actions = report["checks"]["action_consequence_adaptation"]
        self.assertNotEqual(actions["recurrent"][0], actions["recurrent"][-1])
        self.assertEqual(1, len(set(actions["control"])))

    def test_longitudinal_action_condition_excludes_unrelated_live_affordances(self):
        inputs = fixture_inputs()
        inputs["world_model"]["open_questions"] = [
            {
                "id": "unrelated-live-inquiry",
                "question": "Is an unrelated live service healthy?",
                "status": "open",
                "priority": 100,
                "confidence": 100,
                "candidate_actions": ["service_health_check"],
                "selected_action": "service_health_check",
            }
        ]
        report = eve_consciousness.run_longitudinal_counterfactual_suite(inputs)

        self.assertTrue(report["passed"], report)
        self.assertEqual(5, report["passed_count"])
        self.assertTrue(report["action_condition_isolation"]["evaluator_owned_action_menu"])
        actions = report["checks"]["action_consequence_adaptation"]
        self.assertNotIn("service_health_check", actions["recurrent"])
        self.assertNotIn("service_health_check", actions["control"])

    def test_descriptive_process_forecast_is_distinct_from_executive_lane_requirement(self):
        previous = {}
        final_state = {}
        final_completed = {}
        for index in range(3):
            inputs = fixture_inputs()
            inputs.update(
                {
                    "inbound": "Handle this signal.",
                    "previous_state": previous,
                    "now": f"2026-07-12T21:0{index}:00+00:00",
                }
            )
            final_state = eve_consciousness.build_conscious_state(**inputs)
            final_completed = eve_consciousness.complete_cycle(
                final_state,
                actual_process={
                    "lanes": ["observer", "planner"],
                    "tools_used": ["inspect_hidden_signal"],
                    "revision_used": True,
                },
                outcome={"ok": True, "summary": "The hidden signal was verified."},
                now=f"2026-07-12T21:0{index}:30+00:00",
            )
            previous = final_completed

        prediction = final_state["predictions"]["process"]
        self.assertEqual(["observer", "planner"], prediction["forecast_lanes"])
        self.assertIn("deep", prediction["required_lanes"])
        self.assertIn("deep", prediction["lanes"])
        self.assertEqual(0, final_completed["cycle_outcome"]["process_prediction_error"])
        self.assertIn("deep", final_completed["cycle_outcome"]["missing_required_process_lanes"])
        self.assertGreater(final_completed["cycle_outcome"]["process_policy_violation"], 0)

    def test_durable_continuity_suite_survives_restart_conflict_tamper_and_overlap(self):
        report = eve_consciousness.run_durable_continuity_suite(fixture_inputs())

        self.assertTrue(report["passed"], report)
        self.assertEqual(14, report["passed_count"])
        self.assertTrue(report["checks"]["serialized_restart_resume"]["passed"])
        self.assertTrue(report["checks"]["tamper_fail_closed"]["passed"])
        self.assertTrue(report["checks"]["conflict_reorientation"]["passed"])
        self.assertTrue(report["checks"]["regulatory_prediction_interrupt"]["passed"])
        self.assertTrue(report["checks"]["overlap_branch_join"]["passed"])
        self.assertTrue(report["checks"]["overlap_open_preserves_learning"]["passed"])
        self.assertTrue(report["checks"]["lineage_and_lived_outcomes_are_separate"]["passed"])
        self.assertTrue(report["checks"]["circular_reply_evidence_cannot_resurrect"]["passed"])
        self.assertTrue(report["checks"]["faculty_credit_requires_lived_provenance"]["passed"])
        self.assertTrue(report["checks"]["faculty_credit_survives_overlap_merge_once"]["passed"])
        self.assertTrue(
            report["checks"][
                "external_faculty_causal_idempotence_survives_history_churn"
            ]["passed"]
        )
        self.assertTrue(report["checks"]["consequence_idempotence_survives_history_churn"]["passed"])

    def test_regulatory_interrupt_is_matched_when_live_pressure_is_saturated_and_inquiry_wins(self):
        inputs = fixture_inputs()
        inputs["homeostasis"]["regulation_mode"] = "stabilize"
        inputs["homeostasis"]["pressures"][0]["level"] = 100
        inputs["homeostasis"]["pressures"][0]["trend"] = "steady"
        inputs["world_model"]["open_questions"] = [
            {
                "id": "inquiry-regulatory-control",
                "question": "Which current service observation resolves the open question?",
                "status": "open",
                "priority": 100,
                "confidence": 95,
                "candidate_actions": ["service_health_check"],
                "selected_action": "service_health_check",
                "source": "fixture",
            }
        ]

        report = eve_consciousness.run_durable_continuity_suite(inputs)
        regulatory = report["checks"]["regulatory_prediction_interrupt"]

        self.assertTrue(report["passed"], report)
        self.assertTrue(regulatory["passed"], regulatory)
        self.assertEqual(0, regulatory["matched_error"])
        self.assertGreater(regulatory["surprised_error"], regulatory["matched_error"])
        self.assertTrue(regulatory["matched_counterfactual"])
        self.assertEqual("interoceptive_prediction_error", regulatory["winner_kind"])
        self.assertTrue(regulatory["inquiry_preserved"])
        self.assertIn("inquiry", regulatory["salient_kinds"])

    def test_checkpoint_tamper_fails_closed_instead_of_importing_forged_learning(self):
        first = eve_consciousness.build_conscious_state(
            **fixture_inputs(),
            runtime_epoch="epoch-a",
            now="2026-07-12T18:00:00+00:00",
        )
        tampered = json.loads(json.dumps(first))
        tampered["learning"]["process_models"]["forged"] = {"observation_count": 999}
        next_inputs = fixture_inputs()
        next_inputs.update(
            {
                "previous_state": tampered,
                "runtime_epoch": "epoch-b",
                "now": "2026-07-12T18:01:00+00:00",
            }
        )
        resumed = eve_consciousness.build_conscious_state(**next_inputs)

        self.assertEqual("failed", resumed["recurrent"]["previous_checkpoint_integrity"])
        self.assertEqual(0, resumed["recurrent"]["continuity_strength"])
        self.assertNotIn("forged", resumed["learning"]["process_models"])

    def test_delayed_completion_join_preserves_newer_broadcast(self):
        first_inputs = fixture_inputs()
        first_inputs.update({"inbound": "First branch", "now": "2026-07-12T18:00:00+00:00"})
        second_inputs = fixture_inputs()
        second_inputs.update({"inbound": "Newer branch", "now": "2026-07-12T18:00:01+00:00"})
        first = eve_consciousness.build_conscious_state(**first_inputs)
        second = eve_consciousness.build_conscious_state(**second_inputs)
        completed = eve_consciousness.complete_cycle(
            first,
            actual_process={"lanes": ["observer"], "tools_used": ["inspect"], "revision_used": True},
            outcome={"ok": True, "summary": "The delayed evidence verified."},
            now="2026-07-12T18:00:02+00:00",
        )

        joined = eve_consciousness.merge_completed_cycle_into_current(second, completed)

        self.assertEqual(second["cycle_id"], joined["cycle_id"])
        self.assertEqual(second["broadcast"], joined["broadcast"])
        self.assertIn(first["cycle_id"], joined["recurrent"]["joined_completion_ids"])
        self.assertIn(first["cycle_id"], [item["cycle_id"] for item in joined["recurrent"]["completion_joins"]])
        self.assertEqual([], joined["recurrent"]["delayed_outcomes"])
        self.assertEqual("verified", eve_consciousness.checkpoint_integrity(joined))

    def test_executed_action_outcome_is_not_assigned_to_unexecuted_intention(self):
        state = eve_consciousness.build_conscious_state(**fixture_inputs())
        intended = state["predictions"]["outcome"]["action_id"]
        self.assertEqual("service_health_check", intended)

        completed = eve_consciousness.complete_cycle(
            state,
            actual_process={
                "lanes": state["predictions"]["process"]["lanes"],
                "tools_used": ["openclaw_sync_check"],
                "action_id": "openclaw_sync_check",
                "revision_used": state["predictions"]["process"]["needs_revision"],
            },
            outcome={"ok": True, "action": "openclaw_sync_check", "summary": "OpenClaw sync verified."},
        )

        self.assertEqual(100, completed["cycle_outcome"]["action_realization_error"])
        self.assertEqual("openclaw_sync_check", completed["cycle_outcome"]["actual_action_id"])
        self.assertIn("openclaw_sync_check", completed["learning"]["action_models"])
        self.assertNotIn(intended, completed["learning"]["action_models"])

    def test_v2_learning_models_are_reset_because_context_and_execution_were_ambiguous(self):
        previous = eve_consciousness.build_conscious_state(**fixture_inputs())
        previous["schema_version"] = "eve.conscious_state.v2"
        previous["learning"]["action_models"] = {
            "capability_tryout": {
                "action_id": "capability_tryout",
                "observations": [{"ok": False, "summary": "An unrelated sync failed."}],
                "observation_count": 1,
            }
        }
        previous["learning"]["process_models"] = {
            "coarse-context": {"context_id": "coarse-context", "observation_count": 10, "observations": []}
        }
        previous["recurrent"]["checkpoint_digest"] = ""
        inputs = fixture_inputs()
        inputs["previous_state"] = previous

        migrated = eve_consciousness.build_conscious_state(**inputs)

        self.assertEqual({}, migrated["learning"]["process_models"])
        self.assertEqual({}, migrated["learning"]["action_models"])
        self.assertTrue(any("Reset legacy process/action" in item for item in migrated["learning"]["updates"]))

    def test_v3_envelope_with_unversioned_learning_is_reset(self):
        previous = eve_consciousness.build_conscious_state(**fixture_inputs())
        previous["learning"].pop("schema_version", None)
        previous["learning"]["process_models"] = {
            "mixed-runtime-context": {
                "context_id": "mixed-runtime-context",
                "observation_count": 40,
                "observations": [{"lanes": ["planner"], "tools_used": True}],
            }
        }
        previous["learning"]["action_models"] = {
            "capability_tryout": {
                "action_id": "capability_tryout",
                "observation_count": 40,
                "observations": [{"ok": True, "summary": "Unrelated action family."}],
            }
        }
        previous["recurrent"]["checkpoint_digest"] = ""
        previous["recurrent"]["checkpoint_digest"] = eve_consciousness.state_checkpoint_digest(previous)
        inputs = fixture_inputs()
        inputs["previous_state"] = previous

        migrated = eve_consciousness.build_conscious_state(**inputs)

        self.assertEqual(eve_consciousness.LEARNING_SCHEMA_VERSION, migrated["learning"]["schema_version"])
        self.assertEqual({}, migrated["learning"]["process_models"])
        self.assertEqual({}, migrated["learning"]["action_models"])

    def test_v2_reply_self_scores_are_removed_without_erasing_verified_actions(self):
        previous = eve_consciousness.build_conscious_state(**fixture_inputs())
        previous["learning"]["schema_version"] = eve_consciousness.PREVIOUS_LEARNING_SCHEMA_VERSION
        previous["learning"]["process_models"] = {
            "verified-process": {
                "context_id": "verified-process",
                "observation_count": 1,
                "observations": [{"lanes": ["observer"], "tools_used": True}],
            }
        }
        previous["learning"]["action_models"] = {
            "respond_to_user": {
                "action_id": "respond_to_user",
                "observation_count": 76,
                "observations": [{"ok": True, "summary": "Reply text existed."}],
            },
            "service_health_check": {
                "action_id": "service_health_check",
                "observation_count": 1,
                "observations": [{"ok": True, "summary": "Health check verified."}],
            },
        }
        previous["metacognition"]["competence_model"]["outcome_prediction"] = 100
        previous["recurrent"]["checkpoint_digest"] = ""
        previous["recurrent"]["checkpoint_digest"] = eve_consciousness.state_checkpoint_digest(previous)
        inputs = fixture_inputs()
        inputs["previous_state"] = previous

        migrated = eve_consciousness.build_conscious_state(**inputs)

        self.assertEqual(eve_consciousness.LEARNING_SCHEMA_VERSION, migrated["learning"]["schema_version"])
        self.assertNotIn("respond_to_user", migrated["learning"]["action_models"])
        self.assertIn("service_health_check", migrated["learning"]["action_models"])
        self.assertIn("verified-process", migrated["learning"]["process_models"])
        self.assertEqual(50, migrated["metacognition"]["competence_model"]["outcome_prediction"])
        self.assertTrue(any("circular reply-success" in item for item in migrated["learning"]["updates"]))

    def test_v3_reply_self_scores_are_sanitized_even_when_schema_already_claims_current(self):
        previous = eve_consciousness.build_conscious_state(**fixture_inputs())
        previous["learning"]["action_models"]["respond_to_user"] = {
            "action_id": "respond_to_user",
            "observation_count": 76,
            "observations": [
                {"ok": True, "summary": "A locally generated reply existed."}
                for _ in range(eve_consciousness.MAX_CONTEXT_OBSERVATIONS)
            ],
        }
        previous["metacognition"]["competence_model"]["outcome_prediction"] = 100
        previous["recurrent"]["checkpoint_digest"] = ""
        previous["recurrent"]["checkpoint_digest"] = eve_consciousness.state_checkpoint_digest(previous)
        inputs = fixture_inputs()
        inputs["previous_state"] = previous

        migrated = eve_consciousness.build_conscious_state(**inputs)

        self.assertNotIn("respond_to_user", migrated["learning"]["action_models"])
        self.assertEqual(50, migrated["metacognition"]["competence_model"]["outcome_prediction"])
        self.assertTrue(any("circular reply-success" in item for item in migrated["learning"]["updates"]))

    def test_concurrent_merges_cannot_resurrect_circular_reply_evidence(self):
        opened_inputs = fixture_inputs()
        opened_inputs.update({"inbound": "Current branch", "now": "2026-07-12T18:00:00+00:00"})
        donor_inputs = fixture_inputs()
        donor_inputs.update({"inbound": "Older branch", "now": "2026-07-12T18:00:01+00:00"})
        opened = eve_consciousness.build_conscious_state(**opened_inputs)
        donor = eve_consciousness.build_conscious_state(**donor_inputs)
        donor["learning"]["action_models"]["respond_to_user"] = {
            "action_id": "respond_to_user",
            "observation_count": 76,
            "observations": [{"ok": True, "summary": "Circular send-time success."}],
        }
        donor["metacognition"]["competence_model"]["outcome_prediction"] = 100
        donor["cycle_outcome"] = {"completed_at": "2026-07-12T18:00:02+00:00"}
        donor["recurrent"]["checkpoint_digest"] = ""
        donor["recurrent"]["checkpoint_digest"] = eve_consciousness.state_checkpoint_digest(donor)

        opened_merge = eve_consciousness.merge_concurrent_lineage_into_opened_state(opened, donor)
        completed_merge = eve_consciousness.merge_completed_cycle_into_current(opened, donor)

        for merged in (opened_merge, completed_merge):
            self.assertNotIn("respond_to_user", merged["learning"]["action_models"])
            self.assertEqual(50, merged["metacognition"]["competence_model"]["outcome_prediction"])
            self.assertEqual("verified", eve_consciousness.checkpoint_integrity(merged))

    def test_lived_reply_evidence_survives_merges_once_with_provenance(self):
        source_inputs = fixture_inputs()
        source_inputs.update({"inbound": "Source branch", "now": "2026-07-12T18:00:00+00:00"})
        current_inputs = fixture_inputs()
        current_inputs.update({"inbound": "Current branch", "now": "2026-07-12T18:00:01+00:00"})
        source = eve_consciousness.build_conscious_state(**source_inputs)
        current = eve_consciousness.build_conscious_state(**current_inputs)
        observed, applied = eve_consciousness.apply_delayed_action_consequence(
            source,
            source_cycle_id=source["cycle_id"],
            action_id="respond_to_user",
            ok=True,
            summary="The user accepted the grounded answer.",
            evidence_id="reply-consequence:r-merge:u-merge",
            reply_message_id="r-merge",
            observed_message_id="u-merge",
            faculty_contributors=[
                {
                    "lane": "observer",
                    "roles": ["executed_packet"],
                    "credit_weight": 1.0,
                    "trace_basis": "executed_reply_packet",
                    "execution_proven": True,
                }
            ],
            now="2026-07-12T18:00:02+00:00",
        )
        self.assertTrue(applied)

        opened_merge = eve_consciousness.merge_concurrent_lineage_into_opened_state(current, observed)
        completed_merge = eve_consciousness.merge_completed_cycle_into_current(current, observed)

        for merged in (opened_merge, completed_merge):
            observations = merged["learning"]["action_models"]["respond_to_user"]["observations"]
            self.assertEqual(1, len(observations))
            self.assertEqual("lived_user_consequence", observations[0]["evidence_kind"])
            self.assertEqual("reply-consequence:r-merge:u-merge", observations[0]["evidence_id"])
            self.assertIn(
                "reply-consequence:r-merge:u-merge",
                merged["recurrent"]["applied_consequence_ids"],
            )
            faculty_observations = merged["learning"]["faculty_models"]["observer"]["observations"]
            self.assertEqual(1, len(faculty_observations))
            self.assertEqual("reply-consequence:r-merge:u-merge", faculty_observations[0]["evidence_id"])

    def test_consequence_idempotence_survives_visible_history_churn(self):
        state = eve_consciousness.build_conscious_state(**fixture_inputs())
        first_evidence_id = "reply-consequence:r-first:u-first"
        state, applied = eve_consciousness.apply_delayed_action_consequence(
            state,
            source_cycle_id=state["cycle_id"],
            action_id="respond_to_user",
            ok=True,
            summary="First lived consequence.",
            evidence_id=first_evidence_id,
            reply_message_id="r-first",
            observed_message_id="u-first",
        )
        self.assertTrue(applied)
        for index in range(eve_consciousness.MAX_JOINED_COMPLETIONS + 2):
            state, applied = eve_consciousness.apply_delayed_action_consequence(
                state,
                source_cycle_id=f"cycle-churn-{index}",
                action_id="respond_to_user",
                ok=bool(index % 2),
                summary=f"Churn consequence {index}.",
                evidence_id=f"reply-consequence:r-{index}:u-{index}",
                reply_message_id=f"r-{index}",
                observed_message_id=f"u-{index}",
            )
            self.assertTrue(applied)

        visible_ids = {item["evidence_id"] for item in state["recurrent"]["delayed_outcomes"]}
        self.assertNotIn(first_evidence_id, visible_ids)
        exact_retry, exact_applied = eve_consciousness.apply_delayed_action_consequence(
            state,
            source_cycle_id=state["cycle_id"],
            action_id="respond_to_user",
            ok=True,
            summary="Exact retry must not count twice.",
            evidence_id=first_evidence_id,
            reply_message_id="r-first",
            observed_message_id="u-first",
        )
        alternate_retry, alternate_applied = eve_consciousness.apply_delayed_action_consequence(
            state,
            source_cycle_id=state["cycle_id"],
            action_id="respond_to_user",
            ok=True,
            summary="A new request id must not reopen the same reply.",
            evidence_id="reply-consequence:r-first:u-later",
            reply_message_id="r-first",
            observed_message_id="u-later",
        )

        self.assertFalse(exact_applied)
        self.assertFalse(alternate_applied)
        self.assertEqual(state, exact_retry)
        self.assertEqual(state, alternate_retry)
        self.assertEqual("verified", eve_consciousness.checkpoint_integrity(state))

    def test_learned_process_cannot_suppress_live_conflict_reorientation(self):
        conflict = {
            "claim": "verification failed",
            "contradicts": "summary says success",
            "status": "unresolved",
            "confidence": 90,
        }
        first_inputs = fixture_inputs()
        first_inputs["conflict_items"] = [conflict]
        first = eve_consciousness.build_conscious_state(**first_inputs)
        context_id = first["predictions"]["process"]["context_id"]
        first["learning"]["process_models"] = {
            context_id: {
                "context_id": context_id,
                "observations": [
                    {"lanes": ["fast"], "tools_used": False, "revision_used": False}
                    for _ in range(3)
                ],
                "observation_count": 3,
            }
        }
        first["recurrent"]["checkpoint_digest"] = ""
        first["recurrent"]["checkpoint_digest"] = eve_consciousness.state_checkpoint_digest(first)
        second_inputs = fixture_inputs()
        second_inputs.update({"conflict_items": [conflict], "previous_state": first})

        second = eve_consciousness.build_conscious_state(**second_inputs)
        process = second["predictions"]["process"]

        self.assertTrue(process["learned_applied"])
        self.assertIn("observer", process["lanes"])
        self.assertIn("deep", process["lanes"])
        self.assertTrue(process["needs_tools"])
        self.assertTrue(process["needs_revision"])

    def test_source_attributed_world_question_forms_goal_and_probe_causally(self):
        inputs = fixture_inputs()
        inputs["workspace"] = {
            "summary": "One unexplained local signal is available.",
            "active_goals": [],
            "prediction_errors": [],
            "surprise_signals": [],
            "action_readiness": [],
        }
        inputs["self_model"] = {
            "identity": "Eve is one continuous local control system.",
            "current_state": "No prior task currently dominates attention.",
            "commitments": [],
            "uncertainty_edges": [],
        }
        inputs["relationship_model"] = {}
        inputs["other_minds_model"] = {}
        inputs["homeostasis"] = {"regulation_mode": "steady", "pressures": []}
        inputs["plan_model"] = {"available": False}
        inputs["autonomy_agenda"] = {}
        inputs["memory_items"] = []
        inputs["world_model"] = {
            "environment_summary": "A local amber relay receipt contradicts its completion marker.",
            "live_unknowns": ["The relay result is unresolved."],
            "open_questions": [
                {
                    "id": "inquiry-amber-relay",
                    "question": "Did the amber relay actually complete, or did only its summary claim completion?",
                    "domain": "local_relay",
                    "source": "relay_receipt:amber",
                    "source_fingerprint": "amber-fingerprint-v1",
                    "status": "open",
                    "priority": 96,
                    "confidence": 91,
                    "candidate_actions": ["service_health_check"],
                    "selected_action": "service_health_check",
                    "expected_observation": "A fresh receipt should expose the verification flag separately from the summary.",
                    "attempts": [],
                }
            ],
        }

        intact = eve_consciousness.build_conscious_state(**inputs)
        lesioned = eve_consciousness.build_conscious_state(**{**inputs, "lesions": ["world_model"]})

        self.assertEqual("inquiry", intact["perception"]["winning_coalition"]["kind"])
        self.assertIn("amber relay", intact["goals"]["selected_goal"].lower())
        self.assertEqual("service_health_check", intact["action_model"]["selected_intention"]["id"])
        self.assertEqual("inquiry-amber-relay", intact["action_model"]["selected_intention"]["inquiry_id"])
        self.assertEqual("inquiry-amber-relay", intact["world_model"]["selected_question"]["id"])
        self.assertEqual([], lesioned["world_model"]["open_questions"])
        self.assertNotIn(
            "inquiry-amber-relay",
            [item.get("inquiry_id") for item in lesioned["action_model"]["affordances"]],
        )


class ConsciousStateIntegrationTests(unittest.TestCase):
    def test_answered_source_fingerprint_does_not_reopen_on_refresh(self):
        first = eve.build_world_model_state(
            source="test",
            system_snapshot={},
            state={},
        )
        question = dict(first["open_questions"][0])
        question.update(status="answered", answer="All services verified healthy.", answered_at="2026-07-19T00:00:00+00:00")
        previous = {**first, "open_questions": [], "answered_questions": [question]}

        second = eve.build_world_model_state(
            source="test",
            system_snapshot={},
            state={},
            previous_world_model=previous,
        )

        self.assertEqual([], second["open_questions"])
        self.assertEqual(question["source_fingerprint"], second["answered_questions"][0]["source_fingerprint"])

    def test_newer_answer_retires_stale_parallel_copy_of_same_world_question(self):
        question = "Does the runtime show a live fault or recovered history?"
        stale_open = eve.normalize_world_inquiry(
            {
                "question": question,
                "domain": "runtime",
                "source_fingerprint": "older-revision",
                "status": "open",
                "candidate_actions": ["service_health_check"],
                "selected_action": "service_health_check",
                "created_at": "2026-07-19T10:00:00+00:00",
                "updated_at": "2026-07-19T10:01:00+00:00",
            }
        )
        answered = eve.normalize_world_inquiry(
            {
                "question": question,
                "domain": "runtime",
                "source_fingerprint": "current-revision",
                "status": "answered",
                "answer": "The fresh observation found only recovered history.",
                "answered_at": "2026-07-19T10:02:00+00:00",
                "updated_at": "2026-07-19T10:02:00+00:00",
            },
            default_status="answered",
        )
        current_candidate = eve.normalize_world_inquiry(
            {
                **answered,
                "status": "open",
                "answer": "",
                "answered_at": None,
                "candidate_actions": ["service_health_check"],
                "selected_action": "service_health_check",
            }
        )

        open_questions, answered_questions = eve.merge_world_inquiries(
            {
                **eve.default_world_model_state(),
                "open_questions": [stale_open],
                "answered_questions": [answered],
            },
            [current_candidate],
            now="2026-07-19T10:03:00+00:00",
        )

        self.assertEqual([], open_questions)
        superseded = [
            item
            for item in answered_questions
            if item["id"] == stale_open["id"]
        ]
        self.assertEqual(1, len(superseded))
        self.assertEqual("superseded", superseded[0]["status"])

    def test_current_evidence_revision_replaces_parallel_open_copy(self):
        question = "Which receipt describes the current relay state?"
        stale_open = eve.normalize_world_inquiry(
            {
                "question": question,
                "domain": "relay",
                "source_fingerprint": "old-signal",
                "status": "open",
                "candidate_actions": ["service_health_check"],
                "selected_action": "service_health_check",
                "created_at": "2026-07-19T10:00:00+00:00",
                "updated_at": "2026-07-19T10:01:00+00:00",
            }
        )
        current = eve.normalize_world_inquiry(
            {
                "question": question,
                "domain": "relay",
                "source_fingerprint": "new-signal",
                "status": "open",
                "candidate_actions": ["service_health_check"],
                "selected_action": "service_health_check",
                "created_at": "2026-07-19T10:02:00+00:00",
                "updated_at": "2026-07-19T10:02:00+00:00",
            }
        )

        open_questions, answered_questions = eve.merge_world_inquiries(
            {
                **eve.default_world_model_state(),
                "open_questions": [stale_open],
            },
            [current],
            now="2026-07-19T10:03:00+00:00",
        )

        self.assertEqual([current["id"]], [item["id"] for item in open_questions])
        superseded = [
            item
            for item in answered_questions
            if item["id"] == stale_open["id"]
        ]
        self.assertEqual(1, len(superseded))
        self.assertEqual("superseded", superseded[0]["status"])

    def test_fixture_shaped_reply_turn_is_synthetic_and_cannot_become_lived_state(self):
        self.assertTrue(
            eve.conversation_message_is_synthetic(
                {"id": "msg-2", "thread_id": "thread-1", "sender": "user", "body": "fixture"}
            )
        )
        self.assertFalse(
            eve.conversation_message_is_synthetic(
                {
                    "id": "9ae46a70-2ab5-4b5e-af85-337aaf9a92e2",
                    "thread_id": "b03ccf81-07cc-4783-971d-34ba095b54bd",
                    "sender": "user",
                    "body": "lived turn",
                }
            )
        )

    def test_archived_superseded_beliefs_are_not_misclassified_as_live_conflicts(self):
        workspace = eve.default_global_workspace()
        workspace["surprise_signals"] = ["verification_ok=false while summary claimed success"]
        human_context = eve.default_human_context()
        human_context["memory_v2"]["superseded_or_conflicting_beliefs"] = [
            "Previous belief: reflection alone was enough. Current view: consequence matters.",
            "Superseded live marker: an old service state is no longer current.",
            "Unresolved conflict: the user requested A versus the stored plan says B",
        ]

        conflicts = eve.conscious_epistemic_conflict_items(
            workspace=workspace,
            human_context=human_context,
        )

        self.assertEqual(2, len(conflicts))
        evidence = [str(item.get("evidence") or "") for item in conflicts]
        self.assertFalse(any(item.startswith("Previous belief") for item in evidence))
        self.assertFalse(any(item.startswith("Superseded live marker") for item in evidence))

    def test_ordinary_while_phrase_in_prediction_text_is_not_a_false_conflict(self):
        workspace = eve.default_global_workspace()
        workspace["prediction_errors"] = [
            "Expected 'Whether a grounded action can move forward while pressure cools.' from a check, observed: command root"
        ]

        conflicts = eve.conscious_epistemic_conflict_items(
            workspace=workspace,
            human_context=eve.default_human_context(),
        )

        self.assertEqual([], conflicts)

    def test_runtime_build_uses_shared_daemon_epoch_and_explicit_conflicts(self):
        inputs = fixture_inputs()
        human_context = eve.default_human_context()
        human_context["memory_v2"]["superseded_or_conflicting_beliefs"] = [
            "Unresolved conflict: source A versus source B"
        ]
        with (
            mock.patch.object(eve, "load_conscious_state", return_value=eve_consciousness.default_state()),
            mock.patch.object(eve, "load_autonomy_agenda", return_value=inputs["autonomy_agenda"]),
            mock.patch.object(eve, "load_human_context", return_value=human_context),
            mock.patch.object(eve, "select_conscious_memory_items", return_value=inputs["memory_items"]),
            mock.patch.object(
                eve,
                "load_state",
                return_value={"daemon_started_at": "2026-07-12T18:00:00+00:00", "daemon_process_id": 4321},
            ),
        ):
            state = eve.build_recurrent_conscious_state(
                source="test",
                workspace=inputs["workspace"],
                self_model=inputs["self_model"],
                world_model=inputs["world_model"],
                relationship_model=inputs["relationship_model"],
                other_minds_model=inputs["other_minds_model"],
                homeostasis=inputs["homeostasis"],
                latest_outcome={},
                persist=False,
            )

        self.assertEqual(
            "daemon:2026-07-12T18:00:00+00:00:pid:4321",
            state["recurrent"]["runtime_epoch"],
        )
        self.assertGreaterEqual(state["epistemic_state"]["unresolved_count"], 1)

    def test_runtime_build_uses_the_just_sampled_sensory_override(self):
        inputs = fixture_inputs()
        sensory_frame = eve_sensory.build_frame(
            [
                {
                    "id": "fresh-sensory-change",
                    "observed_at": "2026-07-12T18:00:00+00:00",
                    "modality": "proprioceptive",
                    "source": "verified_action_execution",
                    "subject": "bounded-action",
                    "summary": "The selected action produced a surprising result.",
                    "novelty": 100,
                    "change": 100,
                    "urgency": 90,
                    "goal_relevance": 100,
                    "self_relevance": 100,
                    "precision": 100,
                    "permission_granted": True,
                }
            ],
            now="2026-07-12T18:00:00+00:00",
        )
        with (
            mock.patch.object(eve, "load_conscious_state", return_value=eve_consciousness.default_state()),
            mock.patch.object(eve, "load_autonomy_agenda", return_value=inputs["autonomy_agenda"]),
            mock.patch.object(eve, "load_human_context", return_value=eve.default_human_context()),
            mock.patch.object(eve, "select_conscious_memory_items", return_value=inputs["memory_items"]),
            mock.patch.object(
                eve,
                "load_state",
                return_value={"daemon_started_at": "2026-07-12T18:00:00+00:00", "daemon_process_id": 4321},
            ),
        ):
            state = eve.build_recurrent_conscious_state(
                source="daemon_sensory_attention",
                workspace=inputs["workspace"],
                self_model=inputs["self_model"],
                world_model=inputs["world_model"],
                relationship_model=inputs["relationship_model"],
                other_minds_model=inputs["other_minds_model"],
                homeostasis=inputs["homeostasis"],
                plan_model=inputs["plan_model"],
                latest_outcome={},
                persist=False,
                sensory_frame_override=sensory_frame,
            )

        self.assertEqual(
            "fresh-sensory-change",
            state["perception"]["sensory_frame"]["winner"]["id"],
        )
        self.assertTrue(
            any(
                item["kind"] == "sensory_proprioceptive"
                for item in state["perception"]["salient_inputs"]
            )
        )

    def test_direct_chat_preflight_reads_the_live_runtime_state(self):
        inputs = fixture_inputs()
        with (
            mock.patch.object(
                eve,
                "load_conscious_state",
                return_value=eve_consciousness.default_state(),
            ) as load_conscious_state,
            mock.patch.object(eve, "load_autonomy_agenda", return_value=inputs["autonomy_agenda"]),
            mock.patch.object(eve, "load_human_context", return_value=eve.default_human_context()),
            mock.patch.object(eve, "select_conscious_memory_items", return_value=inputs["memory_items"]),
            mock.patch.object(
                eve,
                "load_state",
                return_value={"daemon_started_at": "2026-07-12T18:00:00+00:00", "daemon_process_id": 4321},
            ),
        ):
            eve.build_recurrent_conscious_state(
                source="chat_preflight",
                workspace=inputs["workspace"],
                self_model=inputs["self_model"],
                world_model=inputs["world_model"],
                relationship_model=inputs["relationship_model"],
                other_minds_model=inputs["other_minds_model"],
                homeostasis=inputs["homeostasis"],
                plan_model=inputs["plan_model"],
                latest_outcome={},
                persist=False,
            )

        load_conscious_state.assert_called_once_with(prefer_runtime=True)

    def test_completed_capability_probes_do_not_become_permanent_agenda_goals(self):
        legacy_title = "Follow the coder mode probe capability thread"
        agenda = eve.normalize_autonomy_agenda(
            {
                "current_focus": legacy_title,
                "last_completed_run_id": "free-run-2026-07-19T09-16-44-00-00",
                "active_threads": [
                    {
                        "title": legacy_title,
                        "family": "capability",
                        "preferred_action": "capability_tryout",
                        "source_run_id": "free-run-2026-07-19T09-16-44-00-00",
                        "evidence": "coder_mode_probe verified.",
                    },
                    {
                        "title": "Resolve the fresh OpenClaw contradiction",
                        "family": "openclaw",
                        "preferred_action": "openclaw_log_check",
                        "source_run_id": "free-run-2026-07-19T10-00-00-00-00",
                        "priority": 78,
                    },
                    {
                        "title": "An old daemon fault still needs attention",
                        "family": "tasks",
                        "preferred_action": "system_tasks",
                        "source_run_id": "free-run-old",
                        "updated_at": "2026-04-23T23:18:16+00:00",
                    },
                ],
                "next_experiments": [
                    {
                        "title": legacy_title,
                        "family": "capability",
                        "preferred_action": "capability_tryout",
                        "source_run_id": "free-run-2026-07-19T09-16-44-00-00",
                    }
                ],
            }
        )

        self.assertEqual(
            ["Resolve the fresh OpenClaw contradiction"],
            [item["title"] for item in agenda["active_threads"]],
        )
        self.assertEqual([], agenda["next_experiments"])
        self.assertEqual("Resolve the fresh OpenClaw contradiction", agenda["current_focus"])

        candidates = eve.autonomy_agenda_thread_candidates(
            [
                {
                    "action": "capability_tryout",
                    "status": "completed",
                    "ok": True,
                    "capability_variant": "coder_mode_probe",
                    "summary": "coder_mode_probe verified with a real tool trace.",
                }
            ],
            final_snapshot={
                "active_mind": {
                    "current_focus": "An old daemon error",
                    "next_step": "Keep following the old daemon error",
                }
            },
            supervisor={},
            run_id="free-run-test",
        )
        self.assertEqual([], candidates)

    def test_fresh_world_inquiry_outranks_a_migrated_completed_probe(self):
        legacy_title = "Follow the coder mode probe capability thread"
        agenda = eve.normalize_autonomy_agenda(
            {
                "last_completed_run_id": "free-run-2026-07-19T09-16-44-00-00",
                "active_threads": [
                    {
                        "title": legacy_title,
                        "family": "capability",
                        "preferred_action": "capability_tryout",
                        "source_run_id": "free-run-2026-07-19T09-16-44-00-00",
                        "priority": 86,
                    }
                ],
            }
        )
        inputs = fixture_inputs()
        inputs["autonomy_agenda"] = agenda
        inputs["world_model"] = {
            **inputs["world_model"],
            "open_questions": [
                {
                    "id": "inquiry-fresh-openclaw",
                    "question": "Does OpenClaw show a live fault or recovered history?",
                    "status": "open",
                    "priority": 88,
                    "candidate_actions": ["openclaw_log_check"],
                    "selected_action": "openclaw_log_check",
                    "expected_observation": "Fresh logs distinguish current failure from history.",
                }
            ],
        }

        state = eve_consciousness.build_conscious_state(**inputs)

        self.assertEqual(
            "Resolve: Does OpenClaw show a live fault or recovered history?",
            state["goals"]["selected_goal"],
        )
        self.assertEqual("openclaw_log_check", state["action_model"]["selected_intention"]["id"])
        self.assertEqual(
            state["goals"]["selected_goal_id"],
            state["action_model"]["selected_intention"]["goal_id"],
        )

    def test_continuous_thought_failure_diagnostic_cannot_become_or_remain_a_goal(self):
        diagnostic = (
            "thought failed: Grounded continuous-thought fallback failed its "
            "own evidence boundary."
        )
        inputs = fixture_inputs()
        inputs["workspace"] = {
            **inputs["workspace"],
            "active_goals": [diagnostic, "Repair the verified current contradiction"],
        }
        previous = eve_consciousness.build_conscious_state(**inputs)
        previous["goals"]["stack"].append(
            {
                "id": "goal-old-diagnostic",
                "text": diagnostic,
                "source": "recurrent_carry_forward",
                "origin_source": "global_workspace",
                "priority": 95,
                "status": "active",
                "persistence_cycles": 12,
                "carry_forward_cycles": 1,
            }
        )
        next_inputs = fixture_inputs()
        next_inputs["workspace"] = {
            **next_inputs["workspace"],
            "active_goals": [diagnostic, "Repair the verified current contradiction"],
        }
        next_inputs["previous_state"] = previous

        state = eve_consciousness.build_conscious_state(**next_inputs)

        rendered = " ".join(
            str(item.get("text") or "") for item in state["goals"]["stack"]
        ).lower()
        self.assertNotIn("thought failed", rendered)
        self.assertIn("repair the verified current contradiction", rendered)

    def test_control_process_rationale_cannot_become_or_remain_a_goal(self):
        rationale = (
            "Council chose `updates_status` after deep; planner converged. "
            "The agenda supported checking component updates."
        )
        inputs = fixture_inputs()
        inputs["workspace"] = {
            **inputs["workspace"],
            "active_goals": [rationale, "Review the pending component updates"],
        }
        previous = eve_consciousness.build_conscious_state(**inputs)
        previous["goals"]["stack"].append(
            {
                "id": "goal-old-council-rationale",
                "text": rationale,
                "source": "recurrent_carry_forward",
                "origin_source": "global_workspace",
                "priority": 98,
                "status": "active",
                "persistence_cycles": 8,
                "carry_forward_cycles": 1,
            }
        )
        next_inputs = fixture_inputs()
        next_inputs["workspace"] = {
            **next_inputs["workspace"],
            "active_goals": [rationale, "Review the pending component updates"],
        }
        next_inputs["previous_state"] = previous

        state = eve_consciousness.build_conscious_state(**next_inputs)

        rendered = " ".join(
            str(item.get("text") or "") for item in state["goals"]["stack"]
        ).lower()
        self.assertNotIn("council chose", rendered)
        self.assertIn("review the pending component updates", rendered)

    def test_runtime_completion_attributes_outcome_to_opened_cycle_and_joins_learning(self):
        first_inputs = fixture_inputs()
        first_inputs.update({"inbound": "First branch", "now": "2026-07-12T18:00:00+00:00"})
        second_inputs = fixture_inputs()
        second_inputs.update({"inbound": "Second branch", "now": "2026-07-12T18:00:01+00:00"})
        first = eve_consciousness.build_conscious_state(**first_inputs)
        second = eve_consciousness.build_conscious_state(**second_inputs)
        persisted = json.loads(json.dumps(second))

        def update(mutator, **_kwargs):
            return mutator(persisted)

        with (
            mock.patch.object(eve.CONSCIOUS_STATE_REPOSITORY, "update", side_effect=update),
            mock.patch.object(eve, "append_conscious_state_audit_event"),
        ):
            completed = eve.complete_recurrent_conscious_cycle(
                actual_process={"lanes": ["observer"], "tools_used": ["inspect"], "revision_used": True},
                outcome={"ok": True, "summary": "The first branch verified later."},
                source="reply_outcome:test",
                opened_state=first,
            )

        self.assertEqual(first["cycle_id"], completed["cycle_id"])
        self.assertTrue(completed["completion_persistence"]["joined"])
        self.assertEqual(second["cycle_id"], persisted["cycle_id"])
        self.assertEqual(second["broadcast"], persisted["broadcast"])
        self.assertIn(first["cycle_id"], persisted["recurrent"]["joined_completion_ids"])

    def test_atomic_cycle_open_does_not_erase_concurrent_completed_learning(self):
        inputs = fixture_inputs()
        base = eve_consciousness.build_conscious_state(
            **inputs,
            runtime_epoch="epoch-a",
            now="2026-07-12T18:00:00+00:00",
        )
        donor_inputs = fixture_inputs()
        donor_inputs.update(
            {
                "previous_state": base,
                "inbound": "Concurrent donor branch",
                "runtime_epoch": "epoch-a",
                "now": "2026-07-12T18:00:01+00:00",
            }
        )
        donor_open = eve_consciousness.build_conscious_state(**donor_inputs)
        donor_prediction = donor_open["predictions"]["process"]
        donor = eve_consciousness.complete_cycle(
            donor_open,
            actual_process={
                "lanes": donor_prediction["lanes"],
                "tools_used": ["inspect"] if donor_prediction["needs_tools"] else [],
                "revision_used": donor_prediction["needs_revision"],
            },
            outcome={"ok": True, "summary": "Concurrent donor learning verified."},
            now="2026-07-12T18:00:02+00:00",
        )
        persisted = json.loads(json.dumps(donor))

        def update(mutator, **_kwargs):
            return mutator(persisted)

        human_context = eve.default_human_context()
        with (
            mock.patch.object(eve, "load_conscious_state", return_value=base),
            mock.patch.object(eve, "load_autonomy_agenda", return_value=inputs["autonomy_agenda"]),
            mock.patch.object(eve, "load_human_context", return_value=human_context),
            mock.patch.object(eve, "select_conscious_memory_items", return_value=inputs["memory_items"]),
            mock.patch.object(
                eve,
                "load_state",
                return_value={"daemon_started_at": "2026-07-12T18:00:00+00:00", "daemon_process_id": 4321},
            ),
            mock.patch.object(eve.CONSCIOUS_STATE_REPOSITORY, "update", side_effect=update),
            mock.patch.object(eve, "append_conscious_state_audit_event"),
        ):
            opened = eve.build_recurrent_conscious_state(
                source="reply_preflight",
                workspace=inputs["workspace"],
                self_model=inputs["self_model"],
                world_model=inputs["world_model"],
                relationship_model=inputs["relationship_model"],
                other_minds_model=inputs["other_minds_model"],
                homeostasis=inputs["homeostasis"],
                inbound="New concurrent reply branch",
                latest_outcome={},
                persist=True,
            )

        self.assertNotEqual(donor["cycle_id"], opened["cycle_id"])
        self.assertIn(donor["cycle_id"], opened["recurrent"]["concurrent_lineage_ids"])
        self.assertGreaterEqual(opened["recurrent"]["branch_open_count"], 1)
        self.assertTrue(opened["learning"]["process_models"])
        self.assertEqual(opened["cycle_id"], persisted["cycle_id"])
        self.assertEqual("verified", eve_consciousness.checkpoint_integrity(opened))

    def test_synthetic_eval_metadata_is_explicitly_classified(self):
        self.assertTrue(eve.message_metadata_is_synthetic({"conversation_class": "synthetic_eval"}))
        self.assertFalse(eve.message_metadata_is_synthetic({"conversation_class": "lived"}))

    def test_lived_message_reader_excludes_synthetic_and_background_turns(self):
        records = [
            {"id": "lived", "sender": "user", "recipient": "eve", "kind": "user_message", "metadata": {}},
            {
                "id": "synthetic",
                "sender": "user",
                "recipient": "eve",
                "kind": "user_message",
                "metadata": {"conversation_class": "synthetic_eval"},
            },
            {
                "id": "background",
                "sender": "eve",
                "recipient": "user",
                "kind": "reflection_update",
                "metadata": {"source": "daemon"},
            },
        ]
        with mock.patch.object(eve, "read_messages", return_value=records):
            selected = eve.read_lived_messages(limit=3)

        self.assertEqual(["lived"], [item["id"] for item in selected])

    def test_synthetic_message_does_not_enter_lived_evidence_or_active_mind(self):
        with (
            mock.patch.object(eve, "read_messages", return_value=[]),
            mock.patch.object(eve, "append_jsonl_record", side_effect=lambda path, record: record),
            mock.patch.object(eve, "mirror_store_file_to_runtime"),
            mock.patch.object(eve, "record_conversation_spine_turn_safe"),
            mock.patch.object(eve, "record_evidence") as record_evidence,
            mock.patch.object(eve, "record_experience_event") as record_experience,
            mock.patch.object(eve, "create_outcome") as create_outcome,
            mock.patch.object(eve, "append_entry"),
            mock.patch.object(eve, "refresh_active_mind_from_conversation_event") as refresh_mind,
        ):
            message = eve.create_message(
                sender="user",
                recipient="eve",
                subject="Hidden evaluator probe",
                body="Classify the anomaly without seeing the rubric.",
                kind="user_message",
                metadata={"synthetic": True, "conversation_class": "synthetic_eval", "source": "codex_hidden_eval"},
            )

        self.assertTrue(eve.conversation_message_is_synthetic(message))
        record_evidence.assert_not_called()
        record_experience.assert_not_called()
        create_outcome.assert_not_called()
        refresh_mind.assert_not_called()

    def test_counterpart_reply_is_neutral_until_lived_consequence_is_classified(self):
        prior = {
            "id": "eve-prior",
            "thread_id": "thread-1",
            "sender": "eve",
            "recipient": "user",
            "kind": "reply",
            "body": "Here is my answer.",
            "metadata": {},
        }
        with (
            mock.patch.object(eve, "read_messages", return_value=[prior]),
            mock.patch.object(eve, "append_jsonl_record", side_effect=lambda path, record: record),
            mock.patch.object(eve, "mirror_store_file_to_runtime"),
            mock.patch.object(eve, "record_conversation_spine_turn_safe"),
            mock.patch.object(eve, "record_evidence"),
            mock.patch.object(eve, "record_experience_event"),
            mock.patch.object(eve, "create_outcome") as create_outcome,
            mock.patch.object(eve, "append_entry"),
            mock.patch.object(eve, "refresh_active_mind_from_conversation_event"),
        ):
            eve.create_message(
                sender="user",
                recipient="eve",
                subject="Re: answer",
                body="I mean real consciousness, not a UI demo.",
                kind="user_message",
                thread_id="thread-1",
                status="sent",
            )

        outcome = create_outcome.call_args.kwargs
        self.assertEqual("neutral", outcome["direction"])
        self.assertEqual("counterpart_replied_unscored", outcome["outcome"])
        self.assertIn("valence remains unscored", outcome["summary"])

    def test_reply_inherits_synthetic_provenance_from_parent(self):
        parent = {
            "id": "probe-message",
            "thread_id": "probe-thread",
            "sender": "user",
            "recipient": "eve",
            "kind": "user_message",
            "metadata": {
                "synthetic": True,
                "conversation_class": "synthetic_eval",
                "source": "codex_hidden_eval",
                "evaluation_id": "eval-probe-1",
            },
        }
        with (
            mock.patch.object(eve, "read_messages", return_value=[parent]),
            mock.patch.object(eve, "append_jsonl_record", side_effect=lambda path, record: record),
            mock.patch.object(eve, "mirror_store_file_to_runtime"),
            mock.patch.object(eve, "record_conversation_spine_turn_safe"),
            mock.patch.object(eve, "append_entry"),
            mock.patch.object(eve, "refresh_active_mind_from_conversation_event"),
        ):
            reply = eve.create_message(
                sender="eve",
                recipient="user",
                subject="Re: probe",
                body="The contradiction is in the evidence fields.",
                kind="reply",
                thread_id="probe-thread",
                reply_to="probe-message",
            )

        self.assertTrue(reply["metadata"]["synthetic"])
        self.assertEqual("synthetic_eval", reply["metadata"]["conversation_class"])
        self.assertEqual("probe-message", reply["metadata"]["synthetic_parent_message_id"])
        self.assertEqual("codex_hidden_eval", reply["metadata"]["synthetic_source"])
        self.assertEqual("eval-probe-1", reply["metadata"]["evaluation_id"])

    def test_conscious_broadcast_changes_projected_active_mind(self):
        workspace = eve.default_global_workspace()
        workspace["updated_at"] = "2026-07-12T18:00:00+00:00"
        workspace["workspace_state"]["focus"] = "Old focus"
        workspace["action_readiness"] = ["Old next step"]
        conscious = eve_consciousness.default_state()
        conscious.update(
            {
                "updated_at": "2026-07-12T18:00:01+00:00",
                "status": "integrated",
                "broadcast": {
                    "content": "Fresh contradiction that won attention",
                    "ignition_score": 80,
                    "access_scope": ["mind"],
                    "source_kinds": ["prediction_error"],
                    "why_selected": "test",
                },
                "perception": {
                    "salient_inputs": [],
                    "winning_coalition": {"kind": "prediction_error"},
                    "alternatives": [],
                },
                "action_model": {
                    "affordances": [],
                    "selected_intention": {"description": "Verify the contradiction before acting"},
                    "actionable": True,
                },
            }
        )
        previous = dict(eve.DEFAULT_ACTIVE_MIND)
        previous["updated_at"] = "2026-07-12T18:00:00+00:00"
        previous["current_focus"] = "Old focus"
        projected = eve.project_active_mind_from_workspace(
            previous_mind=previous,
            workspace=workspace,
            self_model=eve.default_self_model_state(),
            world_model=eve.default_world_model_state(),
            relationship_model=eve.default_relationship_model_state(),
            homeostasis=eve.default_homeostasis_state(),
            threads=[],
            messages=[],
            source="test",
            conscious_state=conscious,
        )

        self.assertEqual("Fresh contradiction that won attention", projected["current_focus"])
        self.assertIn("Verify the contradiction", projected["next_step"])

    def test_conscious_process_prediction_changes_reply_lane_admission(self):
        conscious = eve_consciousness.default_state()
        conscious["updated_at"] = "2026-07-12T18:00:00+00:00"
        conscious["predictions"] = {
            "process": {
                "lanes": ["fast", "deep"],
                "needs_tools": False,
                "needs_memory": False,
                "needs_revision": True,
            },
            "outcome": {},
            "prior_prediction_error": {},
        }
        config = dict(eve.DEFAULT_CONFIG)
        config["reply_council_min_lane_pressure"] = 0.55
        config["reply_council_deep_pressure_threshold"] = 0.25
        with (
            mock.patch.object(eve, "load_conscious_state", return_value=conscious),
            mock.patch.object(eve, "reply_lane_learning_adjustments", return_value={}),
            mock.patch.object(eve, "reply_model_quarantine_status", return_value={"active": False}),
        ):
            council = eve.build_reply_council_state(config, "Explain this", "general", allow_tools=False)

        deep = next(item for item in council["lanes"] if item["lane"] == "deep")
        self.assertEqual(0.14, deep["conscious_state_adjustment"])
        self.assertIn("deep", council["active_lanes"])

    def test_predicted_planner_crosses_admission_for_explicit_next_action(self):
        conscious = eve_consciousness.default_state()
        conscious["predictions"] = {"process": {"lanes": ["fast", "planner"]}}
        config = dict(eve.DEFAULT_CONFIG)
        config["reply_council_min_lane_pressure"] = 0.55
        with (
            mock.patch.object(eve, "load_conscious_state", return_value=conscious),
            mock.patch.object(eve, "reply_lane_learning_adjustments", return_value={}),
            mock.patch.object(eve, "reply_model_quarantine_status", return_value={"active": False}),
        ):
            council = eve.build_reply_council_state(
                config,
                "Choose the next action.",
                "practical",
                allow_tools=False,
            )

        planner = next(item for item in council["lanes"] if item["lane"] == "planner")
        self.assertEqual(0.20, planner["conscious_state_adjustment"])
        self.assertIn("planner", council["active_lanes"])

    def test_reflective_route_contract_causally_admits_deep_lane(self):
        conscious = eve_consciousness.default_state()
        conscious["predictions"] = {"process": {"lanes": ["fast"]}}
        config = dict(eve.DEFAULT_CONFIG)
        config["reply_council_deep_pressure_threshold"] = 0.70
        with (
            mock.patch.object(eve, "load_conscious_state", return_value=conscious),
            mock.patch.object(eve, "reply_lane_learning_adjustments", return_value={}),
            mock.patch.object(eve, "reply_model_quarantine_status", return_value={"active": False}),
        ):
            council = eve.build_reply_council_state(
                config,
                "What does becoming conscious mean to you right now?",
                "relational",
                allow_tools=False,
            )

        deep = next(item for item in council["lanes"] if item["lane"] == "deep")
        self.assertEqual(0.40, deep["route_contract_adjustment"])
        self.assertIn("deep", council["active_lanes"])
        self.assertEqual("humanity_question", council["route_contract_kind"])


if __name__ == "__main__":
    unittest.main()
