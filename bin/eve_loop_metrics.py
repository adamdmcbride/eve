#!/usr/bin/env python3
"""Read-only loop metrics for Eve (Rearchitecture Program section 9).

Computes every measure in docs/architecture/EVE_REARCHITECTURE_PROGRAM_2026_09_17.md
section 9 from ``.eve/*.jsonl`` and ``.eve/operational_state.sqlite3``.

Guarantees:
- Nothing under the Eve dir is written. JSONL files are opened for reading only and
  the SQLite spine is opened with ``file:...?mode=ro`` (``uri=True``).
- Every number is computed from the rows; nothing is hard-coded.
- Python 3.9 compatible (the daemon interpreter is Apple /usr/bin/python3 3.9.6).

Usage:
    python3 bin/eve_loop_metrics.py --json [--days 7] [--eve-dir PATH] [--now ISO]
    python3 bin/eve_loop_metrics.py --table [--days 7]

The classification of journal kinds into "lived" and "telemetry" is a fixed list
(``LIVED_KINDS`` / ``LIVED_PREFIXES``) so the number is auditable: the JSON output
carries the per-kind breakdown next to every share.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

DEFAULT_DAYS = 7
MIND_TICK_RECENT_N = 50
TOP_OPERATIONS = 15
CONSEQUENCE_WINDOW_HOURS = 24

# Journal kinds that are Eve's lived record (what a reflection should be reading)
# as opposed to telemetry emitted by the scheduler, the body loop and the probes.
LIVED_KINDS = frozenset(
    {
        "thought",
        "reflection",
        "capture",
        "user_request",
        "assistant_response",
        "outreach_sent",
        "tension_logged",
        "tension_updated",
        "experiment_logged",
        "experiment_updated",
        "outcome_logged",
        "judgment_call_logged",
        "uncertainty_logged",
        "proposal_drafted",
        "proposal_updated",
        "proposal_applied",
        "self_change_applied",
        "config_self_changed",
        "success_pattern_logged",
        "relationship_episodes_extracted",
        "review_note_logged",
        "failure_review_generated",
        "uncertainty_review_generated",
        "judgment_review_generated",
        "code_session_completed",
        "attribution_corrected",
        "capability_gap_logged",
        "commitment_logged",
        "lesson_logged",
    }
)
LIVED_PREFIXES = ("reflection_", "tension_", "experiment_", "conversation_")

# Daemon mailbox kinds that carry the original loop to the operator (section 9 target:
# >= 80% of daemon messages should be one of these).
LOOP_MESSAGE_KINDS = frozenset({"reflection_update", "proposal_update", "self_change", "proactive_outreach"})

TERMINAL_EXPERIMENT_STATUSES = frozenset({"completed", "closed", "concluded", "verified", "succeeded", "failed", "refuted", "supported"})
EXPIRED_EXPERIMENT_STATUSES = frozenset({"expired", "expired_unverified", "unverified"})


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def parse_ts(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                rows.append(record)
    return rows


def row_time(row: Dict[str, Any], *keys: str) -> Optional[datetime]:
    for key in keys:
        parsed = parse_ts(row.get(key))
        if parsed is not None:
            return parsed
    return None


def in_window(when: Optional[datetime], since: datetime, until: datetime) -> bool:
    return when is not None and since <= when <= until


def share(numerator: int, denominator: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return round(numerator / float(denominator), 4)


def per_day(count: int, days: float) -> Optional[float]:
    if days <= 0:
        return None
    return round(count / float(days), 2)


def per_week(count: int, days: float) -> Optional[float]:
    if days <= 0:
        return None
    return round(count / (float(days) / 7.0), 2)


def is_lived_kind(kind: str) -> bool:
    if kind in LIVED_KINDS:
        return True
    return any(kind.startswith(prefix) for prefix in LIVED_PREFIXES)


def metadata_of(row: Dict[str, Any]) -> Dict[str, Any]:
    meta = row.get("metadata")
    return meta if isinstance(meta, dict) else {}


def normalize_title(title: Any) -> str:
    return " ".join(str(title or "").split()).strip().lower()


def truthy_list(value: Any) -> bool:
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def counter_dict(counter: Counter, limit: Optional[int] = None) -> Dict[str, int]:
    items = counter.most_common(limit)
    return {str(key): int(value) for key, value in items}


# ---------------------------------------------------------------------------
# sections
# ---------------------------------------------------------------------------


def journal_section(entries: List[Dict[str, Any]], since: datetime, until: datetime, days: float) -> Dict[str, Any]:
    window = [row for row in entries if in_window(row_time(row, "timestamp"), since, until)]
    kinds = Counter(str(row.get("kind") or "") for row in window)
    lived = sum(count for kind, count in kinds.items() if is_lived_kind(kind))
    telemetry = len(window) - lived
    lived_kinds = Counter({kind: count for kind, count in kinds.items() if is_lived_kind(kind)})
    telemetry_kinds = Counter({kind: count for kind, count in kinds.items() if not is_lived_kind(kind)})
    return {
        "rows_total": len(entries),
        "rows_in_window": len(window),
        "rows_per_week": per_week(len(window), days),
        "lived": lived,
        "telemetry": telemetry,
        "lived_share": share(lived, len(window)),
        "lived_kinds": counter_dict(lived_kinds),
        "telemetry_kinds_top": counter_dict(telemetry_kinds, 20),
    }


def reflection_section(entries: List[Dict[str, Any]], since: datetime, until: datetime, days: float) -> Dict[str, Any]:
    dated: List[Tuple[datetime, Dict[str, Any]]] = []
    for row in entries:
        when = row_time(row, "timestamp")
        if when is not None:
            dated.append((when, row))
    dated.sort(key=lambda item: item[0])
    reflections_all = [(when, row) for when, row in dated if row.get("kind") == "reflection"]
    reflections = [(when, row) for when, row in reflections_all if since <= when <= until]
    per_reflection: List[Dict[str, Any]] = []
    with_lived_kinds_metadata = 0
    lived_total = 0
    context_total = 0
    for when, row in reflections:
        meta = metadata_of(row)
        context_limit = int(meta.get("source_entries") or 0)
        context_days = meta.get("days")
        lived_kinds_meta = meta.get("lived_kinds")
        if isinstance(lived_kinds_meta, (dict, list)):
            with_lived_kinds_metadata += 1
        # Same selection generate_reflection uses: the newest `context_limit` entries
        # written before the reflection, inside `days` days.
        earliest = None
        if isinstance(context_days, (int, float)) and context_days > 0:
            earliest = when - timedelta(days=float(context_days))
        preceding = [
            candidate
            for candidate_when, candidate in dated
            if candidate_when < when and candidate is not row and (earliest is None or candidate_when >= earliest)
        ]
        if context_limit > 0:
            preceding = preceding[-context_limit:]
        kinds = Counter(str(candidate.get("kind") or "") for candidate in preceding)
        lived = sum(count for kind, count in kinds.items() if is_lived_kind(kind))
        lived_total += lived
        context_total += len(preceding)
        per_reflection.append(
            {
                "timestamp": iso(when),
                "model": meta.get("model"),
                "source_entries": context_limit,
                "context_rows": len(preceding),
                "lived": lived,
                "lived_share": share(lived, len(preceding)),
                "context_kinds_top": counter_dict(kinds, 8),
            }
        )
    last_context = per_reflection[-1]["context_kinds_top"] if per_reflection else {}
    return {
        "reflections_total": len(reflections_all),
        "reflections_in_window": len(reflections),
        "reflections_per_week": per_week(len(reflections), days),
        "with_lived_kinds_metadata": with_lived_kinds_metadata,
        "context_rows": context_total,
        "context_lived": lived_total,
        "context_lived_share": share(lived_total, context_total),
        "last_reflection_context_kinds": last_context,
        "per_reflection": per_reflection,
    }


def tension_source(row: Dict[str, Any]) -> str:
    source = row.get("source")
    if not source:
        source = metadata_of(row).get("source")
    return str(source or "")


def tensions_section(tensions: List[Dict[str, Any]], since: datetime, until: datetime, days: float) -> Dict[str, Any]:
    window = [row for row in tensions if in_window(row_time(row, "timestamp", "created_at"), since, until)]
    sources = Counter(tension_source(row) or "(none)" for row in window)
    from_reflection = sum(1 for row in window if tension_source(row) == "reflection")
    return {
        "rows_total": len(tensions),
        "rows_in_window": len(window),
        "per_week": per_week(len(window), days),
        "with_source_reflection": from_reflection,
        "with_source_reflection_per_week": per_week(from_reflection, days),
        "sources": counter_dict(sources),
        "status_counts": counter_dict(Counter(str(row.get("status") or "") for row in window)),
    }


def experiment_is_expired(row: Dict[str, Any]) -> bool:
    status = str(row.get("status") or "").lower()
    outcome = str(row.get("outcome") or "").strip().lower()
    return status in EXPIRED_EXPERIMENT_STATUSES or outcome.startswith("expired")


def experiment_is_closed(row: Dict[str, Any]) -> bool:
    return str(row.get("status") or "").lower() in TERMINAL_EXPERIMENT_STATUSES


def experiments_section(
    experiments: List[Dict[str, Any]],
    outcomes: List[Dict[str, Any]],
    since: datetime,
    until: datetime,
    days: float,
) -> Dict[str, Any]:
    outcome_targets = set()
    for row in outcomes:
        target_kind = str(row.get("target_kind") or "")
        if target_kind == "experiment" or row.get("experiment_id"):
            outcome_targets.add(str(row.get("target_id") or row.get("experiment_id") or ""))
    closed_rows = []
    closed_on_evidence = []
    expired_rows = []
    window_rows = []
    for row in experiments:
        closed_at = row_time(row, "closed_at", "updated_at", "created_at")
        if in_window(closed_at, since, until):
            window_rows.append(row)
        if experiment_is_expired(row):
            expired_rows.append(row)
            continue
        if experiment_is_closed(row):
            closed_rows.append(row)
            outcome_text = str(row.get("outcome") or "").strip()
            has_link = (
                str(row.get("id") or "") in outcome_targets
                or truthy_list(row.get("outcome_ids"))
                or truthy_list(row.get("evidence_ids"))
                or truthy_list(row.get("evidence"))
            )
            if outcome_text and has_link:
                closed_on_evidence.append(row)
    window_ids = {str(row.get("id") or "") for row in window_rows}
    closed_on_evidence_window = [row for row in closed_on_evidence if str(row.get("id") or "") in window_ids]
    expired_window = [row for row in expired_rows if str(row.get("id") or "") in window_ids]
    closed_window = [row for row in closed_rows if str(row.get("id") or "") in window_ids]
    resolved_window = len(closed_window) + len(expired_window)
    return {
        "rows_total": len(experiments),
        "rows_in_window": len(window_rows),
        "status_counts": counter_dict(Counter(str(row.get("status") or "") for row in experiments)),
        "closed_total": len(closed_rows),
        "closed_on_evidence_total": len(closed_on_evidence),
        "closed_in_window": len(closed_window),
        "closed_on_evidence_in_window": len(closed_on_evidence_window),
        "closed_on_evidence_per_week": per_week(len(closed_on_evidence_window), days),
        "expired_unverified_total": len(expired_rows),
        "expired_unverified_in_window": len(expired_window),
        "expired_unverified_share_in_window": share(len(expired_window), resolved_window),
    }


def proposals_section(proposals: List[Dict[str, Any]], since: datetime, until: datetime) -> Dict[str, Any]:
    latest: Dict[str, Dict[str, Any]] = {}
    for row in proposals:
        latest[str(row.get("id") or id(row))] = row
    rows = list(latest.values())
    status_counts = Counter(str(row.get("status") or "") for row in rows)
    drafts = [row for row in rows if str(row.get("status") or "") == "draft"]
    with_tensions = 0
    with_rollback = 0
    with_lineage = 0
    for row in drafts:
        meta = metadata_of(row)
        has_tensions = truthy_list(meta.get("tension_ids")) or truthy_list(row.get("tension_ids"))
        has_rollback = truthy_list(meta.get("rollback")) or truthy_list(row.get("rollback"))
        with_tensions += 1 if has_tensions else 0
        with_rollback += 1 if has_rollback else 0
        with_lineage += 1 if (has_tensions and has_rollback) else 0
    titles = Counter(normalize_title(row.get("title")) for row in drafts)
    duplicate_titles = {title: count for title, count in titles.items() if count > 1}
    duplicate_draft_rows = sum(duplicate_titles.values())
    created_in_window = sum(1 for row in rows if in_window(row_time(row, "created_at"), since, until))
    drafts_created_in_window = sum(1 for row in drafts if in_window(row_time(row, "created_at"), since, until))
    return {
        "rows_total": len(rows),
        "status_counts": counter_dict(status_counts),
        "proposals_created_in_window": created_in_window,
        "drafts": len(drafts),
        "drafts_created_in_window": drafts_created_in_window,
        "drafts_with_tension_ids": with_tensions,
        "drafts_with_rollback": with_rollback,
        "drafts_with_lineage": with_lineage,
        "drafts_lineage_share": share(with_lineage, len(drafts)),
        "duplicate_title_draft_rows": duplicate_draft_rows,
        "duplicate_titles": {title[:80]: count for title, count in sorted(duplicate_titles.items(), key=lambda item: -item[1])},
    }


def self_change_section(
    ledger: List[Dict[str, Any]],
    outcomes: List[Dict[str, Any]],
    eve_dir: Path,
    since: datetime,
    until: datetime,
) -> Dict[str, Any]:
    outcome_index: Dict[str, List[datetime]] = defaultdict(list)
    for row in outcomes:
        target_kind = str(row.get("target_kind") or "")
        if target_kind not in {"self_change", "proposal", "self_change_session"}:
            continue
        when = row_time(row, "created_at", "timestamp")
        if when is None:
            continue
        outcome_index[str(row.get("target_id") or "")].append(when)

    def has_consequence(row: Dict[str, Any]) -> bool:
        if truthy_list(row.get("consequence")) or truthy_list(row.get("consequence_summary")):
            return True
        finished = row_time(row, "finished_at", "started_at")
        if finished is None:
            return False
        limit = finished + timedelta(hours=CONSEQUENCE_WINDOW_HOURS)
        for key in ("session_id", "proposal_id"):
            for when in outcome_index.get(str(row.get(key) or ""), []):
                if finished <= when <= limit:
                    return True
        return False

    def has_before_json(row: Dict[str, Any]) -> bool:
        session_id = str(row.get("session_id") or "")
        if not session_id:
            return False
        candidates = [
            eve_dir / "self_change" / session_id / "before.json",
            eve_dir / "self_change" / session_id / "backup" / "before.json",
        ]
        return any(path.is_file() for path in candidates)

    def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        outcome_counts = Counter(str(row.get("outcome") or "") for row in rows)
        applied = [row for row in rows if str(row.get("outcome") or "") == "applied"]
        failed = outcome_counts.get("failed", 0)
        titles = Counter(normalize_title(row.get("proposal_title")) for row in rows)
        duplicate_titles = {title[:80]: count for title, count in titles.items() if count > 1}
        return {
            "rows": len(rows),
            "outcome_counts": counter_dict(outcome_counts),
            "failed": failed,
            "failed_rate": share(failed, len(rows)),
            "applied": len(applied),
            "applied_with_consequence": sum(1 for row in applied if has_consequence(row)),
            "applied_with_before_json": sum(1 for row in applied if has_before_json(row)),
            "applied_with_rollback": sum(1 for row in applied if truthy_list(row.get("rollback"))),
            "applied_with_patched_paths": sum(1 for row in applied if truthy_list(row.get("patched_paths"))),
            "unfinished": sum(1 for row in rows if row.get("started_at") and not row.get("finished_at")),
            "duplicate_proposal_titles": duplicate_titles,
        }

    window = [row for row in ledger if in_window(row_time(row, "finished_at", "started_at"), since, until)]
    return {"all_time": summarize(ledger), "in_window": summarize(window)}


def mind_tick_section(
    entries: List[Dict[str, Any]],
    perf_rows: List[Dict[str, Any]],
    since: datetime,
    until: datetime,
) -> Dict[str, Any]:
    ticks = [row for row in entries if row.get("kind") == "mind_tick"]
    ticks.sort(key=lambda row: row_time(row, "timestamp") or since)
    window = [row for row in ticks if in_window(row_time(row, "timestamp"), since, until)]

    def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        parsed = sum(1 for row in rows if metadata_of(row).get("used_fallback") is False)
        return {
            "rows": len(rows),
            "used_fallback_false": parsed,
            "parsed_share": share(parsed, len(rows)),
            "model_counts": counter_dict(Counter(str(metadata_of(row).get("model") or "") for row in rows)),
            "fallback_reason_top": counter_dict(
                Counter(str(metadata_of(row).get("fallback_reason") or "")[:90] for row in rows if metadata_of(row).get("used_fallback")),
                6,
            ),
        }

    transport = [row for row in perf_rows if row["name"] == "daemon_model_mind_tick"]
    transport_ok = sum(1 for row in transport if row["ok"])
    return {
        "journal_all_time": summarize(ticks),
        "journal_in_window": summarize(window),
        "journal_last_%d" % MIND_TICK_RECENT_N: summarize(ticks[-MIND_TICK_RECENT_N:]),
        "transport_in_window": {
            "calls": len(transport),
            "ok": transport_ok,
            "ok_rate": share(transport_ok, len(transport)),
            "truncated": sum(1 for row in transport if row["meta"].get("truncated") is True),
        },
    }


def daemon_message_kind(row: Dict[str, Any]) -> str:
    kind = row.get("kind")
    if not kind:
        kind = metadata_of(row).get("kind")
    return str(kind or "")


def daemon_messages_section(messages: List[Dict[str, Any]], since: datetime, until: datetime, days: float) -> Dict[str, Any]:
    eve_rows = [
        row
        for row in messages
        if str(row.get("sender") or "") == "eve" and in_window(row_time(row, "created_at", "timestamp"), since, until)
    ]
    replies = [row for row in eve_rows if daemon_message_kind(row) == "reply"]
    daemon_rows = [row for row in eve_rows if daemon_message_kind(row) != "reply"]
    by_kind = Counter(daemon_message_kind(row) or "(none)" for row in daemon_rows)
    loop_rows = sum(count for kind, count in by_kind.items() if kind in LOOP_MESSAGE_KINDS)
    to_user = sum(1 for row in daemon_rows if str(row.get("recipient") or "") == "user")
    return {
        "eve_rows_in_window": len(eve_rows),
        "replies": len(replies),
        "daemon_rows": len(daemon_rows),
        "daemon_rows_to_user": to_user,
        "per_day": per_day(len(daemon_rows), days),
        "to_user_per_day": per_day(to_user, days),
        "loop_kind_rows": loop_rows,
        "loop_kind_share": share(loop_rows, len(daemon_rows)),
        "by_kind": counter_dict(by_kind),
        "by_kind_per_day": {kind: per_day(count, days) for kind, count in by_kind.most_common()},
    }


def _perf_row(created_at: Any, name: Any, duration_ms: Any, ok: Any, meta: Any) -> Dict[str, Any]:
    if not isinstance(meta, dict):
        meta = {}
    return {
        "created_at": str(created_at or ""),
        "name": str(name or ""),
        "duration_ms": float(duration_ms or 0.0),
        "ok": bool(ok),
        "meta": meta,
    }


def _query_perf_sqlite(uri: str, since: datetime, until: datetime) -> List[Dict[str, Any]]:
    """Read model_call rows through one read-only URI; raises sqlite3.Error on any failure."""
    connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(perf_events)")}
        required = {"created_at", "category", "name", "duration_ms", "ok", "metadata_json"}
        if not required.issubset(columns):
            raise sqlite3.OperationalError(
                "perf_events columns %s missing %s" % (sorted(columns), sorted(required - columns))
            )
        cursor = connection.execute(
            "SELECT created_at, name, duration_ms, ok, metadata_json FROM perf_events "
            "WHERE category = 'model_call' AND created_at >= ? AND created_at <= ? ORDER BY created_at",
            (iso(since), iso(until)),
        )
        rows: List[Dict[str, Any]] = []
        for created_at, name, duration_ms, ok, metadata_json in cursor:
            try:
                meta = json.loads(metadata_json or "{}")
            except ValueError:
                meta = {}
            rows.append(_perf_row(created_at, name, duration_ms, ok, meta))
        return rows
    finally:
        connection.close()


def _read_perf_jsonl(path: Path, since: datetime, until: datetime) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for record in read_jsonl(path):
        if str(record.get("category") or "") != "model_call":
            continue
        when = row_time(record, "timestamp", "created_at")
        if not in_window(when, since, until):
            continue
        rows.append(_perf_row(iso(when), record.get("name"), record.get("duration_ms"), record.get("ok"), record.get("metadata")))
    rows.sort(key=lambda row: row["created_at"])
    return rows


def load_perf_model_calls(eve_dir: Path, since: datetime, until: datetime) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Model-call rows from the perf spine, read-only, with a documented fallback chain.

    1. ``file:...?mode=ro`` — the normal read-only open (what eve_db.connect_database uses).
    2. ``file:...?mode=ro&immutable=1`` — when (1) cannot open the WAL database because no
       ``-shm`` sidecar exists and a read-only connection may not create one. ``immutable``
       never creates a sidecar; it also ignores an un-checkpointed ``-wal`` file, so
       ``wal_sidecar_present`` is reported alongside.
    3. ``perf_events.jsonl`` — the append-only mirror of the same rows.
    """
    sqlite_path = eve_dir / "operational_state.sqlite3"
    jsonl_path = eve_dir / "perf_events.jsonl"
    info: Dict[str, Any] = {
        "source": None,
        "sqlite_path": str(sqlite_path),
        "sqlite_present": sqlite_path.exists(),
        "wal_sidecar_present": (eve_dir / "operational_state.sqlite3-wal").exists(),
        "errors": [],
    }
    if sqlite_path.exists():
        attempts = [
            ("sqlite:ro", "file:%s?mode=ro" % sqlite_path.as_posix()),
            ("sqlite:ro_immutable", "file:%s?mode=ro&immutable=1" % sqlite_path.as_posix()),
        ]
        for label, uri in attempts:
            try:
                rows = _query_perf_sqlite(uri, since, until)
            except sqlite3.Error as exc:
                info["errors"].append("%s: %s" % (label, exc))
                continue
            info["source"] = label
            return rows, info
    else:
        info["errors"].append("sqlite: missing %s" % sqlite_path)
    if jsonl_path.exists():
        info["source"] = "jsonl"
        info["jsonl_path"] = str(jsonl_path)
        return _read_perf_jsonl(jsonl_path, since, until), info
    info["errors"].append("jsonl: missing %s" % jsonl_path)
    return [], info


