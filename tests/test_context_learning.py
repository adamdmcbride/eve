"""Public synthetic controls. No live messages, tools or training ingestion."""
import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack

import eve
import eve_consciousness as kernel
import eve_context_learning as learning
import eve_sensory as sensory
from tests.test_developmental_cycle import cycle_test_patches
from tests.test_recurrent_cognition_integration import action_result


AT = "2026-09-13T02:00:00+00:00"


def context(kind="inspect"):
    return learning.build_context(source="recurrent_module_query:control", inbound="",
                                  regulation_mode="orient", metadata={"module_query_kind": kind})


def observation(index, ok, ctx=None, **extra):
    return {"source_cycle_id": "cycle-" + str(index), "evidence_id": "receipt-" + str(index),
            "execution_id": "execution-" + str(index), "verification_ok": ok,
            "ok": ok, "action_context": ctx or context(),
            "completed_at": (datetime.fromisoformat(AT) - timedelta(seconds=100-index)).isoformat(),
            "evidence_kind": "cycle_action_consequence", **extra}


def affordances(models=None, kind="inspect", lesions=()):
    return kernel._action_affordances(
        workspace={}, world_model={}, autonomy_agenda={}, plan_model={}, goals=[],
        winner={}, broadcast={}, inbound="", regulation_mode="orient", arousal=0, valence=0,
        uncertainty_count=0, epistemic_conflicts=[], regulatory_prediction_error=0,
        module_query={"target_action": "service_health_check", "question": "Inspect the service",
                      "source_module": "control", "query_kind": kind},
        action_models=models or {}, lesions=set(lesions), now=AT,
    )


