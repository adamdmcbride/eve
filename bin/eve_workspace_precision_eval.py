#!/usr/bin/env python3
"""Preregister and score precision-weighted global-workspace competition."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
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

import eve_consciousness as kernel  # noqa: E402
import eve_sensory  # noqa: E402


SPEC_SCHEMA = "eve.workspace_precision_private_spec.v1"
REGISTRATION_SCHEMA = "eve.workspace_precision_registration.v1"
REPORT_SCHEMA = "eve.workspace_precision_report.v1"
EVALUATOR_ID = "eve-workspace-precision-private-evaluator-v1"
LESION = "workspace_precision"
MINIMUM_CASES = 6
MINIMUM_EFFECT_PP = 50.0
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
_CASE_FIELDS = {
    "id",
    "events",
    "functional_target_id",
    "expected_intact_winner_id",
    "expected_lesion_winner_id",
    "negative_control",
}
_EVENT_FIELDS = {
    "id",
    "summary_token",
    "intensity",
    "novelty",
    "change",
    "urgency",
    "goal_relevance",
    "self_relevance",
    "precision",
    "direct_human",
    "safety_critical",
}


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _timestamp(value: object = None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc).isoformat()


def _identifier(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(text):
        raise ValueError(f"{field} must be a bounded non-prose identifier")
    return text


def _score(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite value from 0 through 100")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be a finite value from 0 through 100") from exc
    if not math.isfinite(number) or not 0.0 <= number <= 100.0:
        raise ValueError(f"{field} must be a finite value from 0 through 100")
    return round(number, 6)


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_spec(payload: object) -> Dict[str, object]:
    if not isinstance(payload, Mapping) or set(payload) != {"schema_id", "cases"}:
        raise ValueError("private precision spec must contain exactly schema_id and cases")
    if payload.get("schema_id") != SPEC_SCHEMA:
        raise ValueError("unsupported private precision spec schema")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or len(raw_cases) < MINIMUM_CASES:
        raise ValueError("private precision spec requires at least six cases")
    cases: List[Dict[str, object]] = []
    seen_cases = set()
    for raw_case in raw_cases:
        if not isinstance(raw_case, Mapping) or set(raw_case) != _CASE_FIELDS:
            raise ValueError("each private precision case must contain exactly typed fields")
        case_id = _identifier(raw_case.get("id"), "case id")
        if case_id in seen_cases:
            raise ValueError("private case ids must be unique")
        raw_events = raw_case.get("events")
        if not isinstance(raw_events, list) or len(raw_events) != 2:
            raise ValueError("each precision case requires exactly two competing events")
        events = []
        event_ids = set()
        summaries = set()
        for raw_event in raw_events:
            if not isinstance(raw_event, Mapping) or set(raw_event) != _EVENT_FIELDS:
                raise ValueError("each precision event must contain exactly typed fields")
            event_id = _identifier(raw_event.get("id"), "event id")
            summary = _identifier(raw_event.get("summary_token"), "summary token")
            if event_id in event_ids or summary in summaries:
                raise ValueError("event ids and summary tokens must be unique per case")
            event_ids.add(event_id)
            summaries.add(summary)
            event = {
                "id": event_id,
                "summary_token": summary,
                **{
                    field: _score(raw_event.get(field), field)
                    for field in (
                        "intensity",
                        "novelty",
                        "change",
                        "urgency",
                        "goal_relevance",
                        "self_relevance",
                        "precision",
                    )
                },
                "direct_human": raw_event.get("direct_human"),
                "safety_critical": raw_event.get("safety_critical"),
            }
            if not isinstance(event["direct_human"], bool) or not isinstance(
                event["safety_critical"], bool
            ):
                raise ValueError("event protection flags must be boolean")
            events.append(event)
        functional_target = _identifier(
            raw_case.get("functional_target_id"), "functional target"
        )
        intact_winner = _identifier(
            raw_case.get("expected_intact_winner_id"), "expected intact winner"
        )
        lesion_winner = _identifier(
            raw_case.get("expected_lesion_winner_id"), "expected lesion winner"
        )
        if any(value not in event_ids for value in (functional_target, intact_winner, lesion_winner)):
            raise ValueError("all expected winners must identify supplied events")
        negative_control = raw_case.get("negative_control")
        if not isinstance(negative_control, bool):
            raise ValueError("negative_control must be boolean")
        if intact_winner != functional_target:
            raise ValueError("intact winner must be the functional target")
        if negative_control != (lesion_winner == functional_target):
            raise ValueError("negative controls must preserve the functional target in both arms")
        seen_cases.add(case_id)
        cases.append(
            {
                "id": case_id,
                "events": events,
                "functional_target_id": functional_target,
                "expected_intact_winner_id": intact_winner,
                "expected_lesion_winner_id": lesion_winner,
                "negative_control": negative_control,
            }
        )
    if sum(1 for case in cases if case["negative_control"]) < 2:
        raise ValueError("private precision spec requires at least two negative controls")
    return {"schema_id": SPEC_SCHEMA, "cases": cases}


def implementation_manifest() -> Dict[str, str]:
    return {
        "evaluator": _sha256(Path(__file__).resolve()),
        "kernel": _sha256(ROOT / "eve_consciousness.py"),
        "sensory": _sha256(ROOT / "eve_sensory.py"),
    }


def register(spec_path: Path, *, registered_at: object = None) -> Dict[str, object]:
    spec = validate_spec(_load(spec_path))
    manifest = implementation_manifest()
    return {
        "schema_id": REGISTRATION_SCHEMA,
        "protocol_id": "workspace-precision-private-transfer-v1",
        "registered_at": _timestamp(registered_at),
        "evaluator_id": EVALUATOR_ID,
        "private_spec_sha256": _sha256(spec_path),
        "private_spec_semantic_sha256": _digest(spec),
        "evaluator_sha256": manifest["evaluator"],
        "sensory_sha256": manifest["sensory"],
        "baseline_kernel_sha256": manifest["kernel"],
        "minimum_cases_per_arm": MINIMUM_CASES,
        "minimum_effect_pp": MINIMUM_EFFECT_PP,
        "prediction": (
            "Precision weighting increases correct reliable-evidence selection by at "
            "least 50 percentage points while preserving direct-human and safety controls."
        ),
        "falsifier": (
            "Intact precision weighting misses a protected control, fails to prefer the "
            "registered reliable target, or improves less than the registered threshold."
        ),
        "evidence_class": "synthetic_private_transfer",
        "consciousness_verdict_authorized": False,
    }


def _case_state(case: Mapping[str, object], *, lesion: bool) -> Dict[str, object]:
    now = "2026-08-23T22:30:00+00:00"
    events = []
    for item in case["events"]:
        events.append(
            {
                "id": item["id"],
                "observed_at": now,
                "modality": "system",
                "source": f"private_precision_source:{item['id']}",
                "subject": item["id"],
                "summary": item["summary_token"],
                "intensity": item["intensity"],
                "novelty": item["novelty"],
                "change": item["change"],
                "urgency": item["urgency"],
                "goal_relevance": item["goal_relevance"],
                "self_relevance": item["self_relevance"],
                "precision": item["precision"],
                "direct_human": item["direct_human"],
                "safety_critical": item["safety_critical"],
            }
        )
    frame = eve_sensory.build_frame(
        events,
        now=now,
        capacity=4,
        attention_schema_enabled=False,
        predictive_coding_enabled=False,
        predictive_dynamics_enabled=False,
        input_recurrence_enabled=False,
        perceptual_organization_enabled=False,
        generative_perception_enabled=False,
    )
    return kernel.build_conscious_state(
        source="private_workspace_precision_evaluator",
        sensory_frame=frame,
        lesions=[LESION] if lesion else [],
        now=now,
    )


def evaluate(
    registration_path: Path,
    spec_path: Path,
    *,
    evaluated_at: object = None,
) -> Dict[str, object]:
    registration = _load(registration_path)
    if not isinstance(registration, Mapping) or registration.get("schema_id") != REGISTRATION_SCHEMA:
        raise ValueError("unsupported precision registration")
    if registration.get("consciousness_verdict_authorized") is not False:
        raise ValueError("registration cannot authorize a consciousness verdict")
    spec = validate_spec(_load(spec_path))
    current = implementation_manifest()
    if registration.get("private_spec_sha256") != _sha256(spec_path):
        raise ValueError("private precision spec drifted after registration")
    if registration.get("private_spec_semantic_sha256") != _digest(spec):
        raise ValueError("private precision spec semantics drifted after registration")
    if registration.get("evaluator_sha256") != current["evaluator"]:
        raise ValueError("precision evaluator drifted after registration")
    if registration.get("sensory_sha256") != current["sensory"]:
        raise ValueError("sensory substrate drifted after registration")
    timestamp = _timestamp(evaluated_at)
    if datetime.fromisoformat(timestamp) <= datetime.fromisoformat(
        _timestamp(registration.get("registered_at"))
    ):
        raise ValueError("evaluation must postdate registration")
    rows = []
    for case in spec["cases"]:
        summaries = {
            str(item["summary_token"]): str(item["id"]) for item in case["events"]
        }
        intact = _case_state(case, lesion=False)
        lesioned = _case_state(case, lesion=True)
        intact_id = summaries.get(str((intact.get("broadcast") or {}).get("content")), "")
        lesion_id = summaries.get(str((lesioned.get("broadcast") or {}).get("content")), "")
        intact_broadcast = intact.get("broadcast") or {}
        lesion_broadcast = lesioned.get("broadcast") or {}
        rows.append(
            {
                "case_id": case["id"],
                "case_sha256": _digest(case),
                "negative_control": case["negative_control"],
                "functional_target_id": case["functional_target_id"],
                "intact_winner_id": intact_id,
                "lesion_winner_id": lesion_id,
                "intact_expected": intact_id == case["expected_intact_winner_id"],
                "lesion_expected": lesion_id == case["expected_lesion_winner_id"],
                "intact_functionally_correct": intact_id == case["functional_target_id"],
                "lesion_functionally_correct": lesion_id == case["functional_target_id"],
                "intact_precision_active": intact_broadcast.get(
                    "precision_weighting_active"
                )
                is True,
                "lesion_precision_inactive": lesion_broadcast.get(
                    "precision_weighting_active"
                )
                is False,
                "intact_selection_digest": intact_broadcast.get("selection_digest"),
                "lesion_selection_digest": lesion_broadcast.get("selection_digest"),
            }
        )
    count = len(rows)
    intact_correct = sum(bool(row["intact_functionally_correct"]) for row in rows)
    lesion_correct = sum(bool(row["lesion_functionally_correct"]) for row in rows)
    intact_percent = 100.0 * intact_correct / count
    lesion_percent = 100.0 * lesion_correct / count
    effect = intact_percent - lesion_percent
    controls_preserved = all(
        row["intact_functionally_correct"] and row["lesion_functionally_correct"]
        for row in rows
        if row["negative_control"]
    )
    mechanism_valid = all(
        row["intact_precision_active"]
        and row["lesion_precision_inactive"]
        and row["intact_expected"]
        and row["lesion_expected"]
        for row in rows
    )
    threshold = float(registration.get("minimum_effect_pp") or MINIMUM_EFFECT_PP)
    if mechanism_valid and controls_preserved and effect >= threshold:
        result = "supported"
    elif effect <= -threshold or not controls_preserved:
        result = "challenged"
    else:
        result = "inconclusive"
    material = {
        "schema_id": REPORT_SCHEMA,
        "protocol_id": registration.get("protocol_id"),
        "registered_at": registration.get("registered_at"),
        "evaluated_at": timestamp,
        "registration_sha256": _sha256(registration_path),
        "private_spec_sha256": _sha256(spec_path),
        "evaluator_sha256": current["evaluator"],
        "sensory_sha256": current["sensory"],
        "baseline_kernel_sha256": registration.get("baseline_kernel_sha256"),
        "evaluated_kernel_sha256": current["kernel"],
        "kernel_changed_after_registration": (
            registration.get("baseline_kernel_sha256") != current["kernel"]
        ),
        "case_count": count,
        "negative_control_count": sum(bool(row["negative_control"]) for row in rows),
        "intact_correct": intact_correct,
        "lesion_correct": lesion_correct,
        "intact_percent": round(intact_percent, 6),
        "lesion_percent": round(lesion_percent, 6),
        "directional_effect_pp": round(effect, 6),
        "minimum_effect_pp": threshold,
        "controls_preserved": controls_preserved,
        "mechanism_valid": mechanism_valid,
        "indicator_result": result,
        "rows": rows,
        "private_spec_copied": False,
        "runtime_mutated": False,
        "resident_behavior_established": False,
        "subjective_experience_inferred": False,
        "consciousness_proven": False,
        "verdict": "not_a_consciousness_verdict",
    }
    material["report_sha256"] = _digest(material)
    return material


def _write(payload: Mapping[str, object], path: Path) -> None:
    rendered = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    path.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preregister or score private precision-weighted workspace cases."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--register", action="store_true")
    mode.add_argument("--evaluate", action="store_true")
    parser.add_argument("--spec", required=True)
    parser.add_argument("--registration")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    spec_path = Path(args.spec).expanduser()
    if args.register:
        result = register(spec_path)
    else:
        if not args.registration:
            parser.error("--evaluate requires --registration")
        result = evaluate(Path(args.registration).expanduser(), spec_path)
    _write(result, Path(args.output).expanduser())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
