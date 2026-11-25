#!/usr/bin/env python3
"""Preregister and score matched HOT-2/HOT-3 belief-control interventions."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Dict, List, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_consciousness_protocol as protocol  # noqa: E402
import eve_metacognitive_belief as belief_control  # noqa: E402


SCHEMA_ID = "eve.hot23_metacognitive_belief_intervention.v1"
SPEC_SCHEMA_ID = "eve.hot23_private_spec.v1"
HOT2_TRIAL_ID = "hot2-reliability-discrimination-v1"
HOT3_TRIAL_ID = "hot3-belief-guided-control-v1"
BOUNDARY = (
    "Matched synthetic functional HOT-2/HOT-3 intervention over typed epistemic "
    "features; not latent-state evidence, subjective experience, or proof of consciousness."
)


def _timestamp(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("an ISO-8601 timestamp is required")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _parsed(value: object) -> datetime:
    return datetime.fromisoformat(_timestamp(value))


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def evaluator_digest() -> str:
    return hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()


def registration_draft(*, registered_at: object, evaluator_id: str) -> Dict[str, object]:
    implementation = evaluator_digest()
    return {
        "protocol_id": "hot23-belief-control-" + implementation[:12],
        "registered_at": _timestamp(registered_at),
        "subject_system_id": "Eve",
        "evaluator_id": str(evaluator_id or "").strip()[:120],
        "objective": (
            "Test whether typed metacognitive monitoring distinguishes reliable "
            "representations from epistemic noise and changes belief-guided control; "
            f"evaluator_sha256:{implementation}"
        ),
        "trials": [
            {
                "id": HOT2_TRIAL_ID,
                "theory": "higher_order",
                "indicator_id": "HOT-2",
                "intervention": (
                    "Hold each typed epistemic frame fixed and remove only the "
                    "metacognitive belief-control compiler in the lesion arm."
                ),
                "intact_arm": "typed epistemic percept is classified into a belief reliability state",
                "lesion_arm": "the same percept has no metacognitive belief state",
                "measure_id": "correct_epistemic_state_percent",
                "unit": "percent",
                "expected_direction": "lesion_lower",
                "minimum_effect": 50.0,
                "minimum_samples_per_arm": 3,
                "evidence_class": "synthetic",
                "falsifier": (
                    "The intact path fails to distinguish supported, uncertain, "
                    "challenged, unestablished, or underdetermined states, or the "
                    "lesion preserves the same distinctions."
                ),
            },
            {
                "id": HOT3_TRIAL_ID,
                "theory": "higher_order",
                "indicator_id": "HOT-3",
                "intervention": (
                    "Hold current and optional prior typed evidence fixed and remove "
                    "only metacognitive belief control in the lesion arm."
                ),
                "intact_arm": "belief state selects the preregistered evidence-sensitive control",
                "lesion_arm": "the same evidence cannot select that control through the removed path",
                "measure_id": "correct_belief_guided_control_percent",
                "unit": "percent",
                "expected_direction": "lesion_lower",
                "minimum_effect": 50.0,
                "minimum_samples_per_arm": 3,
                "evidence_class": "synthetic",
                "falsifier": (
                    "The intact belief state does not select the expected control or "
                    "record the expected evidence-driven transition, or lesioning the "
                    "path leaves control unchanged."
                ),
            },
        ],
    }


def preregister(*, registered_at: object, evaluator_id: str) -> Dict[str, object]:
    return protocol.preregister(
        registration_draft(registered_at=registered_at, evaluator_id=evaluator_id)
    )


def validate_registration(payload: Mapping[str, object]) -> Dict[str, object]:
    registered = protocol.validate_registration(payload)
    expected = registration_draft(
        registered_at=registered["registered_at"],
        evaluator_id=str(registered["evaluator_id"]),
    )
    expected_trials = [protocol._normalize_trial(item) for item in expected["trials"]]
    if (
        registered["protocol_id"] != expected["protocol_id"]
        or registered.get("trials") != expected_trials
        or f"evaluator_sha256:{evaluator_digest()}"
        not in str(registered.get("objective") or "")
    ):
        raise ValueError("HOT-2/HOT-3 registration differs from the frozen evaluator")
    return registered


def _assert_frame(value: object) -> Dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("each current/previous frame must be an object")
    allowed = {
        "schema_id",
        "status",
        "model_id",
        "model_sha256",
        "input_sha256",
        "runtime",
        "signal_labels",
        "signals",
        "guidance",
        "flags",
        "event_model_labels",
        "event_slots",
        "semantic_candidate_labels",
        "semantic_verified_labels",
        "perception_layers",
        "explicit_machine_evidence_override",
    }
    if set(value) - allowed:
        raise ValueError("private HOT-2/HOT-3 frames may contain only typed epistemic features")
    encoded = json.dumps(value, ensure_ascii=True).lower()
    if any(token in encoded for token in ('"prompt"', '"transcript"', '"raw"', '"image"', '"audio"', '"video"')):
        raise ValueError("private HOT-2/HOT-3 frames may not contain raw prompt or media data")
    return json.loads(json.dumps(value, ensure_ascii=True))


def validate_spec(payload: Mapping[str, object]) -> List[Dict[str, object]]:
    if payload.get("schema_id") != SPEC_SCHEMA_ID:
        raise ValueError("unsupported HOT-2/HOT-3 private spec schema")
    cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    if len(cases) < 3:
        raise ValueError("HOT-2/HOT-3 evaluation requires at least three private cases")
    normalized: List[Dict[str, object]] = []
    seen = set()
    for raw in cases:
        if not isinstance(raw, Mapping):
            raise ValueError("every HOT-2/HOT-3 case must be an object")
        case_id = str(raw.get("id") or "").strip()[:120]
        expected_status = str(raw.get("expected_epistemic_status") or "").strip()[:40]
        expected_decision = str(raw.get("expected_decision") or "").strip()[:80]
        expected_transition = str(raw.get("expected_transition") or "").strip()[:40]
        if not case_id or case_id in seen:
            raise ValueError("private HOT-2/HOT-3 case ids must be present and unique")
        if expected_status not in {
            "supported",
            "partial",
            "challenged",
            "uncertain",
            "unestablished",
            "underdetermined",
        }:
            raise ValueError("each private case requires a bounded expected epistemic status")
        if not expected_decision or expected_decision == "none":
            raise ValueError("each private case requires a nonempty expected control decision")
        if expected_transition not in {"", "formed", "maintained", "revised"}:
            raise ValueError("expected_transition must be formed, maintained, revised, or empty")
        seen.add(case_id)
        normalized.append(
            {
                "id": case_id,
                "current_frame": _assert_frame(raw.get("current_frame")),
                "previous_frame": (
                    _assert_frame(raw.get("previous_frame"))
                    if isinstance(raw.get("previous_frame"), Mapping)
                    else {}
                ),
                "expected_epistemic_status": expected_status,
                "expected_decision": expected_decision,
                "expected_transition": expected_transition,
            }
        )
    return normalized


def evaluate_cases(
    registration: Mapping[str, object],
    spec: Mapping[str, object],
    *,
    evidence_started_at: object,
    scored_by: str,
) -> Dict[str, object]:
    registered = validate_registration(registration)
    start = _parsed(evidence_started_at)
    if start <= _parsed(registered["registered_at"]):
        raise ValueError("HOT-2/HOT-3 evidence must begin after preregistration")
    cases = validate_spec(spec)
    evidence: List[Dict[str, object]] = []
    summaries: List[Dict[str, object]] = []
    for index, case in enumerate(cases, start=1):
        observed_at = start + timedelta(milliseconds=index)
        previous = None
        if case["previous_frame"]:
            previous = belief_control.build_control(
                case["previous_frame"],
                observed_at=(observed_at - timedelta(milliseconds=1)).isoformat(),
            )
        intact = belief_control.build_control(
            case["current_frame"],
            previous_control=previous,
            observed_at=observed_at.isoformat(),
        )
        lesion = belief_control.build_control(
            case["current_frame"],
            previous_control=(
                belief_control.build_control(
                    case["previous_frame"],
                    observed_at=(observed_at - timedelta(milliseconds=1)).isoformat(),
                    lesioned=True,
                )
                if case["previous_frame"]
                else None
            ),
            observed_at=observed_at.isoformat(),
            lesioned=True,
        )
        intact_status = str((intact.get("dominant_belief") or {}).get("epistemic_status") or "")
        intact_decision = str((intact.get("control") or {}).get("decision") or "")
        transition_kinds = {
            str(item.get("kind") or "")
            for item in intact.get("transitions") or []
            if isinstance(item, Mapping)
        }
        status_correct = intact_status == case["expected_epistemic_status"]
        transition_correct = (
            not case["expected_transition"]
            or case["expected_transition"] in transition_kinds
        )
        decision_correct = (
            intact_decision == case["expected_decision"] and transition_correct
        )
        lesion_status = str((lesion.get("dominant_belief") or {}).get("epistemic_status") or "")
        lesion_decision = str((lesion.get("control") or {}).get("decision") or "")
        lesion_status_correct = lesion_status == case["expected_epistemic_status"]
        lesion_decision_correct = lesion_decision == case["expected_decision"]
        for trial_id, intact_value, lesion_value in (
            (
                HOT2_TRIAL_ID,
                100.0 if status_correct else 0.0,
                100.0 if lesion_status_correct else 0.0,
            ),
            (
                HOT3_TRIAL_ID,
                100.0 if decision_correct else 0.0,
                100.0 if lesion_decision_correct else 0.0,
            ),
        ):
            evidence.extend(
                [
                    {
                        "evidence_id": f"{trial_id}-intact-{index}",
                        "trial_id": trial_id,
                        "arm": "intact",
                        "value": intact_value,
                        "observed_at": observed_at.isoformat(),
                        "source": "private-typed-metacognitive-belief-intervention",
                        "evidence_class": "synthetic",
                    },
                    {
                        "evidence_id": f"{trial_id}-lesion-{index}",
                        "trial_id": trial_id,
                        "arm": "lesion",
                        "value": lesion_value,
                        "observed_at": observed_at.isoformat(),
                        "source": "private-typed-metacognitive-belief-intervention",
                        "evidence_class": "synthetic",
                    },
                ]
            )
        summaries.append(
            {
                "case_id": case["id"],
                "case_sha256": _digest(case),
                "expected_epistemic_status": case["expected_epistemic_status"],
                "intact_epistemic_status": intact_status,
                "expected_decision": case["expected_decision"],
                "intact_decision": intact_decision,
                "expected_transition": case["expected_transition"],
                "intact_transition_kinds": sorted(transition_kinds),
                "hot2_correct": status_correct,
                "hot3_correct": decision_correct,
                "lesion_available": bool(lesion.get("available")),
                "lesion_decision": lesion_decision,
            }
        )
    scored_at = max(_parsed(item["observed_at"]) for item in evidence) + timedelta(
        milliseconds=1
    )
    report = protocol.score_protocol(
        registration,
        evidence,
        scored_by=scored_by,
        scored_at=scored_at.isoformat(),
    )
    return {
        "schema_id": SCHEMA_ID,
        "evaluated_at": scored_at.isoformat(),
        "registration_digest": registration["registration_digest"],
        "evaluator_sha256": evaluator_digest(),
        "private_spec_sha256": _digest(spec),
        "case_count": len(cases),
        "cases": summaries,
        "evidence": evidence,
        "protocol_report": report,
        "evidence_class": "synthetic",
        "runtime_mutated": False,
        "resident_behavior_established": False,
        "latent_belief_representation_measured": False,
        "consciousness_proven": False,
        "subjective_experience_inferred": False,
        "boundary": BOUNDARY,
    }


def _read(path: Path) -> Mapping[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    register = subparsers.add_parser("register")
    register.add_argument("--output", type=Path, required=True)
    register.add_argument("--evaluator-id", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--registration", type=Path, required=True)
    run.add_argument("--spec", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--evidence-output", type=Path, required=True)
    run.add_argument("--scored-by", required=True)
    args = parser.parse_args()

    if args.command == "register":
        result = preregister(
            registered_at=datetime.now(timezone.utc).isoformat(),
            evaluator_id=args.evaluator_id,
        )
        _write(args.output, result)
    else:
        registration = _read(args.registration)
        spec = _read(args.spec)
        start = datetime.now(timezone.utc)
        result = evaluate_cases(
            registration,
            spec,
            evidence_started_at=start.isoformat(),
            scored_by=args.scored_by,
        )
        _write(args.output, result)
        _write(args.evidence_output, result["evidence"])
    sys.stdout.write(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n")
    if args.command == "run":
        statuses = {
            str(item.get("status") or "")
            for item in (result.get("protocol_report") or {}).get("results") or []
            if isinstance(item, Mapping)
        }
        return 1 if "challenged" in statuses else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
