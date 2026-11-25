import ast
from contextlib import ExitStack
import json
import math
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import eve_monitor_projection
import eve_web


ROOT = Path(__file__).resolve().parents[1]


class MonitorProjectionModuleTests(unittest.TestCase):
    def test_eve_web_reexports_every_monitor_projection_function(self):
        module_source = (ROOT / "eve_monitor_projection.py").read_text(encoding="utf-8")
        web_source = (ROOT / "eve_web.py").read_text(encoding="utf-8")
        functions = [
            node.name
            for node in ast.parse(module_source).body
            if isinstance(node, ast.FunctionDef)
        ]

        self.assertEqual(52, len(functions))
        for name in functions:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(eve_monitor_projection, name),
                    getattr(eve_web, name),
                )
                self.assertNotIn(f"def {name}(", web_source)

    def test_projection_module_does_not_import_the_http_service(self):
        tree = ast.parse(
            (ROOT / "eve_monitor_projection.py").read_text(encoding="utf-8")
        )
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

        self.assertNotIn("eve_web", imported_modules)

    def test_monitor_status_projection_is_bounded_and_excludes_extra_fields(self):
        secret = "private-model-command"
        payload = eve_monitor_projection.build_monitor_status_payload(
            {
                "api_version": 8,
                "counts": {"active_threads": 3, "private_count": 99},
                "daemon": {"runtime_dir": "/tmp/eve", "running": True, "awake": True},
                "active_reply": {"id": "reply-1"},
                "model_health": {
                    "summary": "ready",
                    "lanes": [
                        {
                            "lane": "fast",
                            "model": "eve-fast",
                            "loaded": True,
                            "private_command": secret,
                        }
                    ],
                    "loaded_models": [
                        {
                            "name": "eve-fast",
                            "context_length": 65536,
                            "private_command": secret,
                        }
                    ],
                    "probes": {"fast": {"ok": True}, "private": secret},
                },
                "thread_attention": [
                    {
                        "thread_id": f"thread-{index}",
                        "subject": "s" * 200,
                        "latest_preview": "p" * 300,
                    }
                    for index in range(10)
                ],
            },
            api_version=7,
        )

        self.assertEqual(8, payload["api_version"])
        self.assertEqual(3, payload["counts"]["active_threads"])
        self.assertNotIn("private_count", payload["counts"])
        self.assertEqual(8, len(payload["thread_attention"]))
        self.assertEqual(140, len(payload["thread_attention"][0]["subject"]))
        self.assertEqual(220, len(payload["thread_attention"][0]["latest_preview"]))
        self.assertNotIn(secret, json.dumps(payload))

    def test_runtime_service_retains_readers_and_delegates_monitor_assembly(self):
        service = eve_web.EveRuntimeService()
        latest = {"api_version": 7}
        status = {"model_health": {"lanes": []}}
        activity = {"models": {}, "system": {}}
        expected = {"status": status, "activity": activity}

        with (
            patch.object(service, "latest_state", return_value=latest),
            patch.object(
                eve_web,
                "build_monitor_status_payload",
                return_value=status,
            ) as build_status,
        ):
            self.assertIs(status, service.monitor_status_payload())
        build_status.assert_called_once_with(latest, api_version=eve_web.API_VERSION)

        with (
            patch.object(service, "monitor_status_payload", return_value=status),
            patch.object(service, "activity_payload", return_value=activity) as read_activity,
            patch.object(
                eve_web,
                "build_monitor_payload",
                return_value=expected,
            ) as build_payload,
        ):
            self.assertIs(expected, service.monitor_payload(compact=True))
        read_activity.assert_called_once_with(status["model_health"])
        kwargs = build_payload.call_args.kwargs
        self.assertIs(status, kwargs["status"])
        self.assertIs(activity, kwargs["activity"])
        self.assertIs(service, kwargs["conversation_spine"].__self__)
        self.assertTrue(kwargs["compact"])

    def test_compact_monitor_payload_skips_full_only_runtime_reads(self):
        common_reads = {
            "load_human_context": {},
            "read_action_executions": [],
            "read_evidence_ledger": [],
            "read_commitments": [],
            "read_experience_events": [],
            "read_user_corrections": [],
            "read_relationship_episodes": [],
            "read_autonomy_run_summaries": [],
            "governance_status_payload": {},
            "read_system_tasks": [],
            "load_global_workspace": {},
            "load_homeostasis": {},
            "load_autonomy_state": {},
            "load_autonomy_agenda": {},
        }
        full_only_reads = (
            "read_reply_turn_replays",
            "read_reply_council_turns",
            "runtime_source_truth_check",
            "load_self_model_state",
            "load_world_model_state",
            "load_relationship_model_state",
            "load_other_minds_model_state",
        )
        with ExitStack() as stack:
            for name, value in common_reads.items():
                stack.enter_context(
                    patch.object(eve_monitor_projection.eve, name, return_value=value)
                )
            for name in full_only_reads:
                stack.enter_context(
                    patch.object(
                        eve_monitor_projection.eve,
                        name,
                        side_effect=AssertionError(f"compact payload called {name}"),
                    )
                )
            stack.enter_context(
                patch.object(eve_monitor_projection, "fitness_to_monitor_json", return_value={})
            )
            payload = eve_monitor_projection.build_monitor_payload(
                status={"api_version": 7},
                activity={"models": {}, "system": {}},
                conversation_spine=lambda **kwargs: [kwargs],
                compact=True,
            )

        self.assertEqual([{"limit": 12, "include_synthetic": False}], payload["conversation_spine"])
        self.assertNotIn("runtime_source_truth", payload)
        self.assertNotIn("reply_turns", payload)

    def test_numeric_projection_rejects_non_finite_values(self):
        for value in ("nan", "inf", "-inf", float("nan"), float("inf")):
            with self.subTest(value=value):
                self.assertEqual(0.0, eve_monitor_projection.safe_float(value))
                self.assertEqual(0, eve_monitor_projection.safe_int(value))
                self.assertTrue(
                    math.isfinite(eve_monitor_projection.safe_float(value))
                )

        event = eve_monitor_projection.model_call_event_to_monitor_json(
            {
                "duration_ms": "nan",
                "metadata": {"response_chars": 20, "model": "eve-fast"},
            }
        )
        encoded = json.dumps(event, allow_nan=False)
        self.assertIn('"duration_ms": 0.0', encoded)
        self.assertEqual(0.0, event["chars_per_second"])

    def test_process_projection_never_exposes_command_arguments(self):
        secret = "private-token-123"
        result = SimpleNamespace(
            returncode=0,
            stdout=(
                "101 1 12.5 4096 python3 eve.py daemon run "
                f"--api-token {secret}\n"
                "202 1 3.0 2048 /opt/llama-server --model /private/model.gguf\n"
            ),
        )
        with patch.object(eve_monitor_projection.subprocess, "run", return_value=result):
            processes = eve_monitor_projection.read_process_table()

        self.assertEqual(2, len(processes))
        self.assertEqual("Eve daemon", processes[0]["command"])
        self.assertEqual("llama-server", processes[1]["command"])
        encoded = json.dumps(processes)
        self.assertNotIn(secret, encoded)
        self.assertNotIn("/private/model.gguf", encoded)
        self.assertNotIn("--api-token", encoded)

    def test_selected_processes_are_deduplicated_and_bounded(self):
        processes = [
            {
                "pid": index,
                "kind": "eve" if index == 1 else "system",
                "cpu_percent": 100 - index,
                "memory_bytes": index * 100,
            }
            for index in range(1, 8)
        ]

        selected = eve_monitor_projection.selected_processes(processes, limit=3)

        self.assertEqual(3, len(selected))
        self.assertEqual(3, len({item["pid"] for item in selected}))
        self.assertEqual(1, selected[0]["pid"])


if __name__ == "__main__":
    unittest.main()
