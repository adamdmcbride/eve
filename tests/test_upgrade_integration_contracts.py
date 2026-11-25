from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import eve


class UpgradeIntegrationContractTests(unittest.TestCase):
    def setUp(self):
        observer = patch.object(eve, "observe_core_runner", return_value={"available": False})
        observer.start()
        self.addCleanup(observer.stop)

    def test_live_llama_call_fits_only_explicit_optional_context(self) -> None:
        messages = [
            {"role": "system", "content": "required identity"},
            {
                "role": "system",
                "content": "optional history",
                "_prompt_optional_priority": 1,
            },
            {"role": "user", "content": "latest user request"},
        ]
        fit_evidence = {
            "schema_id": "eve.prompt_fit.v1",
            "status": "trimmed",
            "measurement_source": "test",
            "exact_measurement": True,
            "context_tokens": 8192,
            "prompt_budget_tokens": 7716,
            "prompt_tokens_before": 9000,
            "prompt_tokens_after": 7000,
            "max_output_tokens": 220,
            "safety_tokens": 256,
            "trimmed_message_indices": [],
            "removed_message_indices": [1],
            "required_message_indices": [0, 2],
            "final_user_preserved": True,
            "content_persisted": False,
        }
        fitted_messages = [messages[0], messages[2]]
        perf_events: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def record_perf(*args: object, **kwargs: object) -> None:
            perf_events.append((args, kwargs))

        with patch.object(
            eve.eve_prompt_budget,
            "fit_messages",
            return_value=(fitted_messages, fit_evidence),
        ) as fit_messages, patch.object(
            eve,
            "llama_cpp_profile_spec_for_model",
            return_value={"ctx_size": 16384, "parallel_slots": 2},
        ), patch.object(
            eve,
            "post_json_url",
            return_value={"choices": [{"message": {"content": "answer"}}]},
        ) as post_json, patch.object(eve, "append_perf_event", side_effect=record_perf):
            result = eve.llama_cpp_chat(
                {},
                "http://127.0.0.1:8080",
                "eve-fast",
                messages,
                max_tokens=220,
                operation="reply_generate",
                timeout_seconds=30,
            )

        self.assertEqual("answer", result)
        fit_kwargs = fit_messages.call_args.kwargs
        self.assertEqual({1: 1}, fit_kwargs["optional_priorities"])
        self.assertEqual({0, 2}, fit_kwargs["required_indices"])
        self.assertEqual(8192, fit_kwargs["fallback_context_tokens"])
        submitted = post_json.call_args.args[1]["messages"]
        self.assertEqual("latest user request", submitted[-1]["content"])
        self.assertNotIn("optional history", str(submitted))
        self.assertFalse(any("_prompt_optional_priority" in item for item in submitted))
        prompt_events = [item for item in perf_events if item[0][:1] == ("prompt_fit",)]
        self.assertEqual(1, len(prompt_events))
        self.assertNotIn("required identity", str(prompt_events[0]))
        self.assertNotIn("latest user request", str(prompt_events[0]))

    def test_fresh_snapshot_reconciles_stale_disk_clauses_without_rescanning(self) -> None:
        state = {
            "cleanup_candidate_summary": (
                "CPU cleanup scan: disk 99.2% used and 14.8 GiB free; urgency high. "
                "Approval-required cleanup candidates: old candidates."
            ),
            "cleanup_review_summary": (
                "Cleanup review completed without deleting anything. CPU cleanup scan: "
                "disk 98.9% used and 19.6 GiB free; urgency high. Candidates remain reviewed."
            ),
        }
        snapshot = {
            "timestamp": "2026-08-23T18:00:00+00:00",
            "summary": "Current host snapshot",
            "load_state": "idle",
            "disk": {
                "used_percent": 67.4,
                "free_bytes": 600 * 1024 * 1024 * 1024,
            },
        }

        with patch.object(
            eve,
            "cleanup_size_rows",
            side_effect=AssertionError("freshness reconciliation must not rescan disk candidates"),
        ):
            eve.apply_system_snapshot_to_state(state, snapshot)

        self.assertNotIn("99.2%", state["cleanup_candidate_summary"])
        self.assertNotIn("14.8 GiB", state["cleanup_candidate_summary"])
        self.assertIn("67.4% used", state["cleanup_candidate_summary"])
        self.assertIn("600.0 GiB free", state["cleanup_candidate_summary"])
        self.assertIn("urgency low", state["cleanup_candidate_summary"])
        self.assertNotIn("98.9%", state["cleanup_review_summary"])
        self.assertIn("Candidates remain reviewed", state["cleanup_review_summary"])
        self.assertEqual("2026-08-23T18:00:00+00:00", state["cleanup_disk_observed_at"])

    def test_once_daemon_cycle_preserves_resident_process_identity(self) -> None:
        class Args:
            once = True
            force = False
            sleep_seconds = 0

        state = {
            "daemon_started_at": "2026-08-23T16:00:00+00:00",
            "daemon_process_id": 4242,
            "daemon_code_path": "/runtime/eve.py",
            "daemon_code_mtime": "2026-08-23T15:59:00+00:00",
        }
        saved: list[dict[str, object]] = []

        with TemporaryDirectory() as temp_dir, patch.object(
            eve, "RUNTIME_DIR", Path(temp_dir)
        ), patch.object(eve, "load_config", return_value={}), patch.object(
            eve, "load_state", return_value=state
        ), patch.object(
            eve, "save_state", side_effect=lambda value: saved.append(dict(value))
        ), patch.object(
            eve, "run_daemon_cycle", return_value=[]
        ), patch.object(
            eve, "daemon_cycle_activity_heartbeat", return_value=nullcontext({})
        ), patch.object(
            eve, "write_operator_power_state"
        ):
            result = eve.cmd_daemon_run(Args())

        self.assertEqual(0, result)
        self.assertTrue(saved)
        initial = saved[0]
        self.assertEqual(4242, initial["daemon_process_id"])
        self.assertEqual("/runtime/eve.py", initial["daemon_code_path"])
        self.assertEqual("2026-08-23T15:59:00+00:00", initial["daemon_code_mtime"])
        self.assertEqual("2026-08-23T16:00:00+00:00", initial["daemon_started_at"])
        self.assertEqual(os.getpid(), initial["last_daemon_once_pid"])
        self.assertIn("T", str(initial["last_daemon_once_at"]))

    def test_outreach_forces_relational_support_and_marks_bulk_context_optional(self) -> None:
        config = {
            "ollama_host": "http://127.0.0.1:11434",
            "think_level": "off",
            "recent_context_limit": 4,
            "thought_history_limit": 2,
            "outreach_max_tokens": 180,
            "outreach_timeout_seconds": 30,
        }
        with patch.object(eve, "ensure_version_snapshot"), patch.object(
            eve, "resolve_model", return_value="eve-fast"
        ), patch.object(
            eve, "ensure_human_context", return_value={}
        ), patch.object(
            eve, "load_active_mind", return_value={"current_focus": "repair daemon routing"}
        ), patch.object(
            eve, "read_salient_entries", return_value=[{"body": "one grounded entry"}]
        ), patch.object(
            eve, "read_entries_by_kind", return_value=[]
        ), patch.object(
            eve, "read_tensions", return_value=[]
        ), patch.object(
            eve, "read_experiments", return_value=[]
        ), patch.object(
            eve, "read_proposals", return_value=[]
        ), patch.object(
            eve, "read_thread_summaries", return_value=[]
        ), patch.object(
            eve, "read_lived_messages", return_value=[]
        ), patch.object(
            eve,
            "build_eve_identity_system_messages",
            return_value=[{"role": "system", "content": "required identity"}],
        ), patch.object(
            eve,
            "build_supporting_system_messages",
            return_value=[{"role": "system", "content": "relational support"}],
        ) as supporting, patch.object(
            eve, "build_outreach_context_message", return_value="bulk outreach context"
        ), patch.object(
            eve,
            "model_chat",
            return_value="Subject: Checking in\nBody:\nWould you like to talk about what matters today?",
        ) as model_chat, patch.object(
            eve, "proactive_outreach_quality_issues", return_value=[]
        ):
            result = eve.generate_eve_outreach(config, allow_none=True, source="test")

        self.assertIsNotNone(result)
        self.assertEqual(
            "user_relational",
            supporting.call_args.kwargs["context_route"]["profile"],
        )
        submitted = model_chat.call_args.args[2]
        support_message = next(item for item in submitted if item.get("content") == "relational support")
        bulk_message = next(item for item in submitted if item.get("content") == "bulk outreach context")
        self.assertEqual(1, support_message[eve.PROMPT_OPTIONAL_PRIORITY_FIELD])
        self.assertEqual(2, bulk_message[eve.PROMPT_OPTIONAL_PRIORITY_FIELD])
        self.assertNotIn(eve.PROMPT_OPTIONAL_PRIORITY_FIELD, submitted[0])
        self.assertNotIn(eve.PROMPT_OPTIONAL_PRIORITY_FIELD, submitted[-1])

    def test_hermes_empty_hook_receipt_is_not_misclassified_as_configured(self) -> None:
        commands = {
            "hooks_list": {
                "ok": True,
                "stdout": "No shell hooks or outbound webhooks configured in the profile.",
                "stderr": "",
            },
            "cron_list": {"ok": True, "stdout": "No scheduled jobs", "stderr": ""},
        }
        families = eve.build_hermes_capability_families(commands, {})
        cron_hooks = next(item for item in families if item.get("id") == "cron_hooks")
        self.assertEqual("available_not_configured", cron_hooks["status"])

    def test_daemon_health_credits_a_fresh_bounded_cycle_heartbeat(self) -> None:
        stale_loop = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        with patch.object(
            eve,
            "inspect_launch_agent_status",
            return_value={"state": "running", "last_exit_code": "1"},
        ), patch.object(
            eve, "load_state", return_value={"last_loop_at": stale_loop}
        ), patch.object(
            eve,
            "doctor_runtime_state_with_recent_entries",
            side_effect=lambda state, **_kwargs: state,
        ), patch.object(
            eve, "read_text_tail", return_value=""
        ), patch.object(
            eve,
            "presence_runtime_liveness",
            return_value={"live": True, "active": True, "status": "active"},
        ):
            result = eve.daemon_health_diagnostics({"loop_sleep_seconds": 30})

        self.assertFalse(result["degraded"])
        self.assertIn("active bounded cycle heartbeat is fresh", result["part"])
        self.assertNotIn("last exit 1", result["part"])

    def test_new_canaries_are_reachable_through_eves_owned_cli_surfaces(self) -> None:
        parser = eve.build_parser()
        isolation = parser.parse_args(["self-repair", "isolation", "--no-write"])
        otel = parser.parse_args(["infra", "otel-genai", "--runtime", "--no-save"])
        mcp = parser.parse_args(["infra", "mcp-2026", "--no-live", "--no-write"])

        self.assertIs(isolation.func, eve.cmd_self_repair_isolation)
        self.assertIs(otel.func, eve.cmd_infra_otel_genai)
        self.assertIs(mcp.func, eve.cmd_infra_mcp_2026)
        self.assertIn(
            "python3 eve.py self-repair isolation --json",
            eve.SPECIALIST_SUBSTRATE_REGISTRY["coding_self_repair_specialist"]["commands"],
        )
        self.assertIn(
            "python3 eve.py infra otel-genai --runtime --json",
            eve.SPECIALIST_SUBSTRATE_REGISTRY["oss_improvement_substrate"]["commands"],
        )
        self.assertIn(
            "python3 eve.py infra mcp-2026 --json",
            eve.SPECIALIST_SUBSTRATE_REGISTRY["openclaw_body_action_nervous_system"]["commands"],
        )


if __name__ == "__main__":
    unittest.main()
