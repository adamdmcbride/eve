import ast
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import eve_runtime_projection
import eve_web


ROOT = Path(__file__).resolve().parents[1]


class RuntimeProjectionBoundaryTests(unittest.TestCase):
    def test_projection_module_is_one_way_and_owns_no_http_service(self):
        tree = ast.parse((ROOT / "eve_runtime_projection.py").read_text(encoding="utf-8"))
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

        self.assertNotIn("eve_web", imported_modules)
        self.assertFalse(
            any(module.startswith("http") for module in imported_modules),
            imported_modules,
        )

    def test_composition_config_preserves_legacy_patch_seams(self):
        paths = [Path(f"/tmp/eve-projection-{index}.json") for index in range(4)]
        with (
            patch.object(eve_web, "API_VERSION", 91),
            patch.object(eve_web, "MODEL_WATCHDOG_STATUS_PATH", paths[0]),
            patch.object(eve_web, "MODEL_HEALTH_LOG_PATH", paths[1]),
            patch.object(eve_web, "RUNTIME_MODEL_WATCHDOG_STATUS_PATH", paths[2]),
            patch.object(eve_web, "RUNTIME_MODEL_HEALTH_LOG_PATH", paths[3]),
        ):
            config = eve_web._runtime_projection_config()

        self.assertEqual(91, config.api_version)
        self.assertEqual(paths[0], config.model_watchdog_status_path)
        self.assertEqual(paths[1], config.model_health_log_path)
        self.assertEqual(paths[2], config.runtime_model_watchdog_status_path)
        self.assertEqual(paths[3], config.runtime_model_health_log_path)

    def test_projection_config_is_immutable(self):
        config = eve_web._runtime_projection_config()

        with self.assertRaises(FrozenInstanceError):
            config.api_version = 1

    def test_runtime_service_keeps_cache_ownership_and_delegates_builds(self):
        service = eve_web.EveRuntimeService()
        model_health = {"lanes": []}
        latest_state = {"api_version": eve_web.API_VERSION}
        activity = {"models": {}, "system": {}}

        with patch.object(
            eve_web,
            "build_runtime_model_health_payload",
            return_value=model_health,
        ) as build_health:
            self.assertIs(model_health, service._build_model_health_payload(limit=7))
        health_kwargs = build_health.call_args.kwargs
        self.assertEqual(7, health_kwargs["limit"])
        self.assertEqual(eve_web._runtime_projection_config(), health_kwargs["config"])

        with patch.object(
            eve_web,
            "build_runtime_activity_payload",
            return_value=activity,
        ) as build_activity:
            self.assertIs(activity, service._build_activity_payload(model_health=model_health))
        build_activity.assert_called_once_with(model_health=model_health)

        with patch.object(
            eve_web,
            "build_runtime_latest_state",
            return_value=latest_state,
        ) as build_latest:
            self.assertIs(latest_state, service._build_latest_state())
        latest_kwargs = build_latest.call_args.kwargs
        self.assertEqual(eve_web._runtime_projection_config(), latest_kwargs["config"])
        self.assertIs(service, latest_kwargs["ordered_thread_summaries"].__self__)
        self.assertIs(service, latest_kwargs["model_health_payload"].__self__)
        self.assertTrue(hasattr(service, "_status_cache"))
        self.assertTrue(hasattr(service, "_model_health_cache"))
        self.assertTrue(hasattr(service, "_activity_cache"))

    def test_model_health_projection_is_bounded_and_uses_runtime_log(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_log = root / "source-health.jsonl"
            runtime_log = root / "runtime-health.jsonl"
            runtime_log.write_text("", encoding="utf-8")
            config = eve_runtime_projection.RuntimeProjectionConfig(
                api_version=7,
                model_watchdog_status_path=root / "source-status.json",
                model_health_log_path=source_log,
                runtime_model_watchdog_status_path=root / "runtime-status.json",
                runtime_model_health_log_path=runtime_log,
            )
            status = {
                "timestamp": "2026-08-24T00:00:00+00:00",
                "preferred_fast_model": "eve-fast",
                "preferred_deep_model": "eve-deep",
                "effective_fast_model": "eve-fast",
                "effective_deep_model": "eve-deep",
                "effective_fallback_model": "eve-deep",
                "residency": {
                    "preferred_fast_loaded": True,
                    "preferred_deep_loaded": True,
                    "both_preferred_loaded": True,
                },
                "loaded_models": [
                    {
                        "name": "eve-fast",
                        "context_length": 65536,
                        "size_vram": 123,
                        "expires_at": "later",
                        "private_command": "do not project",
                    }
                ],
                "probes": {
                    "eve-fast": {"ok": True},
                    "eve-deep": {"ok": True},
                },
                "actions": [f"action-{index}" for index in range(8)],
            }
            lanes = [{"lane": "fast"}, {"lane": "deep"}]
            hosts = [{"host": "local"}]
            recent = [{"ok": True}]
            with (
                patch.object(
                    eve_runtime_projection.eve,
                    "load_model_watchdog_status",
                    return_value=status,
                ),
                patch.object(eve_runtime_projection.eve, "load_config", return_value={"models": {}}),
                patch.object(eve_runtime_projection.eve, "model_lane_records", return_value=lanes),
                patch.object(eve_runtime_projection.eve, "model_host_records", return_value=hosts),
                patch.object(eve_runtime_projection.eve, "model_lanes_summary", return_value="2 lanes"),
                patch.object(
                    eve_runtime_projection,
                    "read_recent_jsonl",
                    return_value=recent,
                ) as read_recent,
            ):
                payload = eve_runtime_projection.build_model_health_payload(
                    config=config,
                    limit=3,
                )

        read_recent.assert_called_once_with(runtime_log, limit=3)
        self.assertEqual("Fast eve-fast · Deep eve-deep · 2 lanes", payload["summary"])
        self.assertEqual(lanes, payload["lanes"])
        self.assertEqual(hosts, payload["hosts"])
        self.assertEqual(recent, payload["recent_checks"])
        self.assertEqual([f"action-{index}" for index in range(5)], payload["recent_actions"])
        self.assertEqual(
            {"name", "context_length", "size_vram", "expires_at"},
            set(payload["loaded_models"][0]),
        )

    def test_activity_projection_keeps_resource_sampling_bounded(self):
        processes = [
            {"pid": 1, "cpu_percent": 120.0, "memory_percent": 3.0},
            {"pid": 2, "cpu_percent": 80.0, "memory_percent": 2.0},
        ]
        selected = [{"pid": 1, "command": "llama-server"}]
        with (
            patch.object(
                eve_runtime_projection.eve,
                "load_active_model_calls",
                return_value={"calls": [{"id": "call-1"}]},
            ),
            patch.object(
                eve_runtime_projection.eve,
                "read_perf_events",
                return_value=[{"id": "recent-1"}],
            ),
            patch.object(
                eve_runtime_projection,
                "model_call_event_to_monitor_json",
                side_effect=lambda item: {"id": item["id"]},
            ),
            patch.object(
                eve_runtime_projection,
                "activity_lane_to_monitor_json",
                side_effect=lambda item, active, recent: {"lane": item["lane"]},
            ),
            patch.object(eve_runtime_projection, "read_process_table", return_value=processes),
            patch.object(
                eve_runtime_projection,
                "read_memory_snapshot",
                return_value={"used_percent": 25.0},
            ),
            patch.object(eve_runtime_projection, "read_disk_snapshot", return_value={"used_percent": 50.0}),
            patch.object(eve_runtime_projection, "selected_processes", return_value=selected),
            patch.object(eve_runtime_projection.os, "cpu_count", return_value=4),
            patch.object(eve_runtime_projection.os, "getloadavg", return_value=(1.0, 2.0, 3.0)),
        ):
            payload = eve_runtime_projection.build_activity_payload(
                model_health={"lanes": [{"lane": "fast"}]}
            )

        self.assertEqual(50.0, payload["system"]["cpu_percent"])
        self.assertEqual(2, payload["system"]["process_count"])
        self.assertEqual(selected, payload["system"]["processes"])
        self.assertEqual([1.0, 2.0, 3.0], payload["system"]["load_average"])
        self.assertEqual([{"lane": "fast"}], payload["models"]["lanes"])
        self.assertEqual([{"id": "recent-1"}], payload["models"]["recent_calls"])
        self.assertIn("1 model call running", payload["models"]["summary"])


if __name__ == "__main__":
    unittest.main()
