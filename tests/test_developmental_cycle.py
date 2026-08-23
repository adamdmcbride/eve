import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import eve
import eve_consciousness
import eve_store


def noncontrolling_conscious_state():
    state = eve_consciousness.default_state()
    state.update(
        {
            "cycle_id": "cycle-noncontrolling-test",
            "updated_at": eve.utc_now(),
            "status": "integrated",
            "broadcast": {
                "content": "The test state is available to mind and memory only.",
                "ignition_score": 50,
                "source_kinds": ["test"],
                "access_scope": ["mind", "memory"],
                "why_selected": "Stable test fixture.",
            },
        }
    )
    return state


def cycle_test_patches(cycles_path: Path):
    return [
        patch.object(eve, "DEVELOPMENTAL_CYCLES_PATH", cycles_path),
        patch.object(eve, "ensure_store", lambda: None),
        patch.object(eve, "mirror_store_file_to_runtime", lambda path: None),
        patch.object(eve, "append_entry", lambda kind, text, tags=None, metadata=None: {"kind": kind, "text": text}),
        patch.object(eve, "count_jsonl_records", lambda path: 0),
        patch.object(eve, "running_from_runtime_bundle", lambda: False),
        patch.object(eve, "daemon_runtime_running", lambda: False),
        patch.object(eve, "read_action_executions", lambda *args, **kwargs: []),
        patch.object(eve, "read_developmental_cycles", lambda *args, **kwargs: []),
        patch.object(eve, "read_system_tasks", lambda *args, **kwargs: []),
        patch.object(eve, "read_failure_clusters", lambda *args, **kwargs: []),
        patch.object(eve, "load_runtime_identity", lambda *args, **kwargs: dict(eve.DEFAULT_RUNTIME_IDENTITY)),
        patch.object(eve, "load_human_context", lambda *args, **kwargs: dict(eve.DEFAULT_HUMAN_CONTEXT)),
        patch.object(eve, "load_active_mind", lambda *args, **kwargs: {**eve.default_active_mind(), "current_focus": "Keep growth grounded."}),
        patch.object(eve, "load_global_workspace", lambda *args, **kwargs: {**eve.default_global_workspace(), "summary": "Workspace is stable enough for a bounded action."}),
        patch.object(eve, "load_homeostasis", lambda *args, **kwargs: dict(eve.default_homeostasis_state())),
        patch.object(eve, "load_component_update_state", lambda *args, **kwargs: eve.default_component_update_state()),
        patch.object(eve, "load_conscious_state", lambda *args, **kwargs: noncontrolling_conscious_state()),
        patch.object(eve, "build_recurrent_conscious_state", lambda *args, **kwargs: noncontrolling_conscious_state()),
        patch.object(
            eve,
            "complete_recurrent_conscious_cycle",
            lambda *args, **kwargs: {
                **dict(kwargs.get("opened_state") or noncontrolling_conscious_state()),
                "status": "completed",
                "cycle_outcome": {"overall_prediction_error": 0, "outcome_observed": True},
            },
        ),
        patch.object(
            eve,
            "build_organ_assimilation_report",
            lambda *args, **kwargs: {
                "schema_id": "eve_organ_assimilation_report.v1",
                "generated_at": "2026-05-06T00:00:00+00:00",
                "resident_chat_lane_delta": 0,
                "organs": [
                    {
                        "id": "five_model_lanes",
                        "label": "Five model lanes",
                        "status": "healthy",
                        "pressure": 20,
                        "summary": "Five lanes are present.",
                    }
                ],
            },
        ),
        patch.object(eve, "append_organ_pulse_record", lambda *args, **kwargs: {}),
    ]


