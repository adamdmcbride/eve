#!/usr/bin/env python3

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from functools import wraps
from datetime import datetime, timezone, timedelta
import math
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

import eve_db


# Request/task-local correlation; not shared mutable session state. Keep source
# and runtime databases separate even when nested in the same Python task.
_span_context = ContextVar("eve_trace_span", default=None)


def _current_context(db_path):
    current = _span_context.get()
    return current if current and current[0] == str(Path(db_path).resolve()) else None


def submit(executor, function, *args, **kwargs):
    """Preserve the selecting request across an existing executor boundary."""
    if _span_context.get() is None:
        return executor.submit(function, *args, **kwargs)
    return executor.submit(copy_context().run, function, *args, **kwargs)


def traced(database, name, *, category="general", root=False, trace_id=None, attributes=None, outcome=None):
    """Instrument an existing owner without copying its arguments/results.

    Explicit process composition enables roots with EVE_REQUEST_TRACING=1.
    Child operations do nothing outside that context, including ordinary unit
    fixtures. Observability failures never replace the real operation/result.
    """
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            if root and os.environ.get("EVE_REQUEST_TRACING") != "1":
                return function(*args, **kwargs)
            try:
                path = database()
                active = root or _current_context(path) is not None
                identifier = trace_id(*args, **kwargs) if active and trace_id else None
                metadata = (attributes(*args, **kwargs) if callable(attributes) else dict(attributes or {})) if active else {}
            except Exception:
                active = False
            if not active:
                return function(*args, **kwargs)
            with span(path, name=name, category=category, attributes=metadata, trace_id_value=identifier) as status:
                result = function(*args, **kwargs)
                try:
                    status["ok"] = outcome(result) if outcome else None
                except Exception:
                    status["ok"] = None
                return result
        return wrapped
    return decorate


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_started_at(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    text = str(value or "").strip()
    if text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _duration_ms(value: object) -> float:
    try:
        duration = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(duration) or duration < 0.0:
        return 0.0
    return duration


def record_span(
    db_path: Path | str,
    *,
    name: str,
    category: str = "general",
    started_at: object = None,
    duration_ms: float = 0.0,
    ok: bool = True,
    attributes: Optional[Dict[str, Any]] = None,
    trace_id_value: Optional[str] = None,
    parent_id: Optional[str] = None,
    span_id_value: Optional[str] = None,
) -> Dict[str, Any]:
    started = _parse_started_at(started_at)
    duration = _duration_ms(duration_ms)
    try:
        ended = started + timedelta(milliseconds=duration)
    except OverflowError:
        duration = 0.0
        ended = started
    current = _current_context(db_path)
    trace_id_value = trace_id_value or (current[1] if current else str(uuid.uuid4()))
    inherited_parent = current[2] if current and current[1] == trace_id_value else ""
    span = {
        "id": span_id_value or str(uuid.uuid4()),
        "trace_id": trace_id_value,
        "parent_id": inherited_parent if parent_id is None else parent_id,
        "name": str(name or "span"),
        "category": str(category or "general"),
        "started_at": started.isoformat(timespec="seconds"),
        "ended_at": ended.isoformat(timespec="seconds"),
        "duration_ms": round(duration, 2),
        "ok": bool(ok),
        "attributes": attributes or {},
    }
    eve_db.record_trace_span(db_path, span)
    return span


@contextmanager
def span(
    db_path: Path | str,
    *,
    name: str,
    category: str = "general",
    attributes: Optional[Dict[str, Any]] = None,
    trace_id_value: Optional[str] = None,
) -> Iterator[Dict[str, Any]]:
    current = _current_context(db_path)
    trace_id = trace_id_value or (current[1] if current else str(uuid.uuid4()))
    parent_id = current[2] if current and current[1] == trace_id else ""
    span_id = str(uuid.uuid4())
    token = _span_context.set((str(Path(db_path).resolve()), trace_id, span_id))
    started_at = utc_now()
    started = time.perf_counter()
    status: Dict[str, Any] = {"ok": True, "error": ""}
    try:
        yield status
    except BaseException as exc:
        status["ok"] = False
        status["error"] = type(exc).__name__
        raise
    finally:
        attrs = dict(attributes or {})
        if status.get("error"):
            attrs["error"] = status["error"]
            attrs["error.type"] = status["error"]
        known = isinstance(status.get("ok"), bool)
        if not known:
            # SQLite's legacy ok column is non-nullable. Preserve uncertainty
            # explicitly instead of migrating it or fabricating an outcome.
            attrs["eve.outcome.known"] = False
        try:
            record_span(
                db_path,
                name=name,
                category=category,
                started_at=started_at,
                duration_ms=(time.perf_counter() - started) * 1000,
                ok=status["ok"] if known else True,
                attributes=attrs,
                trace_id_value=trace_id,
                parent_id=parent_id,
                span_id_value=span_id,
            )
        except Exception as exc:
            # Observability is evidence, not execution authority. A telemetry
            # write failure must never replace the operation's real result or
            # mask its original exception.
            status["trace_error"] = str(exc)
        finally:
            _span_context.reset(token)


def _prometheus_sample(line: str) -> Optional[tuple[str, str]]:
    """Split one sample without breaking on whitespace inside label strings."""

    brace_depth = 0
    in_quotes = False
    escaped = False
    for index, character in enumerate(line):
        if escaped:
            escaped = False
            continue
        if in_quotes and character == "\\":
            escaped = True
            continue
        if character == '"':
            in_quotes = not in_quotes
            continue
        if in_quotes:
            continue
        if character == "{":
            brace_depth += 1
            continue
        if character == "}" and brace_depth > 0:
            brace_depth -= 1
            continue
        if character.isspace() and brace_depth == 0:
            metric_token = line[:index].strip()
            remainder = line[index:].strip()
            if not metric_token or not remainder:
                return None
            value_token = remainder.split(maxsplit=1)[0]
            return metric_token, value_token
    return None


def parse_prometheus_metrics(text: str, limit: int = 80) -> Dict[str, float]:
    if limit <= 0:
        return {}
    metrics: Dict[str, float] = {}
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        sample = _prometheus_sample(line)
        if sample is None:
            continue
        metric_token, value_token = sample
        try:
            value = float(value_token)
        except ValueError:
            continue
        if math.isnan(value) or math.isinf(value):
            continue
        key = metric_token[:220]
        metrics[key] = value
        if len(metrics) >= limit:
            break
    return metrics


def metrics_excerpt(text: str, limit: int = 6000) -> str:
    if limit <= 0:
        return ""
    cleaned_lines = []
    total_chars = 0
    for raw_line in str(text or "").splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        total_chars += len(line) + (1 if cleaned_lines else 0)
        cleaned_lines.append(line)
        if total_chars >= limit:
            break
    return "\n".join(cleaned_lines)[:limit]
