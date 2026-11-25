"""Public functional regression controls; never write fixtures into lived state."""
import copy
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import eve
import eve_consciousness as kernel
import eve_recurrent_cognition as recurrent
from tests.test_cognition_budget import fresh_probe_snapshot, calm_homeostasis
from tests.test_recurrent_cognition_integration import module_result


AT = "2026-09-13T04:00:00+00:00"


def critic_reply(ok, unsupported=None):
    return json.dumps(dict(ok=ok, target_faithfully_present=True,
        unsupported_claims=unsupported or [], invented_deliberation=False,
        action_overclaim=False, causal_overclaim=False, phenomenal_overclaim=False,
        reason="Evidence checked."))


class SharedThoughtEvidenceTests(unittest.TestCase):
    def generate(self, fake_chat):
        record = {"target_kind": "durable_goal", "durable_goal": "Inspect the workspace"}
        verified = [{"action": "service_health_check", "status": "verified_completed",
                     "completed_at": AT, "summary": "A source observation"}]
        with ExitStack() as stack:
            for name, value in {
                "ensure_version_snapshot": None,
                "build_current_inner_state_report_record": record,
                "recent_verified_action_evidence": verified,
                "build_eve_interaction_system_messages": [],
                "retrieve_reviewed_thought_lessons": [],
            }.items():
                stack.enter_context(patch.object(eve, name, return_value=value))
            stack.enter_context(patch.object(eve, "model_chat", side_effect=fake_chat))
            return eve.generate_continuous_thought(dict(eve.DEFAULT_CONFIG), 3, 3, 160, 30)

    def test_actual_critic_prompt_contains_the_authors_action_evidence(self):
        calls = []
        def model(config, lane, messages, **kw):
            calls.append(kw["operation"])
            text = "\n".join(m["content"] for m in messages)
            if "critic" in kw["operation"]:
                self.assertIn('"action": "service_health_check"', text)
                self.assertIn(AT, text)
                self.assertIn("not ongoing activity", text)
                return critic_reply(True)
            return "The selected goal is to inspect the workspace. The last verified action was a service health check."
        result = self.generate(model)
        self.assertFalse(result["used_fallback"])
        self.assertEqual(2, len(calls))

    def test_post_critic_repair_rechecks_semantics_and_has_one_author_retry(self):
        calls = []
        def model(config, lane, messages, **kw):
            op = kw["operation"]; calls.append(op)
            if "critic" in op:
                return critic_reply(calls.count(op) > 1, [] if calls.count(op) > 1 else ["unsupported origin"])
            if op == "continuous_thought_repair":
                self.assertIn("unsupported origin", messages[-1]["content"])
            return "The selected goal is to inspect the workspace. No new action has started."
        result = self.generate(model)
        self.assertFalse(result["used_fallback"])
        self.assertTrue(result["model_path_repaired"])
        self.assertFalse(result["initial_epistemic_critic"]["ok"])
        self.assertEqual(1, calls.count("continuous_thought_repair"))
        self.assertEqual(4, len(calls))

    def test_persistent_semantic_rejection_does_not_loop_or_bypass_critic(self):
        calls = []
        def model(config, lane, messages, **kw):
            calls.append(kw["operation"])
            return critic_reply(False, ["unsupported origin"]) if "critic" in kw["operation"] else "The selected goal is to inspect the workspace."
        result = self.generate(model)
        self.assertTrue(result["used_fallback"])
        self.assertFalse(result["model_path_grounded"])
        self.assertEqual(4, len(calls))

    def test_rejected_revision_keeps_its_own_critic_receipt(self):
        critics = []
        def model(config, lane, messages, **kw):
            if "critic" in kw["operation"]:
                critics.append(1)
                return critic_reply(False, ["initial defect" if len(critics) == 1 else "revised defect"])
            return "The selected goal is to inspect the workspace."
        result = self.generate(model)
        self.assertEqual(["initial defect"], result["initial_epistemic_critic"]["unsupported_claims"])
        self.assertEqual(["revised defect"], result["epistemic_critic"]["unsupported_claims"])
        self.assertEqual("The selected goal is to inspect the workspace.", result["repair_candidate_response"])
        self.assertEqual("", result["repaired_response"])


