import argparse
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

import eve
import eve_daemon_runtime as runtime
import eve_store


CHILD = """
from pathlib import Path
import json, sys
import eve_daemon_runtime as r
with r.runner_lease(Path(sys.argv[1]), code_path=Path(sys.argv[2]),
                    state_root=Path(sys.argv[3]), mode=sys.argv[4]) as owner:
    print(json.dumps(owner), flush=True)
    sys.stdin.readline()
"""


class DaemonRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / "runtime"

    def lease(self, mode="recurrent", code="source/eve.py"):
        return runtime.runner_lease(self.runtime, code_path=self.root / code,
                                    state_root=self.root / "source/.eve", mode=mode)

    def child(self, mode="recurrent"):
        process = subprocess.Popen(
            [sys.executable, "-u", "-c", CHILD, str(self.runtime),
             str(self.root / "runtime/eve.py"), str(self.root / "runtime/.eve"), mode],
            cwd=Path(eve.__file__).parent, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        def cleanup():
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)
        self.addCleanup(cleanup)
        return process

    def test_same_thread_contender_cannot_replace_receipt(self):
        with self.lease() as owner:
            before = runtime.owner_path(self.runtime).read_bytes()
            with self.assertRaises(eve_store.LockBusy):
                with self.lease("once"):
                    self.fail("duplicate admitted")
            self.assertEqual(before, runtime.owner_path(self.runtime).read_bytes())
            self.assertTrue(runtime.inspect_runner(self.runtime)["lease_held"])
        status = runtime.inspect_runner(self.runtime)
        self.assertFalse(status["lease_held"])
        self.assertEqual("stopped", status["owner_receipt"]["status"])
        self.assertEqual(owner["owner_id"], status["owner_receipt"]["owner_id"])

    def test_process_lock_excludes_both_modes_across_code_roots(self):
        with self.lease():
            for mode in ["once", "recurrent"]:
                child = self.child(mode)
                out, err = child.communicate(timeout=10)
                self.assertNotEqual(0, child.returncode)
                self.assertEqual("", out)
                self.assertIn("LockBusy", err)

    def test_killed_owner_releases_kernel_lock_not_stale_receipt(self):
        child = self.child()
        # Bounded readiness: wait on a reader thread rather than a potentially
        # unbounded pipe readline if the child fails before entering its lease.
        lines = []
        reader = threading.Thread(target=lambda: lines.append(child.stdout.readline()), daemon=True)
        reader.start()
        reader.join(10)
        self.assertFalse(reader.is_alive(), "child did not publish ownership")
        owner = json.loads(lines[0])
        self.assertTrue(runtime.inspect_runner(self.runtime)["lease_held"])
        child.kill()
        child.communicate(timeout=10)
        self.assertFalse(runtime.inspect_runner(self.runtime)["lease_held"])
        self.assertEqual("running", runtime.inspect_runner(self.runtime)["owner_receipt"]["status"])
        with self.lease("once") as replacement:
            self.assertNotEqual(owner["owner_id"], replacement["owner_id"])

    def test_failure_releases_owner_and_retains_attribution(self):
        with self.assertRaisesRegex(ValueError, "cycle failed"):
            with self.lease():
                raise ValueError("cycle failed")
        status = runtime.inspect_runner(self.runtime)
        self.assertFalse(status["lease_held"])
        self.assertEqual("failed", status["owner_receipt"]["status"])
        with self.lease("once"):
            pass

    def test_cleanup_does_not_overwrite_foreign_receipt(self):
        with self.lease():
            eve_store.atomic_write_text(runtime.owner_path(self.runtime), '{"owner_id":"foreign"}\n')
        self.assertEqual({"owner_id": "foreign"}, runtime.inspect_runner(self.runtime)["owner_receipt"])

    def test_mode_and_owner_attached_to_activity_and_failure(self):
        records = []
        with self.assertRaisesRegex(ValueError, "failure"):
            with runtime.cycle_activity(interval_seconds=5, max_active_seconds=180,
                    now=eve.utc_now, write=records.append,
                    owner={"owner_id": "test-owner", "run_mode": "once"}):
                raise ValueError("failure")
        self.assertEqual(["active", "failed"], [r["status"] for r in records])
        for record in records:
            self.assertEqual("test-owner", record["owner_id"])
            self.assertEqual("once", record["run_mode"])
        self.assertEqual("failure", records[-1]["failure"])

    def test_invalid_mode_does_not_create_owner(self):
        with self.assertRaises(ValueError):
            with self.lease("unknown"):
                pass
        self.assertFalse(self.runtime.exists())

    def command_hooks(self, stack, *, once, state=None):
        hooks = {}
        stack.enter_context(patch.object(eve, "RUNTIME_DIR", self.runtime))
        for name, result in {
            "load_config": {"loop_sleep_seconds": 1},
            "load_state": state if state is not None else {},
            "save_state": None, "write_operator_power_state": None,
            "run_daemon_cycle": ["mind_tick"], "write_daemon_activity": None,
            "append_entry": None,
        }.items():
            hooks[name] = stack.enter_context(patch.object(eve, name, return_value=result))
        stack.enter_context(patch("sys.stderr", new_callable=io.StringIO))
        stack.enter_context(patch("sys.stdout", new_callable=io.StringIO))
        return argparse.Namespace(once=once, force=once, sleep_seconds=0), hooks

    def test_busy_cli_returns_75_before_config_power_state_heartbeat_or_cycle(self):
        with self.lease():
            for once in [False, True]:
                with ExitStack() as stack:
                    args, hooks = self.command_hooks(stack, once=once)
                    self.assertEqual(75, eve.cmd_daemon_run(args))
                    for hook in hooks.values():
                        hook.assert_not_called()

    def test_recurring_owns_sleep_and_reloads_state_each_cycle(self):
        with ExitStack() as stack:
            args, hooks = self.command_hooks(stack, once=False)
            def sleep(_):
                with self.assertRaises(eve_store.LockBusy):
                    with self.lease("once"):
                        pass
                raise KeyboardInterrupt
            stack.enter_context(patch.object(eve.time, "sleep", side_effect=sleep))
            self.assertEqual(0, eve.cmd_daemon_run(args))
            self.assertEqual(2, hooks["load_state"].call_count)
            self.assertFalse(hooks["run_daemon_cycle"].call_args.kwargs["force"])
            activity = hooks["write_daemon_activity"].call_args.args[0]
            self.assertEqual("recurrent", activity["run_mode"])
            self.assertEqual("idle", activity["status"])
            self.assertEqual(["mind_tick"], activity["completed_jobs"])
        self.assertFalse(runtime.inspect_runner(self.runtime)["lease_held"])

    def test_once_does_not_change_historical_recurrent_pid(self):
        state = {"daemon_process_id": 4242}
        with ExitStack() as stack:
            args, hooks = self.command_hooks(stack, once=True, state=state)
            self.assertEqual(0, eve.cmd_daemon_run(args))
            self.assertEqual(4242, state["daemon_process_id"])
            self.assertEqual(os.getpid(), state["last_daemon_once_pid"])
            self.assertEqual("once", state["daemon_runner_mode"])
            self.assertTrue(hooks["run_daemon_cycle"].call_args.kwargs["force"])
            self.assertEqual("once", hooks["write_daemon_activity"].call_args.args[0]["run_mode"])

    def test_cycle_exception_not_misreported_as_startup_contention(self):
        with ExitStack() as stack:
            args, hooks = self.command_hooks(stack, once=True)
            hooks["run_daemon_cycle"].side_effect = eve_store.LockBusy("a job lock")
            with self.assertRaisesRegex(eve_store.LockBusy, "a job lock"):
                eve.cmd_daemon_run(args)
        self.assertFalse(runtime.inspect_runner(self.runtime)["lease_held"])

    def test_fresh_once_activity_never_proves_recurrence(self):
        now = eve.utc_now()
        activity = {"pid": 42, "status": "active", "run_mode": "once",
                    "owner_id": "once-owner", "last_heartbeat_at": now, "cycle_started_at": now}
        with patch.object(eve, "load_daemon_activity", return_value=activity):
            result = eve.presence_runtime_liveness({}, {"last_loop_at": now, "daemon_process_id": 42},
                                                   daemon_running=True)
        self.assertFalse(result["live"])
        self.assertFalse(result["active"])
        self.assertEqual("diagnostic", result["status"])
        self.assertEqual("once-owner", result["activity"]["owner_id"])


if __name__ == "__main__":
    unittest.main()