def model_calls_section(perf_rows: List[Dict[str, Any]], days: float, spine: Dict[str, Any]) -> Dict[str, Any]:
    backends = Counter(str(row["meta"].get("backend") or "(none)") for row in perf_rows)
    llama = [row for row in perf_rows if str(row["meta"].get("backend") or "") == "llama_cpp"]

    def bucket(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        rows = list(rows)
        ok = sum(1 for row in rows if row["ok"])
        wall_ms = sum(row["duration_ms"] for row in rows)
        return {
            "calls": len(rows),
            "ok": ok,
            "ok_rate": share(ok, len(rows)),
            "wall_hours": round(wall_ms / 3600000.0, 3),
            "per_day": per_day(len(rows), days),
        }

    per_lane: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    per_operation: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in llama:
        per_lane[str(row["meta"].get("model") or "(none)")].append(row)
        per_operation[row["name"] or str(row["meta"].get("operation") or "(none)")].append(row)
    lanes = {lane: bucket(rows) for lane, rows in per_lane.items()}
    operations = []
    for name, rows in per_operation.items():
        summary = bucket(rows)
        summary["operation"] = name
        summary["lanes"] = counter_dict(Counter(str(row["meta"].get("model") or "(none)") for row in rows))
        operations.append(summary)
    operations.sort(key=lambda item: (-item["wall_hours"], -item["calls"], item["operation"]))
    total = bucket(llama)
    total["backends_seen"] = counter_dict(backends)
    total["model_call_rows_all_backends"] = len(perf_rows)
    total["truncated"] = sum(1 for row in llama if row["meta"].get("truncated") is True)
    total["errors_top"] = counter_dict(Counter(str(row["meta"].get("error") or "")[:80] for row in llama if not row["ok"]), 6)
    return {
        "spine": spine,
        "llama_cpp": total,
        "per_lane": dict(sorted(lanes.items())),
        "operations_total": len(operations),
        "per_operation_top_by_wall": operations[:TOP_OPERATIONS],
    }


def cycle_skipped_section(entries: List[Dict[str, Any]], since: datetime, until: datetime, days: float) -> Dict[str, Any]:
    window = [
        row
        for row in entries
        if row.get("kind") == "cycle_skipped" and in_window(row_time(row, "timestamp"), since, until)
    ]
    by_gate = Counter(str(metadata_of(row).get("gate") or "(none)") for row in window)
    by_job = Counter(str(row.get("text") or "").split(":")[0].strip()[:60] for row in window)
    return {
        "rows_total": sum(1 for row in entries if row.get("kind") == "cycle_skipped"),
        "rows_in_window": len(window),
        "per_week": per_week(len(window), days),
        "by_gate": counter_dict(by_gate),
        "by_gate_per_week": {gate: per_week(count, days) for gate, count in by_gate.most_common()},
        "by_job_top": counter_dict(by_job, 12),
    }


def daemon_error_section(entries: List[Dict[str, Any]], since: datetime, until: datetime, days: float) -> Dict[str, Any]:
    window = [
        row
        for row in entries
        if row.get("kind") == "daemon_error" and in_window(row_time(row, "timestamp"), since, until)
    ]
    texts = Counter(str(row.get("text") or "").split(":")[0].strip()[:70] for row in window)
    return {
        "rows_total": sum(1 for row in entries if row.get("kind") == "daemon_error"),
        "rows_in_window": len(window),
        "per_day": per_day(len(window), days),
        "top_texts": counter_dict(texts, 10),
    }


def actions_section(actions: List[Dict[str, Any]], since: datetime, until: datetime, days: float) -> Dict[str, Any]:
    window = [row for row in actions if in_window(row_time(row, "created_at"), since, until)]
    ok = sum(1 for row in window if row.get("result_ok") is True)
    verified = sum(1 for row in window if row.get("verification_ok") is True)
    return {
        "rows_total": len(actions),
        "rows_in_window": len(window),
        "per_day": per_day(len(window), days),
        "result_ok": ok,
        "result_ok_rate": share(ok, len(window)),
        "verification_ok": verified,
        "by_action_top": counter_dict(Counter(str(row.get("action") or "") for row in window), 10),
        "by_source_top": counter_dict(Counter(str(row.get("source") or "").split(":")[0] for row in window), 6),
    }


def disk_section(eve_dir: Path) -> Dict[str, Any]:
    probe = eve_dir if eve_dir.exists() else Path.cwd()
    try:
        stats = os.statvfs(str(probe))
    except OSError as exc:
        return {"path": str(probe), "error": str(exc)}
    free = stats.f_bavail * stats.f_frsize
    total = stats.f_blocks * stats.f_frsize
    return {
        "path": str(probe),
        "free_bytes": int(free),
        "free_gib": round(free / float(1 << 30), 1),
        "total_gib": round(total / float(1 << 30), 1),
    }


def sources_section(eve_dir: Path, names: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name in names:
        path = eve_dir / name
        if path.exists():
            stat = path.stat()
            out[name] = {"bytes": stat.st_size, "mtime": iso(datetime.fromtimestamp(stat.st_mtime, timezone.utc))}
        else:
            out[name] = {"missing": True}
    return out


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------


SOURCE_FILES = [
    "entries.jsonl",
    "messages.jsonl",
    "proposals.jsonl",
    "self_change_ledger.jsonl",
    "tensions.jsonl",
    "experiments.jsonl",
    "outcomes.jsonl",
    "action_executions.jsonl",
    "operational_state.sqlite3",
    "perf_events.jsonl",
]


def compute_metrics(eve_dir: Path, days: float = DEFAULT_DAYS, now: Optional[datetime] = None) -> Dict[str, Any]:
    eve_dir = Path(eve_dir)
    until = now or datetime.now(timezone.utc)
    until = until.astimezone(timezone.utc)
    since = until - timedelta(days=float(days))
    entries = read_jsonl(eve_dir / "entries.jsonl")
    messages = read_jsonl(eve_dir / "messages.jsonl")
    proposals = read_jsonl(eve_dir / "proposals.jsonl")
    ledger = read_jsonl(eve_dir / "self_change_ledger.jsonl")
    tensions = read_jsonl(eve_dir / "tensions.jsonl")
    experiments = read_jsonl(eve_dir / "experiments.jsonl")
    outcomes = read_jsonl(eve_dir / "outcomes.jsonl")
    actions = read_jsonl(eve_dir / "action_executions.jsonl")
    perf_rows, perf_spine = load_perf_model_calls(eve_dir, since, until)
    return {
        "generated_at": iso(datetime.now(timezone.utc)),
        "eve_dir": str(eve_dir),
        "window": {"days": float(days), "since": iso(since), "until": iso(until)},
        "sources": sources_section(eve_dir, SOURCE_FILES),
        "reflection": reflection_section(entries, since, until, float(days)),
        "tensions": tensions_section(tensions, since, until, float(days)),
        "experiments": experiments_section(experiments, outcomes, since, until, float(days)),
        "proposals": proposals_section(proposals, since, until),
        "self_change": self_change_section(ledger, outcomes, eve_dir, since, until),
        "mind_ticks": mind_tick_section(entries, perf_rows, since, until),
        "journal": journal_section(entries, since, until, float(days)),
        "daemon_messages": daemon_messages_section(messages, since, until, float(days)),
        "model_calls": model_calls_section(perf_rows, float(days), perf_spine),
        "cycle_skipped": cycle_skipped_section(entries, since, until, float(days)),
        "daemon_error": daemon_error_section(entries, since, until, float(days)),
        "actions": actions_section(actions, since, until, float(days)),
        "disk": disk_section(eve_dir),
    }


def fmt_share(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return "%.1f%%" % (value * 100.0)


def fmt_num(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return "%.2f" % value
    return str(value)


def render_table(metrics: Dict[str, Any]) -> str:
    window = metrics["window"]
    lines: List[str] = []
    lines.append("Eve loop metrics  window=%s d  %s .. %s" % (fmt_num(window["days"]), window["since"], window["until"]))
    lines.append("")
    rows: List[Tuple[str, str]] = []
    reflection = metrics["reflection"]
    rows.append(
        (
            "reflection context lived share",
            "%s over %d reflections in window (%d rows; lived_kinds metadata on %d)"
            % (
                fmt_share(reflection["context_lived_share"]),
                reflection["reflections_in_window"],
                reflection["context_rows"],
                reflection["with_lived_kinds_metadata"],
            ),
        )
    )
    tensions = metrics["tensions"]
    rows.append(
        (
            "tensions/week with source=reflection",
            "%s (%d of %d in window; %d rows ever)"
            % (fmt_num(tensions["with_source_reflection_per_week"]), tensions["with_source_reflection"], tensions["rows_in_window"], tensions["rows_total"]),
        )
    )
    experiments = metrics["experiments"]
    rows.append(
        (
            "experiments closed on evidence/week",
            "%s (%d in window; %d ever; expired_unverified share %s)"
            % (
                fmt_num(experiments["closed_on_evidence_per_week"]),
                experiments["closed_on_evidence_in_window"],
                experiments["closed_on_evidence_total"],
                fmt_share(experiments["expired_unverified_share_in_window"]),
            ),
        )
    )
    proposals = metrics["proposals"]
    rows.append(
        (
            "drafts with lineage (tension_ids + rollback)",
            "%d of %d (%s); duplicate-title draft rows %d"
            % (proposals["drafts_with_lineage"], proposals["drafts"], fmt_share(proposals["drafts_lineage_share"]), proposals["duplicate_title_draft_rows"]),
        )
    )
    self_change = metrics["self_change"]["all_time"]
    rows.append(
        (
            "applied self-changes with 24h consequence",
            "%d of %d applied; before.json %d of %d" % (self_change["applied_with_consequence"], self_change["applied"], self_change["applied_with_before_json"], self_change["applied"]),
        )
    )
    rows.append(
        (
            "self-change failed rate",
            "%s (%d of %d rows; window %d of %d)"
            % (
                fmt_share(self_change["failed_rate"]),
                self_change["failed"],
                self_change["rows"],
                metrics["self_change"]["in_window"]["failed"],
                metrics["self_change"]["in_window"]["rows"],
            ),
        )
    )
    ticks = metrics["mind_ticks"]
    recent_key = "journal_last_%d" % MIND_TICK_RECENT_N
    rows.append(
        (
            "mind ticks parsed (used_fallback=False)",
            "window %d of %d (%s); last %d: %s; transport ok %d of %d"
            % (
                ticks["journal_in_window"]["used_fallback_false"],
                ticks["journal_in_window"]["rows"],
                fmt_share(ticks["journal_in_window"]["parsed_share"]),
                MIND_TICK_RECENT_N,
                fmt_share(ticks[recent_key]["parsed_share"]),
                ticks["transport_in_window"]["ok"],
                ticks["transport_in_window"]["calls"],
            ),
        )
    )
    journal = metrics["journal"]
    rows.append(
        (
            "journal lived share",
            "%s (%d lived of %d rows in window)" % (fmt_share(journal["lived_share"]), journal["lived"], journal["rows_in_window"]),
        )
    )
    dm = metrics["daemon_messages"]
    rows.append(
        (
            "daemon messages/day",
            "%s (%d rows; loop kinds %s)" % (fmt_num(dm["per_day"]), dm["daemon_rows"], fmt_share(dm["loop_kind_share"])),
        )
    )
    calls = metrics["model_calls"]["llama_cpp"]
    rows.append(
        (
            "llama.cpp calls/day",
            "%s (%d calls, ok %s, %.1f wall-h)" % (fmt_num(calls["per_day"]), calls["calls"], fmt_share(calls["ok_rate"]), calls["wall_hours"]),
        )
    )
    for lane, lane_stats in metrics["model_calls"]["per_lane"].items():
        rows.append(
            (
                "  lane %s" % lane,
                "%d calls, ok %d (%s), %.1f wall-h, %s/day"
                % (lane_stats["calls"], lane_stats["ok"], fmt_share(lane_stats["ok_rate"]), lane_stats["wall_hours"], fmt_num(lane_stats["per_day"])),
            )
        )
    skipped = metrics["cycle_skipped"]
    rows.append(
        (
            "cycle_skipped/week",
            "%s (%d rows) by gate: %s"
            % (fmt_num(skipped["per_week"]), skipped["rows_in_window"], ", ".join("%s=%d" % item for item in skipped["by_gate"].items()) or "none"),
        )
    )
    errors = metrics["daemon_error"]
    rows.append(("daemon_error/day", "%s (%d rows)" % (fmt_num(errors["per_day"]), errors["rows_in_window"])))
    disk = metrics["disk"]
    rows.append(("disk free", "%s GiB of %s GiB at %s" % (disk.get("free_gib"), disk.get("total_gib"), disk.get("path"))))
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        lines.append("%s  %s" % (label.ljust(width), value))
    lines.append("")
    lines.append("daemon message kinds/day:")
    for kind, value in dm["by_kind_per_day"].items():
        lines.append("  %-36s %s" % (kind, fmt_num(value)))
    lines.append("")
    lines.append("top %d llama.cpp operations by wall time:" % TOP_OPERATIONS)
    lines.append("  %-52s %6s %6s %7s %8s" % ("operation", "calls", "ok", "ok%", "wall-h"))
    for op in metrics["model_calls"]["per_operation_top_by_wall"]:
        lines.append(
            "  %-52s %6d %6d %7s %8.2f" % (op["operation"][:52], op["calls"], op["ok"], fmt_share(op["ok_rate"]), op["wall_hours"])
        )
    spine = metrics["model_calls"]["spine"]
    lines.append(
        "  (perf spine source: %s; wal sidecar present: %s%s)"
        % (
            spine.get("source") or "none",
            spine.get("wal_sidecar_present"),
            ("; errors: " + " | ".join(spine["errors"])) if spine.get("errors") else "",
        )
    )
    return "\n".join(lines)


def default_eve_dir() -> Path:
    env = os.environ.get("EVE_LOOP_METRICS_EVE_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / ".eve"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only loop metrics for Eve (program section 9).")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="print the full metrics document as JSON (default)")
    mode.add_argument("--table", action="store_true", help="print a human-readable summary table")
    parser.add_argument("--days", type=float, default=DEFAULT_DAYS, help="window length in days (default %d)" % DEFAULT_DAYS)
    parser.add_argument("--eve-dir", type=Path, default=None, help="path to the .eve directory (default: repo/.eve)")
    parser.add_argument("--now", default=None, help="ISO timestamp for the window end (default: now, UTC)")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    now = None
    if args.now:
        now = parse_ts(args.now)
        if now is None:
            print("Could not parse --now %r" % args.now, file=sys.stderr)
            return 2
    eve_dir = args.eve_dir or default_eve_dir()
    metrics = compute_metrics(eve_dir, days=args.days, now=now)
    if args.table:
        print(render_table(metrics))
    else:
        print(json.dumps(metrics, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
