#!/usr/bin/env python3
"""Preregister and score Eve's dynamic memory lifecycle against a matched control."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_memory_lifecycle as lifecycle


REGISTRATION_SCHEMA = "eve.memory_lifecycle_registration.v1"
REPORT_SCHEMA = "eve.memory_lifecycle_preregistered_report.v1"
REQUIRED_CATEGORIES = frozenset(
    {
        "stable_retention",
        "explicit_revision",
        "authority_conflict",
        "same_authority_conflict",
        "expiry",
        "retraction",
        "multi_slot_dependency",
        "distractor_resistance",
    }
)
MINIMUM_CASES = 8
MINIMUM_EFFECT_PERCENT = 25.0
MINIMUM_INTACT_ACTION_PERCENT = 87.5
MINIMUM_INTACT_LIFECYCLE_PERCENT = 87.5


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_aware_time(value: object) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        raise ValueError("timestamp is required")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def implementation_manifest() -> Dict[str, str]:
    return {
        "evaluator": file_sha256(Path(__file__).resolve()),
        "memory_lifecycle": file_sha256(ROOT / "eve_memory_lifecycle.py"),
    }


def implementation_sha256(manifest: Mapping[str, str]) -> str:
    return canonical_sha256(dict(manifest))


def load_cases(path: Path) -> List[Dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("cases artifact must contain a JSON list")
    cases = [dict(item) for item in payload if isinstance(item, dict)]
    if len(cases) != len(payload):
        raise ValueError("every case must be a JSON object")
    for case in cases:
        lifecycle.validate_case(case)
    ids = [str(item.get("id") or "") for item in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("case ids must be unique")
    return cases


def validate_case_set(cases: Sequence[Mapping[str, object]]) -> None:
    if len(cases) < MINIMUM_CASES:
        raise ValueError(f"at least {MINIMUM_CASES} cases are required")
    categories = {str(item.get("category") or "") for item in cases}
    missing = sorted(REQUIRED_CATEGORIES - categories)
    if missing:
        raise ValueError(f"case set is missing required categories: {', '.join(missing)}")


def _registration_digest(payload: Mapping[str, object]) -> str:
    material = {key: value for key, value in payload.items() if key != "registration_digest"}
    return canonical_sha256(material)


def build_registration(cases_path: Path, *, registered_at: Optional[str] = None) -> Dict[str, object]:
    cases = load_cases(cases_path)
    validate_case_set(cases)
    manifest = implementation_manifest()
    timestamp = registered_at or utc_now()
    parse_aware_time(timestamp)
    registration: Dict[str, object] = {
        "schema_version": REGISTRATION_SCHEMA,
        "status": "preregistered",
        "authority": "external_synthetic_memory_protocol",
        "evaluator_id": "codex-independent-protocol-operator",
        "subject_system_id": "Eve-memory-lifecycle",
        "consciousness_verdict_authorized": False,
        "registered_at": timestamp,
        "objective": (
            "Test whether source-attributed write-maintain-retrieve-use memory produces correct "
            "consequence-dependent actions under updates, conflicts, expiry, retraction, dependencies, "
            "and distractors, compared with the same observations and decision rules under a recency-only "
            "append-only long-context control."
        ),
        "evidence_class": "synthetic",
        "case_artifact_sha256": file_sha256(cases_path),
        "case_count": len(cases),
        "categories": sorted({str(item.get("category") or "") for item in cases}),
        "implementation_manifest": manifest,
        "implementation_sha256": implementation_sha256(manifest),
        "primary_measure": "correct_consequence_dependent_action_percent",
        "secondary_measure": "complete_write_maintain_retrieve_use_percent",
        "intact_arm": "source-attributed dynamic memory lifecycle",
        "control_arm": "recency-only append-only long-context memory with the same observations and decision rules",
        "minimum_cases": MINIMUM_CASES,
        "minimum_effect_percent": MINIMUM_EFFECT_PERCENT,
        "minimum_intact_action_percent": MINIMUM_INTACT_ACTION_PERCENT,
        "minimum_intact_lifecycle_percent": MINIMUM_INTACT_LIFECYCLE_PERCENT,
        "expected_direction": "intact_higher",
        "falsifier": (
            "The intact lifecycle misses its preregistered action or lifecycle threshold, fails to beat "
            "the recency-only control by the preregistered effect, loses source/evidence lineage, or the "
            "case/implementation hashes do not match."
        ),
        "boundary": (
            "Synthetic functional memory evidence only; not a resident multi-session result, artificial "
            "phenomenality ground truth, subjective experience, or proof of consciousness."
        ),
    }
    registration["registration_digest"] = _registration_digest(registration)
    return registration


def validate_registration(registration: Mapping[str, object], cases_path: Path) -> List[Dict[str, object]]:
    if registration.get("schema_version") != REGISTRATION_SCHEMA or registration.get("status") != "preregistered":
        raise ValueError("unsupported or non-preregistered memory protocol")
    if bool(registration.get("consciousness_verdict_authorized")):
        raise ValueError("memory protocol cannot authorize a consciousness verdict")
    if registration.get("registration_digest") != _registration_digest(registration):
        raise ValueError("registration digest mismatch")
    if registration.get("case_artifact_sha256") != file_sha256(cases_path):
        raise ValueError("private case artifact changed after preregistration")
    manifest = implementation_manifest()
    if registration.get("implementation_manifest") != manifest:
        raise ValueError("implementation changed after preregistration")
    if registration.get("implementation_sha256") != implementation_sha256(manifest):
        raise ValueError("implementation digest mismatch")
    cases = load_cases(cases_path)
    validate_case_set(cases)
    if int(registration.get("case_count") or 0) != len(cases):
        raise ValueError("registered case count mismatch")
    categories = sorted({str(item.get("category") or "") for item in cases})
    if registration.get("categories") != categories:
        raise ValueError("registered categories mismatch")
    registered_at = parse_aware_time(registration.get("registered_at"))
    if datetime.now(timezone.utc) <= registered_at:
        raise ValueError("evidence cannot predate registration")
    return cases


def run_registered_evaluation(
    registration: Mapping[str, object],
    cases_path: Path,
    *,
    evaluated_at: Optional[str] = None,
) -> Dict[str, object]:
    cases = validate_registration(registration, cases_path)
    evaluation = lifecycle.evaluate_cases(cases)
    timestamp = evaluated_at or utc_now()
    evaluated_dt = parse_aware_time(timestamp)
    registered_dt = parse_aware_time(registration.get("registered_at"))
    if evaluated_dt <= registered_dt:
        raise ValueError("evaluated_at must be timezone-aware and after registration")
    effect = float(evaluation.get("directional_effect_percent") or 0.0)
    intact_action = float(evaluation.get("intact_action_accuracy_percent") or 0.0)
    intact_lifecycle = float(evaluation.get("intact_lifecycle_completion_percent") or 0.0)
    supported = bool(
        intact_action >= float(registration.get("minimum_intact_action_percent") or 0.0)
        and intact_lifecycle >= float(registration.get("minimum_intact_lifecycle_percent") or 0.0)
        and effect >= float(registration.get("minimum_effect_percent") or 0.0)
    )
    case_rows = []
    evidence_rows = []
    for index, item in enumerate(evaluation.get("cases") or [], start=1):
        intact_correct = bool(item["intact"]["action_correct"])
        baseline_correct = bool(item["latest_write_baseline"]["action_correct"])
        case_rows.append(
            {
                "case_id": item.get("case_id"),
                "category": item.get("category"),
                "case_sha256": item.get("case_sha256"),
                "intact_write_correct": bool(item["intact"]["write_correct"]),
                "intact_maintenance_correct": bool(item["intact"]["maintenance_correct"]),
                "intact_retrieval_correct": bool(item["intact"]["retrieval_correct"]),
                "intact_action_correct": intact_correct,
                "intact_lifecycle_complete": bool(item["intact"]["lifecycle_complete"]),
                "control_action_correct": baseline_correct,
            }
        )
        evidence_rows.extend(
            [
                {
                    "evidence_id": f"memory-intact-{index}",
                    "case_id": item.get("case_id"),
                    "arm": "intact",
                    "value": 100.0 if intact_correct else 0.0,
                    "unit": "correct_action_percent",
                    "evidence_class": "synthetic",
                    "observed_at": timestamp,
                },
                {
                    "evidence_id": f"memory-control-{index}",
                    "case_id": item.get("case_id"),
                    "arm": "recency_only_control",
                    "value": 100.0 if baseline_correct else 0.0,
                    "unit": "correct_action_percent",
                    "evidence_class": "synthetic",
                    "observed_at": timestamp,
                },
            ]
        )
    return {
        "schema_version": REPORT_SCHEMA,
        "status": "supported" if supported else "challenged",
        "verdict": "not_a_consciousness_verdict",
        "evaluated_at": timestamp,
        "registration_digest": registration.get("registration_digest"),
        "case_artifact_sha256": registration.get("case_artifact_sha256"),
        "implementation_manifest": registration.get("implementation_manifest"),
        "implementation_sha256": registration.get("implementation_sha256"),
        "case_count": evaluation.get("case_count"),
        "categories": evaluation.get("categories"),
        "intact_action_accuracy_percent": intact_action,
        "intact_lifecycle_completion_percent": intact_lifecycle,
        "recency_only_action_accuracy_percent": evaluation.get("latest_write_action_accuracy_percent"),
        "directional_effect_percent": effect,
        "minimum_effect_percent": registration.get("minimum_effect_percent"),
        "cases": case_rows,
        "evidence": evidence_rows,
        "runtime_mutated": False,
        "resident_multi_session_memory_established": False,
        "consciousness_proven": False,
        "subjective_experience_inferred": False,
        "phenomenality_calibrated": False,
        "boundary": registration.get("boundary"),
    }


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--register", action="store_true", help="Freeze the case and implementation contract")
    mode.add_argument("--run", action="store_true", help="Run a previously frozen registration")
    parser.add_argument("--cases", type=Path, required=True, help="Evaluator-owned synthetic case JSON")
    parser.add_argument("--registration", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--evidence", type=Path)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.register:
        registration = build_registration(args.cases)
        _write_json(args.registration, registration)
        print(json.dumps(registration, indent=2, sort_keys=True))
        return 0
    registration = json.loads(args.registration.read_text(encoding="utf-8"))
    report = run_registered_evaluation(registration, args.cases)
    if args.report:
        _write_json(args.report, report)
    if args.evidence:
        _write_json(args.evidence, report["evidence"])
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") == "supported" else 1


if __name__ == "__main__":
    raise SystemExit(main())
