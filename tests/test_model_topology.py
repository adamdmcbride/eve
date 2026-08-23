import json
import importlib.util
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve
import eve_model_topology


WATCHDOG_SPEC = importlib.util.spec_from_file_location(
    "eve_model_watchdog_topology_test", ROOT / "bin" / "eve_model_watchdog.py"
)
assert WATCHDOG_SPEC and WATCHDOG_SPEC.loader
eve_model_watchdog = importlib.util.module_from_spec(WATCHDOG_SPEC)
WATCHDOG_SPEC.loader.exec_module(eve_model_watchdog)

OPENCLAW_TOPOLOGY_SPEC = importlib.util.spec_from_file_location(
    "eve_openclaw_topology_sync_test", ROOT / "bin" / "eve_openclaw_topology_sync.py"
)
assert OPENCLAW_TOPOLOGY_SPEC and OPENCLAW_TOPOLOGY_SPEC.loader
eve_openclaw_topology_sync = importlib.util.module_from_spec(OPENCLAW_TOPOLOGY_SPEC)
OPENCLAW_TOPOLOGY_SPEC.loader.exec_module(eve_openclaw_topology_sync)


THREE_SUBSTRATE_CONFIG = {
    "model_backend": "llama_cpp",
    "model_lane_topology_mode": "three_substrate",
    "model_lane_three_substrate_profile_map": {
        "fast": "fast",
        "relationship": "fast",
        "observer": "observer",
        "planner": "observer",
        "deep": "deep",
    },
    "fast_model": "eve-fast",
    "deep_model": "eve-deep",
    "model": "eve-deep",
    "mind_stream_observer_model": "eve-observer",
    "mind_stream_planner_model": "eve-planner",
    "mind_stream_relationship_model": "eve-relationship",
    "llama_cpp_model_alias": "eve-fast",
    "deep_llama_cpp_model_alias": "eve-deep",
    "observer_llama_cpp_model_alias": "eve-observer",
    "planner_llama_cpp_model_alias": "eve-planner",
    "relationship_llama_cpp_model_alias": "eve-relationship",
}


