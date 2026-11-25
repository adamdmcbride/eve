#!/usr/bin/env python3

"""Shared contracts for Eve's small append-only JSONL record ledgers.

This module deliberately owns only record normalization plumbing. Domain
schemas remain in their respective commitment, evidence, and experience
modules so this does not become a second policy or memory authority.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional

import eve_store


Record = Dict[str, object]
Normalizer = Callable[[Record], Record]
RecordPredicate = Callable[[Record], bool]
RecordSortKey = Callable[[Record], object]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_text(value: object, fallback: str = "", limit: int = 320) -> str:
    """Collapse whitespace and return text no longer than ``limit``.

    The previous ledger-local copies sliced to ``limit - 1`` and then added a
    three-character ellipsis, so a declared limit could be exceeded by two
    characters. Keeping the bound exact matters because these values are later
    composed into model context and UI summaries.
    """

    text = " ".join(str(value or "").split()).strip()
    if not text:
        return fallback
    if limit > 0 and len(text) > limit:
        if limit <= 3:
            return "." * limit
        return text[: limit - 3].rstrip() + "..."
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


def append_normalized_record(path: Path, record: Record, *, normalize: Normalizer) -> Record:
    normalized = normalize(record)
    eve_store.append_jsonl_record(path, normalized, ensure_ascii=True)
    return normalized


def read_normalized_records(
    path: Path,
    *,
    normalize: Normalizer,
    limit: Optional[int] = None,
    filters: Optional[Mapping[str, object]] = None,
    predicate: Optional[RecordPredicate] = None,
    sort_key: Optional[RecordSortKey] = None,
) -> List[Record]:
    """Read, normalize, filter, and newest-sort one domain ledger.

    Unfiltered bounded reads retain Eve's efficient tail path. A filter or
    predicate deliberately performs a full scan because historical ledgers do
    not yet guarantee timestamp order; stopping early could silently omit a
    newer matching record.
    """

    active_filters = {key: value for key, value in (filters or {}).items() if value is not None}
    needs_full_scan = bool(active_filters) or predicate is not None
    if limit is not None and not needs_full_scan:
        raw_records = eve_store.read_jsonl_tail_records(path, limit)
    else:
        raw_records = eve_store.read_jsonl_records(path)

    records = [normalize(item) for item in raw_records]
    for key, expected in active_filters.items():
        records = [item for item in records if item.get(key) == expected]
    if predicate is not None:
        records = [item for item in records if predicate(item)]
    if sort_key is not None:
        records.sort(key=sort_key, reverse=True)
    if limit is not None:
        records = records[:limit]
    return records
