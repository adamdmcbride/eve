#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional
import uuid

import eve_records
from eve_records import normalize_text, normalize_text_list, utc_now


COMMITMENT_KINDS = {"suggestion", "offer", "plan", "commitment"}
COMMITMENT_STATUSES = {
    "proposed",
    "executing",
    "executed",
    "completed",
    "blocked",
    "capability_gap",
    "cancelled",
}


def normalize_commitment_record(payload: Dict[str, object]) -> Dict[str, object]:
    now = utc_now()
    kind = normalize_text(payload.get("kind"), fallback="commitment", limit=40).lower()
    if kind not in COMMITMENT_KINDS:
        kind = "commitment"
    status = normalize_text(payload.get("status"), fallback="proposed", limit=40).lower()
    if status not in COMMITMENT_STATUSES:
        status = "proposed"
    return {
        "id": normalize_text(payload.get("id"), fallback=str(uuid.uuid4()), limit=80),
        "created_at": normalize_text(payload.get("created_at"), fallback=now, limit=60),
        "updated_at": normalize_text(payload.get("updated_at"), fallback=now, limit=60),
        "source": normalize_text(payload.get("source"), fallback="unknown", limit=120),
        "kind": kind,
        "status": status,
        "text": normalize_text(payload.get("text"), fallback="", limit=700),
        "action": normalize_text(payload.get("action"), fallback="", limit=120),
        "supported_action": normalize_text(payload.get("supported_action"), fallback="", limit=120),
        "result_summary": normalize_text(payload.get("result_summary"), fallback="", limit=500),
        "verification": normalize_text(payload.get("verification"), fallback="", limit=500),
        "evidence_ids": normalize_text_list(payload.get("evidence_ids"), limit=12),
        "experience_event_ids": normalize_text_list(payload.get("experience_event_ids"), limit=8),
        "action_execution_ids": normalize_text_list(payload.get("action_execution_ids"), limit=8),
        "capability_gap_id": normalize_text(payload.get("capability_gap_id"), fallback="", limit=100),
        "proposal_id": normalize_text(payload.get("proposal_id"), fallback="", limit=100),
        "thread_id": normalize_text(payload.get("thread_id"), fallback="", limit=100),
        "inbound_message_id": normalize_text(payload.get("inbound_message_id"), fallback="", limit=100),
        "reply_message_id": normalize_text(payload.get("reply_message_id"), fallback="", limit=100),
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    }


def create_commitment_record(
    *,
    source: str,
    text: str,
    kind: str = "commitment",
    status: str = "proposed",
    action: str = "",
    supported_action: str = "",
    result_summary: str = "",
    verification: str = "",
    evidence_ids: Optional[List[str]] = None,
    experience_event_ids: Optional[List[str]] = None,
    action_execution_ids: Optional[List[str]] = None,
    capability_gap_id: str = "",
    proposal_id: str = "",
    thread_id: str = "",
    inbound_message_id: str = "",
    reply_message_id: str = "",
    metadata: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    now = utc_now()
    return normalize_commitment_record(
        {
            "id": str(uuid.uuid4()),
            "created_at": now,
            "updated_at": now,
            "source": source,
            "kind": kind,
            "status": status,
            "text": text,
            "action": action,
            "supported_action": supported_action,
            "result_summary": result_summary,
            "verification": verification,
            "evidence_ids": evidence_ids or [],
            "experience_event_ids": experience_event_ids or [],
            "action_execution_ids": action_execution_ids or [],
            "capability_gap_id": capability_gap_id,
            "proposal_id": proposal_id,
            "thread_id": thread_id,
            "inbound_message_id": inbound_message_id,
            "reply_message_id": reply_message_id,
            "metadata": metadata or {},
        }
    )


def append_commitment_record(path: Path, record: Dict[str, object]) -> Dict[str, object]:
    return eve_records.append_normalized_record(path, record, normalize=normalize_commitment_record)


def read_commitment_records(
    path: Path,
    *,
    limit: Optional[int] = None,
    status: Optional[str] = None,
    source: Optional[str] = None,
) -> List[Dict[str, object]]:
    filters = {}
    if status:
        filters["status"] = status
    if source:
        filters["source"] = source
    return eve_records.read_normalized_records(
        path,
        normalize=normalize_commitment_record,
        limit=limit,
        filters=filters,
        sort_key=lambda item: item.get("created_at") or item.get("updated_at") or "",
    )
