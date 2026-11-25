#!/usr/bin/env python3
"""Preregister and score RPT-1/RPT-2 sensory intact-versus-lesion trials."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Dict, List, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_consciousness_protocol as protocol  # noqa: E402
import eve_sensory  # noqa: E402


SCHEMA_ID = "eve.rpt12_recurrent_perceptual_intervention.v1"
SPEC_SCHEMA_ID = "eve.rpt12_private_spec.v1"
RPT1_TRIAL_ID = "rpt1-input-module-recurrence-v1"
RPT2_TRIAL_ID = "rpt2-perceptual-organization-v1"
BOUNDARY = (
    "Matched feature-only functional evidence for RPT-1 and RPT-2 software "
    "edges; not biological recurrence, phenomenal unity, subjective experience, "
    "or proof of consciousness."
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
_EVENT_FIELDS = {
    "id",
    "observed_at",
    "modality",
    "source",
    "subject",
    "correlation_id",
    "fingerprint",
    "features",
    "intensity",
    "novelty",
    "change",
    "urgency",
    "goal_relevance",
    "self_relevance",
    "social_relevance",
    "precision",
    "direct_human",
    "safety_critical",
    "permission_granted",
    "privacy",
}
_RPT1_STATES = {
    "first_observation",
    "habituated",
    "dishabituated",
    "predicted_change",
    "prediction_violation",
}


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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def implementation_manifest() -> Dict[str, str]:
    return {
        "evaluator": _sha256(Path(__file__).resolve()),
        "sensory_input_organ": _sha256(ROOT / "eve_sensory.py"),
        "protocol": _sha256(ROOT / "eve_consciousness_protocol.py"),
    }


def implementation_digest() -> str:
    return _digest(implementation_manifest())


def _identifier(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(text):
        raise ValueError(f"{field} must be a bounded non-prose identifier")
    return text


def _normalize_private_event(value: object) -> Dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("each private RPT event must be an object")
    if set(value) - _EVENT_FIELDS:
        raise ValueError("private RPT events may contain only typed feature fields")
    forbidden = eve_sensory.forbidden_ingest_paths(value)
    if forbidden:
        raise ValueError("private RPT events may not contain raw or high-dimensional data")
    event_id = _identifier(value.get("id"), "event id")
    modality = _identifier(value.get("modality"), "modality").lower()
    source = _identifier(value.get("source"), "source")
    subject = _identifier(value.get("subject"), "subject")
    fingerprint = _identifier(value.get("fingerprint"), "fingerprint")
    correlation = str(value.get("correlation_id") or "").strip()
    if correlation and not _IDENTIFIER.fullmatch(correlation):
        raise ValueError("correlation_id must be a bounded non-prose identifier")
    candidate = dict(value)
    candidate.update(
        {
            "schema_version": eve_sensory.EVENT_SCHEMA,
            "id": event_id,
            "observed_at": _timestamp(value.get("observed_at")),
            "modality": modality,
            "source": source,
            "subject": subject,
            "correlation_id": correlation,
            "fingerprint": fingerprint,
            "summary": f"Typed {modality} feature event.",
        }
    )
    normalized = eve_sensory.normalize_event(
        candidate,
        now=candidate["observed_at"],
    )
    return normalized


def _normalize_frame(value: object) -> List[Dict[str, object]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 8:
        raise ValueError("each private RPT frame requires one to eight typed events")
    events = [_normalize_private_event(item) for item in value]
    identifiers = [str(item["id"]) for item in events]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("event ids must be unique inside each private RPT frame")
    return events


def validate_spec(payload: Mapping[str, object]) -> Dict[str, object]:
    if payload.get("schema_id") != SPEC_SCHEMA_ID:
        raise ValueError("unsupported RPT-1/RPT-2 private spec schema")
    raw_rpt1 = payload.get("rpt1_cases") if isinstance(payload.get("rpt1_cases"), list) else []
    raw_rpt2 = payload.get("rpt2_cases") if isinstance(payload.get("rpt2_cases"), list) else []
    if len(raw_rpt1) < 6 or len(raw_rpt2) < 6:
        raise ValueError("RPT-1/RPT-2 evaluation requires at least six cases per trial")

    seen = set()
    rpt1_cases: List[Dict[str, object]] = []
    for raw in raw_rpt1:
        if not isinstance(raw, Mapping):
            raise ValueError("every RPT-1 case must be an object")
        if set(raw) - {"id", "sequence", "expected_state"}:
            raise ValueError("RPT-1 cases may contain only id, sequence, and expected_state")
        case_id = _identifier(raw.get("id"), "RPT-1 case id")
        expected = str(raw.get("expected_state") or "").strip()
        sequence = raw.get("sequence") if isinstance(raw.get("sequence"), list) else []
        if case_id in seen:
            raise ValueError("private RPT case ids must be unique")
        if expected not in _RPT1_STATES:
            raise ValueError("RPT-1 cases require a bounded expected temporal state")
        if not 1 <= len(sequence) <= 8:
            raise ValueError("RPT-1 sequences require one to eight frames")
        frames = [_normalize_frame(frame) for frame in sequence]
        flat_ids = [str(item["id"]) for frame in frames for item in frame]
        if len(flat_ids) != len(set(flat_ids)):
            raise ValueError("event ids must be unique across an RPT-1 sequence")
        seen.add(case_id)
        rpt1_cases.append(
            {"id": case_id, "sequence": frames, "expected_state": expected}
        )

    rpt2_cases: List[Dict[str, object]] = []
    for raw in raw_rpt2:
        if not isinstance(raw, Mapping):
            raise ValueError("every RPT-2 case must be an object")
        if set(raw) - {"id", "events", "expected_bound", "expected_modalities"}:
            raise ValueError(
                "RPT-2 cases may contain only id, events, expected_bound, and expected_modalities"
            )
        case_id = _identifier(raw.get("id"), "RPT-2 case id")
        if case_id in seen:
            raise ValueError("private RPT case ids must be unique")
        if not isinstance(raw.get("expected_bound"), bool):
            raise ValueError("RPT-2 expected_bound must be Boolean")
        modalities = sorted(
            {
                _identifier(item, "expected modality").lower()
                for item in (raw.get("expected_modalities") or [])
            }
        )
        if raw["expected_bound"] and len(modalities) < 2:
            raise ValueError("bound RPT-2 cases require at least two expected modalities")
        seen.add(case_id)
        rpt2_cases.append(
            {
                "id": case_id,
                "events": _normalize_frame(raw.get("events")),
                "expected_bound": bool(raw["expected_bound"]),
                "expected_modalities": modalities,
            }
        )
    return {
        "schema_id": SPEC_SCHEMA_ID,
        "rpt1_cases": rpt1_cases,
        "rpt2_cases": rpt2_cases,
    }


def private_spec_digest(spec: Mapping[str, object]) -> str:
    return _digest(validate_spec(spec))


def registration_draft(
    *,
    registered_at: object,
    evaluator_id: str,
    private_spec_sha256: str,
) -> Dict[str, object]:
    implementation = implementation_digest()
    spec_digest = str(private_spec_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", spec_digest):
        raise ValueError("a valid private spec SHA-256 is required")
    return {
        "protocol_id": "rpt12-input-organization-" + implementation[:12],
        "registered_at": _timestamp(registered_at),
        "subject_system_id": "Eve",
        "evaluator_id": str(evaluator_id or "").strip()[:120],
        "objective": (
            f"implementation_sha256:{implementation};"
            f"private_spec_sha256:{spec_digest};"
            "Test bounded prior-input effects and co-referential cross-modal "
            "organization under matched lesions."
        ),
        "trials": [
            {
                "id": RPT1_TRIAL_ID,
                "theory": "recurrent_processing",
                "indicator_id": "RPT-1",
                "intervention": (
                    "Hold each typed event sequence fixed and prevent the input "
                    "organ from consuming its bounded prior frame in the lesion arm."
                ),
                "intact_arm": "current input classification can depend on bounded prior input state",
                "lesion_arm": "the same sequence is processed statelessly at every frame",
                "measure_id": "correct_temporal_input_state_percent",
                "unit": "percent",
                "expected_direction": "lesion_lower",
                "minimum_effect": 40.0,
                "minimum_samples_per_arm": 6,
                "evidence_class": "synthetic",
                "falsifier": (
                    "Intact recurrence does not improve preregistered temporal-state "
                    "classification, or the stateless lesion preserves the effect."
                ),
            },
            {
                "id": RPT2_TRIAL_ID,
                "theory": "recurrent_processing",
                "indicator_id": "RPT-2",
                "intervention": (
                    "Hold simultaneous typed feature events fixed and remove only "
                    "entity tracking and cross-modal episode organization."
                ),
                "intact_arm": "co-referential events form bounded organized representations",
                "lesion_arm": "the same events remain separate unorganized candidates",
                "measure_id": "correct_integrated_episode_classification_percent",
                "unit": "percent",
                "expected_direction": "lesion_lower",
                "minimum_effect": 40.0,
                "minimum_samples_per_arm": 6,
                "evidence_class": "synthetic",
                "falsifier": (
                    "Intact organization fails positive or negative binding cases, "
                    "or lesioning organization preserves the same integrated episodes."
                ),
            },
        ],
    }


def preregister(
    *,
    registered_at: object,
    evaluator_id: str,
    spec: Mapping[str, object],
) -> Dict[str, object]:
    return protocol.preregister(
        registration_draft(
            registered_at=registered_at,
            evaluator_id=evaluator_id,
            private_spec_sha256=private_spec_digest(spec),
        )
    )


def validate_registration(
    payload: Mapping[str, object],
    spec: Mapping[str, object],
) -> Dict[str, object]:
    registered = protocol.validate_registration(payload)
    spec_digest = private_spec_digest(spec)
    expected = registration_draft(
        registered_at=registered["registered_at"],
        evaluator_id=str(registered["evaluator_id"]),
        private_spec_sha256=spec_digest,
    )
    expected_trials = [protocol._normalize_trial(item) for item in expected["trials"]]
    if (
        registered["protocol_id"] != expected["protocol_id"]
        or registered.get("trials") != expected_trials
        or f"implementation_sha256:{implementation_digest()}"
        not in str(registered.get("objective") or "")
        or f"private_spec_sha256:{spec_digest}"
        not in str(registered.get("objective") or "")
    ):
        raise ValueError("RPT-1/RPT-2 registration differs from the frozen evaluator/spec")
    return registered


def _temporal_state(frame: Mapping[str, object]) -> str:
    winner = frame.get("winner") if isinstance(frame.get("winner"), Mapping) else {}
    recurrence = (
        frame.get("recurrent_processing")
        if isinstance(frame.get("recurrent_processing"), Mapping)
        else {}
    )
    if winner.get("prediction_violation"):
        return "prediction_violation"
    if winner.get("predicted_change"):
        return "predicted_change"
    if winner.get("dishabituated"):
        return "dishabituated"
    if winner.get("habituated"):
        return "habituated"
    if not recurrence.get("prior_state_present"):
        return "first_observation"
    return "stateless"


def _organized_match(
    frame: Mapping[str, object],
    *,
    expected_bound: bool,
    expected_modalities: List[str],
) -> bool:
    organization = (
        frame.get("perceptual_organization")
        if isinstance(frame.get("perceptual_organization"), Mapping)
        else {}
    )
    representations = [
        item
        for item in organization.get("representations") or []
        if isinstance(item, Mapping)
    ]
    if not expected_bound:
        return not representations
    expected = sorted(expected_modalities)
    return any(sorted(item.get("modalities") or []) == expected for item in representations)


def evaluate_cases(
    registration: Mapping[str, object],
    spec: Mapping[str, object],
    *,
    evidence_started_at: object,
    scored_by: str,
) -> Dict[str, object]:
    registered = validate_registration(registration, spec)
    start = _parsed(evidence_started_at)
    if start <= _parsed(registered["registered_at"]):
        raise ValueError("RPT-1/RPT-2 evidence must begin after preregistration")
    cases = validate_spec(spec)
    evidence: List[Dict[str, object]] = []
    summaries: List[Dict[str, object]] = []
    index = 0

    for case in cases["rpt1_cases"]:
        intact: Dict[str, object] = {}
        lesion: Dict[str, object] = {}
        for frame_events in case["sequence"]:
            now = max(_parsed(item["observed_at"]) for item in frame_events).isoformat()
            intact = eve_sensory.build_frame(
                frame_events,
                prior_frame=intact,
                now=now,
                input_recurrence_enabled=True,
            )
            lesion = eve_sensory.build_frame(
                frame_events,
                prior_frame=lesion,
                now=now,
                input_recurrence_enabled=False,
            )
        intact_state = _temporal_state(intact)
        lesion_state = _temporal_state(lesion)
        intact_correct = intact_state == case["expected_state"]
        lesion_correct = lesion_state == case["expected_state"]
        index += 1
        observed_at = (start + timedelta(milliseconds=index)).isoformat()
        for arm, correct in (("intact", intact_correct), ("lesion", lesion_correct)):
            evidence.append(
                {
                    "evidence_id": f"rpt1-{arm}-{index}",
                    "trial_id": RPT1_TRIAL_ID,
                    "arm": arm,
                    "value": 100.0 if correct else 0.0,
                    "observed_at": observed_at,
                    "source": "private-feature-only-input-recurrence-intervention",
                    "evidence_class": "synthetic",
                }
            )
        summaries.append(
            {
                "trial_id": RPT1_TRIAL_ID,
                "case_id": case["id"],
                "case_sha256": _digest(case),
                "expected_state": case["expected_state"],
                "intact_state": intact_state,
                "lesion_state": lesion_state,
                "intact_prior_consumed": bool(
                    (intact.get("recurrent_processing") or {}).get("prior_state_consumed")
                ),
                "lesion_prior_consumed": bool(
                    (lesion.get("recurrent_processing") or {}).get("prior_state_consumed")
                ),
            }
        )

    for case in cases["rpt2_cases"]:
        now = max(_parsed(item["observed_at"]) for item in case["events"]).isoformat()
        intact = eve_sensory.build_frame(
            case["events"],
            now=now,
            perceptual_organization_enabled=True,
        )
        lesion = eve_sensory.build_frame(
            case["events"],
            now=now,
            perceptual_organization_enabled=False,
        )
        intact_correct = _organized_match(
            intact,
            expected_bound=case["expected_bound"],
            expected_modalities=case["expected_modalities"],
        )
        lesion_correct = _organized_match(
            lesion,
            expected_bound=case["expected_bound"],
            expected_modalities=case["expected_modalities"],
        )
        index += 1
        observed_at = (start + timedelta(milliseconds=index)).isoformat()
        for arm, correct in (("intact", intact_correct), ("lesion", lesion_correct)):
            evidence.append(
                {
                    "evidence_id": f"rpt2-{arm}-{index}",
                    "trial_id": RPT2_TRIAL_ID,
                    "arm": arm,
                    "value": 100.0 if correct else 0.0,
                    "observed_at": observed_at,
                    "source": "private-feature-only-perceptual-organization-intervention",
                    "evidence_class": "synthetic",
                }
            )
        summaries.append(
            {
                "trial_id": RPT2_TRIAL_ID,
                "case_id": case["id"],
                "case_sha256": _digest(case),
                "expected_bound": case["expected_bound"],
                "expected_modalities": case["expected_modalities"],
                "intact_correct": intact_correct,
                "lesion_correct": lesion_correct,
                "intact_representation_count": int(
                    (intact.get("perceptual_organization") or {}).get(
                        "representation_count"
                    )
                    or 0
                ),
                "lesion_representation_count": int(
                    (lesion.get("perceptual_organization") or {}).get(
                        "representation_count"
                    )
                    or 0
                ),
            }
        )

    scored_at = start + timedelta(milliseconds=index + 1)
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
        "implementation_manifest": implementation_manifest(),
        "implementation_sha256": implementation_digest(),
        "private_spec_sha256": private_spec_digest(spec),
        "case_count": len(summaries),
        "cases": summaries,
        "evidence": evidence,
        "protocol_report": report,
        "evidence_class": "synthetic",
        "runtime_mutated": False,
        "resident_input_recurrence_established": False,
        "raw_scene_reconstruction_established": False,
        "phenomenal_unity_inferred": False,
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
    register.add_argument("--spec", type=Path, required=True)
    register.add_argument("--output", type=Path, required=True)
    register.add_argument("--evaluator-id", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--registration", type=Path, required=True)
    run.add_argument("--spec", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--evidence-output", type=Path, required=True)
    run.add_argument("--scored-by", required=True)
    args = parser.parse_args()

    spec = _read(args.spec)
    if args.command == "register":
        result = preregister(
            registered_at=datetime.now(timezone.utc).isoformat(),
            evaluator_id=args.evaluator_id,
            spec=spec,
        )
        _write(args.output, result)
    else:
        registration = _read(args.registration)
        result = evaluate_cases(
            registration,
            spec,
            evidence_started_at=datetime.now(timezone.utc).isoformat(),
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