class ExecutableContractTests(unittest.TestCase):
    def test_fly_success_cannot_be_faked_by_truthy_string_or_bad_evidence(self):
        valid = dict(action="fly_attack_probe", probe="attack", executed=True,
                     ok=True, evidence={"observed": 1}, returncode=0)
        for changes in ({"ok": "false"}, {"evidence": []}, {"returncode": 2}, {"probe": "invented"}):
            with self.subTest(changes=changes), patch.object(eve, "append_entry"):
                result = eve.apply_operational_action_result_contract("fly_attack_probe", dict(valid, **changes), source="isolated_test")
                self.assertFalse(result["ok"], result)
                self.assertFalse(result["typed_contract"]["valid"], result)

    def test_all_fly_actions_pass_real_selector_validator_runner_verifier_path(self):
        for action in eve.FLY_PROBE_ACTIONS:
            with self.subTest(action=action), tempfile.TemporaryDirectory() as directory:
                Path(directory, "fly_probe.py").write_text(
                    'import json\nprint(json.dumps({"ok": True, "summary": "fixture observation", "evidence": {"sample": 1}}))\n'
                )
                config = dict(eve.DEFAULT_CONFIG, fly_lab_path=directory)
                with patch.object(eve, "execution_tree_enabled", return_value=False), patch.object(
                    eve, "evaluate_freedom_policy", return_value={"allowed": True}
                ), patch.object(eve, "record_operational_action_execution") as ledger:
                    result = eve.run_operational_action_tree(action, config, source="isolated_test", persist=False)
                self.assertTrue(result["executed"], result)
                self.assertTrue(result["execution_verification_ok"], result)
                self.assertTrue(result["typed_contract"]["valid"])
                self.assertTrue(eve.action_result_verified_for_completion(result))
                ledger.assert_not_called()

    def test_unsupported_and_denied_actions_remain_blocked(self):
        with patch.object(eve, "run_bounded_fly_probe") as runner, patch.object(
            eve, "evaluate_freedom_policy", return_value={"allowed": False, "reason": "fixture denied"}
        ):
            unknown = eve.run_operational_action_tree("unknown_probe", {}, source="isolated_test", persist=False)
            denied = eve.run_operational_action_tree("fly_attack_probe", {}, source="isolated_test", persist=False)
        self.assertFalse(unknown["executed"])
        self.assertFalse(denied["executed"])
        runner.assert_not_called()


class JobBudgetTests(unittest.TestCase):
    def test_fast_ready_deep_slow_uses_fast_choice_instead_of_deterministic_only(self):
        snapshot = {"system": {"fast_probe_ms": 900, "deep_probe_ms": 22000,
                    "probe_age_minutes": 0.1, "load_state": "hot", "fast_probe_ok": True},
                    "counts": {}, "components": {}, "openclaw": {}, "autonomy": {}}
        guidance = eve.autonomy_free_run_guidance(eve.autonomy_free_run_action_menu(120), snapshot, [],
                                                remaining_seconds=120, config=dict(eve.DEFAULT_CONFIG))
        self.assertEqual("medium", guidance["chooser_load"])

    def test_nonfinite_boolean_or_missing_lane_timings_are_not_ready(self):
        for timing in (float('nan'), float('inf'), True, None, -1):
            self.assertEqual("unknown", eve.cognition_lane_budget_state(dict(eve.DEFAULT_CONFIG),
                fast_probe_ms=timing, deep_probe_ms=1000, required_lanes=("fast",)))

    def test_old_success_never_masks_new_deferred_attempt_or_timezone_order(self):
        state = dict(last_daemon_autonomy_run_at="2026-09-13T01:00:00+00:00",
                     last_daemon_autonomy_attempt_at="2026-09-12T23:59:00-04:00")
        with patch.object(eve, "interval_due", return_value=False) as due, patch.object(
            eve, "homeostasis_autonomy_interval_factor", return_value=1.0
        ):
            self.assertFalse(eve.daemon_autonomy_due(dict(eve.DEFAULT_CONFIG, daemon_autonomy_continuous=False), state))
        self.assertEqual("2026-09-13T03:59:00+00:00", due.call_args[0][0])
        self.assertTrue(eve.daemon_autonomy_due({}, state, force=True))

    def test_deep_latency_and_residency_do_not_block_fast_only_work(self):
        snapshot = fresh_probe_snapshot(deep_ms=20000)
        snapshot["model_status"]["residency"] = {"preferred_deep_loaded": False}
        with patch.object(eve, "load_homeostasis", return_value=calm_homeostasis()), patch.object(eve, "load_model_watchdog_status", return_value={}):
            self.assertIsNone(eve.system_background_gate_reason(snapshot, "small job", dict(eve.DEFAULT_CONFIG), required_lanes=("fast",)))
            self.assertIsNotNone(eve.system_background_gate_reason(snapshot, "large job", dict(eve.DEFAULT_CONFIG)))

    def test_cpu_consolidation_retains_idle_and_disk_boundaries_not_model_gate(self):
        snapshot = fresh_probe_snapshot(fast_ms=20000, deep_ms=30000)
        snapshot["idle_seconds"] = 600
        with patch.object(eve, "load_homeostasis", return_value={"regulation_mode": "stabilize"}):
            self.assertIsNone(eve.quiet_consolidation_gate_reason(snapshot, dict(eve.DEFAULT_CONFIG)))
            snapshot["idle_seconds"] = 0
            self.assertIsNotNone(eve.quiet_consolidation_gate_reason(snapshot, dict(eve.DEFAULT_CONFIG)))
            snapshot["idle_seconds"] = 600
            snapshot["disk"] = {"free_bytes": 1}
            self.assertIn("Disk", eve.quiet_consolidation_gate_reason(snapshot, dict(eve.DEFAULT_CONFIG)))

    def test_slow_models_restrict_action_menu_but_leave_real_observation_available(self):
        menu = eve.autonomy_free_run_action_menu(120)
        snapshot = {"system": {"fast_probe_ms": 1200, "deep_probe_ms": 20000}}
        admitted = eve.autonomy_admissible_action_menu(menu, snapshot, [], dict(eve.DEFAULT_CONFIG))
        self.assertIn("service_health_check", admitted)
        self.assertNotIn("thought", admitted)
        self.assertNotIn("fly_feeding_probe", admitted)
        self.assertNotIn("capability_tryout", admitted)
        snapshot["system"]["deep_probe_ms"] = 1000
        self.assertIn("thought", eve.autonomy_admissible_action_menu(menu, snapshot, [], dict(eve.DEFAULT_CONFIG)))


