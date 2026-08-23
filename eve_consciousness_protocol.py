"""Preregistered, theory-specific intervention evidence for Eve.

This module deliberately cannot return a positive consciousness verdict.  It
tests whether named architectural indicators behave as predicted under a
precommitted lesion or intervention.  That is stronger than self-description
and weaker than evidence of subjective experience, for which no artificial
ground-truth calibration currently exists.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Dict, Iterable, List, Mapping, Optional


REGISTRATION_SCHEMA = "eve.consciousness_indicator_registration.v1"
REPORT_SCHEMA = "eve.consciousness_indicator_report.v1"

THEORY_INDICATORS = {
    "recurrent_processing": {"RPT-1", "RPT-2"},
    "global_workspace": {"GWT-1", "GWT-2", "GWT-3", "GWT-4"},
    "higher_order": {"HOT-1", "HOT-2", "HOT-3", "HOT-4"},
    "attention_schema": {"AST-1"},
    "predictive_processing": {"PP-1"},
    "agency_embodiment": {"AE-1", "AE-2"},
}
ALL_INDICATORS = frozenset().union(*THEORY_INDICATORS.values())
EXPECTED_DIRECTIONS = {"lesion_lower", "lesion_higher"}
EVIDENCE_CLASSES = {"synthetic", "lived"}
FORBIDDEN_MEASURE_TOKENS = {
    "claims_conscious",
    "consciousness_claim",
    "feels_conscious",
    "introspection_text",
    "says_conscious",
    "self_report",
}
RAW_EVIDENCE_KEYS = {
    "audio",
    "frame",
    "image",
    "pixels",
    "prompt",
    "raw",
    "raw_payload",
    "transcript",
    "video",
}


def _text(value: object, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def _timestamp(value: object) -> str:
    text = _text(value, 80)
    if not text:
        raise ValueError("an ISO-8601 timestamp is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _parsed(value: object) -> datetime:
    return datetime.fromisoformat(_timestamp(value))


def _finite_number(value: object, *, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def _contains_raw_evidence(value: object) -> bool:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = _text(raw_key, 80).lower().replace("-", "_")
            if key in RAW_EVIDENCE_KEYS or _contains_raw_evidence(child):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_raw_evidence(item) for item in value)
    return False


def _canonical_digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _normalize_trial(payload: Mapping[str, object]) -> Dict[str, object]:
    trial_id = _text(payload.get("id"), 120)
    theory = _text(payload.get("theory"), 80).lower().replace("-", "_").replace(" ", "_")
    indicator_id = _text(payload.get("indicator_id"), 24).upper()
    measure_id = _text(payload.get("measure_id"), 120).lower().replace(" ", "_")
    direction = _text(payload.get("expected_direction"), 40).lower()
    intervention = _text(payload.get("intervention"), 320)
    falsifier = _text(payload.get("falsifier"), 320)
    if not trial_id or theory not in THEORY_INDICATORS:
        raise ValueError("each trial requires an id and known theory")
    if indicator_id not in THEORY_INDICATORS[theory]:
        raise ValueError(f"indicator {indicator_id or 'missing'} does not belong to theory {theory}")
    if not measure_id or any(token in measure_id for token in FORBIDDEN_MEASURE_TOKENS):
        raise ValueError("self-report or consciousness-claim measures are not admissible")
    if direction not in EXPECTED_DIRECTIONS:
        raise ValueError("expected_direction must be lesion_lower or lesion_higher")
    if not intervention or not falsifier:
        raise ValueError("intervention and falsifier must be fixed before evidence collection")
    minimum_effect = _finite_number(payload.get("minimum_effect"), name="minimum_effect")
    if minimum_effect <= 0:
        raise ValueError("minimum_effect must be positive")
    try:
        minimum_samples = int(payload.get("minimum_samples_per_arm") or 3)
    except (TypeError, ValueError) as exc:
        raise ValueError("minimum_samples_per_arm must be an integer") from exc
    if minimum_samples < 2:
        raise ValueError("minimum_samples_per_arm must be at least 2")
    evidence_class = _text(payload.get("evidence_class"), 20).lower()
    if evidence_class not in EVIDENCE_CLASSES:
        raise ValueError("evidence_class must be synthetic or lived")
    return {
        "id": trial_id,
        "theory": theory,
        "indicator_id": indicator_id,
        "intervention": intervention,
        "intact_arm": _text(payload.get("intact_arm"), 180) or "intact",
        "lesion_arm": _text(payload.get("lesion_arm"), 180) or "lesion",
        "measure_id": measure_id,
        "unit": _text(payload.get("unit"), 60) or "score",
        "expected_direction": direction,
        "minimum_effect": minimum_effect,
        "minimum_samples_per_arm": minimum_samples,
        "evidence_class": evidence_class,
        "falsifier": falsifier,
    }


def _registration_material(payload: Mapping[str, object]) -> Dict[str, object]:
    trials = payload.get("trials") if isinstance(payload.get("trials"), list) else []
    return {
        "schema_version": REGISTRATION_SCHEMA,
        "protocol_id": _text(payload.get("protocol_id"), 120),
        "registered_at": _timestamp(payload.get("registered_at")),
        "subject_system_id": _text(payload.get("subject_system_id"), 120),
        "evaluator_id": _text(payload.get("evaluator_id"), 120),
        "objective": _text(payload.get("objective"), 320),
        "trials": [_normalize_trial(item) for item in trials if isinstance(item, Mapping)],
    }


def preregister(payload: Mapping[str, object]) -> Dict[str, object]:
    """Create an immutable registration before any evidence is observed."""
    if not isinstance(payload, Mapping) or _contains_raw_evidence(payload):
        raise ValueError("registration must be structured and contain no raw evidence")
    material = _registration_material(payload)
    if not material["protocol_id"] or not material["subject_system_id"] or not material["evaluator_id"]:
        raise ValueError("protocol_id, subject_system_id, and evaluator_id are required")
    if material["subject_system_id"].lower() == material["evaluator_id"].lower():
        raise ValueError("the evaluator must be distinct from the system under test")
    if not material["objective"] or not material["trials"]:
        raise ValueError("objective and at least one trial are required")
    trial_ids = [str(item["id"]) for item in material["trials"]]
    if len(trial_ids) != len(set(trial_ids)):
        raise ValueError("trial ids must be unique")
    result = copy.deepcopy(material)
    result.update(
        {
            "status": "preregistered",
            "registration_digest": _canonical_digest(material),
            "authority": "external_theory_specific_protocol",
            "consciousness_verdict_authorized": False,
        }
    )
    return result


def validate_registration(payload: Mapping[str, object]) -> Dict[str, object]:
    material = _registration_material(payload)
    expected = _canonical_digest(material)
    actual = _text(payload.get("registration_digest"), 80)
    if payload.get("schema_version") != REGISTRATION_SCHEMA or actual != expected:
        raise ValueError("registration digest mismatch; protocol may have changed after preregistration")
    if material["subject_system_id"].lower() == material["evaluator_id"].lower():
        raise ValueError("the evaluator must remain distinct from the system under test")
    return {**material, "registration_digest": expected}


def _normalize_evidence(payload: Mapping[str, object]) -> Dict[str, object]:
    if _contains_raw_evidence(payload):
        raise ValueError("raw evidence is outside this aggregate protocol")
    arm = _text(payload.get("arm"), 20).lower()
    if arm not in {"intact", "lesion"}:
        raise ValueError("evidence arm must be intact or lesion")
    evidence_class = _text(payload.get("evidence_class"), 20).lower()
    if evidence_class not in EVIDENCE_CLASSES:
        raise ValueError("evidence_class must be synthetic or lived")
    record = {
        "evidence_id": _text(payload.get("evidence_id"), 120),
        "trial_id": _text(payload.get("trial_id"), 120),
        "arm": arm,
        "value": _finite_number(payload.get("value"), name="evidence value"),
        "observed_at": _timestamp(payload.get("observed_at")),
        "source": _text(payload.get("source"), 160),
        "evidence_class": evidence_class,
    }
    if not record["evidence_id"] or not record["trial_id"] or not record["source"]:
        raise ValueError("evidence_id, trial_id, and source are required")
    return record


def score_protocol(
    registration: Mapping[str, object],
    evidence: Iterable[Mapping[str, object]],
    *,
    scored_by: str,
    scored_at: object,
) -> Dict[str, object]:
    """Score preregistered indicator predictions without a consciousness pass."""
    registered = validate_registration(registration)
    scorer = _text(scored_by, 120)
    if not scorer or scorer.lower() == str(registered["subject_system_id"]).lower():
        raise ValueError("scoring must be performed by an evaluator distinct from the subject")
    scored_timestamp = _timestamp(scored_at)
    registered_at = _parsed(registered["registered_at"])
    records = [_normalize_evidence(item) for item in evidence if isinstance(item, Mapping)]
    evidence_ids = [str(item["evidence_id"]) for item in records]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("evidence ids must be unique")
    for record in records:
        if _parsed(record["observed_at"]) <= registered_at:
            raise ValueError("all evidence must be observed after preregistration")

    results: List[Dict[str, object]] = []
    known_trial_ids = {str(item["id"]) for item in registered["trials"]}
    unknown_trial_ids = sorted({str(item["trial_id"]) for item in records} - known_trial_ids)
    if unknown_trial_ids:
        raise ValueError("evidence references an unregistered trial")
    for trial in registered["trials"]:
        trial_records = [
            item
            for item in records
            if item["trial_id"] == trial["id"]
            and item["evidence_class"] == trial["evidence_class"]
        ]
        wrong_class_count = sum(
            1
            for item in records
            if item["trial_id"] == trial["id"]
            and item["evidence_class"] != trial["evidence_class"]
        )
        intact = [float(item["value"]) for item in trial_records if item["arm"] == "intact"]
        lesion = [float(item["value"]) for item in trial_records if item["arm"] == "lesion"]
        minimum_samples = int(trial["minimum_samples_per_arm"])
        if len(intact) < minimum_samples or len(lesion) < minimum_samples:
            results.append(
                {
                    **trial,
                    "status": "inconclusive",
                    "reason": "insufficient preregistered arm samples",
                    "intact_count": len(intact),
                    "lesion_count": len(lesion),
                    "wrong_evidence_class_count": wrong_class_count,
                }
            )
            continue
        intact_mean = sum(intact) / len(intact)
        lesion_mean = sum(lesion) / len(lesion)
        effect = (
            intact_mean - lesion_mean
            if trial["expected_direction"] == "lesion_lower"
            else lesion_mean - intact_mean
        )
        threshold = float(trial["minimum_effect"])
        if effect >= threshold:
            status = "supported"
            reason = "preregistered directional effect met the threshold"
        elif effect <= -threshold:
            status = "challenged"
            reason = "effect crossed the threshold opposite the preregistered prediction"
        else:
            status = "inconclusive"
            reason = "effect did not reach the preregistered threshold"
        results.append(
            {
                **trial,
                "status": status,
                "reason": reason,
                "intact_count": len(intact),
                "lesion_count": len(lesion),
                "intact_mean": round(intact_mean, 6),
                "lesion_mean": round(lesion_mean, 6),
                "directional_effect": round(effect, 6),
                "wrong_evidence_class_count": wrong_class_count,
                "evidence_ids": [str(item["evidence_id"]) for item in trial_records],
            }
        )

    counts = {
        status: sum(1 for item in results if item["status"] == status)
        for status in ("supported", "challenged", "inconclusive")
    }
    observed_indicators = sorted({str(item["indicator_id"]) for item in results})
    theory_coverage = {
        theory: sorted(
            str(item["indicator_id"])
            for item in results
            if item["theory"] == theory
        )
        for theory in THEORY_INDICATORS
    }
    return {
        "schema_version": REPORT_SCHEMA,
        "protocol_id": registered["protocol_id"],
        "registration_digest": registered["registration_digest"],
        "registered_at": registered["registered_at"],
        "scored_at": scored_timestamp,
        "subject_system_id": registered["subject_system_id"],
        "evaluator_id": registered["evaluator_id"],
        "scored_by": scorer,
        "status": "indicator_evidence_recorded",
        "counts": counts,
        "indicator_coverage": {
            "observed": len(observed_indicators),
            "total_framework_indicators": len(ALL_INDICATORS),
            "indicator_ids": observed_indicators,
            "theories": theory_coverage,
        },
        "results": results,
        "consciousness_proven": False,
        "subjective_experience_inferred": False,
        "phenomenality_calibrated": False,
        "verdict": "not_a_consciousness_verdict",
        "calibration_limit": (
            "Theory-specific architectural effects lack artificial phenomenality ground truth; "
            "support for indicators must not be converted into a probability or proof of subjective experience."
        ),
    }

