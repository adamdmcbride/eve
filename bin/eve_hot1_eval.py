#!/usr/bin/env python3
"""Preregister and score a matched HOT-1 generative-perception lesion."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Dict, List, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_consciousness_protocol as protocol  # noqa: E402
import eve_perceptual_inference as inference  # noqa: E402
import eve_sensory  # noqa: E402


SCHEMA_ID = "eve.hot1_generative_perception_intervention.v1"
SPEC_SCHEMA_ID = "eve.hot1_private_spec.v1"
TRIAL_ID = "hot1-generative-noisy-perception-v1"
BOUNDARY = (
    "Matched synthetic functional evidence for a bounded HOT-1-style top-down "
    "feature hypothesis; not a learned world model, raw perception, resident "
    "behavior, subjective experience, or proof of consciousness."
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
_CASE_FIELDS = {
    "id",
    "observed_features",
    "predicted_features",
    "sensory_precision",
    "prior_precision",
    "expected_dominance",
    "expected_sampling",
    "expected_sensory_override",
}
_DOMINANCE = {"top_down", "balanced", "bottom_up", "bottom_up_only"}


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
        "generative_perception": _sha256(ROOT / "eve_perceptual_inference.py"),
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


def _precision(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number from 0 through 100")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be a finite number from 0 through 100") from exc
    if not math.isfinite(number) or not 0.0 <= number <= 100.0:
        raise ValueError(f"{field} must be a finite number from 0 through 100")
    return round(number, 6)


def _features(value: object, field: str) -> Dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a sparse feature object")
    if eve_sensory.forbidden_ingest_paths(value):
        raise ValueError("private HOT-1 cases may not contain raw or high-dimensional data")
    modality = _identifier(value.get("feature_modality"), f"{field} modality").lower()
    if modality not in eve_sensory.MODALITIES:
        raise ValueError(f"{field} modality is not admitted")
    admitted = set(eve_sensory.FEATURE_LIMITS) | set(eve_sensory.FEATURE_ENUMS) | {
        "active",
        "visible",
        "feature_modality",
    }
    if set(value) - admitted:
        raise ValueError(f"{field} contains an unknown feature")
    normalized = eve_sensory._normalize_features(
        modality,
        {key: child for key, child in value.items() if key != "feature_modality"},
        strict=True,
    )
    if len(normalized) <= 1:
        raise ValueError(f"{field} requires at least one admitted feature dimension")
    return normalized


def validate_spec(payload: Mapping[str, object]) -> Dict[str, object]:
    if payload.get("schema_id") != SPEC_SCHEMA_ID:
        raise ValueError("unsupported HOT-1 private spec schema")
    if set(payload) - {"schema_id", "cases"}:
        raise ValueError("HOT-1 private spec has unknown top-level fields")
    raw_cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    if len(raw_cases) < 6:
        raise ValueError("HOT-1 evaluation requires at least six private cases")
    cases: List[Dict[str, object]] = []
    seen = set()
    for raw in raw_cases:
        if not isinstance(raw, Mapping) or set(raw) != _CASE_FIELDS:
            raise ValueError("every HOT-1 case must contain exactly the typed case fields")
        case_id = _identifier(raw.get("id"), "HOT-1 case id")
        if case_id in seen:
            raise ValueError("private HOT-1 case ids must be unique")
        dominance = str(raw.get("expected_dominance") or "").strip().lower()
        if dominance not in _DOMINANCE:
            raise ValueError("expected_dominance must be a bounded HOT-1 class")
        if not isinstance(raw.get("expected_sampling"), bool):
            raise ValueError("expected_sampling must be Boolean")
        if not isinstance(raw.get("expected_sensory_override"), bool):
            raise ValueError("expected_sensory_override must be Boolean")
        observed = _features(raw.get("observed_features"), "observed_features")
        predicted = _features(raw.get("predicted_features"), "predicted_features")
        if not (set(observed) - {"feature_modality"}) & (
            set(predicted) - {"feature_modality"}
        ):
            raise ValueError("HOT-1 cases require at least one shared feature dimension")
        seen.add(case_id)
        cases.append(
            {
                "id": case_id,
                "observed_features": observed,
                "predicted_features": predicted,
                "sensory_precision": _precision(raw.get("sensory_precision"), "sensory_precision"),
                "prior_precision": _precision(raw.get("prior_precision"), "prior_precision"),
                "expected_dominance": dominance,
                "expected_sampling": bool(raw["expected_sampling"]),
                "expected_sensory_override": bool(raw["expected_sensory_override"]),
            }
        )
    return {"schema_id": SPEC_SCHEMA_ID, "cases": cases}


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
        "protocol_id": "hot1-generative-perception-" + implementation[:12],
        "registered_at": _timestamp(registered_at),
        "subject_system_id": "Eve",
        "evaluator_id": str(evaluator_id or "").strip()[:120],
        "objective": (
            f"implementation_sha256:{implementation};"
            f"private_spec_sha256:{spec_digest};"
            "Test precision-weighted top-down feature inference and sensory override "
            "under a matched generative-perception lesion."
        ),
        "trials": [
            {
                "id": TRIAL_ID,
                "theory": "higher_order",
                "indicator_id": "HOT-1",
                "intervention": (
                    "Hold sparse admitted observations, predictions, and precision "
                    "values fixed while setting top-down prior precision to zero in "
                    "the matched lesion arm."
                ),
                "intact_arm": "precision-weighted top-down and bottom-up feature hypothesis",
                "lesion_arm": "the same observation is classified bottom-up without a top-down prior",
                "measure_id": "correct_precision_weighted_hypothesis_percent",
                "unit": "percent",
                "expected_direction": "lesion_lower",
                "minimum_effect": 40.0,
                "minimum_samples_per_arm": 6,
                "evidence_class": "synthetic",
                "falsifier": (
                    "The intact path fails preregistered dominance, uncertainty-sampling, "
                    "or high-precision sensory-override cases, or lesioning the prior "
                    "preserves the same classifications."
                ),
            }
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
        raise ValueError("HOT-1 registration differs from the frozen evaluator/spec")
    return registered


def _classification_correct(result: Mapping[str, object], case: Mapping[str, object]) -> bool:
    return bool(
        result.get("dominance") == case["expected_dominance"]
        and result.get("needs_active_sampling") is case["expected_sampling"]
        and result.get("sensory_override") is case["expected_sensory_override"]
        and result.get("observed_features") == case["observed_features"]
        and result.get("observation_rewritten") is False
        and result.get("proposal_only") is True
    )


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
        raise ValueError("HOT-1 evidence must begin after preregistration")
    cases = validate_spec(spec)["cases"]
    evidence: List[Dict[str, object]] = []
    summaries: List[Dict[str, object]] = []
    for index, case in enumerate(cases, start=1):
        arguments = {
            "sensory_precision": case["sensory_precision"],
            "prior_precision": case["prior_precision"],
            "feature_limits": eve_sensory.FEATURE_LIMITS,
            "feature_enums": eve_sensory.FEATURE_ENUMS,
        }
        intact = inference.infer_hypothesis(
            case["observed_features"],
            case["predicted_features"],
            **arguments,
        )
        lesion = inference.infer_hypothesis(
            case["observed_features"],
            case["predicted_features"],
            lesioned=True,
            **arguments,
        )
        intact_correct = _classification_correct(intact, case)
        lesion_correct = _classification_correct(lesion, case)
        observed_at = (start + timedelta(milliseconds=index)).isoformat()
        for arm, correct in (("intact", intact_correct), ("lesion", lesion_correct)):
            evidence.append(
                {
                    "evidence_id": f"hot1-{arm}-{index}",
                    "trial_id": TRIAL_ID,
                    "arm": arm,
                    "value": 100.0 if correct else 0.0,
                    "observed_at": observed_at,
                    "source": "private-sparse-feature-generative-perception-intervention",
                    "evidence_class": "synthetic",
                }
            )
        summaries.append(
            {
                "case_id": case["id"],
                "case_sha256": _digest(case),
                "expected_dominance": case["expected_dominance"],
                "intact_dominance": intact["dominance"],
                "lesion_dominance": lesion["dominance"],
                "expected_sampling": case["expected_sampling"],
                "intact_sampling": intact["needs_active_sampling"],
                "lesion_sampling": lesion["needs_active_sampling"],
                "expected_sensory_override": case["expected_sensory_override"],
                "intact_sensory_override": intact["sensory_override"],
                "lesion_sensory_override": lesion["sensory_override"],
                "intact_correct": intact_correct,
                "lesion_correct": lesion_correct,
                "intact_posterior_sha256": _digest(intact["posterior_features"]),
                "observation_rewritten": bool(intact["observation_rewritten"]),
            }
        )
    scored_at = start + timedelta(milliseconds=len(cases) + 1)
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
        "case_count": len(cases),
        "cases": summaries,
        "evidence": evidence,
        "protocol_report": report,
        "evidence_class": "synthetic",
        "runtime_mutated": False,
        "resident_behavior_established": False,
        "learned_generative_world_model_established": False,
        "raw_perception_established": False,
        "phenomenal_experience_inferred": False,
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
        result = evaluate_cases(
            _read(args.registration),
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
