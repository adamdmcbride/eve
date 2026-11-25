from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "eve_openclaw_outer_timeout_test",
    ROOT / "eve_openclaw.py",
)
assert SPEC and SPEC.loader
eve_openclaw = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(eve_openclaw)


class OpenClawOuterTimeoutTests(unittest.TestCase):
    def test_repair_uses_one_total_deadline_and_records_timeout(self) -> None:
        captured: dict[str, object] = {}

        def fake_run(
            command: list[str],
            **kwargs: object,
        ) -> subprocess.CompletedProcess[str]:
            captured["command"] = command
            captured.update(kwargs)
            return subprocess.CompletedProcess(
                command,
                124,
                stdout="",
                stderr=(
                    "Command timed out after 7 seconds\n"
                    "Process-tree cancellation: enumerated=true descendants=1 remaining=0."
                ),
            )

        with patch.object(eve_openclaw, "run", side_effect=fake_run), patch.object(
            eve_openclaw,
            "collect_openclaw_status",
            return_value={"enabled": True},
        ), patch.object(eve_openclaw, "save_openclaw_status"):
            result = eve_openclaw.repair_openclaw(
                {"openclaw_workspace": "/tmp/eve-openclaw-test"},
                timeout=7,
                skip_sync=True,
            )

        command = captured["command"]
        assert isinstance(command, list)
        timeout_index = command.index("--timeout")
        self.assertEqual("7", command[timeout_index + 1])
        self.assertEqual(7, captured["timeout"])
        self.assertTrue(captured["cancel_process_tree_on_timeout"])
        self.assertFalse(result["ok"])
        self.assertEqual(124, result["returncode"])
        self.assertEqual("timed_out", result["status"]["last_repair_status"])
        self.assertIn("no remaining process", result["status"]["last_repair_verified"])

    def test_unenumerated_timeout_does_not_claim_process_tree_verification(self) -> None:
        result = subprocess.CompletedProcess(
            ["repair"],
            124,
            stdout="",
            stderr="Process-tree cancellation: enumerated=false descendants=0 remaining=0.",
        )
        with patch.object(eve_openclaw, "run", return_value=result), patch.object(
            eve_openclaw,
            "collect_openclaw_status",
            return_value={"enabled": True},
        ), patch.object(eve_openclaw, "save_openclaw_status"):
            repair = eve_openclaw.repair_openclaw(
                {"openclaw_workspace": "/tmp/eve-openclaw-test"},
                timeout=1,
                skip_sync=True,
            )

        self.assertEqual("timed_out", repair["status"]["last_repair_status"])
        self.assertEqual("", repair["status"]["last_repair_verified"])

    def test_timeout_log_redacts_message_content(self) -> None:
        secret = "private-repair-context"
        result = eve_openclaw.run(
            [
                sys.executable,
                "-c",
                "import time; time.sleep(5)",
                "--message",
                secret,
                "--token=also-private",
            ],
            timeout=0.1,
            cancel_process_tree_on_timeout=True,
            termination_grace_seconds=0.1,
        )

        self.assertEqual(124, result.returncode)
        self.assertNotIn(secret, result.stderr)
        self.assertNotIn("also-private", result.stderr)
        self.assertIn("--message <redacted>", result.stderr)
        self.assertIn("--token=<redacted>", result.stderr)

    def test_separate_session_child_cannot_emit_event_or_act_after_caller_timeout(self) -> None:
        child_code = (
            "import pathlib,sys,time; "
            "time.sleep(0.7); "
            "pathlib.Path(sys.argv[1]).write_text('{\"type\":\"tool_call\"}\\n', encoding='utf-8'); "
            "time.sleep(0.1); pathlib.Path(sys.argv[2]).write_text('late', encoding='utf-8')"
        )
        wrapper_code = (
            "import pathlib,subprocess,sys,time; "
            "child=subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2],sys.argv[3]], "
            "start_new_session=True); "
            "pathlib.Path(sys.argv[4]).write_text(str(child.pid), encoding='utf-8'); "
            "time.sleep(10)"
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session_events = root / "session.jsonl"
            marker = root / "late-action.txt"
            child_pid_path = root / "child.pid"

            def descendants(_root_pid: int) -> tuple[list[int], bool]:
                deadline = time.monotonic() + 1
                while time.monotonic() < deadline:
                    try:
                        return [int(child_pid_path.read_text(encoding="utf-8"))], True
                    except (OSError, ValueError):
                        time.sleep(0.01)
                return [], False

            with patch.object(eve_openclaw, "_process_table_descendants", side_effect=descendants):
                result = eve_openclaw.run(
                    [
                        sys.executable,
                        "-c",
                        wrapper_code,
                        child_code,
                        str(session_events),
                        str(marker),
                        str(child_pid_path),
                    ],
                    timeout=0.2,
                    cancel_process_tree_on_timeout=True,
                    termination_grace_seconds=0.2,
                )

            child_pid = int(child_pid_path.read_text(encoding="utf-8"))
            try:
                self.assertEqual(124, result.returncode)
                self.assertIn("remaining=0", result.stderr)
                time.sleep(0.9)
                self.assertFalse(
                    session_events.exists(),
                    "cancelled child emitted a late session/tool event",
                )
                self.assertFalse(marker.exists(), "cancelled child performed a late action")
            finally:
                try:
                    os.killpg(os.getpgid(child_pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass

    def test_completed_isolated_command_preserves_output(self) -> None:
        result = eve_openclaw.run(
            [sys.executable, "-c", "print('ok')"],
            timeout=2,
            cancel_process_tree_on_timeout=True,
        )

        self.assertEqual(0, result.returncode)
        self.assertEqual("ok", result.stdout.strip())
        self.assertEqual("", result.stderr)


if __name__ == "__main__":
    unittest.main()
