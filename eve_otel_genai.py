#!/usr/bin/env python3
"""Privacy-minimized OpenTelemetry GenAI semantic export for Eve traces.

The canonical trace store remains Eve's SQLite store. This module produces a
transport-neutral JSONL projection that follows the current GenAI attribute
names without copying prompts, responses, tool arguments, retrieval text, or
error messages. Export is observability only; it grants no model, tool, memory,
task, routing, or governance authority.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_ID = "eve_otel_genai_span.v1"
# The dedicated upstream repository had not yet published a schema URL when
# this adapter was written, so provenance is explicit and schema_url omitted.
SEMCONV_SOURCE = "https://github.com/open-telemetry/semantic-conventions-genai"
SEMCONV_REVIEWED_AT = "2026-08-23"
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE_DB = PROJECT_ROOT / ".eve" / "operational_state.sqlite3"
DEFAULT_RUNTIME_DB = Path.home() / ".eve_runtime" / ".eve" / "operational_state.sqlite3"
DEFAULT_OUTPUT = PROJECT_ROOT / ".eve" / "capability_canaries" / "otel_genai.jsonl"
DEFAULT_REPORT = PROJECT_ROOT / ".eve" / "capability_canaries" / "otel_genai_report.json"

WELL_KNOWN_OPERATIONS = {
    "chat",
    "create_agent",
    "embeddings",
    "execute_tool",
    "generate_content",
    "invoke_agent",
    "invoke_workflow",
    "retrieval",
    "text_completion",
}
EVE_LANES = {"fast", "observer", "planner", "deep", "relationship"}
FORBIDDEN_CONTENT_KEYS = {
    "arguments",
    "completion",
    "content",
    "error.message",
    "gen_ai.input.messages",
    "gen_ai.output.messages",
    "gen_ai.retrieval.documents",
    "gen_ai.retrieval.query.text",
    "gen_ai.system_instructions",
    "gen_ai.tool.call.arguments",
    "gen_ai.tool.call.result",
    "input",
    "messages",
    "output",
    "prompt",
    "query",
    "response",
    "result",
    "system_prompt",
    "tool_arguments",
    "tool_result",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stable_hex(value: object, length: int) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:length]


def _safe_label(value: object, *, fallback: str = "unknown", limit: int = 120) -> str:
    raw = str(value or "").strip()
    lowered = raw.lower()
    if (
        not raw
        or len(raw) > limit
        or any(character.isspace() for character in raw)
        or "/users/" in lowered
        or "authorization:" in lowered
        or "?" in raw
        or "#" in raw
        or re.search(r"(?:^|[^a-z])sk-(?:proj-)?[a-z0-9]", lowered)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/+-]*", raw)
    ):
        return fallback
    return raw


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


def _nonnegative_float(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return parsed if math.isfinite(parsed) and parsed >= 0.0 else 0.0


def _operation_for(span: Mapping[str, Any], attributes: Mapping[str, Any]) -> str:
    explicit = str(attributes.get("gen_ai.operation.name") or attributes.get("operation") or "").strip()
    if explicit in WELL_KNOWN_OPERATIONS:
        return explicit

    haystack = " ".join(
        [
            str(span.get("name") or ""),
            str(span.get("category") or ""),
            str(attributes.get("kind") or ""),
        ]
    ).lower()
    if "embedding" in haystack:
        return "embeddings"
    if "retriev" in haystack or "memory_search" in haystack:
        return "retrieval"
    if "tool" in haystack or "action" in haystack:
        return "execute_tool"
    if "workflow" in haystack or "council" in haystack:
        return "invoke_workflow"
    if "reply" in haystack or "chat" in haystack or "model" in haystack or "llm" in haystack:
        return "chat"
    if "agent" in haystack or "specialist" in haystack:
        return "invoke_agent"
    if "multimodal" in haystack or "image" in haystack or "speech" in haystack:
        return "generate_content"
    return "chat"


def _attribute_value(attributes: Mapping[str, Any], *names: str) -> object:
    for name in names:
        if name in attributes:
            return attributes[name]
    return None


def span_to_genai(span: Mapping[str, Any], *, exported_at: str | None = None) -> dict[str, Any]:
    """Convert one Eve span to a content-free GenAI semantic record."""

    source_attributes = span.get("attributes") if isinstance(span.get("attributes"), Mapping) else {}
    attributes: Mapping[str, Any] = source_attributes  # type: ignore[assignment]
    operation = _operation_for(span, attributes)
    model = _safe_label(
        _attribute_value(
            attributes,
            "gen_ai.response.model",
            "gen_ai.request.model",
            "model_alias",
            "model",
            "llama_cpp_model_alias",
        ),
        fallback="unknown_local_model",
    )
    provider = _safe_label(
        _attribute_value(attributes, "gen_ai.provider.name", "provider", "model_backend"),
        fallback="eve.local",
    )

    semantic_attributes: dict[str, Any] = {
        "gen_ai.operation.name": operation,
        "gen_ai.provider.name": provider,
        "gen_ai.request.model": model,
        "gen_ai.response.model": model,
        "eve.trace.content_capture": False,
    }

    for source_name, semantic_name in (
        (("input_tokens", "prompt_tokens", "gen_ai.usage.input_tokens"), "gen_ai.usage.input_tokens"),
        (("output_tokens", "completion_tokens", "gen_ai.usage.output_tokens"), "gen_ai.usage.output_tokens"),
        (("reasoning_tokens", "gen_ai.usage.reasoning.output_tokens"), "gen_ai.usage.reasoning.output_tokens"),
        (("max_tokens", "gen_ai.request.max_tokens"), "gen_ai.request.max_tokens"),
    ):
        value = _nonnegative_int(_attribute_value(attributes, *source_name))
        if value is not None:
            semantic_attributes[semantic_name] = value

    lane = str(_attribute_value(attributes, "eve.lane", "lane", "model_lane") or "").strip().lower()
    if lane in EVE_LANES:
        semantic_attributes["eve.lane"] = lane
    substrate = _attribute_value(attributes, "eve.substrate", "substrate", "resident_substrate")
    if substrate:
        semantic_attributes["eve.substrate"] = _safe_label(substrate)
    specialist_role = _attribute_value(attributes, "eve.specialist.role", "specialist_role")
    if specialist_role:
        semantic_attributes["eve.specialist.role"] = _safe_label(specialist_role)
    output_type = str(_attribute_value(attributes, "gen_ai.output.type", "output_type") or "").strip()
    if output_type in {"image", "json", "speech", "text"}:
        semantic_attributes["gen_ai.output.type"] = output_type

    # Missing/null/malformed evidence is unknown, not an implicit success or
    # error. SQLite stores the same typed booleans as integer 0/1.
    ok = span.get("ok")
    status = "UNSET"
    if ok is True or (type(ok) is int and ok == 1):
        status = "OK"
    elif ok is False or (type(ok) is int and ok == 0):
        status = "ERROR"
    if attributes.get("eve.outcome.known") is False:
        status = "UNSET"
        semantic_attributes["eve.outcome.known"] = False
    if isinstance(attributes.get("eve.synthetic"), bool):
        semantic_attributes["eve.synthetic"] = attributes["eve.synthetic"]
    error_type = _attribute_value(attributes, "error.type", "error_type", "exception_type")
    if status == "ERROR":
        semantic_attributes["error.type"] = _safe_label(error_type, fallback="EveOperationError")

    trace_source = span.get("trace_id") or span.get("id") or json.dumps(dict(span), sort_keys=True, default=str)
    span_source = span.get("id") or f"{trace_source}:{span.get('name')}:{span.get('started_at')}"
    parent_source = span.get("parent_id")
    record = {
        "schema_version": SCHEMA_ID,
        "semantic_conventions": {
            "source": SEMCONV_SOURCE,
            "reviewed_at": SEMCONV_REVIEWED_AT,
            "schema_url": None,
        },
        "exported_at": exported_at or _utc_now(),
        "resource": {
            "service.name": "eve",
            "service.namespace": "local.eve",
        },
        "span": {
            "trace_id": _stable_hex(trace_source, 32),
            "span_id": _stable_hex(span_source, 16),
            "parent_span_id": _stable_hex(parent_source, 16) if parent_source else "",
            "name": f"{operation} {model}",
            "kind": "CLIENT" if operation in {"chat", "embeddings", "generate_content", "retrieval", "text_completion"} else "INTERNAL",
            "start_time": str(span.get("started_at") or ""),
            "end_time": str(span.get("ended_at") or ""),
            "duration_ms": _nonnegative_float(span.get("duration_ms")),
            "status": {"code": status},
            "attributes": semantic_attributes,
            "events": [],
        },
    }
    validate_genai_record(record)
    return record


def validate_genai_record(record: Mapping[str, Any]) -> None:
    """Reject accidental content capture or malformed semantic projections."""

    if record.get("schema_version") != SCHEMA_ID:
        raise ValueError("unexpected GenAI export schema")
    span = record.get("span")
    if not isinstance(span, Mapping):
        raise ValueError("missing span")
    attributes = span.get("attributes")
    if not isinstance(attributes, Mapping):
        raise ValueError("missing span attributes")
    if attributes.get("eve.trace.content_capture") is not False:
        raise ValueError("content capture must remain disabled")
    operation = attributes.get("gen_ai.operation.name")
    if operation not in WELL_KNOWN_OPERATIONS:
        raise ValueError("unsupported GenAI operation")
    lowered_keys = {str(key).lower() for key in attributes}
    if lowered_keys & FORBIDDEN_CONTENT_KEYS:
        raise ValueError("content-bearing GenAI attributes are forbidden")
    serialized = json.dumps(record, ensure_ascii=True, sort_keys=True).lower()
    for marker in ("-----begin private key-----", "authorization: bearer", "sk-proj-"):
        if marker in serialized:
            raise ValueError("secret-like content in GenAI export")


def build_genai_export(spans: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    exported_at = _utc_now()
    records = [span_to_genai(span, exported_at=exported_at) for span in spans]
    operation_counts: dict[str, int] = {}
    for record in records:
        operation = str(record["span"]["attributes"]["gen_ai.operation.name"])
        operation_counts[operation] = operation_counts.get(operation, 0) + 1
    report = {
        "schema_version": "eve_otel_genai_export.v1",
        "generated_at": exported_at,
        "status": "ready" if records else "empty",
        "record_count": len(records),
        "operation_counts": operation_counts,
        "content_capture": False,
        "semantic_conventions_source": SEMCONV_SOURCE,
        "semantic_conventions_reviewed_at": SEMCONV_REVIEWED_AT,
    }
    return report, records


def save_genai_export(records: Sequence[Mapping[str, Any]], output_path: Path | str) -> Path:
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    for record in records:
        validate_genai_record(record)
    payload = "".join(json.dumps(dict(record), ensure_ascii=True, sort_keys=True) + "\n" for record in records)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)
    return path


def read_trace_spans_read_only(path: Path | str, *, limit: int = 200) -> list[dict[str, Any]]:
    database = Path(path).expanduser().resolve()
    if not database.is_file():
        return []
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT id, trace_id, parent_id, name, category, started_at, ended_at,
                   duration_ms, ok, attributes_json
            FROM trace_spans
            ORDER BY started_at DESC, id DESC
            LIMIT ?
            """,
            (max(1, min(int(limit or 200), 5_000)),),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        connection.close()
    spans: list[dict[str, Any]] = []
    for row in rows:
        try:
            attributes = json.loads(row["attributes_json"] or "{}")
        except json.JSONDecodeError:
            attributes = {}
        spans.append(
            {
                "id": row["id"],
                "trace_id": row["trace_id"],
                "parent_id": row["parent_id"] or "",
                "name": row["name"],
                "category": row["category"],
                "started_at": row["started_at"],
                "ended_at": row["ended_at"],
                "duration_ms": row["duration_ms"],
                "ok": row["ok"],
                "attributes": attributes if isinstance(attributes, dict) else {},
            }
        )
    return spans


