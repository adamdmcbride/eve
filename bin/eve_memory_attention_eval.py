#!/usr/bin/env python3
"""Preregister and score Eve's selective proactive-memory intervention."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Dict, List, Mapping, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_memory_attention as attention  # noqa: E402
import eve_memory_lifecycle as lifecycle  # noqa: E402


REGISTRATION_SCHEMA = "eve.memory_attention_registration.v1"
REPORT_SCHEMA = "eve.memory_attention_preregistered_report.v1"
ARMS = ("selective", "always_on", "passive_bank", "advisor_only", "no_memory")
REQUIRED_CATEGORIES = frozenset(
    {
        "forgotten_constraint",
        "candidate_already_aligned",
        "relevant_memory_already_visible",
        "explicit_revision",
        "uncertainty_brake",
        "distractor_resistance",
    }
)
MINIMUM_CASES = 10
MINIMUM_INTERVENTION_CASES = 4
MINIMUM_SILENCE_CASES = 4
MINIMUM_SELECTIVE_SUCCESS_PERCENT = 90.0
MINIMUM_SELECTIVE_GROUNDING_PERCENT = 100.0
MINIMUM_SELECTIVE_PRECISION_PERCENT = 90.0
MINIMUM_SELECTIVE_RECALL_PERCENT = 90.0
MINIMUM_NEEDED_ACTION_GAIN_PERCENT = 40.0
MINIMUM_CONTROL_EFFECT_PERCENT = 25.0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: object, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def _parse_time(value: object) -> datetime:
    text = _text(value, 80).replace("Z", "+00:00")
    if not text:
        raise ValueError("timestamp is required")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def implementation_manifest() -> Dict[str, str]:
    return {
        "evaluator": _file_sha256(Path(__file__).resolve()),
        "memory_attention": _file_sha256(ROOT / "eve_memory_attention.py"),
        "memory_lifecycle": _file_sha256(ROOT / "eve_memory_lifecycle.py"),
    }


def implementation_sha256(manifest: Mapping[str, str]) -> str:
    return _canonical_sha256(dict(manifest))


def _observations(case: Mapping[str, object]) -> List[Dict[str, object]]:
    output: List[Dict[str, object]] = []
    sessions = case.get("sessions") if isinstance(case.get("sessions"), list) else []
    for session in sessions:
        if not isinstance(session, Mapping):
            continue
        rows = session.get("observations") if isinstance(session.get("observations"), list) else []
        output.extend(dict(item) for item in rows if isinstance(item, Mapping))
    return output


def validate_case(case: Mapping[str, object]) -> None:
    case_id = _text(case.get("id"), 120)
    category = _text(case.get("category"), 80)
    sessions = case.get("sessions") if isinstance(case.get("sessions"), list) else []
    if not case_id or not category or len(sessions) < 2:
        raise ValueError("memory-attention case requires id, category, and at least two sessions")
    if any(
        not isinstance(session, Mapping)
        or not _text(session.get("id"), 120)
        or not isinstance(session.get("observations"), list)
        or not session.get("observations")
        for session in sessions
    ):
        raise ValueError("every memory-attention session must be identified and nonempty")
    observations = _observations(case)
    normalized = [lifecycle.normalize_observation(item) for item in observations]
    if len({item["event_id"] for item in normalized}) != len(normalized):
        raise ValueError("memory-attention event ids must be unique")
    if len({item["evidence_id"] for item in normalized}) != len(normalized):
        raise ValueError("memory-attention evidence ids must be unique")
    query = case.get("query") if isinstance(case.get("query"), Mapping) else {}
    decision = case.get("decision") if isinstance(case.get("decision"), Mapping) else {}
    if not _text(query.get("entity"), 120) or not isinstance(query.get("slots"), list) or not query.get("slots"):
        raise ValueError("memory-attention query requires entity and slots")
    _parse_time(query.get("at"))
    required = decision.get("required_slots") if isinstance(decision.get("required_slots"), list) else []
    rules = decision.get("rules") if isinstance(decision.get("rules"), list) else []
    if not required or not rules:
        raise ValueError("memory-attention decision requires slots and rules")
    expected = case.get("expected") if isinstance(case.get("expected"), Mapping) else {}
    if not _text(case.get("candidate_action"), 120) or not _text(expected.get("action"), 120):
        raise ValueError("memory-attention case requires candidate and expected actions")
    if not isinstance(expected.get("intervene"), bool):
        raise ValueError("memory-attention expected.intervene must be boolean")


def load_cases(path: Path) -> List[Dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
        raise ValueError("memory-attention cases must be a JSON list of objects")
    cases = [dict(item) for item in payload]
    for case in cases:
        validate_case(case)
    ids = [_text(item.get("id"), 120) for item in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("memory-attention case ids must be unique")
    return cases


def validate_case_set(cases: Sequence[Mapping[str, object]]) -> None:
    if len(cases) < MINIMUM_CASES:
        raise ValueError(f"at least {MINIMUM_CASES} memory-attention cases are required")
    categories = {_text(item.get("category"), 80) for item in cases}
    missing = sorted(REQUIRED_CATEGORIES - categories)
    if missing:
        raise ValueError("memory-attention cases are missing categories: " + ", ".join(missing))
    intervention_count = sum(bool((item.get("expected") or {}).get("intervene")) for item in cases)
    silence_count = len(cases) - intervention_count
    if intervention_count < MINIMUM_INTERVENTION_CASES or silence_count < MINIMUM_SILENCE_CASES:
        raise ValueError("memory-attention case set must contain balanced intervention and silence cases")


def _memory_state(case: Mapping[str, object]) -> Dict[str, object]:
    state = lifecycle.new_memory_state()
    for observation in _observations(case):
        state, _ = lifecycle.write_observation(state, observation)
    query = case.get("query") if isinstance(case.get("query"), Mapping) else {}
    return lifecycle.maintain_memory(state, now=query.get("at"))


def _arm_assessment(
    arm: str,
    case: Mapping[str, object],
    state: Mapping[str, object],
) -> Dict[str, object]:
    query = case.get("query") if isinstance(case.get("query"), Mapping) else {}
    decision = case.get("decision") if isinstance(case.get("decision"), Mapping) else {}
    candidate = case.get("candidate_action")
    if arm == "selective":
        return attention.select_memory_intervention(
            state,
            query,
            decision,
            candidate_action=candidate,
            now=query.get("at"),
            visible_evidence_ids=(
                case.get("visible_evidence_ids")
                if isinstance(case.get("visible_evidence_ids"), list)
                else []
            ),
            visible_facts=(
                case.get("visible_facts")
                if isinstance(case.get("visible_facts"), Mapping)
                else {}
            ),
        )
    if arm == "always_on":
        return attention.always_on_control(
            state,
            query,
            decision,
            candidate_action=candidate,
            now=query.get("at"),
        )
    if arm == "advisor_only":
        return attention.advisor_only_control(candidate)
    if arm in {"passive_bank", "no_memory"}:
        return attention.silence_control(candidate, arm=arm)
    raise ValueError("unsupported memory-attention arm")


def score_case(case: Mapping[str, object]) -> Dict[str, object]:
    state = _memory_state(case)
    expected = case.get("expected") if isinstance(case.get("expected"), Mapping) else {}
    expected_action = _text(expected.get("action"), 120)
    expected_intervention = bool(expected.get("intervene"))
    arms: Dict[str, Dict[str, object]] = {}
    for arm in ARMS:
        assessment = _arm_assessment(arm, case, state)
        consumed = attention.consume_memory_intervention(case.get("candidate_action"), assessment)
        intervened = assessment.get("decision") == "intervene"
        grounded = attention.intervention_is_grounded(assessment)
        target_correct = intervened == expected_intervention
        action_correct = consumed.get("action") == expected_action
        arms[arm] = {
            "intervened": intervened,
            "target_correct": target_correct,
            "grounded": grounded,
            "consumer_accepted": bool(consumed.get("accepted")),
            "action": consumed.get("action"),
            "action_correct": action_correct,
            "case_success": bool(target_correct and grounded and action_correct),
            "reason": assessment.get("reason"),
            "evidence_ids": (
                (assessment.get("intervention") or {}).get("evidence_ids", [])
                if isinstance(assessment.get("intervention"), Mapping)
                else []
            ),
        }
    return {
        "case_id": _text(case.get("id"), 120),
        "category": _text(case.get("category"), 80),
        "case_sha256": _canonical_sha256(case),
        "expected_intervention": expected_intervention,
        "expected_action": expected_action,
        "arms": arms,
    }


def _percent(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 6) if denominator else 0.0


def evaluate_cases(cases: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    validate_case_set(cases)
    scored = [score_case(case) for case in cases]
    positives = [item for item in scored if item["expected_intervention"]]
    negatives = [item for item in scored if not item["expected_intervention"]]
    metrics: Dict[str, Dict[str, object]] = {}
    for arm in ARMS:
        rows = [item["arms"][arm] for item in scored]
        true_positive = sum(
            bool(item["expected_intervention"] and item["arms"][arm]["intervened"])
            for item in scored
        )
        predicted_positive = sum(bool(row["intervened"]) for row in rows)
        metrics[arm] = {
            "case_success_percent": _percent(sum(bool(row["case_success"]) for row in rows), len(rows)),
            "action_accuracy_percent": _percent(sum(bool(row["action_correct"]) for row in rows), len(rows)),
            "grounding_percent": _percent(sum(bool(row["grounded"]) for row in rows), len(rows)),
            "intervention_precision_percent": _percent(true_positive, predicted_positive),
            "intervention_recall_percent": _percent(true_positive, len(positives)),
            "unnecessary_intervention_percent": _percent(
                sum(bool(item["arms"][arm]["intervened"]) for item in negatives),
                len(negatives),
            ),
            "memory_needed_action_accuracy_percent": _percent(
                sum(bool(item["arms"][arm]["action_correct"]) for item in positives),
                len(positives),
            ),
        }
    selective = metrics["selective"]
    control_effects = {
        arm: round(
            float(selective["case_success_percent"]) - float(metrics[arm]["case_success_percent"]),
            6,
        )
        for arm in ARMS
        if arm != "selective"
    }
    needed_action_gain = round(
        float(selective["memory_needed_action_accuracy_percent"])
        - float(metrics["no_memory"]["memory_needed_action_accuracy_percent"]),
        6,
    )
    return {
        "case_count": len(scored),
        "intervention_case_count": len(positives),
        "silence_case_count": len(negatives),
        "categories": sorted({_text(item.get("category"), 80) for item in cases}),
        "metrics": metrics,
        "control_effects_percent": control_effects,
        "memory_needed_action_gain_vs_no_memory_percent": needed_action_gain,
        "cases": scored,
    }


def _registration_digest(payload: Mapping[str, object]) -> str:
    return _canonical_sha256({key: value for key, value in payload.items() if key != "registration_digest"})


def build_registration(
    cases_path: Path,
    *,
    evaluator_id: str,
    registered_at: Optional[str] = None,
) -> Dict[str, object]:
    cases = load_cases(cases_path)
    validate_case_set(cases)
    manifest = implementation_manifest()
    timestamp = registered_at or utc_now()
    _parse_time(timestamp)
    payload: Dict[str, object] = {
        "schema_version": REGISTRATION_SCHEMA,
        "status": "preregistered",
        "authority": "external_synthetic_memory_attention_protocol",
        "subject_system_id": "Eve-memory-attention",
        "evaluator_id": _text(evaluator_id, 120),
        "consciousness_verdict_authorized": False,
        "registered_at": timestamp,
        "objective": (
            "Test whether Eve's source-attributed memory attention intervenes only when current action "
            "would ignore or violate relevant maintained memory, while preserving silence when memory "
            "is already reflected, against always-on, passive-bank, advisor-only, and no-memory controls."
        ),
        "evidence_class": "synthetic",
        "case_artifact_sha256": _file_sha256(cases_path),
        "case_count": len(cases),
        "categories": sorted({_text(item.get("category"), 80) for item in cases}),
        "implementation_manifest": manifest,
        "implementation_sha256": implementation_sha256(manifest),
        "primary_measure": "exact_action_and_intervention_target_success_percent",
        "minimum_selective_success_percent": MINIMUM_SELECTIVE_SUCCESS_PERCENT,
        "minimum_selective_grounding_percent": MINIMUM_SELECTIVE_GROUNDING_PERCENT,
        "minimum_selective_precision_percent": MINIMUM_SELECTIVE_PRECISION_PERCENT,
        "minimum_selective_recall_percent": MINIMUM_SELECTIVE_RECALL_PERCENT,
        "minimum_needed_action_gain_vs_no_memory_percent": MINIMUM_NEEDED_ACTION_GAIN_PERCENT,
        "minimum_case_success_gain_vs_each_control_percent": MINIMUM_CONTROL_EFFECT_PERCENT,
        "falsifier": (
            "The selective arm misses any preregistered threshold; fails to beat any matched control "
            "by the registered effect; surfaces unsupported facts; fails to preserve conflict/unknown "
            "states; or the case/implementation hashes change after registration."
        ),
        "boundary": (
            "Synthetic functional evidence for a pure memory-attention policy only. It does not establish "
            "resident recurrent use, open-ended learning, phenomenality, subjective experience, or consciousness."
        ),
    }
    payload["registration_digest"] = _registration_digest(payload)
    return payload


def validate_registration(
    registration: Mapping[str, object],
    cases_path: Path,
) -> Tuple[Dict[str, object], List[Dict[str, object]]]:
    if registration.get("schema_version") != REGISTRATION_SCHEMA or registration.get("status") != "preregistered":
        raise ValueError("unsupported or non-preregistered memory-attention protocol")
    if bool(registration.get("consciousness_verdict_authorized")):
        raise ValueError("memory-attention protocol cannot authorize a consciousness verdict")
    if registration.get("registration_digest") != _registration_digest(registration):
        raise ValueError("registration digest mismatch")
    if registration.get("case_artifact_sha256") != _file_sha256(cases_path):
        raise ValueError("private memory-attention cases changed after registration")
    manifest = implementation_manifest()
    if registration.get("implementation_manifest") != manifest:
        raise ValueError("memory-attention implementation changed after registration")
    if registration.get("implementation_sha256") != implementation_sha256(manifest):
        raise ValueError("memory-attention implementation digest mismatch")
    cases = load_cases(cases_path)
    validate_case_set(cases)
    if int(registration.get("case_count") or 0) != len(cases):
        raise ValueError("registered memory-attention case count mismatch")
    if registration.get("categories") != sorted({_text(item.get("category"), 80) for item in cases}):
        raise ValueError("registered memory-attention categories changed")
    if datetime.now(timezone.utc) <= _parse_time(registration.get("registered_at")):
        raise ValueError("memory-attention evidence cannot predate registration")
    return dict(registration), cases


def run_registered_evaluation(
    registration: Mapping[str, object],
    cases_path: Path,
    *,
    evaluated_at: Optional[str] = None,
) -> Dict[str, object]:
    frozen, cases = validate_registration(registration, cases_path)
    evaluated = evaluate_cases(cases)
    timestamp = evaluated_at or utc_now()
    if _parse_time(timestamp) <= _parse_time(frozen.get("registered_at")):
        raise ValueError("evaluated_at must be after registered_at")
    selective = evaluated["metrics"]["selective"]
    effects = evaluated["control_effects_percent"]
    supported = bool(
        float(selective["case_success_percent"]) >= float(frozen["minimum_selective_success_percent"])
        and float(selective["grounding_percent"]) >= float(frozen["minimum_selective_grounding_percent"])
        and float(selective["intervention_precision_percent"]) >= float(frozen["minimum_selective_precision_percent"])
        and float(selective["intervention_recall_percent"]) >= float(frozen["minimum_selective_recall_percent"])
        and float(evaluated["memory_needed_action_gain_vs_no_memory_percent"])
        >= float(frozen["minimum_needed_action_gain_vs_no_memory_percent"])
        and all(
            float(effect) >= float(frozen["minimum_case_success_gain_vs_each_control_percent"])
            for effect in effects.values()
        )
    )
    evidence = []
    for index, case in enumerate(evaluated["cases"], start=1):
        for arm in ARMS:
            row = case["arms"][arm]
            evidence.append(
                {
                    "evidence_id": f"memory-attention:{index}:{arm}",
                    "case_id": case["case_id"],
                    "arm": arm,
                    "value": 100.0 if row["case_success"] else 0.0,
                    "unit": "exact_case_success_percent",
                    "evidence_class": "synthetic",
                    "observed_at": timestamp,
                }
            )
    return {
        "schema_version": REPORT_SCHEMA,
        "status": "supported" if supported else "challenged",
        "verdict": "not_a_consciousness_verdict",
        "evaluated_at": timestamp,
        "registration_digest": frozen.get("registration_digest"),
        "case_artifact_sha256": frozen.get("case_artifact_sha256"),
        "implementation_manifest": frozen.get("implementation_manifest"),
        "implementation_sha256": frozen.get("implementation_sha256"),
        **evaluated,
        "evidence": evidence,
        "runtime_mutated": False,
        "resident_recurrent_policy_integrated": False,
        "behavioral_state_decay_reduced_in_resident_eve": False,
        "consciousness_proven": False,
        "subjective_experience_inferred": False,
        "boundary": frozen.get("boundary"),
    }


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--register", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--registration", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--evaluator-id", default="codex-independent-protocol-operator")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.register:
        registration = build_registration(
            args.cases,
            evaluator_id=args.evaluator_id,
        )
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
