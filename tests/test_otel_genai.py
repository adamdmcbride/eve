from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import eve_otel_genai


class EveOpenTelemetryGenAITests(unittest.TestCase):
    def test_unknown_or_malformed_outcome_is_neither_success_nor_failure(self) -> None:
        for value in (None, "false", "true", 2, {}, []):
            with self.subTest(value=value):
                record = eve_otel_genai.span_to_genai({"id": "unknown", "ok": value})
                self.assertEqual("UNSET", record["span"]["status"]["code"])
                self.assertNotIn("error.type", record["span"]["attributes"])
        self.assertEqual("UNSET", eve_otel_genai.span_to_genai({"id": "absent"})["span"]["status"]["code"])

    def test_nonfinite_durations_remain_strict_json(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                record = eve_otel_genai.span_to_genai({"id": "duration", "duration_ms": value})
                self.assertEqual(0, record["span"]["duration_ms"])
                json.dumps(record, allow_nan=False)

    def test_correlated_stages_join_without_exporting_contents(self) -> None:
        stages = ["retrieval", "model", "critic", "tool", "consequence"]
        spans = [{"id": "request", "trace_id": "request", "ok": True}]
        spans.extend({"id": stage, "trace_id": "request", "parent_id": "request", "name": stage,
                      "ok": None if stage == "consequence" else True,
                      "attributes": {"prompt": "private input", "tool_result": "private result"}}
                     for stage in stages)
        _, records = eve_otel_genai.build_genai_export(spans)
        root = records[0]["span"]
        for child in records[1:]:
            self.assertEqual(root["trace_id"], child["span"]["trace_id"])
            self.assertEqual(root["span_id"], child["span"]["parent_span_id"])
        self.assertEqual("UNSET", records[-1]["span"]["status"]["code"])
        self.assertNotIn("private", json.dumps(records))

    def test_sqlite_reader_preserves_unknown_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "traces.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE trace_spans (id, trace_id, parent_id, name, category, started_at, ended_at, duration_ms, ok, attributes_json)")
                connection.execute("INSERT INTO trace_spans VALUES ('unknown', 'request', '', 'tool', 'tool', '', '', 0, NULL, '{}')")
            rows = eve_otel_genai.read_trace_spans_read_only(database)
        self.assertIsNone(rows[0]["ok"])
        self.assertEqual("UNSET", eve_otel_genai.span_to_genai(rows[0])["span"]["status"]["code"])

    def test_model_span_maps_only_semantic_metadata(self) -> None:
        private_prompt = "my private prompt about finances"
        private_response = "private model answer"
        record = eve_otel_genai.span_to_genai(
            {
                "id": "span-one",
                "trace_id": "trace-one",
                "name": "agent_reply_direct",
                "category": "model",
                "started_at": "2026-08-23T12:00:00+00:00",
                "ended_at": "2026-08-23T12:00:01+00:00",
                "duration_ms": 1000,
                "ok": True,
                "attributes": {
                    "model_alias": "eve-fast",
                    "model_backend": "llama.cpp",
                    "lane": "fast",
                    "prompt_tokens": 101,
                    "completion_tokens": 22,
                    "max_tokens": 220,
                    "prompt": private_prompt,
                    "response": private_response,
                },
            }
        )

        attributes = record["span"]["attributes"]
        self.assertEqual("chat", attributes["gen_ai.operation.name"])
        self.assertEqual("eve-fast", attributes["gen_ai.request.model"])
        self.assertEqual("llama.cpp", attributes["gen_ai.provider.name"])
        self.assertEqual("fast", attributes["eve.lane"])
        self.assertEqual(101, attributes["gen_ai.usage.input_tokens"])
        self.assertEqual(22, attributes["gen_ai.usage.output_tokens"])
        self.assertFalse(attributes["eve.trace.content_capture"])
        serialized = json.dumps(record)
        self.assertNotIn(private_prompt, serialized)
        self.assertNotIn(private_response, serialized)
        self.assertNotIn("gen_ai.input.messages", serialized)
        self.assertNotIn("gen_ai.output.messages", serialized)

    def test_error_exports_type_but_not_message(self) -> None:
        private_error = "failed while reading /Users/example/private/file"
        record = eve_otel_genai.span_to_genai(
            {
                "id": "span-two",
                "name": "tool action",
                "category": "tool",
                "ok": False,
                "attributes": {
                    "error": private_error,
                    "error_type": "TimeoutError",
                    "tool_arguments": {"path": "/Users/example/private/file"},
                },
            }
        )

        self.assertEqual("execute_tool", record["span"]["attributes"]["gen_ai.operation.name"])
        self.assertEqual("TimeoutError", record["span"]["attributes"]["error.type"])
        self.assertNotIn(private_error, json.dumps(record))
        self.assertNotIn("tool_arguments", json.dumps(record))

    def test_export_ids_are_stable_otel_lengths(self) -> None:
        span = {"id": "same-span", "trace_id": "same-trace", "name": "embedding", "attributes": {}}
        first = eve_otel_genai.span_to_genai(span)
        second = eve_otel_genai.span_to_genai(span)

        self.assertEqual(first["span"]["trace_id"], second["span"]["trace_id"])
        self.assertEqual(32, len(first["span"]["trace_id"]))
        self.assertEqual(16, len(first["span"]["span_id"]))
        self.assertEqual("embeddings", first["span"]["attributes"]["gen_ai.operation.name"])

    def test_build_and_atomic_jsonl_save(self) -> None:
        report, records = eve_otel_genai.build_genai_export(
            [
                {"id": "a", "name": "retrieval", "attributes": {}},
                {"id": "b", "name": "agent specialist", "attributes": {}},
            ]
        )
        self.assertEqual("ready", report["status"])
        self.assertEqual({"retrieval": 1, "invoke_agent": 1}, report["operation_counts"])
        self.assertFalse(report["content_capture"])

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "genai.jsonl"
            eve_otel_genai.save_genai_export(records, output)
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(2, len(rows))

    def test_validator_rejects_content_capture(self) -> None:
        record = eve_otel_genai.span_to_genai({"id": "x", "name": "chat", "attributes": {}})
        record["span"]["attributes"]["gen_ai.input.messages"] = [{"role": "user", "content": "secret"}]

        with self.assertRaisesRegex(ValueError, "content-bearing"):
            eve_otel_genai.validate_genai_record(record)

    def test_untrusted_label_text_and_malformed_duration_are_not_exported(self) -> None:
        private_label = "my private model prompt has several words"
        record = eve_otel_genai.span_to_genai(
            {
                "id": "x",
                "name": "chat",
                "duration_ms": "not-a-number",
                "attributes": {"model_alias": private_label},
            }
        )

        self.assertEqual("unknown_local_model", record["span"]["attributes"]["gen_ai.request.model"])
        self.assertEqual(0.0, record["span"]["duration_ms"])
        self.assertNotIn(private_label, json.dumps(record))

    def test_sqlite_trace_reader_is_read_only_and_content_is_removed_on_export(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "traces.sqlite3"
            connection = sqlite3.connect(database)
            connection.execute(
                """
                CREATE TABLE trace_spans (
                    id TEXT, trace_id TEXT, parent_id TEXT, name TEXT, category TEXT,
                    started_at TEXT, ended_at TEXT, duration_ms REAL, ok INTEGER,
                    attributes_json TEXT
                )
                """
            )
            connection.execute(
                "INSERT INTO trace_spans VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "span",
                    "trace",
                    "",
                    "reply",
                    "model",
                    "start",
                    "end",
                    1.0,
                    1,
                    json.dumps({"model_alias": "eve-fast", "prompt": "private prompt"}),
                ),
            )
            connection.commit()
            connection.close()

            spans = eve_otel_genai.read_trace_spans_read_only(database)
            report, records = eve_otel_genai.build_genai_export(spans)

        self.assertEqual(1, report["record_count"])
        self.assertNotIn("private prompt", json.dumps(records))


if __name__ == "__main__":
    unittest.main()
