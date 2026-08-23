#!/usr/bin/env python3

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


STALE_STATE_HOURS = 24
LEDGER_STALE_MINUTES = 10
TIMESTAMP_MISMATCH_MINUTES = 60
SYNTHETIC_PROMPT_MARKERS = (
    "what is the next grounded runtime step here",
    "next grounded runtime step",
    "what is the next grounded step here",
)
DEFAULT_RUNTIME_EVE_DIR = Path.home() / ".eve_runtime" / ".eve"
STATE_SOURCE_FILES = (
    "messages.jsonl",
    "conversation_spine.jsonl",
    "experience_events.jsonl",
    "reply_turn_replays.jsonl",
    "reply_council_turns.jsonl",
    "event_ledger.jsonl",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def minutes_between(later: datetime, earlier: datetime) -> float:
    return (later - earlier).total_seconds() / 60.0


def compact_text(value: Any, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def file_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def latest_state_mtime(eve_dir: Path) -> float:
    return max((file_mtime(eve_dir / name) for name in STATE_SOURCE_FILES), default=0.0)


def jsonl_has_records(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with path.open("r", encoding="utf-8") as handle:
            return any(bool(line.strip()) for line in handle)
    except OSError:
        return False


def select_analysis_eve_dir(requested_eve_dir: Path, state_source: str) -> tuple[Path, str, Dict[str, Any]]:
    requested = requested_eve_dir.expanduser()
    runtime = DEFAULT_RUNTIME_EVE_DIR
    if state_source == "source":
        return requested, "source", {"requested_eve_dir": str(requested), "runtime_eve_dir": str(runtime)}
    if state_source == "runtime":
        selected = runtime if runtime.exists() else requested
        source = "runtime" if selected == runtime else "source_runtime_missing"
        return selected, source, {"requested_eve_dir": str(requested), "runtime_eve_dir": str(runtime)}
    requested_latest = latest_state_mtime(requested)
    runtime_latest = latest_state_mtime(runtime)
    requested_has_spine = jsonl_has_records(requested / "conversation_spine.jsonl")
    runtime_has_spine = jsonl_has_records(runtime / "conversation_spine.jsonl")
    if runtime.exists() and runtime_has_spine and not requested_has_spine:
        return runtime, "runtime_auto_has_spine", {
            "requested_eve_dir": str(requested),
            "runtime_eve_dir": str(runtime),
            "requested_latest_mtime": requested_latest,
            "runtime_latest_mtime": runtime_latest,
            "requested_has_conversation_spine": requested_has_spine,
            "runtime_has_conversation_spine": runtime_has_spine,
        }
    if runtime.exists() and runtime_latest >= requested_latest and runtime_latest > 0:
        return runtime, "runtime_auto_newer", {
            "requested_eve_dir": str(requested),
            "runtime_eve_dir": str(runtime),
            "requested_latest_mtime": requested_latest,
            "runtime_latest_mtime": runtime_latest,
        }
    return requested, "source_auto", {
        "requested_eve_dir": str(requested),
        "runtime_eve_dir": str(runtime),
        "requested_latest_mtime": requested_latest,
        "runtime_latest_mtime": runtime_latest,
    }


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_jsonl(path: Path, *, limit: int = 0) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    records.append(payload)
    except OSError:
        return []
    if limit > 0:
        return records[-limit:]
    return records


def record_is_synthetic(record: Dict[str, Any]) -> bool:
    if record.get("synthetic") is True:
        return True
    source = str(record.get("source") or "").lower()
    if any(token in source for token in ("synthetic", "fixture", "eval", "probe", "test")):
        return True
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    if metadata.get("synthetic") is True or metadata.get("is_synthetic") is True:
        return True
    inbound = compact_text(record.get("inbound_preview"), limit=320).lower()
    contract = record.get("turn_contract") if isinstance(record.get("turn_contract"), dict) else {}
    latest = compact_text(contract.get("latest_message"), limit=320).lower()
    has_marker = any(marker in text for text in (inbound, latest) for marker in SYNTHETIC_PROMPT_MARKERS if text)
    if has_marker and (
        str(record.get("source_message_id") or "") in {"msg-1", "message-1"}
        or str(record.get("thread_id") or "") == "thread-1"
    ):
        return True
    return False


def latest_by_timestamp(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    latest: Dict[str, Any] = {}
    latest_ts: Optional[datetime] = None
    for record in records:
        timestamp = first_timestamp(record)
        if not timestamp:
            continue
        if latest_ts is None or timestamp > latest_ts:
            latest = record
            latest_ts = timestamp
    return latest


def first_timestamp(record: Dict[str, Any]) -> Optional[datetime]:
    for key in ("timestamp", "created_at", "updated_at", "generated_at", "finished_at", "started_at"):
        timestamp = parse_timestamp(record.get(key))
        if timestamp:
            return timestamp
    return None


def state_timestamp(record: Dict[str, Any]) -> Optional[datetime]:
    for key in ("updated_at", "generated_at", "timestamp", "created_at"):
        timestamp = parse_timestamp(record.get(key))
        if timestamp:
            return timestamp
    return None


def add_finding(
    findings: List[Dict[str, Any]],
    *,
    finding_id: str,
    severity: str,
    summary: str,
    evidence: Dict[str, Any],
    recommendation: str,
) -> None:
    findings.append(
        {
            "id": finding_id,
            "severity": severity,
            "summary": summary,
            "evidence": evidence,
            "recommendation": recommendation,
        }
    )


def latest_user_signal(experience_events: List[Dict[str, Any]], event_ledger: List[Dict[str, Any]]) -> Dict[str, Any]:
    candidates = [
        record
        for record in experience_events
        if record.get("event_type") == "user_signal" or record.get("metadata", {}).get("kind") == "user_message"
    ]
    candidates.extend(
        record
        for record in event_ledger
        if record.get("type") == "UserMessageEvent"
        or record.get("event_type") == "user_signal"
        or record.get("payload", {}).get("kind") == "user_message"
    )
    return latest_by_timestamp(candidates)


def user_signal_text(record: Dict[str, Any]) -> str:
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    for value in (
        record.get("summary"),
        payload.get("text"),
        payload.get("summary"),
        metadata.get("body"),
        metadata.get("text"),
    ):
        text = compact_text(value)
        if text:
            return text
    return ""


def latest_visible_reply_for_user(
    latest_user: Dict[str, Any],
    *,
    messages: List[Dict[str, Any]],
    conversation_spine: List[Dict[str, Any]],
) -> Dict[str, Any]:
    metadata = latest_user.get("metadata") if isinstance(latest_user.get("metadata"), dict) else {}
    message_id = str(metadata.get("message_id") or "").strip()
    thread_id = str(metadata.get("thread_id") or "").strip()
    latest_user_ts = first_timestamp(latest_user)
    candidates: List[Dict[str, Any]] = []
    for record in messages:
        if str(record.get("sender") or "").lower() != "eve":
            continue
        if str(record.get("recipient") or "").lower() != "user":
            continue
        if message_id and str(record.get("reply_to") or "") == message_id:
            candidates.append(record)
            continue
        if thread_id and str(record.get("thread_id") or "") == thread_id:
            record_ts = first_timestamp(record)
            if latest_user_ts and record_ts and record_ts >= latest_user_ts:
                candidates.append(record)
    for record in conversation_spine:
        if record_is_synthetic(record):
            continue
        if str(record.get("direction") or "").lower() != "outbound":
            continue
        if str(record.get("role") or "").lower() not in {"assistant", "eve"}:
            continue
        if message_id and str(record.get("reply_to") or "") == message_id:
            candidates.append(record)
            continue
        if thread_id and str(record.get("thread_id") or "") == thread_id:
            record_ts = first_timestamp(record)
            if latest_user_ts and record_ts and record_ts >= latest_user_ts:
                candidates.append(record)
    return latest_by_timestamp(candidates)


def reply_body_preview(record: Dict[str, Any]) -> str:
    return compact_text(record.get("body") or record.get("body_preview") or record.get("summary"))


def analyze_reply_replays(
    *,
    findings: List[Dict[str, Any]],
    latest_user: Dict[str, Any],
    messages: List[Dict[str, Any]],
    conversation_spine: List[Dict[str, Any]],
    reply_replays: List[Dict[str, Any]],
    council_turns: List[Dict[str, Any]],
) -> None:
    latest_user_text = user_signal_text(latest_user).strip()
    real_reply_replays = [record for record in reply_replays if not record_is_synthetic(record)]
    synthetic_reply_replays = [record for record in reply_replays if record_is_synthetic(record)]
    latest_replay = latest_by_timestamp(real_reply_replays)
    latest_synthetic_replay = latest_by_timestamp(synthetic_reply_replays)
    latest_visible_reply = latest_visible_reply_for_user(
        latest_user,
        messages=messages,
        conversation_spine=conversation_spine,
    )
    latest_user_ts = first_timestamp(latest_user)
    latest_visible_reply_ts = first_timestamp(latest_visible_reply)
    if latest_synthetic_replay and not latest_replay:
        add_finding(
            findings,
            finding_id="only_synthetic_reply_replays_available",
            severity="medium",
            summary="The replay ledger contains synthetic turns but no current real reply replay to compare.",
            evidence={
                "latest_synthetic_inbound": compact_text(latest_synthetic_replay.get("inbound_preview")),
                "latest_synthetic_at": (
                    first_timestamp(latest_synthetic_replay).isoformat()
                    if first_timestamp(latest_synthetic_replay)
                    else ""
                ),
            },
            recommendation="Run a real conversation turn after the runtime patch so Eve can record a non-synthetic replay.",
        )
    if not latest_replay:
        if latest_visible_reply:
            add_finding(
                findings,
                finding_id="reply_replay_missing_for_latest_visible_reply",
                severity="medium",
                summary="The latest user signal has a visible reply, but reply replay instrumentation did not record it.",
                evidence={
                    "latest_user_signal": latest_user_text,
                    "latest_user_at": latest_user_ts.isoformat() if latest_user_ts else "",
                    "latest_visible_reply_at": latest_visible_reply_ts.isoformat() if latest_visible_reply_ts else "",
                    "latest_visible_reply": reply_body_preview(latest_visible_reply),
                    "reply_message_id": latest_visible_reply.get("id") or latest_visible_reply.get("message_id") or "",
                },
                recommendation=(
                    "Keep the visible reply as the live conversation truth, but wire manual/fallback reply paths "
                    "through reply replay so model/layer attribution remains complete."
                ),
            )
        return
    inbound = compact_text(latest_replay.get("inbound_preview"))
    inbound_lower = inbound.lower()
    latest_replay_ts = first_timestamp(latest_replay)
    if latest_user_text and inbound and latest_user_text.lower() != inbound_lower:
        if latest_visible_reply and latest_visible_reply_ts and (not latest_replay_ts or latest_visible_reply_ts > latest_replay_ts):
            add_finding(
                findings,
                finding_id="reply_replay_lagging_latest_visible_reply",
                severity="medium",
                summary="The latest user signal has a newer visible reply than the latest reply replay.",
                evidence={
                    "latest_user_signal": latest_user_text,
                    "latest_user_at": latest_user_ts.isoformat() if latest_user_ts else "",
                    "latest_replay_inbound": inbound,
                    "latest_replay_at": latest_replay_ts.isoformat() if latest_replay_ts else "",
                    "latest_visible_reply_at": latest_visible_reply_ts.isoformat(),
                    "latest_visible_reply": reply_body_preview(latest_visible_reply),
                },
                recommendation=(
                    "Treat the visible reply as live truth and repair replay instrumentation so manual/fallback "
                    "answers keep attribution, traces, and training exclusions complete."
                ),
            )
            return
        add_finding(
            findings,
            finding_id="reply_replay_not_grounded_to_latest_user_signal",
            severity="high",
            summary="Latest reply replay is not using the latest user signal as its inbound turn.",
            evidence={
                "latest_user_signal": latest_user_text,
                "latest_user_at": latest_user_ts.isoformat() if latest_user_ts else "",
                "latest_replay_inbound": inbound,
                "latest_replay_at": latest_replay_ts.isoformat() if latest_replay_ts else "",
                "reply_preview": compact_text(latest_replay.get("reply_preview")),
            },
            recommendation=(
                "Route reply construction from the authoritative latest user message, and mark replay/test prompts "
                "as synthetic so they cannot overwrite live conversation state."
            ),
        )
    if any(marker in inbound_lower for marker in SYNTHETIC_PROMPT_MARKERS) and not record_is_synthetic(latest_replay):
        add_finding(
            findings,
            finding_id="synthetic_prompt_contamination",
            severity="high",
            summary="A synthetic runtime-step prompt appears in the live reply replay path.",
            evidence={
                "inbound_preview": inbound,
                "turn_contract_latest_message": compact_text(
                    (latest_replay.get("turn_contract") or {}).get("latest_message")
                ),
                "source_message_id": latest_replay.get("source_message_id") or "",
            },
            recommendation=(
                "Keep synthetic probes in a separate eval namespace and block them from relationship memory, "
                "active thread selection, and user-facing replay ledgers."
            ),
        )
    recent_inbounds = [compact_text(record.get("inbound_preview")) for record in real_reply_replays[-12:]]
    repeated = Counter(item for item in recent_inbounds if item)
    repeated_prompt, repeated_count = repeated.most_common(1)[0] if repeated else ("", 0)
    if repeated_count >= 3:
        latest_inbound = compact_text(latest_replay.get("inbound_preview"))
        current_repetition = bool(latest_inbound and repeated_prompt == latest_inbound)
        add_finding(
            findings,
            finding_id="reply_replay_repetition_loop",
            severity="medium" if current_repetition else "low",
            summary=(
                "Recent reply replays are still repeating the current inbound prompt."
                if current_repetition
                else "Older recent reply replays repeated the same inbound prompt, but the latest replay has moved on."
            ),
            evidence={
                "prompt": repeated_prompt,
                "latest_replay_inbound": latest_inbound,
                "recent_count": repeated_count,
                "window": min(len(reply_replays), 12),
                "current_repetition": current_repetition,
            },
            recommendation=(
                "Add a replay-loop guard: repeated identical inbound previews should trigger stale-state refresh "
                "or short-circuit to an explicit continuation resolver."
            ),
        )
    real_council_turns = [record for record in council_turns if not record_is_synthetic(record)]
    latest_council = latest_by_timestamp(real_council_turns)
    if (
        latest_council
        and not latest_council.get("active_lanes")
        and latest_council.get("reply_preview")
        and not latest_council.get("lane_backed")
        and latest_council.get("fallback_label") != "fast_direct_answer"
    ):
        add_finding(
            findings,
            finding_id="all_lanes_abstained_but_reply_synthesized",
            severity="high",
            summary="The council synthesized a reply even though every lane abstained.",
            evidence={
                "used_model": latest_council.get("used_model") or "",
                "synthesis_model": latest_council.get("synthesis_model") or "",
                "reason": latest_council.get("reason") or "",
                "active_lanes": latest_council.get("active_lanes") or [],
                "abstained_lanes": latest_council.get("abstained_lanes") or [],
            },
            recommendation=(
                "If all lanes abstain, record an honest fallback and answer only from the actual latest turn, "
                "or require one lane to cross admission before council synthesis is counted as lane-backed behavior."
            ),
        )


def analyze_ledgers(
    *,
    findings: List[Dict[str, Any]],
    eve_dir: Path,
    latest_user: Dict[str, Any],
    messages: List[Dict[str, Any]],
) -> None:
    latest_user_ts = first_timestamp(latest_user)
    latest_message = latest_by_timestamp(messages)
    latest_message_ts = first_timestamp(latest_message)
    if latest_user_ts and latest_message_ts and minutes_between(latest_user_ts, latest_message_ts) > LEDGER_STALE_MINUTES:
        add_finding(
            findings,
            finding_id="canonical_message_ledger_stale",
            severity="high",
            summary="The message ledger is older than the latest user signal.",
            evidence={
                "messages_jsonl": str(eve_dir / "messages.jsonl"),
                "latest_message_at": latest_message_ts.isoformat(),
                "latest_user_signal_at": latest_user_ts.isoformat(),
                "lag_minutes": round(minutes_between(latest_user_ts, latest_message_ts), 1),
            },
            recommendation=(
                "Choose one authoritative conversation ledger and ensure every real inbound/outbound turn writes there "
                "before relationship memory, active mind, or reply replay consume it."
            ),
        )


def analyze_state_freshness(
    *,
    findings: List[Dict[str, Any]],
    eve_dir: Path,
    latest_user: Dict[str, Any],
) -> None:
    latest_user_ts = first_timestamp(latest_user)
    if not latest_user_ts:
        return
    for name in ("relationship_model.json", "human_context.json", "active_mind.json", "global_workspace.json"):
        path = eve_dir / name
        payload = read_json(path)
        timestamp = state_timestamp(payload)
        if not timestamp:
            continue
        age_hours = minutes_between(latest_user_ts, timestamp) / 60.0
        if age_hours > STALE_STATE_HOURS:
            add_finding(
                findings,
                finding_id=f"stale_state_{name.replace('.json', '')}",
                severity="medium",
                summary=f"{name} is stale compared with the latest user signal.",
                evidence={
                    "path": str(path),
                    "state_timestamp": timestamp.isoformat(),
                    "latest_user_signal_at": latest_user_ts.isoformat(),
                    "age_hours": round(age_hours, 2),
                },
                recommendation=(
                    "Refresh this state before reply construction or exclude it from the turn prompt as historical context."
                ),
            )


def analyze_timestamp_mismatches(
    *,
    findings: List[Dict[str, Any]],
    presence_cycles: List[Dict[str, Any]],
    event_ledger: List[Dict[str, Any]],
) -> None:
    mismatches: List[Dict[str, Any]] = []
    latest_checked: Dict[str, datetime] = {}
    for record in presence_cycles[-20:]:
        outer = parse_timestamp(record.get("timestamp"))
        generated = parse_timestamp((record.get("presence_after") or {}).get("generated_at")) or parse_timestamp(
            (record.get("presence_before") or {}).get("generated_at")
        )
        if outer:
            latest_checked["presence_cycles"] = max(latest_checked.get("presence_cycles", outer), outer)
        if outer and generated and abs(minutes_between(outer, generated)) > TIMESTAMP_MISMATCH_MINUTES:
            mismatches.append(
                {
                    "key": "presence_cycles",
                    "_outer_dt": outer,
                    "source": "presence_cycles",
                    "id": record.get("id") or "",
                    "outer_timestamp": outer.isoformat(),
                    "inner_timestamp": generated.isoformat(),
                }
            )
    for record in event_ledger[-80:]:
        if record.get("type") not in {"PresenceCycleEvent", "PresencePulseEvent", "OrganPulseEvent"}:
            continue
        outer = parse_timestamp(record.get("timestamp"))
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        inner = parse_timestamp(payload.get("timestamp")) or parse_timestamp(payload.get("generated_at"))
        key = f"event_ledger:{record.get('type') or ''}"
        if outer:
            latest_checked[key] = max(latest_checked.get(key, outer), outer)
        if outer and inner and abs(minutes_between(outer, inner)) > TIMESTAMP_MISMATCH_MINUTES:
            mismatches.append(
                {
                    "key": key,
                    "_outer_dt": outer,
                    "source": "event_ledger",
                    "id": record.get("id") or "",
                    "type": record.get("type") or "",
                    "outer_timestamp": outer.isoformat(),
                    "inner_timestamp": inner.isoformat(),
                }
            )
    if mismatches:
        current_mismatches = [
            item
            for item in mismatches
            if item.get("_outer_dt") == latest_checked.get(str(item.get("key") or ""))
        ]
        severity = "high" if current_mismatches else "low"
        finding_id = (
            "runtime_timestamp_provenance_mismatch"
            if current_mismatches
            else "historical_runtime_timestamp_provenance_mismatch"
        )
        examples = current_mismatches[:6] if current_mismatches else mismatches[:6]
        clean_examples = [
            {key: value for key, value in item.items() if not key.startswith("_") and key != "key"}
            for item in examples
        ]
        add_finding(
            findings,
            finding_id=finding_id,
            severity=severity,
            summary=(
                "Latest runtime evidence contains mismatched outer and payload timestamps."
                if current_mismatches
                else "Historical runtime evidence contains mismatched outer and payload timestamps."
            ),
            evidence={"examples": clean_examples, "count": len(mismatches), "current_count": len(current_mismatches)},
            recommendation=(
                "Enforce timestamp invariants when recording presence/organ events: event timestamp, payload timestamp, "
                "provenance timestamp, and append order should describe the same run. Historical-only mismatches are "
                "kept as low-severity provenance debt so old repaired records do not keep the live loop in watch."
            ),
        )


def analyze_reply_progress(findings: List[Dict[str, Any]], reply_progress: Dict[str, Any]) -> None:
    jobs = reply_progress.get("jobs") if isinstance(reply_progress.get("jobs"), list) else []
    if not jobs:
        return
    latest = jobs[-1] if isinstance(jobs[-1], dict) else {}
    notes = latest.get("notes") if isinstance(latest.get("notes"), list) else []
    timestamps = {note.get("timestamp") for note in notes if isinstance(note, dict) and note.get("timestamp")}
    if latest.get("status") == "completed" and len(notes) >= 5 and len(timestamps) <= 1:
        add_finding(
            findings,
            finding_id="reply_progress_zero_duration_theater",
            severity="medium",
            summary="Reply progress shows many phases completing at the same timestamp.",
            evidence={
                "job_id": latest.get("id") or "",
                "started_at": latest.get("started_at") or "",
                "finished_at": latest.get("finished_at") or "",
                "note_count": len(notes),
                "unique_note_timestamps": len(timestamps),
            },
            recommendation=(
                "Show only real elapsed phases, or collapse zero-duration progress into a single honest reply-ready event."
            ),
        )


def build_report(
    eve_dir: Path,
    *,
    state_source: str = "source",
    selection: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    messages = read_jsonl(eve_dir / "messages.jsonl")
    conversation_spine = read_jsonl(eve_dir / "conversation_spine.jsonl")
    reply_replays = read_jsonl(eve_dir / "reply_turn_replays.jsonl")
    council_turns = read_jsonl(eve_dir / "reply_council_turns.jsonl")
    experiences = read_jsonl(eve_dir / "experience_events.jsonl")
    presence_cycles = read_jsonl(eve_dir / "presence_cycles.jsonl")
    event_ledger = read_jsonl(eve_dir / "event_ledger.jsonl")
    reply_progress = read_json(eve_dir / "reply_progress.json")

    findings: List[Dict[str, Any]] = []
    latest_user = latest_user_signal(experiences, event_ledger)
    analyze_ledgers(findings=findings, eve_dir=eve_dir, latest_user=latest_user, messages=messages)
    analyze_reply_replays(
        findings=findings,
        latest_user=latest_user,
        messages=messages,
        conversation_spine=conversation_spine,
        reply_replays=reply_replays,
        council_turns=council_turns,
    )
    analyze_state_freshness(findings=findings, eve_dir=eve_dir, latest_user=latest_user)
    analyze_timestamp_mismatches(findings=findings, presence_cycles=presence_cycles, event_ledger=event_ledger)
    analyze_reply_progress(findings, reply_progress)

    severity_counts = Counter(str(finding["severity"]) for finding in findings)
    status = "passed"
    if severity_counts.get("high"):
        status = "degraded"
    elif severity_counts.get("medium"):
        status = "watch"
    latest_user_ts = first_timestamp(latest_user)
    return {
        "schema_id": "eve_conversation_spine_audit.v1",
        "generated_at": utc_now(),
        "status": status,
        "state_source": state_source,
        "eve_dir": str(eve_dir),
        "selection": selection or {},
        "summary": {
            "latest_user_signal_at": latest_user_ts.isoformat() if latest_user_ts else "",
            "latest_user_signal": user_signal_text(latest_user),
            "messages": len(messages),
            "conversation_spine_turns": len(conversation_spine),
            "reply_replays": len(reply_replays),
            "reply_council_turns": len(council_turns),
            "experience_events": len(experiences),
            "presence_cycles": len(presence_cycles),
            "event_ledger_events": len(event_ledger),
        },
        "severity_counts": dict(severity_counts),
        "findings": findings,
        "next_actions": [
            "Keep Eve Monitor and /api/conversation-spine under regression test so live/open/active turns stay visible without inferring from older stores.",
            "Backfill, quarantine, or explicitly ignore the historical timestamp-mismatch events; current writes should stay guarded.",
            "Use the OpenInference JSONL exporter as the local trace handoff; send it to Phoenix/Langfuse only after the local export stays clean.",
            "Use the curated training/eval dataset in shadow adapter/router tests; keep reply-generation failures and unreviewed failed replays out of training.",
            "Keep hidden probes outside Eve-readable state and preserve private holdout tests for evaluator drift.",
        ],
        "oss_adoption_targets": [
            {"layer": "trace_provenance", "candidate": "OpenTelemetry/OpenInference"},
            {"layer": "trace_ui_and_evals", "candidate": "Phoenix or Langfuse"},
            {"layer": "conversation_workflow", "candidate": "Eve-native first; LangGraph lab adapter after trace history"},
            {"layer": "dataset_versioning", "candidate": "DVC after curated dataset volume grows"},
            {"layer": "adapter_training", "candidate": "PEFT/Axolotl/LLaMA-Factory after shadow and holdout gates pass"},
        ],
    }


def write_report(report: Dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def print_report(report: Dict[str, Any]) -> None:
    print(f"Eve conversation spine audit: {report['status']}")
    summary = report["summary"]
    print(f"state_source: {report.get('state_source') or 'source'} {report.get('eve_dir') or ''}")
    print(f"latest_user_signal: {summary.get('latest_user_signal_at') or 'unknown'} {summary.get('latest_user_signal') or ''}")
    print(f"findings: {len(report['findings'])} {report['severity_counts']}")
    for finding in report["findings"]:
        print(f"- [{finding['severity']}] {finding['id']}: {finding['summary']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit Eve's live conversation spine for grounding and provenance drift.")
    parser.add_argument("--eve-dir", default=".eve", help="Path to Eve runtime state directory.")
    parser.add_argument(
        "--state-source",
        choices=["auto", "source", "runtime"],
        default="auto",
        help="Choose source .eve, runtime ~/.eve_runtime/.eve, or whichever state is freshest.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output JSON path. Defaults to <eve-dir>/oss_improvement/latest_conversation_spine_audit.json.",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON report to stdout.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    requested_eve_dir = Path(args.eve_dir).expanduser()
    eve_dir, state_source, selection = select_analysis_eve_dir(requested_eve_dir, args.state_source)
    output = Path(args.output).expanduser() if args.output else eve_dir / "oss_improvement" / "latest_conversation_spine_audit.json"
    report = build_report(eve_dir, state_source=state_source, selection=selection)
    write_report(report, output)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True))
    else:
        print_report(report)
        print(f"report: {output}")
    return 0 if report["status"] in {"passed", "watch", "degraded"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
