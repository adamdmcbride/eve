#!/usr/bin/env python3
"""Run Eve's fixed recurrent predictive-perception lesion benchmark."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_sensory  # noqa: E402


EVAL_SCHEMA = "eve.predictive_perception_evaluation.v1"
PROTOCOL_TRIAL_ID = "pp1-recurrent-feature-prediction-error"
BOUNDARY = (
    "Synthetic matched-lesion evidence for recurrent feature prediction and "
    "precision-weighted error; not subjective experience or proof of consciousness."
)


def scenario_specs() -> List[Dict[str, object]]:
    return [
        {"id": "expected-ramp-up-10", "values": [10, 20, 30], "expected_surprise": False},
        {"id": "expected-ramp-up-15", "values": [30, 45, 60], "expected_surprise": False},
        {"id": "expected-ramp-down-15", "values": [80, 65, 50], "expected_surprise": False},
        {"id": "unexpected-overshoot", "values": [10, 20, 55], "expected_surprise": True},
        {"id": "unexpected-reversal", "values": [70, 55, 70], "expected_surprise": True},
        {
            "id": "unexpected-categorical-change",
            "values": ["stable", "stable", "movement"],
            "expected_surprise": True,
            "categorical": True,
        },
    ]


def _event(
    value: object,
    *,
    observed_at: str,
    session_id: str,
    categorical: bool,
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
            "precision": 100,
        },
        allowed_modalities=["visual"],
        session_id=session_id,
        now=observed_at,
    )


def _run_scenario(
    spec: Dict[str, object],
    *,
    enabled: bool,
    start: datetime,
) -> Dict[str, object]:
    frame: Dict[str, object] = {}
    session_id = "pp-eval-" + str(spec["id"])
    for index, value in enumerate(spec["values"]):
        observed_at = (start + timedelta(seconds=index * 10)).isoformat()
        frame = eve_sensory.build_frame(
            [
                _event(
                    value,
                    observed_at=observed_at,
                    session_id=session_id,
                    categorical=bool(spec.get("categorical")),
                )
            ],
            prior_frame=frame,
            now=observed_at,
            predictive_coding_enabled=enabled,
        )
    winner = frame.get("winner") if isinstance(frame.get("winner"), dict) else {}
    observed_surprise = bool(winner.get("dishabituated"))
    expected_surprise = bool(spec["expected_surprise"])
    prediction_error = (
        winner.get("prediction_error")
        if isinstance(winner.get("prediction_error"), dict)
        else {}
    )
    return {
        "scenario_id": spec["id"],
        "expected_surprise": expected_surprise,
        "observed_surprise": observed_surprise,
        "correct": observed_surprise == expected_surprise,
        "prediction_comparable": bool(prediction_error.get("comparable")),
        "weighted_error": prediction_error.get("weighted_error"),
        "predicted_change": bool(winner.get("predicted_change")),
        "prediction_violation": bool(winner.get("prediction_violation")),
    }


def run_evaluation(*, evaluated_at: str | None = None) -> Dict[str, object]:
    timestamp = evaluated_at or datetime.now(timezone.utc).isoformat()
    start = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    specs = scenario_specs()
    arms: Dict[str, List[Dict[str, object]]] = {"intact": [], "lesion": []}
    for arm, enabled in (("intact", True), ("lesion", False)):
        for offset, spec in enumerate(specs):
            arms[arm].append(
                _run_scenario(
                    spec,
                    enabled=enabled,
                    start=start + timedelta(minutes=offset),
                )
            )
    accuracies = {
        arm: round(
            sum(int(item["correct"]) for item in records) * 100.0 / len(records),
            6,
        )
        for arm, records in arms.items()
    }
    effect = round(accuracies["intact"] - accuracies["lesion"], 6)
    expected_intact = [item for item in arms["intact"] if not item["expected_surprise"]]
    unexpected_intact = [item for item in arms["intact"] if item["expected_surprise"]]
    checks = {
        "intact_all_classifications_correct": accuracies["intact"] == 100.0,
        "minimum_directional_effect_met": effect >= 20.0,
        "expected_change_suppressed": all(
            item["correct"] and item["predicted_change"] for item in expected_intact
        ),
        "unexpected_violations_preserved": all(
            item["correct"] and item["prediction_violation"] for item in unexpected_intact
        ),
        "intact_used_comparable_predictions": all(
            item["prediction_comparable"] for item in arms["intact"]
        ),
        "lesion_removed_prediction_comparison": all(
            not item["prediction_comparable"] for item in arms["lesion"]
        ),
    }
    evidence = []
    for arm, records in arms.items():
        for index, record in enumerate(records):
            evidence.append(
                {
                    "evidence_id": f"pp1-{arm}-{index + 1}",
                    "trial_id": PROTOCOL_TRIAL_ID,
                    "arm": arm,
                    "value": 100.0 if record["correct"] else 0.0,
                    "observed_at": timestamp,
                    "source": "external-matched-lesion-predictive-perception-runner",
                    "evidence_class": "synthetic",
                    "scenario_id": record["scenario_id"],
                }
            )
    return {
        "schema_version": EVAL_SCHEMA,
        "evaluated_at": timestamp,
        "status": "passed" if all(checks.values()) else "failed",
        "indicator_id": "PP-1",
        "protocol_trial_id": PROTOCOL_TRIAL_ID,
        "intact_accuracy_percent": accuracies["intact"],
        "lesion_accuracy_percent": accuracies["lesion"],
        "directional_effect": effect,
        "checks": checks,
        "arms": arms,
        "protocol_evidence": evidence,
        "consciousness_proven": False,
        "subjective_experience_inferred": False,
        "boundary": BOUNDARY,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate Eve's recurrent predictive perception without mutating lived state."
    )
    parser.add_argument("--output", type=Path, help="Optional JSON artifact path.")
    parser.add_argument("--evidence-output", type=Path, help="Optional protocol evidence path.")
    args = parser.parse_args()
    report = run_evaluation()
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
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
