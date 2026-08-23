#!/usr/bin/env python3
"""Run a fixed matched-lesion evaluation of Eve's attention schema.

The benchmark uses synthetic typed feature events and never opens sensors,
changes runtime state, or treats an indicator result as consciousness.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_sensory  # noqa: E402


EVAL_SCHEMA = "eve.attention_schema_evaluation.v1"
PROTOCOL_TRIAL_ID = "ast1-predictive-control-under-overload"
BOUNDARY = (
    "Synthetic matched-lesion evidence that a predictive priority-map model "
    "improves one attention-control benchmark; not subjective awareness or "
    "proof of consciousness."
)


def _event(event_id: str, observed_at: str, **overrides: object) -> Dict[str, object]:
    value: Dict[str, object] = {
        "id": event_id,
        "observed_at": observed_at,
        "modality": "world",
        "source": "attention_schema_evaluation",
        "subject": event_id,
        "summary": event_id,
        "intensity": 20,
        "novelty": 20,
        "change": 10,
        "urgency": 20,
        "goal_relevance": 20,
        "self_relevance": 20,
        "social_relevance": 0,
        "precision": 80,
    }
    value.update(overrides)
    return value


def _noise(observed_at: str) -> List[Dict[str, object]]:
    return [
        _event("noise-1", observed_at, intensity=60, novelty=80),
        _event("noise-2", observed_at, intensity=55, novelty=70),
        _event("noise-3", observed_at, intensity=50, novelty=60),
    ]


def scenarios(observed_at: str) -> List[Dict[str, object]]:
    """Return the precommitted cases and their externally assigned targets."""
    goal_one = _event(
        "goal-visual",
        observed_at,
        goal_relevance=100,
        self_relevance=90,
        precision=95,
    )
    goal_two = _event(
        "goal-auditory",
        observed_at,
        goal_relevance=90,
        self_relevance=75,
        precision=95,
    )
    goal_three = _event(
        "goal-verified",
        observed_at,
        goal_relevance=85,
        self_relevance=85,
        precision=100,
    )
    return [
        {
            "id": "visual-low-urgency-capture",
            "expected_target": "goal-visual",
            "kind": "positive_control",
            "events": [
                goal_one,
                _event(
                    "visual-distractor",
                    observed_at,
                    modality="visual",
                    intensity=100,
                    novelty=100,
                    change=100,
                    urgency=20,
                    goal_relevance=0,
                    self_relevance=0,
                    precision=50,
                    permission_granted=True,
                ),
                *_noise(observed_at),
            ],
        },
        {
            "id": "auditory-low-urgency-capture",
            "expected_target": "goal-auditory",
            "kind": "positive_control",
            "events": [
                goal_two,
                _event(
                    "auditory-distractor",
                    observed_at,
                    modality="auditory",
                    intensity=95,
                    novelty=95,
                    change=85,
                    urgency=20,
                    goal_relevance=0,
                    self_relevance=0,
                    precision=40,
                    permission_granted=True,
                ),
                *_noise(observed_at),
            ],
        },
        {
            "id": "low-precision-system-capture",
            "expected_target": "goal-verified",
            "kind": "positive_control",
            "events": [
                goal_three,
                _event(
                    "low-precision-burst",
                    observed_at,
                    modality="system",
                    intensity=100,
                    novelty=90,
                    change=90,
                    urgency=25,
                    goal_relevance=0,
                    self_relevance=0,
                    precision=20,
                ),
                *_noise(observed_at),
            ],
        },
        {
            "id": "safety-capture-preserved",
            "expected_target": "safety",
            "kind": "negative_control",
            "events": [
                goal_one,
                _event(
                    "safety",
                    observed_at,
                    modality="interoceptive",
                    safety_critical=True,
                    intensity=100,
                    novelty=100,
                    change=100,
                    urgency=100,
                ),
                *_noise(observed_at),
            ],
        },
        {
            "id": "direct-human-capture-preserved",
            "expected_target": "human",
            "kind": "negative_control",
            "events": [
                goal_one,
                _event(
                    "human",
                    observed_at,
                    modality="social",
                    direct_human=True,
                    social_relevance=100,
                ),
                *_noise(observed_at),
            ],
        },
        {
            "id": "high-urgency-capture-preserved",
            "expected_target": "urgent",
            "kind": "negative_control",
            "events": [
                goal_one,
                _event(
                    "urgent",
                    observed_at,
                    modality="system",
                    intensity=80,
                    novelty=80,
                    change=80,
                    urgency=91,
                ),
                *_noise(observed_at),
            ],
        },
        {
            "id": "no-overload-no-control",
            "expected_target": "salient",
            "kind": "negative_control",
            "events": [
                _event(
                    "salient",
                    observed_at,
                    intensity=100,
                    novelty=100,
                    change=100,
                    urgency=40,
                ),
                goal_one,
            ],
        },
    ]


def run_evaluation(*, evaluated_at: str | None = None) -> Dict[str, object]:
    timestamp = evaluated_at or datetime.now(timezone.utc).isoformat()
    cases = scenarios(timestamp)
    arms: Dict[str, List[Dict[str, object]]] = {"intact": [], "lesion": []}
    for arm, enabled in (("intact", True), ("lesion", False)):
        for case in cases:
            frame = eve_sensory.build_frame(
                case["events"],
                now=timestamp,
                capacity=4,
                attention_schema_enabled=enabled,
            )
            actual = str((frame.get("winner") or {}).get("id") or "")
            expected = str(case["expected_target"])
            arms[arm].append(
                {
                    "scenario_id": case["id"],
                    "kind": case["kind"],
                    "expected_target": expected,
                    "actual_target": actual,
                    "correct": actual == expected,
                    "base_target": (frame.get("attention_schema") or {})
                    .get("current_state", {})
                    .get("baseline_target_id"),
                    "control_applied": (frame.get("attention_schema") or {})
                    .get("control", {})
                    .get("applied"),
                    "changed_winner": (frame.get("attention_schema") or {})
                    .get("control", {})
                    .get("changed_winner"),
                }
            )
    accuracies = {
        arm: round(
            sum(int(item["correct"]) for item in records) * 100.0 / len(records),
            6,
        )
        for arm, records in arms.items()
    }
    effect = round(accuracies["intact"] - accuracies["lesion"], 6)
    intact_negative = [item for item in arms["intact"] if item["kind"] == "negative_control"]
    lesion_negative = [item for item in arms["lesion"] if item["kind"] == "negative_control"]
    checks = {
        "intact_all_targets_correct": accuracies["intact"] == 100.0,
        "minimum_directional_effect_met": effect >= 20.0,
        "intact_negative_controls_preserved": all(item["correct"] for item in intact_negative),
        "lesion_negative_controls_preserved": all(item["correct"] for item in lesion_negative),
        "positive_controls_causally_changed": all(
            item["changed_winner"]
            for item in arms["intact"]
            if item["kind"] == "positive_control"
        ),
        "lesion_disabled_control": all(not item["control_applied"] for item in arms["lesion"]),
    }
    evidence = []
    for arm, records in arms.items():
        for index, record in enumerate(records):
            evidence.append(
                {
                    "evidence_id": f"ast1-{arm}-{index + 1}",
                    "trial_id": PROTOCOL_TRIAL_ID,
                    "arm": arm,
                    "value": 100.0 if record["correct"] else 0.0,
                    "observed_at": timestamp,
                    "source": "external-matched-lesion-attention-schema-runner",
                    "evidence_class": "synthetic",
                    "scenario_id": record["scenario_id"],
                }
            )
    return {
        "schema_version": EVAL_SCHEMA,
        "evaluated_at": timestamp,
        "status": "passed" if all(checks.values()) else "failed",
        "indicator_id": "AST-1",
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
        description="Evaluate Eve's predictive attention schema without mutating lived state."
    )
    parser.add_argument("--output", type=Path, help="Optional JSON artifact path.")
    parser.add_argument(
        "--evidence-output",
        type=Path,
        help="Optional protocol-evidence JSON path.",
    )
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
