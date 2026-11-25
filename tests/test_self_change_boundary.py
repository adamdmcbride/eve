"""Graph-guided self-change extraction and rollback persistence contracts."""
import importlib
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import eve

ROOT = Path(__file__).resolve().parents[1]


class RollbackStoreTests(unittest.TestCase):
    def test_concurrent_before_images_preserve_every_key_and_first_value(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(eve, "SELF_CHANGE_DIR", Path(tmp)):
            count = 12
            start = threading.Barrier(count)
            original_load = eve.load_self_change_before_image

            def slow_read(session_id):
                result = original_load(session_id)
                time.sleep(0.01)  # amplify the old unlocked read/modify/write race
                return result

            def record(index):
                start.wait(timeout=10)
                return eve.record_self_change_before_image(
                    {"_self_change_session": "concurrent"}, "set_config", str(index), index
                )

            with patch.object(eve, "load_self_change_before_image", side_effect=slow_read):
                with ThreadPoolExecutor(max_workers=count) as workers:
                    self.assertTrue(all(workers.map(record, range(count))))
            saved = eve.load_self_change_before_image("concurrent")
            self.assertEqual({str(i): i for i in range(count)}, saved["set_config"])
            self.assertFalse(eve.record_self_change_before_image(
                {"_self_change_session": "concurrent"}, "set_config", "0", "second value"
            ))
            self.assertEqual(saved, eve.load_self_change_before_image("concurrent"))

    def test_failed_before_image_replace_keeps_previous_bytes(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(eve, "SELF_CHANGE_DIR", Path(tmp)):
            config = {"_self_change_session": "atomic"}
            eve.record_self_change_before_image(config, "set_config", "first", 45)
            path = eve.self_change_before_image_path("atomic")
            previous = path.read_bytes()
            with patch.object(Path, "replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    eve.record_self_change_before_image(config, "set_config", "second", 120)
            self.assertEqual(previous, path.read_bytes())
            self.assertEqual([], list(path.parent.glob(".before.json.tmp.*")))

    def test_failed_block_replace_keeps_previous_bytes(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(eve, "ACTION_BLOCKS_PATH", Path(tmp) / "blocks.json"):
            eve.save_action_blocks({"first": {"until": "2099-01-01"}})
            previous = eve.ACTION_BLOCKS_PATH.read_bytes()
            with patch.object(Path, "replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    eve.save_action_blocks({"second": {"until": "2099-01-01"}})
            self.assertEqual(previous, eve.ACTION_BLOCKS_PATH.read_bytes())
            self.assertEqual([], list(Path(tmp).glob(".blocks.json.tmp.*")))

    def test_rollback_files_are_owner_only_and_no_session_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(eve, "SELF_CHANGE_DIR", Path(tmp)), patch.object(eve, "ACTION_BLOCKS_PATH", Path(tmp) / "blocks.json"):
            self.assertFalse(eve.record_self_change_before_image({}, "set_config", "key", 1))
            self.assertEqual([], list(Path(tmp).iterdir()))
            eve.record_self_change_before_image({"_self_change_session": "private"}, "set_config", "key", 1)
            eve.save_action_blocks({})
            for path in (eve.self_change_before_image_path("private"), eve.ACTION_BLOCKS_PATH):
                self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))

    def test_concurrent_ledger_appends_keep_complete_records(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(eve, "SELF_CHANGE_LEDGER_PATH", Path(tmp) / "ledger.jsonl"):
            with ThreadPoolExecutor(max_workers=8) as workers:
                list(workers.map(lambda i: eve.append_self_change_ledger({"id": i, "detail": "x" * 8000}), range(24)))
            rows = eve.read_self_change_ledger()
            self.assertEqual(set(range(24)), {row["id"] for row in rows})
            self.assertEqual(24, len(rows))
            self.assertTrue(all(len(row["detail"]) == 8000 for row in rows))
            self.assertEqual(0o600, stat.S_IMODE(eve.SELF_CHANGE_LEDGER_PATH.stat().st_mode))

    def test_ledger_write_does_not_bootstrap_unrelated_stores(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(eve, "SELF_CHANGE_LEDGER_PATH", Path(tmp) / "ledger.jsonl"), patch.object(eve, "ensure_store", side_effect=AssertionError("unrelated store bootstrap")):
            eve.append_self_change_ledger({"session_id": "isolated"})
            self.assertEqual([{"session_id": "isolated"}], eve.read_self_change_ledger())


class SelfChangeBoundaryTests(unittest.TestCase):
    def test_facade_exports_the_single_implementation(self):
        module = importlib.import_module("eve_self_change")
        self.assertEqual(26, len(module.__all__))
        for name in module.__all__:
            self.assertIs(getattr(eve, name), getattr(module, name), name)

    def test_module_import_does_not_import_the_facade(self):
        out = subprocess.run(
            [sys.executable, "-c", "import sys, eve_self_change; assert 'eve' not in sys.modules"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(0, out.returncode, out.stderr)

    def test_dependency_patches_are_resolved_at_call_time(self):
        module = importlib.import_module("eve_self_change")
        with patch.object(eve, "normalize_text_value", return_value=""), patch.object(eve, "read_proposals") as read:
            self.assertFalse(module.proposal_is_actionable({"title": "Proposal ## Title Example"}))
            read.assert_not_called()
        with patch.object(eve, "SELF_CHANGE_DIR", Path("/isolated")):
            self.assertEqual(Path("/isolated/s/before.json"), module.self_change_before_image_path("s"))

    def test_script_entrypoint_uses_its_own_facade_not_a_second_import(self):
        code = '''
import contextlib, io, runpy, sys
sys.argv = ["eve.py", "--help"]
with contextlib.redirect_stdout(io.StringIO()):
    try:
        runpy.run_path("eve.py", run_name="__main__")
    except SystemExit as exc:
        assert exc.code == 0, exc.code
import eve_late
facade = sys.modules["eve"]
assert facade.__name__ == "__main__", facade.__name__
assert eve_late.facade_module() is facade
assert facade.run_self_change_cycle.__module__ == "eve_self_change"
from pathlib import Path
facade.SELF_CHANGE_DIR = Path("/isolated-main")
assert facade.self_change_before_image_path("s") == Path("/isolated-main/s/before.json")
'''
        out = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True, timeout=60)
        self.assertEqual(0, out.returncode, out.stderr)


if __name__ == "__main__":
    unittest.main()
