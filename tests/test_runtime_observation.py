"""Fault-oriented operational observations, isolated from the live Eve store."""
from contextlib import contextmanager, ExitStack
from datetime import datetime, timedelta, timezone
import copy
import hashlib
import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import eve
import eve_daemon_runtime as runtime
import eve_store


class RuntimeObservationTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.code_root = self.root / "source"
        self.code_root.mkdir()
        (self.code_root / "eve.py").touch()
        self.store = self.code_root / ".eve"
        self.store.mkdir()
        self.runtime_root = self.root / "runtime"
        self.now = datetime(2026, 9, 12, 22, 0, tzinfo=timezone.utc)

    def at(self, seconds_ago):
        return (self.now - timedelta(seconds=seconds_ago)).isoformat()

    def write(self, name, value):
        (self.store / name).write_text(json.dumps(value))

    @contextmanager
    def running(self, mode="recurrent"):
        with patch.object(runtime, "_now", return_value=self.at(600)):
            with runtime.runner_lease(self.runtime_root, code_path=self.code_root / "eve.py",
                                      state_root=self.store, mode=mode) as owner:
                self.state = {
                    "daemon_process_id": os.getpid(), "daemon_code_path": owner["code_path"],
                    "daemon_runner_owner_id": owner["owner_id"], "daemon_runner_mode": mode,
                    "last_loop_at": self.at(60), "private_memory": "must not be projected",
                }
                self.activity = {
                    "pid": os.getpid(), "owner_id": owner["owner_id"], "run_mode": mode,
                    "status": "active", "cycle_id": "fixture-cycle",
                    "cycle_started_at": self.at(60), "last_heartbeat_at": self.at(10),
                    "heartbeat_interval_seconds": 15, "max_active_cycle_seconds": 900,
                    "heartbeat_count": 4, "private_error": "must not be projected",
                }
                self.write("state.json", self.state)
                self.write("daemon_activity.json", self.activity)
                yield owner

    def observe(self):
        return runtime.observe_runner(self.runtime_root, code_roots=[self.code_root, self.runtime_root])

    def evaluate(self, observation=None):
        return runtime.observed_liveness(observation or self.observe(), {}, now=self.now)

    def test_no_runner_does_not_create_a_runtime_tree(self):
        observation = self.observe()
        self.assertFalse(observation["available"])
        self.assertFalse(self.runtime_root.exists())

    def test_windows_process_observation_is_a_query_not_kill_zero(self):
        with patch.object(runtime.os, "name", "nt"), patch.object(runtime.os, "kill") as kill, patch.object(
            runtime.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, '"python.exe","42","Console","1","100 K"\n')
        ) as run:
            runtime._check_process(42)
            kill.assert_not_called()
            self.assertEqual("tasklist", run.call_args.args[0][0])
            self.assertEqual(3, run.call_args.kwargs["timeout"])
            run.return_value = subprocess.CompletedProcess([], 0, 'INFO: No tasks are running\n')
            with self.assertRaises(ProcessLookupError):
                runtime._check_process(42)

    def test_owned_source_not_stale_runtime_mirror_and_read_only_projection(self):
        with self.running():
            mirror = self.runtime_root / ".eve"
            mirror.mkdir()
            (mirror / "state.json").write_text('{"daemon_process_id":999}')
            (mirror / "daemon_activity.json").write_text('{"pid":999}')
            paths = [self.store / "state.json", self.store / "daemon_activity.json",
                     mirror / "state.json", mirror / "daemon_activity.json"]
            before = [(p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths]
            observed = self.observe()
            self.assertTrue(observed["consistent"])
            self.assertEqual(str(self.store / "state.json"), observed["state_path"])
            self.assertNotIn("must not be projected", json.dumps(observed))
            self.assertEqual(before, [(p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths])
            self.assertTrue(self.evaluate(observed)["active"])

    def test_runtime_owned_root_uses_same_contract(self):
        self.code_root = self.runtime_root
        self.code_root.mkdir()
        (self.code_root / "eve.py").touch()
        self.store = self.code_root / ".eve"
        self.store.mkdir()
        with self.running():
            self.assertTrue(self.observe()["consistent"])
            self.assertTrue(self.evaluate()["live"])

    def test_inconsistent_identity_never_falls_back_to_fresh_timestamps(self):
        with self.running():
            cases = [("state.json", "daemon_runner_owner_id", "foreign"),
                     ("state.json", "daemon_runner_mode", "once"),
                     ("state.json", "daemon_process_id", 999),
                     ("state.json", "daemon_code_path", "/different/eve.py"),
                     ("daemon_activity.json", "owner_id", "foreign"),
                     ("daemon_activity.json", "pid", 999),
                     ("daemon_activity.json", "run_mode", "once")]
            for name, key, value in cases:
                with self.subTest(name=name, key=key):
                    original = self.state if name == "state.json" else self.activity
                    self.write(name, {**original, key: value})
                    result = self.evaluate()
                    self.assertFalse(result["live"])
                    self.assertEqual("inconclusive", result["status"])
                    self.write(name, original)

    def test_unadmitted_root_is_not_read(self):
        with self.running(), patch.object(runtime, "_read_record", wraps=runtime._read_record) as read:
            observation = runtime.observe_runner(self.runtime_root, code_roots=[self.root / "other"])
            self.assertEqual("owner_root_not_admitted", observation["problem"])
            self.assertNotIn(self.store / "state.json", [c.args[0] for c in read.call_args_list])

    def test_owner_change_during_read_is_inconclusive(self):
        with self.running():
            first = runtime.inspect_runner(self.runtime_root)
            second = copy.deepcopy(first)
            second["owner_receipt"]["owner_id"] = "replacement"
            with patch.object(runtime, "inspect_runner", side_effect=[first, second]):
                result = self.observe()
            self.assertEqual("owner_changed_during_observation", result["problem"])
            self.assertFalse(result["consistent"])

    def test_dead_pid_even_with_held_lease_is_not_live(self):
        with self.running(), patch.object(runtime.os, "kill", side_effect=ProcessLookupError):
            self.assertEqual("inconclusive", self.evaluate()["status"])

    def test_released_owner_with_fresh_files_is_dormant(self):
        with self.running():
            pass
        result = self.evaluate()
        self.assertFalse(result["live"])
        self.assertEqual("dormant", result["status"])

    def test_once_is_never_recurrence(self):
        with self.running("once"):
            result = self.evaluate()
            self.assertEqual("diagnostic", result["status"])
            self.assertFalse(result["live"])
            self.assertFalse(result["daemon_running"])

    def test_failed_stale_future_or_overbound_activity_cannot_borrow_fresh_loop(self):
        with self.running():
            cases = [{"status": "failed"}, {"last_heartbeat_at": self.at(120)},
                     {"last_heartbeat_at": self.at(-86400)}, {"cycle_started_at": self.at(-86400)},
                     {"cycle_started_at": None}, {"cycle_started_at": "2026-09-12T22:00:00"},
                     {"cycle_started_at": self.at(950)}, {"status": "unknown"}]
            for delta in cases:
                with self.subTest(delta=delta):
                    self.write("daemon_activity.json", {**self.activity, **delta})
                    result = self.evaluate()
                    self.assertFalse(result["live"])
                    self.assertEqual("stale", result["status"])

    def test_idle_recent_completed_cycle_is_live_but_not_active(self):
        with self.running():
            self.write("daemon_activity.json", {**self.activity, "status": "idle"})
            result = self.evaluate()
            self.assertTrue(result["live"])
            self.assertFalse(result["active"])
            self.assertEqual("live", result["status"])
            self.write("state.json", {**self.state, "last_loop_at": self.at(-86400)})
            self.assertFalse(self.evaluate()["live"])

    def test_activity_cannot_extend_configured_cycle_deadline(self):
        with self.running():
            self.write("daemon_activity.json", {**self.activity, "cycle_started_at": self.at(400),
                                                "max_active_cycle_seconds": 3600})
            result = runtime.observed_liveness(self.observe(), {"daemon_max_active_cycle_seconds": 180}, now=self.now)
            self.assertFalse(result["live"])
            self.assertEqual(180, result["activity"]["max_active_cycle_seconds"])

    def test_malformed_missing_oversized_and_symlinked_evidence_are_inconclusive(self):
        with self.running():
            path = self.store / "state.json"
            for content in ['[]', '{broken secret text', ' ' * (1024 * 1024 + 1)]:
                path.write_text(content)
                observed = self.observe()
                self.assertFalse(observed["consistent"])
                self.assertNotIn("secret text", json.dumps(observed))
            path.unlink()
            self.assertFalse(self.observe()["consistent"])
            target = self.root / "unrelated.json"
            target.write_text(json.dumps(self.state))
            path.symlink_to(target)
            self.assertFalse(self.observe()["consistent"])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "Unix FIFO test")
    def test_fifo_observation_does_not_block(self):
        with self.running():
            path = self.store / "daemon_activity.json"
            path.unlink()
            os.mkfifo(path)
            self.assertFalse(self.observe()["consistent"])

    def test_dataless_record_is_not_opened(self):
        with self.running():
            target = self.store / "daemon_activity.json"
            original = Path.lstat
            def lstat(path):
                result = original(path)
                if path == target:
                    class Dataless:
                        st_mode = result.st_mode
                        st_flags = 0x40000000
                    return Dataless()
                return result
            with patch.object(Path, "lstat", lstat):
                self.assertFalse(self.observe()["consistent"])

    def test_health_uses_owned_evidence_without_ledger_hydration_or_native_log(self):
        with self.running(), ExitStack() as stack:
            observation = self.observe()
            # Use current clock for the facade's liveness calculation.
            observation["ownership"]["owner_receipt"]["started_at"] = eve.utc_now()
            for key in ["cycle_started_at", "last_heartbeat_at"]:
                observation["activity"][key] = eve.utc_now()
            observation["state"]["last_loop_at"] = eve.utc_now()
            stack.enter_context(patch.object(eve, "observe_core_runner", return_value=observation))
            stack.enter_context(patch.object(eve, "inspect_launch_agent_status", return_value={"state": "unknown"}))
            untouched = [stack.enter_context(patch.object(eve, name)) for name in [
                "doctor_runtime_state_with_recent_entries", "load_state", "read_text_tail"]]
            result = eve.daemon_health_diagnostics({})
            self.assertFalse(result["degraded"])
            self.assertEqual("unknown", result["native_service_state"])
            self.assertEqual("running", result["state"])
            for mock in untouched:
                mock.assert_not_called()

    def test_inconclusive_owned_observation_cannot_use_healthy_native_fallback(self):
        with patch.object(eve, "observe_core_runner", return_value={"available": True, "consistent": False,
                "problem": "owner_changed_during_observation", "ownership": {"lease_held": True}}), patch.object(
                eve, "inspect_launch_agent_status", return_value={"state": "running"}):
            self.assertTrue(eve.daemon_health_diagnostics({})["degraded"])

    def test_native_storage_routing_predicate_is_unchanged_by_owned_observation(self):
        mirror = self.runtime_root / ".eve"
        mirror.mkdir(parents=True)
        source_path = self.store / "example.json"
        mirror_path = mirror / "example.json"
        source_path.write_text('{}')
        mirror_path.write_text('{}')
        os.utime(source_path, (200, 200))
        os.utime(mirror_path, (100, 100))
        with ExitStack() as stack:
            stack.enter_context(patch.object(eve, "APP_DIR", self.store))
            stack.enter_context(patch.object(eve, "RUNTIME_APP_DIR", mirror))
            stack.enter_context(patch.object(eve, "ensure_store"))
            observer = stack.enter_context(patch.object(eve, "observe_core_runner", side_effect=AssertionError("not a router")))
            for native, expected in [(False, source_path), (True, mirror_path)]:
                with patch.object(eve, "daemon_runtime_running", return_value=native):
                    self.assertEqual(expected, eve.resolve_store_read_path(source_path, prefer_runtime=True))
            observer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
