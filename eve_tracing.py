#!/usr/bin/env python3

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import math
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

import eve_db


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_started_at(value: object) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    text = str(value or "").strip()
    if text:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


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
) -> Dict[str, Any]:
    started = _parse_started_at(started_at)
    duration = max(0.0, float(duration_ms or 0.0))
    ended = started + timedelta(milliseconds=duration)
    span = {
        "id": str(uuid.uuid4()),
        "trace_id": trace_id_value or str(uuid.uuid4()),
        "parent_id": parent_id or "",
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
) -> Iterator[Dict[str, Any]]:
    started_at = utc_now()
    started = time.perf_counter()
    status: Dict[str, Any] = {"ok": True, "error": ""}
    try:
        yield status
    except Exception as exc:
        status["ok"] = False
        status["error"] = str(exc)
        raise
    finally:
        attrs = dict(attributes or {})
        if status.get("error"):
            attrs["error"] = status["error"]
        record_span(
            db_path,
            name=name,
            category=category,
            started_at=started_at,
            duration_ms=(time.perf_counter() - started) * 1000,
            ok=bool(status.get("ok", True)),
            attributes=attrs,
        )


def parse_prometheus_metrics(text: str, limit: int = 80) -> Dict[str, float]:
    metrics: Dict[str, float] = {}
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        metric_token = parts[0]
        value_token = parts[-1]
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
    cleaned_lines = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        cleaned_lines.append(line)
        if sum(len(item) + 1 for item in cleaned_lines) >= limit:
            break
    return "\n".join(cleaned_lines)[:limit]
