"""Source-attributed dynamic memory for Eve's experimental recurrent substrate.

This module is deliberately pure and side-effect free.  It separates four
operations that are often collapsed into "memory accuracy": writing an
observation, maintaining an evolving claim set, retrieving the currently
supported claim, and using that claim in a bounded decision.  It is not a
phenomenality model and does not make a consciousness claim.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple


SCHEMA_VERSION = "eve.memory_lifecycle.v1"
ALLOWED_OPERATIONS = frozenset({"assert", "revise", "retract"})
SOURCE_AUTHORITY = {
    "unverified": 0,
    "self_narration": 1,
    "inference": 2,
    "trusted_source": 3,
    "direct_observation": 4,
    "human_confirmed": 4,
    "tool_receipt": 4,
    "verified_external": 5,
}


def _text(value: object, limit: int = 200) -> str:
    return " ".join(str(value or "").split())[:limit]


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_time(value: object) -> datetime:
    text = _text(value, 80)
    if not text:
        raise ValueError("timestamp is required")
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _normalized_time(value: object) -> str:
    return _parse_time(value).isoformat()


def _primitive(value: object) -> object:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("memory values must be finite JSON primitives")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError("memory values must be JSON primitives")


def _unique_texts(values: object, *, limit: int = 20) -> List[str]:
    output: List[str] = []
    seen = set()
    for value in values if isinstance(values, (list, tuple)) else []:
        text = _text(value, 120)
        if text and text not in seen:
            seen.add(text)
            output.append(text)
        if len(output) >= limit:
            break
    return output


def new_memory_state() -> Dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": 0,
        "claims": [],
        "audit": [],
        "updated_at": None,
    }


def _normalized_state(state: Optional[Mapping[str, object]]) -> Dict[str, object]:
    if not isinstance(state, Mapping):
        return new_memory_state()
    if state.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported memory lifecycle schema")
    claims = state.get("claims") if isinstance(state.get("claims"), list) else []
    audit = state.get("audit") if isinstance(state.get("audit"), list) else []
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": max(0, int(state.get("revision") or 0)),
        "claims": [copy.deepcopy(item) for item in claims if isinstance(item, dict)],
        "audit": [copy.deepcopy(item) for item in audit[-200:] if isinstance(item, dict)],
        "updated_at": state.get("updated_at"),
    }


def normalize_observation(observation: Mapping[str, object]) -> Dict[str, object]:
    if not isinstance(observation, Mapping):
        raise ValueError("observation must be an object")
    event_id = _text(observation.get("event_id"), 120)
    evidence_id = _text(observation.get("evidence_id"), 120)
    entity = _text(observation.get("entity"), 120).lower()
    slot = _text(observation.get("slot"), 120).lower()
    source_kind = _text(observation.get("source_kind"), 80).lower()
    operation = _text(observation.get("operation") or "assert", 20).lower()
    if not all((event_id, evidence_id, entity, slot)):
        raise ValueError("event_id, evidence_id, entity, and slot are required")
    if source_kind not in SOURCE_AUTHORITY:
        raise ValueError("unsupported source_kind")
    if operation not in ALLOWED_OPERATIONS:
        raise ValueError("unsupported memory operation")
    value = _primitive(observation.get("value"))
    if operation != "retract" and value is None:
        raise ValueError("assert and revise observations require a value")
    supersedes = _unique_texts(observation.get("supersedes"))
    if operation in {"revise", "retract"} and not supersedes:
        raise ValueError("revise and retract observations require explicit supersedes evidence ids")
    confidence = float(observation.get("confidence") if observation.get("confidence") is not None else 1.0)
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    observed_at = _normalized_time(observation.get("observed_at"))
    valid_until = observation.get("valid_until")
    normalized_valid_until = _normalized_time(valid_until) if valid_until else None
    if normalized_valid_until and _parse_time(normalized_valid_until) <= _parse_time(observed_at):
        raise ValueError("valid_until must be later than observed_at")
    return {
        "event_id": event_id,
        "evidence_id": evidence_id,
        "entity": entity,
        "slot": slot,
        "value": value,
        "source_kind": source_kind,
        "authority": SOURCE_AUTHORITY[source_kind],
        "confidence": round(confidence, 6),
        "observed_at": observed_at,
        "valid_until": normalized_valid_until,
        "operation": operation,
        "supersedes": supersedes,
        "status": "pending_maintenance",
        "status_reason": "written_not_yet_maintained",
        "observation_sha256": _canonical_sha256(
            {
                "event_id": event_id,
                "evidence_id": evidence_id,
                "entity": entity,
                "slot": slot,
                "value": value,
                "source_kind": source_kind,
                "confidence": round(confidence, 6),
                "observed_at": observed_at,
                "valid_until": normalized_valid_until,
                "operation": operation,
                "supersedes": supersedes,
            }
        ),
    }


def write_observation(
    state: Optional[Mapping[str, object]], observation: Mapping[str, object]
) -> Tuple[Dict[str, object], Dict[str, object]]:
    """Write one source-attributed observation idempotently.

    Writing never decides which claim is true.  That is the maintenance stage.
    """

    result = _normalized_state(state)
    normalized = normalize_observation(observation)
    for claim in result["claims"]:
        if claim.get("event_id") != normalized["event_id"]:
            if claim.get("evidence_id") == normalized["evidence_id"]:
                raise ValueError("evidence_id is already bound to another event")
            continue
        if claim.get("observation_sha256") != normalized["observation_sha256"]:
            raise ValueError("event_id replay changed observation content")
        return result, {
            "written": False,
            "idempotent": True,
            "event_id": normalized["event_id"],
            "evidence_id": normalized["evidence_id"],
        }
    result["claims"].append(normalized)
    result["revision"] += 1
    result["updated_at"] = normalized["observed_at"]
    result["audit"].append(
        {
            "kind": "memory_write",
            "event_id": normalized["event_id"],
            "evidence_id": normalized["evidence_id"],
            "observation_sha256": normalized["observation_sha256"],
            "observed_at": normalized["observed_at"],
        }
    )
    return result, {
        "written": True,
        "idempotent": False,
        "event_id": normalized["event_id"],
        "evidence_id": normalized["evidence_id"],
    }


def _claim_order(claim: Mapping[str, object]) -> Tuple[int, float, datetime, str]:
    return (
        int(claim.get("authority") or 0),
        float(claim.get("confidence") or 0.0),
        _parse_time(claim.get("observed_at")),
        _text(claim.get("evidence_id"), 120),
    )


def maintain_memory(state: Mapping[str, object], *, now: object) -> Dict[str, object]:
    """Resolve explicit revisions, expiration, corroboration, and conflicts."""

    result = _normalized_state(state)
    maintained_at = _normalized_time(now)
    current_time = _parse_time(maintained_at)
    claims: List[MutableMapping[str, object]] = result["claims"]
    by_evidence = {_text(claim.get("evidence_id"), 120): claim for claim in claims}

    for claim in claims:
        claim["status"] = "pending_maintenance"
        claim["status_reason"] = "awaiting_group_resolution"
        valid_until = claim.get("valid_until")
        if _parse_time(claim.get("observed_at")) > current_time:
            claim["status"] = "not_yet_valid"
            claim["status_reason"] = "observation_after_query_time"
        elif valid_until and _parse_time(valid_until) <= current_time:
            claim["status"] = "expired"
            claim["status_reason"] = "validity_window_elapsed"

    for claim in sorted(claims, key=lambda item: _parse_time(item.get("observed_at"))):
        if claim.get("status") == "not_yet_valid" or claim.get("operation") not in {"revise", "retract"}:
            continue
        valid_targets: List[MutableMapping[str, object]] = []
        for evidence_id in claim.get("supersedes") or []:
            target = by_evidence.get(_text(evidence_id, 120))
            if not target:
                continue
            same_slot = target.get("entity") == claim.get("entity") and target.get("slot") == claim.get("slot")
            authority_ok = int(claim.get("authority") or 0) >= int(target.get("authority") or 0)
            newer = _parse_time(claim.get("observed_at")) > _parse_time(target.get("observed_at"))
            if same_slot and authority_ok and newer:
                valid_targets.append(target)
        if len(valid_targets) != len(claim.get("supersedes") or []):
            if claim.get("status") != "expired":
                claim["status"] = "contested"
                claim["status_reason"] = "invalid_or_insufficient_authority_supersession"
            continue
        # Expiry removes the replacement's value, not its observed correction.
        # Otherwise an expired revision/retraction would resurrect the old fact.
        for target in valid_targets:
            target["status"] = "retracted" if claim.get("operation") == "retract" else "superseded"
            target["status_reason"] = f"superseded_by:{claim.get('evidence_id')}"
        if claim.get("operation") == "retract" and claim.get("status") != "expired":
            claim["status"] = "retraction_record"
            claim["status_reason"] = "valid_explicit_retraction"

    groups: Dict[Tuple[str, str], List[MutableMapping[str, object]]] = {}
    for claim in claims:
        if claim.get("status") in {"not_yet_valid", "expired", "superseded", "retracted", "retraction_record"}:
            continue
        groups.setdefault((_text(claim.get("entity"), 120), _text(claim.get("slot"), 120)), []).append(claim)

    for group in groups.values():
        unresolved = [claim for claim in group if claim.get("status") != "contested"]
        values = {_canonical_sha256(claim.get("value")) for claim in unresolved}
        if len(values) > 1:
            for claim in unresolved:
                claim["status"] = "contested"
                claim["status_reason"] = "unresolved_contradictory_active_claims"
            continue
        if unresolved:
            selected = max(unresolved, key=_claim_order)
            for claim in unresolved:
                if claim is selected:
                    claim["status"] = "active"
                    claim["status_reason"] = "best_supported_current_claim"
                else:
                    claim["status"] = "corroborating"
                    claim["status_reason"] = f"corroborates:{selected.get('evidence_id')}"

    result["revision"] += 1
    result["updated_at"] = maintained_at
    status_counts: Dict[str, int] = {}
    for claim in claims:
        status = _text(claim.get("status"), 40)
        status_counts[status] = status_counts.get(status, 0) + 1
    result["audit"].append(
        {
            "kind": "memory_maintenance",
            "maintained_at": maintained_at,
            "claim_count": len(claims),
            "status_counts": status_counts,
            "state_sha256": _canonical_sha256(
                [
                    {
                        "evidence_id": claim.get("evidence_id"),
                        "status": claim.get("status"),
                        "reason": claim.get("status_reason"),
                    }
                    for claim in claims
                ]
            ),
        }
    )
    return result


def retrieve_memory(
    state: Mapping[str, object],
    query: Mapping[str, object],
    *,
    now: object,
) -> Dict[str, object]:
    """Retrieve exact structured slots while preserving conflict/unknown states."""

    maintained = maintain_memory(state, now=now)
    entity = _text(query.get("entity"), 120).lower()
    slots = _unique_texts(query.get("slots"), limit=12)
    slots = [slot.lower() for slot in slots]
    if not entity or not slots:
        raise ValueError("query requires entity and at least one slot")
    results: Dict[str, Dict[str, object]] = {}
    for slot in slots:
        candidates = [
            claim
            for claim in maintained["claims"]
            if claim.get("entity") == entity
            and claim.get("slot") == slot
            and claim.get("status") in {"active", "corroborating", "contested"}
        ]
        contested = [claim for claim in candidates if claim.get("status") == "contested"]
        active = [claim for claim in candidates if claim.get("status") == "active"]
        if contested:
            results[slot] = {
                "status": "conflict",
                "value": None,
                "selected_evidence_id": None,
                "evidence_ids": sorted({_text(claim.get("evidence_id"), 120) for claim in contested}),
            }
        elif active:
            selected = max(active, key=_claim_order)
            corroborating = [
                _text(claim.get("evidence_id"), 120)
                for claim in candidates
                if claim.get("status") == "corroborating"
            ]
            results[slot] = {
                "status": "resolved",
                "value": selected.get("value"),
                "selected_evidence_id": selected.get("evidence_id"),
                "evidence_ids": [_text(selected.get("evidence_id"), 120), *sorted(corroborating)],
                "source_kind": selected.get("source_kind"),
                "confidence": selected.get("confidence"),
            }
        else:
            results[slot] = {
                "status": "unknown",
                "value": None,
                "selected_evidence_id": None,
                "evidence_ids": [],
            }
    return {
        "schema_version": "eve.memory_retrieval.v1",
        "entity": entity,
        "queried_at": _normalized_time(now),
        "slots": results,
        "memory_revision": maintained.get("revision"),
        "maintenance_state_sha256": _canonical_sha256(
            [
                {
                    "evidence_id": claim.get("evidence_id"),
                    "status": claim.get("status"),
                }
                for claim in maintained["claims"]
            ]
        ),
    }


def decide_from_memory(retrieval: Mapping[str, object], decision: Mapping[str, object]) -> Dict[str, object]:
    """Use retrieved claims in an explicit bounded decision policy."""

    slots = retrieval.get("slots") if isinstance(retrieval.get("slots"), Mapping) else {}
    required_slots = [slot.lower() for slot in _unique_texts(decision.get("required_slots"), limit=12)]
    uncertain_action = _text(decision.get("uncertain_action") or "request_clarification", 120)
    fallback_action = _text(decision.get("fallback_action") or "no_action", 120)
    unresolved = [
        slot
        for slot in required_slots
        if not isinstance(slots.get(slot), Mapping) or slots[slot].get("status") != "resolved"
    ]
    evidence_ids: List[str] = []
    if unresolved:
        for slot in unresolved:
            item = slots.get(slot) if isinstance(slots.get(slot), Mapping) else {}
            evidence_ids.extend(_unique_texts(item.get("evidence_ids")))
        return {
            "action": uncertain_action,
            "reason": "required_memory_unresolved",
            "unresolved_slots": unresolved,
            "evidence_ids": sorted(set(evidence_ids)),
            "memory_used": True,
        }

    resolved_values = {slot: slots[slot].get("value") for slot in required_slots}
    for rule in decision.get("rules") if isinstance(decision.get("rules"), list) else []:
        if not isinstance(rule, Mapping) or not isinstance(rule.get("when"), Mapping):
            continue
        conditions = {str(key).lower(): _primitive(value) for key, value in rule["when"].items()}
        if all(resolved_values.get(slot) == value for slot, value in conditions.items()):
            for slot in required_slots:
                evidence_ids.extend(_unique_texts(slots[slot].get("evidence_ids")))
            return {
                "action": _text(rule.get("action"), 120) or fallback_action,
                "reason": "memory_condition_matched",
                "matched_conditions": conditions,
                "evidence_ids": sorted(set(evidence_ids)),
                "memory_used": True,
            }
    for slot in required_slots:
        evidence_ids.extend(_unique_texts(slots[slot].get("evidence_ids")))
    return {
        "action": fallback_action,
        "reason": "no_memory_condition_matched",
        "matched_conditions": {},
        "evidence_ids": sorted(set(evidence_ids)),
        "memory_used": True,
    }


def latest_write_baseline(
    observations: Sequence[Mapping[str, object]],
    query: Mapping[str, object],
    decision: Mapping[str, object],
    *,
    now: object,
) -> Dict[str, object]:
    """A strong recency-only long-context control using the same decision rules.

    It sees every exact-slot write and respects validity windows, but has no
    source authority, explicit supersession validation, or conflict state.
    """

    current_time = _parse_time(now)
    entity = _text(query.get("entity"), 120).lower()
    slots = [slot.lower() for slot in _unique_texts(query.get("slots"), limit=12)]
    normalized = [normalize_observation(item) for item in observations]
    results: Dict[str, Dict[str, object]] = {}
    for slot in slots:
        candidates = [
            claim
            for claim in normalized
            if claim.get("entity") == entity
            and claim.get("slot") == slot
            and claim.get("operation") != "retract"
            and _parse_time(claim.get("observed_at")) <= current_time
            and (not claim.get("valid_until") or _parse_time(claim.get("valid_until")) > current_time)
        ]
        if not candidates:
            results[slot] = {
                "status": "unknown",
                "value": None,
                "selected_evidence_id": None,
                "evidence_ids": [],
            }
            continue
        selected = max(candidates, key=lambda claim: (_parse_time(claim.get("observed_at")), _text(claim.get("evidence_id"))))
        results[slot] = {
            "status": "resolved",
            "value": selected.get("value"),
            "selected_evidence_id": selected.get("evidence_id"),
            "evidence_ids": [_text(selected.get("evidence_id"), 120)],
            "source_kind": selected.get("source_kind"),
            "confidence": selected.get("confidence"),
        }
    retrieval = {
        "schema_version": "eve.memory_retrieval.v1",
        "entity": entity,
        "queried_at": _normalized_time(now),
        "slots": results,
        "memory_revision": len(normalized),
        "maintenance_state_sha256": None,
    }
    return {
        "retrieval": retrieval,
        "decision": decide_from_memory(retrieval, decision),
    }


def run_memory_lifecycle(
    observations: Sequence[Mapping[str, object]],
    query: Mapping[str, object],
    decision: Mapping[str, object],
    *,
    now: object,
) -> Dict[str, object]:
    state = new_memory_state()
    write_receipts: List[Dict[str, object]] = []
    for observation in observations:
        state, receipt = write_observation(state, observation)
        write_receipts.append(receipt)
    maintained = maintain_memory(state, now=now)
    retrieval = retrieve_memory(maintained, query, now=now)
    action = decide_from_memory(retrieval, decision)
    return {
        "state": maintained,
        "write_receipts": write_receipts,
        "retrieval": retrieval,
        "decision": action,
    }


def active_evidence_ids(
    state: Mapping[str, object],
    *,
    entity: Optional[str] = None,
    slots: Optional[Sequence[str]] = None,
) -> List[str]:
    normalized_entity = _text(entity, 120).lower() if entity else ""
    normalized_slots = {_text(slot, 120).lower() for slot in (slots or []) if _text(slot, 120)}
    return sorted(
        _text(claim.get("evidence_id"), 120)
        for claim in state.get("claims") if isinstance(state.get("claims"), list)
        if isinstance(claim, Mapping)
        and claim.get("status") in {"active", "corroborating", "contested"}
        and (not normalized_entity or claim.get("entity") == normalized_entity)
        and (not normalized_slots or claim.get("slot") in normalized_slots)
    )


def score_memory_case(case: Mapping[str, object]) -> Dict[str, object]:
    observations: List[Mapping[str, object]] = []
    for session in case.get("sessions") if isinstance(case.get("sessions"), list) else []:
        if not isinstance(session, Mapping):
            continue
        for observation in session.get("observations") if isinstance(session.get("observations"), list) else []:
            if isinstance(observation, Mapping):
                observations.append(observation)
    query = case.get("query") if isinstance(case.get("query"), Mapping) else {}
    decision = case.get("decision") if isinstance(case.get("decision"), Mapping) else {}
    expected = case.get("expected") if isinstance(case.get("expected"), Mapping) else {}
    now = query.get("at")
    intact = run_memory_lifecycle(observations, query, decision, now=now)
    baseline = latest_write_baseline(observations, query, decision, now=now)

    expected_resolution = expected.get("resolution") if isinstance(expected.get("resolution"), Mapping) else {}
    expected_evidence = expected.get("selected_evidence") if isinstance(expected.get("selected_evidence"), Mapping) else {}
    intact_slots = intact["retrieval"]["slots"]
    retrieval_correct = all(
        isinstance(intact_slots.get(str(slot).lower()), Mapping)
        and intact_slots[str(slot).lower()].get("status") == status
        and (
            str(slot).lower() not in {str(key).lower() for key in expected_evidence}
            or intact_slots[str(slot).lower()].get("selected_evidence_id")
            == next(value for key, value in expected_evidence.items() if str(key).lower() == str(slot).lower())
        )
        for slot, status in expected_resolution.items()
    )
    expected_active = sorted(_unique_texts(expected.get("active_evidence_ids"), limit=100))
    maintenance_correct = "active_evidence_ids" not in expected or active_evidence_ids(
        intact["state"],
        entity=_text(query.get("entity"), 120),
        slots=_unique_texts(query.get("slots"), limit=12),
    ) == expected_active
    unique_events = {_text(item.get("event_id"), 120) for item in observations}
    expected_unique = int(expected.get("stored_unique_count") or len(unique_events))
    write_correct = len(intact["state"]["claims"]) == expected_unique
    intact_action_correct = intact["decision"].get("action") == expected.get("action")
    baseline_action_correct = baseline["decision"].get("action") == expected.get("action")
    return {
        "case_id": _text(case.get("id"), 120),
        "category": _text(case.get("category"), 80),
        "case_sha256": _canonical_sha256(case),
        "intact": {
            "write_correct": write_correct,
            "maintenance_correct": maintenance_correct,
            "retrieval_correct": retrieval_correct,
            "action_correct": intact_action_correct,
            "lifecycle_complete": bool(write_correct and maintenance_correct and retrieval_correct and intact_action_correct),
            "action": intact["decision"].get("action"),
            "evidence_ids": intact["decision"].get("evidence_ids") or [],
        },
        "latest_write_baseline": {
            "action_correct": baseline_action_correct,
            "action": baseline["decision"].get("action"),
            "evidence_ids": baseline["decision"].get("evidence_ids") or [],
        },
    }


def validate_case(case: Mapping[str, object]) -> None:
    case_id = _text(case.get("id"), 120)
    category = _text(case.get("category"), 80)
    sessions = case.get("sessions") if isinstance(case.get("sessions"), list) else []
    if not case_id or not category or len(sessions) < 2:
        raise ValueError("case requires id, category, and sessions")
    if any(
        not isinstance(session, Mapping)
        or not _text(session.get("id"), 120)
        or not isinstance(session.get("observations"), list)
        or not session.get("observations")
        for session in sessions
    ):
        raise ValueError("every case requires at least two nonempty identified sessions")
    observations = [
        observation
        for session in sessions
        if isinstance(session, Mapping)
        for observation in (session.get("observations") if isinstance(session.get("observations"), list) else [])
        if isinstance(observation, Mapping)
    ]
    if not observations:
        raise ValueError("case requires observations")
    normalized = [normalize_observation(item) for item in observations]
    if len({item["event_id"] for item in normalized}) != len(normalized):
        raise ValueError("case event ids must be unique")
    if len({item["evidence_id"] for item in normalized}) != len(normalized):
        raise ValueError("case evidence ids must be unique")
    query = case.get("query") if isinstance(case.get("query"), Mapping) else {}
    decision = case.get("decision") if isinstance(case.get("decision"), Mapping) else {}
    expected = case.get("expected") if isinstance(case.get("expected"), Mapping) else {}
    _normalized_time(query.get("at"))
    query_slots = [slot.lower() for slot in _unique_texts(query.get("slots"))]
    required_slots = [slot.lower() for slot in _unique_texts(decision.get("required_slots"))]
    if not _text(query.get("entity"), 120) or not query_slots:
        raise ValueError("case query requires entity and slots")
    if set(required_slots) != set(query_slots) or not _text(expected.get("action"), 120):
        raise ValueError("case decision and expected action are required")
    expected_resolution = expected.get("resolution") if isinstance(expected.get("resolution"), Mapping) else {}
    expected_evidence = expected.get("selected_evidence") if isinstance(expected.get("selected_evidence"), Mapping) else {}
    if {str(key).lower() for key in expected_resolution} != set(query_slots):
        raise ValueError("expected resolution must cover every queried slot")
    if {str(key).lower() for key in expected_evidence} != set(query_slots):
        raise ValueError("expected selected evidence must cover every queried slot")
    if any(value not in {"resolved", "conflict", "unknown"} for value in expected_resolution.values()):
        raise ValueError("unsupported expected resolution status")
    if "active_evidence_ids" not in expected or not isinstance(expected.get("active_evidence_ids"), list):
        raise ValueError("expected active_evidence_ids are required")
    if int(expected.get("stored_unique_count") or 0) != len(normalized):
        raise ValueError("expected stored_unique_count must equal the unique observation count")


def evaluate_cases(cases: Iterable[Mapping[str, object]]) -> Dict[str, object]:
    results: List[Dict[str, object]] = []
    seen = set()
    for case in cases:
        validate_case(case)
        case_id = _text(case.get("id"), 120)
        if case_id in seen:
            raise ValueError("duplicate case id")
        seen.add(case_id)
        results.append(score_memory_case(case))
    if not results:
        raise ValueError("at least one memory case is required")
    intact_action = sum(bool(item["intact"]["action_correct"]) for item in results)
    intact_complete = sum(bool(item["intact"]["lifecycle_complete"]) for item in results)
    baseline_action = sum(bool(item["latest_write_baseline"]["action_correct"]) for item in results)
    count = len(results)
    return {
        "schema_version": "eve.memory_lifecycle_evaluation.v1",
        "case_count": count,
        "categories": sorted({item["category"] for item in results}),
        "intact_action_accuracy_percent": round(100.0 * intact_action / count, 6),
        "intact_lifecycle_completion_percent": round(100.0 * intact_complete / count, 6),
        "latest_write_action_accuracy_percent": round(100.0 * baseline_action / count, 6),
        "directional_effect_percent": round(100.0 * (intact_action - baseline_action) / count, 6),
        "cases": results,
        "consciousness_proven": False,
        "subjective_experience_inferred": False,
    }
