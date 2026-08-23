#!/usr/bin/env python3

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import uuid

import eve_store


EVENT_TYPES = {
    "percept",
    "user_signal",
    "self_state",
    "prediction",
    "intention",
    "action",
    "outcome",
    "surprise",
    "repair",
    "consolidation",
    "presence_cycle",
    "relationship_episode",
    "experiment",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_text(value: object, fallback: str = "", limit: int = 320) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return fallback
    if limit > 0 and len(text) > limit:
        return text[: max(0, limit - 1)].rstrip() + "..."
    return text


def normalize_text_list(value: object, limit: int = 8, item_limit: int = 180) -> List[str]:
    if not isinstance(value, list):
        return []
    items: List[str] = []
    seen = set()
    for raw in value:
        text = normalize_text(raw, fallback="", limit=item_limit)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(text)
        if len(items) >= limit:
            break
    return items


def normalize_experience_event(payload: Dict[str, object]) -> Dict[str, object]:
    now = utc_now()
    event_type = normalize_text(payload.get("event_type"), fallback="percept", limit=40)
    if event_type not in EVENT_TYPES:
        event_type = "percept"
    event = {
        "id": normalize_text(payload.get("id"), fallback=str(uuid.uuid4()), limit=80),
        "timestamp": normalize_text(payload.get("timestamp"), fallback=now, limit=60),
        "event_type": event_type,
        "source": normalize_text(payload.get("source"), fallback="unknown", limit=120),
        "actor": normalize_text(payload.get("actor"), fallback="eve", limit=80),
        "subject": normalize_text(payload.get("subject"), fallback="", limit=160),
        "summary": normalize_text(payload.get("summary"), fallback="Experience event recorded.", limit=500),
        "prediction": normalize_text(payload.get("prediction"), fallback="", limit=320),
        "result": normalize_text(payload.get("result"), fallback="", limit=320),
        "learning": normalize_text(payload.get("learning"), fallback="", limit=320),
        "evidence_ids": normalize_text_list(payload.get("evidence_ids"), limit=12),
        "commitment_ids": normalize_text_list(payload.get("commitment_ids"), limit=8),
        "action_ids": normalize_text_list(payload.get("action_ids"), limit=8),
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    }
    return event


def create_experience_event(
    *,
    event_type: str,
    source: str,
    summary: str,
    actor: str = "eve",
    subject: str = "",
    prediction: str = "",
    result: str = "",
    learning: str = "",
    evidence_ids: Optional[List[str]] = None,
    commitment_ids: Optional[List[str]] = None,
    action_ids: Optional[List[str]] = None,
    metadata: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    return normalize_experience_event(
        {
            "id": str(uuid.uuid4()),
            "timestamp": utc_now(),
            "event_type": event_type,
            "source": source,
            "actor": actor,
            "subject": subject,
            "summary": summary,
            "prediction": prediction,
            "result": result,
            "learning": learning,
            "evidence_ids": evidence_ids or [],
            "commitment_ids": commitment_ids or [],
            "action_ids": action_ids or [],
            "metadata": metadata or {},
        }
    )


def append_experience_event(path: Path, event: Dict[str, object]) -> Dict[str, object]:
    normalized = normalize_experience_event(event)
    eve_store.append_jsonl_record(path, normalized, ensure_ascii=True)
    return normalized


def read_experience_events(
    path: Path,
    *,
    limit: Optional[int] = None,
    event_type: Optional[str] = None,
    source: Optional[str] = None,
) -> List[Dict[str, object]]:
    if limit is not None and not event_type and not source:
        raw_records = eve_store.read_jsonl_tail_records(path, limit)
    else:
        raw_records = eve_store.read_jsonl_records(path)
    records = [normalize_experience_event(item) for item in raw_records]
    if event_type:
        records = [item for item in records if item.get("event_type") == event_type]
    if source:
        records = [item for item in records if item.get("source") == source]
    records.sort(key=lambda item: item.get("timestamp") or "", reverse=True)
    if limit is not None:
        records = records[:limit]
    return records
