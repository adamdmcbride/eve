#!/usr/bin/env python3
"""Build Eve's privacy-minimized, non-canonical Spotlight projection.

The caller must provide an explicit backend-owned approval bit. This module
never reads or mutates Eve's canonical stores and never accepts records from
the browser. Its output is a lossy convenience index that can be deleted and
rebuilt from fresher monitor evidence.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
from typing import Any, Mapping


SCHEMA_ID = "eve_spotlight_projection.v1"
MAX_RECORDS = 3

_FORBIDDEN_PATTERNS = (
    re.compile(r"-----begin (?:rsa |ec |openssh )?private key-----", re.IGNORECASE),
    re.compile(r"\b(?:api[_-]?key|password|authorization)\s*[:=]", re.IGNORECASE),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?:^|\s)/(?:Users|home|private|Volumes)/", re.IGNORECASE),
    re.compile(r"\b[A-Za-z]:\\Users\\", re.IGNORECASE),
    re.compile(r"(?:^|[\s/])\.(?:eve|ssh|aws|gnupg)(?:[/\s]|$)", re.IGNORECASE),
    re.compile(r"\b[A-Fa-f0-9]{32,}\b"),
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", re.IGNORECASE),
    re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b"),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _compact(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text or any(pattern.search(text) for pattern in _FORBIDDEN_PATTERNS):
        return ""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first_text(values: list[object], *, limit: int) -> str:
    for value in values:
        if isinstance(value, Mapping):
            value = value.get("title") or value.get("summary") or value.get("goal") or ""
        text = _compact(value, limit)
        if text:
            return text
    return ""


def _record(source_kind: str, slot: str, title: str, summary: str, keywords: list[str]) -> dict[str, Any]:
    revision = hashlib.sha256(f"{source_kind}\0{summary}".encode("utf-8")).hexdigest()
    opaque_id = hashlib.sha256(f"eve-spotlight\0{source_kind}\0{slot}".encode("utf-8")).hexdigest()
    return {
        "approval": "spotlight_approved",
        "opaque_id": opaque_id,
        "source_kind": source_kind,
        "source_revision": revision,
        "title": title,
        "summary": summary,
        "keywords": keywords[:8],
    }


def build_spotlight_projection(
    monitor: Mapping[str, Any],
    *,
    approved: bool,
    approval_source: str = "",
) -> dict[str, Any]:
    """Return at most three approved derived records from bounded monitor data."""

    if not approved:
        return {
            "schema_id": SCHEMA_ID,
            "generated_at": _utc_now(),
            "source_authority": "eve_local_backend",
            "canonical": False,
            "approved": False,
            "approval_source": "",
            "records": [],
            "record_count": 0,
            "raw_transcripts_included": False,
            "canonical_identifiers_included": False,
        }

    workspace = _mapping(monitor.get("workspace"))
    workspace_state = _mapping(workspace.get("workspace_state"))
    autonomy = _mapping(monitor.get("autonomy"))
    agenda = _mapping(autonomy.get("agenda"))
    homeostasis = _mapping(monitor.get("homeostasis"))
    operations = _mapping(monitor.get("operations"))

    goals = workspace.get("active_goals") if isinstance(workspace.get("active_goals"), list) else []
    focus = _first_text(
        [*(goals[:1]), workspace_state.get("focus"), agenda.get("current_focus")],
        limit=520,
    )
    next_step = _first_text(
        [homeostasis.get("next_regulation_step"), agenda.get("next_step")],
        limit=520,
    )

    action_rows = [
        item for item in (operations.get("actions") or []) if isinstance(item, Mapping)
    ] if isinstance(operations.get("actions"), list) else []
    verified_actions = [
        item
        for item in action_rows
        if str(item.get("tree_status") or "").upper() == "SUCCESS"
        and item.get("verification_ok") is True
        and item.get("result_ok") is True
        and item.get("typed_contract_ok") is not False
    ]
    verified_actions.sort(
        key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
        reverse=True,
    )
    action = _first_text(
        [verified_actions[0].get("action") if verified_actions else ""],
        limit=300,
    )

    records: list[dict[str, Any]] = []
    if focus:
        records.append(
            _record(
                "current_focus",
                "current",
                "Eve's current focus",
                focus,
                ["Eve", "current focus"],
            )
        )
    if next_step and next_step.casefold() != focus.casefold():
        records.append(
            _record(
                "commitment_summary",
                "next",
                "Eve's next bounded step",
                next_step,
                ["Eve", "next step"],
            )
        )
    if action:
        records.append(
            _record(
                "evidence_summary",
                "latest-verified-action",
                "Eve's latest verified action",
                f"Verified local action: {action}.",
                ["Eve", "verified action"],
            )
        )

    records = records[:MAX_RECORDS]
    return {
        "schema_id": SCHEMA_ID,
        "generated_at": _utc_now(),
        "source_authority": "eve_local_backend",
        "canonical": False,
        "approved": True,
        "approval_source": _compact(approval_source, 120) or "operator_config",
        "records": records,
        "record_count": len(records),
        "raw_transcripts_included": False,
        "canonical_identifiers_included": False,
    }


__all__ = ["MAX_RECORDS", "SCHEMA_ID", "build_spotlight_projection"]
