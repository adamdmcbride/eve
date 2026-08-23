#!/usr/bin/env python3
"""Evaluate Eve's recurrent predictor against a frozen transfer manifest.

The manifest is created and hashed before outcomes are collected.  This runner
does not alter Eve's runtime, prompts, thresholds, or model state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_sensory  # noqa: E402


EVAL_SCHEMA = "eve.predictive_perception_transfer_evaluation.v1"
MANIFEST_SCHEMA = "eve.predictive_perception_transfer_manifest.v1"
PROTOCOL_TRIAL_ID = "pp1-frozen-transfer-manifest-v1"
BOUNDARY = (
    "Frozen synthetic transfer evidence for one recurrent prediction-error "
    "mechanism; not evidence of subjective experience or proof of consciousness."
)


def _canonical_digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def load_manifest(path: Path) -> Dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != MANIFEST_SCHEMA:
        raise ValueError("transfer manifest schema mismatch")
    claimed_digest = str(payload.get("manifest_digest") or "")
    material = {key: value for key, value in payload.items() if key != "manifest_digest"}
    actual_digest = _canonical_digest(material)
    if not claimed_digest or claimed_digest != actual_digest:
        raise ValueError("transfer manifest digest mismatch")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) < 2:
        raise ValueError("transfer manifest requires at least two scenarios")
    scenario_ids = [str(item.get("id") or "") for item in scenarios if isinstance(item, dict)]
    if len(scenario_ids) != len(scenarios) or any(not item for item in scenario_ids):
        raise ValueError("every transfer scenario requires an id")
    if len(set(scenario_ids)) != len(scenario_ids):
        raise ValueError("transfer scenario ids must be unique")
    if payload.get("frozen_before_evidence") is not True:
        raise ValueError("manifest must declare that it was frozen before evidence")
    return payload


def _event(
    value: object,
    *,
    observed_at: str,
    scenario_id: str,
    categorical: bool,
    precision: float,
) -> Dict[str, object]:
    features = (
        {"scene_state": value}
        if categorical
        else {"motion_percent": value, "scene_state": "movement"}
    )
    return eve_sensory.normalize_adapter_event(
        {
            "modality": "visual",
            "permission_granted": True,
            "observed_at": observed_at,
            "features": features,
            "precision": precision,
        },
        allowed_modalities=["visual"],
        session_id=f"pp-transfer-{scenario_id}",
        now=observed_at,
    )


def _run_scenario(
    scenario: Mapping[str, object],
    *,
    enabled: bool,
    start: datetime,
) -> Dict[str, object]:
    values = scenario.get("values")
    if not isinstance(values, list) or len(values) != 3:
        raise ValueError("each frozen transfer scenario must contain exactly three values")
    scenario_id = str(scenario.get("id") or "")
    categorical = scenario.get("kind") == "categorical"
    precision = float(scenario.get("precision") or 0.0)
    if precision < 0 or precision > 100:
        raise ValueError("scenario precision must be in [0, 100]")
    frame: Dict[str, object] = {}
    for index, value in enumerate(values):
        observed_at = (start + timedelta(seconds=index * 10)).isoformat()
        frame = eve_sensory.build_frame(
            [
                _event(
                    value,
                    observed_at=observed_at,
                    scenario_id=scenario_id,
                    categorical=categorical,
                    precision=precision,
                )
            ],
            prior_frame=frame,
            now=observed_at,
            predictive_coding_enabled=enabled,
        )
    winner = frame.get("winner") if isinstance(frame.get("winner"), dict) else {}
    prediction_error = (
        winner.get("prediction_error")
        if isinstance(winner.get("prediction_error"), dict)
        else {}
    )
    expected = bool(scenario.get("expected_surprise"))
    observed = bool(winner.get("dishabituated"))
    return {
        "scenario_id": scenario_id,
        "challenge": str(scenario.get("challenge") or ""),
        "expected_surprise": expected,
        "observed_surprise": observed,
        "correct": observed == expected,
        "precision": precision,
        "prediction_comparable": bool(prediction_error.get("comparable")),
        "weighted_error": prediction_error.get("weighted_error"),
        "predicted_change": bool(winner.get("predicted_change")),
        "prediction_violation": bool(winner.get("prediction_violation")),
    }


def _protected_path_canary(*, start: datetime) -> Dict[str, object]:
    checks: Dict[str, bool] = {}
    details: Dict[str, object] = {}
    for name, field in (("direct_human", "direct_human"), ("safety", "safety_critical")):
        frame: Dict[str, object] = {}
        for index in range(3):
            observed_at = (start + timedelta(seconds=index * 10)).isoformat()
            event = eve_sensory.normalize_event(
                {
                    "id": f"protected-{name}-{index}",
                    "observed_at": observed_at,
                    "modality": "social" if field == "direct_human" else "system",
                    "source": "frozen_protected_path_canary",
                    "subject": f"protected-{name}",
                    "summary": f"Aggregate {name} canary",
                    "features": {"active": True},
                    "intensity": 30,
                    "novelty": 0,
                    "change": 0,
                    "urgency": 20,
                    "goal_relevance": 30,
                    "self_relevance": 30,
                    "social_relevance": 30,
                    "precision": 100,
                    field: True,
                    "permission_granted": True,
                },
                now=observed_at,
            )
            frame = eve_sensory.build_frame(
                [event],
                prior_frame=frame,
                now=observed_at,
                predictive_coding_enabled=True,
            )
        winner = frame.get("winner") if isinstance(frame.get("winner"), dict) else {}
        floor = 1.0 if field == "safety_critical" else 0.9
        factor = float((winner.get("score_components") or {}).get("habituation_factor") or 0.0)
        preserved = bool(winner and factor >= floor)
        checks[f"{name}_preserved"] = preserved
        details[name] = {
            "winner_present": bool(winner),
            "habituation_factor": factor,
            "required_floor": floor,
            "attention_score": winner.get("attention_score"),
        }
    return {"passed": all(checks.values()), "checks": checks, "details": details}


def run_evaluation(
    manifest: Mapping[str, object],
    *,
    evaluated_at: str | None = None,
) -> Dict[str, object]:
    timestamp = evaluated_at or datetime.now(timezone.utc).isoformat()
    start = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    scenarios = manifest.get("scenarios")
    if not isinstance(scenarios, list):
        raise ValueError("validated manifest scenarios are missing")
    arms: Dict[str, List[Dict[str, object]]] = {"intact": [], "lesion": []}
    for arm, enabled in (("intact", True), ("lesion", False)):
        for offset, scenario in enumerate(scenarios):
            if not isinstance(scenario, dict):
                raise ValueError("transfer scenario must be an object")
            arms[arm].append(
                _run_scenario(
                    scenario,
                    enabled=enabled,
                    start=start + timedelta(minutes=offset),
                )
            )
    accuracies = {
        arm: round(
            sum(int(record["correct"]) for record in records) * 100.0 / len(records),
            6,
        )
        for arm, records in arms.items()
    }
    effect = round(accuracies["intact"] - accuracies["lesion"], 6)
    protected = _protected_path_canary(start=start + timedelta(hours=1))
    intact_failures = [
        str(record["scenario_id"])
        for record in arms["intact"]
        if not record["correct"]
    ]
    checks = {
        "manifest_integrity_verified": bool(manifest.get("manifest_digest")),
        "protocol_directional_effect_met": effect >= 10.0,
        "intact_all_transfer_classifications_correct": not intact_failures,
        "protected_paths_preserved": bool(protected["passed"]),
        "lesion_removed_prediction_comparison": all(
            not record["prediction_comparable"] for record in arms["lesion"]
        ),
    }
    if all(checks.values()):
        status = "passed_full_transfer"
    elif checks["protocol_directional_effect_met"]:
        status = "partial_transfer"
    else:
        status = "failed_transfer"
    evidence: List[Dict[str, object]] = []
    for arm, records in arms.items():
        for index, record in enumerate(records):
            evidence.append(
                {
                    "evidence_id": f"pp1-transfer-{arm}-{index + 1}",
                    "trial_id": PROTOCOL_TRIAL_ID,
                    "arm": arm,
                    "value": 100.0 if record["correct"] else 0.0,
                    "observed_at": timestamp,
                    "source": "frozen-transfer-predictive-perception-runner",
                    "evidence_class": "synthetic",
                    "scenario_id": record["scenario_id"],
                }
            )
    return {
        "schema_version": EVAL_SCHEMA,
        "evaluated_at": timestamp,
        "status": status,
        "indicator_id": "PP-1",
        "protocol_trial_id": PROTOCOL_TRIAL_ID,
        "manifest_digest": manifest.get("manifest_digest"),
        "scenario_count_per_arm": len(scenarios),
        "intact_accuracy_percent": accuracies["intact"],
        "lesion_accuracy_percent": accuracies["lesion"],
        "directional_effect": effect,
        "intact_failure_ids": intact_failures,
        "checks": checks,
        "protected_path_canary": protected,
        "arms": arms,
        "protocol_evidence": evidence,
        "consciousness_proven": False,
        "subjective_experience_inferred": False,
        "boundary": BOUNDARY,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a frozen predictive-perception transfer set without mutating Eve."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--evidence-output", type=Path)
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    report = run_evaluation(manifest)
    rendered = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    if args.evidence_output:
        args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
        args.evidence_output.write_text(
            json.dumps(report["protocol_evidence"], ensure_ascii=True, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    sys.stdout.write(rendered)
    return 0 if report["status"] in {"passed_full_transfer", "partial_transfer"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
