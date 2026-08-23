import json
import stat
import unittest
import unittest.mock
from pathlib import Path
from tempfile import TemporaryDirectory

import eve_store


class EveStoreTests(unittest.TestCase):
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