class ModelTopologyContractTests(unittest.TestCase):
    def test_fresh_eve_defaults_to_local_llama_cpp_on_three_substrates(self):
        config = dict(eve.DEFAULT_CONFIG)
        routes = {item["lane"]: item for item in eve.model_lane_records(config)}

        self.assertEqual("llama_cpp", eve.normalize_model_backend(None))
        self.assertEqual("llama_cpp", config["model_backend"])
        self.assertEqual("three_substrate", config["model_lane_topology_mode"])
        self.assertEqual("eve-fast", routes["fast"]["model"])
        self.assertEqual("eve-deep", routes["deep"]["model"])
        self.assertEqual("eve-observer", routes["planner"]["model"])
        self.assertEqual(routes["fast"]["host"], routes["relationship"]["host"])
        self.assertEqual(routes["observer"]["host"], routes["planner"]["host"])
        self.assertTrue(all(item["backend"] == "llama_cpp" for item in routes.values()))

    def test_five_endpoint_default_has_five_distinct_substrates(self):
        snapshot = eve_model_topology.topology_snapshot({})

        self.assertTrue(snapshot["valid"])
        self.assertEqual("five_endpoint", snapshot["mode"])
        self.assertEqual(5, snapshot["logical_lane_count"])
        self.assertEqual(5, snapshot["substrate_count"])
        self.assertEqual([], snapshot["inactive_substrates"])

    def test_three_substrate_preserves_five_routes_on_three_processes(self):
        snapshot = eve_model_topology.topology_snapshot(THREE_SUBSTRATE_CONFIG)
        routes = {item["logical_lane"]: item for item in snapshot["routes"]}

        self.assertTrue(snapshot["valid"])
        self.assertEqual(5, snapshot["logical_lane_count"])
        self.assertEqual(3, snapshot["substrate_count"])
        self.assertEqual("fast", routes["relationship"]["substrate_profile"])
        self.assertEqual("eve-fast", routes["relationship"]["substrate_model"])
        self.assertEqual("observer", routes["planner"]["substrate_profile"])
        self.assertEqual("eve-observer", routes["planner"]["substrate_model"])
        self.assertEqual(
            {"planner", "relationship"},
            {item["profile"] for item in snapshot["inactive_substrates"]},
        )

    def test_nominal_duplicate_aliases_resolve_to_active_substrates(self):
        self.assertEqual(
            "eve-observer",
            eve_model_topology.effective_substrate_model(
                THREE_SUBSTRATE_CONFIG, "eve-planner"
            ),
        )
        self.assertEqual(
            "eve-fast",
            eve_model_topology.effective_substrate_model(
                THREE_SUBSTRATE_CONFIG, "eve-relationship"
            ),
        )

    def test_invalid_three_substrate_map_is_rejected_before_lifecycle_change(self):
        config = dict(THREE_SUBSTRATE_CONFIG)
        config["model_lane_three_substrate_profile_map"] = {
            **THREE_SUBSTRATE_CONFIG["model_lane_three_substrate_profile_map"],
            "planner": "planner",
        }

        snapshot = eve_model_topology.topology_snapshot(config)

        self.assertFalse(snapshot["valid"])
        self.assertIn("requires 3 active substrates", " ".join(snapshot["validation_errors"]))

    def test_shell_contract_exposes_active_and_inactive_service_sets(self):
        snapshot = eve_model_topology.topology_snapshot(THREE_SUBSTRATE_CONFIG)
        contract = eve_model_topology.shell_contract(snapshot)

        self.assertIn("EVE_MODEL_TOPOLOGY_VALID=1", contract)
        self.assertIn("MODEL_LANE_ACTIVE_LABELS=(", contract)
        self.assertIn(eve_model_topology.profile_launch_label("observer"), contract)
        self.assertIn(
            "MODEL_LANE_INACTIVE_LABELS=(%s %s)"
            % (
                eve_model_topology.profile_launch_label("planner"),
                eve_model_topology.profile_launch_label("relationship"),
            ),
            contract,
        )

    @unittest.skipUnless(Path("/bin/zsh").is_file(), "requires macOS /bin/zsh")
    def test_launcher_refuses_inactive_duplicate_profile(self):
        script = ROOT / "bin" / "start_llama_cpp_server.sh"
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            runtime_config = home / ".eve_runtime" / ".eve" / "config.json"
            runtime_config.parent.mkdir(parents=True)
            runtime_config.write_text(json.dumps(THREE_SUBSTRATE_CONFIG), encoding="utf-8")
            environment = dict(os.environ)
            environment["HOME"] = str(home)

            result = subprocess.run(
                ["/bin/zsh", str(script), "planner", "--dry-run"],
                capture_output=True,
                text=True,
                timeout=10,
                env=environment,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("planner is inactive under three_substrate", result.stdout)
        self.assertNotIn("--port 8083", result.stdout)

    def test_three_substrate_plists_leave_rollback_definitions_installed_but_inactive(self):
        with patch.object(eve.eve_platform, "is_macos", return_value=True), patch.object(
            eve, "load_config", return_value=dict(THREE_SUBSTRATE_CONFIG)
        ):
            payloads = eve.build_macos_continuity_launch_agent_plists()

        planner = plistlib.loads(payloads[eve.LLAMA_CPP_LANE_SERVICE_LABELS["planner"]])
        relationship = plistlib.loads(payloads[eve.LLAMA_CPP_LANE_SERVICE_LABELS["relationship"]])
        observer = plistlib.loads(payloads[eve.LLAMA_CPP_LANE_SERVICE_LABELS["observer"]])
        self.assertFalse(planner["RunAtLoad"])
        self.assertFalse(planner["KeepAlive"])
        self.assertFalse(relationship["RunAtLoad"])
        self.assertFalse(relationship["KeepAlive"])
        self.assertTrue(observer["RunAtLoad"])
        self.assertTrue(observer["KeepAlive"])

    def test_continuity_start_disables_duplicate_services_and_starts_active_substrates(self):
        installed = [
            *eve.CONTINUITY_GUARDIAN_LABELS,
            *eve.CONTINUITY_BASE_COMPANION_LABELS,
            *eve.LLAMA_CPP_LANE_SERVICE_LABELS.values(),
        ]
        with patch.object(eve.eve_platform, "is_macos", return_value=True), patch.object(
            eve, "install_macos_continuity_launch_agents", return_value=installed
        ), patch.object(eve, "load_config", return_value=dict(THREE_SUBSTRATE_CONFIG)), patch.object(
            eve, "continuity_launch_agent_path", side_effect=lambda label: Path(f"/tmp/{label}.plist")
        ), patch.object(eve, "launchctl_domain", return_value="gui/501"), patch.object(
            eve, "run_launchctl"
        ) as run_launchctl:
            started = eve.start_macos_continuity_launch_agents()

        planner_label = eve.LLAMA_CPP_LANE_SERVICE_LABELS["planner"]
        relationship_label = eve.LLAMA_CPP_LANE_SERVICE_LABELS["relationship"]
        active_labels = {
            eve.LLAMA_CPP_LANE_SERVICE_LABELS["fast"],
            eve.LLAMA_CPP_LANE_SERVICE_LABELS["deep"],
            eve.LLAMA_CPP_LANE_SERVICE_LABELS["observer"],
        }
        commands = [call.args[0] for call in run_launchctl.call_args_list]
        self.assertIn(["disable", f"gui/501/{planner_label}"], commands)
        self.assertIn(["disable", f"gui/501/{relationship_label}"], commands)
        self.assertTrue(active_labels.issubset(set(started)))
        self.assertNotIn(planner_label, started)
        self.assertNotIn(relationship_label, started)
        for label in active_labels:
            self.assertIn(["bootstrap", "gui/501", f"/tmp/{label}.plist"], commands)

    def test_operator_scripts_consume_shared_topology_contract(self):
        control = (ROOT / "mac" / "bin" / "eve_control.sh").read_text(encoding="utf-8")
        deadman = (ROOT / "bin" / "eve_deadman.sh").read_text(encoding="utf-8")

        self.assertIn("eve_model_topology.py", control)
        self.assertIn("MODEL_LANE_INACTIVE_LABELS", control)
        self.assertIn("EVE_ACTIVE_MODEL_URLS", control)
        self.assertIn("eve_model_topology.py", deadman)
        self.assertIn("active-urls", deadman)
        self.assertIn("expected_model_substrates", deadman)
        self.assertIn("--check-only", deadman)

    def test_openclaw_logical_providers_follow_active_substrates(self):
        openclaw = {
            "agents": {
                "defaults": {
                    "model": {
                        "primary": "llamacpp-deep/eve-deep",
                        "fallbacks": ["llamacpp-planner/eve-planner"],
                    },
                    "utilityModel": "llamacpp-observer/eve-observer",
                    "models": {
                        "llamacpp/eve-fast": {"alias": "Eve Fast"},
                        "llamacpp-deep/eve-deep": {"alias": "Eve Deep"},
                        "llamacpp-observer/eve-observer": {"alias": "Eve Observer"},
                        "llamacpp-planner/eve-planner": {"alias": "Eve Planner"},
                        "llamacpp-relationship/eve-relationship": {
                            "alias": "Eve Relationship"
                        },
                    },
                }
            },
            "models": {
                "mode": "replace",
                "providers": {
                    provider: {
                        "baseUrl": f"http://127.0.0.1:{port}/v1",
                        "models": [{"id": model, "contextWindow": 8192}],
                    }
                    for provider, port, model in (
                        ("llamacpp", 8080, "eve-fast"),
                        ("llamacpp-deep", 8081, "eve-deep"),
                        ("llamacpp-observer", 8082, "eve-observer"),
                        ("llamacpp-planner", 8083, "eve-planner"),
                        ("llamacpp-relationship", 8084, "eve-relationship"),
                    )
                },
            },
        }
        openclaw["models"]["providers"]["llamacpp-deep"]["timeoutSeconds"] = 450

        updated, report = (
            eve_openclaw_topology_sync.reconcile_openclaw_topology_config(
                THREE_SUBSTRATE_CONFIG, openclaw
            )
        )
        providers = updated["models"]["providers"]
        aliases = updated["agents"]["defaults"]["models"]

        self.assertEqual("three_substrate", report["topology_mode"])
        self.assertEqual(3, report["substrate_count"])
        self.assertEqual(
            "http://127.0.0.1:8082/v1", providers["llamacpp-planner"]["baseUrl"]
        )
        self.assertEqual(
            "eve-observer", providers["llamacpp-planner"]["models"][0]["id"]
        )
        self.assertEqual(
            "http://127.0.0.1:8080/v1",
            providers["llamacpp-relationship"]["baseUrl"],
        )
        self.assertEqual(
            "eve-fast", providers["llamacpp-relationship"]["models"][0]["id"]
        )
        self.assertEqual(450, providers["llamacpp-deep"]["timeoutSeconds"])
        self.assertTrue(
            all(provider["timeoutSeconds"] >= 300 for provider in providers.values())
        )
        self.assertEqual(
            16384,
            providers["llamacpp-observer"]["models"][0]["contextWindow"],
        )
        self.assertEqual(
            15616,
            providers["llamacpp-planner"]["models"][0]["contextTokens"],
        )
        self.assertIn("llamacpp-planner/eve-observer", aliases)
        self.assertIn("llamacpp-relationship/eve-fast", aliases)
        self.assertNotIn("llamacpp-planner/eve-planner", aliases)
        self.assertEqual(
            ["llamacpp-planner/eve-observer"],
            updated["agents"]["defaults"]["model"]["fallbacks"],
        )
        self.assertNotIn("utilityModel", updated["agents"]["defaults"])

    def test_live_canary_dry_run_validates_without_changing_config(self):
        script = ROOT / "bin" / "eve_model_topology_canary.py"
        before = (ROOT / ".eve" / "config.json").read_bytes()

        result = subprocess.run(
            [sys.executable, str(script), "--dry-run"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=20,
        )

        after = (ROOT / ".eve" / "config.json").read_bytes()
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("three_substrate", payload["target"]["mode"])
        self.assertEqual(5, payload["target"]["logical_lane_count"])
        self.assertEqual(3, payload["target"]["substrate_count"])
        self.assertEqual(before, after)

    def test_live_canary_contains_automatic_rollback_and_shared_failure_gates(self):
        source = (ROOT / "bin" / "eve_model_topology_canary.py").read_text(encoding="utf-8")

        self.assertIn("shared_failure_recovery", source)
        self.assertIn("concurrency_probe", source)
        self.assertIn("deploy_current_source_config", source)
        self.assertIn("baseline_normalized_by_fresh_redeploy", source)
        self.assertIn("capture_residency_window", source)
        self.assertIn("physical_footprint_for_pid", source)
        self.assertIn("if target_deployed and not promoted", source)
        self.assertIn("eve_store.write_json_dict(SOURCE_CONFIG_PATH, original_config", source)

    def test_watchdog_watches_active_substrate_aliases_not_duplicate_or_experimental_models(self):
        config = {
            **THREE_SUBSTRATE_CONFIG,
            "experimental_memory_retrieval_model": "embedding-helper",
            "experimental_prompt_router_model": "router-helper",
            "reply_stream_listener_model": "eve-relationship",
        }

        names = eve_model_watchdog.configured_all_model_names(config)

        self.assertEqual({"eve-fast", "eve-deep", "eve-observer"}, set(names))

    def test_watchdog_restarts_planner_through_observer_substrate_label(self):
        self.assertEqual(
            eve_model_topology.profile_launch_label("observer"),
            eve_model_watchdog.llama_cpp_launch_label_for_model(
                dict(THREE_SUBSTRATE_CONFIG), "eve-planner"
            ),
        )

    def test_watchdog_reconciliation_disables_only_inactive_duplicate_services(self):
        completed = subprocess.CompletedProcess([], 0)
        with patch.object(eve_model_watchdog.eve_platform, "is_macos", return_value=True), patch.object(
            eve_model_watchdog.os, "getuid", return_value=501
        ), patch.object(
            eve_model_watchdog.subprocess, "run", return_value=completed
        ) as run:
            result = eve_model_watchdog.reconcile_llama_cpp_service_topology(
                dict(THREE_SUBSTRATE_CONFIG)
            )

        self.assertTrue(result["valid"])
        self.assertEqual(3, len(result["active_labels"]))
        self.assertEqual(2, len(result["inactive_labels"]))
        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn(
            [
                "launchctl",
                "disable",
                f"gui/501/{eve_model_topology.profile_launch_label('planner')}",
            ],
            commands,
        )
        self.assertIn(
            [
                "launchctl",
                "disable",
                f"gui/501/{eve_model_topology.profile_launch_label('relationship')}",
            ],
            commands,
        )
        self.assertIn(
            [
                "launchctl",
                "enable",
                f"gui/501/{eve_model_topology.profile_launch_label('observer')}",
            ],
            commands,
        )

    def test_status_projects_three_physical_substrates_back_to_five_logical_lanes(self):
        watchdog = {
            "updated_at": eve.utc_now(),
            "loaded_models": [
                {"name": "eve-fast", "size_vram": 1},
                {"name": "eve-deep", "size_vram": 2},
                {"name": "eve-observer", "size_vram": 1},
            ],
            "probes": {
                "eve-fast": {"ok": True, "wall_ms": 100},
                "eve-deep": {"ok": True, "wall_ms": 200},
                "eve-observer": {"ok": True, "wall_ms": 100},
            },
            "llama_hosts": [
                {"host": "http://127.0.0.1:8080", "ready": True, "models": ["eve-fast"]},
                {"host": "http://127.0.0.1:8081", "ready": True, "models": ["eve-deep"]},
                {"host": "http://127.0.0.1:8082", "ready": True, "models": ["eve-observer"]},
            ],
        }

        lanes = eve.model_lane_records(dict(THREE_SUBSTRATE_CONFIG), watchdog_status=watchdog)
        by_lane = {item["lane"]: item for item in lanes}
        health = eve.model_lane_health_whole_system_result(
            dict(THREE_SUBSTRATE_CONFIG), watchdog
        )

        self.assertEqual(5, len(lanes))
        self.assertTrue(all(item["loaded"] and item["probe_ok"] for item in lanes))
        self.assertEqual("eve-observer", by_lane["planner"]["model"])
        self.assertEqual("observer", by_lane["planner"]["substrate_profile"])
        self.assertEqual("eve-fast", by_lane["relationship"]["model"])
        self.assertEqual("fast", by_lane["relationship"]["substrate_profile"])
        self.assertEqual("passed", health["status"])
        self.assertEqual(5, health["evidence"]["expected_lane_count"])
        self.assertEqual(5, health["evidence"]["loaded_lane_count"])
        self.assertEqual(3, health["evidence"]["expected_substrate_count"])
        self.assertEqual(3, health["evidence"]["loaded_substrate_count"])


if __name__ == "__main__":
    unittest.main()
