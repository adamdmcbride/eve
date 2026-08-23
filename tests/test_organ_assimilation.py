import contextlib
import io
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import eve
import eve_consciousness
import eve_store


def five_lane_records():
    return [
        {"lane": lane, "model": f"eve-{lane}", "loaded": True, "probe_ok": True}
        for lane in eve.MODEL_LANE_ORDER
    ]


class OrganAssimilationTests(unittest.TestCase):
    def test_organ_registry_preserves_five_lane_boundary(self):
        self.assertIn("five_model_lanes", eve.ORGAN_ASSIMILATION_REGISTRY)
        self.assertIn("OpenClaw", eve.ORGAN_ASSIMILATION_REGISTRY["openclaw_body_action_nervous_system"]["label"])
        self.assertIn("Proposal-only", eve.ORGAN_ASSIMILATION_REGISTRY["hermes_learning_organ"]["authority_boundary"])
        self.assertIn("Never a sixth resident mind", eve.ORGAN_ASSIMILATION_REGISTRY["model_inference_acceleration_lab"]["authority_boundary"])

    def test_build_report_uses_substrates_models_and_watchers(self):
        specialist_report = {
            "substrates": [
                {
                    "id": "openclaw_body_action_nervous_system",
                    "label": "OpenClaw body/action nervous system",
                    "status": "partial",
                    "purpose": "Body bus",
                    "evidence": ["gateway_reachable=yes"],
                    "next_maturation": "Keep testing body contracts.",
                },
                {
                    "id": "hermes_learning_organ",
                    "label": "Hermes learning organ",
                    "status": "partial",
                    "purpose": "Learning proposals",
                    "evidence": ["direct_state_write_allowed=no"],
                },
            ]
        }
        with (
            patch.object(eve, "build_specialist_substrate_report", return_value=specialist_report),
            patch.object(eve, "load_model_watchdog_status", return_value={"updated_at": eve.utc_now()}),
            patch.object(eve, "model_lane_records", return_value=five_lane_records()),
            patch.object(
                eve,
                "governance_watcher_report",
                return_value={"generated_at": "2026-05-06T00:00:00+00:00", "status": "clean", "total_warnings": 0, "blocking_warnings": 0},
            ),
        ):
            report = eve.build_organ_assimilation_report(dict(eve.DEFAULT_CONFIG), prefer_runtime=False)

        by_id = {item["id"]: item for item in report["organs"]}
        self.assertEqual("healthy", by_id["five_model_lanes"]["status"])
        self.assertEqual("partial", by_id["openclaw_body_action_nervous_system"]["status"])
        self.assertEqual("working", by_id["openclaw_body_action_nervous_system"]["operational_status"])
        self.assertEqual("partial", by_id["hermes_learning_organ"]["status"])
        self.assertEqual("healthy", by_id["watchers_immune_layer"]["status"])
        self.assertTrue(report["readiness"]["working_now"])
        self.assertEqual(0, report["resident_chat_lane_delta"])

    def test_organ_pulse_writes_pulse_and_event_ledgers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pulses_path = Path(temp_dir) / "organ_pulses.jsonl"
            event_path = Path(temp_dir) / "event_ledger.jsonl"
            record = {
                "schema_id": "eve_organ_assimilation_report.v1",
                "generated_at": eve.utc_now(),
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
            }
            with (
                patch.object(eve, "ORGAN_PULSES_PATH", pulses_path),
                patch.object(eve, "EVENT_LEDGER_PATH", event_path),
                patch.object(eve, "ensure_store", lambda: None),
                patch.object(eve, "mirror_store_file_to_runtime", lambda path: None),
            ):
                saved = eve.append_organ_pulse_record(record, event_ledger_enabled=True)

            pulses = eve_store.read_jsonl_records(pulses_path)
            events = eve_store.read_jsonl_records(event_path)

        self.assertEqual(saved["generated_at"], pulses[0]["generated_at"])
        self.assertEqual("OrganPulseEvent", events[0]["type"])
        self.assertEqual("organs", events[0]["stream"])
        self.assertEqual(["five_model_lanes"], events[0]["payload"]["organ_ids"])

    def test_stale_organ_pulse_does_not_create_fresh_event_envelope(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pulses_path = Path(temp_dir) / "organ_pulses.jsonl"
            event_path = Path(temp_dir) / "event_ledger.jsonl"
            record = {
                "schema_id": "eve_organ_assimilation_report.v1",
                "generated_at": "2026-04-21T03:05:00+00:00",
                "resident_chat_lane_delta": 0,
                "organs": [],
            }
            with (
                patch.object(eve, "ORGAN_PULSES_PATH", pulses_path),
                patch.object(eve, "EVENT_LEDGER_PATH", event_path),
                patch.object(eve, "ensure_store", lambda: None),
                patch.object(eve, "mirror_store_file_to_runtime", lambda path: None),
                patch.object(eve, "append_entry", lambda *args, **kwargs: None),
            ):
                saved = eve.append_organ_pulse_record(record, event_ledger_enabled=True)

            pulses = eve_store.read_jsonl_records(pulses_path)
            events = eve_store.read_jsonl_records(event_path)

        self.assertEqual(saved["generated_at"], pulses[0]["generated_at"])
        self.assertEqual([], events)

    def test_active_mind_carries_organ_signals(self):
        mind = eve.normalize_active_mind(
            {
                **eve.default_active_mind(),
                "organ_signals": [
                    {
                        "id": "hermes_learning_organ",
                        "label": "Hermes learning organ",
                        "status": "partial",
                        "summary": "Hermes can propose learning but cannot write memory directly.",
                        "pressure": 58,
                    }
                ],
            }
        )
        message = eve.build_active_mind_message(mind, compact=True)

        self.assertEqual("hermes_learning_organ", mind["organ_signals"][0]["id"])
        self.assertIn("Organ signals", message)
        self.assertIn("Hermes learning organ", message)

    def test_presence_report_combines_consciousness_and_organs(self):
        organ_report = {
            "organs": [
                {
                    "id": "five_model_lanes",
                    "status": "healthy",
                    "operational_status": "ready",
                    "summary": "lanes ready",
                },
                {
                    "id": "openclaw_body_action_nervous_system",
                    "status": "healthy",
                    "operational_status": "ready",
                    "summary": "body ready",
                },
                {
                    "id": "memory_retrieval_service",
                    "status": "healthy",
                    "operational_status": "ready",
                    "summary": "memory ready",
                },
                {
                    "id": "hermes_learning_organ",
                    "status": "healthy",
                    "operational_status": "ready",
                    "summary": "learning ready",
                },
                {
                    "id": "watchers_immune_layer",
                    "status": "healthy",
                    "operational_status": "ready",
                    "summary": "watchers ready",
                },
            ],
            "readiness": {"working_now": True, "blocking_organs": [], "counts": {"ready": 5}},
        }
        consciousness = {
            "passed": True,
            "verdict": "strong_candidate_evidence",
            "tested_at": "2026-05-06T00:00:00+00:00",
            "rank": {"average_score": 5.0, "minimum_score": 5},
            "scorecard": {
                "fallback_independence": 5,
                "integrated_present": 5,
                "temporal_continuity": 5,
                "attention_control": 5,
            },
        }
        with (
            patch.object(eve, "build_organ_assimilation_report", return_value=organ_report),
            patch.object(eve, "latest_consciousness_test_record", return_value=(consciousness, "/tmp/latest.json")),
            patch.object(eve, "load_global_workspace", return_value={"summary": "Eve is integrating the current request."}),
            patch.object(eve, "load_homeostasis", return_value={"dominant_pressures": ["continuity drift 20"]}),
            patch.object(eve, "load_active_mind", return_value={"current_focus": "Help the user make Eve more present."}),
            patch.object(eve, "load_conscious_state", return_value=eve_consciousness.default_state()),
            patch.object(eve, "load_state", return_value={}),
            patch.object(eve, "load_component_update_state", return_value={"components": []}),
            patch.object(eve, "read_action_executions", return_value=[]),
            patch.object(eve, "read_developmental_cycles", return_value=[]),
            patch.object(
                eve,
                "presence_runtime_liveness",
                return_value={
                    "status": "live",
                    "live": True,
                    "daemon_running": True,
                    "last_loop_at": "2026-05-06T00:00:00+00:00",
                    "last_loop_age_minutes": 0.1,
                    "max_loop_age_seconds": 180,
                    "reason": "fresh",
                },
            ),
            patch.object(eve, "daemon_runtime_running", return_value=True),
        ):
            report = eve.build_presence_report(dict(eve.DEFAULT_CONFIG), prefer_runtime=False)

        self.assertEqual("present", report["status"])
        self.assertEqual(5, report["organ_embodiment_score"])
        self.assertEqual("source", report["state_authority"]["side"])
        self.assertIn("not proof", report["not_claiming"])
        self.assertEqual("service_health_check", report["bounded_action_contract"]["bounded_action"])
        self.assertEqual("source", report["bounded_action_contract"]["state_authority_side"])
        self.assertEqual("Help the user make Eve more present.", report["bounded_action_contract"]["focus"])
        self.assertEqual("watchers_immune_layer", report["bounded_action_contract"]["organ_id"])
        self.assertIn("service-health", report["bounded_action_contract"]["expected_verification_signal"])
        formatted = eve.format_presence_report(report, full=True)
        self.assertIn("bounded_action: service_health_check via watchers_immune_layer", formatted)
        self.assertIn("state_authority: source", formatted)
        self.assertIn("verification_signal:", formatted)

    def test_presence_report_is_dormant_when_daemon_is_not_running(self):
        organ_report = {
            "organs": [],
            "readiness": {"working_now": True, "blocking_organs": [], "counts": {"ready": 8}},
        }
        consciousness = {
            "passed": True,
            "verdict": "strong_candidate_evidence",
            "rank": {"average_score": 5.0},
            "scorecard": {
                "fallback_independence": 5,
                "integrated_present": 5,
                "temporal_continuity": 5,
                "attention_control": 5,
            },
        }
        with (
            patch.object(eve, "build_organ_assimilation_report", return_value=organ_report),
            patch.object(eve, "latest_consciousness_test_record", return_value=(consciousness, "/tmp/latest.json")),
            patch.object(eve, "load_global_workspace", return_value={"summary": "stale focus"}),
            patch.object(eve, "load_homeostasis", return_value={}),
            patch.object(eve, "load_active_mind", return_value={"current_focus": "stale focus"}),
            patch.object(eve, "load_conscious_state", return_value=eve_consciousness.default_state()),
            patch.object(eve, "load_state", return_value={"last_loop_at": "2026-05-06T00:00:00+00:00"}),
            patch.object(eve, "load_component_update_state", return_value={"components": []}),
            patch.object(eve, "read_action_executions", return_value=[]),
            patch.object(eve, "read_developmental_cycles", return_value=[]),
            patch.object(eve, "daemon_runtime_running", return_value=False),
        ):
            report = eve.build_presence_report(dict(eve.DEFAULT_CONFIG), prefer_runtime=True)

        self.assertEqual("dormant", report["status"])
        self.assertFalse(report["runtime_liveness"]["live"])
        self.assertIn("continuity_runtime", report["organ_readiness"]["blocking_organs"])
        self.assertFalse(report["organ_readiness"]["working_now"])
        self.assertLessEqual(report["organ_embodiment_score"], 2)
        self.assertIn("not running", " ".join(report["problems"]).lower())

    def test_presence_liveness_accepts_fresh_bounded_active_cycle(self):
        now = eve.utc_now()
        activity = {
            "status": "active",
            "cycle_id": "cycle-live",
            "pid": 123,
            "cycle_started_at": now,
            "last_heartbeat_at": now,
            "heartbeat_interval_seconds": 15,
            "max_active_cycle_seconds": 900,
            "heartbeat_count": 3,
        }
        config = dict(eve.DEFAULT_CONFIG)
        with patch.object(eve, "load_daemon_activity", return_value=activity):
            result = eve.presence_runtime_liveness(
                config,
                {
                    "daemon_process_id": 123,
                    "last_loop_at": "2026-01-01T00:00:00+00:00",
                },
                daemon_running=True,
                prefer_runtime=True,
            )

        self.assertTrue(result["live"])
        self.assertTrue(result["active"])
        self.assertEqual("active", result["status"])
        self.assertEqual("cycle-live", result["activity"]["cycle_id"])

    def test_presence_liveness_rejects_active_cycle_past_its_bound(self):
        activity = {
            "status": "active",
            "cycle_id": "cycle-stuck",
            "pid": 123,
            "cycle_started_at": "2026-01-01T00:00:00+00:00",
            "last_heartbeat_at": eve.utc_now(),
            "heartbeat_interval_seconds": 15,
            "max_active_cycle_seconds": 900,
        }
        with patch.object(eve, "load_daemon_activity", return_value=activity):
            result = eve.presence_runtime_liveness(
                dict(eve.DEFAULT_CONFIG),
                {
                    "daemon_process_id": 123,
                    "last_loop_at": "2026-01-01T00:00:00+00:00",
                },
                daemon_running=True,
                prefer_runtime=True,
            )

        self.assertFalse(result["live"])
        self.assertFalse(result["active"])
        self.assertEqual("stale", result["status"])

    def test_model_lane_organ_signal_rejects_stale_cached_health(self):
        stale_watchdog = {
            "updated_at": "2026-01-01T00:00:00+00:00",
            "loaded_models": [{"name": f"eve-{lane}"} for lane in eve.MODEL_LANE_ORDER],
            "probes": {f"eve-{lane}": {"ok": True} for lane in eve.MODEL_LANE_ORDER},
        }
        lane_records = [
            {"lane": lane, "model": f"eve-{lane}", "loaded": True, "probe_ok": True}
            for lane in eve.MODEL_LANE_ORDER
        ]
        with patch.object(eve, "load_model_watchdog_status", return_value=stale_watchdog), patch.object(
            eve, "model_lane_records", return_value=lane_records
        ):
            signal = eve.model_lane_organ_signal(dict(eve.DEFAULT_CONFIG), prefer_runtime=True)

        self.assertEqual("degraded", signal["status"])
        self.assertEqual("degraded", signal["operational_status"])
        self.assertIn("stale", signal["summary"].lower())
        self.assertIn("watchdog_fresh=no", signal["evidence"])

    def test_organs_status_defaults_to_runtime_when_daemon_is_live(self):
        report = {
            "schema_id": "eve_organ_assimilation_report.v1",
            "generated_at": "2026-07-20T16:37:00+00:00",
            "resident_chat_lane_delta": 0,
            "organs": [],
            "readiness": {"working_now": True, "counts": {"ready": 1}},
        }
        args = Namespace(runtime=False, json=True, full=False)
        with (
            patch.object(eve, "load_config", return_value=dict(eve.DEFAULT_CONFIG)),
            patch.object(eve, "daemon_runtime_running", return_value=True),
            patch.object(eve, "running_from_runtime_bundle", return_value=False),
            patch.object(eve, "build_organ_assimilation_report", return_value=report) as build_report,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = eve.cmd_organs_status(args)

        self.assertEqual(0, result)
        self.assertTrue(build_report.call_args.kwargs["prefer_runtime"])

    def test_presence_status_defaults_to_runtime_when_daemon_is_live(self):
        report = {
            "schema_id": "eve_presence_report.v1",
            "generated_at": "2026-06-13T21:40:00+00:00",
            "status": "present",
            "current_focus": "runtime focus",
            "organ_embodiment_score": 5,
            "consciousness": {"passed": True, "verdict": "strong", "rank": {"average_score": 5}},
            "not_claiming": "integration evidence",
            "dominant_pressures": [],
            "bounded_action_contract": {"bounded_action": "service_health_check", "organ_id": "watchers_immune_layer"},
            "problems": [],
            "next_step": "verify",
            "state_authority": {"side": "runtime", "prefer_runtime": True, "daemon_runtime_running": True},
        }
        with (
            patch.object(eve, "load_config", return_value=dict(eve.DEFAULT_CONFIG)),
            patch.object(eve, "daemon_runtime_running", return_value=True),
            patch.object(eve, "running_from_runtime_bundle", return_value=False),
            patch.object(eve, "build_presence_report", return_value=report) as build_report,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            code = eve.cmd_presence_status(Namespace(runtime=False, json=False, full=False))

        self.assertEqual(0, code)
        self.assertTrue(build_report.call_args.kwargs["prefer_runtime"])

    def test_presence_pulse_delegates_to_runtime_when_daemon_is_live(self):
        with (
            patch.object(eve, "load_config", return_value=dict(eve.DEFAULT_CONFIG)),
            patch.object(eve, "daemon_runtime_running", return_value=True),
            patch.object(eve, "running_from_runtime_bundle", return_value=False),
            patch.object(eve, "delegate_cli_to_runtime", return_value=0) as delegate,
            patch.object(eve, "build_presence_report") as build_report,
        ):
            code = eve.cmd_presence_pulse(Namespace(runtime=False, json=False, full=True))

        self.assertEqual(0, code)
        self.assertEqual(["presence", "pulse", "--full"], delegate.call_args.args[0])
        build_report.assert_not_called()

    def test_presence_cycle_records_lived_loop_without_status_chatter(self):
        now = eve.utc_now()
        action_contract = {
            "schema_id": "eve_presence_action_contract.v1",
            "bounded_action": "service_health_check",
            "capability": "operational_action_tree.service_health_check",
            "organ_id": "watchers_immune_layer",
            "expected_verification_signal": "typed service-health result with ok/execution_verification_ok evidence",
            "why_this_action": "Start with live service health.",
            "care": "Ground aspiration in runtime truth.",
            "next_test": "Rotate next.",
        }
        before_presence = {
            "schema_id": "eve_presence_report.v1",
            "generated_at": now,
            "status": "present",
            "current_focus": "Eve is choosing one bounded action.",
            "dominant_pressures": ["keep continuity alive"],
            "bounded_action_contract": action_contract,
            "organ_embodiment_score": 5,
            "organ_readiness": {"counts": {"ready": 9}, "blocking_organs": []},
            "consciousness": {
                "passed": True,
                "verdict": "strong_candidate_evidence",
                "rank": {"average_score": 5.0},
                "tested_at": now,
            },
            "problems": [],
        }
        after_presence = {
            **before_presence,
            "generated_at": now,
            "current_focus": "Eve verified one bounded consequence.",
        }
        developmental_cycle = {
            "id": "dev-cycle-1",
            "timestamp": "2026-05-06T00:00:30+00:00",
            "capability_attempted": "service_health_check",
            "result": "Service health check returned usable evidence.",
            "failure_mode_if_any": "",
            "next_thing_to_test": "Repeat the loop and compare consequence.",
            "action_result": {
                "execution_id": "action-1",
                "execution_verification_ok": True,
                "ok": True,
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            cycles_path = temp_path / "presence_cycles.jsonl"
            pulses_path = temp_path / "presence_pulses.jsonl"
            event_path = temp_path / "event_ledger.jsonl"
            state = {}
            with (
                patch.object(eve, "PRESENCE_CYCLES_PATH", cycles_path),
                patch.object(eve, "PRESENCE_PULSES_PATH", pulses_path),
                patch.object(eve, "EVENT_LEDGER_PATH", event_path),
                patch.object(eve, "ensure_store", lambda: None),
                patch.object(eve, "mirror_store_file_to_runtime", lambda path: None),
                patch.object(eve, "save_state", lambda updated_state: None),
                patch.object(eve, "append_entry", lambda *args, **kwargs: None),
                patch.object(eve, "build_presence_report", side_effect=[before_presence, after_presence]),
                patch.object(
                    eve,
                    "run_mind_tick",
                    return_value={
                        "model": "fast",
                        "used_fallback": False,
                        "mind": {"current_focus": "Eve is choosing one bounded action."},
                    },
                ),
                patch.object(
                    eve,
                    "refresh_global_workspace",
                    return_value={"workspace": {"updated_at": "2026-05-06T00:00:20+00:00"}},
                ),
                patch.object(eve, "run_developmental_cycle", return_value=developmental_cycle),
                patch.object(
                    eve,
                    "record_experience_event",
                    return_value={"id": "experience-1", "event_type": "presence_cycle"},
                ) as record_experience,
            ):
                record = eve.run_presence_cycle(dict(eve.DEFAULT_CONFIG), state, source="test", force=True)

            cycles = eve_store.read_jsonl_records(cycles_path)
            pulses = eve_store.read_jsonl_records(pulses_path)
            events = eve_store.read_jsonl_records(event_path)

        self.assertEqual("eve_presence_cycle.v1", record["schema_id"])
        self.assertEqual("verified", record["status"])
        self.assertEqual("service_health_check", record["capability_attempted"])
        self.assertTrue(record["verification_ok"])
        self.assertEqual(action_contract, record["action_contract_before"])
        self.assertEqual("service_health_check", record["presence_before"]["bounded_action_contract"]["bounded_action"])
        self.assertTrue(record["action_matched_contract"])
        self.assertTrue(any(stage.get("action_matched_contract") is True for stage in record["stages"]))
        self.assertIn("do not inject routine presence telemetry", record["conversation_boundary"])
        self.assertEqual(1, len(cycles))
        self.assertEqual(record["id"], cycles[0]["id"])
        self.assertEqual(1, len(pulses))
        self.assertEqual(["PresencePulseEvent", "PresenceCycleEvent"], [event["type"] for event in events])
        self.assertFalse(events[1]["human_visible"])
        self.assertEqual("service_health_check", events[1]["payload"]["action_contract_before"]["bounded_action"])
        self.assertTrue(events[1]["payload"]["action_matched_contract"])
        self.assertEqual(record["id"], state["last_presence_cycle_id"])
        self.assertEqual("service_health_check", state["last_presence_cycle_expected_action"])
        self.assertTrue(state["last_presence_cycle_action_matched_contract"])
        self.assertIn("action_contract: service_health_check via watchers_immune_layer | matched=yes", eve.format_presence_cycle_record(record, full=True))
        record_experience.assert_called_once()

    def test_lab_live_report_separates_live_canary_and_gated_layers(self):
        whole_system = {
            "passed": True,
            "status": "passed",
            "average_score": 4.88,
            "check_count": 21,
            "failing_check_count": 0,
        }
        organ_report = {
            "resident_chat_lane_delta": 0,
            "readiness": {"working_now": True, "counts": {"ready": 8, "lab_ready": 3}},
            "organs": [],
        }
        presence_report = {
            "status": "present",
            "organ_embodiment_score": 5,
        }
        oss_status = {
            "status": "healthy",
            "trace_status": "ready",
            "training_dataset_status": "ready",
            "trainer_recipe_status": "written",
            "dvc_manifest_status": "ready",
            "readiness": {"ready_checks": 6, "total_checks": 6},
            "service_status": {"langfuse": "server_ready"},
        }
        dvc_manifest = {
            "status": "ready",
            "file_count": 4,
            "dvc": {
                "available": True,
                "initialized": True,
                "workspace_root": "/tmp/eve",
                "tracking_sidecar_exists": True,
            },
        }
        beads_status = {
            "status": "staged_live",
            "status_ok": True,
            "ready_ok": True,
            "total_issues": 1,
            "ready_issues": 0,
        }
        mtp_report = {
            "status": "passed",
            "mode": "llama-smoke",
            "llama_status": "passed",
            "llama_flavor": "gemma4-mtp",
            "llama_trace_has_mtp": True,
            "live_routing_changed": False,
            "artifact_path": "/tmp/latest.json",
        }
        hermes_run = {
            "id": "hermes-smoke-1",
            "status": "passed_with_warnings",
            "strict_json_ok": True,
            "json_repair_used": False,
            "proposal_count": 3,
        }
        autonomy_run = {"run_id": "free-run-1", "actions": [{"status": "completed"}]}
        with (
            patch.object(eve, "read_whole_system_json_artifact", return_value=(whole_system, "/tmp/whole.json")),
            patch.object(eve, "build_organ_assimilation_report", return_value=organ_report),
            patch.object(eve, "build_presence_report", return_value=presence_report),
            patch.object(eve, "read_presence_cycles", return_value=[{"id": "presence-1", "status": "verified"}]),
            patch.object(eve, "build_oss_integration_status_report", return_value=oss_status),
            patch.object(eve, "build_oss_dvc_dataset_manifest", return_value=dvc_manifest),
            patch.object(eve, "oss_resolve_executable", return_value="/usr/local/bin/dvc"),
            patch.object(eve, "oss_run_command", return_value={"status": "ok"}),
            patch.object(eve, "detect_beads_work_graph", return_value=beads_status),
            patch.object(
                eve,
                "detect_dagster_evidence_orchestrator",
                return_value={"status": "lab_available", "installed": True, "version_detail": "Dagster version probe timed out"},
            ),
            patch.object(eve, "read_gemma4_mtp_lab_report", return_value=mtp_report),
            patch.object(eve, "latest_hermes_run", return_value=hermes_run),
            patch.object(eve.eve_openclaw, "load_openclaw_status", return_value={"gateway_reachable": True, "memory_capability_available": True}),
            patch.object(eve.eve_openclaw_body, "read_evidence_events", return_value=[{"type": "openclaw_status_snapshot"}]),
            patch.object(eve, "read_autonomy_run_summaries", return_value=[autonomy_run]),
            patch.object(eve, "autonomy_latest_explorer_whole_system_result", return_value={"status": "passed"}),
        ):
            report = eve.build_lab_live_activation_report(dict(eve.DEFAULT_CONFIG), prefer_runtime=False)

        by_id = {item["id"]: item for item in report["layers"]}
        self.assertEqual("live_with_gates", report["status"])
        self.assertTrue(by_id["presence"]["live_now"])
        self.assertEqual("live", by_id["dvc_dataset_versioning"]["status"])
        self.assertEqual("canary_passed", by_id["model_inference_acceleration_mtp"]["status"])
        self.assertEqual("lane_bakeoff_required_before_promotion", by_id["model_inference_acceleration_mtp"]["blocker"])
        self.assertEqual("blocked", by_id["dagster_evidence_orchestration"]["status"])
        self.assertEqual("staged_live", by_id["frontier_api_lab"]["status"])
        self.assertNotIn("frontier_api_lab", report["blocking"])
        formatted = eve.format_lab_live_activation_report(report, full=False)
        self.assertIn("Eve lab-live activation", formatted)
        self.assertIn("blocking:", formatted)

    def test_builtin_access_report_treats_local_canary_as_built_in_access(self):
        activation = {
            "status": "live_with_gates",
            "blocking": ["model_inference_acceleration_mtp"],
            "layers": [
                {
                    "id": "presence",
                    "status": "live",
                    "live_now": True,
                    "summary": "Presence loop is current.",
                    "evidence": {"status": "present"},
                    "blocker": "",
                    "next_action": "",
                    "authority": "evidence_only",
                },
                {
                    "id": "model_inference_acceleration_mtp",
                    "status": "canary_passed",
                    "live_now": False,
                    "summary": "MTP canary passed; live routing unchanged.",
                    "evidence": {"live_routing_changed": False, "llama_trace_has_mtp": True},
                    "blocker": "lane_bakeoff_required_before_promotion",
                    "next_action": "Run lane bakeoffs.",
                    "authority": "canary_only",
                },
                {
                    "id": "frontier_api_lab",
                    "status": "staged_live",
                    "live_now": True,
                    "summary": "Review packet surface is available.",
                    "evidence": {"provider_adapter_count": 0},
                    "blocker": "",
                    "next_action": "",
                    "authority": "lab_only",
                },
            ],
        }

        with patch.object(eve, "build_lab_live_activation_report", return_value=activation):
            report = eve.build_builtin_access_report(dict(eve.DEFAULT_CONFIG), prefer_runtime=False)

        by_id = {item["id"]: item for item in report["layers"]}
        self.assertEqual("eve_built_in_access.v1", report["schema_id"])
        self.assertEqual("full_local_access_with_canaries", report["status"])
        self.assertTrue(report["local_full_access"])
        self.assertEqual([], report["unavailable_layers"])
        self.assertEqual(["model_inference_acceleration_mtp"], report["canary_layers"])
        self.assertEqual("built_in_canary", by_id["model_inference_acceleration_mtp"]["built_in_status"])
        self.assertTrue(by_id["model_inference_acceleration_mtp"]["full_local_access"])
        self.assertIn("live resident lane routing", by_id["model_inference_acceleration_mtp"]["not_automatic"])
        self.assertEqual("built_in", by_id["frontier_api_lab"]["built_in_status"])
        self.assertIn("hosted model-provider calls", by_id["frontier_api_lab"]["not_automatic"])
        formatted = eve.format_builtin_access_report(report, full=True)
        self.assertIn("Eve built-in access", formatted)
        self.assertIn("local_access: 3/3", formatted)
        self.assertIn("non_local_stop_lines:", formatted)


if __name__ == "__main__":
    unittest.main()
