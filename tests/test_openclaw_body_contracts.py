import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json

import eve_openclaw_body


class OpenClawBodyContractTests(unittest.TestCase):
    def test_contract_registry_defines_required_body_bus_contracts(self) -> None:
        contracts = eve_openclaw_body.openclaw_body_contracts()
        ids = {item["id"] for item in contracts}

        self.assertEqual(set(eve_openclaw_body.OPENCLAW_BODY_CONTRACT_ORDER), ids)
        self.assertIn("openclaw_action_router", ids)
        for contract in contracts:
            self.assertFalse(contract["adds_chat_lane"], contract["id"])
            self.assertFalse(contract["canonical_memory_authority"], contract["id"])
            self.assertIn(contract["owning_lane"], {"fast", "observer", "planner", "deep", "relationship"})
            self.assertTrue(contract["verification_command"], contract["id"])
            self.assertTrue(contract["safety_gate"], contract["id"])
            self.assertIsInstance(contract["input_schema"], dict)
            self.assertIsInstance(contract["output_schema"], dict)

    def test_contract_report_keeps_eve_as_brain_and_openclaw_as_body_bus(self) -> None:
        report = eve_openclaw_body.build_openclaw_body_contract_report(
            {
                "gateway_reachable": True,
                "memory_status_severity": "ready",
                "last_sync_ok": True,
                "summary": "OpenClaw reachable.",
            }
        )

        self.assertEqual(0, report["resident_chat_lane_delta"])
        self.assertEqual(
            [
                "eve_brain",
                "typed_eve_action_contracts",
                "openclaw_body_bus",
                "evidence_bridge",
                "operator_safety_gates",
            ],
            report["integration_layers"],
        )
        self.assertTrue(report["status"]["gateway_ready"])
        self.assertTrue(report["status"]["memory_ready"])

    def test_action_router_infers_allowlisted_actions(self) -> None:
        repair = eve_openclaw_body.build_openclaw_action_plan(intent="diagnose the latest OpenClaw repair issue")
        activity = eve_openclaw_body.build_openclaw_action_plan(intent="ingest background tasks and hook activity")
        admission = eve_openclaw_body.build_openclaw_action_plan(intent="audit admitted skills and plugins")
        sync = eve_openclaw_body.build_openclaw_action_plan(intent="sync Eve context into OpenClaw")
        memory = eve_openclaw_body.build_openclaw_action_plan(intent="check OpenClaw memory wiki health")

        self.assertEqual("repair_diagnose", repair["action"])
        self.assertTrue(repair["requires_specific_approval"])
        self.assertEqual("activity_ingest", activity["action"])
        self.assertEqual("admission_audit", admission["action"])
        self.assertEqual("sync_context", sync["action"])
        self.assertEqual("memory_wiki_health", memory["action"])
        self.assertFalse(memory["requires_specific_approval"])
        for plan in [repair, activity, admission, sync, memory]:
            self.assertFalse(plan["adds_chat_lane"])
            self.assertFalse(plan["canonical_memory_authority"])
            self.assertIn(plan["action"], eve_openclaw_body.openclaw_router_action_ids())

    def test_action_router_event_is_not_canonical_memory(self) -> None:
        plan = eve_openclaw_body.build_openclaw_action_plan(intent="check OpenClaw status", requested_action="status_snapshot")
        event = eve_openclaw_body.build_openclaw_action_router_event(
            plan,
            {
                "ok": True,
                "executed": True,
                "summary": "OpenClaw status recorded.",
                "evidence_event_ids": ["evt-1"],
            },
        )

        self.assertEqual("openclaw_action_router_execution", event["event_type"])
        self.assertEqual("typed_eve_action_contracts", event["body_bus_layer"])
        self.assertFalse(event["canonical_memory_authority"])
        self.assertEqual("status_snapshot", event["action"])

    def test_action_router_event_does_not_double_append_when_runtime_path_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            event_path = Path(temp_dir) / "router.jsonl"
            event = {
                "event_type": "openclaw_action_router_execution",
                "action": "status_snapshot",
                "ok": True,
                "summary": "ok",
            }
            with patch.object(eve_openclaw_body, "OPENCLAW_ACTION_ROUTER_EVENTS_PATH", event_path), patch.object(
                eve_openclaw_body,
                "RUNTIME_OPENCLAW_ACTION_ROUTER_EVENTS_PATH",
                event_path,
            ):
                eve_openclaw_body.append_openclaw_action_router_event(event)

            records = eve_openclaw_body.eve_store.read_jsonl_records(event_path)

        self.assertEqual(1, len(records))

    def test_status_evidence_event_is_not_canonical_memory(self) -> None:
        event = eve_openclaw_body.build_status_evidence_event(
            {
                "gateway_reachable": True,
                "memory_status_severity": "ready",
                "memory_provider": "local",
                "memory_capability_available": True,
                "last_sync_at": "2026-04-24T23:26:31+00:00",
                "sync_health_summary": "Latest run recovered.",
                "summary": "OpenClaw reachable.",
            },
            source="unit_test",
        )

        self.assertEqual("openclaw_status_snapshot", event["event_type"])
        self.assertEqual("ready", event["status"])
        self.assertFalse(event["canonical_memory_authority"])
        self.assertEqual("local", event["payload"]["memory_provider"])

    def test_admission_record_defaults_to_not_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            with patch.object(eve_openclaw_body, "OPENCLAW_CAPABILITY_ADMISSIONS_PATH", temp_path / "admissions.jsonl"), patch.object(
                eve_openclaw_body,
                "RUNTIME_OPENCLAW_CAPABILITY_ADMISSIONS_PATH",
                temp_path / "runtime" / "admissions.jsonl",
            ):
                record = eve_openclaw_body.create_admission_record(
                    candidate_id="calendar-mcp",
                    candidate_type="mcp",
                    source="local-test",
                    capability="calendar read access",
                    permission_level="pending_review",
                    data_boundary="calendar metadata",
                    decision="pending_review",
                )

                self.assertFalse(record["enabled_for_eve"])
                self.assertFalse(record["adds_chat_lane"])
                records = eve_openclaw_body.read_admission_records()
                self.assertEqual(["calendar-mcp"], [item["candidate_id"] for item in records])

    def test_parse_mixed_json_handles_openclaw_log_prefix(self) -> None:
        payload = eve_openclaw_body.parse_mixed_json(
            '[plugins] registered route eveRepair\n{"hooks":[{"name":"command-logger"}]}'
        )

        self.assertEqual({"hooks": [{"name": "command-logger"}]}, payload)

    def test_run_openclaw_json_command_accepts_task_json_on_stderr(self) -> None:
        completed = SimpleNamespace(
            returncode=0,
            stdout="",
            stderr='{"count":0,"runtime":null,"status":null,"tasks":[]}\n',
        )
        with patch("subprocess.run", return_value=completed):
            result = eve_openclaw_body.run_openclaw_json_command(["tasks", "list", "--json"])

        self.assertTrue(result["ok"])
        self.assertEqual([], result["payload"]["tasks"])

    def test_activity_ingest_events_keep_openclaw_as_noncanonical_body_bus(self) -> None:
        def fake_command(args, *, timeout=20):
            joined = " ".join(args)
            if joined.startswith("tasks"):
                return {"ok": True, "payload": {"tasks": []}}
            if joined.startswith("hooks"):
                return {"ok": True, "payload": {"hooks": [{"name": "command-logger"}]}}
            if joined.startswith("mcp"):
                return {"ok": True, "payload": {}}
            return {"ok": False, "payload": {}}

        with patch.object(eve_openclaw_body, "run_openclaw_json_command", side_effect=fake_command), patch.object(
            eve_openclaw_body,
            "read_task_rows_from_sqlite",
            return_value={"ok": True, "source": "tasks.sqlite", "tasks": [{"task_id": "task-1"}]},
        ):
            events = eve_openclaw_body.build_openclaw_activity_events(state_dir=Path("/tmp/openclaw-test"), limit=5)

        self.assertEqual(
            ["openclaw_task_snapshot", "openclaw_hook_inventory", "openclaw_mcp_inventory"],
            [event["event_type"] for event in events],
        )
        for event in events:
            self.assertEqual("openclaw_body_bus", event["body_bus_layer"])
            self.assertFalse(event["canonical_memory_authority"])
            self.assertEqual(eve_openclaw_body.OPENCLAW_BODY_SUBSTRATE_ID, event["substrate_id"])

    def test_hook_callback_event_redacts_sensitive_context(self) -> None:
        event = eve_openclaw_body.build_hook_callback_event(
            {
                "type": "command",
                "action": "new",
                "sessionKey": "agent:main:main",
                "timestamp": "2026-04-24T23:45:00.000Z",
                "context": {
                    "senderId": "local",
                    "token": "secret-token",
                    "cfg": {"gateway": {"auth": {"token": "also-secret"}}},
                    "deps": {"cron": {"state": "internal"}},
                    "sessionEntry": {
                        "sessionId": "abc",
                        "sessionFile": "/tmp/session.jsonl",
                    },
                },
            }
        )

        self.assertEqual("openclaw_hook_callback", event["event_type"])
        self.assertFalse(event["canonical_memory_authority"])
        context = event["payload"]["event"]["context"]
        self.assertEqual("[redacted]", context["token"])
        self.assertEqual("[redacted]", context["cfg"])
        self.assertEqual("[redacted]", context["deps"])
        self.assertEqual("abc", context["sessionEntry"]["sessionId"])

    def test_session_activity_reads_dedicated_repair_agent_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            for agent_id in ["main", "eve-repair"]:
                sessions_dir = state_dir / "agents" / agent_id / "sessions"
                sessions_dir.mkdir(parents=True)
                session_id = f"{agent_id}-session"
                (sessions_dir / "sessions.json").write_text(
                    json.dumps(
                        {
                            f"agent:{agent_id}:main": {
                                "sessionId": session_id,
                                "status": "done",
                                "modelProvider": "llamacpp-deep",
                                "model": "eve-deep",
                                "sessionFile": str(sessions_dir / f"{session_id}.jsonl"),
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                (sessions_dir / f"{session_id}.trajectory.jsonl").write_text(
                    json.dumps({"type": "session.started", "ts": "2026-04-25T00:00:00Z"}) + "\n",
                    encoding="utf-8",
                )

            activity = eve_openclaw_body.read_session_activity(state_dir, limit=4)

        self.assertEqual(["eve-repair", "main"], activity["agents_checked"])
        self.assertEqual(2, activity["active_session_count"])
        agent_ids = {item["agent_id"] for item in activity["active_sessions"]}
        self.assertEqual({"main", "eve-repair"}, agent_ids)
        trajectory_agent_ids = {item["agent_id"] for item in activity["recent_trajectories"]}
        self.assertEqual({"main", "eve-repair"}, trajectory_agent_ids)

    def test_sanitize_existing_hook_evidence_rewrites_with_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            evidence_path = Path(temp_dir) / "openclaw_evidence_events.jsonl"
            stale_record = eve_openclaw_body.build_hook_callback_event(
                {
                    "type": "gateway",
                    "action": "startup",
                    "sessionKey": "gateway:startup",
                    "context": {"deps": {"cron": {"state": "verbose"}}, "token": "secret"},
                }
            )
            stale_record["payload"]["event"]["context"]["deps"] = {"cron": {"state": "verbose"}}
            evidence_path.write_text(json.dumps(stale_record) + "\n", encoding="utf-8")

            report = eve_openclaw_body.sanitize_existing_hook_evidence_events(paths=[evidence_path])
            records = eve_openclaw_body.eve_store.read_jsonl_records(evidence_path)

            self.assertEqual(1, report["changed_records"])
            self.assertEqual(1, len(list(Path(temp_dir).glob("*.bak"))))
            self.assertEqual("[redacted]", records[0]["payload"]["event"]["context"]["deps"])
            self.assertEqual("openclaw_hook_sensitive_context_v2", records[0]["redaction_revision"])


if __name__ == "__main__":
    unittest.main()
