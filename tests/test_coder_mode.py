import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import eve


class EveCoderModeTests(unittest.TestCase):
    def test_coder_command_blocks_destructive_commands(self):
        result = eve.run_coder_shell_command("rm -rf .", eve.DEFAULT_CONFIG, timeout_seconds=1)

        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked"])
        self.assertIn("deletion", result["error"])

    def test_coder_command_blocks_clawkeeper_style_disk_wipe(self):
        result = eve.run_coder_shell_command("dd if=/dev/zero of=/dev/disk9 bs=1m", eve.DEFAULT_CONFIG, timeout_seconds=1)

        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked"])
        self.assertIn("raw disk write", result["error"])

    def test_coder_command_blocks_protected_secret_paths(self):
        result = eve.run_coder_shell_command("cat ~/.ssh/id_rsa", eve.DEFAULT_CONFIG, timeout_seconds=1)

        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked"])
        self.assertIn("SSH keys", result["error"])

    def test_code_commitment_is_supported_action(self):
        self.assertEqual(
            "code_change",
            eve.classify_supported_reply_commitment("I will patch the code and run the tests."),
        )
        self.assertIn("code_change", eve.supported_commitment_action_descriptions())

    def test_codex_handoff_commitment_is_supported_action(self):
        self.assertEqual(
            "codex_independent_handoff",
            eve.classify_supported_reply_commitment("I will ask Codex for a bounded review."),
        )
        self.assertTrue(
            eve.reply_current_turn_supports_action(
                "codex_independent_handoff",
                "Ask Codex to audit this repo and report evidence.",
            )
        )
        self.assertIn("codex_independent_handoff", eve.supported_commitment_action_descriptions())

    def test_codex_handoff_builds_bounded_bridge_message(self):
        fake_message = {"id": "msg-codex-1", "thread_id": "thread-codex-1"}
        config = {
            **eve.DEFAULT_CONFIG,
            "_codex_handoff_objective": "Audit the model scout docs and return evidence.",
            "_codex_handoff_acceptance": "Return changed files, commands run, and residual risks.",
        }

        with patch.object(eve, "create_message", return_value=fake_message) as create_message, patch.object(
            eve, "append_entry", lambda *args, **kwargs: {}
        ):
            result = eve.run_bounded_codex_independent_handoff(config, source="test")

        self.assertTrue(result["ok"], result)
        self.assertEqual("msg-codex-1", result["message_id"])
        kwargs = create_message.call_args.kwargs
        self.assertEqual("eve", kwargs["sender"])
        self.assertEqual(eve.CODEX_PARTICIPANT, kwargs["recipient"])
        self.assertEqual("codex_bridge", kwargs["kind"])
        self.assertIn("Codex is a separate builder-supervisor/operator", kwargs["body"])
        self.assertIn("Return changed files, commands run, and residual risks.", kwargs["body"])
        self.assertEqual("independent_operator", kwargs["metadata"]["handoff_type"])
        self.assertEqual("eve_codex_independent_operator", kwargs["metadata"]["skill"])

    def test_codex_handoff_is_permission_gated_system_boundary(self):
        boundary = eve.operational_action_privacy_boundary("codex_independent_handoff")

        self.assertEqual("system_mutation", boundary["privacy_tier"])
        self.assertEqual("yes", boundary["requires_specific_approval"])
        self.assertIn("Codex", boundary["privacy_label"])

    def test_coder_patch_rejects_runtime_state_edits(self):
        patch_text = """diff --git a/.eve/config.json b/.eve/config.json
--- a/.eve/config.json
+++ b/.eve/config.json
@@ -1 +1 @@
-{}
+{"blocked": true}
"""

        ok, problem, paths = eve.validate_coder_patch(patch_text, eve.DEFAULT_CONFIG)

        self.assertFalse(ok)
        self.assertIn(".eve", problem)
        self.assertEqual([".eve/config.json"], paths)

    def test_coder_apply_patch_creates_file_inside_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True, text=True)
            patch_text = """diff --git a/hello.txt b/hello.txt
new file mode 100644
index 0000000..1269488
--- /dev/null
+++ b/hello.txt
@@ -0,0 +1 @@
+hello coder
"""

            with patch.object(eve, "ROOT", root):
                result = eve.execute_coder_apply_patch_tool({"patch": patch_text}, eve.DEFAULT_CONFIG)

            self.assertTrue(result["ok"], result)
            self.assertEqual(["hello.txt"], result["paths"])
            self.assertEqual("hello coder\n", (root / "hello.txt").read_text(encoding="utf-8"))

    def test_coder_apply_patch_can_be_disabled_for_autonomy(self):
        result = eve.execute_coder_tool(
            "apply_patch",
            {"patch": "diff --git a/hello.txt b/hello.txt\n--- a/hello.txt\n+++ b/hello.txt\n@@ -1 +1 @@\n-old\n+new\n"},
            {**eve.DEFAULT_CONFIG, "_coder_disable_apply_patch": True},
        )

        self.assertFalse(result["ok"])
        self.assertTrue(result["blocked"])
        self.assertIn("disabled", result["error"])

    def test_coder_tools_can_use_configured_workspace_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "marker.txt").write_text("configured root\n", encoding="utf-8")
            config = {**eve.DEFAULT_CONFIG, "code_workspace_root": str(root)}

            command_result = eve.run_coder_shell_command("pwd", config, timeout_seconds=5)
            list_result = eve.execute_coder_tool("list_dir", {"path": ".", "limit": 5}, config)

        resolved_root = str(root.resolve())
        self.assertEqual(resolved_root, command_result["cwd"])
        self.assertEqual(resolved_root, command_result["stdout"].strip())
        self.assertEqual(resolved_root, list_result["path"])
        self.assertIn("marker.txt", [item["name"] for item in list_result["items"]])

    def test_autonomy_coder_uses_runtime_root_from_runtime_bundle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir)
            (runtime_root / "eve.py").write_text("print('runtime')\n", encoding="utf-8")
            document_root = runtime_root / "Documents" / "Eve"
            document_root.mkdir(parents=True)
            config = {**eve.DEFAULT_CONFIG, "code_workspace_root": str(document_root)}

            with patch.object(eve, "ROOT", runtime_root), patch.object(eve, "running_from_runtime_bundle", return_value=True):
                bounded = eve.autonomy_coder_tryout_config(config)

        self.assertEqual(str(runtime_root.resolve()), bounded["code_workspace_root"])

    def test_runtime_bundle_skips_unchanged_dataless_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.md"
            destination = root / "runtime" / "source.md"
            source.write_text("prompt\n", encoding="utf-8")
            destination.parent.mkdir()
            destination.write_text("prompt\n", encoding="utf-8")

            with patch.object(eve, "runtime_bundle_file_is_dataless", return_value=True), patch.object(
                eve, "runtime_bundle_destination_matches_source_metadata", return_value=True
            ), patch.object(eve.shutil, "copy2", side_effect=AssertionError("copy2 should not hydrate dataless files")):
                copied = eve.copy_runtime_bundle_file(source, destination)

        self.assertFalse(copied)

    def test_runtime_bundle_refuses_changed_dataless_source_without_hydrating(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.md"
            destination = root / "runtime" / "source.md"
            source.write_text("new prompt\n", encoding="utf-8")
            destination.parent.mkdir()
            destination.write_text("old prompt\n", encoding="utf-8")

            with patch.object(eve, "runtime_bundle_file_is_dataless", return_value=True), patch.object(
                eve, "runtime_bundle_destination_matches_source_metadata", return_value=False
            ), patch.object(eve.shutil, "copy2", side_effect=AssertionError("copy2 should not hydrate dataless files")):
                copied = eve.copy_runtime_bundle_file(source, destination)

        self.assertFalse(copied)

    def test_runtime_bundle_tree_uses_guarded_file_copy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "source"
            destination_dir = root / "runtime"
            source_dir.mkdir()
            (source_dir / "item.txt").write_text("safe\n", encoding="utf-8")

            with patch.object(eve, "copy_runtime_bundle_file") as guarded_copy, patch.object(
                eve.shutil, "copytree", side_effect=AssertionError("copytree bypasses runtime sync safeguards")
            ):
                eve.copy_runtime_bundle_tree(source_dir, destination_dir)

        guarded_copy.assert_called_once_with(source_dir / "item.txt", destination_dir / "item.txt")

    def test_runtime_sync_skips_state_authority_truth_scan(self):
        check = {
            "status": "ok",
            "daemon_runtime_running": True,
            "needs_runtime_sync": False,
            "files": [],
            "state_authority": {"status": "skipped", "records": []},
        }
        with patch.object(eve, "sync_runtime_bundle") as sync_runtime_bundle, patch.object(
            eve,
            "reload_active_runtime_code_services_after_sync",
            return_value=[{"label": eve.CHAT_BACKEND_LABEL, "status": "reloaded", "reloaded": True}],
        ) as reload_services, patch.object(
            eve, "runtime_source_truth_check", return_value=check
        ) as runtime_source_truth_check, patch("builtins.print"):
            status = eve.cmd_runtime_sync(object())

        self.assertEqual(0, status)
        sync_runtime_bundle.assert_called_once_with()
        reload_services.assert_called_once_with()
        runtime_source_truth_check.assert_called_once_with(include_daemon=True, include_state_authority=False)

    def test_runtime_sync_reloads_active_daemon_and_chat_backend_on_macos(self):
        completed = lambda args, code=0: subprocess.CompletedProcess(args, code, stdout="ok", stderr="")
        results = [
            completed(["launchctl", "print"]),
            completed(["launchctl", "kickstart"]),
            completed(["launchctl", "print"]),
            completed(["launchctl", "print"]),
            completed(["launchctl", "kickstart"]),
            completed(["launchctl", "print"]),
        ]
        with patch.object(eve.eve_platform, "is_macos", return_value=True), patch.object(
            eve, "launchctl_domain", return_value="gui/501"
        ), patch.object(eve, "run_launchctl", side_effect=results) as run_launchctl:
            reloaded = eve.reload_active_runtime_code_services_after_sync()

        self.assertEqual(
            [eve.LAUNCH_AGENT_LABEL, eve.CHAT_BACKEND_LABEL],
            [item["label"] for item in reloaded],
        )
        self.assertTrue(all(item["reloaded"] for item in reloaded))
        self.assertEqual(
            [
                ["print", f"gui/501/{eve.LAUNCH_AGENT_LABEL}"],
                ["kickstart", "-k", f"gui/501/{eve.LAUNCH_AGENT_LABEL}"],
                ["print", f"gui/501/{eve.LAUNCH_AGENT_LABEL}"],
                ["print", f"gui/501/{eve.CHAT_BACKEND_LABEL}"],
                ["kickstart", "-k", f"gui/501/{eve.CHAT_BACKEND_LABEL}"],
                ["print", f"gui/501/{eve.CHAT_BACKEND_LABEL}"],
            ],
            [call.args[0] for call in run_launchctl.call_args_list],
        )

    def test_autonomy_summary_reader_limits_hot_path_file_reads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index in range(80):
                path = root / f"run-{index:02d}.summary.json"
                path.write_text("{}", encoding="utf-8")
                os.utime(path, (index, index))

            read_paths = []

            def fake_load_json(path, default=None):
                read_paths.append(Path(path))
                index = int(Path(path).stem.split("-")[-1].split(".")[0])
                return {
                    "run_id": f"run-{index:02d}",
                    "finished_at": f"2026-04-29T00:{index:02d}:00+00:00",
                }

            with patch.object(eve, "autonomy_runs_read_dir", return_value=root), patch.object(
                eve.eve_store, "load_json_dict", side_effect=fake_load_json
            ), patch.object(eve, "runtime_bundle_file_is_dataless", return_value=False):
                records = eve.read_autonomy_run_summaries(limit=5)

        self.assertEqual(5, len(records))
        self.assertLessEqual(len(read_paths), 40)
        self.assertEqual("run-79", records[0]["run_id"])

    def test_autonomy_free_run_delegates_to_runtime_bundle(self):
        args = SimpleNamespace(
            minutes=3,
            sample_seconds=20,
            max_actions=8,
            id="free-run-test",
            style="explorer",
        )
        with patch.object(eve, "delegate_cli_to_runtime", return_value=7) as delegate, patch.object(
            eve, "run_autonomy_free_run_session", side_effect=AssertionError("should delegate to runtime")
        ):
            status = eve.cmd_autonomy_free_run(args)

        self.assertEqual(7, status)
        delegated_args = delegate.call_args.args[0]
        self.assertEqual(["autonomy", "free-run"], delegated_args[:2])
        self.assertIn("--max-actions", delegated_args)
        self.assertIn("free-run-test", delegated_args)
        self.assertGreaterEqual(delegate.call_args.kwargs["timeout_seconds"], 480)

    def test_autonomous_coder_tryout_falls_back_to_deterministic_tools(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "eve.py").write_text("def cmd_chat(args):\n    return 0\n", encoding="utf-8")
            code_dir = root / "code_sessions"
            config = {
                **eve.DEFAULT_CONFIG,
                "code_workspace_root": str(root),
                "autonomy_coder_deterministic_fallback_enabled": True,
            }
            with patch.object(eve, "CODE_SESSIONS_DIR", code_dir), patch.object(
                eve, "run_eve_coder_agent", side_effect=SystemExit("model unavailable")
            ), patch.object(eve, "ensure_store", lambda: None):
                result = eve.run_bounded_autonomous_coder_tryout(config, source="test", timeout_seconds=30)

        self.assertTrue(result["ok"], result)
        self.assertEqual("coder_mode_probe", result["variant"])
        self.assertIn("git_status", result["tools_used"])
        self.assertIn("search_text", result["tools_used"])
        self.assertTrue(result["verification_used"])

    def test_workspace_feature_probe_uses_required_tools_without_model(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "eve.py").write_text("def run_bounded_capability_tryout():\n    pass\n", encoding="utf-8")
            with patch.object(eve, "ROOT", root):
                result = eve.run_bounded_workspace_feature_probe(eve.DEFAULT_CONFIG, source="test", timeout_seconds=30)

        self.assertTrue(result["ok"], result)
        self.assertEqual("workspace_feature_probe", result["variant"])
        self.assertEqual(["list_dir", "search_text", "read_file"], result["tools_used"])

    def test_code_session_event_log_is_jsonl(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            code_dir = Path(temp_dir) / "code_sessions"
            with patch.object(eve, "CODE_SESSIONS_DIR", code_dir), patch.object(eve, "ensure_store", lambda: None):
                event = eve.append_code_session_event("session one", "user_request", {"request": "fix it"})
                events = eve.read_code_session_events("session one")

        self.assertEqual("user_request", event["type"])
        self.assertEqual(1, len(events))
        self.assertEqual("fix it", events[0]["request"])

    def test_code_session_event_log_truncates_large_payloads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            code_dir = Path(temp_dir) / "code_sessions"
            with patch.object(eve, "CODE_SESSIONS_DIR", code_dir), patch.object(
                eve, "CODE_SESSION_EVENT_STRING_MAX_CHARS", 80
            ), patch.object(eve, "CODE_SESSION_EVENT_CONTAINER_MAX_ITEMS", 3), patch.object(
                eve, "ensure_store", lambda: None
            ):
                event = eve.append_code_session_event(
                    "large-payload",
                    "tool_call",
                    {
                        "result": {
                            "stdout": "x" * 500,
                            "items": [1, 2, 3, 4, 5],
                        }
                    },
                )
                events = eve.read_code_session_events("large-payload")

        self.assertLessEqual(len(event["result"]["stdout"]), 90)
        self.assertEqual({"_truncated_items": 2}, event["result"]["items"][-1])
        self.assertEqual(event["result"], events[0]["result"])

    def test_code_session_log_compaction_preserves_head_and_tail(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "session.jsonl"
            path.write_text(
                '{"type":"user_request","request":"first"}\n'
                + ("{\"type\":\"tool_call\",\"stdout\":\"middle\"}\n" * 20)
                + '{"type":"final","response":"last"}\n',
                encoding="utf-8",
            )

            dry_run = eve.compact_code_session_log_file(path, apply=False, max_bytes=120, head_bytes=80, tail_bytes=80)
            applied = eve.compact_code_session_log_file(path, apply=True, max_bytes=120, head_bytes=80, tail_bytes=80)
            compacted = path.read_text(encoding="utf-8")

        self.assertEqual("would_compact", dry_run["status"])
        self.assertEqual("compacted", applied["status"])
        self.assertIn('"type": "log_compaction"', compacted)
        self.assertIn('"request":"first"', compacted)
        self.assertIn('"response":"last"', compacted)

    def test_coder_agent_repairs_final_before_tool_use(self):
        responses = iter(
            [
                '{"type":"final","message":"The tree is dirty."}',
                '{"type":"tool_call","tool":"git_status","args":{}}',
                '{"type":"final","message":"I checked git status."}',
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            code_dir = Path(temp_dir) / "code_sessions"
            with patch.object(eve, "CODE_SESSIONS_DIR", code_dir), patch.object(
                eve, "model_chat", side_effect=lambda *args, **kwargs: next(responses)
            ), patch.object(eve, "append_entry", lambda *args, **kwargs: {}):
                result = eve.run_eve_coder_agent(
                    dict(eve.DEFAULT_CONFIG),
                    "Use git_status only.",
                    session_id="repair-test",
                    model_override="test-model",
                    require_tool_use=True,
                )

        self.assertEqual("I checked git status.", result["response"])
        self.assertEqual(["git_status"], [call["tool"] for call in result["tool_calls"]])

    def test_coder_agent_enforces_required_tool_groups(self):
        responses = iter(
            [
                '{"type":"tool_call","tool":"git_status","args":{}}',
                '{"type":"final","message":"I checked git status."}',
                '{"type":"tool_call","tool":"read_file","args":{"path":"README.md","start_line":1,"end_line":1}}',
                '{"type":"final","message":"I checked git status and read a file."}',
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            code_dir = Path(temp_dir) / "code_sessions"
            with patch.object(eve, "CODE_SESSIONS_DIR", code_dir), patch.object(
                eve, "model_chat", side_effect=lambda *args, **kwargs: next(responses)
            ), patch.object(eve, "append_entry", lambda *args, **kwargs: {}):
                result = eve.run_eve_coder_agent(
                    dict(eve.DEFAULT_CONFIG),
                    "Use required tools.",
                    session_id="required-tools-test",
                    model_override="test-model",
                    require_tool_use=True,
                    required_tools=["git_status"],
                    required_tool_groups=[["read_file", "search_text"]],
                )

        self.assertEqual("I checked git status and read a file.", result["response"])
        self.assertEqual(["git_status", "read_file"], [call["tool"] for call in result["tool_calls"]])

    def test_autonomy_capability_tryout_can_choose_coder_mode_probe(self):
        fake_result = {
            "executed": True,
            "ok": True,
            "summary": "Coder Mode tryout used git_status and run_command.",
            "response": "Coder Mode tryout completed.",
            "variant": "coder_mode_probe",
            "tools_used": ["git_status", "run_command"],
            "artifact_path": "/tmp/session.jsonl",
        }
        with patch.object(eve, "recent_autonomy_capability_tryout_variants", return_value=[]), patch.object(
            eve, "recent_capability_tryout_variant_health", return_value={}
        ), patch.object(
            eve.eve_openclaw, "openclaw_enabled", return_value=False
        ), patch.object(eve, "run_bounded_autonomous_coder_tryout", return_value=fake_result), patch.object(
            eve, "append_entry", lambda *args, **kwargs: {}
        ):
            result = eve.run_bounded_capability_tryout(
                {**eve.DEFAULT_CONFIG, "autonomy_coder_tryout_enabled": True},
                source="test",
                remaining_seconds=90,
            )

        self.assertEqual("coder_mode_probe", result["variant"])
        self.assertTrue(result["ok"])

    def test_autonomy_curiosity_state_marks_untried_capability_due(self):
        with patch.object(eve, "recent_autonomy_capability_tryout_variants", return_value=[]), patch.object(
            eve, "recent_capability_tryout_variant_health", return_value={}
        ), patch.object(
            eve.eve_openclaw, "openclaw_enabled", return_value=False
        ):
            state = eve.autonomy_curiosity_state(
                {**eve.DEFAULT_CONFIG, "autonomy_coder_tryout_enabled": True},
                [{"action": "ambient_note", "status": "completed", "ok": True}],
                90,
            )

        self.assertTrue(state["curiosity_due"])
        self.assertEqual("coder_mode_probe", state["preferred_variant"])
        self.assertIn("coder_mode_probe", state["untried_variants"])

    def test_capability_selector_skips_quarantined_variants(self):
        variant = eve.select_autonomy_capability_tryout_variant(
            {**eve.DEFAULT_CONFIG, "autonomy_coder_tryout_enabled": True},
            remaining_seconds=120,
            openclaw_ready=True,
            openclaw_attention=True,
            recent_variants=[],
            quarantined_variants={
                "coder_mode_probe": {"quarantined": True, "reason": "permission failures"},
                "openclaw_self_test": {"quarantined": True, "reason": "tracebacks"},
                "workspace_feature_probe": {"quarantined": True, "reason": "missing tools"},
            },
        )

        self.assertEqual("model_exercise", variant)

    def test_recent_capability_variant_health_quarantines_repeated_failures(self):
        runs = [
            {
                "run_id": "recent",
                "actions": [
                    {
                        "action": "capability_tryout",
                        "capability_variant": "openclaw_self_test",
                        "status": "completed",
                        "ok": False,
                        "summary": "Traceback while syncing OpenClaw.",
                    },
                    {
                        "action": "capability_tryout",
                        "status": "error",
                        "ok": False,
                        "summary": "Operation not permitted: eve.py",
                    },
                ],
            }
        ]
        with patch.object(eve, "read_autonomy_run_summaries", return_value=runs), patch.object(
            eve, "read_action_executions", return_value=[]
        ), patch.object(
            eve, "read_entries", return_value=[]
        ):
            health = eve.recent_capability_tryout_variant_health()

        self.assertTrue(health["openclaw_self_test"]["quarantined"])
        self.assertTrue(health["coder_mode_probe"]["quarantined"])

    def test_recent_capability_variant_health_unquarantines_latest_success_entry(self):
        runs = [
            {
                "run_id": "recent",
                "actions": [
                    {
                        "action": "capability_tryout",
                        "capability_variant": "coder_mode_probe",
                        "status": "error",
                        "ok": False,
                        "summary": "Operation not permitted: eve.py",
                        "finished_at": "2026-04-24T10:00:00+00:00",
                    }
                ],
            }
        ]
        entries = [
            {
                "kind": "autonomy_capability_tryout",
                "timestamp": "2026-04-24T11:00:00+00:00",
                "text": "Coder Mode tryout recovered.",
                "metadata": {"variant": "coder_mode_probe", "ok": True},
            }
        ]
        with patch.object(eve, "read_autonomy_run_summaries", return_value=runs), patch.object(
            eve, "read_entries", return_value=entries
        ), patch.object(eve, "read_action_executions", return_value=[]):
            health = eve.recent_capability_tryout_variant_health()

        self.assertFalse(health["coder_mode_probe"]["quarantined"])
        self.assertEqual(1, health["coder_mode_probe"]["successes"])

    def test_capability_selector_does_not_repeat_openclaw_when_other_variants_are_untried(self):
        with patch.object(eve.eve_openclaw, "openclaw_enabled", return_value=True):
            variant = eve.select_autonomy_capability_tryout_variant(
                {**eve.DEFAULT_CONFIG, "autonomy_coder_tryout_enabled": True},
                remaining_seconds=120,
                openclaw_ready=True,
                openclaw_attention=True,
                recent_variants=["openclaw_self_test"],
            )

        self.assertEqual("coder_mode_probe", variant)

    def test_capability_selector_rotates_away_from_dominant_recent_variant(self):
        variant = eve.select_autonomy_capability_tryout_variant(
            {**eve.DEFAULT_CONFIG, "autonomy_coder_tryout_enabled": True},
            remaining_seconds=120,
            openclaw_ready=False,
            recent_variants=[
                "coder_mode_probe",
                "coder_mode_probe",
                "coder_mode_probe",
                "workspace_feature_probe",
            ],
            variant_health={
                "coder_mode_probe": {"attempts": 3, "successes": 3, "failures": 0},
                "workspace_feature_probe": {"attempts": 1, "successes": 1, "failures": 0},
            },
        )

        self.assertEqual("model_exercise", variant)

    def test_capability_tryout_uses_current_window_variant_rotation(self):
        fake_result = {
            "executed": True,
            "ok": True,
            "summary": "Workspace feature probe inspected a feature surface.",
            "response": "Workspace feature probe completed.",
            "variant": "workspace_feature_probe",
            "tools_used": ["search_text"],
            "artifact_path": "/tmp/workspace-probe.json",
        }
        with patch.object(eve, "recent_autonomy_capability_tryout_variants", return_value=[]), patch.object(
            eve, "recent_capability_tryout_variant_health", return_value={}
        ), patch.object(
            eve.eve_openclaw, "openclaw_enabled", return_value=False
        ), patch.object(eve, "run_bounded_workspace_feature_probe", return_value=fake_result), patch.object(
            eve, "append_entry", lambda *args, **kwargs: {}
        ):
            result = eve.run_bounded_capability_tryout(
                {**eve.DEFAULT_CONFIG, "autonomy_coder_tryout_enabled": True},
                source="test",
                remaining_seconds=90,
                tried_this_window=["coder_mode_probe"],
            )

        self.assertEqual("workspace_feature_probe", result["variant"])

    def test_autonomy_guidance_forces_curiosity_probe_when_due(self):
        menu = eve.autonomy_free_run_action_menu(remaining_seconds=90)
        with patch.object(eve, "recent_autonomy_capability_tryout_variants", return_value=[]), patch.object(
            eve, "recent_capability_tryout_variant_health", return_value={}
        ), patch.object(
            eve.eve_openclaw, "openclaw_enabled", return_value=False
        ):
            guidance = eve.autonomy_free_run_guidance(
                menu,
                {"counts": {}, "components": {}, "openclaw": {}, "system": {}, "autonomy": {}},
                [{"action": "ambient_note", "status": "completed", "ok": True}],
                90,
                style="explorer",
                config={**eve.DEFAULT_CONFIG, "autonomy_coder_tryout_enabled": True},
            )

        self.assertTrue(guidance["require_curiosity_probe"])
        self.assertEqual("capability_tryout", guidance["recommended_actions"][0])
        self.assertEqual("coder_mode_probe", guidance["curiosity"]["preferred_variant"])

    def test_autonomy_guidance_cools_down_dominant_capability_family(self):
        menu = eve.autonomy_free_run_action_menu(remaining_seconds=120)
        previous_actions = [
            {
                "action": "capability_tryout",
                "status": "completed",
                "ok": True,
                "capability_variant": variant,
                "summary": f"{variant} completed.",
            }
            for variant in ["coder_mode_probe", "workspace_feature_probe", "model_exercise", "coder_mode_probe"]
        ]
        with patch.object(eve, "recent_autonomy_capability_tryout_variants", return_value=[]), patch.object(
            eve, "recent_capability_tryout_variant_health", return_value={}
        ), patch.object(eve.eve_openclaw, "openclaw_enabled", return_value=False):
            guidance = eve.autonomy_free_run_guidance(
                menu,
                {"counts": {}, "components": {}, "openclaw": {}, "system": {}, "autonomy": {}},
                previous_actions,
                120,
                style="explorer",
                config={**eve.DEFAULT_CONFIG, "autonomy_coder_tryout_enabled": True},
            )

        self.assertIn("capability", guidance["family_pressure"]["cooldowns"])
        self.assertIn("capability_tryout", guidance["family_pressure"]["cooldown_actions"])
        self.assertNotIn("capability_tryout", guidance["recommended_actions"])

    def test_autonomy_finalizer_overrides_to_curiosity_probe(self):
        menu = eve.autonomy_free_run_action_menu(remaining_seconds=90)
        action, override, policy = eve.finalize_autonomy_free_run_choice(
            "wait_observe",
            menu=menu,
            guidance={
                "style": "explorer",
                "objective": {},
                "progression": {},
                "curiosity": {"preferred_variant": "coder_mode_probe"},
                "require_curiosity_probe": True,
            },
            recommended_actions=["capability_tryout"],
            selection_policy="guided_choice",
        )

        self.assertEqual("capability_tryout", action)
        self.assertIn("curiosity", override)
        self.assertEqual("forced_curiosity_probe", policy)

    def test_autonomy_finalizer_overrides_saturated_family_choice(self):
        menu = eve.autonomy_free_run_action_menu(remaining_seconds=90)
        action, override, policy = eve.finalize_autonomy_free_run_choice(
            "capability_tryout",
            menu=menu,
            guidance={
                "style": "explorer",
                "objective": {"preferred_actions": ["updates_status"]},
                "progression": {},
                "family_pressure": {
                    "cooldown_actions": {
                        "capability_tryout": "Capability already dominates this window.",
                    }
                },
            },
            recommended_actions=["updates_status", "system_tasks"],
            selection_policy="multi_lane_council",
        )

        self.assertEqual("updates_status", action)
        self.assertIn("saturated-family", override)
        self.assertEqual("forced_family_cooldown", policy)

    def test_autonomy_choice_failure_uses_deterministic_guidance(self):
        menu = eve.autonomy_free_run_action_menu(remaining_seconds=90)
        guidance = {
            "style": "explorer",
            "objective": {"preferred_actions": ["system_tasks"]},
            "progression": {},
            "curiosity": {"preferred_variant": "coder_mode_probe"},
            "require_curiosity_probe": True,
            "recommended_actions": ["capability_tryout", "system_tasks"],
            "recommended_reasons": ["Curiosity is due.", "Ground the run."],
        }

        with patch.object(eve, "model_chat", side_effect=RuntimeError("model unavailable")):
            decision = eve.choose_autonomy_free_run_action_single_lane(
                {**eve.DEFAULT_CONFIG},
                run_id="free-run-test",
                snapshot={"counts": {}, "components": {}, "openclaw": {}, "system": {}, "autonomy": {}},
                previous_actions=[{"action": "wait_observe", "status": "completed", "ok": True}],
                remaining_seconds=90,
                menu=menu,
                guidance=guidance,
        )

        self.assertEqual("capability_tryout", decision["action"])
        self.assertEqual("deterministic_guidance_fallback", decision["selection_policy"])
        self.assertIn("deterministic bounded guidance", decision["reason"])

    def test_autonomy_high_chooser_load_uses_deterministic_choice(self):
        with patch.object(eve, "model_chat", side_effect=AssertionError("chooser should not call a model under high load")), patch.object(
            eve, "recent_autonomy_capability_tryout_variants", return_value=[]
        ), patch.object(eve, "recent_capability_tryout_variant_health", return_value={}), patch.object(
            eve.eve_openclaw, "openclaw_enabled", return_value=False
        ):
            decision = eve.choose_autonomy_free_run_action(
                {**eve.DEFAULT_CONFIG, "autonomy_free_run_multi_lane_enabled": True},
                run_id="free-run-test",
                snapshot={
                    "counts": {"choice_failures_recent": 20},
                    "components": {},
                    "openclaw": {},
                    "system": {},
                    "autonomy": {},
                },
                previous_actions=[{"action": "wait_observe", "status": "completed", "ok": True}],
                remaining_seconds=90,
                style="explorer",
            )

        self.assertEqual("deterministic_load_shed", decision["model"])
        self.assertEqual("deterministic_load_shed", decision["selection_policy"])
        self.assertIn(decision["action"], eve.AUTONOMY_FREE_RUN_ACTIONS)

    def test_action_mix_tracks_capability_variant_counts(self):
        mix = eve.autonomy_free_run_action_mix(
            [
                {"action": "capability_tryout", "capability_variant": "coder_mode_probe"},
                {"action": "capability_tryout", "capability_variant": "workspace_feature_probe"},
                {"action": "system_tasks"},
            ]
        )

        self.assertEqual(1, mix["by_capability_variant"]["coder_mode_probe"])
        self.assertEqual(1, mix["by_capability_variant"]["workspace_feature_probe"])

    def test_supervisor_does_not_flag_ratio_balanced_long_window_as_dominance(self):
        actions = [
            {"action": "capability_tryout", "status": "completed", "ok": True, "capability_variant": "coder_mode_probe"}
            for _ in range(10)
        ]
        actions.extend(
            {"action": "wait_observe", "status": "completed", "ok": True}
            for _ in range(9)
        )
        actions.extend(
            {"action": "system_tasks", "status": "completed", "ok": True, "summary": "Created 1 task(s), completed 1 CPU task(s), processed 0 maintenance task(s)."}
            for _ in range(5)
        )
        actions.extend(
            {"action": "updates_status", "status": "completed", "ok": True}
            for _ in range(7)
        )
        action_mix = eve.autonomy_free_run_action_mix(actions)
        supervisor = eve.autonomy_free_run_supervisor(
            actions=actions,
            decisions=[],
            action_mix=action_mix,
            claim_audit=[],
            errors=[],
            final_snapshot={"counts": {}},
        )

        self.assertFalse(any("dominated the run" in issue for issue in supervisor["issues"]))
        self.assertFalse(any("family dominated" in issue for issue in supervisor["issues"]))

    def test_supervisor_penalizes_repeated_capability_variant(self):
        actions = [
            {
                "action": "capability_tryout",
                "status": "completed",
                "ok": True,
                "summary": "coder_mode_probe: verification=yes.",
                "capability_variant": "coder_mode_probe",
            }
            for _ in range(4)
        ]
        action_mix = eve.autonomy_free_run_action_mix(actions)
        supervisor = eve.autonomy_free_run_supervisor(
            actions=actions,
            decisions=[],
            action_mix=action_mix,
            claim_audit=[],
            errors=[],
            final_snapshot={"counts": {}},
        )

        self.assertEqual("coder_mode_probe", supervisor["repeated_capability_variant"])
        self.assertLess(supervisor["novelty_action_balance"]["score"], 100)
        self.assertTrue(any("capability variant" in issue for issue in supervisor["issues"]))


if __name__ == "__main__":
    unittest.main()
