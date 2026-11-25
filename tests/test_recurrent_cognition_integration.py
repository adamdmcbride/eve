import tempfile
import unittest
import copy
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import eve
import eve_consciousness
import eve_recurrent_cognition as recurrent
from tests.test_conscious_state import fixture_inputs
from tests.test_developmental_cycle import cycle_test_patches


AT = "2026-08-23T20:00:00+00:00"
ADMITTED = [
    "system_tasks",
    "service_health_check",
    "cleanup_candidate_check",
    "openclaw_log_check",
    "openclaw_sync_check",
]


def action_result(*, ok=True, verified=True, execution_id="execution-1"):
    return {
        "executed": True,
        "ok": ok,
        "status": "completed",
        "summary": "The action produced a bounded result.",
        "execution_id": execution_id,
        "execution_backend": "deterministic",
        "execution_tree_status": "BYPASSED",
        "execution_verification_ok": verified,
        "execution_summary": "The action produced a bounded result.",
        "typed_contract": {
            "schema_id": "service_health_check_result.v1",
            "valid": True,
            "repaired": False,
            "issues": [],
        },
    }


def module_result(action="service_health_check", *, ok=True, verified=True, execution_id="execution-1"):
    return recurrent.build_typed_module_result(
        action,
        action_result(ok=ok, verified=verified, execution_id=execution_id),
        source_cycle_id="source-cycle-1",
        observed_at=AT,
    )


def conscious_action_state(action):
    state = eve_consciousness.default_state()
    state.update(
        {
            "cycle_id": "cycle-conscious-action-test",
            "updated_at": eve.utc_now(),
            "status": "integrated",
            "broadcast": {
                "content": "A bounded recurrent inquiry won attention.",
                "ignition_score": 78,
                "source_kinds": ["module_query"],
                "access_scope": ["mind", "memory", "action"],
                "why_selected": "It had the highest current expected value.",
            },
            "action_model": {
                "affordances": [],
                "selected_intention": {
                    "id": action,
                    "description": f"Execute {action} and observe the result",
                    "value": 82.5,
                },
                "actionable": True,
            },
        }
    )
    return state


