#!/usr/bin/env python3

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional
import uuid

import eve_store


DEFAULT_TTL_HOURS = 24


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso_datetime(value: object) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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


def normalize_confidence(value: object) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 1.0
    return min(1.0, max(0.0, confidence))


def default_expires_at(observed_at: str, ttl_hours: object = DEFAULT_TTL_HOURS) -> str:
    observed = parse_iso_datetime(observed_at) or datetime.now(timezone.utc)
    try:
        hours = max(1, int(ttl_hours))
    except (TypeError, ValueError):
        hours = DEFAULT_TTL_HOURS
    return (observed + timedelta(hours=hours)).replace(microsecond=0).isoformat()


def normalize_evidence_record(payload: Dict[str, object]) -> Dict[str, object]:
    now = utc_now()
    created_at = normalize_text(payload.get("created_at"), fallback=now, limit=60)
    observed_at = normalize_text(payload.get("observed_at"), fallback=created_at, limit=60)
    expires_at = normalize_text(
        payload.get("expires_at"),
        fallback=default_expires_at(observed_at, payload.get("ttl_hours", DEFAULT_TTL_HOURS)),
        limit=60,
    )
    status = normalize_text(payload.get("status"), fallback="active", limit=40).lower()
    if status not in {"active", "superseded", "expired", "retracted"}:
        status = "active"
    record = {
        "id": normalize_text(payload.get("id"), fallback=str(uuid.uuid4()), limit=80),
        "created_at": created_at,
        "updated_at": normalize_text(payload.get("updated_at"), fallback=now, limit=60),
        "observed_at": observed_at,
        "expires_at": expires_at,
        "source": normalize_text(payload.get("source"), fallback="unknown", limit=120),
        "kind": normalize_text(payload.get("kind"), fallback="signal", limit=80),
        "claim": normalize_text(payload.get("claim"), fallback="", limit=500),
        "summary": normalize_text(payload.get("summary"), fallback="", limit=500),
        "confidence": normalize_confidence(payload.get("confidence")),
        "status": status,
        "supports": normalize_text_list(payload.get("supports"), limit=8),
        "contradicts": normalize_text_list(payload.get("contradicts"), limit=8),
        "supersedes": normalize_text_list(payload.get("supersedes"), limit=8),
        "actionability": normalize_text(payload.get("actionability"), fallback="watch", limit=80),
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    }
    if not record["claim"]:
        record["claim"] = record["summary"] or "Evidence recorded."
    if not record["summary"]:
        record["summary"] = record["claim"]
    return record


def evidence_freshness_score(record: Dict[str, object], now: Optional[datetime] = None) -> int:
    normalized = normalize_evidence_record(record)
    if normalized["status"] in {"superseded", "expired", "retracted"}:
        return 0
    current = now or datetime.now(timezone.utc)
    observed = parse_iso_datetime(normalized.get("observed_at")) or current
    expires = parse_iso_datetime(normalized.get("expires_at"))
    if expires is not None and current >= expires:
        return 0
    confidence = normalize_confidence(normalized.get("confidence"))
    if expires is None or expires <= observed:
        return int(round(100 * confidence))
    total = max(1.0, (expires - observed).total_seconds())
    remaining = max(0.0, (expires - current).total_seconds())
    return int(round(100 * confidence * min(1.0, remaining / total)))


def evidence_is_active(record: Dict[str, object], *, min_freshness: int = 1) -> bool:
    return evidence_freshness_score(record) >= min_freshness


def create_evidence_record(
    *,
    source: str,
    kind: str,
    claim: str,
    summary: str = "",
    confidence: float = 1.0,
    ttl_hours: int = DEFAULT_TTL_HOURS,
    supports: Optional[Iterable[str]] = None,
    contradicts: Optional[Iterable[str]] = None,
    supersedes: Optional[Iterable[str]] = None,
    actionability: str = "watch",
    metadata: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    observed_at = utc_now()
    return normalize_evidence_record(
        {
            "id": str(uuid.uuid4()),
            "created_at": observed_at,
            "updated_at": observed_at,
            "observed_at": observed_at,
            "expires_at": default_expires_at(observed_at, ttl_hours),
            "source": source,
            "kind": kind,
            "claim": claim,
            "summary": summary or claim,
            "confidence": confidence,
            "supports": list(supports or []),
            "contradicts": list(contradicts or []),
            "supersedes": list(supersedes or []),
            "actionability": actionability,
            "metadata": metadata or {},
        }
    )


def append_evidence_record(path: Path, record: Dict[str, object]) -> Dict[str, object]:
    normalized = normalize_evidence_record(record)
    eve_store.append_jsonl_record(path, normalized, ensure_ascii=True)
    return normalized


def read_evidence_records(
    path: Path,
    *,
    limit: Optional[int] = None,
    source: Optional[str] = None,
    kind: Optional[str] = None,
    active_only: bool = False,
    min_freshness: int = 1,
) -> List[Dict[str, object]]:
    if limit is not None and not source and not kind and not active_only:
        raw_records = eve_store.read_jsonl_tail_records(path, limit)
    else:
        raw_records = eve_store.read_jsonl_records(path)
    records = [normalize_evidence_record(item) for item in raw_records]
    if source:
        records = [item for item in records if item.get("source") == source]
    if kind:
        records = [item for item in records if item.get("kind") == kind]
    if active_only:
        records = [item for item in records if evidence_is_active(item, min_freshness=min_freshness)]
    records.sort(key=lambda item: item.get("observed_at") or item.get("created_at") or "", reverse=True)
    if limit is not None:
        records = records[:limit]
    return records


def supersede_records(
    records: List[Dict[str, object]],
    *,
    superseded_ids: Iterable[str],
    superseding_id: str,
) -> List[Dict[str, object]]:
    ids = {str(item) for item in superseded_ids if str(item)}
    if not ids:
        return records
    updated: List[Dict[str, object]] = []
    for record in records:
        normalized = normalize_evidence_record(record)
        if normalized["id"] in ids and normalized["status"] == "active":
            normalized["status"] = "superseded"
            normalized["updated_at"] = utc_now()
            superseded_by = normalize_text_list(normalized.get("superseded_by"), limit=8)
            if superseding_id and superseding_id not in superseded_by:
                superseded_by.append(superseding_id)
            normalized["superseded_by"] = superseded_by
        updated.append(normalized)
    return updated