class RepeatedFaultTests(unittest.TestCase):
    def records(self):
        return [dict(action="service_health_check", id=str(i), updated_at=f"2026-09-13T03:5{i}:00+00:00",
                     verification_ok=False, tree_status="FAILURE", summary="same fault") for i in (1, 2)]

    def test_repeated_failure_waits_and_changed_evidence_or_time_reopens(self):
        records = self.records()
        self.assertIn("service_health_check", recurrent.action_retry_inhibition(records, now=AT))
        self.assertEqual({}, recurrent.action_retry_inhibition(records[:1] * 2, now=AT))
        changed = dict(records[-1], id="new", updated_at="2026-09-13T03:59:00+00:00", summary="different fault")
        self.assertEqual({}, recurrent.action_retry_inhibition([*records, changed], now=AT))
        self.assertEqual({}, recurrent.action_retry_inhibition(records, now="2026-09-13T04:10:00+00:00"))

    def test_repeated_failure_cannot_be_reselected_by_model_or_override(self):
        with patch.object(eve, "utc_now", return_value=AT):
            menu = eve.autonomy_admissible_action_menu(eve.autonomy_free_run_action_menu(120), {"recent_actions": self.records()}, [], dict(eve.DEFAULT_CONFIG))
        self.assertNotIn("service_health_check", menu)
        selected, _, _ = eve.finalize_autonomy_free_run_choice("service_health_check", menu=menu,
            guidance={"require_inquiry_probe": True, "inquiry_action": "service_health_check"},
            recommended_actions=["service_health_check"], selection_policy="test")
        self.assertNotEqual("service_health_check", selected)

    def test_unrelated_fly_probe_never_becomes_a_repair_explanation(self):
        result = module_result("fly_attack_probe", ok=False, verified=False)
        query = recurrent.derive_next_module_query(result, admitted_actions=["fly_attack_probe", "fly_feeding_probe"])
        self.assertEqual("await_evidence", query["query_kind"])
        self.assertEqual("", query["target_action"])
        self.assertTrue(recurrent.module_query_is_valid(query))
        self.assertTrue(kernel._normalize_module_query(query))

    def test_timestamp_refresh_does_not_reopen_identical_runtime_question(self):
        arguments = dict(source="test", state={"service_health_summary": "healthy"}, system_snapshot={"load_state": "calm"})
        status = {"summary": "gateway failed", "gateway_reachable": False, "last_sync_at": AT}
        with patch.object(eve, "system_resource_alerts", return_value=[]), patch.object(eve, "openclaw_attention_needs_action", return_value=True):
            first = eve.build_world_model_state(**arguments, openclaw_status=status)
            status["last_sync_at"] = "2026-09-13T04:05:00+00:00"
            second = eve.build_world_model_state(**arguments, openclaw_status=status, previous_world_model=first)
        self.assertEqual(first["open_questions"][0]["id"], second["open_questions"][0]["id"])


