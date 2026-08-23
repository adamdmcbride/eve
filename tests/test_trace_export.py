import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import eve
import eve_db


class TraceExportTests(unittest.TestCase):
    def test_openinference_export_reads_local_spans(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "operational.sqlite3"
            eve_db.record_trace_span(
                db_path,
                {
                    "id": "span-1",
                    "trace_id": "trace-1",
                    "parent_id": "",
                    "name": "reply.synthesize",
                    "category": "reply",
                    "started_at": "2026-05-06T12:00:00+00:00",
                    "ended_at": "2026-05-06T12:00:01+00:00",
                    "duration_ms": 1000,
                    "ok": True,
                    "attributes": {"model": "eve-fast", "thread_id": "thread-1"},
                },
            )

            with patch.object(eve, "OPERATIONAL_DB_PATH", db_path):
                report, records = eve.build_openinference_trace_export(limit=10)

        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["span_count"], 1)
        self.assertEqual(records[0]["name"], "reply.synthesize")
        self.assertEqual(records[0]["status_code"], "OK")
        self.assertEqual(records[0]["attributes"]["openinference.span.kind"], "LLM")
        self.assertEqual(records[0]["attributes"]["eve.attr.model"], "eve-fast")

    def test_trace_export_save_writes_jsonl(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "trace.jsonl"
            record = eve.trace_span_to_openinference(
                {
                    "id": "span-2",
                    "trace_id": "trace-2",
                    "name": "tool.execute",
                    "category": "tool",
                    "started_at": "2026-05-06T12:00:00+00:00",
                    "ended_at": "2026-05-06T12:00:00+00:00",
                    "duration_ms": 0,
                    "ok": False,
                    "attributes": {"tool": "openclaw"},
                }
            )

            path = eve.save_openinference_trace_export([record], output_path=output)
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(path, output)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["attributes"]["openinference.span.kind"], "TOOL")
        self.assertEqual(rows[0]["status_code"], "ERROR")


if __name__ == "__main__":
    unittest.main()
