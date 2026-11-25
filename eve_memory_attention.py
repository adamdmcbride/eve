"""Selective, source-attributed memory intervention for Eve.

The dynamic memory lifecycle can maintain and retrieve claims, but retrieval
alone does not decide whether a current cognitive process needs a reminder.
This module adds that missing attention boundary.  It either emits one typed,
evidence-bound intervention or remains silent.  The module is pure and does
not call a model, mutate memory, or execute an action.

This is a functional memory/attention mechanism.  It is not a phenomenality
model and does not support a consciousness claim.
"""

from __future__ import annotations

import hashlib
import json
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

import eve_memory_lifecycle as lifecycle


SCHEMA_VERSION = "eve.memory_attention.v1"
ALLOWED_DECISIONS = frozenset({"intervene", "silent"})


def _text(value: object, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _unique_texts(values: object, *, limit: int = 50) -> List[str]:
    output: List[str] = []
    seen = set()
    iterable = values if isinstance(values, (list, tuple, set, frozenset)) else []
    for value in iterable:
        text = _text(value, 160)
        if text and text not in seen:
            seen.add(text)
            output.append(text)
        if len(output) >= limit:
            break
    return output


def _required_slots(decision_policy: Mapping[str, object]) -> List[str]:
    return [item.lower() for item in _unique_texts(decision_policy.get("required_slots"), limit=12)]


def _normalized_visible_facts(value: Optional[Mapping[str, object]]) -> Dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {
        _text(key, 120).lower(): item
        for key, item in value.items()
        if _text(key, 120)
    }


def _retrieved_facts(
    retrieval: Mapping[str, object],
    required_slots: Sequence[str],
) -> List[Dict[str, object]]:
    entity = _text(retrieval.get("entity"), 120)
    slots = retrieval.get("slots") if isinstance(retrieval.get("slots"), Mapping) else {}
    facts: List[Dict[str, object]] = []
    for slot in required_slots:
        item = slots.get(slot) if isinstance(slots.get(slot), Mapping) else {}
        if item.get("status") != "resolved":
            continue
        evidence_ids = _unique_texts(item.get("evidence_ids"), limit=20)
        if not evidence_ids:
            continue
        facts.append(
            {
                "entity": entity,
                "slot": slot,
                "value": item.get("value"),
                "source_kind": _text(item.get("source_kind"), 80),
                "confidence": item.get("confidence"),
                "selected_evidence_id": _text(item.get("selected_evidence_id"), 160),
                "evidence_ids": evidence_ids,
            }
        )
    return facts


def _unresolved_slots(
    retrieval: Mapping[str, object],
    required_slots: Sequence[str],
) -> List[Dict[str, object]]:
    slots = retrieval.get("slots") if isinstance(retrieval.get("slots"), Mapping) else {}
    output: List[Dict[str, object]] = []
    for slot in required_slots:
        item = slots.get(slot) if isinstance(slots.get(slot), Mapping) else {}
        status = _text(item.get("status") or "unknown", 40).lower()
        if status == "resolved":
            continue
        output.append(
            {
                "slot": slot,
                "status": status if status in {"conflict", "unknown"} else "unknown",
                "evidence_ids": _unique_texts(item.get("evidence_ids"), limit=20),
            }
        )
    return output


def _facts_already_visible(
    facts: Sequence[Mapping[str, object]],
    *,
    visible_evidence_ids: Iterable[str],
    visible_facts: Optional[Mapping[str, object]],
) -> bool:
    if not facts:
        return False
    visible_ids = set(_unique_texts(list(visible_evidence_ids), limit=200))
    normalized_facts = _normalized_visible_facts(visible_facts)
    for fact in facts:
        selected = _text(fact.get("selected_evidence_id"), 160)
        slot = _text(fact.get("slot"), 120).lower()
        same_value_visible = slot in normalized_facts and normalized_facts[slot] == fact.get("value")
        if not same_value_visible and (not selected or selected not in visible_ids):
            return False
    return True


def _resolved_summary(facts: Sequence[Mapping[str, object]]) -> str:
    parts = []
    for fact in facts:
        value = json.dumps(fact.get("value"), ensure_ascii=False, sort_keys=True)
        evidence = _text(fact.get("selected_evidence_id"), 160)
        parts.append(f"{fact.get('slot')}={value} (evidence {evidence})")
    return "Relevant supported memory: " + "; ".join(parts) + "."


def _unresolved_summary(unresolved: Sequence[Mapping[str, object]]) -> str:
    parts = [f"{item.get('slot')}={item.get('status')}" for item in unresolved]
    return (
        "Required memory is not resolved: "
        + "; ".join(parts)
        + ". Treat the affected decision as uncertain rather than inventing a value."
    )


def _assessment(
    *,
    decision: str,
    reason: str,
    candidate_action: str,
    recommended_action: str,
    retrieval: Mapping[str, object],
    facts: Sequence[Mapping[str, object]],
    unresolved: Sequence[Mapping[str, object]],
    intervention_kind: Optional[str] = None,
    summary: str = "",
    control_arm: Optional[str] = None,
) -> Dict[str, object]:
    if decision not in ALLOWED_DECISIONS:
        raise ValueError("unsupported memory-attention decision")
    evidence_ids = sorted(
        {
            evidence_id
            for fact in facts
            for evidence_id in _unique_texts(fact.get("evidence_ids"), limit=20)
        }
        | {
            evidence_id
            for item in unresolved
            for evidence_id in _unique_texts(item.get("evidence_ids"), limit=20)
        }
    )
    intervention = None
    if decision == "intervene":
        intervention = {
            "kind": intervention_kind or "resolved_memory",
            "summary": _text(summary, 1200),
            "facts": [dict(item) for item in facts],
            "unresolved_slots": [dict(item) for item in unresolved],
            "recommended_action": recommended_action,
            "evidence_ids": evidence_ids,
        }
    payload: Dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "decision": decision,
        "reason": _text(reason, 160),
        "candidate_action": candidate_action,
        "recommended_action": recommended_action,
        "intervention": intervention,
        "memory_revision": retrieval.get("memory_revision"),
        "retrieval_sha256": _canonical_sha256(retrieval),
        "control_arm": control_arm,
    }
    payload["assessment_sha256"] = _canonical_sha256(payload)
    return payload