class ContextLearningTests(unittest.TestCase):
    def test_context_is_stable_private_and_not_a_health_claim(self):
        a = learning.build_context(source="current_turn", inbound="Please check secret-one",
                                   regulation_mode="orient", metadata={})
        b = learning.build_context(source="current_turn", inbound="Check secret-two now",
                                   regulation_mode="orient", metadata={})
        self.assertEqual(a, b)
        self.assertNotIn("secret", json.dumps(a))
        self.assertNotIn("healthy", json.dumps(a))
        self.assertTrue(learning.valid_context(a))
        a["features"]["mode"] = "tampered"
        self.assertFalse(learning.valid_context(a))

    def test_contexts_do_not_share_failure_and_reversal_uses_recent_evidence(self):
        rows = [observation(i, False) for i in range(6)]
        bad = learning.estimate({"observations": rows}, context(), now=AT)
        other = learning.estimate({"observations": rows}, context("follow_up"), now=AT)
        self.assertLess(bad["probability"], .5)
        self.assertEqual((0, .5, 0), (other["attempts"], other["probability"], other["adjustment"]))
        rows += [observation(i, True) for i in range(6, 12)]
        reversed_estimate = learning.estimate({"observations": rows}, context(), now=AT)
        self.assertGreater(reversed_estimate["probability"], .5)
        self.assertEqual(12, reversed_estimate["attempts"])
        self.assertEqual(6, sum(not row["ok"] for row in rows))  # contrary evidence retained

    def test_unknown_forged_stale_future_and_duplicate_evidence_do_not_train(self):
        good = observation(1, True)
        variants = [observation(2, "true"), observation(3, True, action_context={}),
                    observation(4, True, source_cycle_id=""), observation(5, True, evidence_id=""),
                    observation(6, True, evidence_kind="self_reflection"),
                    observation(7, True, completed_at="2025-01-01T00:00:00+00:00"),
                    observation(8, True, completed_at="2027-01-01T00:00:00+00:00"),
                    {**good, "evidence_id": "same-cycle-other-receipt"},
                    {**good, "source_cycle_id": "same-receipt-other-cycle"}]
        result = learning.estimate({"observations": [good, *variants]}, context(), now=AT)
        self.assertEqual(1, result["attempts"])
        self.assertAlmostEqual(.6, result["probability"], places=3)

    def test_conflicting_receipt_does_not_count_twice_or_win_by_success(self):
        good = observation(1, True)
        result = learning.estimate({"observations": [good, {**good, "ok": False}]}, context(), now=AT)
        self.assertEqual(1, result["attempts"])
        self.assertLess(result["probability"], .5)
        later = {**good, "completed_at": AT}
        result = learning.estimate({"observations": [{**good, "ok": False}, later]}, context(), now=AT)
        self.assertLess(result["probability"], .5)

    def test_learning_changes_existing_executor_choice_with_frozen_control(self):
        at = datetime.now(timezone.utc).isoformat()
        inputs = {"source": "synthetic", "now": at,
                  "autonomy_agenda": {"active_threads": [
                      {"preferred_action": "updates_status", "title": "Inspect available evidence"},
                      {"preferred_action": "service_health_check", "title": "Inspect available evidence"}]}}
        opened = kernel.build_conscious_state(**inputs)
        self.assertEqual("updates_status", opened["action_model"]["selected_intention"]["id"])
        closed = kernel.complete_cycle(opened,
            actual_process={"action_id": "updates_status", "execution_id": "failed-1"},
            outcome={"observed": True, "ok": False, "evidence_id": "failed-1"}, now=at)
        learned = kernel.build_conscious_state(**inputs, previous_state=closed)
        frozen = kernel.build_conscious_state(**inputs, previous_state=closed, lesions=["contextual_action_learning"])
        self.assertEqual("service_health_check", learned["action_model"]["selected_intention"]["id"])
        self.assertEqual("updates_status", frozen["action_model"]["selected_intention"]["id"])
        # The production selector, not just a reported score, reaches the
        # existing executor with this learned choice. Fixture tool does no IO.
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            for item in cycle_test_patches(Path(folder) / "cycles.jsonl"):
                stack.enter_context(item)
            stack.enter_context(patch.object(eve, "build_recurrent_conscious_state", return_value=learned))
            execute = stack.enter_context(patch.object(eve, "run_operational_action_tree", return_value=action_result()))
            result = eve.run_developmental_cycle(dict(eve.DEFAULT_CONFIG), {}, source="test")
        self.assertEqual("service_health_check", result["capability_attempted"])
        self.assertEqual("service_health_check", execute.call_args.args[0])

    def test_qualified_memory_changes_value_not_permissions(self):
        model = {"service_health_check": {"observations": [observation(i, False) for i in range(5)]}}
        neutral, learned = affordances()[0], affordances(model)[0]
        self.assertLess(learned["value"], neutral["value"])
        self.assertEqual(5, learned["learned_attempts"])
        self.assertEqual(neutral["value"], affordances(model, kind="follow_up")[0]["value"])
        self.assertEqual(neutral["value"], affordances(model, lesions=["contextual_action_learning"])[0]["value"])
        self.assertEqual(neutral["id"], learned["id"])

    def test_context_bound_credit_is_not_taken_from_current_cycle(self):
        state = {"cycle_id": "old", "action_model": {"selected_intention": affordances()[0]}}
        credit = learning.capture_credit(state, "service_health_check")
        self.assertEqual(context(), learning.bound_context(credit, "old", "service_health_check"))
        self.assertEqual({}, learning.bound_context(credit, "new", "service_health_check"))
        self.assertEqual({}, learning.bound_context(credit, "old", "openclaw_sync_check"))
        self.assertEqual({}, learning.capture_credit(state, "unexecuted_tool"))

    def test_delayed_feedback_preserves_current_focus_and_original_context(self):
        original = kernel.build_conscious_state(source="synthetic", inbound="Please check status", now=AT)
        credit = learning.capture_credit(original, "respond_to_user")
        current = kernel.build_conscious_state(source="synthetic", inbound="I feel hurt", now=AT)
        updated, applied = kernel.apply_delayed_action_consequence(
            current, source_cycle_id=original["cycle_id"], action_id="respond_to_user", ok=False,
            summary="Explicit correction", evidence_id="feedback-1", reply_message_id="reply-1",
            observed_message_id="user-2", source_credit=credit, now=AT,
            faculty_contributors=[{"lane": "fast", "credit_weight": 1.0, "execution_proven": True}],
        )
        self.assertTrue(applied)
        self.assertEqual(current["broadcast"], updated["broadcast"])
        model = updated["learning"]["action_models"]["respond_to_user"]
        self.assertEqual(credit["action_context"], model["observations"][-1]["action_context"])
        estimate = learning.estimate(model, credit["action_context"], now=AT)
        self.assertEqual(1, estimate["attempts"])
        self.assertLess(estimate["probability"], .5)
        again, applied = kernel.apply_delayed_action_consequence(
            updated, source_cycle_id=original["cycle_id"], action_id="respond_to_user", ok=False,
            summary="Duplicate", evidence_id="feedback-1", reply_message_id="reply-1", now=AT)
        self.assertFalse(applied)
        self.assertEqual(updated, again)

    def test_completion_captures_preaction_context_and_forecast_uses_same_estimate(self):
        opened = kernel.build_conscious_state(source="synthetic", now=AT,
            autonomy_agenda={"active_threads": [{"preferred_action": "service_health_check", "title": "Inspect service"}]})
        selected = opened["action_model"]["selected_intention"]
        self.assertEqual(selected["learned_reliability"], opened["predictions"]["outcome"]["expected_success_probability"])
        closed = kernel.complete_cycle(opened, actual_process={"action_id": selected["id"], "execution_id": "exec-1"},
            outcome={"observed": True, "ok": True, "verification_ok": True, "evidence_id": "receipt-1"}, now=AT)
        row = closed["learning"]["action_models"][selected["id"]]["observations"][-1]
        self.assertEqual(selected["action_context"], row["action_context"])
        self.assertEqual(1, learning.estimate({"observations": [row]}, selected["action_context"], now=AT)["attempts"])
        restored = eve.normalize_conscious_state(json.loads(json.dumps(closed)))
        next_state = kernel.build_conscious_state(source="synthetic", previous_state=restored, now=AT,
            autonomy_agenda={"active_threads": [{"preferred_action": "service_health_check", "title": "Inspect service"}]})
        next_choice = next_state["action_model"]["selected_intention"]
        self.assertEqual(1, next_choice["learned_attempts"])
        self.assertEqual(next_choice["learned_reliability"], next_state["predictions"]["outcome"]["expected_success_probability"])

    def test_consolidation_requires_repeated_verified_execution_not_language(self):
        model = {"observations": [observation(i, True) for i in range(3)]}
        self.assertEqual(1, len(learning.consolidated_candidates({"service_health_check": model}, now=AT)))
        for field, value in [("verification_ok", None), ("execution_id", ""), ("ok", False)]:
            changed = copy.deepcopy(model)
            changed["observations"][-1][field] = value
            self.assertEqual([], learning.consolidated_candidates({"service_health_check": changed}, now=AT))
        self.assertEqual([], learning.consolidated_candidates({"respond_to_user": model}, now=AT))
        replayed = {"observations": [observation(i, True, execution_id="one-real-execution") for i in range(3)]}
        self.assertEqual([], learning.consolidated_candidates({"service_health_check": replayed}, now=AT))

    def test_reply_acceptance_does_not_verify_a_tool_in_the_same_turn(self):
        original = kernel.build_conscious_state(source="synthetic", inbound="Check status", now=AT)
        current = kernel.build_conscious_state(source="synthetic", inbound="Thanks", now=AT)
        replay = {"conscious_cycle_id": original["cycle_id"], "reply_message_id": "reply-1",
                  "conscious_action_id": "service_health_check",
                  "conscious_reply_credit": learning.capture_credit(original, "respond_to_user")}
        with patch.object(eve.CONSCIOUS_STATE_REPOSITORY, "update", side_effect=lambda fn: fn(current)), \
                patch.object(eve, "update_reply_turn_replay_user_consequence", return_value=(replay, True)), \
                patch.object(eve, "record_reply_lane_learning_from_user_consequence"), \
                patch.object(eve, "append_conscious_state_audit_event"), patch.object(eve, "append_entry"):
            eve.join_delayed_reply_consequence(replay, {"consequence_observed": True, "outcome_ok": True,
                "observed_message_id": "user-2", "evidence_id": "feedback-1", "observed_text": "Thanks"})
        self.assertIn("respond_to_user", current["learning"]["action_models"])
        self.assertNotIn("service_health_check", current["learning"]["action_models"])

    def test_free_run_keeps_verified_execution_identity_for_kernel_learning(self):
        opened = kernel.build_conscious_state(source="synthetic", now=AT,
            autonomy_agenda={"active_threads": [{"preferred_action": "service_health_check", "title": "Inspect service"}]})
        result = {**action_result(), "action": "service_health_check"}
        projected = eve.autonomy_conscious_outcome(
            result, eve.autonomy_action_outcome_observation(result), opened, {}, None)
        closed = kernel.complete_cycle(opened, actual_process={"action_id": "service_health_check"}, outcome=projected, now=AT)
        record = closed["learning"]["action_models"]["service_health_check"]["observations"][-1]
        self.assertEqual("execution-1", record["execution_id"])
        self.assertEqual("execution-1", record["evidence_id"])
        self.assertIs(record["verification_ok"], True)
        self.assertEqual(1, learning.estimate({"observations": [record]}, record["action_context"], now=AT)["attempts"])
        no_receipt = eve.autonomy_conscious_outcome(
            {"action": "service_health_check", "ok": True}, {"outcome_ok": True, "consequence_observed": True}, opened, {}, None)
        self.assertEqual("", no_receipt["evidence_id"])
        self.assertFalse(no_receipt["procedural_verification_ok"])

    def test_verified_raw_operational_envelope_without_status_is_not_failure(self):
        raw = action_result()
        raw.pop("status")
        observed = eve.autonomy_action_outcome_observation(raw)
        self.assertTrue(observed["consequence_observed"])
        self.assertIs(observed["outcome_ok"], True)
        for fields in [{"ok": False}, {"executed": False}, {"execution_verification_ok": False},
                       {"typed_contract": {"valid": False}}, {"execution_tree_status": "FAILURE"}]:
            self.assertIs(eve.autonomy_action_outcome_observation({**raw, **fields})["outcome_ok"], False)
        self.assertIsNone(eve.autonomy_action_outcome_observation({"executed": True, "ok": True})["outcome_ok"])

    def test_existing_procedural_store_retracts_and_recovers_without_repeat_promotion(self):
        current = {"updated_at": AT, "learning": {"action_models": {
            "service_health_check": {"observations": [observation(i, True) for i in range(3)]}}},
            "action_model": {"affordances": affordances()}}
        with tempfile.TemporaryDirectory() as folder, patch.object(eve, "SUCCESS_PATTERNS_PATH", Path(folder)/"patterns.jsonl"), \
                patch.object(eve, "mirror_store_file_to_runtime"), patch.object(eve, "append_entry"), \
                patch.object(eve, "utc_now", return_value=AT), patch.object(eve, "load_conscious_state", return_value=current):
            first = eve.consolidate_contextual_success_patterns(current, source="synthetic")
            self.assertEqual(1, first["changed_count"])
            self.assertEqual(0, eve.consolidate_contextual_success_patterns(current, source="synthetic")["changed_count"])
            self.assertEqual(1, len(eve.read_success_patterns()))
            current["learning"]["action_models"]["service_health_check"]["observations"].append(observation(3, False))
            self.assertEqual([], eve.read_success_patterns())  # before next quiet period
            self.assertEqual(1, eve.consolidate_contextual_success_patterns(current, source="synthetic")["changed_count"])
            self.assertEqual("superseded", eve.read_success_patterns(status=None)[0]["status"])
            current["learning"]["action_models"]["service_health_check"]["observations"] += [observation(i, True) for i in range(4, 7)]
            self.assertEqual(1, eve.consolidate_contextual_success_patterns(current, source="synthetic")["changed_count"])
            self.assertEqual(1, len(eve.read_success_patterns()))
            current["action_model"]["affordances"] = affordances(kind="unrelated")
            self.assertEqual([], eve.read_success_patterns())
            self.assertEqual(1, len(eve.read_success_patterns(status=None)))

    def test_repeated_human_turn_retains_capture_and_real_critical_interrupt_wins(self):
        def event(identifier, **extra):
            return {"id": identifier, "source": identifier, "modality": "system",
                    "summary": "Synthetic signal", "intensity": 60, "novelty": 60,
                    "change": 0, "urgency": 60, "precision": 80, **extra}
        human = event("human", modality="social", direct_human=True)
        frame = None
        for i in range(6):
            at = (datetime.fromisoformat(AT) + timedelta(seconds=i)).isoformat()
            frame = sensory.build_frame([human, event("routine")], prior_frame=frame, now=at)
        row = next(row for row in frame["working_set"] if row.get("direct_human"))
        self.assertGreaterEqual(row["attention_score"], 94)
        self.assertTrue(frame["winner"]["direct_human"])
        interrupted = sensory.build_frame([human, event("critical", safety_critical=True)], prior_frame=frame, now=at)
        self.assertTrue(interrupted["winner"]["safety_critical"])


if __name__ == "__main__":
    unittest.main()
