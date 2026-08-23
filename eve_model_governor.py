#!/usr/bin/env python3

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Iterable, List
import uuid


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_iso_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def boolish(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def operation_family(operation: object) -> str:
    normalized = " ".join(str(operation or "general").lower().split()) or "general"
    if normalized.startswith("reply_stream_"):
        return "reply_stream"
    if normalized.startswith("mind_stream_"):
        return "mind_stream"
    if normalized.startswith("self_awareness"):
        return "self_awareness"
    if normalized.startswith("model_exercise_"):
        return "model_exercise"
    if normalized.startswith("model_bakeoff_"):
        return "model_bakeoff"
    return normalized


def _same_model_or_host(event: Dict[str, Any], model: str, host: str) -> bool:
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    event_model = str(metadata.get("model") or "").strip()
    event_host = str(metadata.get("host") or "").rstrip("/")
    if model and event_model and event_model == model:
        return True
    if host and event_host and event_host == host.rstrip("/"):
        return True
    return False


def _context_overflow_failure(event: Dict[str, Any]) -> bool:
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    error_text = str(metadata.get("error") or event.get("error") or "").lower()
    return (
        "exceed_context_size_error" in error_text
        or "exceeds the available context size" in error_text
        or "n_prompt_tokens" in error_text and "n_ctx" in error_text
    )


def relevant_failures(
    events: Iterable[Dict[str, Any]],
    *,
    model: str,
    operation: str,
    host: str,
    window_minutes: int,
) -> List[Dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(1, int(window_minutes or 1)))
    family = operation_family(operation)
    failures: List[Dict[str, Any]] = []
    for event in events:
        if bool(event.get("ok", True)):
            continue
        if str(event.get("category") or "") != "model_call":
            continue
        event_time = parse_iso_datetime(event.get("timestamp") or event.get("created_at"))
        if event_time and event_time < cutoff:
            continue
        event_family = operation_family(event.get("name"))
        if event_family != family and not _same_model_or_host(event, model, host):
            continue
        failures.append(event)
    return failures


def decide(
    config: Dict[str, Any],
    recent_events: Iterable[Dict[str, Any]],
    *,
    model: str,
    operation: str,
    host: str,
) -> Dict[str, Any]:
    enabled = boolish(config.get("model_governor_enabled"), default=True)
    enforce = boolish(config.get("model_governor_enforce"), default=False)
    enforce_context_overflow = boolish(config.get("model_governor_context_overflow_enforce"), default=True)
    threshold = int(config.get("model_governor_failure_threshold") or 2)
    window_minutes = int(config.get("model_governor_failure_window_minutes") or 20)
    decision = {
        "id": str(uuid.uuid4()),
        "created_at": utc_now(),
        "model": model,
        "operation": operation,
        "operation_family": operation_family(operation),
        "host": host,
        "action": "allow",
        "reason": "governor disabled" if not enabled else "within failure budget",
        "enabled": enabled,
        "enforce": enforce,
        "context_overflow_enforce": enforce_context_overflow,
        "failure_threshold": threshold,
        "failure_window_minutes": window_minutes,
        "failure_count": 0,
        "context_overflow_failure_count": 0,
    }
    if not enabled:
        return decision
    failures = relevant_failures(
        recent_events,
        model=model,
        operation=operation,
        host=host,
        window_minutes=window_minutes,
    )
    decision["failure_count"] = len(failures)
    overflow_count = sum(1 for event in failures if _context_overflow_failure(event))
    decision["context_overflow_failure_count"] = overflow_count
    if overflow_count >= threshold and enforce_context_overflow:
        decision["action"] = "skip"
        decision["reason"] = (
            f"{overflow_count} recent context-window failure(s) in {window_minutes}m for "
            f"{decision['operation_family']} or the same lane"
        )
        return decision
    if len(failures) >= threshold:
        decision["action"] = "skip" if enforce else "warn"
        decision["reason"] = (
            f"{len(failures)} recent model-call failure(s) in {window_minutes}m for "
            f"{decision['operation_family']} or the same lane"
        )
    return decision


def summarize(recent_events: Iterable[Dict[str, Any]], config: Dict[str, Any]) -> Dict[str, Any]:
    window_minutes = int(config.get("model_governor_failure_window_minutes") or 20)
    failures = [
        event for event in recent_events
        if str(event.get("category") or "") == "model_call" and not bool(event.get("ok", True))
    ]
    by_family: Dict[str, int] = {}
    for event in failures:
        family = operation_family(event.get("name"))
        by_family[family] = by_family.get(family, 0) + 1
    return {
        "enabled": boolish(config.get("model_governor_enabled"), default=True),
        "enforce": boolish(config.get("model_governor_enforce"), default=False),
        "context_overflow_enforce": boolish(config.get("model_governor_context_overflow_enforce"), default=True),
        "window_minutes": window_minutes,
        "failure_threshold": int(config.get("model_governor_failure_threshold") or 2),
        "failure_count": len(failures),
        "failures_by_family": by_family,
    }