def save_report(report: Mapping[str, Any], output_path: Path | str) -> Path:
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(dict(report), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export content-free OTel GenAI metadata from Eve traces.")
    parser.add_argument("--db", help="Source SQLite path; opened read-only.")
    parser.add_argument("--limit", type=int, default=200, help="Maximum recent spans (1-5000).")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Content-free JSONL output.")
    parser.add_argument("--report", default=str(DEFAULT_REPORT), help="Summary JSON output.")
    parser.add_argument("--no-write", action="store_true", help="Do not persist outputs.")
    parser.add_argument("--json", action="store_true", help="Print the summary report.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database = Path(args.db).expanduser() if args.db else (
        DEFAULT_RUNTIME_DB if DEFAULT_RUNTIME_DB.is_file() else DEFAULT_SOURCE_DB
    )
    spans = read_trace_spans_read_only(database, limit=args.limit)
    report, records = build_genai_export(spans)
    report.update(
        {
            "source": "runtime_trace_store" if database == DEFAULT_RUNTIME_DB else "local_trace_store",
            "source_path_persisted": False,
            "source_open_mode": "read_only",
            "canonical_store_changed": False,
            "remote_collector_contacted": False,
        }
    )
    if not args.no_write:
        save_genai_export(records, Path(args.output))
        save_report(report, Path(args.report))
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True))
    else:
        print(
            f"OTel GenAI export: status={report['status']} "
            f"spans={report['record_count']} content_capture=false"
        )
    return 0


__all__ = [
    "FORBIDDEN_CONTENT_KEYS",
    "SCHEMA_ID",
    "SEMCONV_SOURCE",
    "build_genai_export",
    "save_genai_export",
    "read_trace_spans_read_only",
    "save_report",
    "span_to_genai",
    "validate_genai_record",
]


if __name__ == "__main__":
    raise SystemExit(main())
