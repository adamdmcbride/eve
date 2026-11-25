"""Checks for bin/eve_daemon_restart.sh (Rearchitecture Program task 0.2).

The script is only ever exercised here in DRY_RUN=1 mode against a temporary
checkout, so nothing under the live .eve/ or ~/.eve_runtime is touched and no
process is signalled or started.
"""

import os
from pathlib import Path
import shutil
import subprocess
import time
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bin" / "eve_daemon_restart.sh"
FIXTURES = ROOT / "tests" / "fixtures" / "daemon_restart"


class DaemonRestartScriptTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.source = Path(self._tmp.name) / "checkout"
        self.runtime = Path(self._tmp.name) / "runtime"
        self.log = Path(self._tmp.name) / "eve_daemon.log"
        (self.source / ".eve").mkdir(parents=True)
        (self.source / "bin").mkdir()
        self.runtime.mkdir()
        (self.source / "eve.py").write_text("# placeholder checkout\n", encoding="utf-8")
        self.install_owner()

    # -- fixture helpers -------------------------------------------------

    def install_activity(self, name):
        shutil.copy(FIXTURES / name, self.source / ".eve" / "daemon_activity.json")

    def install_owner(self):
        shutil.copy(FIXTURES / "daemon_owner.json", self.runtime / ".eve-daemon-owner.json")

    def install_restart_request(self, age_seconds=0):
        target = self.source / ".eve" / "daemon_restart_request.json"
        shutil.copy(FIXTURES / "daemon_restart_request.json", target)
        if age_seconds:
            stamp = time.time() - age_seconds
            os.utime(target, (stamp, stamp))
        return target

    def snapshot(self):
        paths = []
        for base in (self.source, self.runtime):
            for path in sorted(base.rglob("*")):
                stat = path.stat()
                paths.append((str(path), stat.st_size, stat.st_mtime))
        return paths

    def run_script(self, env=None, dry_run=True):
        merged = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": self._tmp.name,
            "EVE_SOURCE_DIR": str(self.source),
            "EVE_RUNTIME_DIR": str(self.runtime),
            "EVE_SESSION": "test_session",
            "DAEMON_LOG": str(self.log),
        }
        if dry_run:
            merged["DRY_RUN"] = "1"
        merged.update(env or {})
        return subprocess.run(
            ["bash", str(SCRIPT)],
            env=merged, capture_output=True, text=True, check=False, timeout=30,
        )

    # -- tests -------------------------------------------------------------

    def test_script_is_executable_and_parses(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK), "bin/eve_daemon_restart.sh must be executable")
        result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_script_declares_every_step_and_never_pkills(self):
        text = SCRIPT.read_text(encoding="utf-8")
        for needle in (
            "codex_coord.py",
            "--to all",
            "daemon_activity.json",
            ".eve-daemon-owner.json",
            "EVE_STARTED_BY=",
            "nohup",
            "daemon_restart_request.json",
            "DAEMON_SUCCESSOR_WATCH:-120",
            "EVE_TRACE_USAGE",
        ):
            self.assertIn(needle, text)
        code_lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
        code = "\n".join(code_lines)
        self.assertNotIn("pkill", code)
        self.assertNotIn("killall", code)
        # The kill step only ever names the owner pid read from the owner file.
        self.assertIn('kill -TERM "$owner_pid"', code)
        self.assertIn('kill -KILL "$owner_pid"', code)

    def test_heartbeat_baseline_follows_the_stop_step_and_pgrep_is_portable(self):
        text = SCRIPT.read_text(encoding="utf-8")
        # cycle_activity.persist() refreshes last_heartbeat_at on every status
        # write, including the one that follows a TERM, so the baseline for the
        # successor watch must be read after the old owner is stopped.
        baseline = text.index('baseline_heartbeat="$(json_field')
        self.assertGreater(baseline, text.index('kill -KILL "$owner_pid"'))
        self.assertLess(baseline, text.index('nohup "$EVE_PYTHON" eve.py daemon run'))
        # macOS pgrep has no -c flag (it exits 2 with a usage message).
        self.assertNotIn("pgrep -fc", text)
        self.assertNotIn("pgrep -c", text)

    def test_dry_run_idle_reports_plan_and_touches_nothing(self):
        self.install_activity("daemon_activity_idle.json")
        before = self.snapshot()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        out = result.stdout
        self.assertIn("codex_coord.py message --from test_session --to all --body", out)
        self.assertIn("daemon is idle now", out)
        self.assertIn("status=idle", out)
        self.assertIn("would send TERM to pid 12345", out)
        self.assertIn("KILL after 15s", out)
        self.assertIn("EVE_STARTED_BY=test_session nohup /usr/bin/python3 eve.py daemon run >> %s 2>&1 &" % self.log, out)
        self.assertIn("would run from %s" % self.source, out)
        self.assertIn("wait up to 120s", out)
        self.assertIn("2026-09-17T05:14:21+00:00", out)
        self.assertIn("nothing was touched", out)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(self.log.exists())
        self.assertFalse((self.source / "coordination").exists())

    def test_dry_run_preserves_trace_usage_and_watch_override(self):
        self.install_activity("daemon_activity_idle.json")
        result = self.run_script(env={"EVE_TRACE_USAGE": "1", "DAEMON_SUCCESSOR_WATCH": "45"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("EVE_TRACE_USAGE=1 EVE_STARTED_BY=test_session nohup", result.stdout)
        self.assertIn("wait up to 45s", result.stdout)

    def test_dry_run_without_trace_usage_does_not_invent_it(self):
        self.install_activity("daemon_activity_idle.json")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("EVE_TRACE_USAGE=", result.stdout)

    def test_session_defaults_when_unset(self):
        self.install_activity("daemon_activity_idle.json")
        result = self.run_script(env={"EVE_SESSION": ""})
        # An empty EVE_SESSION falls back to the script's default name.
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("--from eve_daemon_restart --to all", result.stdout)

    def test_refuses_while_handover_is_in_progress(self):
        self.install_activity("daemon_activity_idle.json")
        self.install_restart_request(age_seconds=0)
        before = self.snapshot()
        result = self.run_script()
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn("refusing to restart", result.stdout)
        self.assertIn("self-change handover is in progress", result.stdout)
        self.assertNotIn("would send TERM", result.stdout)
        self.assertEqual(before, self.snapshot())

    def test_refusal_also_applies_without_dry_run_before_anything_happens(self):
        # The refusal is the first gate, so a real run stops before posting,
        # waiting, killing, or starting anything.
        self.install_activity("daemon_activity_idle.json")
        self.install_restart_request(age_seconds=60)
        before = self.snapshot()
        result = self.run_script(dry_run=False)
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn("refusing to restart", result.stdout)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(self.log.exists())

    def test_stale_restart_request_is_ignored(self):
        self.install_activity("daemon_activity_idle.json")
        self.install_restart_request(age_seconds=20 * 60)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("stale restart request", result.stdout)
        self.assertIn("would send TERM to pid 12345", result.stdout)

    def test_dry_run_reports_active_daemon_without_waiting(self):
        self.install_activity("daemon_activity_active.json")
        started = time.time()
        result = self.run_script()
        self.assertLess(time.time() - started, 15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("daemon is not idle", result.stdout)
        self.assertIn("status=active (need idle)", result.stdout)
        self.assertIn("would wait up to 60s", result.stdout)

    def test_missing_status_key_falls_back_to_mtime(self):
        self.install_activity("daemon_activity_no_status.json")
        activity = self.source / ".eve" / "daemon_activity.json"
        # Fresh file: still being written, so not idle.
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("daemon is not idle", result.stdout)
        self.assertIn("no status key; mtime age", result.stdout)
        # Old file: idle by the mtime rule.
        stamp = time.time() - 30
        os.utime(activity, (stamp, stamp))
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("daemon is idle now", result.stdout)
        self.assertIn("no status key; mtime age", result.stdout)

    def test_missing_activity_file_counts_as_idle(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no activity file", result.stdout)
        self.assertIn("would send TERM to pid 12345", result.stdout)

    def test_missing_owner_file_skips_the_stop_step(self):
        self.install_activity("daemon_activity_idle.json")
        (self.runtime / ".eve-daemon-owner.json").unlink()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no owner file", result.stdout)
        self.assertNotIn("would send TERM", result.stdout)
        self.assertIn("EVE_STARTED_BY=test_session nohup", result.stdout)

    def test_non_numeric_owner_pid_is_never_killed(self):
        self.install_activity("daemon_activity_idle.json")
        (self.runtime / ".eve-daemon-owner.json").write_text('{"pid": "12345; rm -rf /", "status": "running"}', encoding="utf-8")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no numeric owner pid", result.stdout)
        self.assertNotIn("would send TERM", result.stdout)

    def test_missing_checkout_is_a_precondition_failure(self):
        shutil.rmtree(self.source)
        result = self.run_script()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("checkout not found", result.stdout)

    def test_dry_run_warns_when_eve_py_is_missing(self):
        self.install_activity("daemon_activity_idle.json")
        (self.source / "eve.py").unlink()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("eve.py is missing", result.stdout)


if __name__ == "__main__":
    unittest.main()
