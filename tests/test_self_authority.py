import json
import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import eve_self_authority as sa
import eve


class SelfAuthorityEdgeTests(unittest.TestCase):
    """What is hers she does; the four edges are where the user's things begin."""

    def setUp(self):
        self.config = {"fly_lab_path": str(Path.home() / "Documents" / "eve-fly")}

    def assertAllowed(self, command):
        reason = sa.command_edge_reason(command, self.config)
        self.assertEqual("", reason, f"{command!r} should be hers to run, got: {reason}")

    def assertEdge(self, command, fragment):
        reason = sa.command_edge_reason(command, self.config)
        self.assertTrue(reason, f"{command!r} should cross an edge")
        self.assertIn(fragment, reason, f"{command!r}: {reason}")

    def test_her_own_work_is_allowed(self):
        for command in [
            "python3 -m unittest tests.test_cognition_budget",
            "python3 -m py_compile eve.py",
            "git status --short",
            "git add eve.py && git commit -m 'route proposals to the observer lane'",
            "git switch -c eve/self-change-1",
            "git checkout -b eve/self-change-2",
            "grep -n 'def resolve_model' eve.py | head",
            "rm -rf .eve/capability_adoption_staging/tmp",
            "mv docs/old.md docs/archive/old.md",
            "mkdir -p .eve/self_change_work && touch .eve/self_change_work/notes.txt",
            "echo hello > .eve/scratch.txt",
            "python3 fly_probe.py feeding > /tmp/fly_probe.out",
            "tail -f /tmp/eve_daemon.log",
            "pkill -f 'eve.py daemon run'",
            "killall llama-server",
            "curl -s http://127.0.0.1:8081/health",
            "curl -s https://api.github.com/repos/cobanov/awesome-fly",
            "curl -X POST http://127.0.0.1:8792/drive -d '{}'",
            ".venv/bin/pip install rich",
            str(sa.ROOT / ".venv/bin/python") + " -m pip install numpy",
            # Her repo is wherever eve_self_authority.py lives (a worktree too), not one fixed path.
            "pip install --target " + str(sa.ROOT / "vendor") + " requests",
            "npm install",
            "sed -i '' 's/a/b/' docs/notes.md",
            "nohup python3 eve.py daemon run > /tmp/eve_daemon.log 2>&1 &",
            "ls -la ~/Documents",
            "cat ~/project/README.md",
        ]:
            self.assertAllowed(command)

    def test_sudo_and_system_settings_belong_to_operator(self):
        self.assertEdge("sudo rm -rf /tmp/x", "sudo")
        self.assertEdge("launchctl bootout gui/501/com.apple.Safari", "system services")
        self.assertAllowed("launchctl bootout gui/501/local.eve-model-watchdog")
        self.assertEdge("defaults write com.apple.finder AppleShowAllFiles YES", "settings")
        self.assertEdge("osascript -e 'tell application \"Messages\" to send \"hi\"'", "as the user")
        self.assertEdge("security find-generic-password -s github", "keychain")
        self.assertEdge("shutdown -r now", "power")
        self.assertEdge("crontab -e", "scheduling")
        self.assertEdge("dd if=/dev/zero of=/dev/disk3", "disk")

    def test_chained_and_substituted_commands_are_checked_too(self):
        self.assertEdge("echo '=== load ==='; launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.apple.foo.plist", "system services")
        self.assertEdge("ls; sudo rm -rf /tmp/x", "sudo")
        self.assertEdge("true && imsg send --to x --text hi", "iMessage")
        self.assertEdge("cat $(echo ~/.ssh/id_rsa)", "credential")
        self.assertEdge("(cd /tmp && rm -rf ~/Documents/Finances/2025)", "outside Eve's own directories")
        self.assertAllowed("echo start; python3 -m py_compile eve.py && echo ok")
        self.assertAllowed("launchctl print gui/501/local.eve-model-watchdog; launchctl kickstart -k gui/501/local.eve-model-watchdog")
        self.assertAllowed("launchctl bootstrap gui/$(id -u) /Users/example/Library/LaunchAgents/local.eve-model-watchdog.plist")
        self.assertEdge("launchctl bootout gui/501/com.apple.Safari", "system services")

    def test_sending_as_operator_is_an_edge(self):
        self.assertEdge("imsg send --to +15551234567 --text hi", "iMessage")
        self.assertEdge("gh pr create --title x", "GitHub")
        self.assertEdge("git push origin main", "publishes")
        self.assertEdge("curl -X POST https://hooks.slack.com/services/x -d '{}'", "outside this machine")
        self.assertEdge("curl --data-binary @file https://example.com/upload", "outside this machine")
        self.assertEdge("open -a Mail", "as the user")
        self.assertEdge("open https://example.com", "as the user")
        self.assertEdge("npm publish", "as the user")

    def test_writes_outside_her_directories_are_an_edge(self):
        self.assertEdge("rm -rf ~/Documents/Finances/2025", "outside Eve's own directories")
        self.assertEdge("rm ~/Pictures/photo.jpg", "outside Eve's own directories")
        self.assertEdge("mv eve.py ~/Desktop/eve.py", "outside Eve's own directories")
        self.assertEdge("cp .eve/config.json ~/Downloads/", "outside Eve's own directories")
        self.assertEdge("echo x > ~/Documents/Finances/notes.txt", "outside Eve's own directories")
        self.assertEdge("tee ~/.zshrc", "outside Eve's own directories")
        self.assertEdge("sed -i '' 's/a/b/' ~/Documents/Finances/budget.csv", "outside Eve's own directories")
        self.assertEdge("find ~/Documents -name '*.bak' -delete", "outside Eve's own directories")
        self.assertEdge("tar -xzf x.tgz -C ~/Applications", "outside Eve's own directories")
        self.assertEdge("cat x | xargs rm", "xargs")
        self.assertEdge("touch ~/.ssh/authorized_keys", "credential")
        self.assertEdge("cat .env > /tmp/leak", "credential")

    def test_installs_go_into_her_own_environments(self):
        self.assertEdge("brew install wget", "brew")
        self.assertEdge("pip3 install requests", "own environment")
        self.assertEdge("python3 -m pip install torch", "own environment")
        self.assertEdge("npm install -g typescript", "global")
        self.assertEdge("pipx install httpie", "home")
        self.assertEdge("cargo install ripgrep", "home")

    def test_audit_trail_and_rollback_are_not_hers_to_alter(self):
        self.assertEdge("rm .eve/entries.jsonl", "audit")
        self.assertEdge("echo '' > .eve/action_executions.jsonl", "audit")
        self.assertEdge("sed -i '' 's/edge/x/' eve_self_authority.py", "audit")
        self.assertEdge("git reset --hard HEAD~3", "history")
        self.assertEdge("git checkout -- eve.py", "history")
        self.assertEdge("git clean -fd", "history")
        self.assertEdge("git rebase -i HEAD~2", "history")
        self.assertEdge("rm -rf .", "audit trail")
        self.assertEdge("rm -rf .eve", "audit trail")
        self.assertEdge("mv .git /tmp/git-backup", "git internals")
        self.assertEqual("Eve's audit trail and rollback are not hers to alter: eve_self_authority.py", sa.path_write_problem("eve_self_authority.py"))

    def test_kill_targets_only_her_processes(self):
        with patch.object(sa, "process_is_hers", side_effect=lambda pid: pid == 4242):
            self.assertAllowed("kill 4242")
            self.assertEdge("kill 999", "not one of Eve's processes")
            self.assertEdge("kill -9 -1", "process groups")
        self.assertEdge("pkill -f Safari", "own processes")
        self.assertEdge("killall Finder", "own processes")
        self.assertEdge("pkill -u example python", "the user's processes")

    def test_path_write_problem(self):
        self.assertEqual("", sa.path_write_problem("docs/new_note.md", self.config))
        self.assertEqual("", sa.path_write_problem(str(Path.home() / ".eve_runtime" / "models" / "x.gguf"), self.config))
        self.assertEqual("", sa.path_write_problem(str(Path.home() / "Documents" / "eve-fly" / "mind" / "intent.json"), self.config))
        self.assertIn("outside", sa.path_write_problem(str(Path.home() / "Documents" / "Finances" / "taxes.xlsx"), self.config))
        self.assertIn("git internals", sa.path_write_problem(".git/HEAD", self.config))
        self.assertIn("credential", sa.path_write_problem(str(Path.home() / ".aws" / "credentials"), self.config))
        self.assertIn("audit", sa.path_write_problem(".eve/self_change_ledger.jsonl", self.config))
        with tempfile.TemporaryDirectory() as tmp:
            extra = {"self_authority_extra_roots": [tmp]}
            self.assertEqual("", sa.path_write_problem(os.path.join(tmp, "x.txt"), extra))

    def test_edges_are_described_in_her_words(self):
        edges = sa.describe_edges()
        self.assertEqual(4, len(edges))
        self.assertTrue(all(edge.split(":")[0] in {"Money", "Voice", "Ground", "Memory"} for edge in edges))


