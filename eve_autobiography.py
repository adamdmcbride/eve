"""Temporal, source-grounded autobiographical continuity for Eve.

This module projects Eve's existing relationship episodes into an ordered
event-and-change model.  It does not create a second transcript and it does not
turn Eve-authored prose into observation.  A self-change is eligible only when
the episode has external correction lineage, a verified action consequence, or
an explicitly verified change record.

The projection is a functional memory/control mechanism.  It is not evidence
of phenomenal recollection, a human narrative self, or consciousness.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


SCHEMA_VERSION = "eve.autobiographical_continuity.v1"
EVENT_SCHEMA_VERSION = "eve.autobiographical_event.v1"
CHANGE_SCHEMA_VERSION = "eve.autobiographical_self_change.v1"
MAX_EVENTS = 64
MAX_CHANGES = 24
MAX_TRAJECTORIES = 16

BOUNDARY = (
    "This projection preserves source-grounded event and operational self-change "
    "lineage. It does not establish phenomenal recollection, private mental state, "
    "a human narrative self, or consciousness."
)

_STOPWORDS = {
    "and",
    "about",
    "after",
    "again",
    "also",
    "because",
    "before",
    "could",
    "eve",
    "from",
    "has",
    "have",
    "into",
    "just",
    "more",
    "not",
    "only",
    "should",
    "that",
    "the",
    "their",
    "there",
    "these",
    "they",
    "this",
    "through",
    "was",
    "were",
    "user",
    "what",
    "when",
    "where",
    "which",
    "with",
    "would",
    "your",
}


def _text(value: object, limit: int = 320) -> str:
    return " ".join(str(value or "").split())[:limit]


def _timestamp(value: object = None) -> str:
    text = _text(value, 80)
    if not text:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _parsed_time(value: object) -> Optional[datetime]:
    text = _text(value, 80)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _stable_id(prefix: str, *parts: object) -> str:
    material = "|".join(_text(part, 500) for part in parts)
    return f"{prefix}-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]


def _digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _unique_text(values: object, *, limit: int, text_limit: int = 160) -> List[str]:
    source = values if isinstance(values, list) else []
    result: List[str] = []
    seen = set()
    for value in source:
        text = _text(value, text_limit)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _tokens(value: object) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", _text(value, 1600).lower())
        if len(token) > 2 and token not in _STOPWORDS
    }


def _source_class(payload: Mapping[str, object]) -> Tuple[str, str, bool]:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    source = _text(payload.get("source"), 100).lower()
    evidence_ids = _unique_text(payload.get("evidence_ids"), limit=20)
    correction_ids = _unique_text(payload.get("correction_ids"), limit=20)
    synthetic = bool(
        payload.get("synthetic")
        or metadata.get("synthetic")
        or metadata.get("evaluation")
        or any(marker in source for marker in ("synthetic", "evaluator", "private_probe"))
    )
    self_output = bool(
        metadata.get("self_output")
        or metadata.get("source_kind") == "self_output"
        or "self_output" in source
    )
    if synthetic:
        return "synthetic", "excluded_synthetic", False
    if self_output:
        return "self_output", "excluded_self_output", False
    verified_presence = bool(
        metadata.get("source_presence_cycle_id")
        and metadata.get("verification_ok") is True
        and metadata.get("action_matched_contract") is True
    )
    if verified_presence:
        return "verified_action_consequence", "verified_action_consequence", True
    if correction_ids or metadata.get("user_correction_id"):
        return "external_correction", "explicit_external_correction", True
    if metadata.get("change_verified") is True and evidence_ids:
        return "verified_external_change", "explicit_verified_change", True
    if evidence_ids and metadata.get("source_message_id"):
        return "external_exchange", "source_message_lineage", True
    if evidence_ids:
        return "grounded_event", "bounded_evidence_lineage", True
    return "unverified", "missing_external_or_verified_lineage", False


def _normalize_event(payload: object) -> Optional[Dict[str, object]]:
    if not isinstance(payload, Mapping):
        return None
    source_class, authority, grounded = _source_class(payload)
    if not grounded:
        return None
    happened = _text(payload.get("what_happened"), 500)
    occurred_at = _timestamp(payload.get("created_at") or payload.get("updated_at"))
    if not happened:
        return None
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    evidence_ids = _unique_text(payload.get("evidence_ids"), limit=20)
    correction_ids = _unique_text(payload.get("correction_ids"), limit=20)
    episode_id = _text(payload.get("id"), 100) or _stable_id(
        "episode",
        occurred_at,
        payload.get("thread_id"),
        happened,
        evidence_ids,
        correction_ids,
    )
    changed = _text(payload.get("what_changed_afterward"), 500)
    change_eligible = bool(
        changed
        and source_class
        in {
            "verified_action_consequence",
            "external_correction",
            "verified_external_change",
        }
    )
    if source_class == "verified_action_consequence":
        change_kind = "verified_action_learning"
        change_strength = "verified"
        change_status = "verified"
    elif source_class == "external_correction":
        change_kind = "correction_driven_revision"
        change_strength = "observed_external_feedback"
        change_status = "revision_required"
    elif source_class == "verified_external_change":
        change_kind = "verified_explicit_revision"
        change_strength = "verified"
        change_status = "verified"
    else:
        change_kind = "event_without_self_change"
        change_strength = "none"
        change_status = "none"
    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "episode_id": episode_id,
        "occurred_at": occurred_at,
        "thread_id": _text(payload.get("thread_id"), 120) or "unthreaded",
        "source": _text(payload.get("source"), 100) or "unknown",
        "source_class": source_class,
        "source_authority": authority,
        "what_happened": happened,
        "recorded_user_priority": _text(payload.get("what_user_cared_about"), 500),
        "observed_error": _text(payload.get("what_eve_got_wrong"), 500),
        "explicit_change": changed,
        "change_eligible": change_eligible,
        "change_kind": change_kind,
        "change_strength": change_strength,
        "change_status": change_status,
        "evidence_ids": evidence_ids,
        "correction_ids": correction_ids,
        "source_message_id": _text(metadata.get("source_message_id"), 120),
        "reply_message_id": _text(metadata.get("reply_message_id"), 120),
        "source_presence_cycle_id": _text(metadata.get("source_presence_cycle_id"), 120),
        "grounded": True,
        "self_output_used_as_observation": False,
        "private_mental_state_inferred": False,
        "content_sha256": hashlib.sha256(happened.encode("utf-8")).hexdigest(),
    }


def _boundary_reason(previous: Optional[Mapping[str, object]], current: Mapping[str, object]) -> str:
    if previous is None:
        return "trajectory_start"
    if previous.get("source_class") != current.get("source_class"):
        return "source_class_change"
    before = _parsed_time(previous.get("occurred_at"))
    after = _parsed_time(current.get("occurred_at"))
    if before is not None and after is not None and (after - before).total_seconds() > 21600:
        return "context_gap_over_six_hours"
    if current.get("change_eligible"):
        return "explicit_change_record"
    return "continuous_context"


def _build_temporal_projection(
    episodes: Sequence[Mapping[str, object]],
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]]]:
    events = [item for item in (_normalize_event(raw) for raw in episodes) if item is not None]
    deduped: Dict[str, Dict[str, object]] = {}
    for event in events:
        deduped[str(event["episode_id"])] = event
    events = sorted(
        deduped.values(),
        key=lambda item: (str(item.get("occurred_at") or ""), str(item.get("episode_id") or "")),
    )[-MAX_EVENTS:]
    previous_by_thread: Dict[str, Dict[str, object]] = {}
    previous_change_by_thread: Dict[str, str] = {}
    changes: List[Dict[str, object]] = []
    grouped: Dict[str, List[Dict[str, object]]] = {}
    for global_index, event in enumerate(events, start=1):
        thread_id = str(event.get("thread_id") or "unthreaded")
        previous = previous_by_thread.get(thread_id)
        event["global_sequence"] = global_index
        event["trajectory_sequence"] = len(grouped.get(thread_id, [])) + 1
        event["previous_episode_id"] = str(previous.get("episode_id") or "") if previous else ""
        event["boundary_reason"] = _boundary_reason(previous, event)
        event["event_boundary"] = event["boundary_reason"] != "continuous_context"
        grouped.setdefault(thread_id, []).append(event)
        if event.get("change_eligible"):
            change_id = _stable_id("self-change", event["episode_id"], event["explicit_change"])
            change = {
                "schema_version": CHANGE_SCHEMA_VERSION,
                "change_id": change_id,
                "episode_id": event["episode_id"],
                "occurred_at": event["occurred_at"],
                "thread_id": thread_id,
                "sequence": len(changes) + 1,
                "previous_episode_id": event["previous_episode_id"],
                "previous_change_id": previous_change_by_thread.get(thread_id, ""),
                "change_kind": event["change_kind"],
                "change_strength": event["change_strength"],
                "change_status": event["change_status"],
                "observed_error": event["observed_error"],
                "change_directive": event["explicit_change"],
                "recorded_priority": event["recorded_user_priority"],
                "source_authority": event["source_authority"],
                "evidence_ids": copy.deepcopy(event["evidence_ids"]),
                "correction_ids": copy.deepcopy(event["correction_ids"]),
                "causal_link_basis": event["source_authority"],
                "chronology_alone_treated_as_causation": False,
                "self_output_used_as_observation": False,
                "private_mental_state_inferred": False,
            }
            changes.append(change)
            previous_change_by_thread[thread_id] = change_id
            event["change_id"] = change_id
        else:
            event["change_id"] = ""
        previous_by_thread[thread_id] = event
    trajectories: List[Dict[str, object]] = []
    for thread_id, items in grouped.items():
        trajectory_changes = [item["change_id"] for item in items if item.get("change_id")]
        trajectories.append(
            {
                "trajectory_id": _stable_id("autobiography", thread_id, items[0]["episode_id"]),
                "thread_id": thread_id,
                "started_at": items[0]["occurred_at"],
                "updated_at": items[-1]["occurred_at"],
                "episode_ids": [item["episode_id"] for item in items],
                "change_ids": trajectory_changes,
                "event_count": len(items),
                "change_count": len(trajectory_changes),
                "event_boundary_count": sum(1 for item in items if item.get("event_boundary")),
                "temporally_ordered": True,
                "prior_states_preserved": len(items) > 1,
            }
        )
    trajectories.sort(key=lambda item: (str(item["updated_at"]), str(item["trajectory_id"])))
    return events, changes[-MAX_CHANGES:], trajectories[-MAX_TRAJECTORIES:]


def _select_precedent(changes: Sequence[Mapping[str, object]], query: object) -> Dict[str, object]:
    query_tokens = _tokens(query)
    if not query_tokens:
        return {}
    ranked: List[Tuple[float, int, Mapping[str, object], List[str]]] = []
    for index, change in enumerate(changes):
        weighted_fields = (
            (change.get("observed_error"), 3.0),
            (change.get("change_directive"), 3.0),
            (change.get("recorded_priority"), 2.0),
        )
        score = 0.0
        matched = set()
        for value, weight in weighted_fields:
            overlap = query_tokens & _tokens(value)
            matched.update(overlap)
            score += len(overlap) * weight
        if score < 2.0:
            continue
        strength_bonus = 1.0 if change.get("change_strength") == "verified" else 0.5
        ranked.append((score + strength_bonus, index, change, sorted(matched)))
    if not ranked:
        return {}
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    score, _, change, matched = ranked[0]
    return {
        "selected": True,
        "change_id": _text(change.get("change_id"), 100),
        "episode_id": _text(change.get("episode_id"), 100),
        "occurred_at": _timestamp(change.get("occurred_at")),
        "thread_id": _text(change.get("thread_id"), 120),
        "change_kind": _text(change.get("change_kind"), 80),
        "change_strength": _text(change.get("change_strength"), 60),
        "change_status": _text(change.get("change_status"), 60),
        "observed_error": _text(change.get("observed_error"), 400),
        "change_directive": _text(change.get("change_directive"), 400),
        "recorded_priority": _text(change.get("recorded_priority"), 400),
        "source_authority": _text(change.get("source_authority"), 100),
        "evidence_ids": _unique_text(change.get("evidence_ids"), limit=20),
        "correction_ids": _unique_text(change.get("correction_ids"), limit=20),
        "matched_tokens": matched[:12],
        "relevance_score": round(score, 3),
        "requires_memory": True,
        "requires_revision": change.get("change_kind") == "correction_driven_revision",
        "private_mental_state_inferred": False,
    }


def _material(payload: Mapping[str, object]) -> Dict[str, object]:
    material = copy.deepcopy(dict(payload))
    material.pop("state_sha256", None)
    return material


def normalize_state(payload: object) -> Dict[str, object]:
    source = payload if isinstance(payload, Mapping) else {}
    episodes = source.get("source_episodes") if isinstance(source.get("source_episodes"), list) else []
    if episodes:
        events, changes, trajectories = _build_temporal_projection(episodes)
    else:
        events = [copy.deepcopy(item) for item in source.get("events") or [] if isinstance(item, Mapping)][-MAX_EVENTS:]
        changes = [copy.deepcopy(item) for item in source.get("changes") or [] if isinstance(item, Mapping)][-MAX_CHANGES:]
        trajectories = [copy.deepcopy(item) for item in source.get("trajectories") or [] if isinstance(item, Mapping)][-MAX_TRAJECTORIES:]
    selected = (
        copy.deepcopy(source.get("selected_precedent"))
        if isinstance(source.get("selected_precedent"), Mapping)
        else {}
    )
    state: Dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": _timestamp(source.get("updated_at")),
        "status": "active" if events else "empty",
        "events": events,
        "changes": changes,
        "trajectories": trajectories,
        "selected_precedent": selected,
        "event_count": len(events),
        "change_count": len(changes),
        "trajectory_count": len(trajectories),
        "prior_state_retrieval_count": sum(1 for item in trajectories if item.get("prior_states_preserved")),
        "source_grounded_event_count": sum(1 for item in events if item.get("grounded")),
        "change_lesioned": bool(source.get("change_lesioned")),
        "autobiography_lesioned": bool(source.get("autobiography_lesioned")),
        "source_contract": "derived projection over existing relationship episodes; no duplicate transcript",
        "epistemic_boundary": BOUNDARY,
        "contains_private_mental_state": False,
        "self_output_used_as_observation": False,
        "consciousness_verdict_authorized": False,
    }
    state["state_sha256"] = _digest(_material(state))
    return state


def build_state(
    episodes: Sequence[Mapping[str, object]],
    *,
    query: object = "",
    now: object = None,
) -> Dict[str, object]:
    events, changes, trajectories = _build_temporal_projection(episodes)
    selected = _select_precedent(changes, query)
    return normalize_state(
        {
            "updated_at": _timestamp(now),
            "events": events,
            "changes": changes,
            "trajectories": trajectories,
            "selected_precedent": selected,
        }
    )


def validate_state(payload: object) -> Dict[str, object]:
    if not isinstance(payload, Mapping) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported autobiographical-continuity schema")
    normalized = normalize_state(payload)
    expected = _digest(_material(normalized))
    supplied = _text(payload.get("state_sha256"), 64)
    if supplied and supplied != expected:
        raise ValueError("autobiographical-continuity digest mismatch")
    if normalized.get("contains_private_mental_state") is not False:
        raise ValueError("autobiographical projection crossed the private-state boundary")
    if normalized.get("self_output_used_as_observation") is not False:
        raise ValueError("autobiographical projection admitted self-output as observation")
    return normalized


def lesion_change(payload: object) -> Dict[str, object]:
    state = normalize_state(payload)
    events = copy.deepcopy(state.get("events") or [])
    for event in events:
        if not isinstance(event, dict):
            continue
        event["explicit_change"] = ""
        event["change_eligible"] = False
        event["change_id"] = ""
        event["change_kind"] = "change_lesioned"
        event["change_strength"] = "none"
        event["change_status"] = "none"
    trajectories = copy.deepcopy(state.get("trajectories") or [])
    for trajectory in trajectories:
        if not isinstance(trajectory, dict):
            continue
        trajectory["change_ids"] = []
        trajectory["change_count"] = 0
    return normalize_state(
        {
            "updated_at": state.get("updated_at"),
            "events": events,
            "changes": [],
            "trajectories": trajectories,
            "selected_precedent": {},
            "change_lesioned": True,
        }
    )


def lesion_all(payload: object) -> Dict[str, object]:
    state = normalize_state(payload)
    return normalize_state(
        {
            "updated_at": state.get("updated_at"),
            "events": [],
            "changes": [],
            "trajectories": [],
            "selected_precedent": {},
            "autobiography_lesioned": True,
        }
    )


def transient_memory_item(payload: object) -> Dict[str, object]:
    state = normalize_state(payload)
    precedent = state.get("selected_precedent") if isinstance(state.get("selected_precedent"), Mapping) else {}
    if not precedent.get("selected"):
        return {}
    change_id = _text(precedent.get("change_id"), 100)
    return {
        "id": f"autobiographical_change:{change_id}",
        "source": "autobiographical_continuity",
        "title": "Source-grounded prior change record",
        "text": (
            f"At {precedent.get('occurred_at')}, source-grounded episode "
            f"{precedent.get('episode_id')} recorded error "
            f"'{precedent.get('observed_error') or 'none'}' and change directive "
            f"'{precedent.get('change_directive')}'. Status is "
            f"'{precedent.get('change_status')}'. Apply it only when relevant "
            "and preserve its evidence boundary."
        ),
        "confidence": 90 if precedent.get("change_strength") == "verified" else 82,
        "relevance_score": float(precedent.get("relevance_score") or 0.0),
        "episode_id": _text(precedent.get("episode_id"), 100),
        "change_id": change_id,
        "evidence_ids": _unique_text(precedent.get("evidence_ids"), limit=20),
        "tags": ["autobiographical_continuity", "source_grounded_self_change"],
        "transient_projection": True,
        "contains_private_mental_state": False,
    }


__all__ = [
    "BOUNDARY",
    "CHANGE_SCHEMA_VERSION",
    "EVENT_SCHEMA_VERSION",
    "MAX_CHANGES",
    "MAX_EVENTS",
    "MAX_TRAJECTORIES",
    "SCHEMA_VERSION",
    "build_state",
    "lesion_all",
    "lesion_change",
    "normalize_state",
    "transient_memory_item",
    "validate_state",
]
