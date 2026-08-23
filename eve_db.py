#!/usr/bin/env python3

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

try:  # pragma: no cover - macOS/Linux only lock detail
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


MIN_SAFE_WAL_SQLITE_VERSION = (3, 51, 3)
_INITIALIZED_PATHS: set[str] = set()
_INITIALIZE_LOCK = threading.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sqlite_version_info() -> Tuple[int, int, int]:
    parts = str(sqlite3.sqlite_version).split(".")
    parsed = [int(part) for part in parts[:3] if part.isdigit()]
    while len(parsed) < 3:
        parsed.append(0)
    return parsed[0], parsed[1], parsed[2]


def sqlite_wal_warning() -> str:
    version = sqlite_version_info()
    if version < MIN_SAFE_WAL_SQLITE_VERSION:
        return (
            f"Python sqlite3 is {sqlite3.sqlite_version}; keep Eve's SQLite writes behind "
            "the single-writer guard until the runtime is on SQLite 3.51.3+."
        )
    return ""


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=True, sort_keys=True)


def _json_loads_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value in (None, ""):
        return {}
    try:
        parsed = json.loads(value if isinstance(value, str) else str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _text_value(value: Any, fallback: str = "") -> str:
    if isinstance(value, str):
        return value.strip() or fallback
    text = str(value if value is not None else "").strip()
    return text or fallback


def _db_path(path: Path | str) -> Path:
    return Path(path).expanduser().resolve()


def _lock_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".lock")


@contextmanager
def single_writer_lock(path: Path | str, timeout_seconds: float = 10.0) -> Iterator[None]:
    db_path = _db_path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _lock_path(db_path)
    started = time.monotonic()
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        if fcntl is None:
            yield
            return
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() - started >= timeout_seconds:
                    holder_info = "unknown"
                    try:
                        lock_file.seek(0)
                        holder_info = lock_file.read().strip() or "unknown"
                    except Exception:
                        pass
                    raise TimeoutError(
                        f"Timed out waiting for Eve DB writer lock: {lock_path} (current holder: {holder_info})"
                    )
                time.sleep(0.05)
        try:
            try:
                lock_file.seek(0)
                lock_file.truncate()
                lock_file.write(f"pid={os.getpid()} thread={threading.get_ident()} acquired_at={utc_now()}")
                lock_file.flush()
            except Exception:
                pass
            yield
        finally:
            try:
                lock_file.seek(0)
                lock_file.truncate()
                lock_file.flush()
            except Exception:
                pass
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def connect_database(path: Path | str, *, read_only: bool = False) -> sqlite3.Connection:
    db_path = _db_path(path)
    if read_only:
        conn = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True, timeout=10.0)
    else:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA foreign_keys = ON")
    if read_only:
        conn.execute("PRAGMA query_only = ON")
    return conn