class InquiryProposalTests(unittest.TestCase):
    def test_both_chooser_paths_use_native_schema_and_only_supplied_checkpoint(self):
        menu = {"service_health_check": "Inspect current state", "wait_observe": "Wait"}
        guidance = {"selected_inquiry": {"id": "question-one", "source_fingerprint": "source-one"}}
        payload = dict(action="service_health_check", reason="Observe the endpoint", expected_signal="A response", confidence="medium",
                       alternatives=self.proposal()["alternatives"])
        captured = []
        def model(config, lane, messages, **kwargs):
            captured.append(kwargs["response_schema"])
            return json.dumps(payload)
        with patch.object(eve, "model_chat", side_effect=model), patch.object(
            eve, "load_active_mind", side_effect=AssertionError("unsupplied active mind")
        ), patch.object(eve, "load_human_context", side_effect=AssertionError("unsupplied human context")):
            common = dict(config=dict(eve.DEFAULT_CONFIG), run_id="isolated-choice", menu=menu,
                          guidance=guidance, snapshot={}, previous_actions=[], remaining_seconds=120)
            single = eve.choose_autonomy_free_run_action_single_lane(**common)
            vote = eve.run_autonomy_free_run_choice_lane(lane_name="fast", **common)
        self.assertEqual("guided_choice", single["selection_policy"])
        self.assertEqual("ok", vote["status"])
        for schema in captured:
            self.assertEqual(list(menu), schema["properties"]["action"]["enum"])
            self.assertEqual(2, schema["properties"]["alternatives"]["maxItems"])
            self.assertIn("alternatives", schema["required"])
        self.assertEqual(2, len(captured))

    def proposal(self):
        return dict(inquiry_id="question-one", source_fingerprint="source-one", action="service_health_check", model="fixture-model",
                    epistemic_status="verified_fact", alternatives=[
                        {"explanation": "A process stopped", "predicted_observation": "No process at the endpoint"},
                        {"explanation": "A probe timed out", "predicted_observation": "Process exists but request is slow"}])

    def test_hypotheses_never_accept_model_claimed_fact_status(self):
        proposal = eve.normalize_inquiry_reasoning_proposal(self.proposal())
        self.assertEqual("unverified_hypotheses", proposal["epistemic_status"])
        for malformed in (5, "a string", {}, None, []):
            self.assertEqual({}, eve.normalize_inquiry_reasoning_proposal(dict(self.proposal(), alternatives=malformed)))
        attempt = eve.normalize_world_inquiry_attempt(dict(action="service_health_check", observed="process healthy", outcome_ok=True, reasoning_proposal=proposal))
        self.assertEqual("unverified_hypotheses", attempt["reasoning_proposal"]["epistemic_status"])

    def test_overridden_action_cannot_borrow_original_hypotheses(self):
        guidance = {"selected_inquiry": {"id": "question-one", "source_fingerprint": "source-one"}, "inquiry_action": "openclaw_log_check"}
        result = eve.attach_endogenous_inquiry_to_decision(dict(action="openclaw_log_check", reasoning_proposal=self.proposal()), guidance)
        self.assertEqual({}, result["reasoning_proposal"])

    def test_real_persistence_restart_recovery_and_world_model_ablation(self):
        """The changed next action must depend on a saved failed observation."""
        inquiry = dict(id="question-one", question="Which current observation resolves this receipt?",
                       domain="runtime_receipt", source_fingerprint="source-one", priority=94,
                       status="open", confidence=84,
                       candidate_actions=["openclaw_log_check", "service_health_check"],
                       selected_action="openclaw_log_check", attempts=[])
        initial = eve.normalize_world_model_state(dict(eve.default_world_model_state(), open_questions=[inquiry]))

        class DiskRepository:
            def __init__(self, path): self.path = path
            def update(self, mutator):
                data = json.loads(self.path.read_text())
                result = mutator(data)
                self.path.write_text(json.dumps(data))
                return result

        def build(world, lesions=()):
            return kernel.build_conscious_state(source="isolated_test", workspace={},
                self_model={"identity": "Eve"}, world_model=world, relationship_model={},
                other_minds_model={}, homeostasis={"regulation_mode": "orient", "pressures": []},
                plan_model={"available": False}, autonomy_agenda={}, memory_items=[],
                lesions=list(lesions), now=AT)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "world.json"); path.write_text(json.dumps(initial))
            decision = dict(action="openclaw_log_check", inquiry_id="question-one",
                            inquiry_source_fingerprint="source-one",
                            reasoning_proposal=dict(self.proposal(), action="openclaw_log_check"))
            failure = dict(action="openclaw_log_check", execution_id="failure-one", status="error",
                           ok=False, execution_verification_ok=False, summary="No trustworthy response")
            with patch.object(eve, "WORLD_MODEL_REPOSITORY", DiskRepository(path)):
                result = eve.record_world_model_inquiry_observation(decision, failure, run_id="run-one", source_cycle_id="cycle-one")
                duplicate = eve.record_world_model_inquiry_observation(decision, failure, run_id="run-one", source_cycle_id="cycle-one")
                stale = eve.record_world_model_inquiry_observation(dict(decision, inquiry_source_fingerprint="different"),
                    dict(failure, execution_id="stale"), run_id="run-two", source_cycle_id="cycle-two")
            self.assertTrue(result["recovery_required"])
            self.assertEqual("already_observed", duplicate["status"])
            self.assertEqual("source_mismatch", stale["status"])
            recovered_world = json.loads(path.read_text())  # New instance: no process-local continuity.
            saved = recovered_world["open_questions"][0]
            self.assertEqual(1, len(saved["attempts"]))
            self.assertEqual("failure-one", saved["attempts"][0]["execution_id"])
            restored = build(recovered_world)
            self.assertEqual("service_health_check", restored["action_model"]["selected_intention"]["id"])
            self.assertEqual("openclaw_log_check", build(initial)["action_model"]["selected_intention"]["id"])
            self.assertFalse(any(a.get("inquiry_id") == "question-one"
                for a in build(recovered_world, ("world_model",))["action_model"]["affordances"]))
            self.assertEqual(2, len(restored["world_model"]["selected_question"]["prior_hypotheses"]))
            success = dict(action="service_health_check", execution_id="success-two", executed=True,
                           status="completed", ok=True, execution_verification_ok=True, summary="Endpoint responded")
            next_decision = dict(decision, action="service_health_check", reasoning_proposal=self.proposal())
            with patch.object(eve, "WORLD_MODEL_REPOSITORY", DiskRepository(path)):
                wrong_action = eve.record_world_model_inquiry_observation(next_decision, failure, run_id="run-two", source_cycle_id="cycle-two")
                completed = eve.record_world_model_inquiry_observation(next_decision, success, run_id="run-two", source_cycle_id="cycle-two")
            self.assertEqual("action_mismatch", wrong_action["status"])
            self.assertTrue(completed["answered"])
            final_world = json.loads(path.read_text())
            self.assertFalse(final_world["open_questions"])
            attempts = final_world["answered_questions"][0]["attempts"]
            self.assertEqual(["failure-one", "success-two"], [a["execution_id"] for a in attempts])
            self.assertTrue(all(a["reasoning_proposal"]["epistemic_status"] == "unverified_hypotheses" for a in attempts))

    def test_exhausted_inquiry_is_retained_but_no_longer_competes_for_attention(self):
        inquiry = dict(id="exhausted", question="No current observation remains", status="in_progress",
                       candidate_actions=["service_health_check"], selected_action="",
                       attempts=[dict(action="service_health_check", outcome_ok=None, status="pending")])
        world = {"open_questions": [inquiry]}
        original = copy.deepcopy(world)
        self.assertEqual([], kernel._open_world_inquiries(world))
        self.assertEqual(original, world)

    def test_repaired_candidate_becomes_reviewable_pair_not_canonical_knowledge(self):
        result = dict(used_fallback=False, model_path_repaired=True, grounded=True,
            attempted_model="eve-fast", attempted_response="Unsupported origin.",
            response="The selected goal is to inspect the workspace.",
            current_state_record={"target_kind": "durable_goal", "durable_goal": "Inspect the workspace"},
            initial_epistemic_critic={"ok": False}, epistemic_critic={"ok": True},
            verified_action_evidence=[{"action": "service_health_check", "completed_at": AT}])
        with tempfile.TemporaryDirectory() as directory, patch.object(eve, "CONTINUOUS_THOUGHT_LEARNING_PATH", Path(directory, "pairs.jsonl")), patch.object(eve, "mirror_store_file_to_runtime") as mirror:
            pair = eve.record_continuous_thought_learning_episode(result, source="isolated_test")
        self.assertEqual("critic_checked_model_revision", pair["correction_source"])
        self.assertFalse(pair["safe_for_training"])
        self.assertFalse(pair["authority"]["canonical_memory_writer"])
        self.assertFalse(pair["initial_epistemic_critic"]["ok"])
        self.assertEqual(AT, pair["verified_action_evidence"][0]["completed_at"])


if __name__ == "__main__":
    unittest.main()
