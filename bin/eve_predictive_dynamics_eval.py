#!/usr/bin/env python3
"""Run Eve's frozen identifiable-dynamics matched-lesion holdout."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_predictive_dynamics as dynamics  # noqa: E402


EVAL_SCHEMA = "eve.predictive_dynamics_holdout_evaluation.v1"
MANIFEST_SCHEMA = "eve.predictive_dynamics_holdout_manifest.v1"
PROTOCOL_TRIAL_ID = "pp1-multi-hypothesis-identifiable-holdout-v1"
BOUNDARY = (
    "Frozen matched-lesion evidence for auditable dynamics selection; not "
    "subjective experience and not proof of consciousness."
)


def _digest(payload: Mapping[str, object]) -> str:
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
        raise ValueError("predictive dynamics holdout schema mismatch")
    claimed = str(payload.get("manifest_digest") or "")
    material = {key: value for key, value in payload.items() if key != "manifest_digest"}
    if not claimed or claimed != _digest(material):
        raise ValueError("predictive dynamics holdout digest mismatch")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) < 2:
        raise ValueError("predictive dynamics holdout requires scenarios")
    if payload.get("frozen_before_evidence") is not True:
        raise ValueError("holdout must be frozen before evidence")
    ids = [str(item.get("id") or "") for item in scenarios if isinstance(item, dict)]
    if len(ids) != len(scenarios) or any(not item for item in ids) or len(ids) != len(set(ids)):
        raise ValueError("holdout scenario ids must be present and unique")
    return payload


def _run_scenario(
    scenario: Mapping[str, object],
    *,
    intact: bool,
    feature_limit: float,
    threshold: float,
) -> Dict[str, object]:
    history = scenario.get("history")
    if not isinstance(history, list) or len(history) < 5:
        raise ValueError("each dynamics holdout requires at least five identifying observations")
    source_precision = float(scenario.get("source_precision") or 0.0)
    kind = str(scenario.get("kind") or "")
    if kind == "numeric":
        forecast = dynamics.forecast_numeric(
            history,
            limit=feature_limit,
            source_precision=source_precision,
            enabled_experts=dynamics.NUMERIC_EXPERTS if intact else ("velocity",),
        )
    elif kind == "categorical":
        forecast = dynamics.forecast_categorical(
            history,
            source_precision=source_precision,
            periodic_enabled=intact,
        )
    else:
        raise ValueError("holdout scenario kind must be numeric or categorical")
    result = dynamics.evaluate_observation(
        scenario.get("actual"),
        forecast,
        error_threshold=threshold,
    )
    expected = bool(scenario.get("expected_surprise"))
    observed = bool(result.get("surprising"))
    return {
        "scenario_id": str(scenario.get("id") or ""),
        "kind": kind,
        "history_length": len(history),
        "source_precision": source_precision,
        "selected_expert": forecast.get("selected_expert"),
        "prediction": forecast.get("prediction"),
        "forecast_precision": forecast.get("forecast_precision"),
        "actual": scenario.get("actual"),
        "weighted_error": result.get("weighted_error"),
        "expected_surprise": expected,
        "observed_surprise": observed,
        "correct": expected == observed,
        "action_authority": bool(forecast.get("action_authority")),
    }


def run_evaluation(
    manifest: Mapping[str, object],
    *,
    evaluated_at: str | None = None,
) -> Dict[str, object]:
    timestamp = evaluated_at or datetime.now(timezone.utc).isoformat()
    feature_limit = float(manifest.get("feature_limit") or 0.0)
    threshold = float(manifest.get("error_threshold") or 0.0)
    scenarios = manifest.get("scenarios")
    if feature_limit <= 0 or threshold <= 0 or not isinstance(scenarios, list):
        raise ValueError("validated holdout settings are missing")
    arms: Dict[str, List[Dict[str, object]]] = {"intact": [], "lesion": []}
    for arm, intact in (("intact", True), ("lesion", False)):
        arms[arm] = [
            _run_scenario(
                scenario,
                intact=intact,
                feature_limit=feature_limit,
                threshold=threshold,
            )
            for scenario in scenarios
            if isinstance(scenario, dict)
        ]
    accuracies = {
        arm: round(
            sum(int(record["correct"]) for record in records) * 100.0 / len(records),
            6,
        )
        for arm, records in arms.items()
    }
    effect = round(accuracies["intact"] - accuracies["lesion"], 6)
    intact_failures = [
        str(record["scenario_id"])
        for record in arms["intact"]
        if not record["correct"]
    ]
    low_precision = next(
        (
            record
            for record in arms["intact"]
            if record["scenario_id"] == "low-precision-linear-deviation"
        ),
        {},
    )
    checks = {
        "protocol_directional_effect_met": effect >= 20.0,
        "intact_accuracy_at_least_95_percent": accuracies["intact"] >= 95.0,
        "all_histories_identifying_length": all(
            int(record["history_length"]) >= 5 for record in arms["intact"]
        ),
        "low_precision_deviation_suppressed": bool(
            low_precision and low_precision.get("correct") and not low_precision.get("observed_surprise")
        ),
        "no_forecast_has_action_authority": not any(
            record["action_authority"] for records in arms.values() for record in records
        ),
    }
    status = "passed" if all(checks.values()) else "failed"
    evidence: List[Dict[str, object]] = []
    for arm, records in arms.items():
        for index, record in enumerate(records):
            evidence.append(
                {
                    "evidence_id": f"pp1-dynamics-{arm}-{index + 1}",
                    "trial_id": PROTOCOL_TRIAL_ID,
                    "arm": arm,
                    "value": 100.0 if record["correct"] else 0.0,
                    "observed_at": timestamp,
                    "source": "frozen-identifiable-dynamics-holdout-runner",
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
        "scenario_count_per_arm": len(arms["intact"]),
        "intact_accuracy_percent": accuracies["intact"],
        "lesion_accuracy_percent": accuracies["lesion"],
        "directional_effect": effect,
        "intact_failure_ids": intact_failures,
        "checks": checks,
        "arms": arms,
        "protocol_evidence": evidence,
        "consciousness_proven": False,
        "subjective_experience_inferred": False,
        "boundary": BOUNDARY,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate multi-hypothesis perceptual dynamics on a frozen holdout."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--evidence-output", type=Path)
    args = parser.parse_args()
    report = run_evaluation(load_manifest(args.manifest))
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
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