def initialize_database(path: Path | str) -> None:
    db_path = _db_path(path)
    key = str(db_path)
    with _INITIALIZE_LOCK:
        if key in _INITIALIZED_PATHS and db_path.exists():
            return
        with single_writer_lock(db_path):
            with connect_database(db_path) as conn:
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("PRAGMA synchronous = NORMAL")
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS events (
                        id TEXT PRIMARY KEY,
                        created_at TEXT NOT NULL,
                        source TEXT NOT NULL,
                        actor TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        stream TEXT NOT NULL,
                        subject TEXT NOT NULL,
                        correlation_id TEXT NOT NULL,
                        causation_id TEXT NOT NULL,
                        schema_version INTEGER NOT NULL DEFAULT 1,
                        payload_json TEXT NOT NULL,
                        metadata_json TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_events_stream_created
                        ON events(stream, created_at);
                    CREATE INDEX IF NOT EXISTS idx_events_kind_created
                        ON events(kind, created_at);
                    CREATE INDEX IF NOT EXISTS idx_events_correlation
                        ON events(correlation_id);

                    CREATE TABLE IF NOT EXISTS infrastructure_events (
                        id TEXT PRIMARY KEY,
                        created_at TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        name TEXT NOT NULL,
                        ok INTEGER NOT NULL DEFAULT 1,
                        payload_json TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_infrastructure_events_kind_created
                        ON infrastructure_events(kind, created_at);

                    CREATE TABLE IF NOT EXISTS perf_events (
                        id TEXT PRIMARY KEY,
                        created_at TEXT NOT NULL,
                        category TEXT NOT NULL,
                        name TEXT NOT NULL,
                        duration_ms REAL NOT NULL,
                        ok INTEGER NOT NULL DEFAULT 1,
                        metadata_json TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_perf_events_category_name_created
                        ON perf_events(category, name, created_at);

                    CREATE TABLE IF NOT EXISTS trace_spans (
                        id TEXT PRIMARY KEY,
                        trace_id TEXT NOT NULL,
                        parent_id TEXT,
                        name TEXT NOT NULL,
                        category TEXT NOT NULL,
                        started_at TEXT NOT NULL,
                        ended_at TEXT NOT NULL,
                        duration_ms REAL NOT NULL,
                        ok INTEGER NOT NULL DEFAULT 1,
                        attributes_json TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_trace_spans_trace_started
                        ON trace_spans(trace_id, started_at);
                    CREATE INDEX IF NOT EXISTS idx_trace_spans_category_started
                        ON trace_spans(category, started_at);

                    CREATE TABLE IF NOT EXISTS llama_cpp_metrics (
                        id TEXT PRIMARY KEY,
                        captured_at TEXT NOT NULL,
                        profile TEXT NOT NULL,
                        host TEXT NOT NULL,
                        ok INTEGER NOT NULL DEFAULT 1,
                        metrics_json TEXT NOT NULL,
                        raw_excerpt TEXT NOT NULL,
                        error TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_llama_cpp_metrics_profile_captured
                        ON llama_cpp_metrics(profile, captured_at);

                    CREATE TABLE IF NOT EXISTS model_governor_decisions (
                        id TEXT PRIMARY KEY,
                        created_at TEXT NOT NULL,
                        model TEXT NOT NULL,
                        operation TEXT NOT NULL,
                        host TEXT NOT NULL,
                        action TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        payload_json TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_model_governor_model_created
                        ON model_governor_decisions(model, created_at);
                    """
                )
                conn.commit()
        _INITIALIZED_PATHS.add(key)


def execute_write(path: Path | str, sql: str, params: Iterable[Any]) -> None:
    db_path = _db_path(path)
    initialize_database(db_path)
    with single_writer_lock(db_path):
        with connect_database(db_path) as conn:
            conn.execute(sql, tuple(params))
            conn.commit()


def normalize_event_record(event: Dict[str, Any]) -> Dict[str, Any]:
    event_id = _text_value(event.get("id"), str(uuid.uuid4()))
    payload = event.get("payload")
    metadata = event.get("metadata")
    if payload is None:
        payload = _json_loads_dict(event.get("payload_json"))
    if metadata is None:
        metadata = _json_loads_dict(event.get("metadata_json"))
    payload_dict = payload if isinstance(payload, dict) else {}
    metadata_dict = metadata if isinstance(metadata, dict) else {}
    return {
        "id": event_id,
        "created_at": _text_value(event.get("created_at") or event.get("timestamp"), utc_now()),
        "source": _text_value(event.get("source"), "eve"),
        "actor": _text_value(event.get("actor"), "eve"),
        "kind": _text_value(event.get("kind"), "event"),
        "stream": _text_value(event.get("stream"), "system"),
        "subject": _text_value(event.get("subject"), ""),
        "correlation_id": _text_value(event.get("correlation_id"), event_id),
        "causation_id": _text_value(event.get("causation_id"), ""),
        "schema_version": int(event.get("schema_version") or 1),
        "payload": payload_dict,
        "metadata": metadata_dict,
    }


def record_event(
    path: Path | str,
    *,
    kind: str,
    source: str = "eve",
    actor: str = "eve",
    stream: str = "system",
    subject: str = "",
    correlation_id: str = "",
    causation_id: str = "",
    payload: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    schema_version: int = 1,
) -> Dict[str, Any]:
    record = normalize_event_record(
        {
            "id": str(uuid.uuid4()),
            "created_at": utc_now(),
            "source": source,
            "actor": actor,
            "kind": kind,
            "stream": stream,
            "subject": subject,
            "correlation_id": correlation_id,
            "causation_id": causation_id,
            "schema_version": schema_version,
            "payload": payload or {},
            "metadata": metadata or {},
        }
    )
    execute_write(
        path,
        """
        INSERT OR REPLACE INTO events
            (id, created_at, source, actor, kind, stream, subject, correlation_id,
             causation_id, schema_version, payload_json, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["id"],
            record["created_at"],
            record["source"],
            record["actor"],
            record["kind"],
            record["stream"],
            record["subject"],
            record["correlation_id"],
            record["causation_id"],
            record["schema_version"],
            _json_dumps(record["payload"]),
            _json_dumps(record["metadata"]),
        ),
    )
    return record


def read_events(
    path: Path | str,
    *,
    limit: int = 50,
    stream: str = "",
    kind: str = "",
    correlation_id: str = "",
) -> List[Dict[str, Any]]:
    db_path = _db_path(path)
    initialize_database(db_path)
    clauses: List[str] = []
    params: List[Any] = []
    if stream:
        clauses.append("stream = ?")
        params.append(stream)
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if correlation_id:
        clauses.append("correlation_id = ?")
        params.append(correlation_id)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, int(limit or 50)))
    with connect_database(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT id, created_at, source, actor, kind, stream, subject,
                   correlation_id, causation_id, schema_version, payload_json, metadata_json
            FROM events
            {where_sql}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
    return [
        normalize_event_record(
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "source": row["source"],
                "actor": row["actor"],
                "kind": row["kind"],
                "stream": row["stream"],
                "subject": row["subject"],
                "correlation_id": row["correlation_id"],
                "causation_id": row["causation_id"],
                "schema_version": row["schema_version"],
                "payload_json": row["payload_json"],
                "metadata_json": row["metadata_json"],
            }
        )
        for row in rows
    ]


def event_contract() -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "table": "events",
        "purpose": "Canonical typed event spine for Eve's Python mind and future Go/Swift/TypeScript runtimes.",
        "required_fields": [
            "id",
            "created_at",
            "source",
            "actor",
            "kind",
            "stream",
            "subject",
            "correlation_id",
            "causation_id",
            "schema_version",
            "payload",
            "metadata",
        ],
        "recommended_streams": [
            "chat",
            "autonomy",
            "capability",
            "memory",
            "model",
            "workspace",
            "tool",
            "action",
            "system",
            "ui",
        ],
    }


def record_infrastructure_event(
    path: Path | str,
    *,
    kind: str,
    name: str,
    ok: bool = True,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    record = {
        "id": str(uuid.uuid4()),
        "created_at": utc_now(),
        "kind": str(kind or "infrastructure"),
        "name": str(name or "event"),
        "ok": bool(ok),
        "payload": payload or {},
    }
    execute_write(
        path,
        """
        INSERT OR REPLACE INTO infrastructure_events
            (id, created_at, kind, name, ok, payload_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            record["id"],
            record["created_at"],
            record["kind"],
            record["name"],
            1 if record["ok"] else 0,
            _json_dumps(record["payload"]),
        ),
    )
    return record


def record_perf_event(path: Path | str, event: Dict[str, Any]) -> None:
    execute_write(
        path,
        """
        INSERT OR REPLACE INTO perf_events
            (id, created_at, category, name, duration_ms, ok, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(event.get("id") or uuid.uuid4()),
            str(event.get("timestamp") or event.get("created_at") or utc_now()),
            str(event.get("category") or "unknown"),
            str(event.get("name") or "unknown"),
            float(event.get("duration_ms") or 0.0),
            1 if bool(event.get("ok", True)) else 0,
            _json_dumps(event.get("metadata") if isinstance(event.get("metadata"), dict) else {}),
        ),
    )


def record_trace_span(path: Path | str, span: Dict[str, Any]) -> None:
    execute_write(
        path,
        """
        INSERT OR REPLACE INTO trace_spans
            (id, trace_id, parent_id, name, category, started_at, ended_at, duration_ms, ok, attributes_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(span.get("id") or uuid.uuid4()),
            str(span.get("trace_id") or uuid.uuid4()),
            str(span.get("parent_id") or ""),
            str(span.get("name") or "span"),
            str(span.get("category") or "general"),
            str(span.get("started_at") or utc_now()),
            str(span.get("ended_at") or utc_now()),
            float(span.get("duration_ms") or 0.0),
            1 if bool(span.get("ok", True)) else 0,
            _json_dumps(span.get("attributes") if isinstance(span.get("attributes"), dict) else {}),
        ),
    )


def read_trace_spans(
    path: Path | str,
    *,
    limit: int = 200,
    trace_id: str = "",
    category: str = "",
) -> List[Dict[str, Any]]:
    db_path = _db_path(path)
    initialize_database(db_path)
    clauses: List[str] = []
    params: List[Any] = []
    if trace_id:
        clauses.append("trace_id = ?")
        params.append(str(trace_id))
    if category:
        clauses.append("category = ?")
        params.append(str(category))
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, int(limit or 200)))
    with connect_database(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT id, trace_id, parent_id, name, category, started_at, ended_at,
                   duration_ms, ok, attributes_json
            FROM trace_spans
            {where_sql}
            ORDER BY started_at DESC, id DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "trace_id": row["trace_id"],
            "parent_id": row["parent_id"] or "",
            "name": row["name"],
            "category": row["category"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "duration_ms": float(row["duration_ms"] or 0.0),
            "ok": bool(row["ok"]),
            "attributes": _json_loads_dict(row["attributes_json"]),
        }
        for row in rows
    ]


def record_llama_cpp_metrics(
    path: Path | str,
    *,
    profile: str,
    host: str,
    ok: bool,
    metrics: Optional[Dict[str, Any]] = None,
    raw_excerpt: str = "",
    error: str = "",
) -> Dict[str, Any]:
    record = {
        "id": str(uuid.uuid4()),
        "captured_at": utc_now(),
        "profile": str(profile or "unknown"),
        "host": str(host or ""),
        "ok": bool(ok),
        "metrics": metrics or {},
        "raw_excerpt": raw_excerpt[:6000],
        "error": error[:1000],
    }
    execute_write(
        path,
        """
        INSERT OR REPLACE INTO llama_cpp_metrics
            (id, captured_at, profile, host, ok, metrics_json, raw_excerpt, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["id"],
            record["captured_at"],
            record["profile"],
            record["host"],
            1 if record["ok"] else 0,
            _json_dumps(record["metrics"]),
            record["raw_excerpt"],
            record["error"],
        ),
    )
    return record


def record_model_governor_decision(path: Path | str, decision: Dict[str, Any]) -> None:
    execute_write(
        path,
        """
        INSERT OR REPLACE INTO model_governor_decisions
            (id, created_at, model, operation, host, action, reason, payload_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(decision.get("id") or uuid.uuid4()),
            str(decision.get("created_at") or utc_now()),
            str(decision.get("model") or ""),
            str(decision.get("operation") or ""),
            str(decision.get("host") or ""),
            str(decision.get("action") or "allow"),
            str(decision.get("reason") or ""),
            _json_dumps(decision),
        ),
    )


def _table_count(conn: sqlite3.Connection, table: str) -> int:
    try:
        row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
        return int(row["count"] if row else 0)
    except sqlite3.Error:
        return 0


def database_status(path: Path | str) -> Dict[str, Any]:
    db_path = _db_path(path)
    exists = db_path.exists()
    status: Dict[str, Any] = {
        "path": str(db_path),
        "exists": exists,
        "sqlite_version": sqlite3.sqlite_version,
        "sqlite_version_info": list(sqlite_version_info()),
        "wal_warning": sqlite_wal_warning(),
        "single_writer_guard": "fcntl_file_lock" if fcntl is not None else "best_effort_process_lock",
        "single_writer_guard_enabled": fcntl is not None,
        "readable": False,
        "read_only_probe": True,
        "journal_mode": "unknown",
        "tables": {},
        "error": "",
    }
    if not exists:
        return status
    try:
        with connect_database(db_path, read_only=True) as conn:
            row = conn.execute("PRAGMA journal_mode").fetchone()
            status["journal_mode"] = str(row[0] if row else "unknown")
            for table in [
                "events",
                "infrastructure_events",
                "perf_events",
                "trace_spans",
                "llama_cpp_metrics",
                "model_governor_decisions",
            ]:
                status["tables"][table] = _table_count(conn, table)
            status["readable"] = True
    except (OSError, sqlite3.Error) as exc:
        status["error"] = f"{exc.__class__.__name__}: {exc}"
    return status
