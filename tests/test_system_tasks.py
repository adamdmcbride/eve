import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import eve
import eve_store


class SystemTaskTests(unittest.TestCase):
    def _snapshot(self, scanned_at: str, summary: str) -> dict:
        return {
            "frontmost_app": "Terminal",
            "load_state": "idle",
            "workspace": {
                "scanned_at": scanned_at,
                "recent_changes_summary": summary,
                "focus_files": [{"path": "eve.py"}],
                "recent_changes": [{"path": "eve.py"}],
            },
            "disk": {"used_percent": 10, "free_bytes": 100_000_000_000},
        }

    def test_gpu_followup_snapshot_refresh_updates_existing_open_task(self):
        with TemporaryDirectory() as tmpdir:
            tasks_path = Path(tmpdir) / "system_tasks.jsonl"
            eve_store.write_jsonl_records(tasks_path, [])
            state = {}

            with patch.object(eve, "SYSTEM_TASKS_PATH", tasks_path), patch.object(
                eve, "append_entry", return_value=None
            ), patch.object(eve, "load_config", return_value={}), patch.object(
                eve, "cleanup_candidate_specs", return_value=[]
            ), patch.object(
                eve, "system_background_gate_reason", return_value=""
            ):
                first_created = eve.refresh_system_tasks_from_snapshot(
                    self._snapshot("2026-06-13T23:00:00+00:00", "first scan"),
                    state,
                    "daemon",
                    config={},
                )
                first_gpu = [
                    record
                    for record in eve_store.read_jsonl_records(tasks_path)
                    if record.get("kind") == "gpu_followup_reflection"
                ][0]
                second_created = eve.refresh_system_tasks_from_snapshot(
                    self._snapshot("2026-06-13T23:10:00+00:00", "second scan"),
                    state,
                    "daemon",
                    config={},
                )

            records = eve_store.read_jsonl_records(tasks_path)
            gpu_tasks = [record for record in records if record.get("kind") == "gpu_followup_reflection"]
            duplicate_groups = eve.roadmap_duplicate_groups(gpu_tasks, fields=["title"])

        self.assertEqual(1, len(gpu_tasks))
        self.assertEqual([], duplicate_groups)
        self.assertEqual(first_gpu["id"], gpu_tasks[0]["id"])
        self.assertEqual("2026-06-13T23:10:00+00:00", gpu_tasks[0]["metadata"]["scanned_at"])
        self.assertIn("second scan", gpu_tasks[0]["summary"])
        self.assertEqual(1, sum(1 for task in first_created if task.get("kind") == "gpu_followup_reflection"))
        self.assertEqual(0, sum(1 for task in second_created if task.get("kind") == "gpu_followup_reflection"))

    def test_gpu_followup_snapshot_refresh_does_not_reopen_completed_task(self):
        with TemporaryDirectory() as tmpdir:
            tasks_path = Path(tmpdir) / "system_tasks.jsonl"
            eve_store.write_jsonl_records(
                tasks_path,
                [
                    eve.normalize_system_task(
                        {
                            "id": "completed-gpu",
                            "kind": "gpu_followup_reflection",
                            "title": "Escalate only unresolved work from CPU to GPU",
                            "status": "completed",
                            "lane": "hybrid",
                            "dedupe_key": "gpu_followup_reflection:closed",
                            "metadata": {"evidence_key": "old"},
                        }
                    )
                ],
            )
            state = {}

            with patch.object(eve, "SYSTEM_TASKS_PATH", tasks_path), patch.object(
                eve, "append_entry", return_value=None
            ), patch.object(eve, "load_config", return_value={}), patch.object(
                eve, "cleanup_candidate_specs", return_value=[]
            ), patch.object(
                eve, "system_background_gate_reason", return_value=""
            ):
                eve.refresh_system_tasks_from_snapshot(
                    self._snapshot("2026-06-13T23:20:00+00:00", "new scan after closure"),
                    state,
                    "daemon",
                    config={},
                )

            records = eve_store.read_jsonl_records(tasks_path)
            completed = [record for record in records if record.get("id") == "completed-gpu"][0]
            open_gpu_tasks = [
                record
                for record in records
                if record.get("kind") == "gpu_followup_reflection"
                and record.get("status") in eve.SYSTEM_TASK_OPEN_STATUSES
            ]

        self.assertEqual("completed", completed["status"])
        self.assertEqual(1, len(open_gpu_tasks))
        self.assertNotEqual("completed-gpu", open_gpu_tasks[0]["id"])
        self.assertEqual("2026-06-13T23:20:00+00:00", open_gpu_tasks[0]["metadata"]["scanned_at"])


if __name__ == "__main__":
    unittest.main()
