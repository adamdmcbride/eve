import tempfile
import asyncio
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import eve_db
import eve_otel_genai
import eve_tracing


class TracingContractTests(unittest.TestCase):
    def test_concurrent_requests_do_not_share_trace_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.sqlite3"

            async def request(identifier):
                with eve_tracing.span(path, name="request", trace_id_value=identifier):
                    await asyncio.sleep(0)
                    return eve_tracing.record_span(path, name="child")

            async def run():
                return await asyncio.gather(request("first"), request("second"))

            first, second = asyncio.run(run())
        self.assertEqual("first", first["trace_id"])
        self.assertEqual("second", second["trace_id"])
        self.assertNotEqual(first["parent_id"], second["parent_id"])
        self.assertIsNone(eve_tracing._span_context.get())

    def test_nested_operations_and_direct_receipts_share_one_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.sqlite3"
            with eve_tracing.span(path, name="request", trace_id_value="request-id"):
                with eve_tracing.span(path, name="retrieval"):
                    inner = eve_tracing.record_span(path, name="model")
                tool = eve_tracing.record_span(path, name="tool")
                explicit = eve_tracing.record_span(path, name="foreign", trace_id_value="other-id")
            unrelated = eve_tracing.record_span(path, name="next-request")
            rows = {row["name"]: row for row in eve_db.read_trace_spans(path)}
        self.assertEqual(rows["request"]["id"], rows["retrieval"]["parent_id"])
        self.assertEqual(rows["retrieval"]["id"], inner["parent_id"])
        self.assertEqual(rows["request"]["id"], tool["parent_id"])
        self.assertEqual("request-id", inner["trace_id"])
        self.assertEqual("", explicit["parent_id"])
        self.assertNotEqual("request-id", unrelated["trace_id"])
        parent = eve_otel_genai.span_to_genai(rows["request"])["span"]
        child = eve_otel_genai.span_to_genai(tool)["span"]
        self.assertEqual(parent["span_id"], child["parent_span_id"])

    def test_exception_or_persistence_failure_clears_request_context(self):
        for persistence_fails in (False, True):
            with self.subTest(persistence_fails=persistence_fails), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "trace.sqlite3"
                with patch.object(eve_tracing.eve_db, "record_trace_span", side_effect=RuntimeError("unavailable") if persistence_fails else None):
                    with self.assertRaises(ValueError):
                        with eve_tracing.span(path, name="failed", trace_id_value="failed-request"):
                            raise ValueError("original error")
                self.assertIsNone(eve_tracing._span_context.get())

    def test_other_database_does_not_inherit_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            with eve_tracing.span(Path(tmp)/"source.db", name="request", trace_id_value="source"):
                child = eve_tracing.record_span(Path(tmp)/"runtime.db", name="independent")
        self.assertNotEqual("source", child["trace_id"])
        self.assertEqual("", child["parent_id"])

    def test_naive_started_at_is_interpreted_as_utc(self):
        parsed = eve_tracing._parse_started_at(datetime(2026, 1, 2, 3, 4, 5))

        self.assertEqual(datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc), parsed)

    def test_record_span_bounds_invalid_and_non_finite_durations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "trace.sqlite3"

            invalid = eve_tracing.record_span(db_path, name="invalid", duration_ms="not-a-number")
            infinite = eve_tracing.record_span(db_path, name="infinite", duration_ms=float("inf"))
            negative = eve_tracing.record_span(db_path, name="negative", duration_ms=-100)

            self.assertEqual(0.0, invalid["duration_ms"])
            self.assertEqual(0.0, infinite["duration_ms"])
            self.assertEqual(0.0, negative["duration_ms"])
            self.assertEqual(3, len(eve_db.read_trace_spans(db_path)))

    def test_context_span_does_not_mask_the_original_exception(self):
        with patch.object(eve_tracing, "record_span", side_effect=RuntimeError("telemetry unavailable")):
            with self.assertRaisesRegex(ValueError, "work failed"):
                with eve_tracing.span(Path("unused.sqlite3"), name="work"):
                    raise ValueError("work failed")

    def test_context_span_is_best_effort_when_only_persistence_fails(self):
        with patch.object(eve_tracing, "record_span", side_effect=RuntimeError("telemetry unavailable")):
            with eve_tracing.span(Path("unused.sqlite3"), name="work") as status:
                status["result"] = "complete"

        self.assertTrue(status["ok"])
        self.assertEqual("complete", status["result"])

    def test_prometheus_parser_handles_label_spaces_and_optional_timestamps(self):
        metrics = eve_tracing.parse_prometheus_metrics(
            'llama_tokens_total{model="eve fast"} 42 1780000000\n'
            'llama_slots_processing 2\n'
        )

        self.assertEqual(42.0, metrics['llama_tokens_total{model="eve fast"}'])
        self.assertEqual(2.0, metrics["llama_slots_processing"])

    def test_metrics_excerpt_is_strictly_bounded(self):
        excerpt = eve_tracing.metrics_excerpt("first\nsecond\nthird\n", limit=12)

        self.assertLessEqual(len(excerpt), 12)
        self.assertEqual("first\nsecond", excerpt)


if __name__ == "__main__":
    unittest.main()
