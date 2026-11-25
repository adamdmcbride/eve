import json
import errno
import os
import stat
import threading
import unittest
import unittest.mock
from pathlib import Path
from tempfile import TemporaryDirectory

import eve_store


class EveStoreTests(unittest.TestCase):
    def test_nonblocking_lock_excludes_another_thread_without_waiting(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "owner.json"
            result = []
            def contender():
                try:
                    with eve_store.file_lock(path, blocking=False, reentrant=False):
                        result.append("admitted")
                except eve_store.LockBusy:
                    result.append("busy")
            with eve_store.file_lock(path):
                worker = threading.Thread(target=contender, daemon=True)
                worker.start()
                worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(["busy"], result)
            with eve_store.file_lock(path, blocking=False, reentrant=False):
                pass

    def test_nonreentrant_failure_keeps_outer_lock_depth(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "owner.json"
            with eve_store.file_lock(path):
                with self.assertRaises(eve_store.LockBusy):
                    with eve_store.file_lock(path, blocking=False, reentrant=False):
                        self.fail("duplicate owner")
                self.assertEqual(1, eve_store._thread_depths()[eve_store._path_key(path)])
            self.assertNotIn(eve_store._path_key(path), eve_store._thread_depths())

    def test_nonblocking_windows_contention_is_not_an_unlock(self):
        fake = unittest.mock.Mock(LK_NBLCK=2, LK_UNLCK=3)
        fake.locking.side_effect = OSError(errno.EACCES, "busy")
        with TemporaryDirectory() as temp_dir, unittest.mock.patch.object(
            eve_store, "fcntl", None
        ), unittest.mock.patch.object(eve_store, "msvcrt", fake):
            path = Path(temp_dir) / "owner.json"
            with self.assertRaises(eve_store.LockBusy):
                with eve_store.file_lock(path, blocking=False, reentrant=False):
                    pass
            self.assertEqual(1, fake.locking.call_count)
            self.assertEqual(fake.LK_NBLCK, fake.locking.call_args.args[1])
            self.assertNotIn(eve_store._path_key(path), eve_store._thread_depths())

    def test_nonblocking_unsupported_backend_does_not_grant_ownership(self):
        with TemporaryDirectory() as temp_dir, unittest.mock.patch.object(
            eve_store, "fcntl", None
        ), unittest.mock.patch.object(eve_store, "msvcrt", None):
            with self.assertRaisesRegex(RuntimeError, "kernel file-lock"):
                with eve_store.file_lock(Path(temp_dir) / "owner.json", blocking=False):
                    self.fail("unprotected owner")

    def test_load_json_dict_returns_default_for_missing_or_invalid_file(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            self.assertEqual({"fallback": True}, eve_store.load_json_dict(path, default={"fallback": True}))

            path.write_text("{not valid json\n", encoding="utf-8")
            self.assertEqual({"fallback": True}, eve_store.load_json_dict(path, default={"fallback": True}))

    def test_write_json_dict_persists_newline_terminated_json(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            eve_store.write_json_dict(path, {"name": "Eve", "ready": True}, sort_keys=True)

            raw = path.read_text(encoding="utf-8")
            self.assertTrue(raw.endswith("\n"))
            self.assertEqual({"name": "Eve", "ready": True}, json.loads(raw))
            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))

    def test_append_jsonl_record_keeps_owner_only_permissions(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "events.jsonl"
            eve_store.append_jsonl_record(path, {"kind": "note"})

            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))

    def test_file_lock_removes_zero_byte_dataless_placeholder(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            lock_path = path.with_name(f".{path.name}.lock")
            lock_path.write_text("", encoding="utf-8")

            class DatalessStat:
                st_size = 0
                st_flags = eve_store._MACOS_DATALESS_FLAG

            original_stat = Path.stat

            def fake_stat(candidate, *args, **kwargs):
                if candidate == lock_path:
                    return DatalessStat()
                return original_stat(candidate, *args, **kwargs)

            with unittest.mock.patch.object(Path, "stat", fake_stat):
                with eve_store.file_lock(path):
                    self.assertTrue(lock_path.exists())

            self.assertTrue(lock_path.exists())

    def test_file_lock_releases_process_lock_when_os_open_fails(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            with unittest.mock.patch.object(
                eve_store.os,
                "open",
                side_effect=PermissionError("lock denied"),
            ):
                with self.assertRaisesRegex(PermissionError, "lock denied"):
                    with eve_store.file_lock(path):
                        self.fail("unreachable")

            acquired = threading.Event()

            def acquire_after_failure():
                with eve_store.file_lock(path):
                    acquired.set()

            worker = threading.Thread(target=acquire_after_failure, daemon=True)
            worker.start()
            worker.join(timeout=2)
            self.assertTrue(acquired.is_set(), "failed lock attempt leaked the in-process lock")
            self.assertNotIn(eve_store._path_key(path), eve_store._thread_depths())

    def test_nested_file_lock_acquires_kernel_lock_once(self):
        if eve_store.fcntl is None:
            self.skipTest("fcntl unavailable")
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            with unittest.mock.patch.object(
                eve_store.fcntl,
                "flock",
                wraps=eve_store.fcntl.flock,
            ) as flock:
                with eve_store.file_lock(path):
                    with eve_store.file_lock(path):
                        pass

            self.assertEqual(1, flock.call_count)
            self.assertEqual(eve_store.fcntl.LOCK_EX, flock.call_args.args[1])

    def test_file_lock_refuses_symlink_without_truncating_target(self):
        if not getattr(os, "O_NOFOLLOW", 0):
            self.skipTest("O_NOFOLLOW unavailable")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "state.json"
            lock_path = root / ".state.json.lock"
            victim = root / "victim.txt"
            victim.write_text("preserve me", encoding="utf-8")
            try:
                lock_path.symlink_to(victim)
            except OSError as exc:  # pragma: no cover - platform capability
                self.skipTest(f"symlinks unavailable: {exc}")

            with self.assertRaises(OSError):
                with eve_store.file_lock(path):
                    self.fail("unreachable")
            self.assertEqual("preserve me", victim.read_text(encoding="utf-8"))

    def test_windows_fallback_acquires_and_releases_one_byte_lock(self):
        class FakeMsvcrt:
            LK_LOCK = 1
            LK_UNLCK = 2

            def __init__(self):
                self.calls = []

            def locking(self, descriptor, mode, byte_count):
                self.calls.append((descriptor, mode, byte_count))

        fake = FakeMsvcrt()
        with TemporaryDirectory() as temp_dir, unittest.mock.patch.object(
            eve_store,
            "fcntl",
            None,
        ), unittest.mock.patch.object(eve_store, "msvcrt", fake):
            path = Path(temp_dir) / "state.json"
            with eve_store.file_lock(path):
                pass

            lock_path = path.with_name(f".{path.name}.lock")
            self.assertEqual(b"\0", lock_path.read_bytes())
            self.assertEqual(
                [(fake.LK_LOCK, 1), (fake.LK_UNLCK, 1)],
                [(mode, byte_count) for _descriptor, mode, byte_count in fake.calls],
            )

    def test_mutate_json_dict_reads_mutates_and_writes_under_one_helper(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            eve_store.write_json_dict(path, {"count": 1})

            def bump(payload):
                payload["count"] = int(payload.get("count", 0)) + 1
                return payload["count"]

            payload, result = eve_store.mutate_json_dict(path, bump)

            self.assertEqual(2, result)
            self.assertEqual({"count": 2}, payload)
            self.assertEqual({"count": 2}, eve_store.load_json_dict(path))

    def test_jsonl_helpers_skip_invalid_lines_and_replace_records_atomically(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "entries.jsonl"
            eve_store.append_jsonl_record(path, {"kind": "note", "text": "first"})
            with path.open("a", encoding="utf-8") as handle:
                handle.write("not-json\n")
            eve_store.append_jsonl_record(path, {"kind": "note", "text": "second"})

            records = eve_store.read_jsonl_records(path)
            self.assertEqual(
                [
                    {"kind": "note", "text": "first"},
                    {"kind": "note", "text": "second"},
                ],
                records,
            )

            eve_store.write_jsonl_records(path, [{"kind": "thought", "text": "replacement"}])
            self.assertEqual([{"kind": "thought", "text": "replacement"}], eve_store.read_jsonl_records(path))

    def test_jsonl_tail_reader_returns_recent_valid_records(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "events.jsonl"
            for index in range(6):
                eve_store.append_jsonl_record(path, {"index": index})
            with path.open("a", encoding="utf-8") as handle:
                handle.write("not-json\n")
            eve_store.append_jsonl_record(path, {"index": 6})

            self.assertEqual(
                [{"index": 4}, {"index": 5}, {"index": 6}],
                eve_store.read_jsonl_tail_records(path, 3),
            )

    def test_count_jsonl_lines_and_text_tail(self):
        with TemporaryDirectory() as temp_dir:
            jsonl_path = Path(temp_dir) / "events.jsonl"
            jsonl_path.write_text('{"a":1}\n{"a":2}\n{"a":3}', encoding="utf-8")
            self.assertEqual(3, eve_store.count_jsonl_lines(jsonl_path))

            text_path = Path(temp_dir) / "daemon.log"
            text_path.write_text("one\n\ntwo\nthree\nfour\n", encoding="utf-8")
            self.assertEqual("three | four", eve_store.read_text_tail(text_path, max_lines=2, max_chars=100))


if __name__ == "__main__":
    unittest.main()
