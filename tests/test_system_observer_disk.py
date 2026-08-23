import importlib.util
import json
import tempfile
import unittest
from collections import namedtuple
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
OBSERVER_PATH = ROOT / "bin" / "eve_system_observer.py"


def load_observer_module():
    spec = importlib.util.spec_from_file_location("eve_system_observer_under_test", OBSERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SystemObserverDiskTests(unittest.TestCase):
    def test_load_model_status_prefers_newer_runtime_watchdog(self) -> None:
        observer = load_observer_module()
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            app_dir = root / "source" / ".eve"
            runtime_app_dir = root / "runtime" / ".eve"
            app_dir.mkdir(parents=True)
            runtime_app_dir.mkdir(parents=True)
            (app_dir / "model_watchdog_status.json").write_text(
                json.dumps({"updated_at": "2026-05-06T20:44:21+00:00", "summary": "stale source"}),
                encoding="utf-8",
            )
            (runtime_app_dir / "model_watchdog_status.json").write_text(
                json.dumps({"updated_at": "2026-05-06T21:18:29+00:00", "summary": "fresh runtime"}),
                encoding="utf-8",
            )

            with (
                patch.object(observer, "APP_DIR", app_dir),
                patch.object(observer, "RUNTIME_APP_DIR", runtime_app_dir),
            ):
                status = observer.load_model_status()

        self.assertEqual(status["summary"], "fresh runtime")

    def test_load_model_status_uses_source_when_it_is_newer(self) -> None:
        observer = load_observer_module()
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            app_dir = root / "source" / ".eve"
            runtime_app_dir = root / "runtime" / ".eve"
            app_dir.mkdir(parents=True)
            runtime_app_dir.mkdir(parents=True)
            (app_dir / "model_watchdog_status.json").write_text(
                json.dumps({"updated_at": "2026-05-06T21:25:00+00:00", "summary": "fresh source"}),
                encoding="utf-8",
            )
            (runtime_app_dir / "model_watchdog_status.json").write_text(
                json.dumps({"updated_at": "2026-05-06T21:18:29+00:00", "summary": "older runtime"}),
                encoding="utf-8",
            )

            with (
                patch.object(observer, "APP_DIR", app_dir),
                patch.object(observer, "RUNTIME_APP_DIR", runtime_app_dir),
            ):
                status = observer.load_model_status()

        self.assertEqual(status["summary"], "fresh source")

    def test_disk_status_prefers_macos_important_usage_capacity(self) -> None:
        observer = load_observer_module()
        usage = namedtuple("usage", "total used free")(1000, 980, 20)

        with (
            patch.object(observer.shutil, "disk_usage", return_value=usage),
            patch.object(
                observer,
                "macos_volume_capacity",
                return_value={
                    "volume_name": "Macintosh HD",
                    "total_bytes": 1000,
                    "available_bytes": 20,
                    "important_available_bytes": 600,
                    "opportunistic_available_bytes": 10,
                },
            ),
        ):
            disk = observer.disk_status()

        self.assertEqual(disk["capacity_source"], "macos_important_usage")
        self.assertEqual(disk["free_bytes"], 600)
        self.assertEqual(disk["used_percent"], 40.0)
        self.assertEqual(disk["strict_free_bytes"], 20)
        self.assertEqual(disk["strict_used_percent"], 98.0)

    def test_disk_status_falls_back_to_strict_free_space(self) -> None:
        observer = load_observer_module()
        usage = namedtuple("usage", "total used free")(1000, 750, 250)

        with (
            patch.object(observer.shutil, "disk_usage", return_value=usage),
            patch.object(observer, "macos_volume_capacity", return_value={}),
        ):
            disk = observer.disk_status()

        self.assertEqual(disk["capacity_source"], "posix_statvfs")
        self.assertEqual(disk["free_bytes"], 250)
        self.assertEqual(disk["used_percent"], 75.0)
        self.assertEqual(disk["strict_free_bytes"], 250)


if __name__ == "__main__":
    unittest.main()
