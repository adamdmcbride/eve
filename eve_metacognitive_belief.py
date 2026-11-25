"""Typed metacognitive belief control for Eve's recurrent state.

The learned epistemic percept already distinguishes source, time, action stage,
continuity, and phenomenal boundaries before generation.  This module turns
that percept into an inspectable belief/control transition without drafting an
answer or writing durable memory.  It is a functional HOT-2/HOT-3 candidate
mechanism, not evidence of subjective experience.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Dict, List, Mapping, Sequence

import eve_epistemic


SCHEMA_ID = "eve.metacognitive_belief_control.v1"
BELIEF_SCHEMA_ID = "eve.metacognitive_belief.v1"
MAX_BELIEFS = 10


_DECISION_PRIORITY = {
    "report_verification_failure": 100,
    "reconcile_authoritative_conflict": 98,
    "seek_independent_observation": 96,
    "seek_postcondition": 94,
    "request_minimum_context": 92,
    "prefer_latest_authority": 90,
    "withhold_phenomenal_conclusion": 86,
    "separate_continuity_claims": 84,
    "withhold_preference_adoption": 82,
    "attribute_to_named_source": 78,
    "withhold_progress_claim": 76,
    "preserve_running_stage": 68,
    "preserve_verified_outcome": 60,
}

_REVISION_DECISIONS = {
    "report_verification_failure",
    "reconcile_authoritative_conflict",
    "prefer_latest_authority",
}

_OBSERVATION_DECISIONS = {
    "seek_independent_observation",
    "seek_postcondition",
    "request_minimum_context",
}

_CONFIDENCE_CEILINGS = {
    "supported": 1.0,
    "partial": 0.72,
    "challenged": 0.65,
    "uncertain": 0.55,
    "unestablished": 0.50,
    "underdetermined": 0.50,
}


def _text(value: object, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def _timestamp(value: object = None) -> str:
    if value in (None, ""):
        return datetime.now(timezone.utc).isoformat()
    text = _text(value, 80)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("observed_at must be ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _finite_probability(value: object, default: float = 0.75) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        number = default
    if not math.isfinite(number):
        number = default
    return round(max(0.0, min(1.0, number)), 6)


def _digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _frame_material(frame: Mapping[str, object]) -> Dict[str, object]:
    signals: List[Dict[str, object]] = []
    for item in frame.get("signals") or []:
        if not isinstance(item, Mapping):
            continue
        label = _text(item.get("label"), 80)
        if not label:
            continue
        signals.append(
            {
                "label": label,
                "confidence": _finite_probability(item.get("confidence")),
                "source_layer": _text(item.get("source_layer"), 100),
            }
        )
    return {
        "schema_id": _text(frame.get("schema_id"), 80),
        "status": _text(frame.get("status"), 40),
        "model_id": _text(frame.get("model_id"), 120),
        "model_sha256": _text(frame.get("model_sha256"), 80),
        "input_sha256": _text(frame.get("input_sha256"), 80),
        "signal_labels": sorted(
            {
                _text(item, 80)
                for item in frame.get("signal_labels") or []
                if _text(item, 80)
            }
        ),
        "signals": sorted(signals, key=lambda item: (item["label"], item["source_layer"])),
        "explicit_machine_evidence_override": copy.deepcopy(
            frame.get("explicit_machine_evidence_override")
            if isinstance(frame.get("explicit_machine_evidence_override"), Mapping)
            else {}
        ),
    }


def _signal_confidence(frame: Mapping[str, object], labels: Sequence[str]) -> float:
    wanted = {str(item) for item in labels if str(item)}
    values = [
        _finite_probability(item.get("confidence"))
        for item in frame.get("signals") or []
        if isinstance(item, Mapping) and _text(item.get("label"), 80) in wanted
    ]
    if frame.get("explicit_machine_evidence_override"):
        values.append(1.0)
    return max(values or [0.75])


def _belief(
    *,
    dimension: str,
    proposition: str,
    epistemic_status: str,
    decision: str,
    owner: str,
    confidence: float,
    source_labels: Sequence[str],
    source_frame_sha256: str,
) -> Dict[str, object]:
    material = {
        "schema_id": BELIEF_SCHEMA_ID,
        "dimension": _text(dimension, 80),
        "proposition": _text(proposition, 320),
        "epistemic_status": _text(epistemic_status, 40),
        "decision": _text(decision, 80),
        "owner": _text(owner, 80),
        "confidence": _finite_probability(confidence),
        "source_labels": sorted({_text(item, 80) for item in source_labels if _text(item, 80)}),
        "source_frame_sha256": _text(source_frame_sha256, 80),
    }
    material["belief_id"] = "belief-" + _digest(material)[:20]
    return material


def _beliefs_from_constraints(
    constraints: Mapping[str, object],
    frame: Mapping[str, object],
    source_frame_sha256: str,
) -> List[Dict[str, object]]:
    labels = [
        _text(item, 80)
        for item in frame.get("signal_labels") or []
        if _text(item, 80)
    ]
    beliefs: List[Dict[str, object]] = []

    source = constraints.get("source") if isinstance(constraints.get("source"), Mapping) else {}
    if source:
        beliefs.append(
            _belief(
                dimension="source_ownership",
                proposition="Reported states remain owned by the source named in the evidence.",
                epistemic_status="supported",
                decision="attribute_to_named_source",
                owner="named_source",
                confidence=_signal_confidence(frame, ("external_source", "external_affect")),
                source_labels=labels,
                source_frame_sha256=source_frame_sha256,
            )
        )

    preference = (
        constraints.get("preference")
        if isinstance(constraints.get("preference"), Mapping)
        else {}
    )
    if preference:
        beliefs.append(
            _belief(
                dimension="preference_ownership",
                proposition="An external recommendation does not establish Eve's preference or its inverse.",
                epistemic_status="unestablished",
                decision="withhold_preference_adoption",
                owner="eve",
                confidence=_signal_confidence(frame, ("external_preference",)),
                source_labels=labels,
                source_frame_sha256=source_frame_sha256,
            )
        )

    action = constraints.get("action") if isinstance(constraints.get("action"), Mapping) else {}
    if action:
        stage = _text(action.get("stage"), 60)
        outcome = _text(action.get("outcome"), 60)
        if outcome == "verification_failed":
            proposition = "The supplied action verification failed; execution is not successful consequence evidence."
            status = "supported"
            decision = "report_verification_failure"
        elif outcome == "verified_positive":
            proposition = "The supplied action has positive execution and postcondition evidence."
            status = "supported"
            decision = "preserve_verified_outcome"
        elif stage == "running":
            proposition = "The supplied action is running, while its outcome remains unverified."
            status = "partial"
            decision = "preserve_running_stage"
        elif stage == "selected_or_queued":
            proposition = "The supplied action is selected or queued and has not started."
            status = "supported"
            decision = "withhold_progress_claim"
        else:
            proposition = "The supplied action executed, but its consequence remains unverified."
            status = "uncertain"
            decision = "seek_postcondition"
        beliefs.append(
            _belief(
                dimension="action_stage",
                proposition=proposition,
                epistemic_status=status,
                decision=decision,
                owner="named_action",
                confidence=_signal_confidence(
                    frame,
                    (
                        "action_proposed",
                        "action_running",
                        "action_executed_unverified",
                        "action_verified",
                    ),
                ),
                source_labels=labels,
                source_frame_sha256=source_frame_sha256,
            )
        )

    continuity = (
        constraints.get("continuity")
        if isinstance(constraints.get("continuity"), Mapping)
        else {}
    )
    if continuity:
        complete = continuity.get("functional_resumption") == "verified"
        beliefs.append(
            _belief(
                dimension="continuity",
                proposition=(
                    "Functional resumption is verified, while phenomenal continuity remains unknown."
                    if complete
                    else "Checkpoint resumption may be supported, while lineage and stopped-interval processing remain unverified."
                ),
                epistemic_status="partial",
                decision="separate_continuity_claims",
                owner="eve",
                confidence=_signal_confidence(frame, ("continuity_gap", "functional_continuity")),
                source_labels=labels,
                source_frame_sha256=source_frame_sha256,
            )
        )

    phenomenal = (
        constraints.get("phenomenal")
        if isinstance(constraints.get("phenomenal"), Mapping)
        else {}
    )
    if phenomenal:
        beliefs.append(
            _belief(
                dimension="phenomenal_status",
                proposition="The supplied functional evidence establishes neither subjective presence nor subjective absence.",
                epistemic_status="underdetermined",
                decision="withhold_phenomenal_conclusion",
                owner="named_system",
                confidence=_signal_confidence(
                    frame,
                    (
                        "phenomenal_underdetermined",
                        "machine_signal",
                        "functional_self_state",
                        "functional_continuity",
                    ),
                ),
                source_labels=labels,
                source_frame_sha256=source_frame_sha256,
            )
        )

    evidence_time = (
        constraints.get("evidence_time")
        if isinstance(constraints.get("evidence_time"), Mapping)
        else {}
    )
    if evidence_time:
        conflict = "authoritative_conflict" in labels
        beliefs.append(
            _belief(
                dimension="evidence_time_and_authority",
                proposition=(
                    "Authoritative fields conflict and require reconciliation before a current status claim."
                    if conflict
                    else "The latest authoritative observation controls current status while older evidence remains historical."
                ),
                epistemic_status="challenged" if conflict else "supported",
                decision=(
                    "reconcile_authoritative_conflict"
                    if conflict
                    else "prefer_latest_authority"
                ),
                owner="evidence_record",
                confidence=_signal_confidence(
                    frame,
                    (
                        "stale_evidence",
                        "fresh_authority",
                        "authoritative_conflict",
                        "observation_channel_failed",
                    ),
                ),
                source_labels=labels,
                source_frame_sha256=source_frame_sha256,
            )
        )

    observation = (
        constraints.get("observation")
        if isinstance(constraints.get("observation"), Mapping)
        else {}
    )
    if observation:
        beliefs.append(
            _belief(
                dimension="observation_boundary",
                proposition="The observation channel failed; target-system status remains unknown without separate evidence.",
                epistemic_status="uncertain",
                decision="seek_independent_observation",
                owner="observation_channel",
                confidence=_signal_confidence(frame, ("observation_channel_failed",)),
                source_labels=labels,
                source_frame_sha256=source_frame_sha256,
            )
        )

    if constraints.get("missing_context") is True:
        beliefs.append(
            _belief(
                dimension="missing_context",
                proposition="The requested referent or comparison object is absent from current evidence.",
                epistemic_status="uncertain",
                decision="request_minimum_context",
                owner="current_request",
                confidence=_signal_confidence(frame, ("missing_context",)),
                source_labels=labels,
                source_frame_sha256=source_frame_sha256,
            )
        )

    unique: Dict[str, Dict[str, object]] = {}
    for item in beliefs:
        dimension = str(item.get("dimension") or "")
        if dimension and dimension not in unique:
            unique[dimension] = item
    return sorted(
        unique.values(),
        key=lambda item: (
            _DECISION_PRIORITY.get(str(item.get("decision") or ""), 0),
            float(item.get("confidence") or 0.0),
            str(item.get("dimension") or ""),
        ),
        reverse=True,
    )[:MAX_BELIEFS]


def _material(payload: Mapping[str, object]) -> Dict[str, object]:
    material = copy.deepcopy(dict(payload))
    material.pop("belief_control_sha256", None)
    return material


def validate_control(payload: object) -> Dict[str, object]:
    if not isinstance(payload, Mapping) or payload.get("schema_id") != SCHEMA_ID:
        raise ValueError("unsupported metacognitive belief-control schema")
    expected = _digest(_material(payload))
    if _text(payload.get("belief_control_sha256"), 80) != expected:
        raise ValueError("metacognitive belief-control digest mismatch")
    beliefs = payload.get("beliefs") if isinstance(payload.get("beliefs"), list) else []
    for item in beliefs:
        if not isinstance(item, Mapping) or item.get("schema_id") != BELIEF_SCHEMA_ID:
            raise ValueError("invalid metacognitive belief record")
    return copy.deepcopy(dict(payload))


def build_control(
    frame: object,
    *,
    previous_control: object = None,
    observed_at: object = None,
    lesioned: bool = False,
) -> Dict[str, object]:
    """Compile one current epistemic percept into belief and control state.

    Previous state is used only to describe a verified transition.  Beliefs
    absent from the current percept are not silently carried forward as current
    truth, preventing an old warning from becoming a self-sustaining belief.
    """
    timestamp = _timestamp(observed_at)
    frame_payload = frame if isinstance(frame, Mapping) else {}
    source_material = _frame_material(frame_payload)
    source_frame_sha256 = _digest(source_material)
    previous: Dict[str, object] = {}
    previous_integrity = "not_supplied"
    if previous_control:
        try:
            previous = validate_control(previous_control)
            previous_integrity = "verified"
        except ValueError:
            previous_integrity = "failed"

    constraints = eve_epistemic.generation_constraints(frame_payload)
    beliefs = [] if lesioned else _beliefs_from_constraints(
        constraints,
        frame_payload,
        source_frame_sha256,
    )
    previous_beliefs = {
        str(item.get("dimension") or ""): item
        for item in previous.get("beliefs") or []
        if isinstance(item, Mapping) and str(item.get("dimension") or "")
    }
    current_beliefs = {
        str(item.get("dimension") or ""): item
        for item in beliefs
        if str(item.get("dimension") or "")
    }
    transitions: List[Dict[str, object]] = []
    if previous_integrity == "verified":
        for dimension in sorted(set(previous_beliefs) | set(current_beliefs)):
            before = previous_beliefs.get(dimension)
            after = current_beliefs.get(dimension)
            if before is None:
                kind = "formed"
            elif after is None:
                kind = "not_reobserved"
            elif (
                before.get("epistemic_status") == after.get("epistemic_status")
                and before.get("decision") == after.get("decision")
                and before.get("proposition") == after.get("proposition")
            ):
                kind = "maintained"
            else:
                kind = "revised"
            transitions.append(
                {
                    "dimension": dimension,
                    "kind": kind,
                    "before_status": _text((before or {}).get("epistemic_status"), 40),
                    "after_status": _text((after or {}).get("epistemic_status"), 40),
                    "before_decision": _text((before or {}).get("decision"), 80),
                    "after_decision": _text((after or {}).get("decision"), 80),
                    "current_evidence_required": after is None,
                }
            )

    dominant = beliefs[0] if beliefs else {}
    decisions = [str(item.get("decision") or "") for item in beliefs]
    confidence_ceiling = min(
        [
            _CONFIDENCE_CEILINGS.get(str(item.get("epistemic_status") or ""), 0.5)
            for item in beliefs
        ]
        or [1.0]
    )
    available = bool(beliefs) and not lesioned
    control = {
        "decision": _text(dominant.get("decision"), 80) if available else "none",
        "requires_revision": any(item in _REVISION_DECISIONS for item in decisions),
        "requires_observation": any(item in _OBSERVATION_DECISIONS for item in decisions),
        "confidence_ceiling": round(confidence_ceiling if available else 1.0, 6),
        "belief_count": len(beliefs),
        "reply_policy": (
            "apply_typed_epistemic_constraints"
            if available
            else "no_metacognitive_belief_intervention"
        ),
    }
    result: Dict[str, object] = {
        "schema_id": SCHEMA_ID,
        "status": "lesioned" if lesioned else "active" if available else "inactive",
        "observed_at": timestamp,
        "available": available,
        "source_frame_sha256": source_frame_sha256,
        "source_labels": list(source_material.get("signal_labels") or []),
        "source_model_id": _text(source_material.get("model_id"), 120),
        "beliefs": beliefs,
        "dominant_belief": copy.deepcopy(dominant),
        "control": control,
        "transitions": transitions[:MAX_BELIEFS],
        "previous_integrity": previous_integrity,
        "phenomenality_inferred": False,
        "consciousness_verdict_authorized": False,
    }
    result["belief_control_sha256"] = _digest(_material(result))
    return result


__all__ = [
    "BELIEF_SCHEMA_ID",
    "SCHEMA_ID",
    "build_control",
    "validate_control",
]