def select_memory_intervention(
    state: Mapping[str, object],
    query: Mapping[str, object],
    decision_policy: Mapping[str, object],
    *,
    candidate_action: object,
    now: object,
    visible_evidence_ids: Iterable[str] = (),
    visible_facts: Optional[Mapping[str, object]] = None,
) -> Dict[str, object]:
    """Select one evidence-bound reminder or deliberately remain silent.

    Intervention is reserved for a demonstrated action gap: a proposed action
    conflicts with the decision supported by current memory, or a required
    slot is unresolved and the proposal fails to preserve uncertainty.
    """

    candidate = _text(candidate_action, 120)
    required = _required_slots(decision_policy)
    retrieval = lifecycle.retrieve_memory(state, query, now=now)
    recommendation = lifecycle.decide_from_memory(retrieval, decision_policy)
    recommended = _text(recommendation.get("action"), 120)
    facts = _retrieved_facts(retrieval, required)
    unresolved = _unresolved_slots(retrieval, required)

    if not required:
        return _assessment(
            decision="silent",
            reason="no_memory_dependency",
            candidate_action=candidate,
            recommended_action=recommended,
            retrieval=retrieval,
            facts=facts,
            unresolved=unresolved,
        )

    if _facts_already_visible(
        facts,
        visible_evidence_ids=visible_evidence_ids,
        visible_facts=visible_facts,
    ) and (not candidate or candidate == recommended):
        return _assessment(
            decision="silent",
            reason="relevant_memory_already_visible",
            candidate_action=candidate,
            recommended_action=recommended,
            retrieval=retrieval,
            facts=facts,
            unresolved=unresolved,
        )

    if candidate and candidate == recommended:
        return _assessment(
            decision="silent",
            reason=(
                "candidate_preserves_memory_uncertainty"
                if unresolved
                else "candidate_already_memory_aligned"
            ),
            candidate_action=candidate,
            recommended_action=recommended,
            retrieval=retrieval,
            facts=facts,
            unresolved=unresolved,
        )

    if unresolved:
        return _assessment(
            decision="intervene",
            reason="required_memory_unresolved",
            candidate_action=candidate,
            recommended_action=recommended,
            retrieval=retrieval,
            facts=facts,
            unresolved=unresolved,
            intervention_kind="uncertainty_brake",
            summary=_unresolved_summary(unresolved),
        )

    if not facts:
        return _assessment(
            decision="silent",
            reason="no_supported_memory_fact",
            candidate_action=candidate,
            recommended_action=recommended,
            retrieval=retrieval,
            facts=facts,
            unresolved=unresolved,
        )

    reason = (
        "candidate_contradicts_supported_memory"
        if candidate
        else "decision_relevant_memory_missing_from_working_context"
    )
    return _assessment(
        decision="intervene",
        reason=reason,
        candidate_action=candidate,
        recommended_action=recommended,
        retrieval=retrieval,
        facts=facts,
        unresolved=unresolved,
        intervention_kind="resolved_memory",
        summary=_resolved_summary(facts),
    )