class DevelopmentalCycleTests(unittest.TestCase):
    @staticmethod
    def conscious_action_state(action="updates_status", *, action_access=True, lesions=None):
        state = eve_consciousness.default_state()
        state.update(
            {
                "cycle_id": "cycle-conscious-action-test",
                "updated_at": eve.utc_now(),
                "status": "integrated",
                "lesions": list(lesions or []),
                "broadcast": {
                    "content": "A pending component signal won the current attention competition.",
                    "ignition_score": 78,
                    "source_kinds": ["goal"],
                    "access_scope": ["mind", "memory", "action"] if action_access else ["mind", "memory"],
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

    def test_full_developmental_formatter_exposes_conscious_action_binding(self):
        output = eve.format_developmental_cycle_record(
            {
                "id": "developmental-test",
                "timestamp": "2026-08-23T00:00:00+00:00",
                "capability_attempted": "system_tasks",
                "selection_source": "recurrent_conscious_state",
                "conscious_action_binding": {
                    "source_cycle_id": "cycle-before",
                    "selected_action": "system_tasks",
                    "actual_action": "system_tasks",
                    "matched_actual": True,
                    "outcome_observed": True,
                    "outcome_ok": True,
                    "completed_cycle_id": "cycle-before",
                    "next_cycle_id": "cycle-after",
                },
            },
            full=True,
        )

        self.assertIn("selection_source: recurrent_conscious_state", output)
        self.assertIn("conscious_action_binding:", output)
        self.assertIn('"source_cycle_id": "cycle-before"', output)
        self.assertIn('"matched_actual": true', output)

    def test_endogenous_inquiry_overrides_timer_curiosity_and_closes_into_world_model(self):
        inquiry = {
            "id": "inquiry-service-health",
            "question": "What is the current verified service-health state?",
            "domain": "service_health",
            "source": "state.service_health_summary",
            "source_fingerprint": "service-health-missing-v1",
            "status": "open",
            "priority": 90,
            "confidence": 80,
            "candidate_actions": ["service_health_check"],
            "selected_action": "service_health_check",
            "expected_observation": "A fresh service-health result should identify current failures.",
            "attempt_count": 0,
        }
        snapshot = {
            "counts": {},
            "components": {},
            "openclaw": {},
            "system": {},
            "autonomy": {},
            "conscious_state": {
                "selected_inquiry": inquiry,
                "affordances": [
                    {
                        "id": "service_health_check",
                        "value": 98,
                        "expected_utility": 82,
                        "epistemic_value": 100,
                        "continuity_support": 90,
                        "broadcast_alignment": 100,
                        "risk": 12,
                        "inquiry_id": inquiry["id"],
                    }
                ],
            },
        }
        menu = eve.autonomy_free_run_action_menu(remaining_seconds=120)
        guidance = eve.autonomy_free_run_guidance(
            menu,
            snapshot,
            previous_actions=[],
            remaining_seconds=120,
            style="explorer",
            config={**eve.DEFAULT_CONFIG, "autonomy_curiosity_enabled": True},
        )
        action, override, policy = eve.finalize_autonomy_free_run_choice(
            "capability_tryout",
            menu=menu,
            guidance=guidance,
            recommended_actions=guidance["recommended_actions"],
            selection_policy="test",
        )

        self.assertTrue(guidance["require_inquiry_probe"])
        self.assertFalse(guidance["require_curiosity_probe"])
        self.assertEqual("service_health_check", action)
        self.assertEqual("forced_endogenous_inquiry_probe", policy)

        class InMemoryRepository:
            def __init__(self, payload):
                self.payload = payload

            def update(self, mutator):
                return mutator(self.payload)

        repository = InMemoryRepository(
            eve.normalize_world_model_state(
                {
                    **eve.default_world_model_state(),
                    "open_questions": [{**inquiry, "attempts": []}],
                }
            )
        )
        decision = eve.attach_endogenous_inquiry_to_decision(
            {
                "action": action,
                "reason": "The chooser preferred an unrelated capability tryout.",
                "expected_signal": "",
                "model": "test",
                "selection_policy": policy,
                "override": override,
            },
            guidance,
        )
        result = {
            "action": action,
            "status": "completed",
            "ok": True,
            "execution_verification_ok": True,
            "summary": "All required services answered their bounded health probes.",
        }
        with patch.object(eve, "WORLD_MODEL_REPOSITORY", repository):
            observation = eve.record_world_model_inquiry_observation(
                decision,
                result,
                run_id="inquiry-run",
                source_cycle_id="cycle-1",
            )

        self.assertTrue(observation["answered"])
        self.assertIn("recurrent world model", decision["reason"])
        self.assertEqual(
            "The chooser preferred an unrelated capability tryout.",
            decision["chooser_reason"],
        )
        self.assertEqual([], repository.payload["open_questions"])
        self.assertEqual("answered", repository.payload["answered_questions"][0]["status"])
        self.assertEqual("cycle-1", repository.payload["answered_questions"][0]["attempts"][0]["source_cycle_id"])

    def test_failed_inquiry_probe_forces_unused_alternative_then_revises_belief(self):
        inquiry = {
            "id": "inquiry-alternative-probe",
            "question": "Which current observation resolves the contradictory runtime receipt?",
            "domain": "runtime_receipt",
            "source": "runtime.receipt",
            "source_fingerprint": "runtime-receipt-v1",
            "status": "open",
            "priority": 94,
            "confidence": 84,
            "candidate_actions": ["openclaw_log_check", "service_health_check"],
            "selected_action": "openclaw_log_check",
            "expected_observation": "An independent live observation should resolve the receipt contradiction.",
            "attempts": [],
        }

        class InMemoryRepository:
            def __init__(self, payload):
                self.payload = payload

            def update(self, mutator):
                return mutator(self.payload)

        repository = InMemoryRepository(
            eve.normalize_world_model_state(
                {
                    **eve.default_world_model_state(),
                    "open_questions": [inquiry],
                }
            )
        )
        first_state = eve_consciousness.build_conscious_state(
            source="test",
            workspace={"summary": "One runtime receipt remains contradictory."},
            self_model={"identity": "Eve is one local control system."},
            world_model=repository.payload,
            relationship_model={},
            other_minds_model={},
            homeostasis={"regulation_mode": "orient", "pressures": []},
            plan_model={"available": False},
            autonomy_agenda={},
            memory_items=[],
            now="2026-07-19T06:00:00+00:00",
        )
        with patch.object(eve, "WORLD_MODEL_REPOSITORY", repository):
            failed = eve.record_world_model_inquiry_observation(
                {
                    "action": "openclaw_log_check",
                    "inquiry_id": inquiry["id"],
                    "epistemic_question": inquiry["question"],
                },
                {
                    "action": "openclaw_log_check",
                    "status": "error",
                    "ok": False,
                    "execution_verification_ok": False,
                    "summary": "The first evidence path failed before returning a trustworthy signal.",
                },
                run_id="recovery-run",
                source_cycle_id=first_state["cycle_id"],
            )

        open_question = repository.payload["open_questions"][0]
        self.assertFalse(failed["answered"])
        self.assertTrue(failed["recovery_required"])
        self.assertEqual("service_health_check", failed["next_action"])
        self.assertEqual("service_health_check", open_question["selected_action"])
        self.assertEqual(["openclaw_log_check"], open_question["failed_actions"])

        second_state = eve_consciousness.build_conscious_state(
            source="test",
            workspace={"summary": "The receipt remains unresolved after one failed observation."},
            self_model={"identity": "Eve is one local control system."},
            world_model=repository.payload,
            relationship_model={},
            other_minds_model={},
            homeostasis={"regulation_mode": "orient", "pressures": []},
            plan_model={"available": False},
            autonomy_agenda={},
            memory_items=[],
            previous_state=first_state,
            now="2026-07-19T06:00:01+00:00",
        )
        lesioned = eve_consciousness.build_conscious_state(
            source="test",
            workspace={"summary": "The receipt remains unresolved after one failed observation."},
            self_model={"identity": "Eve is one local control system."},
            world_model=repository.payload,
            relationship_model={},
            other_minds_model={},
            homeostasis={"regulation_mode": "orient", "pressures": []},
            plan_model={"available": False},
            autonomy_agenda={},
            memory_items=[],
            previous_state=first_state,
            lesions=["world_model"],
            now="2026-07-19T06:00:01+00:00",
        )
        self.assertEqual("service_health_check", second_state["action_model"]["selected_intention"]["id"])
        self.assertTrue(second_state["world_model"]["selected_question"]["recovery_step"])
        self.assertFalse(
            any(
                item.get("inquiry_id") == inquiry["id"]
                for item in lesioned["action_model"]["affordances"]
            )
        )

        menu = eve.autonomy_free_run_action_menu(120)
        guidance = eve.autonomy_free_run_guidance(
            menu,
            {
                "counts": {},
                "components": {},
                "openclaw": {},
                "system": {},
                "autonomy": {},
                "conscious_state": {
                    "selected_inquiry": second_state["world_model"]["selected_question"],
                    "affordances": second_state["action_model"]["affordances"],
                },
            },
            previous_actions=[],
            remaining_seconds=120,
            style="explorer",
            config={**eve.DEFAULT_CONFIG, "autonomy_curiosity_enabled": True},
        )
        action, override, policy = eve.finalize_autonomy_free_run_choice(
            "system_tasks",
            menu=menu,
            guidance=guidance,
            recommended_actions=guidance["recommended_actions"],
            selection_policy="test",
        )
        decision = eve.attach_endogenous_inquiry_to_decision(
            {
                "action": action,
                "reason": "The chooser preferred an unrelated task.",
                "selection_policy": policy,
                "override": override,
            },
            guidance,
        )

        self.assertTrue(guidance["require_inquiry_probe"])
        self.assertTrue(guidance["inquiry_recovery_step"])
        self.assertFalse(guidance["require_curiosity_probe"])
        self.assertEqual("service_health_check", action)
        self.assertEqual("forced_endogenous_inquiry_probe", policy)
        self.assertIn("unused alternative", decision["reason"])
        self.assertEqual(["openclaw_log_check"], decision["inquiry_failed_actions"])

        with patch.object(eve, "WORLD_MODEL_REPOSITORY", repository):
            recovered = eve.record_world_model_inquiry_observation(
                decision,
                {
                    "action": "service_health_check",
                    "status": "completed",
                    "ok": True,
                    "execution_verification_ok": True,
                    "summary": "The independent service observation verified the current live state.",
                },
                run_id="recovery-run",
                source_cycle_id=second_state["cycle_id"],
            )

        self.assertTrue(recovered["answered"])
        self.assertEqual([], repository.payload["open_questions"])
        answered = repository.payload["answered_questions"][0]
        self.assertEqual(2, answered["attempt_count"])
        self.assertEqual(
            ["openclaw_log_check", "service_health_check"],
            answered["attempted_actions"],
        )

    def test_openclaw_attention_ignores_recovered_failure_history(self):
        self.assertFalse(
            eve.openclaw_attention_needs_action(
                {
                    "summary": "OpenClaw reachable. Latest sync recovered cleanly.",
                    "sync_health_summary": "3 recent OpenClaw sync failure(s), but the latest run recovered.",
                }
            )
        )

    def test_openclaw_attention_keeps_current_gateway_failures_actionable(self):
        self.assertTrue(
            eve.openclaw_attention_needs_action(
                {
                    "summary": "OpenClaw sidecar is installed, but the local gateway is not reachable.",
                    "sync_health_summary": "latest sync failed",
                }
            )
        )

    def test_openclaw_attention_ignores_auth_unavailable_memory_capability(self):
        self.assertFalse(
            eve.openclaw_attention_needs_action(
                {
                    "memory_status_ok": True,
                    "memory_status_severity": "unavailable",
                    "memory_capability_available": False,
                    "memory_status_summary": "Memory embeddings unavailable via bedrock: AWS credentials are not configured",
                }
            )
        )

    def test_developmental_selector_does_not_loop_on_recovered_openclaw_summary(self):
        state = {
            "openclaw_summary": "OpenClaw reachable. Latest sync recovered cleanly.",
            "openclaw_sync_health_summary": "3 recent OpenClaw sync failure(s), but the latest run recovered.",
        }
        with patch.object(eve, "developmental_openclaw_ready", return_value=True):
            action = eve.select_developmental_cycle_action(
                dict(eve.DEFAULT_CONFIG),
                state,
                workspace={"summary": "Older OpenClaw sync failure context is still in view."},
                homeostasis={"dominant_pressures": ["coherence 100"]},
                component_state={"components": []},
                recent_actions=[],
                recent_cycles=[
                    {"capability_attempted": "service_health_check", "timestamp": "2026-04-24T20:00:00+00:00"},
                    {"capability_attempted": "cleanup_candidate_check", "timestamp": "2026-04-24T19:50:00+00:00"},
                    {"capability_attempted": "openclaw_log_check", "timestamp": "2026-04-24T19:40:00+00:00"},
                    {"capability_attempted": "openclaw_sync_check", "timestamp": "2026-04-24T19:30:00+00:00"},
                ],
            )

        self.assertNotIn(action["action"], {"openclaw_log_check", "openclaw_sync_check"})

    def test_fresh_recurrent_intention_with_action_access_controls_developmental_action(self):
        selection = eve.select_developmental_cycle_action(
            dict(eve.DEFAULT_CONFIG),
            {},
            workspace={"summary": "Workspace is stable."},
            homeostasis={"dominant_pressures": []},
            component_state={"components": []},
            recent_actions=[],
            recent_cycles=[],
            conscious_state=self.conscious_action_state("updates_status"),
        )

        self.assertEqual("updates_status", selection["action"])
        self.assertEqual("recurrent_conscious_state", selection["selection_source"])
        self.assertEqual("cycle-conscious-action-test", selection["conscious_cycle_id"])
        self.assertTrue(selection["conscious_action_access"])

    def test_recurrent_intention_without_action_access_cannot_control_body(self):
        selection = eve.select_developmental_cycle_action(
            dict(eve.DEFAULT_CONFIG),
            {},
            workspace={"summary": "Workspace is stable."},
            homeostasis={"dominant_pressures": []},
            component_state={"components": []},
            recent_actions=[],
            recent_cycles=[],
            conscious_state=self.conscious_action_state("updates_status", action_access=False),
        )

        self.assertEqual("service_health_check", selection["action"])
        self.assertNotEqual("recurrent_conscious_state", selection.get("selection_source"))

    def test_lesioned_recurrent_intention_cannot_control_body(self):
        selection = eve.select_developmental_cycle_action(
            dict(eve.DEFAULT_CONFIG),
            {},
            workspace={"summary": "Workspace is stable."},
            homeostasis={"dominant_pressures": []},
            component_state={"components": []},
            recent_actions=[],
            recent_cycles=[],
            conscious_state=self.conscious_action_state("updates_status", lesions=["action_model"]),
        )

        self.assertEqual("service_health_check", selection["action"])

    def test_stale_or_unsupported_recurrent_intention_cannot_control_body(self):
        stale = self.conscious_action_state("updates_status")
        stale["updated_at"] = "2026-01-01T00:00:00+00:00"
        unsupported = self.conscious_action_state("delete_everything")

        self.assertEqual(
            {},
            eve.recurrent_developmental_action_selection(dict(eve.DEFAULT_CONFIG), stale),
        )
        self.assertEqual(
            {},
            eve.recurrent_developmental_action_selection(dict(eve.DEFAULT_CONFIG), unsupported),
        )

    def test_system_tasks_is_an_admitted_recurrent_body_action(self):
        selection = eve.recurrent_developmental_action_selection(
            dict(eve.DEFAULT_CONFIG),
            self.conscious_action_state("system_tasks"),
        )

        self.assertEqual("system_tasks", selection["action"])
        self.assertEqual("developmental_cycle.system_tasks", selection["capability"])

    def test_free_run_recovery_suppresses_stale_openclaw_agenda(self):
        snapshot = {
            "openclaw": {
                "summary": "OpenClaw reachable. Latest sync recovered cleanly.",
                "sync_health_summary": "3 recent OpenClaw sync failure(s), but the latest run recovered.",
            },
            "autonomy": {
                "last_supervisor_score": 44,
                "next_experiments": [
                    {
                        "title": "Repair OpenClaw sync loop",
                        "preferred_action": "openclaw_log_check",
                    }
                ],
            },
            "counts": {},
            "components": {},
            "active_mind": {"current_focus": "Recover from the last weak autonomy run."},
        }

        objective = eve.autonomy_free_run_objective(snapshot, [], 300, style="explorer")

        self.assertIn("stale_agenda_note", objective)
        self.assertNotIn("openclaw_log_check", objective["preferred_actions"])
        self.assertIn("openclaw_log_check", objective["avoid_actions"])
        self.assertIn("capability_tryout", objective["preferred_actions"])

    def test_free_run_cools_down_openclaw_sync_write_path_failures(self):
        menu = eve.autonomy_free_run_action_menu(remaining_seconds=120)
        snapshot = {
            "openclaw": {
                "summary": "OpenClaw gateway reachable.",
                "sync_health_summary": "Latest sync failed: context artifacts could not be updated.",
            },
            "recent_actions": [
                {
                    "action": "openclaw_sync_check",
                    "status": "completed",
                    "tree_status": "FAILURE",
                    "verification_ok": False,
                    "summary": "OpenClaw sync completed, but context artifacts could not be updated: Operation not permitted.",
                }
            ],
            "counts": {},
            "components": {},
            "system": {},
            "autonomy": {},
        }

        guidance = eve.autonomy_free_run_guidance(
            menu,
            snapshot,
            previous_actions=[
                {"action": "system_tasks", "status": "completed", "ok": True, "summary": "Created 0 task(s)."},
                {"action": "updates_status", "status": "completed", "ok": True, "summary": "0 update signal(s)."},
            ],
            remaining_seconds=120,
            style="explorer",
        )
        action, override, policy = eve.finalize_autonomy_free_run_choice(
            "openclaw_sync_check",
            menu=menu,
            guidance=guidance,
            recommended_actions=guidance["recommended_actions"],
            selection_policy="test",
        )

        self.assertIn("openclaw_sync_check", guidance["objective"]["avoid_actions"])
        self.assertNotIn("openclaw_sync_check", guidance["recommended_actions"])
        self.assertNotEqual("openclaw_sync_check", action)
        self.assertTrue(override)
        self.assertEqual("forced_objective_progress", policy)

    def test_free_run_branches_after_openclaw_log_check_on_known_write_failure(self):
        menu = eve.autonomy_free_run_action_menu(remaining_seconds=120)
        snapshot = {
            "openclaw": {
                "summary": "OpenClaw gateway reachable.",
                "sync_health_summary": "Latest sync failed: context artifacts could not be updated.",
            },
            "recent_actions": [
                {
                    "action": "openclaw_sync_check",
                    "status": "completed",
                    "tree_status": "FAILURE",
                    "verification_ok": False,
                    "summary": "OpenClaw sync completed, but context artifacts could not be updated: Operation not permitted.",
                },
                {
                    "action": "openclaw_log_check",
                    "status": "completed",
                    "ok": True,
                    "summary": "The recent OpenClaw gateway logs look stable.",
                },
            ],
            "counts": {},
            "components": {},
            "system": {},
            "autonomy": {},
        }

        guidance = eve.autonomy_free_run_guidance(
            menu,
            snapshot,
            previous_actions=[
                {"action": "system_tasks", "status": "completed", "ok": True, "summary": "Created 0 task(s)."},
            ],
            remaining_seconds=120,
            style="explorer",
        )
        action, override, policy = eve.finalize_autonomy_free_run_choice(
            "openclaw_log_check",
            menu=menu,
            guidance=guidance,
            recommended_actions=guidance["recommended_actions"],
            selection_policy="test",
        )

        self.assertIn("openclaw_sync_check", guidance["objective"]["avoid_actions"])
        self.assertIn("openclaw_log_check", guidance["objective"]["avoid_actions"])
        self.assertNotIn("openclaw_log_check", guidance["recommended_actions"])
        self.assertNotEqual("openclaw_log_check", action)
        self.assertTrue(override)
        self.assertEqual("forced_objective_progress", policy)

    def test_developmental_cycle_logs_observe_choose_act_reflect_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cycles_path = Path(temp_dir) / "developmental_cycles.jsonl"
            patches = cycle_test_patches(cycles_path)
            with patch.object(
                eve,
                "run_operational_action_tree",
                return_value={
                    "executed": True,
                    "ok": True,
                    "summary": "Service health is stable.",
                    "execution_id": "action-1",
                    "execution_backend": "deterministic",
                    "execution_tree_status": "BYPASSED",
                    "execution_verification_ok": True,
                    "execution_summary": "Service health is stable.",
                },
            ) as action_tree:
                with ExitStack() as stack:
                    for item in patches:
                        stack.enter_context(item)
                    state = {}
                    config = dict(eve.DEFAULT_CONFIG)
                    config["openclaw_enabled"] = False

                    cycle = eve.run_developmental_cycle(config, state, source="test")

            action_tree.assert_called_once()
            self.assertEqual("service_health_check", action_tree.call_args.args[0])
            records = eve_store.read_jsonl_records(cycles_path)
            self.assertEqual(1, len(records))
            self.assertEqual(cycle["id"], records[0]["id"])
            self.assertIn("Workspace is stable", records[0]["what_eve_observed"])
            self.assertIn("organ:", records[0]["what_eve_observed"])
            self.assertEqual(1, records[0]["organ_assimilation"]["organ_count"])
            self.assertEqual("five_model_lanes", records[0]["organ_signals"][0]["id"])
            self.assertEqual("service_health_check", records[0]["capability_attempted"])
            self.assertEqual("", records[0]["failure_mode_if_any"])
            self.assertIn("next", records[0]["next_thing_to_test"].lower())
            self.assertEqual("verified", state["last_developmental_cycle_result"])

    def test_developmental_cycle_binds_exact_recurrent_system_task_intention_to_outcome(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cycles_path = Path(temp_dir) / "developmental_cycles.jsonl"
            patches = cycle_test_patches(cycles_path)
            opened = self.conscious_action_state("system_tasks")
            next_state = self.conscious_action_state("updates_status")
            next_state["cycle_id"] = "cycle-after-system-tasks"
            completion = {
                **opened,
                "status": "completed",
                "cycle_outcome": {
                    "overall_prediction_error": 0,
                    "outcome_observed": True,
                    "actual_action_id": "system_tasks",
                },
            }
            bounded_result = {
                "action": "system_tasks",
                "status": "completed",
                "executed": True,
                "ok": True,
                "execution_backend": "bounded_system_task_executor",
                "execution_id": "system-task-execution-1",
                "execution_tree_status": "SUCCESS",
                "execution_verification_ok": True,
                "summary": "Created 1 task, completed 1 CPU task, processed 0 maintenance tasks.",
                "created_count": 1,
                "completed_count": 1,
                "maintenance_count": 0,
            }

            with ExitStack() as stack:
                for item in patches:
                    stack.enter_context(item)
                build_state = stack.enter_context(
                    patch.object(eve, "build_recurrent_conscious_state", side_effect=[opened, next_state])
                )
                complete_state = stack.enter_context(
                    patch.object(eve, "complete_recurrent_conscious_cycle", return_value=completion)
                )
                bounded_step = stack.enter_context(
                    patch.object(eve, "run_bounded_system_tasks_step", return_value=bounded_result)
                )
                action_tree = stack.enter_context(patch.object(eve, "run_operational_action_tree"))
                state = {}
                cycle = eve.run_developmental_cycle(dict(eve.DEFAULT_CONFIG), state, source="test")

            bounded_step.assert_called_once()
            action_tree.assert_not_called()
            self.assertEqual(2, build_state.call_count)
            complete_state.assert_called_once()
            self.assertIs(opened, complete_state.call_args.kwargs["opened_state"])
            binding = cycle["conscious_action_binding"]
            self.assertEqual("recurrent_conscious_state", cycle["selection_source"])
            self.assertEqual("cycle-conscious-action-test", binding["source_cycle_id"])
            self.assertEqual("system_tasks", binding["selected_action"])
            self.assertEqual("system_tasks", binding["actual_action"])
            self.assertTrue(binding["matched_actual"])
            self.assertTrue(binding["outcome_observed"])
            self.assertTrue(binding["outcome_ok"])
            self.assertEqual("cycle-after-system-tasks", binding["next_cycle_id"])
            self.assertEqual(1, cycle["action_result"]["completed_count"])
            self.assertEqual("", cycle["failure_mode_if_any"])

    def test_developmental_cycle_creates_repair_task_on_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cycles_path = Path(temp_dir) / "developmental_cycles.jsonl"
            patches = cycle_test_patches(cycles_path)
            created_tasks = []

            def create_task(payload):
                created_tasks.append(payload)
                return {"id": "repair-task-1", **payload}

            with patch.object(
                eve,
                "run_operational_action_tree",
                return_value={
                    "executed": False,
                    "ok": False,
                    "summary": "Service health check could not read the snapshot.",
                    "execution_verification_ok": False,
                },
            ), patch.object(eve, "create_system_task", create_task):
                with ExitStack() as stack:
                    for item in patches:
                        stack.enter_context(item)
                    state = {}
                    config = dict(eve.DEFAULT_CONFIG)
                    config["openclaw_enabled"] = False

                    cycle = eve.run_developmental_cycle(config, state, source="test")

            self.assertEqual(1, len(created_tasks))
            self.assertEqual("developmental_repair", created_tasks[0]["kind"])
            self.assertIn("did not execute", cycle["failure_mode_if_any"])
            self.assertEqual("repair-task-1", cycle["repair_task_id"])
            self.assertEqual("needs_repair", state["last_developmental_cycle_result"])

    def test_explicit_failed_verification_overrides_optimistic_ok_and_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cycles_path = Path(temp_dir) / "developmental_cycles.jsonl"
            patches = cycle_test_patches(cycles_path)
            with patch.object(
                eve,
                "run_operational_action_tree",
                return_value={
                    "executed": True,
                    "ok": True,
                    "summary": "completed successfully",
                    "execution_id": "action-contradiction",
                    "execution_tree_status": "SUCCESS",
                    "execution_verification_ok": False,
                    "execution_summary": "verification_ok=false despite optimistic result text",
                },
            ), patch.object(
                eve,
                "create_system_task",
                return_value={"id": "repair-verification-contradiction"},
            ):
                with ExitStack() as stack:
                    for item in patches:
                        stack.enter_context(item)
                    state = {}
                    config = dict(eve.DEFAULT_CONFIG)
                    config["openclaw_enabled"] = False
                    cycle = eve.run_developmental_cycle(config, state, source="test")

        self.assertFalse(eve.action_result_explicit_verification(cycle["action_result"]))
        self.assertFalse(cycle["action_result"]["execution_verification_ok"])
        self.assertIn("did not verify cleanly", cycle["failure_mode_if_any"])
        self.assertEqual("repair-verification-contradiction", cycle["repair_task_id"])
        self.assertEqual("needs_repair", state["last_developmental_cycle_result"])

    def test_raw_failed_verification_cannot_become_success_through_result_ok_or_string_truthiness(self):
        contradictory_action = {
            "id": "action-raw-contradiction",
            "action": "service_health_check",
            "tree_status": "SUCCESS",
            "verification_ok": "false",
            "result_ok": True,
            "ok": True,
            "summary": "completed successfully",
        }

        self.assertFalse(eve.action_execution_verified(contradictory_action))
        self.assertFalse(eve.presence_cycle_is_episode_worthy({
            **contradictory_action,
            "status": "verified",
            "action_matched_contract": True,
            "action_contract_before": {},
            "capability_attempted": "service_health_check",
        }))
        self.assertIn(
            "did not verify cleanly",
            eve.infer_developmental_failure_mode("service_health_check", contradictory_action),
        )
        with patch.object(eve, "read_action_executions", return_value=[contradictory_action]), patch.object(
            eve,
            "read_failure_clusters",
            return_value=[],
        ), patch.object(eve, "daemon_health_diagnostics", return_value={"degraded": False}), patch.object(
            eve,
            "running_from_runtime_bundle",
            return_value=False,
        ):
            modes = eve.build_developmental_failure_modes({}, {})

        self.assertIn("unverified action: service_health_check", modes)

    def test_autonomy_prediction_uses_explicit_verification_not_optimistic_ok(self):
        decision = {
            "expected_signal": "The action should produce a verified consequence.",
            "confidence": "high",
        }
        action_result = {
            "action": "service_health_check",
            "status": "completed",
            "ok": True,
            "execution_verification_ok": False,
            "summary": "completed successfully",
        }

        with patch.object(eve, "append_prediction_check_record", return_value=True):
            check = eve.record_autonomy_prediction_check(decision, action_result, "run-1")

        self.assertTrue(check["consequence_observed"])
        self.assertFalse(check["outcome_ok"])
        self.assertFalse(check["fulfilled"])
        self.assertEqual("explicit_verification", check["evidence_kind"])
        self.assertEqual(80, check["error_magnitude"])

    def test_developmental_cycle_reader_uses_timestamp_not_file_tail(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cycles_path = Path(temp_dir) / "developmental_cycles.jsonl"
            eve_store.append_jsonl_record(
                cycles_path,
                {
                    "id": "newer",
                    "timestamp": "2026-04-24T12:02:53+00:00",
                    "capability_attempted": "openclaw_sync_check",
                },
            )
            eve_store.append_jsonl_record(
                cycles_path,
                {
                    "id": "older-appended-later",
                    "timestamp": "2026-04-21T02:00:00+00:00",
                    "capability_attempted": "openclaw_log_check",
                },
            )

            with patch.object(eve, "DEVELOPMENTAL_CYCLES_PATH", cycles_path), patch.object(
                eve, "ensure_store", lambda: None
            ):
                records = eve.read_developmental_cycles(limit=1)

            self.assertEqual("newer", records[0]["id"])

    def test_developmental_cycle_state_syncs_from_newer_log_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cycles_path = Path(temp_dir) / "developmental_cycles.jsonl"
            eve_store.append_jsonl_record(
                cycles_path,
                {
                    "id": "latest-cycle",
                    "timestamp": "2026-04-24T14:17:08+00:00",
                    "capability_attempted": "openclaw_log_check",
                    "result": "The recent OpenClaw gateway logs look stable.",
                    "failure_mode_if_any": "",
                    "action_result": {"execution_verification_ok": True, "ok": True},
                },
            )
            state = {"last_developmental_cycle_at": "2026-04-24T13:10:48+00:00"}

            with patch.object(eve, "DEVELOPMENTAL_CYCLES_PATH", cycles_path), patch.object(
                eve, "ensure_store", lambda: None
            ):
                changed = eve.sync_developmental_cycle_state_from_log(state)

            self.assertTrue(changed)
            self.assertEqual("2026-04-24T14:17:08+00:00", state["last_developmental_cycle_at"])
            self.assertEqual("latest-cycle", state["last_developmental_cycle_id"])
            self.assertEqual("openclaw_log_check", state["last_developmental_cycle_action"])
            self.assertEqual("verified", state["last_developmental_cycle_result"])

    def test_daemon_developmental_cycle_persists_scheduler_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cycles_path = Path(temp_dir) / "developmental_cycles.jsonl"
            patches = cycle_test_patches(cycles_path)
            saved_states = []

            with patch.object(
                eve,
                "run_operational_action_tree",
                return_value={
                    "executed": True,
                    "ok": True,
                    "summary": "Service health is stable.",
                    "execution_id": "action-daemon-1",
                    "execution_tree_status": "SUCCESS",
                    "execution_verification_ok": True,
                },
            ), patch.object(eve, "save_state", lambda state: saved_states.append(dict(state))):
                with ExitStack() as stack:
                    for item in patches:
                        stack.enter_context(item)
                    state = {}
                    config = dict(eve.DEFAULT_CONFIG)
                    config["openclaw_enabled"] = False

                    cycle = eve.run_developmental_cycle(config, state, source="daemon")

            self.assertEqual(1, len(saved_states))
            self.assertEqual(cycle["id"], saved_states[0]["last_developmental_cycle_id"])
            self.assertEqual("verified", saved_states[0]["last_developmental_cycle_result"])


if __name__ == "__main__":
    unittest.main()
