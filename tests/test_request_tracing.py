from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import eve_db
import eve_otel_genai
import eve_tracing


class RequestTracingTests(unittest.TestCase):
    def test_disabled_or_contextless_instrumentation_never_retries_an_operation(self):
        for root in (False, True):
            with self.subTest(root=root), tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"EVE_REQUEST_TRACING": "0"}):
                calls = []
                path = Path(tmp) / "trace.db"

                @eve_tracing.traced(lambda: path, "operation", root=root)
                def operation():
                    calls.append("effect")
                    raise RuntimeError("work failed")

                with self.assertRaises(RuntimeError):
                    operation()
                self.assertEqual(["effect"], calls)
                self.assertFalse(path.exists())

    def test_real_worker_context_joins_without_argument_or_result_capture(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"EVE_REQUEST_TRACING": "1"}):
            path = Path(tmp) / "trace.db"

            @eve_tracing.traced(lambda: path, "model.chat", attributes={"gen_ai.operation.name": "chat"}, outcome=lambda result: True)
            def child(private_argument):
                return "private result"

            @eve_tracing.traced(lambda: path, "request", root=True, trace_id=lambda: "request-id")
            def request():
                with ThreadPoolExecutor(max_workers=2) as executor:
                    return [eve_tracing.submit(executor, child, "private input").result() for _ in range(2)]

            self.assertEqual(["private result"] * 2, request())
            rows = eve_db.read_trace_spans(path)
        root = next(row for row in rows if row["name"] == "request")
        self.assertTrue(all(row["trace_id"] == "request-id" for row in rows))
        for row in rows:
            if row["name"] != "request":
                self.assertEqual(root["id"], row["parent_id"])
        _, exported = eve_otel_genai.build_genai_export(rows)
        self.assertNotIn("private", json.dumps(exported))
        self.assertEqual("UNSET", eve_otel_genai.span_to_genai(root)["span"]["status"]["code"])
        self.assertIsNone(eve_tracing._span_context.get())

    def test_error_classifier_and_store_failure_cannot_repeat_effect_or_replace_result(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"EVE_REQUEST_TRACING": "1"}):
            calls = []

            def bad_classifier(result):
                raise ValueError("classification unavailable")

            @eve_tracing.traced(lambda: Path(tmp)/"trace.db", "request", root=True, outcome=bad_classifier)
            def operation():
                calls.append("effect")
                return {"verified": "unknown"}

            with patch.object(eve_tracing.eve_db, "record_trace_span", side_effect=OSError("disk unavailable")):
                self.assertEqual({"verified": "unknown"}, operation())
            self.assertEqual(["effect"], calls)
            self.assertIsNone(eve_tracing._span_context.get())

    def test_system_exit_is_failure_not_false_success_or_private_error_capture(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"EVE_REQUEST_TRACING": "1"}):
            path = Path(tmp)/"trace.db"

            @eve_tracing.traced(lambda: path, "request", root=True)
            def operation():
                raise SystemExit("private model prompt")

            with self.assertRaises(SystemExit):
                operation()
            rows = eve_db.read_trace_spans(path)
        self.assertEqual("ERROR", eve_otel_genai.span_to_genai(rows[0])["span"]["status"]["code"])
        self.assertNotIn("private model prompt", json.dumps(rows))


if __name__ == "__main__":
    unittest.main()