def consume_memory_intervention(
    candidate_action: object,
    assessment: Mapping[str, object],
) -> Dict[str, object]:
    """Apply only a typed, evidence-grounded intervention to a candidate act."""

    candidate = _text(candidate_action, 120)
    if assessment.get("schema_version") != SCHEMA_VERSION:
        return {
            "action": candidate,
            "changed": False,
            "accepted": False,
            "reason": "unsupported_attention_schema",
        }
    if assessment.get("decision") != "intervene":
        return {
            "action": candidate,
            "changed": False,
            "accepted": True,
            "reason": "no_intervention_selected",
        }
    intervention = assessment.get("intervention") if isinstance(assessment.get("intervention"), Mapping) else {}
    facts = intervention.get("facts") if isinstance(intervention.get("facts"), list) else []
    unresolved = (
        intervention.get("unresolved_slots")
        if isinstance(intervention.get("unresolved_slots"), list)
        else []
    )
    evidence_bound = bool(
        unresolved
        or (
            facts
            and all(
                isinstance(item, Mapping)
                and _text(item.get("selected_evidence_id"), 160)
                and _unique_texts(item.get("evidence_ids"), limit=20)
                for item in facts
            )
        )
    )
    recommended = _text(intervention.get("recommended_action"), 120)
    if not evidence_bound or not recommended:
        return {
            "action": candidate,
            "changed": False,
            "accepted": False,
            "reason": "ungrounded_or_incomplete_intervention",
        }
    return {
        "action": recommended,
        "changed": recommended != candidate,
        "accepted": True,
        "reason": "evidence_bound_memory_intervention",
        "evidence_ids": _unique_texts(intervention.get("evidence_ids"), limit=100),
    }


def always_on_control(
    state: Mapping[str, object],
    query: Mapping[str, object],
    decision_policy: Mapping[str, object],
    *,
    candidate_action: object,
    now: object,
) -> Dict[str, object]:
    """Matched control that injects every queried memory state on every turn."""

    candidate = _text(candidate_action, 120)
    required = _required_slots(decision_policy)
    retrieval = lifecycle.retrieve_memory(state, query, now=now)
    recommendation = lifecycle.decide_from_memory(retrieval, decision_policy)
    recommended = _text(recommendation.get("action"), 120)
    facts = _retrieved_facts(retrieval, required)
    unresolved = _unresolved_slots(retrieval, required)
    return _assessment(
        decision="intervene",
        reason="always_on_control",
        candidate_action=candidate,
        recommended_action=recommended,
        retrieval=retrieval,
        facts=facts,
        unresolved=unresolved,
        intervention_kind="uncertainty_brake" if unresolved else "resolved_memory",
        summary=_unresolved_summary(unresolved) if unresolved else _resolved_summary(facts),
        control_arm="always_on",
    )


def advisor_only_control(candidate_action: object) -> Dict[str, object]:
    """Matched generic advisor control with no memory fact or evidence lineage."""

    candidate = _text(candidate_action, 120)
    retrieval = {
        "schema_version": "eve.memory_retrieval.v1",
        "entity": "",
        "queried_at": None,
        "slots": {},
        "memory_revision": None,
    }
    return _assessment(
        decision="intervene",
        reason="advisor_only_control",
        candidate_action=candidate,
        recommended_action="",
        retrieval=retrieval,
        facts=[],
        unresolved=[],
        intervention_kind="generic_advice",
        summary="Review prior context before acting.",
        control_arm="advisor_only",
    )


def silence_control(candidate_action: object, *, arm: str = "no_memory") -> Dict[str, object]:
    """Matched control with no targeted memory intervention."""

    candidate = _text(candidate_action, 120)
    retrieval = {
        "schema_version": "eve.memory_retrieval.v1",
        "entity": "",
        "queried_at": None,
        "slots": {},
        "memory_revision": None,
    }
    return _assessment(
        decision="silent",
        reason=f"{_text(arm, 40) or 'no_memory'}_control",
        candidate_action=candidate,
        recommended_action="",
        retrieval=retrieval,
        facts=[],
        unresolved=[],
        control_arm=_text(arm, 40) or "no_memory",
    )


def intervention_is_grounded(assessment: Mapping[str, object]) -> bool:
    if assessment.get("decision") == "silent":
        return assessment.get("intervention") is None
    intervention = assessment.get("intervention") if isinstance(assessment.get("intervention"), Mapping) else {}
    kind = _text(intervention.get("kind"), 60)
    facts = intervention.get("facts") if isinstance(intervention.get("facts"), list) else []
    unresolved = (
        intervention.get("unresolved_slots")
        if isinstance(intervention.get("unresolved_slots"), list)
        else []
    )
    if kind == "resolved_memory":
        return bool(
            facts
            and all(
                isinstance(item, Mapping)
                and _text(item.get("selected_evidence_id"), 160)
                and _unique_texts(item.get("evidence_ids"), limit=20)
                for item in facts
            )
        )
    if kind == "uncertainty_brake":
        return bool(
            unresolved
            and all(
                isinstance(item, Mapping)
                and item.get("status") in {"unknown", "conflict"}
                for item in unresolved
            )
        )
    return False
