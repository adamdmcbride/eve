import io
import os
import plistlib
import re
from contextlib import ExitStack
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import eve
import eve_platform


class EvePlatformTests(unittest.TestCase):
    def test_llama_cpp_compatible_messages_preserve_leading_system_and_current_user_roles(self):
        messages = [
            {"role": "system", "content": "identity"},
            {"role": "system", "content": "current state"},
            {"role": "user", "content": "the actual current request"},
        ]

        prepared = eve.llama_cpp_compatible_messages(messages)

        self.assertEqual(["system", "user"], [item["role"] for item in prepared])
        self.assertIn("identity", prepared[0]["content"])
        self.assertIn("current state", prepared[0]["content"])
        self.assertEqual("the actual current request", prepared[1]["content"])
        self.assertNotIn("the actual current request", prepared[0]["content"])

    def test_llama_cpp_compatible_messages_turn_later_system_evidence_into_user_turn(self):
        prepared = eve.llama_cpp_compatible_messages(
            [
                {"role": "system", "content": "identity"},
                {"role": "user", "content": "inspect the file"},
                {"role": "assistant", "content": '{"type":"tool_call"}'},
                {"role": "system", "content": "tool result: file exists"},
            ]
        )

        self.assertEqual(["system", "user", "assistant", "user"], [item["role"] for item in prepared])
        self.assertIn("tool result: file exists", prepared[-1]["content"])

    def test_live_interaction_identity_is_compact_and_does_not_invite_organ_recitation(self):
        message = eve.build_interaction_identity_message(eve.default_runtime_identity())

        self.assertLess(len(message), 700)
        self.assertIn("Answer the user directly and naturally", message)
        self.assertIn("Never claim phenomenal consciousness", message)
        self.assertIn("or their absence is established", message)
        self.assertNotIn("Hermes", message)
        self.assertNotIn("Dagster", message)
        self.assertNotIn("OpenClaw", message)

    def test_live_reply_contract_keeps_current_perception_larger_than_static_manual(self):
        direct = eve.build_interaction_reply_contract(
            "The relay is still processing a block.",
            "general",
        )
        synthesis = eve.build_interaction_reply_contract(
            "The relay is still processing a block.",
            "general",
            synthesis=True,
        )

        self.assertLess(len(direct), 1200)
        self.assertLess(len(synthesis), 1300)
        self.assertIn("latest user message", direct)
        self.assertIn("fallible evidence", synthesis)
        self.assertNotIn("OpenClaw", direct)
        self.assertNotIn("proposal_id", synthesis)

    def test_approved_reply_learning_is_projected_as_compact_current_turn_signal(self):
        with patch.object(
            eve,
            "active_reply_repair_flags",
            return_value={"strict_completion", "user_anchor", "relational_concrete"},
        ):
            message = eve.build_active_reply_repairs_message(
                "How should a caring reply land?",
                "relational",
            )

        self.assertLess(len(message), 500)
        self.assertIn("complete, usable landing", message)
        self.assertIn("observable sign", message)
        self.assertNotIn("proposal_id", message)

    def test_model_input_provenance_hashes_current_user_without_retaining_text(self):
        private_text = "private current request"
        provenance = eve.model_input_provenance(
            {"model_backend": "llama_cpp", "llama_cpp_model_alias": "eve-fast"},
            "eve-fast",
            [
                {"role": "system", "content": "identity"},
                {"role": "system", "content": "state"},
                {"role": "user", "content": private_text},
            ],
            operation="agent_reply_direct",
        )

        self.assertEqual(["system", "user"], provenance["prepared_roles"])
        self.assertTrue(provenance["final_user_present"])
        self.assertTrue(provenance["final_user_is_terminal"])
        self.assertNotIn(private_text, repr(provenance))
        self.assertEqual(64, len(provenance["final_user_sha256"]))

    def test_macos_continuity_plists_cover_guardian_runtime_lanes_and_chat(self):
        topology_config = {
            "model_lane_topology_mode": "three_substrate",
            "model_lane_three_substrate_profile_map": {
                "fast": "fast",
                "relationship": "fast",
                "observer": "observer",
                "planner": "observer",
                "deep": "deep",
            },
        }
        with patch.object(eve.eve_platform, "is_macos", return_value=True), patch.object(
            eve, "load_config", return_value=topology_config
        ):
            payloads = eve.build_macos_continuity_launch_agent_plists()

        expected = {
            eve.DEADMAN_LABEL,
            eve.SYSTEM_OBSERVER_LABEL,
            eve.LIVED_NOTE_LABEL,
            eve.CHAT_BACKEND_LABEL,
            *eve.LLAMA_CPP_LANE_SERVICE_LABELS.values(),
        }
        self.assertEqual(expected, set(payloads))
        deadman = plistlib.loads(payloads[eve.DEADMAN_LABEL])
        self.assertEqual(300, deadman["StartInterval"])
        self.assertTrue(deadman["RunAtLoad"])
        chat = plistlib.loads(payloads[eve.CHAT_BACKEND_LABEL])
        self.assertTrue(chat["KeepAlive"])
        for profile, label in eve.LLAMA_CPP_LANE_SERVICE_LABELS.items():
            lane = plistlib.loads(payloads[label])
            self.assertEqual(profile, lane["ProgramArguments"][-1])
            if profile in {"planner", "relationship"}:
                self.assertFalse(lane["RunAtLoad"])
                self.assertFalse(lane["KeepAlive"])
            else:
                self.assertTrue(lane["RunAtLoad"])
                self.assertTrue(lane["KeepAlive"])

    def test_llama_cpp_launcher_prefers_synced_runtime_config(self):
        script = Path(__file__).resolve().parents[1] / "bin" / "start_llama_cpp_server.sh"
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            runtime_config = home / ".eve_runtime" / ".eve" / "config.json"
            runtime_config.parent.mkdir(parents=True)
            model_path = home / "runtime-model.gguf"
            model_path.write_bytes(b"runtime-model")
            runtime_config.write_text(
                "{"
                f'"llama_cpp_model_path": "{model_path}", '
                '"llama_cpp_model_alias": "runtime-config-fast", '
                '"llama_cpp_binary_path": "/bin/echo"'
                "}",
                encoding="utf-8",
            )
            environment = dict(os.environ)
            environment["HOME"] = str(home)

            result = subprocess.run(
                ["/bin/zsh", str(script), "fast", "--dry-run"],
                capture_output=True,
                text=True,
                timeout=10,
                env=environment,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("--alias runtime-config-fast", result.stdout)
        self.assertIn(f"--model {model_path}", result.stdout)

    def test_deadman_treats_disabled_daemon_as_failure_unless_operator_powered_off(self):
        script = (Path(__file__).resolve().parents[1] / "bin" / "eve_deadman.sh").read_text(encoding="utf-8")
        self.assertIn("operator_power_state", script)
        self.assertIn('operator_power_state" == "off"', script)
        self.assertIn("daemon service disabled while operator power state is on", script)
        self.assertIn("daemon process not running", script)
        self.assertIn("daemon loop stale", script)
        self.assertIn("daemon_activity.json", script)
        self.assertIn('activity_live" != "yes"', script)

    def test_daemon_cycle_activity_heartbeat_records_active_then_idle(self):
        records = []
        config = dict(eve.DEFAULT_CONFIG)
        config["daemon_activity_heartbeat_seconds"] = 5

        with patch.object(eve, "write_daemon_activity", side_effect=lambda record: records.append(dict(record)) or record):
            with eve.daemon_cycle_activity_heartbeat(config) as activity:
                activity["completed_jobs"] = ["mind_tick"]

        self.assertGreaterEqual(len(records), 2)
        self.assertEqual("active", records[0]["status"])
        self.assertEqual("idle", records[-1]["status"])
        self.assertEqual(["mind_tick"], records[-1]["completed_jobs"])

    def test_mac_power_control_stops_eve_services_without_killing_external_acp(self):
        script = (Path(__file__).resolve().parents[1] / "mac" / "bin" / "eve_control.sh").read_text(encoding="utf-8")
        self.assertIn('"$(service_label lived-note)"', script)
        self.assertIn('"$(service_label .chat-backend)"', script)
        self.assertNotIn('"$(service_label deadman)"', script)
        self.assertNotIn("@zed-industries/codex-acp", script)
        self.assertNotIn("openclaw-gateway|openclaw-memory|openclaw-skills", script)
        declared_pattern = re.search(
            r"^EVE_OPENCLAW_PROCESS_PATTERN='([^']+)'$",
            script,
            flags=re.MULTILINE,
        )
        self.assertIsNotNone(declared_pattern)
        pattern = declared_pattern.group(1)
        self.assertRegex(
            "/bin/sh /Users/example/.openclaw-eve-repair/wrapper --port 19011",
            pattern,
        )
        self.assertRegex("OPENCLAW_PROFILE=eve-repair node gateway", pattern)
        for external_process in (
            "/opt/homebrew/bin/node openclaw gateway --port 18789",
            "/opt/homebrew/bin/node @zed-industries/codex-acp",
            "/opt/homebrew/bin/openclaw-memory index",
        ):
            self.assertIsNone(re.search(pattern, external_process))

    def test_runtime_dir_uses_windows_local_appdata(self):
        with patch("sys.platform", "win32"), patch.dict(
            "os.environ",
            {"LOCALAPPDATA": r"C:\Users\example\AppData\Local"},
            clear=False,
        ):
            path = eve_platform.runtime_dir()
        self.assertEqual(Path(r"C:\Users\example\AppData\Local") / "Eve" / "runtime", path)

    def test_service_definition_path_uses_linux_systemd_user_dir(self):
        with patch("sys.platform", "linux"), patch.dict(
            "os.environ",
            {"XDG_CONFIG_HOME": "/home/example/.config"},
            clear=False,
        ):
            path = eve_platform.service_definition_path("org.example.eve")
        self.assertEqual(Path("/home/example/.config/systemd/user/org.example.eve.service"), path)

    def test_native_service_install_supported_on_linux_with_systemctl(self):
        with patch("sys.platform", "linux"), patch.object(eve_platform, "command_available", return_value=True):
            self.assertTrue(eve_platform.native_service_install_supported())

    def test_platform_capabilities_reports_linux_systemd_support(self):
        with patch("sys.platform", "linux"), patch.object(
            eve_platform,
            "command_available",
            side_effect=lambda name: name in {"systemctl", "ollama"},
        ):
            capabilities = eve_platform.platform_capabilities()
        self.assertEqual("linux", capabilities["platform"])
        self.assertEqual("systemd", capabilities["service_manager"])
        self.assertTrue(capabilities["native_service_install"])
        self.assertTrue(capabilities["watchdog_service_install"])
        self.assertFalse(capabilities["model_warm_service_install"])

    def test_platform_capabilities_reports_windows_scheduler_support(self):
        with patch("sys.platform", "win32"), patch.object(
            eve_platform,
            "command_available",
            side_effect=lambda name: name in {"schtasks", "ollama"},
        ):
            capabilities = eve_platform.platform_capabilities()
        self.assertEqual("windows", capabilities["platform"])
        self.assertEqual("task_scheduler", capabilities["service_manager"])
        self.assertTrue(capabilities["native_service_install"])
        self.assertTrue(capabilities["daemon_service_install"])
        self.assertTrue(capabilities["watchdog_service_install"])
        self.assertFalse(capabilities["model_warm_service_install"])


class RuntimeFallbackTests(unittest.TestCase):
    def test_sync_runtime_bundle_uses_cross_process_lock(self):
        with patch.object(eve, "ensure_store") as ensure_store, patch.object(
            eve.eve_store, "file_lock"
        ) as file_lock, patch.object(eve, "_sync_runtime_bundle_unlocked") as sync_unlocked, patch.object(
            eve,
            "runtime_source_truth_check",
            return_value={"needs_runtime_sync": False, "files": []},
        ) as truth_check:
            eve.sync_runtime_bundle()

        ensure_store.assert_called_once_with()
        file_lock.assert_called_once_with(eve.RUNTIME_BUNDLE_SYNC_LOCK_PATH)
        sync_unlocked.assert_called_once_with()
        truth_check.assert_called_once_with(include_daemon=False, include_state_authority=False)

    def test_sync_runtime_bundle_fails_closed_when_truth_still_drifts(self):
        with patch.object(eve, "ensure_store"), patch.object(eve.eve_store, "file_lock"), patch.object(
            eve, "_sync_runtime_bundle_unlocked"
        ), patch.object(
            eve,
            "runtime_source_truth_check",
            return_value={
                "needs_runtime_sync": True,
                "status": "missing_runtime_or_source",
                "files": [{"label": "eve_brandnew/feature.py", "matches": False}],
            },
        ):
            with self.assertRaisesRegex(RuntimeError, "eve_brandnew/feature.py"):
                eve.sync_runtime_bundle()

    def test_runtime_truth_tracks_extracted_eve_commands_package(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_root = temp_path / "source"
            runtime_root = temp_path / "runtime"
            source_commands = source_root / "eve_commands"
            source_commands.mkdir(parents=True)
            runtime_root.mkdir()
            (source_root / "eve.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            (source_root / "eve_web.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            (runtime_root / "eve.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            (runtime_root / "eve_web.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            (source_commands / "__init__.py").write_text("", encoding="utf-8")
            (source_commands / "openclaw_admission.py").write_text("VALUE = 1\n", encoding="utf-8")

            # New contract: the truth check auto-discovers packages and derives
            # runtime paths from RUNTIME_DIR, so patching ROOT + RUNTIME_DIR is enough.
            with patch.object(eve, "ROOT", source_root), patch.object(eve, "RUNTIME_DIR", runtime_root):
                check = eve.runtime_source_truth_check(include_daemon=False, include_state_authority=False)

        labels = {item["label"] for item in check["files"]}
        self.assertIn("eve_commands/openclaw_admission.py", labels)
        package_record = next(item for item in check["files"] if item["label"] == "eve_commands/openclaw_admission.py")
        self.assertFalse(package_record["runtime_exists"])
        self.assertTrue(check["needs_runtime_sync"])

    def test_runtime_truth_auto_discovers_a_new_package(self):
        # Regression for the May 2026 outage class: a brand-new first-party package
        # must be picked up by both the sync discovery and the truth check without
        # any hardcoded entry.
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_root = temp_path / "source"
            runtime_root = temp_path / "runtime"
            new_pkg = source_root / "eve_brandnew"
            new_pkg.mkdir(parents=True)
            runtime_root.mkdir()
            (source_root / "eve.py").write_text("#\n", encoding="utf-8")
            (runtime_root / "eve.py").write_text("#\n", encoding="utf-8")
            (new_pkg / "__init__.py").write_text("", encoding="utf-8")
            (new_pkg / "feature.py").write_text("VALUE = 2\n", encoding="utf-8")

            with patch.object(eve, "ROOT", source_root), patch.object(eve, "RUNTIME_DIR", runtime_root):
                discovered = {p.name for p in eve.first_party_package_dirs()}
                check = eve.runtime_source_truth_check(include_daemon=False, include_state_authority=False)

        self.assertIn("eve_brandnew", discovered)
        labels = {item["label"] for item in check["files"]}
        self.assertIn("eve_brandnew/feature.py", labels)
        self.assertTrue(check["needs_runtime_sync"])  # new package not yet in runtime

    def test_first_party_package_dirs_excludes_sidecar_and_generated_roots(self):
        # Auto-discovery should pick up new Eve packages, not every top-level
        # folder that accidentally grows an __init__.py. This prevents sidecars,
        # generated evidence, backups, web/UI trees, and vendor references from
        # leaking into the daemon runtime bundle.
        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir) / "source"
            source_root.mkdir()
            expected_runtime_packages = ["dagster_lab", "eve_brandnew", "eve_commands"]
            excluded_roots = [
                "EveBackups",
                "bin",
                "coordination",
                "data",
                "design",
                "docs",
                "go",
                "launchd",
                "mac",
                "memory",
                "models",
                "openclaw",
                "reviews",
                "rust",
                "script",
                "tests",
                "vendor",
                "web",
                "random_helpers",
            ]
            for name in [*expected_runtime_packages, *excluded_roots]:
                package_dir = source_root / name
                package_dir.mkdir(parents=True)
                (package_dir / "__init__.py").write_text("", encoding="utf-8")

            with patch.object(eve, "ROOT", source_root):
                discovered = {path.name for path in eve.first_party_package_dirs()}

        self.assertEqual(set(expected_runtime_packages), discovered)
        self.assertNotIn("openclaw", discovered)
        self.assertNotIn("memory", discovered)
        self.assertNotIn("random_helpers", discovered)

    def test_sync_runtime_bundle_auto_copies_new_first_party_package(self):
        # The truth-check regression above proves discovery; this one proves the
        # actual sync path mirrors the new package into the runtime bundle.
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_root = temp_path / "source"
            runtime_root = temp_path / "runtime"
            source_root.mkdir()
            runtime_root.mkdir()
            for module_name in ("eve.py", "eve_web.py", "eve_platform.py"):
                (source_root / module_name).write_text("print('runtime candidate')\n", encoding="utf-8")
            prompts_dir = source_root / "prompts"
            bin_dir = source_root / "bin"
            mac_bin_dir = source_root / "mac" / "bin"
            go_dir = source_root / "go"
            memory_dir = source_root / "memory"
            app_dir = source_root / ".eve"
            log_dir = source_root / ".logs"
            for directory in (prompts_dir, bin_dir, mac_bin_dir, go_dir, memory_dir, app_dir, log_dir):
                directory.mkdir(parents=True)
            (app_dir / "config.json").write_text("{}\n", encoding="utf-8")
            epistemic_model_path = source_root / eve.EPISTEMIC_MODEL_ARTIFACT_NAME
            epistemic_event_manifest_path = source_root / eve.EPISTEMIC_EVENT_MANIFEST_NAME
            epistemic_model_path.write_text("{}\n", encoding="utf-8")
            epistemic_event_manifest_path.write_text("{}\n", encoding="utf-8")
            new_pkg = source_root / "eve_brandnew"
            new_pkg.mkdir()
            (new_pkg / "__init__.py").write_text("", encoding="utf-8")
            (new_pkg / "feature.py").write_text("VALUE = 42\n", encoding="utf-8")

            runtime_app_dir = runtime_root / ".eve"
            patches = {
                "ROOT": source_root,
                "PROMPTS_DIR": prompts_dir,
                "BIN_DIR": bin_dir,
                "MAC_BIN_DIR": mac_bin_dir,
                "GO_DIR": go_dir,
                "MEMORY_DIR": memory_dir,
                "APP_DIR": app_dir,
                "LOG_DIR": log_dir,
                "CONFIG_PATH": app_dir / "config.json",
                "PROJECT_MEMORY_PATH": source_root / "PROJECT_MEMORY.md",
                "EPISTEMIC_MODEL_PATH": epistemic_model_path,
                "EPISTEMIC_EVENT_MANIFEST_PATH": epistemic_event_manifest_path,
                "MEMORY_RETRIEVAL_LANCEDB_DIR": app_dir / "memory_retrieval.lancedb",
                "AUTONOMY_RUNS_DIR": app_dir / "autonomy_runs",
                "CODE_SESSIONS_DIR": app_dir / "code_sessions",
                "WHOLE_SYSTEM_EVALS_DIR": app_dir / "whole_system_evals",
                "MODEL_SUITABILITY_DIR": app_dir / "model_suitability",
                "MANUAL_PROBE_RUNS_DIR": app_dir / "manual_probe_runs",
                "HIDDEN_EVALUATOR_DIR": app_dir / "hidden_evaluator",
                "LONG_RUN_EVALS_DIR": app_dir / "long_run_evals",
                "RUNTIME_DIR": runtime_root,
                "RUNTIME_BIN_DIR": runtime_root / "bin",
                "RUNTIME_GO_DIR": runtime_root / "go",
                "RUNTIME_EVE_COMMANDS_DIR": runtime_root / "eve_commands",
                "RUNTIME_PROMPTS_DIR": runtime_root / "prompts",
                "RUNTIME_WEB_DIR": runtime_root / "web",
                "RUNTIME_MEMORY_DIR": runtime_root / "memory",
                "RUNTIME_PROJECT_MEMORY_PATH": runtime_root / "PROJECT_MEMORY.md",
                "RUNTIME_APP_DIR": runtime_app_dir,
                "RUNTIME_LOCK_DIR": runtime_app_dir / "locks",
                "RUNTIME_LOG_DIR": runtime_app_dir / "logs",
                "RUNTIME_CODE_SESSIONS_DIR": runtime_app_dir / "code_sessions",
                "RUNTIME_MANUAL_PROBE_RUNS_DIR": runtime_app_dir / "manual_probe_runs",
                "RUNTIME_HIDDEN_EVALUATOR_DIR": runtime_app_dir / "hidden_evaluator",
                "RUNTIME_HIDDEN_EVALUATOR_RUNS_DIR": runtime_app_dir / "hidden_evaluator" / "runs",
                "RUNTIME_LONG_RUN_EVALS_DIR": runtime_app_dir / "long_run_evals",
                "RUNTIME_LONG_RUN_EVAL_HISTORY_DIR": runtime_app_dir / "long_run_evals" / "history",
                "RUNTIME_MEMORY_RETRIEVAL_LANCEDB_DIR": runtime_app_dir / "memory_retrieval.lancedb",
                "RUNTIME_AUTONOMY_RUNS_DIR": runtime_app_dir / "autonomy_runs",
            }
            with ExitStack() as stack:
                for attr, value in patches.items():
                    stack.enter_context(patch.object(eve, attr, value))
                stack.enter_context(patch.object(eve, "daemon_runtime_running", return_value=False))
                stack.enter_context(patch.object(eve, "copy_runtime_bundle_data_file_preserving_newer_runtime"))
                stack.enter_context(patch.object(eve.eve_epistemic, "load_model", return_value={"ok": True}))
                stack.enter_context(
                    patch.object(eve.eve_epistemic, "load_event_manifest", return_value={"admission": {"status": "candidate"}})
                )
                stack.enter_context(patch.object(eve.eve_epistemic, "event_manifest_live_admitted", return_value=False))
                eve._sync_runtime_bundle_unlocked()

            synced_feature = runtime_root / "eve_brandnew" / "feature.py"
            self.assertEqual("VALUE = 42\n", synced_feature.read_text(encoding="utf-8"))
            self.assertFalse((runtime_root / eve.EPISTEMIC_EVENT_MANIFEST_NAME).exists())

    def test_runtime_sync_allows_missing_optional_epistemic_model(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "missing-model.json"
            runtime = root / "runtime"
            with patch.object(eve, "EPISTEMIC_MODEL_PATH", source), patch.object(
                eve, "RUNTIME_DIR", runtime
            ), patch.object(eve.eve_epistemic, "load_model") as load_model:
                result = eve.sync_optional_epistemic_model()

        self.assertEqual({"status": "not_installed", "copied": False}, result)
        load_model.assert_not_called()

    def test_runtime_sync_rejects_present_invalid_optional_epistemic_model(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "model.json"
            source.write_text("{}\n", encoding="utf-8")
            with patch.object(eve, "EPISTEMIC_MODEL_PATH", source), patch.object(
                eve.eve_epistemic, "load_model", return_value=None
            ):
                with self.assertRaisesRegex(RuntimeError, "is invalid"):
                    eve.sync_optional_epistemic_model()

    def test_runtime_openclaw_workspace_mirrors_static_files_but_preserves_lived_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "source"
            runtime_root = root / "runtime"
            source_workspace = source_root / "openclaw"
            runtime_workspace = runtime_root / "openclaw"
            (source_workspace / "skills" / "example").mkdir(parents=True)
            (source_workspace / "context").mkdir(parents=True)
            (source_workspace / "memory").mkdir(parents=True)
            (runtime_workspace / "context").mkdir(parents=True)
            (runtime_workspace / "memory").mkdir(parents=True)
            (source_workspace / "AGENTS.md").write_text("source doctrine\n", encoding="utf-8")
            (source_workspace / "skills" / "example" / "SKILL.md").write_text(
                "source skill\n", encoding="utf-8"
            )
            (source_workspace / "context" / "eve_status.json").write_text(
                '{"source": true}\n', encoding="utf-8"
            )
            (source_workspace / "memory" / "today.md").write_text(
                "source memory\n", encoding="utf-8"
            )
            (runtime_workspace / "context" / "eve_status.json").write_text(
                '{"runtime": true}\n', encoding="utf-8"
            )
            (runtime_workspace / "memory" / "today.md").write_text(
                "runtime memory\n", encoding="utf-8"
            )

            with patch.object(eve, "ROOT", source_root), patch.object(
                eve, "RUNTIME_DIR", runtime_root
            ):
                eve.sync_runtime_openclaw_workspace()

            self.assertEqual(
                "source doctrine\n",
                (runtime_workspace / "AGENTS.md").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                "source skill\n",
                (runtime_workspace / "skills" / "example" / "SKILL.md").read_text(
                    encoding="utf-8"
                ),
            )
            self.assertEqual(
                '{"runtime": true}\n',
                (runtime_workspace / "context" / "eve_status.json").read_text(
                    encoding="utf-8"
                ),
            )
            self.assertEqual(
                "runtime memory\n",
                (runtime_workspace / "memory" / "today.md").read_text(encoding="utf-8"),
            )

    def test_rejected_epistemic_event_candidate_is_not_runtime_drift(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_root = temp_path / "source"
            runtime_root = temp_path / "runtime"
            source_root.mkdir()
            runtime_root.mkdir()
            source_manifest = source_root / eve.EPISTEMIC_EVENT_MANIFEST_NAME
            source_manifest.write_text("{}\n", encoding="utf-8")
            (source_root / "eve.py").write_text("# same\n", encoding="utf-8")
            (runtime_root / "eve.py").write_text("# same\n", encoding="utf-8")

            with patch.object(eve, "ROOT", source_root), patch.object(
                eve, "RUNTIME_DIR", runtime_root
            ), patch.object(
                eve, "EPISTEMIC_MODEL_PATH", source_root / "missing-stable-model.json"
            ), patch.object(
                eve, "EPISTEMIC_EVENT_MANIFEST_PATH", source_manifest
            ), patch.object(
                eve.eve_epistemic,
                "load_event_manifest",
                return_value={"admission": {"status": "candidate"}},
            ), patch.object(
                eve.eve_epistemic, "event_manifest_live_admitted", return_value=False
            ):
                check = eve.runtime_source_truth_check(
                    include_daemon=False,
                    include_state_authority=False,
                )

        labels = {item["label"] for item in check["files"]}
        self.assertNotIn(eve.EPISTEMIC_EVENT_MANIFEST_NAME, labels)
        self.assertFalse(check["needs_runtime_sync"])
        deployment = check["epistemic_event_deployment"]
        self.assertEqual("source_candidate_isolated", deployment["status"])
        self.assertFalse(deployment["blocks_core_runtime_sync"])
        self.assertEqual("candidate", deployment["source"]["status"])
        self.assertFalse(deployment["source"]["live_admitted"])

    def test_promoted_epistemic_event_bundle_pairs_include_model_files_and_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_root = temp_path / "source"
            runtime_root = temp_path / "runtime"
            model_root = source_root / "models" / "epistemic" / "promoted"
            model_root.mkdir(parents=True)
            runtime_root.mkdir()
            (model_root / "config.json").write_text("{}\n", encoding="utf-8")
            (model_root / "model.safetensors").write_bytes(b"weights")
            source_manifest = source_root / eve.EPISTEMIC_EVENT_MANIFEST_NAME
            source_manifest.write_text("{}\n", encoding="utf-8")
            manifest = {
                "admission": {"status": "promoted"},
                "model_path": "models/epistemic/promoted",
                "model_files_sha256": {
                    "config.json": eve.file_sha256(model_root / "config.json"),
                    "model.safetensors": eve.file_sha256(model_root / "model.safetensors"),
                },
            }

            with patch.object(eve, "ROOT", source_root), patch.object(
                eve, "RUNTIME_DIR", runtime_root
            ), patch.object(
                eve, "EPISTEMIC_EVENT_MANIFEST_PATH", source_manifest
            ), patch.object(
                eve.eve_epistemic, "load_event_manifest", return_value=manifest
            ), patch.object(
                eve.eve_epistemic, "event_manifest_live_admitted", return_value=True
            ):
                pairs = eve.live_admitted_epistemic_event_bundle_pairs()

        self.assertEqual(
            {
                "models/epistemic/promoted/config.json",
                "models/epistemic/promoted/model.safetensors",
                eve.EPISTEMIC_EVENT_MANIFEST_NAME,
            },
            {label for label, _source, _runtime in pairs},
        )

    def test_promoted_epistemic_event_bundle_syncs_manifest_last_after_verified_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_root = temp_path / "source"
            runtime_root = temp_path / "runtime"
            source_model_root = source_root / "models" / "epistemic" / "promoted"
            source_worker = source_root / "bin" / "eve_epistemic_event_worker.py"
            runtime_worker = runtime_root / "bin" / "eve_epistemic_event_worker.py"
            source_model_root.mkdir(parents=True)
            source_worker.parent.mkdir(parents=True)
            runtime_worker.parent.mkdir(parents=True)
            (source_model_root / "config.json").write_text("{}\n", encoding="utf-8")
            (source_model_root / "model.safetensors").write_bytes(b"weights")
            source_worker.write_text("# worker\n", encoding="utf-8")
            runtime_worker.write_text("# worker\n", encoding="utf-8")
            source_manifest = source_root / eve.EPISTEMIC_EVENT_MANIFEST_NAME
            source_manifest.write_text('{"admission":"promoted"}\n', encoding="utf-8")
            manifest = {
                "admission": {"status": "promoted"},
                "artifact_sha256": "a" * 64,
                "model_path": "models/epistemic/promoted",
                "model_files_sha256": {
                    "config.json": eve.file_sha256(source_model_root / "config.json"),
                    "model.safetensors": eve.file_sha256(source_model_root / "model.safetensors"),
                },
                "runtime": {
                    "worker": "bin/eve_epistemic_event_worker.py",
                    "worker_sha256": eve.file_sha256(source_worker),
                },
            }

            with patch.object(eve, "ROOT", source_root), patch.object(
                eve, "RUNTIME_DIR", runtime_root
            ), patch.object(
                eve, "EPISTEMIC_EVENT_MANIFEST_PATH", source_manifest
            ), patch.object(
                eve.eve_epistemic, "load_event_manifest", return_value=manifest
            ), patch.object(
                eve.eve_epistemic, "event_manifest_live_admitted", return_value=True
            ):
                result = eve.sync_live_admitted_epistemic_event_bundle()

            self.assertEqual("live_admitted_bundle_synced", result["status"])
            self.assertEqual(
                b"weights",
                (runtime_root / "models" / "epistemic" / "promoted" / "model.safetensors").read_bytes(),
            )
            self.assertEqual(
                source_manifest.read_bytes(),
                (runtime_root / eve.EPISTEMIC_EVENT_MANIFEST_NAME).read_bytes(),
            )

    def test_runtime_sync_refuses_unpromoted_typed_event_candidate(self):
        path = Path("/tmp/eve-source/eve_epistemic_event_v1.json")
        with patch.object(
            eve.eve_epistemic,
            "load_event_manifest",
            return_value={"admission": {"status": "candidate"}},
        ), patch.object(
            eve.eve_epistemic, "event_manifest_live_admitted", return_value=False
        ):
            with self.assertRaisesRegex(RuntimeError, "candidate without a passing private causal promotion receipt"):
                eve.require_live_admitted_epistemic_event_manifest(path)

    def test_copy_runtime_bundle_file_refuses_invalid_python_over_existing_runtime(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "source" / "eve.py"
            destination = temp_path / "runtime" / "eve.py"
            source.parent.mkdir()
            destination.parent.mkdir()
            source.write_text("def broken(:\n", encoding="utf-8")
            destination.write_text("print('known-good runtime')\n", encoding="utf-8")

            with patch.object(eve.sys, "stderr", new=io.StringIO()):
                replaced = eve.copy_runtime_bundle_file(source, destination)

            self.assertFalse(replaced)
            self.assertEqual("print('known-good runtime')\n", destination.read_text(encoding="utf-8"))
            self.assertEqual([], list(destination.parent.glob(".eve.py.tmp*")))

    def test_copy_runtime_bundle_file_refuses_source_that_changes_during_copy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "source" / "eve.py"
            destination = temp_path / "runtime" / "eve.py"
            source.parent.mkdir()
            destination.parent.mkdir()
            source.write_text("print('unstable source')\n", encoding="utf-8")
            destination.write_text("print('known-good runtime')\n", encoding="utf-8")

            with patch.object(
                eve,
                "runtime_bundle_source_signature",
                side_effect=[(1, 10), (99, 99), (1, 10), (2, 20)],
            ), patch.object(
                eve.sys, "stderr", new=io.StringIO()
            ):
                replaced = eve.copy_runtime_bundle_file(source, destination)

            self.assertFalse(replaced)
            self.assertEqual("print('known-good runtime')\n", destination.read_text(encoding="utf-8"))
            self.assertEqual([], list(destination.parent.glob(".eve.py.tmp*")))

    def test_copy_runtime_bundle_file_replaces_with_valid_python(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "source" / "eve.py"
            destination = temp_path / "runtime" / "eve.py"
            source.parent.mkdir()
            destination.parent.mkdir()
            source.write_text("print('fresh runtime')\n", encoding="utf-8")
            destination.write_text("print('old runtime')\n", encoding="utf-8")

            replaced = eve.copy_runtime_bundle_file(source, destination)

            self.assertTrue(replaced)
            self.assertEqual("print('fresh runtime')\n", destination.read_text(encoding="utf-8"))
            self.assertEqual([], list(destination.parent.glob(".eve.py.tmp*")))

    def test_cmd_daemon_run_refreshes_long_running_process_metadata(self):
        class Args:
            once = False
            force = False
            sleep_seconds = 0

        state = {"daemon_started_at": "2026-04-20T22:38:54+00:00"}
        with patch.object(eve, "load_config", return_value={"loop_sleep_seconds": 1}), patch.object(
            eve, "load_state", return_value=state
        ), patch.object(eve, "save_state") as save_state, patch.object(
            eve, "run_daemon_cycle", return_value=[]
        ), patch.object(
            eve.time, "sleep", side_effect=KeyboardInterrupt
        ), patch.object(
            eve, "append_entry"
        ), patch.object(
            eve, "write_operator_power_state"
        ):
            result = eve.cmd_daemon_run(Args())

        self.assertEqual(0, result)
        saved_state = save_state.call_args_list[0].args[0]
        self.assertNotEqual("2026-04-20T22:38:54+00:00", saved_state["daemon_started_at"])
        self.assertEqual(saved_state["daemon_process_id"], eve.os.getpid())
        self.assertTrue(saved_state["daemon_code_path"].endswith("eve.py"))
        self.assertIn("T", saved_state["daemon_code_mtime"])

    def test_doctor_runtime_state_with_recent_entries_prefers_fresher_entry_timestamps(self):
        state = {
            "last_loop_at": "2026-04-22T23:24:31+00:00",
            "last_thought_at": "2026-04-22T23:24:31+00:00",
            "last_heartbeat_at": "2026-04-22T23:24:31+00:00",
        }
        entries = [
            {"kind": "thought", "timestamp": "2026-04-23T19:24:14+00:00"},
            {"kind": "heartbeat", "timestamp": "2026-04-23T19:24:44+00:00"},
            {"kind": "mind_tick", "timestamp": "2026-04-23T19:24:45+00:00"},
        ]
        with patch.object(eve, "resolve_store_read_path", return_value=Path("/tmp/entries.jsonl")), patch.object(
            Path, "exists", return_value=True
        ), patch.object(eve, "read_jsonl_tail_records", return_value=entries), patch.object(
            eve, "read_jsonl_records", return_value=entries
        ):
            hydrated = eve.doctor_runtime_state_with_recent_entries(state, prefer_runtime=True)
        self.assertEqual("2026-04-23T19:24:14+00:00", hydrated["last_thought_at"])
        self.assertEqual("2026-04-23T19:24:44+00:00", hydrated["last_heartbeat_at"])
        self.assertEqual("2026-04-23T19:24:45+00:00", hydrated["last_loop_at"])

    def test_runtime_truth_reports_live_runtime_mirror_lag_without_failing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_app = temp_path / "source" / ".eve"
            runtime_app = temp_path / "runtime" / ".eve"
            source_app.mkdir(parents=True)
            runtime_app.mkdir(parents=True)
            source_code = temp_path / "source" / "eve.py"
            runtime_code = temp_path / "runtime" / "eve.py"
            source_code.write_text("print('same')\n", encoding="utf-8")
            runtime_code.write_text("print('same')\n", encoding="utf-8")
            source_state = source_app / "state.json"
            runtime_state = runtime_app / "state.json"
            source_state.write_text('{"state":"source"}\n', encoding="utf-8")
            runtime_state.write_text('{"state":"runtime"}\n', encoding="utf-8")
            catalog = [
                {
                    "id": "state",
                    "path": source_state,
                    "authority": eve.STATE_AUTHORITY_RUNTIME_OWNED,
                    "contract": "test state",
                }
            ]

            with patch.object(eve, "APP_DIR", source_app), patch.object(
                eve, "RUNTIME_APP_DIR", runtime_app
            ), patch.object(eve, "daemon_runtime_running", return_value=True):
                check = eve.runtime_source_truth_check(
                    pairs=[("eve.py", source_code, runtime_code)],
                    state_catalog=catalog,
                )

        self.assertEqual("ok", check["status"])
        self.assertFalse(check["needs_runtime_sync"])
        self.assertFalse(check["needs_state_reconcile"])
        self.assertTrue(check["state_reconcile_available"])
        self.assertEqual("live_mirror_lag", check["state_authority"]["status"])
        self.assertEqual(1, check["state_authority"]["mirror_lag_count"])
        record = check["state_authority"]["records"][0]
        self.assertEqual("runtime", record["authoritative_side"])
        self.assertEqual("source", record["mirror_side"])
        self.assertTrue(record["mirror_lag"])
        self.assertFalse(record["blocks_truth"])

    def test_offline_runtime_owned_state_preserves_newest_persisted_copy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_app = temp_path / "source" / ".eve"
            runtime_app = temp_path / "runtime" / ".eve"
            source_app.mkdir(parents=True)
            runtime_app.mkdir(parents=True)
            source_state = source_app / "state.json"
            runtime_state = runtime_app / "state.json"
            source_state.write_text('{"state":"older-source"}\n', encoding="utf-8")
            runtime_state.write_text('{"state":"newer-runtime"}\n', encoding="utf-8")
            os.utime(source_state, (1_700_000_000, 1_700_000_000))
            os.utime(runtime_state, (1_800_000_000, 1_800_000_000))
            catalog = [
                {
                    "id": "state",
                    "path": source_state,
                    "authority": eve.STATE_AUTHORITY_RUNTIME_OWNED,
                    "contract": "test state",
                }
            ]

            with patch.object(eve, "APP_DIR", source_app), patch.object(
                eve, "RUNTIME_APP_DIR", runtime_app
            ), patch.object(eve, "daemon_runtime_running", return_value=False):
                authority = eve.runtime_state_authority_records(catalog)
                result = eve.reconcile_runtime_state_authority(catalog=catalog, apply=True)

            record = authority["records"][0]
            self.assertEqual("offline_recovery_lag", authority["status"])
            self.assertEqual("runtime", record["authoritative_side"])
            self.assertEqual("offline_newest_persisted_runtime", record["selection_reason"])
            self.assertTrue(record["offline_recovery_lag"])
            self.assertFalse(record["blocks_truth"])
            self.assertEqual(1, result["applied_count"])
            self.assertEqual(runtime_state.read_text(encoding="utf-8"), source_state.read_text(encoding="utf-8"))

    def test_offline_runtime_preferred_state_honors_newer_source_restore(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_app = temp_path / "source" / ".eve"
            runtime_app = temp_path / "runtime" / ".eve"
            source_app.mkdir(parents=True)
            runtime_app.mkdir(parents=True)
            source_state = source_app / "human_context.json"
            runtime_state = runtime_app / "human_context.json"
            source_state.write_text('{"state":"newer-source"}\n', encoding="utf-8")
            runtime_state.write_text('{"state":"older-runtime"}\n', encoding="utf-8")
            os.utime(runtime_state, (1_700_000_000, 1_700_000_000))
            os.utime(source_state, (1_800_000_000, 1_800_000_000))
            catalog = [
                {
                    "id": "human_context",
                    "path": source_state,
                    "authority": eve.STATE_AUTHORITY_RUNTIME_PREFERRED_MIRROR,
                    "contract": "test human context",
                }
            ]

            with patch.object(eve, "APP_DIR", source_app), patch.object(
                eve, "RUNTIME_APP_DIR", runtime_app
            ), patch.object(eve, "daemon_runtime_running", return_value=False):
                authority = eve.runtime_state_authority_records(catalog)

            record = authority["records"][0]
            self.assertEqual("source", record["authoritative_side"])
            self.assertEqual("offline_newest_persisted_source", record["selection_reason"])

    def test_runtime_truth_reports_blocking_state_authority_mismatch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_app = temp_path / "source" / ".eve"
            runtime_app = temp_path / "runtime" / ".eve"
            source_app.mkdir(parents=True)
            runtime_app.mkdir(parents=True)
            source_code = temp_path / "source" / "eve.py"
            runtime_code = temp_path / "runtime" / "eve.py"
            source_code.write_text("print('same')\n", encoding="utf-8")
            runtime_code.write_text("print('same')\n", encoding="utf-8")
            source_state = source_app / "config.json"
            runtime_state = runtime_app / "config.json"
            source_state.write_text('{"state":"source"}\n', encoding="utf-8")
            runtime_state.write_text('{"state":"runtime"}\n', encoding="utf-8")
            catalog = [
                {
                    "id": "config",
                    "path": source_state,
                    "authority": eve.STATE_AUTHORITY_SOURCE_OWNED,
                    "contract": "test config",
                }
            ]

            with patch.object(eve, "APP_DIR", source_app), patch.object(
                eve, "RUNTIME_APP_DIR", runtime_app
            ), patch.object(eve, "daemon_runtime_running", return_value=True):
                check = eve.runtime_source_truth_check(
                    pairs=[("eve.py", source_code, runtime_code)],
                    state_catalog=catalog,
                )

        self.assertEqual("state_authority_mismatch", check["status"])
        self.assertTrue(check["needs_state_reconcile"])
        record = check["state_authority"]["records"][0]
        self.assertEqual("source", record["authoritative_side"])
        self.assertEqual("runtime", record["mirror_side"])
        self.assertTrue(record["blocks_truth"])

    def test_runtime_reconcile_copies_authoritative_runtime_state_to_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_app = temp_path / "source" / ".eve"
            runtime_app = temp_path / "runtime" / ".eve"
            source_app.mkdir(parents=True)
            runtime_app.mkdir(parents=True)
            source_state = source_app / "state.json"
            runtime_state = runtime_app / "state.json"
            source_state.write_text('{"state":"source"}\n', encoding="utf-8")
            runtime_state.write_text('{"state":"runtime"}\n', encoding="utf-8")
            catalog = [
                {
                    "id": "state",
                    "path": source_state,
                    "authority": eve.STATE_AUTHORITY_RUNTIME_OWNED,
                    "contract": "test state",
                }
            ]

            with patch.object(eve, "APP_DIR", source_app), patch.object(
                eve, "RUNTIME_APP_DIR", runtime_app
            ), patch.object(eve, "daemon_runtime_running", return_value=True):
                result = eve.reconcile_runtime_state_authority(catalog=catalog, apply=True)

            self.assertEqual(1, result["applied_count"])
            self.assertEqual(runtime_state.read_text(encoding="utf-8"), source_state.read_text(encoding="utf-8"))

    def test_doctor_quick_skips_deep_probe_setup(self):
        class Args:
            json = False
            quick = True

        check = {
            "status": "ok",
            "daemon_runtime_running": False,
            "needs_runtime_sync": False,
            "needs_state_reconcile": False,
            "files": [],
            "state_authority": {"status": "ok", "reconcile_count": 0, "records": []},
        }
        with patch.object(eve, "runtime_source_truth_check", return_value=check), patch.object(
            eve, "load_config"
        ) as load_config, patch.object(eve.sys, "stdout", new=io.StringIO()) as stdout:
            result = eve.cmd_doctor(Args())

        self.assertEqual(0, result)
        load_config.assert_not_called()
        self.assertIn("Quick doctor only checks", stdout.getvalue())

    def test_test_metadata_guard_detects_fixture_leak(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "entries.jsonl"
            path.write_text(
                '{"id":"1","kind":"safe","metadata":{"source":"manual_test"}}\n'
                '{"id":"2","kind":"leak","metadata":{"source":"test"}}\n',
                encoding="utf-8",
            )

            report = eve.scan_test_metadata_leaks(paths=[path])

        self.assertEqual("failed", report["status"])
        self.assertEqual(1, report["leak_count"])
        self.assertEqual("2", report["examples"][0]["id"])

    def test_test_metadata_quarantine_preserves_record_without_live_test_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "entries.jsonl"
            path.write_text(
                '{"id":"1","kind":"safe","metadata":{"source":"manual_test"}}\n'
                '{"id":"2","kind":"leak","source":"test","metadata":{"source":"test"}}\n',
                encoding="utf-8",
            )

            quarantine = eve.quarantine_test_metadata_leaks(paths=[path])
            report = eve.scan_test_metadata_leaks(paths=[path])
            records = eve.eve_store.read_jsonl_records(path)

        self.assertEqual(1, quarantine["quarantined_count"])
        self.assertEqual("ok", report["status"])
        self.assertEqual("historical_test_quarantined", records[1]["source"])
        self.assertEqual("historical_test_quarantined", records[1]["metadata"]["source"])
        self.assertEqual("test", records[1]["metadata"]["original_source"])
        self.assertEqual("test", records[1]["metadata"]["original_metadata_source"])

    def test_run_local_command_missing_binary_fails_soft(self):
        result = eve.run_local_command(["definitely-not-a-real-command"], timeout=1)
        self.assertEqual(127, result.returncode)
        self.assertTrue(result.stderr)

    def test_run_launchctl_allow_failure_returns_stub_when_not_macos(self):
        with patch.object(eve_platform, "is_macos", return_value=False):
            result = eve.run_launchctl(["print", "whatever"], allow_failure=True)
        self.assertIsInstance(result, subprocess.CompletedProcess)
        self.assertEqual(127, result.returncode)
        self.assertIn("launchctl", result.stderr)

    def test_llama_cpp_binary_path_for_profile_prefers_profile_specific_then_global(self):
        config = {
            "llama_cpp_binary_path": "/global/llama-server",
            "planner_llama_cpp_binary_path": "/planner/llama-server",
        }
        self.assertEqual("/global/llama-server", eve.llama_cpp_binary_path_for_profile(config, "fast"))
        self.assertEqual("/global/llama-server", eve.llama_cpp_binary_path_for_profile(config, "observer"))
        self.assertEqual("/planner/llama-server", eve.llama_cpp_binary_path_for_profile(config, "planner"))

    def test_parse_llama_cpp_version_output_extracts_version_line(self):
        output = "\n".join(
            [
                "ggml_metal_device_init: GPU name: MTL0",
                "version: 8946 (0f1bb602d)",
                "built with AppleClang for Darwin arm64",
            ]
        )
        self.assertEqual("8946 (0f1bb602d)", eve.parse_llama_cpp_version_output(output))

    def test_llama_cpp_version_probe_uses_bounded_read_fallback_when_server_hangs(self):
        def fake_component_command(cmd, timeout):
            if cmd == ["/opt/homebrew/bin/llama-server", "--version"]:
                return None, "Command timed out after 2s: /opt/homebrew/bin/llama-server --version"
            return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="unexpected command"), ""

        with patch.object(eve, "run_component_command", side_effect=fake_component_command), patch.object(
            eve,
            "read_bounded_llama_cpp_version_output",
            return_value=("version: 9200 (3e12fbdea)\nbuilt with AppleClang for arm64", ""),
        ):
            probe = eve.llama_cpp_server_version_probe("/opt/homebrew/bin/llama-server", timeout=2)

        self.assertTrue(probe["ok"])
        self.assertEqual("9200 (3e12fbdea)", probe["version"])
        self.assertEqual("bounded_read_fallback", probe["probe_note"])

    def test_build_daemon_systemd_service_text_contains_runtime_exec(self):
        with patch.object(eve, "sync_runtime_bundle"), patch.object(eve, "RUNTIME_DIR", Path("/tmp/eve-runtime")), patch.object(
            eve, "RUNTIME_SCRIPT_PATH", Path("/tmp/eve-runtime/eve.py")
        ):
            text = eve.build_daemon_systemd_service_text()
        self.assertIn("Description=Eve daemon", text)
        self.assertIn("WorkingDirectory=/tmp/eve-runtime", text)
        self.assertIn("ExecStart=", text)
        self.assertIn("/tmp/eve-runtime/eve.py daemon run", text)

    def test_build_model_watchdog_systemd_timer_text_uses_config_interval(self):
        with patch.object(eve, "load_config", return_value={"model_watchdog_interval_seconds": 420}):
            text = eve.build_model_watchdog_systemd_timer_text()
        self.assertIn("OnUnitActiveSec=420s", text)

    def test_build_daemon_windows_task_text_contains_runtime_exec(self):
        with patch.object(eve, "sync_runtime_bundle"), patch.object(eve, "RUNTIME_DIR", Path(r"C:\Eve\runtime")), patch.object(
            eve, "RUNTIME_SCRIPT_PATH", Path(r"C:\Eve\runtime\eve.py")
        ), patch.object(eve, "sys") as fake_sys:
            fake_sys.executable = r"C:\Python39\python.exe"
            text = eve.build_daemon_windows_task_text()
        self.assertIn("<LogonTrigger>", text)
        self.assertIn(r"C:\Python39\python.exe", text)
        self.assertIn(r"C:\Eve\runtime\eve.py", text)

    def test_build_model_watchdog_windows_task_text_uses_interval(self):
        with patch.object(eve, "sync_runtime_bundle"), patch.object(
            eve, "RUNTIME_MODEL_WATCHDOG_SCRIPT_PATH", Path(r"C:\Eve\runtime\bin\eve_model_watchdog.py")
        ), patch.object(eve, "RUNTIME_DIR", Path(r"C:\Eve\runtime")), patch.object(eve, "load_config", return_value={"model_watchdog_interval_seconds": 420}), patch.object(
            eve, "sys"
        ) as fake_sys:
            fake_sys.executable = r"C:\Python39\python.exe"
            text = eve.build_model_watchdog_windows_task_text()
        self.assertIn("<TimeTrigger>", text)
        self.assertIn("PT7M", text)
        self.assertIn(r"C:\Eve\runtime\bin\eve_model_watchdog.py", text)

    def test_run_schtasks_allow_failure_returns_stub_when_not_windows(self):
        with patch.object(eve_platform, "is_windows", return_value=False):
            result = eve.run_schtasks(["/Query"], allow_failure=True)
        self.assertIsInstance(result, subprocess.CompletedProcess)
        self.assertEqual(127, result.returncode)
        self.assertIn("schtasks", result.stderr)


if __name__ == "__main__":
    unittest.main()