class RecurrentCognitionIntegrationTests(unittest.TestCase):
    def test_negative_execution_evidence_vetoes_success_across_consumers(self):
        variants = [
            {"ok": False}, {"ok": "false"}, {"executed": False}, {"executed": "false"},
            {"result_ok": False}, {"typed_contract_ok": "false"},
            {"typed_contract": {"valid": False}}, {"typed_contract": {"valid": "false"}},
            {"execution_tree_status": "FAILURE"}, {"status": "failed"},
        ]
        for fields in variants:
            with self.subTest(fields=fields):
                result = {**action_result(), **fields, "summary": "completed successfully"}
                before = copy.deepcopy(result)
                observed = eve.autonomy_action_outcome_observation(result)
                typed = recurrent.build_typed_module_result(
                    "service_health_check", result, source_cycle_id="current", observed_at=AT
                )
                self.assertFalse(observed["outcome_ok"])
                self.assertTrue(observed["consequence_observed"])
                self.assertFalse(eve.action_result_verified_for_completion(result))
                self.assertFalse(eve.action_execution_verified(result))
                self.assertNotEqual("verified_success", typed["outcome_state"])
                self.assertEqual("repair_or_alternative", recurrent.derive_next_module_query(
                    typed, admitted_actions=ADMITTED
                )["query_kind"])
                self.assertEqual(before, result)

    def test_malformed_execution_flags_remain_unobserved_not_positive_learning(self):
        for fields in [
            {"ok": "unknown"}, {"executed": []}, {"typed_contract": []},
            {"typed_contract": {}}, {"typed_contract": {"valid": "unknown"}},
        ]:
            with self.subTest(fields=fields):
                result = {**action_result(), **fields}
                observed = eve.autonomy_action_outcome_observation(result)
                typed = recurrent.build_typed_module_result(
                    "service_health_check", result, source_cycle_id="current", observed_at=AT
                )
                self.assertIsNone(observed["outcome_ok"])
                self.assertFalse(observed["consequence_observed"])
                self.assertFalse(eve.action_result_verified_for_completion(result))
                self.assertFalse(typed["grounded"])
                self.assertEqual("unverified", typed["outcome_state"])
                self.assertEqual("verification_gap", recurrent.derive_next_module_query(
                    typed, admitted_actions=ADMITTED
                )["query_kind"])

    def test_consistent_receipt_and_internal_process_evidence_stay_distinct(self):
        verified = eve.autonomy_action_outcome_observation(action_result())
        self.assertTrue(verified["outcome_ok"])
        self.assertEqual("explicit_verification", verified["evidence_kind"])
        process = {"status": "completed", "ok": True}
        observed = eve.autonomy_action_outcome_observation(process)
        self.assertTrue(observed["outcome_ok"])
        self.assertEqual("executor_process_result", observed["evidence_kind"])
        self.assertFalse(eve.action_result_verified_for_completion(process))
        self.assertFalse(eve.autonomy_action_outcome_observation(
            {**process, "executed": False}
        )["outcome_ok"])
        self.assertTrue(eve.action_result_verified_for_completion(action_result()))

    def test_typed_contract_false_is_not_serialized_as_true(self):
        typed = recurrent.build_typed_module_result(
            "service_health_check", {**action_result(), "typed_contract": {"valid": "false"}},
            source_cycle_id="current", observed_at=AT,
        )
        self.assertIs(typed["typed_contract_valid"], False)
        self.assertEqual("verified_failure", typed["outcome_state"])
        self.assertTrue(recurrent.module_result_is_valid(typed))

    def test_memory_shadow_retains_wrapper_failure_over_raw_success(self):
        row = {**action_result(), "action": "service_health_check", "created_at": AT,
               "execution_verification_ok": False, "verification_ok": True}
        shadow = recurrent.evaluate_action_memory_shadow([row], "service_health_check", now=AT)
        self.assertEqual("choose_alternative", shadow["recommended_policy_action"])
        self.assertFalse(shadow["action_change_applied"])

    def test_memory_shadow_preserves_ledger_aliases_and_optional_contract_absence(self):
        row = {"id": "legacy-receipt", "action": "service_health_check", "created_at": AT,
               "verification_ok": True, "result_ok": True, "typed_contract_ok": None}
        good = recurrent.evaluate_action_memory_shadow([row], "service_health_check", now=AT)
        bad = recurrent.evaluate_action_memory_shadow([{**row, "ok": False}], "service_health_check", now=AT)
        self.assertEqual("repeat_candidate", good["recommended_policy_action"])
        self.assertEqual("choose_alternative", bad["recommended_policy_action"])
        self.assertFalse(good["action_change_applied"])
        self.assertFalse(bad["action_change_applied"])

    def test_failed_preflight_preserves_fallback_but_never_credits_old_cycle(self):
        for preflight in [RuntimeError("preflight unavailable"), {}, None,
                          {**conscious_action_state("updates_status"), "status": "completed"}]:
            with self.subTest(preflight=type(preflight).__name__), tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
                for item in cycle_test_patches(Path(tmp) / "cycles.jsonl"):
                    stack.enter_context(item)
                stale = conscious_action_state("updates_status")
                old = stack.enter_context(patch.object(eve, "load_conscious_state", return_value=stale))
                build = stack.enter_context(patch.object(eve, "build_recurrent_conscious_state", side_effect=[preflight]))
                complete = stack.enter_context(patch.object(eve, "complete_recurrent_conscious_cycle"))
                execute = stack.enter_context(patch.object(eve, "run_operational_action_tree", return_value=action_result()))
                repair = stack.enter_context(patch.object(eve, "record_developmental_failure_task", return_value={"id": "repair"}))
                state = {}
                cycle = eve.run_developmental_cycle(dict(eve.DEFAULT_CONFIG), state, source="test")
                execute.assert_called_once()
                old.assert_not_called()
                complete.assert_not_called()
                build.assert_called_once()
                repair.assert_called_once()
                self.assertEqual("service_health_check", execute.call_args.args[0])
                self.assertNotEqual("recurrent_conscious_state", cycle["selection_source"])
                self.assertEqual({}, cycle["typed_module_result"])
                self.assertEqual({}, cycle["next_module_query"])
                self.assertFalse(cycle["conscious_action_binding"]["preflight_opened"])
                self.assertEqual("", cycle["conscious_action_binding"]["source_cycle_id"])
                self.assertEqual("needs_repair", state["last_developmental_cycle_result"])

    def test_developmental_contradiction_closes_negative_not_success(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            for item in cycle_test_patches(Path(tmp) / "cycles.jsonl"):
                stack.enter_context(item)
            result = {**action_result(), "ok": "false", "summary": "completed successfully"}
            stack.enter_context(patch.object(eve, "run_operational_action_tree", return_value=result))
            complete = stack.enter_context(patch.object(eve, "complete_recurrent_conscious_cycle", return_value={}))
            repair = stack.enter_context(patch.object(eve, "record_developmental_failure_task", return_value={"id": "repair"}))
            state = {}
            cycle = eve.run_developmental_cycle(dict(eve.DEFAULT_CONFIG), state, source="test")
            self.assertIs(complete.call_args.kwargs["outcome"]["ok"], False)
            self.assertIs(cycle["action_result"]["ok"], False)
            self.assertFalse(cycle["action_result"]["completion_verified"])
            self.assertEqual("needs_repair", state["last_developmental_cycle_result"])
            repair.assert_called_once()

    def test_corrected_consequence_changes_next_cycle_action_reliability(self):
        # Hold the context and verifier fixed. Only actual result success changes.
        adjustments = {}
        for result_ok in (True, False):
            inputs = fixture_inputs()
            inputs["inbound"] = ""
            opened = eve_consciousness.build_conscious_state(**inputs)
            result = action_result(ok=result_ok)
            observed = eve.autonomy_action_outcome_observation(result)
            completed = eve_consciousness.complete_cycle(
                opened,
                actual_process={"lanes": ["planner"], "action_id": "service_health_check",
                                "tools_used": ["service_health_check"], "revision_used": False},
                outcome={"ok": observed["outcome_ok"], "observed": observed["consequence_observed"],
                         "evidence_kind": observed["evidence_kind"], "evidence_id": result["execution_id"],
                         "execution_id": result["execution_id"], "source_cycle_id": opened["cycle_id"],
                         "action": "service_health_check"},
                now="2026-07-12T18:02:00+00:00",
            )
            observations = completed["learning"]["action_models"]["service_health_check"]["observations"]
            self.assertEqual([result_ok], [item["ok"] for item in observations])
            inputs.update(previous_state=completed, now="2026-07-12T18:03:00+00:00")
            next_state = eve_consciousness.build_conscious_state(**inputs)
            affordance = next(item for item in next_state["action_model"]["affordances"]
                              if item["id"] == "service_health_check")
            adjustments[result_ok] = affordance["learned_adjustment"]
        self.assertGreater(adjustments[True], 0)
        self.assertLess(adjustments[False], 0)

    def test_recurrence_recovers_after_unbound_fallback_without_backfilling_old_credit(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            for item in cycle_test_patches(Path(tmp) / "cycles.jsonl"):
                stack.enter_context(item)
            fresh = conscious_action_state("updates_status")
            fresh["cycle_id"] = "fresh-recovered-cycle"
            successor = conscious_action_state("service_health_check")
            successor["cycle_id"] = "successor"
            stack.enter_context(patch.object(eve, "build_recurrent_conscious_state", side_effect=[
                RuntimeError("preflight unavailable"), fresh, successor,
            ]))
            execute = stack.enter_context(patch.object(eve, "run_operational_action_tree", side_effect=[
                action_result(execution_id="fallback-execution"), action_result(execution_id="recovered-execution"),
            ]))
            complete = stack.enter_context(patch.object(eve, "complete_recurrent_conscious_cycle", return_value={**fresh, "status": "completed"}))
            stack.enter_context(patch.object(eve, "record_developmental_failure_task", return_value={"id": "repair"}))
            state = {}
            first = eve.run_developmental_cycle(dict(eve.DEFAULT_CONFIG), state, source="test")
            second = eve.run_developmental_cycle(dict(eve.DEFAULT_CONFIG), state, source="test")
            self.assertEqual(["service_health_check", "updates_status"], [call.args[0] for call in execute.call_args_list])
            complete.assert_called_once()
            self.assertIs(fresh, complete.call_args.kwargs["opened_state"])
            self.assertEqual("recovered-execution", complete.call_args.kwargs["outcome"]["execution_id"])
            self.assertFalse(first["conscious_action_binding"]["preflight_opened"])
            self.assertTrue(second["conscious_action_binding"]["preflight_opened"])
            self.assertEqual("fresh-recovered-cycle", second["next_module_query"]["source_cycle_id"])
            self.assertEqual("verified", state["last_developmental_cycle_result"])

    def test_typed_result_is_bound_to_exact_cycle_and_evidence(self):
        result = module_result()

        self.assertEqual(recurrent.MODULE_RESULT_SCHEMA, result["schema_id"])
        self.assertEqual("source-cycle-1", result["source_cycle_id"])
        self.assertEqual("execution-1", result["execution_id"])
        self.assertEqual(["execution-1"], result["evidence_ids"])
        self.assertEqual("verified_success", result["outcome_state"])
        self.assertTrue(result["grounded"])
        self.assertEqual(64, len(result["result_sha256"]))

    def test_next_query_changes_with_the_observed_result(self):
        success = recurrent.derive_next_module_query(
            module_result("openclaw_sync_check", ok=True, verified=True, execution_id="success"),
            admitted_actions=ADMITTED,
            recent_actions=[],
        )
        failure = recurrent.derive_next_module_query(
            module_result("openclaw_sync_check", ok=False, verified=False, execution_id="failure"),
            admitted_actions=ADMITTED,
            recent_actions=[],
        )

        self.assertEqual("consequence_and_novelty", success["query_kind"])
        self.assertEqual("repair_or_alternative", failure["query_kind"])
        self.assertEqual("system_tasks", success["target_action"])
        self.assertEqual("openclaw_log_check", failure["target_action"])
        self.assertNotEqual(success["query_sha256"], failure["query_sha256"])
        self.assertNotEqual(success["question"], failure["question"])

    def test_tampered_result_or_query_is_rejected(self):
        result = module_result()
        tampered_result = dict(result)
        tampered_result["outcome_state"] = "verified_failure"
        self.assertFalse(recurrent.module_result_is_valid(tampered_result))
        with self.assertRaises(ValueError):
            recurrent.derive_next_module_query(
                tampered_result,
                admitted_actions=ADMITTED,
                recent_actions=[],
            )

        query = recurrent.derive_next_module_query(
            result,
            admitted_actions=ADMITTED,
            recent_actions=[],
        )
        tampered_query = dict(query)
        tampered_query["target_action"] = "openclaw_sync_check"
        self.assertFalse(recurrent.module_query_is_valid(tampered_query))

    def test_empty_query_field_preserves_existing_checkpoint_digest(self):
        legacy_shaped = eve_consciousness.default_state()
        legacy_shaped.pop("module_query", None)
        upgraded = copy.deepcopy(legacy_shaped)
        upgraded["module_query"] = {}

        self.assertEqual(
            eve_consciousness.state_checkpoint_digest(legacy_shaped),
            eve_consciousness.state_checkpoint_digest(upgraded),
        )

    def test_action_memory_is_selective_and_never_applies_in_shadow(self):
        failed = {
            "id": "failed-receipt",
            "action": "service_health_check",
            "created_at": "2026-08-23T19:00:00+00:00",
            "verification_ok": False,
            "typed_contract_ok": True,
            "result_ok": False,
            "tree_status": "FAILURE",
        }
        succeeded = {
            **failed,
            "id": "success-receipt",
            "verification_ok": True,
            "result_ok": True,
            "tree_status": "SUCCESS",
        }

        failed_shadow = recurrent.evaluate_action_memory_shadow(
            [failed], "service_health_check", now=AT
        )
        success_shadow = recurrent.evaluate_action_memory_shadow(
            [succeeded], "service_health_check", now=AT
        )
        novel_shadow = recurrent.evaluate_action_memory_shadow([], "system_tasks", now=AT)

        self.assertTrue(failed_shadow["would_intervene"])
        self.assertEqual("choose_alternative", failed_shadow["recommended_policy_action"])
        self.assertEqual(["failed-receipt"], failed_shadow["evidence_ids"])
        self.assertFalse(success_shadow["would_intervene"])
        self.assertEqual("repeat_candidate", success_shadow["recommended_policy_action"])
        self.assertEqual(["success-receipt"], success_shadow["evidence_ids"])
        self.assertFalse(novel_shadow["would_intervene"])
        self.assertFalse(failed_shadow["action_change_applied"])
        self.assertFalse(success_shadow["action_change_applied"])

    def test_latest_action_receipt_supersedes_older_outcome(self):
        rows = [
            {
                "id": "old-success",
                "action": "service_health_check",
                "created_at": "2026-08-23T18:00:00+00:00",
                "verification_ok": True,
                "typed_contract_ok": True,
                "result_ok": True,
                "tree_status": "SUCCESS",
            },
            {
                "id": "new-failure",
                "action": "service_health_check",
                "created_at": "2026-08-23T19:00:00+00:00",
                "verification_ok": False,
                "typed_contract_ok": True,
                "result_ok": False,
                "tree_status": "FAILURE",
            },
        ]

        shadow = recurrent.evaluate_action_memory_shadow(
            list(reversed(rows)), "service_health_check", now=AT
        )

        self.assertTrue(shadow["would_intervene"])
        self.assertEqual("choose_alternative", shadow["recommended_policy_action"])
        self.assertEqual(["new-failure", "old-success"], shadow["evidence_ids"])

    def test_internal_module_query_ignites_without_impersonating_user_input(self):
        inputs = fixture_inputs()
        inputs.update(
            workspace={
                "summary": "A steady internal cycle.",
                "current_experience": "A steady internal cycle.",
                "dominant_pressures": [],
                "active_goals": [],
                "salient_percepts": [],
                "prediction_errors": [],
                "continuity_threads": [],
                "surprise_signals": [],
                "consequence_trace": [],
                "action_readiness": [],
                "workspace_state": {"focus": "", "mode": "steady"},
            },
            homeostasis={},
            plan_model={},
            autonomy_agenda={},
            memory_items=[],
        )
        query = recurrent.derive_next_module_query(
            module_result(),
            admitted_actions=ADMITTED,
            recent_actions=[],
        )
        inputs["module_query"] = query

        state = eve_consciousness.build_conscious_state(**inputs)

        self.assertEqual("module_query", state["perception"]["winning_coalition"]["kind"])
        self.assertEqual(query["question"], state["broadcast"]["content"])
        self.assertEqual(query["id"], state["module_query"]["id"])
        self.assertEqual(query["target_action"], state["action_model"]["selected_intention"]["id"])
        self.assertNotIn(
            "respond_to_user",
            [item["id"] for item in state["action_model"]["affordances"]],
        )
        self.assertIn("recurrent_module_query", state["causal_provenance"])

    def test_real_user_input_still_outranks_background_module_query(self):
        inputs = fixture_inputs()
        inputs["inbound"] = "Please answer this new question directly."
        inputs["module_query"] = recurrent.derive_next_module_query(
            module_result(),
            admitted_actions=ADMITTED,
            recent_actions=[],
        )

        state = eve_consciousness.build_conscious_state(**inputs)

        self.assertEqual("inbound", state["perception"]["winning_coalition"]["kind"])
        self.assertEqual("respond_to_user", state["action_model"]["selected_intention"]["id"])

    def test_runtime_carries_unconsumed_typed_query_across_recurrent_builds(self):
        inputs = fixture_inputs()
        query = recurrent.derive_next_module_query(
            module_result(),
            admitted_actions=ADMITTED,
            recent_actions=[],
        )
        previous = eve_consciousness.default_state()
        previous.update(
            cycle_id="previous-cycle",
            cycle_index=3,
            updated_at="2026-08-23T19:59:00+00:00",
            status="integrated",
            module_query=copy.deepcopy(query),
        )
        with (
            patch.object(eve, "load_conscious_state", return_value=previous),
            patch.object(eve, "load_autonomy_agenda", return_value={}),
            patch.object(eve, "load_human_context", return_value=eve.default_human_context()),
            patch.object(eve, "select_conscious_memory_items", return_value=[]),
            patch.object(
                eve,
                "load_state",
                return_value={
                    "daemon_started_at": "2026-08-23T19:00:00+00:00",
                    "daemon_process_id": 4321,
                },
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
                plan_model={},
                persist=False,
            )

        self.assertEqual(query["id"], state["module_query"]["id"])
        self.assertTrue(
            any(
                item.get("module_query_id") == query["id"]
                for item in state["perception"]["salient_inputs"]
            )
        )

    def test_developmental_cycle_carries_actual_result_into_next_internal_query(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cycles_path = Path(temp_dir) / "developmental_cycles.jsonl"
            opened = conscious_action_state("service_health_check")
            calls = []

            def build_state(*args, **kwargs):
                calls.append(kwargs)
                if len(calls) == 1:
                    return opened
                query = kwargs.get("module_query") or {}
                state = conscious_action_state(query.get("target_action") or "system_tasks")
                state["cycle_id"] = "next-conscious-cycle"
                state["module_query"] = dict(query)
                state["broadcast"] = {
                    "content": query.get("question") or "",
                    "ignition_score": 80,
                    "source_kinds": ["module_query"],
                    "access_scope": ["mind", "memory", "action"],
                    "why_selected": "The exact prior result created this query.",
                }
                return state

            with ExitStack() as stack:
                for item in cycle_test_patches(cycles_path):
                    stack.enter_context(item)
                stack.enter_context(
                    patch.object(eve, "build_recurrent_conscious_state", side_effect=build_state)
                )
                stack.enter_context(
                    patch.object(
                        eve,
                        "run_operational_action_tree",
                        return_value=action_result(),
                    )
                )
                cycle = eve.run_developmental_cycle(
                    dict(eve.DEFAULT_CONFIG),
                    {},
                    source="test",
                )

        self.assertEqual(2, len(calls))
        query = cycle["next_module_query"]
        self.assertEqual(recurrent.MODULE_RESULT_SCHEMA, cycle["typed_module_result"]["schema_id"])
        self.assertEqual(recurrent.MODULE_QUERY_SCHEMA, query["schema_id"])
        self.assertEqual(query, calls[1]["module_query"])
        self.assertTrue(cycle["conscious_action_binding"]["next_module_query_broadcast"])
        self.assertEqual("shadow", cycle["memory_attention_shadow"]["mode"])
        self.assertFalse(cycle["memory_attention_shadow"]["action_change_applied"])
        self.assertEqual("", cycle["failure_mode_if_any"])
        rendered = eve.format_developmental_cycle_record(cycle, full=True)
        self.assertIn("memory_attention_shadow:", rendered)
        self.assertIn("typed_module_result:", rendered)
        self.assertIn("next_module_query:", rendered)


if __name__ == "__main__":
    unittest.main()
