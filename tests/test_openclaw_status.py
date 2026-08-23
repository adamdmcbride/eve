import argparse
import io
import importlib.util
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import eve
import eve_openclaw
import eve_openclaw_body
import eve_store


SYNC_MODULE_PATH = Path(__file__).resolve().parent.parent / "bin" / "eve_openclaw_sync.py"
SYNC_SPEC = importlib.util.spec_from_file_location("eve_openclaw_sync", SYNC_MODULE_PATH)
eve_openclaw_sync = importlib.util.module_from_spec(SYNC_SPEC)
assert SYNC_SPEC and SYNC_SPEC.loader
SYNC_SPEC.loader.exec_module(eve_openclaw_sync)

REPAIR_MODULE_PATH = Path(__file__).resolve().parent.parent / "bin" / "eve_openclaw_repair.py"
REPAIR_SPEC = importlib.util.spec_from_file_location("eve_openclaw_repair", REPAIR_MODULE_PATH)
eve_openclaw_repair = importlib.util.module_from_spec(REPAIR_SPEC)
assert REPAIR_SPEC and REPAIR_SPEC.loader
REPAIR_SPEC.loader.exec_module(eve_openclaw_repair)


class OpenClawStatusTests(unittest.TestCase):
    def test_default_workspace_is_runtime_owned(self):
        self.assertEqual(
            (eve_openclaw.RUNTIME_DIR / "openclaw").resolve(),
            eve_openclaw.openclaw_workspace({}),
        )

    def test_openclaw_template_has_explicit_admitted_plugin_allow_list(self):
        template = json.loads(
            (eve_openclaw.ROOT / "openclaw" / "config" / "eve-openclaw.base.json").read_text(
                encoding="utf-8"
            )
        )
        plugins = template["plugins"]
        self.assertEqual(
            [
                "llama-cpp",
                "acpx",
                "active-memory",
                "memory-wiki",
                "webhooks",
                "memory-core",
                "imessage",
            ],
            plugins["allow"],
        )
        self.assertNotIn("codex", plugins["entries"])

    def test_openclaw_template_uses_one_runtime_owned_wiki_vault(self):
        template = json.loads(
            (eve_openclaw.ROOT / "openclaw" / "config" / "eve-openclaw.base.json").read_text(
                encoding="utf-8"
            )
        )
        vault_path = template["plugins"]["entries"]["memory-wiki"]["config"]["vault"]["path"]

        self.assertEqual(
            "__EVE_RUNTIME_ROOT__/openclaw/wiki/eve-memory-wiki",
            vault_path,
        )
        rendered_path = vault_path.replace("__EVE_RUNTIME_ROOT__", "/tmp/eve-runtime")
        self.assertTrue(Path(rendered_path).is_absolute())

    def test_openclaw_template_exposes_wiki_tools_to_the_resident_agent(self):
        template = json.loads(
            (eve_openclaw.ROOT / "openclaw" / "config" / "eve-openclaw.base.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            [
                "wiki_apply",
                "wiki_get",
                "wiki_lint",
                "wiki_search",
                "wiki_status",
            ],
            template["tools"]["alsoAllow"],
        )
        repair_agent = next(
            item for item in template["agents"]["list"] if item["id"] == "eve-repair"
        )
        self.assertEqual(
            ["read", "write", "edit", "exec", "process"],
            repair_agent["tools"]["alsoAllow"],
        )

    def test_openclaw_template_keeps_bounded_compaction_headroom(self):
        template = json.loads(
            (eve_openclaw.ROOT / "openclaw" / "config" / "eve-openclaw.base.json").read_text(
                encoding="utf-8"
            )
        )
        compaction = template["agents"]["defaults"]["compaction"]

        self.assertEqual("safeguard", compaction["mode"])
        self.assertEqual(6144, compaction["reserveTokens"])
        self.assertEqual(6144, compaction["reserveTokensFloor"])
        self.assertTrue(compaction["midTurnPrecheck"]["enabled"])
        self.assertNotIn("utilityModel", template["agents"]["defaults"])

    def test_openclaw_template_admits_only_the_complete_eve_skill_set(self):
        template = json.loads(
            (eve_openclaw.ROOT / "openclaw" / "config" / "eve-openclaw.base.json").read_text(
                encoding="utf-8"
            )
        )
        expected = [
            "eve_capability_use",
            "eve_codex_independent_operator",
            "eve_control_home",
            "eve_external_channel_drafting",
            "eve_memory_wiki_reflection",
            "eve_organ_assimilation",
            "eve_personal_conversation",
            "eve_self_repair",
            "eve_system_sensing",
            "eve_task_followthrough",
        ]
        agents = {item["id"]: item for item in template["agents"]["list"]}

        self.assertEqual(expected, agents["main"]["skills"])
        self.assertEqual(expected, agents["eve-repair"]["skills"])
        self.assertEqual(5000, agents["main"]["skillsLimits"]["maxSkillsPromptChars"])
        self.assertEqual(5000, agents["eve-repair"]["skillsLimits"]["maxSkillsPromptChars"])
        personal_skill = (
            eve_openclaw.ROOT / "openclaw" / "skills" / "eve_personal_conversation" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertTrue(personal_skill.startswith("---\nname: eve_personal_conversation\n"))

    def test_openclaw_template_uses_local_qmd_with_keep_alive_mcporter_config(self):
        template = json.loads(
            (eve_openclaw.ROOT / "openclaw" / "config" / "eve-openclaw.base.json").read_text(
                encoding="utf-8"
            )
        )
        memory = template["memory"]
        qmd = memory["qmd"]
        mcporter = json.loads(
            (eve_openclaw.ROOT / "openclaw" / "config" / "mcporter.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual("qmd", memory["backend"])
        self.assertEqual("/opt/homebrew/bin/qmd", qmd["command"])
        self.assertEqual("query", qmd["searchMode"])
        self.assertFalse(qmd["rerank"])
        self.assertFalse(qmd["sessions"]["enabled"])
        self.assertTrue(qmd["mcporter"]["enabled"])
        self.assertTrue(qmd["mcporter"]["startDaemon"])
        self.assertEqual(45000, qmd["limits"]["timeoutMs"])
        self.assertTrue(all(item["path"].startswith("__EVE_RUNTIME_ROOT__/") for item in qmd["paths"]))
        self.assertEqual([], template["agents"]["defaults"]["memorySearch"]["extraPaths"])
        self.assertEqual(
            "keep-alive",
            mcporter["mcpServers"]["qmd"]["lifecycle"]["mode"],
        )

    def test_openclaw_template_keeps_unapproved_imessage_transport_dormant(self):
        template = json.loads(
            (eve_openclaw.ROOT / "openclaw" / "config" / "eve-openclaw.base.json").read_text(
                encoding="utf-8"
            )
        )
        imessage = template["channels"]["imessage"]

        self.assertFalse(imessage["enabled"])
        self.assertEqual("disabled", imessage["dmPolicy"])
        self.assertEqual("allowlist", imessage["groupPolicy"])

    def test_component_watchlist_tracks_qmd_mcporter_and_acpx(self):
        by_id = {item["id"]: item for item in eve.component_watchlist({})}

        self.assertEqual("@tobilu/qmd", by_id["qmd"]["package"])
        self.assertEqual("mcporter", by_id["mcporter"]["package"])
        self.assertEqual("acpx", by_id["openclaw-acpx"]["plugin_id"])
        self.assertIn("2.5.0", by_id["pytrees-system-python"]["blocked_versions"])
        self.assertIn("1.24.0", by_id["huggingface-hub-techlab"]["blocked_versions"])

    def test_plugin_allow_fields_report_current_explicit_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            (state_dir / "openclaw.json").write_text(
                json.dumps(
                    {
                        "plugins": {
                            "allow": [
                                "memory-core",
                                "webhooks",
                                "memory-core",
                                "imessage",
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            fields = eve_openclaw.openclaw_plugin_allow_fields(
                {"openclaw_state_dir": str(state_dir)}
            )

        self.assertTrue(fields["plugins_allow_explicit"])
        self.assertTrue(fields["plugins_allow_ok"])
        self.assertEqual(3, fields["plugins_allow_count"])
        self.assertEqual(
            ["memory-core", "webhooks", "imessage"],
            fields["plugins_allow_entries"],
        )
        self.assertEqual("", fields["plugins_allow_error"])

    def test_plugin_allow_fields_distinguish_explicit_empty_list(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            (state_dir / "openclaw.json").write_text(
                json.dumps({"plugins": {"allow": []}}),
                encoding="utf-8",
            )

            fields = eve_openclaw.openclaw_plugin_allow_fields(
                {"openclaw_state_dir": str(state_dir)}
            )

        self.assertTrue(fields["plugins_allow_explicit"])
        self.assertFalse(fields["plugins_allow_ok"])
        self.assertEqual(0, fields["plugins_allow_count"])
        self.assertEqual("plugins.allow is empty", fields["plugins_allow_error"])

    def test_openclaw_run_timeout_returns_degraded_completed_process(self):
        with patch.object(
            eve_openclaw.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["openclaw", "memory", "status"], timeout=2),
        ):
            result = eve_openclaw.run(["openclaw", "memory", "status"], timeout=2)

        self.assertEqual(124, result.returncode)
        self.assertIn("timed out after 2 seconds", result.stderr)

    def test_openclaw_memory_status_timeout_degrades_without_crashing(self):
        timeout_result = subprocess.CompletedProcess(
            args=["openclaw", "memory", "status"],
            returncode=124,
            stdout="",
            stderr="Command timed out after 90 seconds: openclaw memory status --deep --json",
        )

        with patch.object(eve_openclaw, "openclaw_command", return_value="/opt/homebrew/bin/openclaw"), patch.object(
            eve_openclaw, "run", return_value=timeout_result
        ):
            fields = eve_openclaw.probe_openclaw_memory_status({"openclaw_profile": "eve-repair"})

        self.assertFalse(fields["memory_status_ok"])
        self.assertEqual("degraded", fields["memory_status_severity"])
        self.assertIn("timed out", fields["memory_status_summary"])

    def test_atomic_write_text_falls_back_when_replace_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            status_path = Path(temp_dir) / "eve_status.md"

            with patch("pathlib.Path.replace", side_effect=PermissionError("operation not permitted")):
                result = eve_openclaw_sync.atomic_write_text(status_path, "fresh status\n")

            self.assertTrue(result)
            self.assertEqual("fresh status\n", status_path.read_text(encoding="utf-8"))
            self.assertEqual([], list(status_path.parent.glob(".*.tmp.*")))

    def test_atomic_write_text_degrades_when_snapshot_write_is_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            status_path = Path(temp_dir) / "eve_status.md"

            with patch("pathlib.Path.write_text", side_effect=PermissionError("operation not permitted")), patch(
                "sys.stderr", new_callable=io.StringIO
            ):
                result = eve_openclaw_sync.atomic_write_text(status_path, "fresh status\n")

            self.assertFalse(result)
            self.assertFalse(status_path.exists())
            self.assertEqual([], list(status_path.parent.glob(".*.tmp.*")))

    def test_atomic_write_text_clears_generated_file_xattrs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            status_path = Path(temp_dir) / "eve_status.md"

            with patch.object(eve_openclaw_sync.os, "removexattr", create=True) as removexattr:
                result = eve_openclaw_sync.atomic_write_text(status_path, "fresh status\n")

            self.assertTrue(result)
            self.assertEqual("fresh status\n", status_path.read_text(encoding="utf-8"))
            cleared_attrs = {call.args[1] for call in removexattr.call_args_list}
            self.assertIn("com.apple.macl", cleared_attrs)
            self.assertIn("com.apple.provenance", cleared_attrs)

    def test_clear_generated_file_xattrs_falls_back_to_xattr_command(self):
        status_path = Path("/tmp/eve_status.md")

        with patch.object(eve_openclaw_sync.os, "removexattr", create=True, side_effect=PermissionError("denied")), patch.object(
            eve_openclaw_sync.Path, "exists", return_value=True
        ), patch.object(eve_openclaw_sync.subprocess, "run") as run:
            eve_openclaw_sync.clear_generated_file_xattrs(status_path)

        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn(["/usr/bin/xattr", "-d", "com.apple.macl", str(status_path)], commands)
        self.assertIn(["/usr/bin/xattr", "-d", "com.apple.provenance", str(status_path)], commands)

    def test_sync_helper_uses_bounded_openclaw_status_probe(self):
        commands = dict(eve_openclaw_sync.build_commands())

        self.assertIn("--no-memory-probe", commands["openclaw_status"])

    def test_sync_run_command_timeout_returns_degraded_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = eve_openclaw_sync.run_command(
                [sys.executable, "-c", "import time; time.sleep(3)"],
                timeout=1,
                cwd=Path(temp_dir),
            )

        self.assertEqual(124, result["returncode"])
        self.assertTrue(result["timed_out"])
        self.assertIn("Command timed out after 1 seconds", result["stderr"])

    def test_openclaw_status_flags_disable_expensive_probes(self):
        args = argparse.Namespace(no_gateway_probe=True, no_memory_probe=True)
        with patch.object(eve, "load_config", return_value={}), patch.object(
            eve.eve_openclaw,
            "collect_openclaw_status",
            return_value={"summary": "bounded status"},
        ) as collect_status, patch.object(eve.eve_openclaw, "save_openclaw_status"), patch.object(
            eve, "load_state", return_value={}
        ), patch.object(
            eve, "save_state"
        ), patch(
            "sys.stdout", new_callable=io.StringIO
        ):
            eve.cmd_openclaw_status(args)

        self.assertFalse(collect_status.call_args.kwargs["include_gateway_probe"])
        self.assertFalse(collect_status.call_args.kwargs["include_memory_probe"])

    def test_cleanup_stale_temp_artifacts_removes_old_sync_temps_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            context_dir = Path(temp_dir)
            stale = context_dir / ".eve_status.json.tmp.123"
            fresh = context_dir / ".eve_status.json.tmp.456"
            unrelated = context_dir / ".other.tmp.789"
            stale.write_text("stale", encoding="utf-8")
            fresh.write_text("fresh", encoding="utf-8")
            unrelated.write_text("other", encoding="utf-8")
            old_time = time.time() - 7200
            stale.touch()
            unrelated.touch()
            eve_openclaw_sync.os.utime(stale, (old_time, old_time))
            eve_openclaw_sync.os.utime(unrelated, (old_time, old_time))

            removed = eve_openclaw_sync.cleanup_stale_temp_artifacts(context_dir, older_than_seconds=3600)

            self.assertEqual(1, removed)
            self.assertFalse(stale.exists())
            self.assertTrue(fresh.exists())
            self.assertTrue(unrelated.exists())

    def test_append_memory_note_degrades_when_append_is_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            payload = {
                "generated_at": "2026-04-24T18:40:00+00:00",
                "commands": {"doctor": {}, "tasks": {}, "maintenance": {}},
            }

            with patch("pathlib.Path.open", side_effect=PermissionError("operation not permitted")), patch(
                "sys.stderr", new_callable=io.StringIO
            ):
                result = eve_openclaw_sync.append_memory_note(workspace, payload)

            self.assertFalse(result)

    def test_append_memory_note_clears_generated_file_xattrs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            payload = {
                "generated_at": "2026-04-24T18:40:00+00:00",
                "commands": {"doctor": {}, "tasks": {}, "maintenance": {}},
            }

            with patch.object(eve_openclaw_sync.os, "removexattr", create=True) as removexattr:
                result = eve_openclaw_sync.append_memory_note(workspace, payload)

            self.assertTrue(result)
            cleared_attrs = {call.args[1] for call in removexattr.call_args_list}
            self.assertIn("com.apple.macl", cleared_attrs)
            self.assertIn("com.apple.provenance", cleared_attrs)

    def test_append_memory_note_is_compact(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            payload = {
                "generated_at": "2026-04-24T18:40:00+00:00",
                "repo_root": "/repo",
                "command_root": "/runtime",
                "commands": {
                    "doctor": {
                        "cmd": ["eve.py", "doctor"],
                        "returncode": 0,
                        "stdout": "Eve config\n" + ("A" * 6000) + "\nDegraded signals: none\n",
                        "stderr": "",
                    },
                    "tasks": {
                        "cmd": ["eve.py", "task", "list"],
                        "returncode": 0,
                        "stdout": "blocked system task: example\n" + ("B" * 6000),
                        "stderr": "",
                    },
                    "maintenance": {"cmd": [], "returncode": 0, "stdout": "no maintenance", "stderr": ""},
                    "openclaw_status": {
                        "cmd": ["eve.py", "openclaw", "status"],
                        "returncode": 0,
                        "stdout": "Gateway: reachable\nsync_health_summary: stable\n",
                        "stderr": "",
                    },
                },
            }

            result = eve_openclaw_sync.append_memory_note(workspace, payload)
            # Operational repair status now goes to context/last_repair.md (atomic
            # overwrite), NOT memory/YYYY-MM-DD.md — the daily notes feed the
            # dreaming pipeline and must not carry repair boilerplate.
            self.assertFalse(list((workspace / "memory").glob("*.md")) if (workspace / "memory").exists() else [])
            repair_file = workspace / "context" / "last_repair.md"
            self.assertTrue(repair_file.exists())
            memory_text = repair_file.read_text(encoding="utf-8")

            self.assertTrue(result)
            self.assertLess(len(memory_text), 2500)
            self.assertNotIn("A" * 1000, memory_text)
            self.assertIn("Degraded signals: none", memory_text)

    def test_brief_snapshot_summarizes_without_raw_dump(self):
        payload = {
            "generated_at": "2026-04-24T18:40:00+00:00",
            "repo_root": "/repo",
            "command_root": "/runtime",
            "commands": {
                "doctor": {
                    "cmd": ["eve.py", "doctor"],
                    "returncode": 0,
                    "stdout": "Eve config\n" + ("A" * 6000) + "\nGateway: reachable\n",
                    "stderr": "",
                }
            },
        }

        brief = eve_openclaw_sync.build_brief_payload(payload)
        rendered = eve_openclaw_sync.render_brief_markdown(brief)

        self.assertIn("Gateway: reachable", rendered)
        self.assertNotIn("A" * 1000, rendered)
        self.assertLess(len(rendered), 1800)

    def test_openclaw_sync_lock_blocks_duplicate_writer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "openclaw_sync.lock"
            with patch.object(eve_openclaw_sync, "LOCK_PATH", lock_path), patch(
                "sys.stderr", new_callable=io.StringIO
            ):
                first = eve_openclaw_sync.acquire_sync_lock(timeout_seconds=0)
                second = eve_openclaw_sync.acquire_sync_lock(timeout_seconds=0)
                eve_openclaw_sync.release_sync_lock(first)

            self.assertIsNotNone(first)
            self.assertIsNone(second)

    def test_openclaw_status_uses_freshest_status_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            local_path = temp_path / "local" / "openclaw_status.json"
            runtime_path = temp_path / "runtime" / "openclaw_status.json"
            eve_store.write_json_dict(
                local_path,
                {
                    "last_sync_at": "2026-04-24T13:16:09+00:00",
                    "last_sync_summary": "source stale",
                },
            )
            eve_store.write_json_dict(
                runtime_path,
                {
                    "last_sync_at": "2026-04-24T14:20:30+00:00",
                    "last_sync_summary": "runtime fresh",
                },
            )

            with patch.object(eve_openclaw, "OPENCLAW_STATUS_PATH", local_path), patch.object(
                eve_openclaw, "RUNTIME_OPENCLAW_STATUS_PATH", runtime_path
            ):
                runtime_status = eve_openclaw.load_openclaw_status(prefer_runtime=True)
                local_status = eve_openclaw.load_openclaw_status(prefer_runtime=False)

            self.assertEqual("2026-04-24T14:20:30+00:00", runtime_status["last_sync_at"])
            self.assertEqual("runtime fresh", runtime_status["last_sync_summary"])
            self.assertEqual("2026-04-24T14:20:30+00:00", local_status["last_sync_at"])
            self.assertEqual("runtime fresh", local_status["last_sync_summary"])

    def test_openclaw_status_uses_fresher_source_when_runtime_is_stale(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            local_path = temp_path / "local" / "openclaw_status.json"
            runtime_path = temp_path / "runtime" / "openclaw_status.json"
            eve_store.write_json_dict(
                local_path,
                {
                    "last_sync_at": "2026-04-24T14:20:30+00:00",
                    "last_sync_summary": "source fresh",
                },
            )
            eve_store.write_json_dict(
                runtime_path,
                {
                    "last_sync_at": "2026-04-24T13:16:09+00:00",
                    "last_sync_summary": "runtime stale",
                },
            )

            with patch.object(eve_openclaw, "OPENCLAW_STATUS_PATH", local_path), patch.object(
                eve_openclaw, "RUNTIME_OPENCLAW_STATUS_PATH", runtime_path
            ):
                status = eve_openclaw.load_openclaw_status(prefer_runtime=True)

            self.assertEqual("2026-04-24T14:20:30+00:00", status["last_sync_at"])
            self.assertEqual("source fresh", status["last_sync_summary"])

    def test_openclaw_sync_history_sorts_by_timestamp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            local_history = temp_path / "local" / "openclaw_sync_history.jsonl"
            runtime_history = temp_path / "runtime" / "openclaw_sync_history.jsonl"
            eve_store.append_jsonl_record(
                runtime_history,
                {"id": "older", "timestamp": "2026-04-24T13:16:09+00:00", "ok": False},
            )
            eve_store.append_jsonl_record(
                local_history,
                {"id": "newer", "timestamp": "2026-04-24T14:20:30+00:00", "ok": True},
            )

            with patch.object(eve_openclaw, "OPENCLAW_SYNC_HISTORY_PATH", local_history), patch.object(
                eve_openclaw, "RUNTIME_OPENCLAW_SYNC_HISTORY_PATH", runtime_history
            ):
                history = eve_openclaw.load_openclaw_sync_history(prefer_runtime=True)

            self.assertEqual(["older", "newer"], [item["id"] for item in history])

    def test_sync_openclaw_marks_context_artifact_degradation_unverified(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = subprocess.CompletedProcess(
                args=["sync"],
                returncode=0,
                stdout=(
                    "Command root: /Users/example/.eve_runtime\n"
                    "OpenClaw sync completed, but one or more context artifacts could not be updated in "
                    "/Users/example/Projects/Eve/openclaw/context\n"
                ),
                stderr=(
                    "Warning: could not update OpenClaw sync artifact "
                    "/Users/example/Projects/Eve/openclaw/context/eve_status.json"
                ),
            )

            with patch.object(eve_openclaw, "run", return_value=result), patch.object(
                eve_openclaw, "collect_openclaw_status", return_value={"enabled": True}
            ), patch.object(eve_openclaw, "append_openclaw_sync_history") as append_history, patch.object(
                eve_openclaw, "load_openclaw_sync_history", return_value=[]
            ), patch.object(eve_openclaw, "save_openclaw_status"):
                sync = eve_openclaw.sync_openclaw({"openclaw_workspace": temp_dir}, append_memory=True)

            self.assertFalse(sync["ok"])
            self.assertTrue(sync["artifact_write_degraded"])
            self.assertFalse(sync["status"]["last_sync_ok"])
            append_history.assert_called_once()
            self.assertFalse(append_history.call_args.args[0]["ok"])

    def test_sync_openclaw_treats_duplicate_lock_skip_as_non_degraded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = subprocess.CompletedProcess(
                args=["sync"],
                returncode=0,
                stdout=(
                    "Command root: unavailable\n"
                    "Skipped duplicate OpenClaw sync because another sync writer is already active.\n"
                ),
                stderr=(
                    "Warning: another OpenClaw sync held /Users/example/.eve_runtime/.eve/locks/"
                    "openclaw_sync.lock for more than 0s; skipping this duplicate sync.\n"
                ),
            )

            with patch.object(eve_openclaw, "run", return_value=result), patch.object(
                eve_openclaw, "collect_openclaw_status", return_value={"enabled": True}
            ), patch.object(eve_openclaw, "append_openclaw_sync_history") as append_history, patch.object(
                eve_openclaw, "load_openclaw_sync_history", return_value=[]
            ), patch.object(eve_openclaw, "save_openclaw_status"):
                sync = eve_openclaw.sync_openclaw({"openclaw_workspace": temp_dir}, append_memory=True)

            self.assertTrue(sync["ok"])
            self.assertFalse(sync["artifact_write_degraded"])
            append_history.assert_called_once()
            self.assertTrue(append_history.call_args.args[0]["ok"])

    def test_repair_strict_json_parser_rejects_tool_preamble(self):
        parsed, error = eve_openclaw_repair.parse_strict_repair_json("Let me start by reading the current status.")

        self.assertIsNone(parsed)
        self.assertIn("strict JSON", error)

    def test_repair_strict_json_parser_accepts_final_contract(self):
        parsed, error = eve_openclaw_repair.parse_strict_repair_json(
            '{"status":"diagnosed","issue":"x","action":"checked","verified":"command ok","next_step":"none"}'
        )

        self.assertEqual("", error)
        self.assertEqual("diagnosed", parsed["status"])

    def test_repair_strict_json_parser_rejects_non_string_values(self):
        parsed, error = eve_openclaw_repair.parse_strict_repair_json(
            json.dumps(
                {
                    "status": "diagnosed",
                    "issue": "x",
                    "action": "checked",
                    "verified": False,
                    "next_step": "none",
                }
            )
        )

        self.assertIsNone(parsed)
        self.assertIn("values must be strings", error)

    def test_repair_helper_detects_tool_use_continuation_needed(self):
        stderr = json.dumps({"meta": {"stopReason": "toolUse", "completion": {"stopReason": "toolUse"}}})

        self.assertTrue(eve_openclaw_repair.openclaw_needs_continuation("", stderr))

    def test_repair_helper_does_not_continue_after_final_stop(self):
        stderr = json.dumps({"meta": {"stopReason": "stop", "completion": {"stopReason": "stop"}}})

        self.assertFalse(eve_openclaw_repair.openclaw_needs_continuation("", stderr))

    def test_repair_helper_retries_contract_violation(self):
        stdout = json.dumps({"ok": False, "error": "reply was not strict JSON: Expecting value"})

        self.assertTrue(eve_openclaw_repair.repair_contract_retry_needed(stdout, ""))

    def test_repair_helper_retries_prose_wrapped_cli_payload(self):
        stdout = json.dumps(
            {
                "payloads": [
                    {
                        "text": (
                            "Verified. Strict repair JSON:\n"
                            '{"status":"diagnosed","issue":"x","action":"checked",'
                            '"verified":"ok","next_step":"none"}'
                        )
                    }
                ],
                "meta": {"replayInvalid": True},
            }
        )

        normalized = eve_openclaw_repair.normalize_openclaw_agent_result(
            stdout,
            "",
            0,
        )

        self.assertFalse(normalized["ok"])
        self.assertIn("strict JSON", normalized["error"])
        self.assertTrue(
            eve_openclaw_repair.repair_contract_retry_needed(stdout, "")
        )

    def test_repair_helper_accepts_strict_cli_payload(self):
        reply = (
            '{"status":"diagnosed","issue":"x","action":"checked",'
            '"verified":"ok","next_step":"none"}'
        )
        stdout = json.dumps(
            {
                "payloads": [{"text": reply}],
                "meta": {"replayInvalid": False},
            }
        )

        normalized = eve_openclaw_repair.normalize_openclaw_agent_result(
            stdout,
            "",
            0,
        )

        self.assertTrue(normalized["ok"])
        self.assertEqual("diagnosed", normalized["parsed_reply"]["status"])
        self.assertEqual("openclaw_cli_json", normalized["source"])

    def test_repair_openclaw_requires_strict_json_success(self):
        result = subprocess.CompletedProcess(
            args=["repair"],
            returncode=0,
            stdout='{"reply":"Let me start by reading the current status.","error":"","hard_failures":[]}',
            stderr="",
        )

        with patch.object(eve_openclaw, "run", return_value=result), patch.object(
            eve_openclaw, "collect_openclaw_status", return_value={"enabled": True}
        ), patch.object(eve_openclaw, "save_openclaw_status"):
            repair = eve_openclaw.repair_openclaw({"openclaw_workspace": "/tmp/eve-openclaw-test"}, skip_sync=True)

        self.assertFalse(repair["ok"])
        self.assertFalse(repair["status"]["last_repair_ok"])

    def test_repair_openclaw_accepts_strict_json_contract(self):
        reply = {
            "status": "diagnosed",
            "issue": "status brief is current",
            "action": "checked brief",
            "verified": "read context/eve_status_brief.md",
            "next_step": "none",
        }
        result = subprocess.CompletedProcess(
            args=["repair"],
            returncode=0,
            stdout=json.dumps({"reply": json.dumps(reply), "parsed_reply": reply, "error": "", "hard_failures": []}),
            stderr="",
        )

        with patch.object(eve_openclaw, "run", return_value=result), patch.object(
            eve_openclaw, "collect_openclaw_status", return_value={"enabled": True}
        ), patch.object(eve_openclaw, "save_openclaw_status"):
            repair = eve_openclaw.repair_openclaw({"openclaw_workspace": "/tmp/eve-openclaw-test"}, skip_sync=True)

        self.assertTrue(repair["ok"])
        self.assertTrue(repair["status"]["last_repair_ok"])
        self.assertEqual("diagnosed", repair["status"]["last_repair_status"])
        self.assertEqual("read context/eve_status_brief.md", repair["status"]["last_repair_verified"])

    def test_openclaw_repair_signals_skip_load_deferred_gpu_followup(self):
        with (
            patch.object(eve, "daemon_health_diagnostics", return_value={"degraded": False}),
            patch.object(eve, "read_failure_clusters", return_value=[]),
            patch.object(
                eve,
                "read_system_tasks",
                return_value=[
                    {
                        "status": "blocked",
                        "kind": "gpu_followup_reflection",
                        "title": "Escalate only unresolved work from CPU to GPU",
                        "blocked_reason": "System load is hot, so defer GPU follow-up reflection until the machine cools down.",
                    }
                ],
            ),
            patch.object(eve, "read_maintenance_actions", return_value=[]),
            patch.object(eve, "read_entries", return_value=[]),
        ):
            signals = eve.openclaw_repair_signals({}, {})

        self.assertEqual([], signals)

    def test_openclaw_repair_signals_include_non_benign_blocked_reason(self):
        with (
            patch.object(eve, "daemon_health_diagnostics", return_value={"degraded": False}),
            patch.object(eve, "read_failure_clusters", return_value=[]),
            patch.object(
                eve,
                "read_system_tasks",
                return_value=[
                    {
                        "status": "blocked",
                        "kind": "gpu_followup_reflection",
                        "title": "Escalate only unresolved work from CPU to GPU",
                        "blocked_reason": "No GPU escalation criteria are configured.",
                    }
                ],
            ),
            patch.object(eve, "read_maintenance_actions", return_value=[]),
            patch.object(eve, "read_entries", return_value=[]),
        ):
            signals = eve.openclaw_repair_signals({}, {})

        self.assertEqual(
            ["blocked system task: Escalate only unresolved work from CPU to GPU (No GPU escalation criteria are configured.)"],
            signals,
        )

    def test_openclaw_action_router_status_snapshot_records_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            plan = eve_openclaw_body.build_openclaw_action_plan(
                intent="check OpenClaw status",
                requested_action="status_snapshot",
                source="unit_test",
            )
            status = {
                "gateway_reachable": True,
                "memory_status_severity": "ready",
                "memory_provider": "local",
                "memory_capability_available": True,
                "summary": "OpenClaw reachable.",
            }

            with (
                patch.object(eve_openclaw_body, "OPENCLAW_EVIDENCE_EVENTS_PATH", temp_path / "evidence.jsonl"),
                patch.object(eve_openclaw_body, "RUNTIME_OPENCLAW_EVIDENCE_EVENTS_PATH", temp_path / "runtime" / "evidence.jsonl"),
                patch.object(eve_openclaw_body, "OPENCLAW_ACTION_ROUTER_EVENTS_PATH", temp_path / "router.jsonl"),
                patch.object(eve_openclaw_body, "RUNTIME_OPENCLAW_ACTION_ROUTER_EVENTS_PATH", temp_path / "runtime" / "router.jsonl"),
                patch.object(eve_openclaw, "collect_openclaw_status", return_value=status),
                patch.object(eve_openclaw, "save_openclaw_status"),
                patch.object(eve, "append_entry"),
            ):
                result = eve.execute_openclaw_action_plan({}, plan, timeout=5)

            self.assertTrue(result["ok"])
            self.assertTrue(result["executed"])
            self.assertEqual("status_snapshot", result["action"])
            self.assertTrue(result["event_id"])
            evidence_records = eve_store.read_jsonl_records(temp_path / "evidence.jsonl")
            router_records = eve_store.read_jsonl_records(temp_path / "router.jsonl")
            self.assertEqual(1, len(evidence_records))
            self.assertEqual(1, len(router_records))
            self.assertEqual("openclaw_status_snapshot", evidence_records[0]["event_type"])
            self.assertEqual("openclaw_action_router_execution", router_records[0]["event_type"])
            self.assertFalse(router_records[0]["canonical_memory_authority"])

    def test_openclaw_routines_run_due_action_and_record_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            state = {}
            fake_result = {
                "ok": True,
                "executed": True,
                "summary": "OpenClaw status snapshot recorded.",
                "event_id": "router-1",
                "evidence_event_ids": ["evidence-1"],
            }

            with (
                patch.object(eve_openclaw_body, "OPENCLAW_ROUTINE_EVENTS_PATH", temp_path / "routines.jsonl"),
                patch.object(eve_openclaw_body, "RUNTIME_OPENCLAW_ROUTINE_EVENTS_PATH", temp_path / "runtime" / "routines.jsonl"),
                patch.object(eve, "execute_openclaw_action_plan", return_value=fake_result),
            ):
                result = eve.run_openclaw_routines(
                    {"openclaw_enabled": True, "openclaw_routines_enabled": True},
                    state,
                    force=True,
                    limit=1,
                    source="unit_test",
                )

            self.assertTrue(result["ok"])
            self.assertEqual(1, result["executed"])
            self.assertIn("last_openclaw_routine_daily_status_snapshot_at", state)
            records = eve_store.read_jsonl_records(temp_path / "routines.jsonl")
            self.assertEqual(1, len(records))
            self.assertEqual("openclaw_routine", records[0]["event_type"])
            self.assertEqual("daily_status_snapshot", records[0]["routine_id"])
            self.assertEqual("router-1", records[0]["payload"]["router_event_id"])
            self.assertFalse(records[0]["canonical_memory_authority"])

    def test_openclaw_worker_dry_run_records_bounded_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            with (
                patch.object(eve_openclaw_body, "OPENCLAW_WORKER_EVENTS_PATH", temp_path / "workers.jsonl"),
                patch.object(eve_openclaw_body, "RUNTIME_OPENCLAW_WORKER_EVENTS_PATH", temp_path / "runtime" / "workers.jsonl"),
            ):
                plan = eve.build_openclaw_worker_plan(
                    worker_kind="audit",
                    parent_intention="verify worker milestone",
                    prompt="Check bounded worker evidence.",
                    source="unit_test",
                    timeout=30,
                )
                result = eve.run_openclaw_worker_plan(plan, dry_run=True)

            self.assertTrue(result["ok"])
            records = eve_store.read_jsonl_records(temp_path / "workers.jsonl")
            self.assertEqual(1, len(records))
            self.assertEqual("openclaw_worker", records[0]["event_type"])
            self.assertEqual("audit", records[0]["worker_kind"])
            self.assertEqual("dry_run", records[0]["status"])
            self.assertFalse(records[0]["canonical_memory_authority"])
            self.assertFalse(records[0]["plan"]["adds_chat_lane"])
            self.assertFalse(records[0]["plan"]["persistent_agent"])
            self.assertFalse(records[0]["plan"]["canonical_memory_authority"])

    def test_openclaw_worker_blocks_approval_gated_execution(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            with (
                patch.object(eve_openclaw_body, "OPENCLAW_WORKER_EVENTS_PATH", temp_path / "workers.jsonl"),
                patch.object(eve_openclaw_body, "RUNTIME_OPENCLAW_WORKER_EVENTS_PATH", temp_path / "runtime" / "workers.jsonl"),
                patch.object(eve_openclaw_body, "run_openclaw_json_command") as run_command,
            ):
                plan = eve.build_openclaw_worker_plan(
                    worker_kind="code_repair",
                    parent_intention="repair OpenClaw integration",
                    prompt="Patch the code.",
                    source="unit_test",
                    timeout=30,
                )
                result = eve.run_openclaw_worker_plan(plan, dry_run=False)

            self.assertFalse(result["ok"])
            run_command.assert_not_called()
            records = eve_store.read_jsonl_records(temp_path / "workers.jsonl")
            self.assertEqual(1, len(records))
            self.assertEqual("blocked", records[0]["status"])
            self.assertTrue(records[0]["plan"]["requires_specific_approval"])
            self.assertFalse(records[0]["canonical_memory_authority"])

    def test_openclaw_worker_degrades_when_reply_is_not_strict_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_command_result = {
                "ok": True,
                "command": ["openclaw", "agent"],
                "returncode": 0,
                "payload": {
                    "meta": {
                        "finalAssistantRawText": 'Done. ```json {"status":"alive","issue":"","action":"","verified":"","next_step":""} ```'
                    },
                    "payloads": [],
                },
            }
            with (
                patch.object(eve_openclaw_body, "OPENCLAW_WORKER_EVENTS_PATH", temp_path / "workers.jsonl"),
                patch.object(eve_openclaw_body, "RUNTIME_OPENCLAW_WORKER_EVENTS_PATH", temp_path / "runtime" / "workers.jsonl"),
                patch.object(eve_openclaw_body, "run_openclaw_json_command", return_value=fake_command_result),
            ):
                plan = eve.build_openclaw_worker_plan(
                    worker_kind="audit",
                    parent_intention="verify strict worker contract",
                    prompt="Return strict JSON.",
                    source="unit_test",
                    timeout=30,
                )
                result = eve.run_openclaw_worker_plan(plan, dry_run=False)

            self.assertFalse(result["ok"])
            records = eve_store.read_jsonl_records(temp_path / "workers.jsonl")
            self.assertEqual(1, len(records))
            self.assertEqual("degraded", records[0]["status"])
            self.assertFalse(records[0]["worker_strict_json"]["ok"])
            self.assertIn("strict JSON", records[0]["summary"])

    def test_openclaw_worker_accepts_one_strict_json_object(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_command_result = {
                "ok": True,
                "command": ["openclaw", "agent"],
                "returncode": 0,
                "payload": {
                    "meta": {
                        "finalAssistantRawText": json.dumps(
                            {
                                "status": "alive",
                                "issue": "none",
                                "action": "checked",
                                "verified": "strict json parsed",
                                "next_step": "none",
                            }
                        )
                    },
                    "payloads": [],
                },
            }
            with (
                patch.object(eve_openclaw_body, "OPENCLAW_WORKER_EVENTS_PATH", temp_path / "workers.jsonl"),
                patch.object(eve_openclaw_body, "RUNTIME_OPENCLAW_WORKER_EVENTS_PATH", temp_path / "runtime" / "workers.jsonl"),
                patch.object(eve_openclaw_body, "run_openclaw_json_command", return_value=fake_command_result),
            ):
                plan = eve.build_openclaw_worker_plan(
                    worker_kind="audit",
                    parent_intention="verify strict worker contract",
                    prompt="Return strict JSON.",
                    source="unit_test",
                    timeout=30,
                )
                result = eve.run_openclaw_worker_plan(plan, dry_run=False)

            self.assertTrue(result["ok"])
            records = eve_store.read_jsonl_records(temp_path / "workers.jsonl")
            self.assertEqual("ready", records[0]["status"])
            self.assertTrue(records[0]["worker_strict_json"]["ok"])

    def test_openclaw_channel_inventory_records_read_only_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            def fake_command(command, timeout=30):
                if command[:2] == ["channels", "list"]:
                    return {"ok": True, "command": command, "payload": {"chat": {"slack": {}}}}
                if command[:2] == ["channels", "status"]:
                    return {"ok": True, "command": command, "payload": {"channelOrder": ["slack"]}}
                if command[:2] == ["channels", "capabilities"]:
                    return {"ok": True, "command": command, "payload": {"channel": "slack", "send": True}}
                return {"ok": False, "command": command, "payload": {}}

            with (
                patch.object(eve_openclaw_body, "OPENCLAW_CHANNEL_EVENTS_PATH", temp_path / "channels.jsonl"),
                patch.object(eve_openclaw_body, "RUNTIME_OPENCLAW_CHANNEL_EVENTS_PATH", temp_path / "runtime" / "channels.jsonl"),
                patch.object(eve_openclaw_body, "run_openclaw_json_command", side_effect=fake_command),
            ):
                result = eve.run_openclaw_channel_inventory(timeout=5, source="unit_test")

            self.assertTrue(result["ok"])
            self.assertEqual(["slack"], result["configured_channels"])
            records = eve_store.read_jsonl_records(temp_path / "channels.jsonl")
            self.assertEqual(1, len(records))
            self.assertEqual("openclaw_channel_inventory", records[0]["event_type"])
            self.assertFalse(records[0]["external_send_attempted"])
            self.assertFalse(records[0]["canonical_memory_authority"])

    def test_openclaw_channel_inventory_gives_capabilities_longer_budget(self):
        calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            def fake_command(command, timeout=30):
                calls.append((command, timeout))
                if command[:2] == ["channels", "list"]:
                    return {"ok": True, "command": command, "payload": {"chat": {"imessage": ["default"]}}}
                if command[:2] == ["channels", "status"]:
                    return {"ok": True, "command": command, "payload": {"channelOrder": ["imessage"]}}
                if command[:2] == ["channels", "capabilities"]:
                    return {"ok": True, "command": command, "payload": {"channel": "imessage", "send": True}}
                return {"ok": False, "command": command, "payload": {}}

            with (
                patch.object(eve_openclaw_body, "OPENCLAW_CHANNEL_EVENTS_PATH", temp_path / "channels.jsonl"),
                patch.object(eve_openclaw_body, "RUNTIME_OPENCLAW_CHANNEL_EVENTS_PATH", temp_path / "runtime" / "channels.jsonl"),
                patch.object(eve_openclaw_body, "run_openclaw_json_command", side_effect=fake_command),
            ):
                result = eve.run_openclaw_channel_inventory(timeout=5, source="unit_test")

        self.assertTrue(result["ok"])
        list_timeout = next(timeout for command, timeout in calls if command[:2] == ["channels", "list"])
        status_timeout = next(timeout for command, timeout in calls if command[:2] == ["channels", "status"])
        capability_timeout = next(timeout for command, timeout in calls if command[:2] == ["channels", "capabilities"])
        self.assertEqual(5, list_timeout)
        self.assertEqual(5, status_timeout)
        self.assertEqual(eve.OPENCLAW_CHANNEL_CAPABILITY_TIMEOUT_SECONDS, capability_timeout)

    def test_openclaw_channel_inventory_flags_configured_channel_down(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            def fake_command(command, timeout=30):
                if command[:2] == ["channels", "list"]:
                    return {"ok": True, "command": command, "payload": {"chat": {"imessage": ["default"]}}}
                if command[:2] == ["channels", "status"]:
                    return {
                        "ok": True,
                        "command": command,
                        "payload": {
                            "channelOrder": ["imessage"],
                            "channels": {
                                "imessage": {
                                    "configured": True,
                                    "running": False,
                                    "lastError": "permission denied",
                                }
                            },
                            "channelAccounts": {
                                "imessage": [
                                    {
                                        "accountId": "default",
                                        "configured": True,
                                        "enabled": True,
                                        "running": False,
                                        "lastError": "permission denied",
                                    }
                                ]
                            },
                        },
                    }
                if command[:2] == ["channels", "capabilities"]:
                    return {
                        "ok": True,
                        "command": command,
                        "payload": {
                            "channels": [
                                {
                                    "channel": "imessage",
                                    "accountId": "default",
                                    "configured": True,
                                    "enabled": True,
                                    "probe": {"ok": False, "error": "permission denied"},
                                }
                            ]
                        },
                    }
                return {"ok": False, "command": command, "payload": {}}

            with (
                patch.object(eve_openclaw_body, "OPENCLAW_CHANNEL_EVENTS_PATH", temp_path / "channels.jsonl"),
                patch.object(eve_openclaw_body, "RUNTIME_OPENCLAW_CHANNEL_EVENTS_PATH", temp_path / "runtime" / "channels.jsonl"),
                patch.object(eve_openclaw_body, "run_openclaw_json_command", side_effect=fake_command),
            ):
                result = eve.run_openclaw_channel_inventory(timeout=5, source="unit_test")

            self.assertFalse(result["ok"])
            self.assertEqual(["imessage"], result["configured_channels"])
            self.assertGreaterEqual(len(result["channel_health_issues"]), 1)
            records = eve_store.read_jsonl_records(temp_path / "channels.jsonl")
            self.assertEqual("degraded", records[0]["status"])
            self.assertFalse(records[0]["ok"])
            self.assertGreaterEqual(len(records[0]["payload"]["channel_health_issues"]), 1)

    def test_openclaw_channel_inventory_uses_status_as_liveness_authority(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            def fake_command(command, timeout=30):
                if command[:2] == ["channels", "list"]:
                    return {"ok": True, "command": command, "payload": {"chat": {"imessage": ["default"]}}}
                if command[:2] == ["channels", "status"]:
                    return {
                        "ok": True,
                        "command": command,
                        "payload": {
                            "channelOrder": ["imessage"],
                            "channels": {
                                "imessage": {
                                    "configured": True,
                                    "running": True,
                                    "lastError": None,
                                }
                            },
                            "channelAccounts": {
                                "imessage": [
                                    {
                                        "accountId": "default",
                                        "configured": True,
                                        "enabled": True,
                                        "running": True,
                                        "lastError": None,
                                    }
                                ]
                            },
                        },
                    }
                if command[:2] == ["channels", "capabilities"]:
                    return {
                        "ok": True,
                        "command": command,
                        "payload": {
                            "channels": [
                                {
                                    "channel": "imessage",
                                    "accountId": "default",
                                    "configured": True,
                                    "enabled": True,
                                    "probe": {"ok": False, "error": "imsg rpc usage text"},
                                }
                            ]
                        },
                    }
                return {"ok": False, "command": command, "payload": {}}

            with (
                patch.object(eve_openclaw_body, "OPENCLAW_CHANNEL_EVENTS_PATH", temp_path / "channels.jsonl"),
                patch.object(eve_openclaw_body, "RUNTIME_OPENCLAW_CHANNEL_EVENTS_PATH", temp_path / "runtime" / "channels.jsonl"),
                patch.object(eve_openclaw_body, "run_openclaw_json_command", side_effect=fake_command),
            ):
                result = eve.run_openclaw_channel_inventory(timeout=5, source="unit_test")

            self.assertTrue(result["ok"])
            self.assertEqual([], result["channel_health_issues"])
            records = eve_store.read_jsonl_records(temp_path / "channels.jsonl")
            self.assertEqual("ready", records[0]["status"])

    def test_openclaw_channel_inventory_does_not_fail_for_deliberately_disabled_channel(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            def fake_command(command, timeout=30):
                if command[:2] == ["channels", "list"]:
                    return {"ok": True, "command": command, "payload": {"chat": {"imessage": ["default"]}}}
                if command[:2] == ["channels", "status"]:
                    return {
                        "ok": True,
                        "command": command,
                        "payload": {
                            "channelOrder": ["imessage"],
                            "channels": {
                                "imessage": {
                                    "configured": True,
                                    "running": False,
                                    "lastError": "disabled",
                                }
                            },
                            "channelAccounts": {
                                "imessage": [
                                    {
                                        "accountId": "default",
                                        "configured": True,
                                        "enabled": False,
                                        "running": False,
                                        "lastError": "disabled",
                                    }
                                ]
                            },
                        },
                    }
                if command[:2] == ["channels", "capabilities"]:
                    return {
                        "ok": True,
                        "command": command,
                        "payload": {
                            "channels": [
                                {
                                    "channel": "imessage",
                                    "accountId": "default",
                                    "configured": True,
                                    "enabled": False,
                                    "probe": {"ok": False, "error": "Full Disk Access unavailable"},
                                }
                            ]
                        },
                    }
                return {"ok": False, "command": command, "payload": {}}

            with (
                patch.object(eve_openclaw_body, "OPENCLAW_CHANNEL_EVENTS_PATH", temp_path / "channels.jsonl"),
                patch.object(eve_openclaw_body, "RUNTIME_OPENCLAW_CHANNEL_EVENTS_PATH", temp_path / "runtime" / "channels.jsonl"),
                patch.object(eve_openclaw_body, "run_openclaw_json_command", side_effect=fake_command),
            ):
                result = eve.run_openclaw_channel_inventory(timeout=5, source="unit_test")

            self.assertTrue(result["ok"])
            self.assertEqual([], result["channel_health_issues"])

    def test_openclaw_channel_draft_records_no_send_attempt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            def fake_command(command, timeout=30):
                if command[:2] == ["channels", "list"]:
                    return {"ok": True, "command": command, "payload": {"chat": {}}}
                if command[:2] == ["channels", "status"]:
                    return {"ok": True, "command": command, "payload": {"channelOrder": []}}
                return {"ok": False, "command": command, "payload": {}}

            with (
                patch.object(eve_openclaw_body, "OPENCLAW_CHANNEL_EVENTS_PATH", temp_path / "channels.jsonl"),
                patch.object(eve_openclaw_body, "RUNTIME_OPENCLAW_CHANNEL_EVENTS_PATH", temp_path / "runtime" / "channels.jsonl"),
                patch.object(eve_openclaw_body, "run_openclaw_json_command", side_effect=fake_command) as run_command,
            ):
                result = eve.run_openclaw_channel_draft(
                    channel="slack",
                    target="channel:C123",
                    message="draft only",
                    source="unit_test",
                    timeout=5,
                )

            self.assertTrue(result["ok"])
            self.assertFalse(any(call.args[0][:2] == ["message", "send"] for call in run_command.call_args_list))
            records = eve_store.read_jsonl_records(temp_path / "channels.jsonl")
            self.assertEqual(1, len(records))
            self.assertEqual("openclaw_channel_draft", records[0]["event_type"])
            self.assertEqual("draft_only", records[0]["permission_level"])
            self.assertFalse(records[0]["external_send_attempted"])
            self.assertFalse(records[0]["payload"]["channel_configured"])

    def test_openclaw_channel_send_blocks_without_approval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            with (
                patch.object(eve_openclaw_body, "OPENCLAW_CHANNEL_EVENTS_PATH", temp_path / "channels.jsonl"),
                patch.object(eve_openclaw_body, "RUNTIME_OPENCLAW_CHANNEL_EVENTS_PATH", temp_path / "runtime" / "channels.jsonl"),
                patch.object(eve_openclaw_body, "run_openclaw_json_command") as run_command,
            ):
                result = eve.run_openclaw_channel_send(
                    channel="slack",
                    target="channel:C123",
                    message="send attempt",
                    source="unit_test",
                    timeout=5,
                )

            self.assertFalse(result["ok"])
            run_command.assert_not_called()
            records = eve_store.read_jsonl_records(temp_path / "channels.jsonl")
            self.assertEqual(1, len(records))
            self.assertEqual("blocked", records[0]["status"])
            self.assertFalse(records[0]["external_send_attempted"])

    def test_openclaw_channel_pairing_inventory_never_approves(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            def fake_command(command, timeout=30):
                return {
                    "ok": True,
                    "command": command,
                    "payload": {"channel": "imessage", "requests": [{"id": "+15551234567", "code": "ABCDEFGH"}]},
                }

            with (
                patch.object(eve_openclaw_body, "OPENCLAW_CHANNEL_EVENTS_PATH", temp_path / "channels.jsonl"),
                patch.object(eve_openclaw_body, "RUNTIME_OPENCLAW_CHANNEL_EVENTS_PATH", temp_path / "runtime" / "channels.jsonl"),
                patch.object(eve_openclaw_body, "run_openclaw_json_command", side_effect=fake_command) as run_command,
            ):
                result = eve.run_openclaw_channel_pairing_inventory(
                    channel="imessage",
                    account="default",
                    source="unit_test",
                    timeout=5,
                )

            self.assertTrue(result["ok"])
            self.assertEqual(1, result["pending_request_count"])
            self.assertTrue(all("approve" not in call.args[0] for call in run_command.call_args_list))
            records = eve_store.read_jsonl_records(temp_path / "channels.jsonl")
            self.assertEqual("openclaw_channel_pairing_inventory", records[0]["event_type"])
            self.assertFalse(records[0]["external_send_attempted"])

    def test_openclaw_channel_directory_self_degrades_on_interactive_prompt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            def fake_command(command, timeout=30):
                if command[:2] == ["channels", "list"]:
                    return {"ok": True, "command": command, "payload": {"chat": {"imessage": ["default"]}}}
                if command[:2] == ["channels", "status"]:
                    return {"ok": True, "command": command, "payload": {"channelOrder": ["imessage"]}}
                if command[:2] == ["channels", "capabilities"]:
                    return {"ok": True, "command": command, "payload": {"channel": "imessage", "send": True}}
                if command[:2] == ["directory", "self"]:
                    return {
                        "ok": False,
                        "command": command,
                        "stdout_excerpt": "Install iMessage plugin? Proceed?",
                        "payload": {"raw": "Install iMessage plugin? Proceed?"},
                    }
                return {"ok": False, "command": command, "payload": {}}

            with (
                patch.object(eve_openclaw_body, "OPENCLAW_CHANNEL_EVENTS_PATH", temp_path / "channels.jsonl"),
                patch.object(eve_openclaw_body, "RUNTIME_OPENCLAW_CHANNEL_EVENTS_PATH", temp_path / "runtime" / "channels.jsonl"),
                patch.object(eve_openclaw_body, "run_openclaw_json_command", side_effect=fake_command),
            ):
                result = eve.run_openclaw_channel_directory_self(
                    channel="imessage",
                    account="default",
                    source="unit_test",
                    timeout=5,
                )

            self.assertFalse(result["ok"])
            records = eve_store.read_jsonl_records(temp_path / "channels.jsonl")
            self.assertEqual("openclaw_channel_directory_self", records[0]["event_type"])
            self.assertEqual("degraded", records[0]["status"])
            self.assertTrue(records[0]["payload"]["interactive_prompt_detected"])
            self.assertFalse(records[0]["external_send_attempted"])

    def test_openclaw_model_smoke_downgrades_runtime_error_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_command_result = {
                "ok": True,
                "command": ["openclaw", "--profile", "eve-repair", "capability", "model", "run"],
                "returncode": 0,
                "payload": {
                    "ok": True,
                    "outputs": [{"text": "Message ordering conflict - please try again"}],
                },
            }

            with (
                patch.object(eve_openclaw_body, "OPENCLAW_EVIDENCE_EVENTS_PATH", temp_path / "evidence.jsonl"),
                patch.object(eve_openclaw_body, "RUNTIME_OPENCLAW_EVIDENCE_EVENTS_PATH", temp_path / "runtime" / "evidence.jsonl"),
                patch.object(eve, "run_openclaw_configured_model_direct", return_value={"attempted": False, "ok": False}),
                patch.object(eve_openclaw_body, "run_openclaw_json_command", return_value=fake_command_result) as run_command,
            ):
                result = eve.run_openclaw_model_smoke(
                    model="llamacpp/eve-fast",
                    prompt="Return exactly OK.",
                    expect_contains="OK",
                    timeout=5,
                    source="unit_test",
                )

            self.assertFalse(result["ok"])
            self.assertIn("runtime_error:message ordering conflict", result["failure_reasons"])
            self.assertIn("missing_expected_text:OK", result["failure_reasons"])
            self.assertIn("--local", run_command.call_args.args[0])
            records = eve_store.read_jsonl_records(temp_path / "evidence.jsonl")
            self.assertEqual("openclaw_capability_model_smoke", records[0]["event_type"])
            self.assertEqual("degraded", records[0]["status"])
            self.assertFalse(records[0]["external_send_attempted"])

    def test_openclaw_model_smoke_accepts_expected_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_command_result = {
                "ok": True,
                "command": ["openclaw", "--profile", "eve-repair", "capability", "model", "run"],
                "returncode": 0,
                "payload": {"ok": True, "outputs": [{"text": "OK"}]},
            }

            with (
                patch.object(eve_openclaw_body, "OPENCLAW_EVIDENCE_EVENTS_PATH", temp_path / "evidence.jsonl"),
                patch.object(eve_openclaw_body, "RUNTIME_OPENCLAW_EVIDENCE_EVENTS_PATH", temp_path / "runtime" / "evidence.jsonl"),
                patch.object(eve, "run_openclaw_configured_model_direct", return_value={"attempted": False, "ok": False}),
                patch.object(eve_openclaw_body, "run_openclaw_json_command", return_value=fake_command_result),
            ):
                result = eve.run_openclaw_model_smoke(
                    model="llamacpp/eve-fast",
                    prompt="Return exactly OK.",
                    expect_contains="OK",
                    timeout=5,
                    source="unit_test",
                )

            self.assertTrue(result["ok"])
            records = eve_store.read_jsonl_records(temp_path / "evidence.jsonl")
            self.assertEqual("ready", records[0]["status"])

    def test_openclaw_model_smoke_prefers_configured_provider_direct_probe(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            direct_result = {
                "ok": True,
                "attempted": True,
                "transport": "configured_provider_direct",
                "provider": "llamacpp",
                "model": "eve-fast",
                "payload": {"status": "completed", "output": [{"content": [{"type": "output_text", "text": "OK"}]}]},
            }

            with (
                patch.object(eve_openclaw_body, "OPENCLAW_EVIDENCE_EVENTS_PATH", temp_path / "evidence.jsonl"),
                patch.object(eve_openclaw_body, "RUNTIME_OPENCLAW_EVIDENCE_EVENTS_PATH", temp_path / "runtime" / "evidence.jsonl"),
                patch.object(eve, "run_openclaw_configured_model_direct", return_value=direct_result),
                patch.object(eve_openclaw_body, "run_openclaw_json_command") as run_command,
            ):
                result = eve.run_openclaw_model_smoke(
                    model="llamacpp/eve-fast",
                    prompt="Return exactly OK.",
                    expect_contains="OK",
                    timeout=5,
                    source="unit_test",
                )

            self.assertTrue(result["ok"])
            self.assertEqual(["OK"], result["output_texts"])
            run_command.assert_not_called()
            records = eve_store.read_jsonl_records(temp_path / "evidence.jsonl")
            self.assertEqual("configured_provider_direct", records[0]["payload"]["mode"])

    def test_legacy_repair_success_is_downgraded(self):
        status = eve_openclaw.sanitize_legacy_repair_status(
            {
                "last_repair_at": "2026-04-25T19:23:45+00:00",
                "last_repair_ok": True,
                "last_repair_summary": "Let me start by reading the current status and doctor output.",
                "last_repair_issue": "",
                "last_repair_next_step": "",
                "last_repair_status": "",
            }
        )

        self.assertFalse(status["last_repair_ok"])
        self.assertEqual("legacy_non_contract", status["last_repair_status"])
        self.assertIn("Legacy non-contract", status["last_repair_summary"])
        self.assertIn("strict JSON contract", status["last_repair_issue"])

    def test_append_sync_history_does_not_double_write_same_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_path = Path(tmpdir) / "openclaw_sync_history.jsonl"
            with patch.object(eve_openclaw, "OPENCLAW_SYNC_HISTORY_PATH", history_path), patch.object(
                eve_openclaw, "RUNTIME_OPENCLAW_SYNC_HISTORY_PATH", history_path
            ):
                eve_openclaw.append_openclaw_sync_history(
                    {
                        "id": "same-path",
                        "timestamp": "2026-04-25T20:24:32+00:00",
                        "ok": True,
                        "summary": "ok",
                        "error": "",
                        "returncode": 0,
                    }
                )

            lines = history_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(1, len(lines))

    def test_record_openclaw_sync_state_clears_stale_sync_repair_loop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            local_state = temp_path / "source" / "state.json"
            runtime_state = temp_path / "runtime" / "state.json"
            local_mind = temp_path / "source" / "active_mind.json"
            runtime_mind = temp_path / "runtime" / "active_mind.json"
            local_workspace = temp_path / "source" / "global_workspace.json"
            runtime_workspace = temp_path / "runtime" / "global_workspace.json"
            stale_state = {
                "last_openclaw_sync_at": "2026-04-22T23:24:34+00:00",
                "last_openclaw_repair_issue": "OpenClaw sync commands are timing out/killed on this machine.",
                "last_openclaw_repair_next_step": "Retry sync in a future repair turn.",
            }
            eve_store.write_json_dict(local_state, dict(stale_state))
            eve_store.write_json_dict(runtime_state, dict(stale_state))
            stale_attention = {
                "current_focus": "The persistent timeouts with the OpenClaw sync are still causing pressure.",
                "live_threads": [{"title": "OpenClaw sync loop saturated", "detail": "OpenClaw sync is failing."}],
                "active_goals": [
                    "The OpenClaw sync timeouts are still persistent.",
                    "OpenClaw sync recovered cleanly at 2026-04-29T07:51:58+00:00; keep watching.",
                ],
            }
            for path in (local_mind, runtime_mind, local_workspace, runtime_workspace):
                eve_store.write_json_dict(path, dict(stale_attention))

            status = {
                "last_sync_at": "2026-04-29T07:51:58+00:00",
                "last_sync_ok": True,
                "last_sync_summary": "Command root: /Users/example/.eve_runtime Wrote OpenClaw sync artifacts.",
                "summary": "OpenClaw reachable. Latest sync recovered cleanly.",
            }

            with patch.object(eve_openclaw, "STATE_PATH", local_state), patch.object(
                eve_openclaw, "RUNTIME_STATE_PATH", runtime_state
            ), patch.object(eve_openclaw, "ACTIVE_MIND_PATH", local_mind), patch.object(
                eve_openclaw, "RUNTIME_ACTIVE_MIND_PATH", runtime_mind
            ), patch.object(eve_openclaw, "GLOBAL_WORKSPACE_PATH", local_workspace), patch.object(
                eve_openclaw, "RUNTIME_GLOBAL_WORKSPACE_PATH", runtime_workspace
            ):
                updated = eve_openclaw.record_openclaw_sync_state(status)

            self.assertEqual(2, updated)
            for path in (local_state, runtime_state):
                state = eve_store.load_json_dict(path)
                self.assertEqual("2026-04-29T07:51:58+00:00", state["last_openclaw_sync_at"])
                self.assertTrue(state["last_openclaw_sync_ok"])
                self.assertEqual("OpenClaw reachable. Latest sync recovered cleanly.", state["openclaw_summary"])
                self.assertEqual("recovered_by_sync", state["last_openclaw_repair_status"])
                self.assertIn("Recovered by successful OpenClaw sync", state["last_openclaw_repair_issue"])
                self.assertNotIn("timing out", state["last_openclaw_repair_issue"])
            for path in (local_mind, runtime_mind, local_workspace, runtime_workspace):
                payload = eve_store.load_json_dict(path)
                rendered = json.dumps(payload)
                self.assertIn("OpenClaw sync recovered cleanly", rendered)
                self.assertNotIn("sync loop saturated", rendered)
                self.assertNotIn("sync is failing", rendered)
                self.assertNotIn("sync timeouts are still persistent", rendered)

    def test_build_openclaw_summary_prefers_recovered_sync_over_stale_probe_failure(self):
        summary = eve_openclaw.build_openclaw_summary(
            {
                "enabled": True,
                "command_available": True,
                "installed": True,
                "gateway_reachable": False,
                "last_sync_ok": True,
                "last_sync_summary": "Command root: /Users/example/.eve_runtime",
                "sync_health_summary": "7 recent OpenClaw sync failure(s), but the latest run recovered.",
            }
        )

        self.assertEqual(
            "OpenClaw reachable. Latest sync recovered cleanly: Command root: /Users/example/.eve_runtime",
            summary,
        )

    def test_parse_noisy_openclaw_json_payload_skips_plugin_logs(self):
        payload = eve_openclaw.parse_noisy_json_payload(
            "[plugins] registered route eveRepair\n"
            '[{"agentId":"main","status":{"provider":"bedrock"}}]'
        )

        self.assertEqual("bedrock", payload[0]["status"]["provider"])

    def test_memory_status_fields_surface_embedding_auth_unavailable(self):
        fields = eve_openclaw.openclaw_memory_status_fields(
            [
                {
                    "agentId": "main",
                    "status": {
                        "provider": "bedrock",
                        "model": "amazon.titan-embed-text-v2:0",
                        "files": 0,
                        "chunks": 0,
                        "dirty": True,
                    },
                    "embeddingProbe": {
                        "ok": False,
                        "error": "Could not load credentials from any providers",
                    },
                }
            ],
            returncode=0,
        )

        self.assertTrue(fields["memory_status_ok"])
        self.assertEqual("unavailable", fields["memory_status_severity"])
        self.assertFalse(fields["memory_capability_available"])
        self.assertEqual("bedrock", fields["memory_provider"])
        self.assertIn("AWS credentials are not configured", fields["memory_status_summary"])

    def test_memory_status_fields_fail_when_json_payload_is_missing(self):
        fields = eve_openclaw.openclaw_memory_status_fields(
            None,
            returncode=0,
            output="not json",
        )

        self.assertFalse(fields["memory_status_ok"])
        self.assertEqual("degraded", fields["memory_status_severity"])
        self.assertIn("not json", fields["memory_status_summary"])

    def test_build_openclaw_summary_prioritizes_memory_degradation(self):
        summary = eve_openclaw.build_openclaw_summary(
            {
                "enabled": True,
                "command_available": True,
                "installed": True,
                "gateway_reachable": True,
                "last_sync_ok": True,
                "last_sync_summary": "Command root: /Users/example/.eve_runtime",
                "memory_status_ok": False,
                "memory_status_summary": "Memory search degraded via bedrock: missing credentials",
            }
        )

        self.assertEqual(
            "OpenClaw reachable, but memory search is degraded: Memory search degraded via bedrock: missing credentials",
            summary,
        )

    def test_build_openclaw_summary_does_not_treat_auth_unavailable_as_outage(self):
        summary = eve_openclaw.build_openclaw_summary(
            {
                "enabled": True,
                "command_available": True,
                "installed": True,
                "gateway_reachable": True,
                "last_sync_ok": True,
                "last_sync_summary": "Command root: /Users/example/.eve_runtime",
                "memory_status_ok": True,
                "memory_status_severity": "unavailable",
                "memory_capability_available": False,
                "memory_status_summary": "Memory embeddings unavailable via bedrock: AWS credentials are not configured",
            }
        )

        self.assertEqual(
            "OpenClaw reachable. Latest sync recovered cleanly: Command root: /Users/example/.eve_runtime",
            summary,
        )

    def test_self_test_treats_restricted_gateway_probe_as_verified_sync_surface(self):
        status = {
            "enabled": True,
            "installed": True,
            "gateway_reachable": False,
            "gateway_status_ok": False,
            "gateway_status_output": (
                "Runtime: running (pid 123, state active) "
                "Listening: 127.0.0.1:19011 "
                "Connectivity probe: failed connect EPERM 127.0.0.1:19011"
            ),
            "profile": "eve-repair",
        }
        sync_result = {
            "ok": True,
            "status": {"last_sync_summary": "Command root: /Users/example/.eve_runtime"},
            "stdout": "Command root: /Users/example/.eve_runtime",
            "stderr": "",
        }

        with patch.object(eve.eve_openclaw, "collect_openclaw_status", return_value=status), patch.object(
            eve.eve_openclaw, "sync_openclaw", return_value=sync_result
        ), patch.object(eve.eve_openclaw, "repair_openclaw") as repair:
            result = eve.run_bounded_openclaw_self_test(eve.DEFAULT_CONFIG, source="test")

        self.assertTrue(result["status_ok"], result)
        self.assertTrue(result["sync_ok"], result)
        self.assertTrue(result["diagnose_ok"], result)
        self.assertTrue(result["metadata"]["diagnose"]["skipped"])
        repair.assert_not_called()

    def test_self_test_skips_stale_repair_narrative_when_fresh_state_is_healthy(self):
        status = {
            "enabled": True,
            "installed": True,
            "gateway_reachable": True,
            "gateway_status_ok": True,
            "gateway_status_output": "Runtime: running; Listening: 127.0.0.1:19011",
            "profile": "eve-repair",
            "plugins_allow_explicit": True,
            "plugins_allow_ok": True,
            "plugins_allow_count": 2,
            "plugins_allow_entries": ["memory-core", "imessage"],
            "plugins_allow_error": "",
        }
        sync_result = {
            "ok": True,
            "status": {"last_sync_summary": "Current sync completed successfully."},
            "stdout": "Current sync completed successfully.",
            "stderr": "",
        }
        repair_result = {
            "ok": True,
            "parsed_reply": {
                "issue": "The plugins.allow list is empty and a sync write lock remains.",
                "why_it_matters": "The old repair context says plugin routing is blocked.",
                "next_bounded_move": "Rewrite plugins.allow.",
            },
        }

        with patch.object(
            eve.eve_openclaw, "collect_openclaw_status", return_value=status
        ), patch.object(
            eve.eve_openclaw, "sync_openclaw", return_value=sync_result
        ), patch.object(
            eve.eve_openclaw, "repair_openclaw", return_value=repair_result
        ) as repair:
            result = eve.run_bounded_openclaw_self_test(
                eve.DEFAULT_CONFIG, source="test"
            )

        self.assertTrue(result["status_ok"], result)
        self.assertTrue(result["sync_ok"], result)
        self.assertTrue(result["plugins_allow_ok"], result)
        self.assertEqual(2, result["plugins_allow_count"])
        self.assertTrue(result["diagnose_ok"], result)
        self.assertIn("No current OpenClaw repair target", result["issue"])
        self.assertIn("2 entries", result["response"])
        self.assertNotIn("Rewrite plugins.allow", result["response"])
        self.assertEqual(
            "current_health_verified", result["metadata"]["diagnose"]["reason"]
        )
        repair.assert_not_called()


if __name__ == "__main__":
    unittest.main()
