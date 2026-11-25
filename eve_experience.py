#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional
import uuid

import eve_records
from eve_records import normalize_text, normalize_text_list, utc_now


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
    return eve_records.append_normalized_record(path, event, normalize=normalize_experience_event)


def read_experience_events(
    path: Path,
    *,
    limit: Optional[int] = None,
    event_type: Optional[str] = None,
    source: Optional[str] = None,
) -> List[Dict[str, object]]:
    filters = {}
    if event_type:
        filters["event_type"] = event_type
    if source:
        filters["source"] = source
    return eve_records.read_normalized_records(
        path,
        normalize=normalize_experience_event,
        limit=limit,
        filters=filters,
        sort_key=lambda item: item.get("timestamp") or "",
    )
