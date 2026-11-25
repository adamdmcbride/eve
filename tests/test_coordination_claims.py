"""Task 1.7: the claim-aware executor.

Codex sessions and Claude claim files on the coordination board (``coordination/claims.json``,
see bin/codex_coord.py). Before Eve's coder tools edit a path under another session's active
claim, they defer with ``deferred_claim`` instead of editing; a self-change cycle whose only
actions were deferred records ``deferred_claim`` and leaves the proposal a draft without
spending an attempt.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import eve  # noqa: E402


PATCH_EVE = """diff --git a/eve.py b/eve.py
--- a/eve.py
+++ b/eve.py
@@ -1 +1 @@
-old
+new
"""

PATCH_NOTES = """diff --git a/docs/notes.md b/docs/notes.md
--- a/docs/notes.md
+++ b/docs/notes.md
@@ -1 +1 @@
-old
+new
"""


def claims_fixture(root: Path, files, session: str = "codex-x") -> None:
    (root / "coordination").mkdir(exist_ok=True)
    (root / "coordination" / "claims.json").write_text(
        json.dumps({session: {"session": session, "scope": "test", "files": list(files), "note": "", "updated_at": "2026-09-17T00:00:00+00:00"}}),
        encoding="utf-8",
    )


class ClaimCoverageTests(unittest.TestCase):
    def test_claim_entries_cover_files_directories_and_globs(self):
        self.assertTrue(eve.coordination_claim_covers("eve.py", "eve.py"))
        self.assertFalse(eve.coordination_claim_covers("eve.py", "eve_web.py"))
        self.assertTrue(eve.coordination_claim_covers("bin", "bin/codex_coord.py"))
        self.assertTrue(eve.coordination_claim_covers("bin/", "bin/sub/tool.py"))
        self.assertFalse(eve.coordination_claim_covers("bin", "binary.txt"))
        self.assertTrue(eve.coordination_claim_covers("eve_*.py", "eve_web.py"))
        self.assertFalse(eve.coordination_claim_covers("eve_*.py", "eve.py"))
        self.assertFalse(eve.coordination_claim_covers("", "eve.py"))

    def test_read_only_commands_name_no_paths_but_writers_do(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "eve.py").write_text("x\n", encoding="utf-8")
            (root / "bin").mkdir()
            config = {**eve.DEFAULT_CONFIG, "code_workspace_root": str(root)}
            self.assertEqual([], eve.coder_command_named_paths("cat eve.py | head -5", config))
            self.assertEqual([], eve.coder_command_named_paths("git diff -- eve.py", config))
            self.assertEqual([], eve.coder_command_named_paths("python3 -m unittest tests.test_cognition_budget", config))
            self.assertEqual(["eve.py"], eve.coder_command_named_paths("sed -i '' 's/a/b/' eve.py", config))
            self.assertEqual(["eve.py"], eve.coder_command_named_paths("echo hi > eve.py", config))
            self.assertEqual(["bin/new_tool.py"], eve.coder_command_named_paths("touch bin/new_tool.py", config))
            self.assertEqual([], eve.coder_command_named_paths("touch nowhere/new_tool.py", config), "a path under no existing workspace directory is not a target")


class ClaimAwareToolTests(unittest.TestCase):
    def _repo(self, tmp):
        root = Path(tmp).resolve()
        subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True, text=True)
        (root / "eve.py").write_text("old\n", encoding="utf-8")
        (root / "docs").mkdir()
        (root / "docs" / "notes.md").write_text("old\n", encoding="utf-8")
        claims_fixture(root, ["eve.py"])
        return root

    def test_apply_patch_defers_a_claimed_file_and_applies_an_unclaimed_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            config = {**eve.DEFAULT_CONFIG, "code_workspace_root": str(root)}
            blocked = eve.execute_coder_apply_patch_tool({"patch": PATCH_EVE}, config)
            self.assertFalse(blocked["ok"], blocked)
            self.assertTrue(blocked["blocked"])
            self.assertEqual("codex-x", blocked["deferred_claim"])
            self.assertEqual("claimed_by_codex-x", blocked["reason"])
            self.assertEqual("claimed by codex-x until released", blocked["error"])
            self.assertEqual(["eve.py"], blocked["paths"])
            self.assertEqual("old\n", (root / "eve.py").read_text(encoding="utf-8"), "a deferred patch edits nothing")

            free = eve.execute_coder_apply_patch_tool({"patch": PATCH_NOTES}, config)
            self.assertTrue(free["ok"], free)
            self.assertNotIn("deferred_claim", free)
            self.assertEqual("new\n", (root / "docs" / "notes.md").read_text(encoding="utf-8"))

    def test_her_own_session_and_a_released_claim_do_not_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            own = {**eve.DEFAULT_CONFIG, "code_workspace_root": str(root), "_self_change_session": "codex-x"}
            self.assertTrue(eve.execute_coder_apply_patch_tool({"patch": PATCH_EVE}, own)["ok"])
            (root / "eve.py").write_text("old\n", encoding="utf-8")
            (root / "coordination" / "claims.json").write_text("{}\n", encoding="utf-8")
            config = {**eve.DEFAULT_CONFIG, "code_workspace_root": str(root)}
            self.assertTrue(eve.execute_coder_apply_patch_tool({"patch": PATCH_EVE}, config)["ok"])

    def test_write_file_and_shell_commands_defer_on_a_claimed_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            config = {**eve.DEFAULT_CONFIG, "code_workspace_root": str(root)}
            tool_config = eve.coder_tool_config(config)
            written = eve.execute_write_file_tool({"path": "eve.py", "content": "new\n"}, tool_config)
            self.assertEqual("codex-x", written.get("deferred_claim"), written)
            self.assertEqual("old\n", (root / "eve.py").read_text(encoding="utf-8"))
            self.assertTrue(eve.execute_write_file_tool({"path": "docs/notes.md", "content": "new\n"}, tool_config)["ok"])

            shell = eve.run_coder_shell_command("echo new > eve.py", config, timeout_seconds=5)
            self.assertEqual("codex-x", shell.get("deferred_claim"), shell)
            self.assertTrue(shell["blocked"])
            self.assertEqual("old\n", (root / "eve.py").read_text(encoding="utf-8"))
            reader = eve.run_coder_shell_command("cat eve.py", config, timeout_seconds=5)
            self.assertTrue(reader["ok"], reader)
            self.assertNotIn("deferred_claim", reader)

            with patch.object(eve, "ROOT", root):
                capability = eve.execute_shell_tool({"command": "echo new > eve.py"}, config)
            self.assertEqual("codex-x", capability.get("deferred_claim"), capability)
            self.assertEqual("old\n", (root / "eve.py").read_text(encoding="utf-8"))


class DeferredSelfChangeCycleTests(unittest.TestCase):
    def _isolate(self, tmp):
        base = Path(tmp)
        (base / ".eve").mkdir()
        self.entries, self.messages = [], []
        patches = [
            patch.object(eve, "APP_DIR", base / ".eve"),
            patch.object(eve, "SELF_CHANGE_LEDGER_PATH", base / ".eve" / "self_change_ledger.jsonl"),
            patch.object(eve, "SELF_CHANGE_DIR", base / ".eve" / "self_change"),
            patch.object(eve, "DAEMON_RESTART_REQUEST_PATH", base / ".eve" / "daemon_restart_request.json"),
            patch.object(eve, "append_entry", side_effect=lambda kind, text, **kw: self.entries.append((kind, text, kw.get("metadata") or {}))),
            patch.object(eve, "create_daemon_message", side_effect=lambda **kw: self.messages.append(kw)),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        return base

    def test_cycle_whose_only_action_was_deferred_keeps_the_draft_and_the_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._isolate(tmp)
            proposal = {"id": "p7", "created_at": "2026-09-16T00:00:00+00:00", "title": "Proposal ## Title Tighten a check", "body": "Patch eve.py", "status": "draft", "source": "daemon", "metadata": {"self_change_attempts": 1}}
            updates = []
            deferred_result = {"ok": False, "blocked": True, "deferred_claim": "codex-x", "reason": "claimed_by_codex-x", "error": "claimed by codex-x until released", "paths": ["eve.py"]}
            fake_session = {
                "response": "eve.py is claimed by codex-x; I will wait.",
                "tool_calls": [
                    {"tool": "read_file", "args": {"path": "eve.py"}, "result": {"ok": True}},
                    {"tool": "apply_patch", "args": {"patch": PATCH_EVE}, "result": deferred_result},
                ],
                "session_id": "s",
            }
            with patch.object(eve, "read_proposals", return_value=[proposal]), patch.object(eve, "update_proposal_record", side_effect=lambda pid, **ch: updates.append((pid, ch))), patch.object(eve, "run_eve_coder_agent", return_value=fake_session), patch.object(eve, "request_daemon_restart") as restart:
                result = eve.run_self_change_cycle(dict(eve.DEFAULT_CONFIG), source="test")
            self.assertTrue(result["executed"])
            self.assertEqual("deferred_claim", result["outcome"], result)
            self.assertEqual("codex-x", result["deferred_claim"])
            self.assertFalse(result["ok"])
            self.assertEqual(0, restart.call_count)
            self.assertEqual("draft", updates[-1][1]["status"])
            self.assertEqual(1, updates[-1][1]["metadata"]["self_change_attempts"], "a deferral spends no attempt")
            self.assertEqual("codex-x", updates[-1][1]["metadata"]["self_change_deferred_claim"])
            ledger = eve.read_self_change_ledger()
            self.assertEqual(1, len(ledger))
            self.assertEqual("deferred_claim", ledger[0]["outcome"])
            self.assertEqual("codex-x", ledger[0]["deferred_claim"])
            self.assertEqual([], self.messages, "a deferral is not a change to report")
            self.assertEqual(["self_change_started", "self_change_deferred_claim"], [e[0] for e in self.entries])

    def test_a_deferred_patch_beside_a_real_lever_still_counts_as_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._isolate(tmp)
            proposal = {"id": "p8", "created_at": "2026-09-16T00:00:00+00:00", "title": "Proposal ## Title Route and patch", "body": "x", "status": "draft", "source": "daemon"}
            updates = []
            fake_session = {
                "response": "routed; the patch waits on codex-x",
                "tool_calls": [
                    {"tool": "apply_patch", "args": {}, "result": {"ok": False, "blocked": True, "deferred_claim": "codex-x", "error": "claimed by codex-x until released"}},
                    {"tool": "set_config", "args": {"key": "proposal_interval_minutes", "value": 120}, "result": {"ok": True}},
                ],
                "session_id": "s",
            }
            with patch.object(eve, "read_proposals", return_value=[proposal]), patch.object(eve, "update_proposal_record", side_effect=lambda pid, **ch: updates.append((pid, ch))), patch.object(eve, "run_eve_coder_agent", return_value=fake_session):
                result = eve.run_self_change_cycle(dict(eve.DEFAULT_CONFIG), source="test")
            self.assertEqual("applied", result["outcome"], result)
            self.assertEqual(1, updates[-1][1]["metadata"]["self_change_attempts"])


if __name__ == "__main__":
    unittest.main()