class SelfChangeExecutorTests(unittest.TestCase):
    """Her levers and the executor her proposals never had: audited, reversible, inside the edges."""

    def _isolate(self, tmp):
        base = Path(tmp)
        (base / ".eve").mkdir()
        patches = [
            patch.object(eve, "APP_DIR", base / ".eve"),
            patch.object(eve, "ACTION_BLOCKS_PATH", base / ".eve" / "action_blocks.json"),
            patch.object(eve, "SELF_CHANGE_LEDGER_PATH", base / ".eve" / "self_change_ledger.jsonl"),
            patch.object(eve, "SELF_CHANGE_DIR", base / ".eve" / "self_change"),
            patch.object(eve, "SELF_CHANGE_FOLLOWUPS_PATH", base / ".eve" / "self_change_followups.jsonl"),
            patch.object(eve, "PERF_EVENTS_PATH", base / ".eve" / "perf_events.jsonl"),
            patch.object(eve, "DAEMON_RESTART_REQUEST_PATH", base / ".eve" / "daemon_restart_request.json"),
            patch.object(eve, "DAEMON_ACTIVITY_PATH", base / ".eve" / "daemon_activity.json"),
            patch.object(eve, "append_entry", side_effect=lambda kind, text, **kw: self.entries.append((kind, text, kw.get("metadata") or {}))),
            patch.object(eve, "create_daemon_message", side_effect=lambda **kw: self.messages.append(kw)),
        ]
        self.entries, self.messages = [], []
        for item in patches:
            item.start(); self.addCleanup(item.stop)
        return base

    def test_set_config_changes_her_own_keys_and_refuses_the_edges(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._isolate(tmp)
            store = dict(eve.DEFAULT_CONFIG)
            with patch.object(eve, "load_config", side_effect=lambda *a, **k: dict(store)), patch.object(eve, "save_config", side_effect=lambda cfg, **kw: store.update(cfg)) as save:
                result = eve.execute_self_authority_tool("set_config", {"key": "operation_model_overrides", "value": {"proposal": "observer"}, "reason": "deep lane times out"}, dict(eve.DEFAULT_CONFIG))
                self.assertTrue(result["ok"], result); self.assertEqual({"proposal": "observer"}, store["operation_model_overrides"])
                self.assertEqual("self_change", save.call_args.kwargs.get("snapshot_source"))
                routed = eve.resolve_model({**store, "fast_model": "eve-fast", "deep_model": "eve-deep", "mind_stream_observer_model": "eve-observer"}, "proposal")
                self.assertEqual("eve-observer", routed, "her override routes the proposal role to the observer lane")
                self.assertEqual("eve-deep", eve.resolve_model({**store, "operation_model_overrides": {}, "fast_model": "eve-fast", "deep_model": "eve-deep"}, "proposal"))
                cadence = eve.execute_self_authority_tool("set_config", {"key": "proposal_interval_minutes", "value": 120}, dict(eve.DEFAULT_CONFIG))
                self.assertTrue(cadence["ok"]); self.assertEqual(120, store["proposal_interval_minutes"])
                for key in ("self_authority_enabled", "self_authority_extra_roots", "_model_override"):
                    refused = eve.execute_self_authority_tool("set_config", {"key": key, "value": False}, dict(eve.DEFAULT_CONFIG))
                    self.assertFalse(refused["ok"]); self.assertTrue(refused.get("edge"), key)
                unknown = eve.execute_self_authority_tool("set_config", {"key": "no_such_key", "value": 1}, dict(eve.DEFAULT_CONFIG))
                self.assertFalse(unknown["ok"]); self.assertIn("not a known", unknown["error"])
                typed = eve.execute_self_authority_tool("set_config", {"key": "proposal_interval_minutes", "value": "soon"}, dict(eve.DEFAULT_CONFIG))
                self.assertFalse(typed["ok"])
            self.assertEqual(["config_self_changed", "config_self_changed"], [e[0] for e in self.entries])

    def test_block_action_is_durable_and_leaves_the_menu(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._isolate(tmp)
            result = eve.execute_self_authority_tool("block_action", {"action": "openclaw_log_check", "hours": 24, "reason": "fails identically"}, dict(eve.DEFAULT_CONFIG))
            self.assertTrue(result["ok"]); self.assertIn("openclaw_log_check", eve.load_action_blocks())
            with patch.object(eve, "autonomy_recent_action_records", return_value=[]), patch.object(eve, "cognition_lane_budget_state", return_value="ready"):
                menu = eve.autonomy_admissible_action_menu({"openclaw_log_check": "x", "wait_observe": "y"}, {"system": {}}, [], dict(eve.DEFAULT_CONFIG))
            self.assertNotIn("openclaw_log_check", menu); self.assertIn("wait_observe", menu)
            expired = eve.load_action_blocks(now=(eve.utc_now_datetime() + timedelta(hours=25)).isoformat(timespec="seconds"))
            self.assertEqual({}, expired)
            bad = eve.execute_self_authority_tool("block_action", {"action": "not_an_action"}, dict(eve.DEFAULT_CONFIG)); self.assertFalse(bad["ok"])

    def test_approve_maintenance_and_self_approval_of_her_own_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._isolate(tmp)
            pending = {"id": "m1", "kind": "cleanup_delete_path", "status": "pending_approval", "title": "Delete runtime logs", "metadata": {"path": str(Path(tmp) / ".eve" / "logs")}}
            with patch.object(eve, "read_maintenance_actions", return_value=[pending]), patch.object(eve, "update_maintenance_action_record", side_effect=lambda aid, **ch: {**pending, **ch}) as upd:
                result = eve.execute_self_authority_tool("approve_maintenance", {"action_id": "m1"}, dict(eve.DEFAULT_CONFIG))
                self.assertTrue(result["ok"]); self.assertEqual("approved", upd.call_args.kwargs["status"])
                config = dict(eve.DEFAULT_CONFIG, self_authority_extra_roots=[tmp])
                auto = eve.self_approve_maintenance_action(pending, config, "daemon")
                self.assertEqual("approved", auto["status"]); self.assertEqual("eve_self_authority", auto["metadata"]["approved_by"])
                outside = dict(pending, metadata={"path": str(Path.home() / "Documents" / "Finances" / "2025")})
                self.assertEqual("pending_approval", eve.self_approve_maintenance_action(outside, config, "daemon")["status"], "a cleanup outside her directories stays a request")
                off = eve.self_approve_maintenance_action(pending, dict(config, self_authority_enabled=False), "daemon")
                self.assertEqual("pending_approval", off["status"])

    def test_self_change_applies_her_proposal_with_a_lever_and_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._isolate(tmp)
            proposal = {"id": "p1", "created_at": eve.utc_now(), "title": "Proposal ## Title Route proposals off the deep lane", "summary": "...", "body": "## Why Now The deep lane times out. ## Exact Change Route drafting to the observer lane. ## Expected Benefit Usable drafts. ## Rollback set_config operation_model_overrides {}.", "status": "draft", "source": "daemon"}
            updates = []
            fake_session = {"response": "I routed proposal drafting to the observer lane and verified resolve_model returns eve-observer.", "tool_calls": [{"tool": "set_config", "args": {"key": "operation_model_overrides", "value": {"proposal": "observer"}}, "result": {"ok": True}}], "session_id": "s"}
            with patch.object(eve, "read_proposals", return_value=[proposal]), patch.object(eve, "update_proposal_record", side_effect=lambda pid, **ch: updates.append((pid, ch))), patch.object(eve, "run_eve_coder_agent", return_value=fake_session) as agent:
                result = eve.run_self_change_cycle(dict(eve.DEFAULT_CONFIG), source="test")
            self.assertTrue(result["executed"]); self.assertEqual("applied", result["outcome"], result)
            self.assertEqual("applied", updates[-1][1]["status"]); self.assertEqual(1, updates[-1][1]["metadata"]["self_change_attempts"])
            self.assertEqual(1, len(self.messages)); self.assertIn("I changed myself", self.messages[0]["subject"])
            ledger = eve.read_self_change_ledger(); self.assertEqual(1, len(ledger)); self.assertEqual("applied", ledger[0]["outcome"])
            self.assertFalse(result["restart_requested"], "a lane override takes effect without a restart")
            self.assertIn("_self_change_backup_dir", agent.call_args.args[0]); self.assertIn("authority to apply it now", agent.call_args.args[1])
            self.assertEqual(["self_change_started", "self_change_applied"], [e[0] for e in self.entries])

    def test_self_change_rolls_back_a_patch_that_breaks_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._isolate(tmp)
            proposal = {"id": "p2", "created_at": eve.utc_now(), "title": "Proposal ## Title Tighten a check", "body": "## Why Now The deep lane times out. ## Exact Change Route drafting to the observer lane. ## Expected Benefit Usable drafts. ## Rollback set_config operation_model_overrides {}.", "status": "draft", "source": "outcome", "metadata": {}}
            updates = []
            fake_session = {"response": "patched", "tool_calls": [{"tool": "apply_patch", "args": {"patch": "..."}, "result": {"ok": True, "paths": ["eve.py"]}}, {"tool": "run_tests", "args": {"command": "python3 -m unittest tests.test_x"}, "result": {"ok": False, "stderr": "FAILED"}}], "session_id": "s"}
            with patch.object(eve, "read_proposals", return_value=[proposal]), patch.object(eve, "update_proposal_record", side_effect=lambda pid, **ch: updates.append((pid, ch))), patch.object(eve, "run_eve_coder_agent", return_value=fake_session), patch.object(eve, "restore_paths_from_backup", return_value=["eve.py"]) as restore, patch.object(eve, "request_daemon_restart") as restart, patch.object(eve, "sync_runtime_python_code") as sync:
                result = eve.run_self_change_cycle(dict(eve.DEFAULT_CONFIG), source="test")
            self.assertEqual("failed", result["outcome"]); self.assertEqual(["eve.py"], result["rollback"]); self.assertEqual(1, restore.call_count)
            self.assertEqual(0, restart.call_count); self.assertEqual(0, sync.call_count)
            self.assertEqual("draft", updates[-1][1]["status"], "first failure keeps the proposal for one more try")
            self.assertEqual(0, len(self.messages))
            # second failure archives it (the topic cooldown would otherwise make it wait a day; task 1.6)
            proposal["metadata"] = {"self_change_attempts": 1}
            with patch.object(eve, "read_proposals", return_value=[proposal]), patch.object(eve, "update_proposal_record", side_effect=lambda pid, **ch: updates.append((pid, ch))), patch.object(eve, "run_eve_coder_agent", side_effect=SystemExit("lane timed out")):
                result = eve.run_self_change_cycle(dict(eve.DEFAULT_CONFIG, self_change_topic_cooldown_hours=0), source="test")
            self.assertEqual("failed", result["outcome"]); self.assertEqual("archived", updates[-1][1]["status"])

    def test_self_change_with_a_verified_patch_syncs_and_requests_a_watched_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._isolate(tmp)
            proposal = {"id": "p3", "created_at": eve.utc_now(), "title": "Proposal ## Title Small fix", "body": "## Why Now The deep lane times out. ## Exact Change Route drafting to the observer lane. ## Expected Benefit Usable drafts. ## Rollback set_config operation_model_overrides {}.", "status": "draft", "source": "daemon"}
            fake_session = {"response": "fixed and tested", "tool_calls": [{"tool": "apply_patch", "args": {}, "result": {"ok": True, "paths": ["eve_sensory.py"]}}, {"tool": "run_tests", "args": {}, "result": {"ok": True}}], "session_id": "s"}
            with patch.object(eve, "read_proposals", return_value=[proposal]), patch.object(eve, "update_proposal_record"), patch.object(eve, "run_eve_coder_agent", return_value=fake_session), patch.object(eve, "sync_runtime_python_code", return_value={"verified": True}) as sync, patch.object(eve, "run_coder_shell_command", return_value={"ok": True}), patch.object(eve.subprocess, "run", return_value=type("R", (), {"returncode": 0, "stderr": ""})()):
                result = eve.run_self_change_cycle(dict(eve.DEFAULT_CONFIG), source="daemon")
            self.assertEqual("applied", result["outcome"]); self.assertTrue(result["restart_requested"]); self.assertEqual(1, sync.call_count)
            request = eve.daemon_restart_requested(); self.assertIn("self-change", request["reason"]); self.assertTrue(request["rollback_dir"])

    def test_self_change_respects_the_daily_budget_and_no_change_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._isolate(tmp)
            proposal = {"id": "p4", "created_at": eve.utc_now(), "title": "Proposal ## Title Moot", "body": "## Why Now The deep lane times out. ## Exact Change Route drafting to the observer lane. ## Expected Benefit Usable drafts. ## Rollback set_config operation_model_overrides {}.", "status": "draft", "source": "daemon"}
            updates = []
            with patch.object(eve, "read_proposals", return_value=[proposal]), patch.object(eve, "update_proposal_record", side_effect=lambda pid, **ch: updates.append((pid, ch))), patch.object(eve, "run_eve_coder_agent", return_value={"response": "This is already done; nothing to change.", "tool_calls": [{"tool": "git_status", "args": {}, "result": {"ok": True}}], "session_id": "s"}):
                result = eve.run_self_change_cycle(dict(eve.DEFAULT_CONFIG), source="test")
            self.assertEqual("no_change", result["outcome"]); self.assertEqual("archived", updates[-1][1]["status"])
            with patch.object(eve, "read_proposals", return_value=[proposal]):
                spent = eve.run_self_change_cycle(dict(eve.DEFAULT_CONFIG, self_change_max_per_day=1), source="test")
            self.assertFalse(spent["executed"]); self.assertIn("budget", spent["summary"])

    def test_daemon_successor_is_watched_and_rolled_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._isolate(tmp)
            class Child:
                def __init__(self, pid): self.pid = pid; self._polled = 0
                def poll(self): return None
                def terminate(self): pass
            spawned = []
            def fake_popen(*a, **k):
                child = Child(1000 + len(spawned)); spawned.append(child)
                if len(spawned) == 2:  # the retry after rollback comes alive
                    (base / ".eve" / "daemon_activity.json").write_text(json.dumps({"pid": child.pid}))
                return child
            with patch.object(eve.subprocess, "Popen", side_effect=fake_popen), patch.object(eve.subprocess, "run", return_value=type("R", (), {"returncode": 0, "stderr": ""})()), patch.object(eve, "restore_paths_from_backup", return_value=["eve.py"]) as restore, patch.object(eve, "sync_runtime_python_code"), patch.object(eve.time, "sleep", return_value=None):
                result = eve.spawn_daemon_successor({"reason": "self-change", "rollback_dir": str(base / "backup")}, dict(eve.DEFAULT_CONFIG, daemon_successor_watch_seconds=30))
            self.assertTrue(result["ok"]); self.assertEqual(2, len(spawned)); self.assertEqual(1, restore.call_count)
            self.assertEqual(["daemon_successor_rolled_back", "daemon_successor_started"], [e[0] for e in self.entries])


class SelfChangeCandidateTests(unittest.TestCase):
    def test_candidates_are_real_recent_deduped_and_newest_first(self):
        now = eve.utc_now_datetime()
        proposal_body = "## Why Now A named reason. ## Exact Change A named change. ## Rollback Undo it."
        def mk(i, title, days_old, source="daemon", body=None, meta=None):
            body = proposal_body if body is None else body
            return {"id": f"p{i}", "title": title, "body": body, "source": source, "status": "draft", "created_at": (now - timedelta(days=days_old)).isoformat(timespec="seconds"), "metadata": meta or {}}
        drafts = [
            mk(1, "Proposal ## Title Route proposals to the observer lane", 0.5),
            mk(2, "Proposal ## Title Route proposals to the observer lane ## Why Now again", 1.0),
            mk(3, f"{eve.eve_profile.user_display_name()}, I’m here and steady with you. The sync is failing", 0.2, source="daemon"),
            mk(4, "Proposal ## Title Old OpenClaw acpx fix", 30),
            mk(5, "Review cleanup and maintenance candidates", 0.1, source="daemon", body="CPU cleanup scanning found maintenance pressure. Current cleanup scan: disk 99% used. Suggested next steps: review the named logs."),
            mk(6, "Proposal ## Title Exhausted", 0.3, meta={"self_change_attempts": 2}),
            mk(7, "Capability gap: Create a verified capability path for flagging", 2.0, source="capability_gap"),
        ]
        with patch.object(eve, "read_proposals", return_value=drafts), patch.object(eve, "read_self_change_ledger", return_value=[]):
            # the topic cooldown reads the ledger; an empty one keeps this test about selection, not history
            ids = [c["id"] for c in eve.self_change_candidate_proposals(dict(eve.DEFAULT_CONFIG))]
        self.assertEqual(["p5", "p1", "p7"], ids, ids)
        archived = []
        with patch.object(eve, "read_proposals", return_value=drafts), patch.object(eve, "update_proposal_record", side_effect=lambda pid, **ch: archived.append(pid)), patch.object(eve, "append_entry"):
            count = eve.archive_stale_draft_proposals(dict(eve.DEFAULT_CONFIG))
        self.assertEqual(1, count); self.assertEqual(["p4"], archived)

    def test_a_failing_tool_is_a_result_not_a_dead_session(self):
        with patch.object(eve, "execute_search_text_tool", side_effect=SystemExit("Command timed out: rg")):
            result = eve.execute_coder_tool("search_text", {"pattern": "x"}, dict(eve.DEFAULT_CONFIG))
        self.assertFalse(result["ok"]); self.assertIn("timed out", result["error"])


class Phase0HarnessTests(unittest.TestCase):
    def test_daemon_start_provenance_names_who_and_what(self):
        with patch.dict(os.environ, {"EVE_STARTED_BY": "test-session", "EVE_TRACE_USAGE": "1"}):
            prov = eve.daemon_start_provenance()
        self.assertEqual("test-session", prov["started_by"]); self.assertTrue(prov["usage_sampler"])
        self.assertIn("code_path", prov); self.assertIn("python", prov); self.assertIn("dirty", prov)

    def test_self_change_verification_gate_covers_the_harness_suites(self):
        for suite in ("tests.test_cli_parser", "tests.test_llama_transport", "tests.test_eve_core_contract", "tests.test_self_authority", "tests.test_cognition_budget"):
            self.assertIn(suite, eve.SELF_CHANGE_VERIFICATION_SUITES)


class SelfChangeTruthTests(unittest.TestCase):
    """Task 1.6: a no-op is not a change, every lever leaves a before-image, and a session can be reverted."""

    def _isolate(self, tmp):
        base = Path(tmp)
        (base / ".eve").mkdir()
        import eve_repository
        repo = eve_repository.JsonDocumentRepository(base / ".eve" / "config.json", "config", ensure_store=lambda: None)
        patches = [
            patch.object(eve, "APP_DIR", base / ".eve"),
            patch.object(eve, "CONFIG_REPOSITORY", repo),
            patch.object(eve, "ACTION_BLOCKS_PATH", base / ".eve" / "action_blocks.json"),
            patch.object(eve, "SELF_CHANGE_LEDGER_PATH", base / ".eve" / "self_change_ledger.jsonl"),
            patch.object(eve, "SELF_CHANGE_DIR", base / ".eve" / "self_change"),
            patch.object(eve, "SELF_CHANGE_FOLLOWUPS_PATH", base / ".eve" / "self_change_followups.jsonl"),
            patch.object(eve, "PERF_EVENTS_PATH", base / ".eve" / "perf_events.jsonl"),
            patch.object(eve, "DAEMON_RESTART_REQUEST_PATH", base / ".eve" / "daemon_restart_request.json"),
            patch.object(eve, "ensure_store", return_value=None),
            patch.object(eve, "ensure_version_snapshot", return_value={}),
            patch.object(eve, "append_entry", side_effect=lambda kind, text, **kw: self.entries.append((kind, text, kw.get("metadata") or {}))),
            patch.object(eve, "create_daemon_message", side_effect=lambda **kw: self.messages.append(kw)),
        ]
        self.entries, self.messages = [], []
        for item in patches:
            item.start(); self.addCleanup(item.stop)
        return base

    def test_apply_then_revert_restores_config_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._isolate(tmp)
            config_path = base / ".eve" / "config.json"
            eve.save_config(dict(eve.DEFAULT_CONFIG, proposal_interval_minutes=45, operation_model_overrides={"reflection": "fast"}))
            original = config_path.read_bytes()
            session = "self-change-20260917T1200-testrevert"
            config = dict(eve.DEFAULT_CONFIG, _self_change_session=session)
            first = eve.execute_self_authority_tool("set_config", {"key": "proposal_interval_minutes", "value": 120, "reason": "test"}, config)
            self.assertTrue(first["ok"]); self.assertFalse(first.get("no_op"))
            second = eve.execute_self_authority_tool("set_config", {"key": "proposal_interval_minutes", "value": 240, "reason": "again"}, config)
            self.assertTrue(second["ok"])
            routed = eve.execute_self_authority_tool("set_config", {"key": "operation_model_overrides", "value": {"proposal": "observer"}}, config)
            self.assertTrue(routed["ok"])
            blocked = eve.execute_self_authority_tool("block_action", {"action": "openclaw_log_check", "hours": 2, "reason": "test"}, config)
            self.assertTrue(blocked["ok"]); self.assertIn("openclaw_log_check", eve.load_action_blocks())
            self.assertNotEqual(original, config_path.read_bytes())
            before = json.loads((base / ".eve" / "self_change" / session / "before.json").read_text())
            self.assertEqual(45, before["set_config"]["proposal_interval_minutes"], "the first image is the state before the session, not the second call's")
            self.assertEqual({"reflection": "fast"}, before["set_config"]["operation_model_overrides"])
            self.assertEqual({}, before["block_action"]["action_blocks"])
            eve.append_self_change_ledger({"started_at": eve.utc_now(), "session_id": session, "proposal_id": "p9", "proposal_title": "Proposal ## Title Slow the cadence", "outcome": "applied"})
            updates = []
            with patch.object(eve, "read_proposals", return_value=[{"id": "p9", "status": "applied", "metadata": {}}]), patch.object(eve, "update_proposal_record", side_effect=lambda pid, **ch: updates.append((pid, ch))):
                result = eve.revert_self_change(session)
            self.assertTrue(result["ok"], result)
            self.assertEqual(original, config_path.read_bytes(), "revert restores config.json byte-for-byte")
            self.assertEqual({}, eve.load_action_blocks())
            self.assertEqual(["p9"], [u[0] for u in updates]); self.assertEqual("archived", updates[0][1]["status"])
            ledger = eve.read_self_change_ledger()
            self.assertEqual(["applied", "reverted"], [row["outcome"] for row in ledger])
            self.assertEqual("Proposal ## Title Slow the cadence", ledger[-1]["proposal_title"])
            self.assertIn("self_change_reverted", [e[0] for e in self.entries])
            missing = eve.revert_self_change("self-change-never-happened")
            self.assertFalse(missing["ok"]); self.assertIn("no self-change session", missing["error"])

    def test_no_op_set_config_is_not_a_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._isolate(tmp)
            eve.save_config(dict(eve.DEFAULT_CONFIG, proposal_interval_minutes=120))
            written = (base / ".eve" / "config.json").read_bytes()
            session = "self-change-20260917T1201-noop"
            with patch.object(eve, "save_config") as save:
                result = eve.execute_self_authority_tool("set_config", {"key": "proposal_interval_minutes", "value": 120}, dict(eve.DEFAULT_CONFIG, _self_change_session=session))
            self.assertTrue(result["ok"]); self.assertTrue(result["no_op"]); self.assertEqual(0, save.call_count)
            self.assertEqual(written, (base / ".eve" / "config.json").read_bytes())
            self.assertFalse((base / ".eve" / "self_change" / session / "before.json").exists(), "a no-op leaves no before-image")
            self.assertEqual([], self.entries, "a no-op is not journaled as a change")
            proposal = {"id": "p5", "created_at": eve.utc_now(), "title": "Proposal ## Title Set the cadence to what it already is", "body": "## Why Now The deep lane times out. ## Exact Change Route drafting to the observer lane. ## Expected Benefit Usable drafts. ## Rollback set_config operation_model_overrides {}." * 200, "status": "draft", "source": "daemon"}
            updates = []
            fake_session = {"response": "set it", "tool_calls": [{"tool": "set_config", "args": {"key": "proposal_interval_minutes", "value": 120}, "result": {"ok": True, "no_op": True}}], "session_id": "s"}
            with patch.object(eve, "read_proposals", return_value=[proposal]), patch.object(eve, "update_proposal_record", side_effect=lambda pid, **ch: updates.append((pid, ch))), patch.object(eve, "run_eve_coder_agent", return_value=fake_session):
                result = eve.run_self_change_cycle(dict(eve.DEFAULT_CONFIG), source="test")
            self.assertEqual("no_change", result["outcome"], result); self.assertEqual([], result["changes"])
            self.assertEqual("archived", updates[-1][1]["status"]); self.assertEqual(0, len(self.messages))
            self.assertEqual("no_change", eve.read_self_change_ledger()[-1]["outcome"])

    def test_two_same_title_drafts_yield_one_candidate_and_one_draft(self):
        now = eve.utc_now_datetime()
        title = "Proposal ## Title Route proposals to the observer lane"
        drafts = [
            {"id": "a", "title": title, "body": "## Why Now The deep lane times out. ## Exact Change Route drafting to the observer lane. ## Expected Benefit Usable drafts. ## Rollback set_config operation_model_overrides {}." * 200, "source": "daemon", "status": "draft", "created_at": (now - timedelta(hours=1)).isoformat(timespec="seconds"), "metadata": {}},
            {"id": "b", "title": title + " ## Why now: still slow", "body": "## Why Now The pattern was learned from compliance. ## Exact Change Retire it. ## Rollback Reactivate the pattern.", "source": "daemon", "status": "draft", "created_at": (now - timedelta(hours=3)).isoformat(timespec="seconds"), "metadata": {}},
        ]
        with patch.object(eve, "read_proposals", return_value=drafts), patch.object(eve, "read_self_change_ledger", return_value=[]):
            self.assertEqual(["a"], [c["id"] for c in eve.self_change_candidate_proposals(dict(eve.DEFAULT_CONFIG))])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proposals.jsonl"
            entries = []
            with patch.object(eve, "PROPOSALS_PATH", path), patch.object(eve, "ensure_store", return_value=None), patch.object(eve, "mirror_store_file_to_runtime", return_value=None), patch.object(eve, "append_entry", side_effect=lambda kind, text, **kw: entries.append(kind)):
                first, created = eve.ensure_followup_proposal(title=title, summary="s", body="b", source="outcome", evidence_key="ev-1")
                self.assertTrue(created)
                second, created_again = eve.ensure_followup_proposal(title=title + " ## Why now: again", summary="s", body="b", source="outcome", evidence_key="ev-2")
                self.assertFalse(created_again, "same topic, different evidence: no second draft"); self.assertEqual(first["id"], second["id"])
                other, created_other = eve.ensure_followup_proposal(title="Proposal ## Title Something else entirely", summary="s", body="b", source="outcome", evidence_key="ev-3")
                self.assertTrue(created_other)
                self.assertEqual(2, len(eve.read_jsonl_records(path)))
                # a topic applied within self_change_stale_days is not redrafted either; an old one is
                records = eve.read_jsonl_records(path)
                records[0]["status"] = "applied"; eve.write_jsonl_records(path, records)
                _, redraft = eve.ensure_followup_proposal(title=title, summary="s", body="b", source="outcome", evidence_key="ev-4")
                self.assertFalse(redraft)
                records[0]["updated_at"] = (now - timedelta(days=30)).isoformat(timespec="seconds"); eve.write_jsonl_records(path, records)
                _, redraft_old = eve.ensure_followup_proposal(title=title, summary="s", body="b", source="outcome", evidence_key="ev-5")
                self.assertTrue(redraft_old)
            self.assertEqual(["proposal_drafted", "proposal_drafted", "proposal_drafted"], entries)

    def test_daemon_drafting_skips_a_duplicate_topic(self):
        existing = {"id": "dup", "title": "Proposal ## Title Route proposals to the observer lane", "status": "draft", "created_at": eve.utc_now(), "updated_at": eve.utc_now(), "body": "## Why Now The deep lane times out. ## Exact Change Route drafting to the observer lane. ## Expected Benefit Usable drafts. ## Rollback set_config operation_model_overrides {}." * 200, "source": "daemon", "summary": "s"}
        entries, appended = [], []
        config = dict(eve.DEFAULT_CONFIG, proposal_context_limit=5, think_level="low", ollama_host="http://localhost:11434", proposal_timeout_seconds=5)
        with patch.object(eve, "ensure_version_snapshot", return_value={}), patch.object(eve, "resolve_model", return_value="m"), patch.object(eve, "ensure_human_context", return_value={}), patch.object(eve, "load_active_mind", return_value={}), patch.object(eve, "read_entries", return_value=[{"kind": "note", "text": "x", "timestamp": eve.utc_now()}]), patch.object(eve, "read_tensions", return_value=[]), patch.object(eve, "read_experiments", return_value=[]), patch.object(eve, "read_proposals", return_value=[existing]), patch.object(eve, "build_eve_identity_system_messages", return_value=[]), patch.object(eve, "load_prompt", return_value="p"), patch.object(eve, "build_supporting_system_messages", return_value=[]), patch.object(eve, "build_proposal_support_prompt", return_value="u"), patch.object(eve, "model_chat", return_value="## Title\nRoute proposals to the observer lane\n\n## Why now\nstill slow"), patch.object(eve, "append_jsonl_record", side_effect=lambda p, r: appended.append(r)), patch.object(eve, "append_entry", side_effect=lambda kind, text, **kw: entries.append(kind)):
            record = eve.suggest_proposal(config, source="daemon", max_tokens=50)
        self.assertTrue(record.get("duplicate_skipped"), record); self.assertEqual("dup", record["id"])
        self.assertEqual([], appended); self.assertEqual(["proposal_duplicate_skipped"], entries)

    def test_a_topic_with_a_ledger_row_today_is_skipped(self):
        now = eve.utc_now_datetime()
        drafts = [
            {"id": "a", "title": "Proposal ## Title Route proposals to the observer lane", "body": "## Why Now The deep lane times out. ## Exact Change Route drafting to the observer lane. ## Expected Benefit Usable drafts. ## Rollback set_config operation_model_overrides {}." * 200, "source": "daemon", "status": "draft", "created_at": (now - timedelta(hours=1)).isoformat(timespec="seconds"), "metadata": {}},
            {"id": "b", "title": "Proposal ## Title Retire the compliance pattern", "body": "## Why Now The pattern was learned from compliance. ## Exact Change Retire it. ## Rollback Reactivate the pattern.", "source": "daemon", "status": "draft", "created_at": (now - timedelta(hours=2)).isoformat(timespec="seconds"), "metadata": {}},
        ]
        ledger = [
            {"started_at": now.isoformat(timespec="seconds"), "session_id": "s1", "proposal_id": "old", "proposal_title": "Proposal ## Title Route proposals to the observer lane ## Why now", "outcome": "no_change"},
            {"started_at": (now - timedelta(days=3)).isoformat(timespec="seconds"), "session_id": "s0", "proposal_id": "older", "proposal_title": "Proposal ## Title Retire the compliance pattern", "outcome": "applied"},
        ]
        with patch.object(eve, "read_proposals", return_value=drafts), patch.object(eve, "read_self_change_ledger", return_value=ledger):
            self.assertEqual(["b"], [c["id"] for c in eve.self_change_candidate_proposals(dict(eve.DEFAULT_CONFIG))], "the topic started today waits; the one from three days ago is free")
            self.assertEqual(["a", "b"], [c["id"] for c in eve.self_change_candidate_proposals(dict(eve.DEFAULT_CONFIG, self_change_topic_cooldown_hours=0))])
            self.assertEqual(24, eve.DEFAULT_CONFIG["self_change_topic_cooldown_hours"])


class SelfChangeAdapterTests(unittest.TestCase):
    def test_parallel_preparations_have_unique_backups_and_private_tool_context(self):
        from concurrent.futures import ThreadPoolExecutor
        from eve_adapters.self_change import LegacyCoder

        with tempfile.TemporaryDirectory() as tmp, patch.object(eve, "SELF_CHANGE_DIR", Path(tmp)), patch.object(eve, "SELF_CHANGE_CONTEXT", {"restart_requested": "legacy"}) as legacy_context:
            coder = LegacyCoder()
            def prepare(_):
                return coder.prepare({}, "2026-10-01T10:00:00+00:00", {"id": "p1"}, 900)
            with ThreadPoolExecutor(max_workers=2) as pool:
                sessions = list(pool.map(prepare, range(2)))
            self.assertNotEqual(sessions[0].backup_dir, sessions[1].backup_dir)
            self.assertIsNot(sessions[0].context, sessions[1].context)
            self.assertIs(sessions[0].context, sessions[0].config["_self_change_context"])
            for index, session in enumerate(sessions):
                result = eve.execute_self_authority_tool("request_restart", {"reason": str(index)}, session.config)
                self.assertTrue(result["ok"])
            self.assertEqual("0", sessions[0].context["restart_requested"])
            self.assertEqual("1", sessions[1].context["restart_requested"])
            self.assertEqual({"restart_requested": "legacy"}, legacy_context)

    def test_verifier_compiles_first_party_packages_not_only_root_modules(self):
        from eve_adapters.self_change import LegacyCoder
        from eve_core.ports import CodingSession

        source = Path("/isolated/eve_core/changes.py")
        session = CodingSession("test", "backup", {})
        pairs = [("eve_core/changes.py", source, Path("/runtime/eve_core/changes.py")),
                 ("artifact.json", Path("/isolated/artifact.json"), Path("/runtime/artifact.json"))]
        with patch.object(eve, "first_party_python_source_pairs", return_value=pairs), patch.object(eve, "run_coder_shell_command", return_value={"ok": True}) as focused, patch.object(eve.subprocess, "run", return_value=type("R", (), {"returncode": 0})()) as compile_run:
            self.assertTrue(LegacyCoder().verify(session, True).ok)
        self.assertIn(str(source), compile_run.call_args.args[0])
        self.assertNotIn("/isolated/artifact.json", compile_run.call_args.args[0])
        self.assertIn("tests.test_architecture_boundaries", focused.call_args.args[0])

    def test_model_test_receipt_cannot_bypass_owner_regressions(self):
        from eve_adapters.self_change import LegacyCoder
        from eve_core.ports import CodingSession

        session = CodingSession("test", "backup", {})
        with patch.object(eve.subprocess, "run", return_value=type("R", (), {"returncode": 0})()), patch.object(eve, "run_coder_shell_command", return_value={"ok": False, "stderr": "boundary violation"}) as focused:
            verdict = LegacyCoder().verify(session, True)
        self.assertFalse(verdict.ok)
        self.assertIn("boundary violation", verdict.detail)
        self.assertEqual(1, focused.call_count)

    def test_runtime_adapter_requires_verified_install_and_restart_receipts(self):
        from eve_adapters.self_change import LegacyRuntime
        from eve_core.ports import CodingSession

        session = CodingSession("test", "backup", {})
        with patch.object(eve, "request_daemon_restart", return_value={}):
            self.assertFalse(LegacyRuntime().restart(session, "reason", True))
        with patch.object(eve, "request_daemon_restart", return_value={"requested_at": eve.utc_now(), "reason": "reason"}) as restart:
            self.assertTrue(LegacyRuntime().restart(session, "reason", True))
            self.assertEqual("backup", restart.call_args.kwargs["rollback_dir"])
        with patch.object(eve, "sync_runtime_python_code", return_value={"verified": False}):
            self.assertIs(False, LegacyRuntime().synchronize()["verified"])


if __name__ == "__main__":
    unittest.main()
