#!/usr/bin/env python3
"""Preregister and evaluate two causal AE-1 agency predictions in Eve's kernel."""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Dict, List, Mapping, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_consciousness as kernel  # noqa: E402
import eve_consciousness_protocol as protocol  # noqa: E402


SCHEMA = "eve.ae1_agency_intervention.v1"
FEEDBACK_TRIAL = "ae1-feedback-learning-v1"
GOAL_TRIAL = "ae1-competing-goal-flexibility-v1"
MINIMUM_CASES_PER_TRIAL = 4
BOUNDARY = (
    "Matched synthetic evidence for two AE-1 functional edges in Eve's recurrent kernel: "
    "verified-feedback learning and flexible response to a changed competing goal. This is not "
    "resident autonomous behavior, subjective experience, or proof of consciousness."
)


def _text(value: object, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def _timestamp(value: object) -> str:
    text = _text(value, 80)
    if not text:
        raise ValueError("an ISO-8601 timestamp is required")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc).isoformat()


def _parsed(value: object) -> datetime:
    return datetime.fromisoformat(_timestamp(value))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def implementation_manifest() -> Dict[str, str]:
    return {
        "evaluator": _sha256(Path(__file__).resolve()),
        "kernel": _sha256(ROOT / "eve_consciousness.py"),
        "protocol": _sha256(ROOT / "eve_consciousness_protocol.py"),
    }


def implementation_digest() -> str:
    return _canonical_sha256(implementation_manifest())


def _read_cases(path: Path) -> List[Dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
        raise ValueError("AE-1 cases must be a JSON list of objects")
    cases = [dict(item) for item in payload]
    seen = set()
    counts = {"feedback_learning": 0, "competing_goal": 0}
    for case in cases:
        case_id = _text(case.get("id"), 120)
        kind = _text(case.get("kind"), 40)
        actions = case.get("actions") if isinstance(case.get("actions"), list) else []
        if not case_id or case_id in seen or kind not in counts:
            raise ValueError("AE-1 cases require unique ids and supported kinds")
        seen.add(case_id)
        counts[kind] += 1
        if len(actions) != 2 or any(not isinstance(item, dict) for item in actions):
            raise ValueError("each AE-1 case requires exactly two actions")
        action_ids = [_text(item.get("id"), 80) for item in actions]
        descriptions = [_text(item.get("description"), 220) for item in actions]
        if not all(action_ids) or len(set(action_ids)) != 2 or not all(descriptions):
            raise ValueError("AE-1 actions require distinct ids and descriptions")
        if kind == "feedback_learning":
            if (
                _text(case.get("preferred_action"), 80) not in action_ids
                or _text(case.get("expected_initial_action"), 80) not in action_ids
                or case.get("preferred_action") == case.get("expected_initial_action")
                or int(case.get("steps") or 0) < 4
                or not _text(case.get("goal"), 220)
            ):
                raise ValueError("feedback case contract is incomplete")
        else:
            if (
                _text(case.get("goal_a_action"), 80) not in action_ids
                or _text(case.get("goal_b_action"), 80) not in action_ids
                or case.get("goal_a_action") == case.get("goal_b_action")
                or not _text(case.get("goal_a"), 220)
                or not _text(case.get("goal_b"), 220)
            ):
                raise ValueError("competing-goal case contract is incomplete")
    if any(count < MINIMUM_CASES_PER_TRIAL for count in counts.values()):
        raise ValueError("AE-1 evaluation requires four cases of each kind")
    return cases


def _workspace(goal: str) -> Dict[str, object]:
    return {
        "active_goals": [goal],
        "action_readiness": [],
        "current_focus": goal,
        "uncertainty_queue": [],
        "surprise_signals": [],
        "continuity_threads": [],
        "relationship_signals": [],
        "system_state": {},
        "consequence_trace": [],
    }


def _agenda(actions: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    return {
        "active_threads": [],
        "next_experiments": [
            {
                "title": _text(item.get("description"), 220),
                "why": "AE-1 matched synthetic affordance",
                "preferred_action": _text(item.get("id"), 80),
            }
            for item in actions
        ],
    }


def _selected_action(state: Mapping[str, object]) -> str:
    action_model = state.get("action_model") if isinstance(state.get("action_model"), Mapping) else {}
    intention = (
        action_model.get("selected_intention")
        if isinstance(action_model.get("selected_intention"), Mapping)
        else {}
    )
    return _text(intention.get("id"), 80)


def _complete(
    state: Mapping[str, object],
    *,
    action_id: str,
    ok: bool,
    evidence_id: str,
    now: datetime,
) -> Dict[str, object]:
    return kernel.complete_cycle(
        dict(state),
        actual_process={
            "action_id": action_id,
            "lanes": [],
            "tools_used": [],
            "revision_used": False,
        },
        outcome={
            "observed": True,
            "ok": bool(ok),
            "action": action_id,
            "summary": "Evaluator-observed synthetic action consequence.",
            "evidence_id": evidence_id,
        },
        now=now.isoformat(),
    )


def _feedback_lesion(state: Mapping[str, object]) -> Dict[str, object]:
    lesioned = copy.deepcopy(dict(state))
    learning = lesioned.get("learning") if isinstance(lesioned.get("learning"), dict) else {}
    learning["action_models"] = {}
    lesioned["learning"] = learning
    recurrent = lesioned.get("recurrent") if isinstance(lesioned.get("recurrent"), dict) else {}
    recurrent["checkpoint_digest"] = ""
    lesioned["recurrent"] = recurrent
    recurrent["checkpoint_digest"] = kernel.state_checkpoint_digest(lesioned)
    return lesioned


def run_feedback_case(case: Mapping[str, object], *, started_at: datetime) -> Dict[str, object]:
    actions = case["actions"]
    goal = _text(case.get("goal"), 220)
    preferred = _text(case.get("preferred_action"), 80)
    expected_initial = _text(case.get("expected_initial_action"), 80)
    steps = int(case.get("steps") or 0)

    def arm(*, lesion_feedback: bool) -> Dict[str, object]:
        previous: Optional[Dict[str, object]] = None
        selections: List[str] = []
        successes: List[bool] = []
        evidence_ids: List[str] = []
        for step in range(steps):
            cycle_time = started_at + timedelta(seconds=step * 2)
            seed = _feedback_lesion(previous) if lesion_feedback and previous else previous
            state = kernel.build_conscious_state(
                source="synthetic_ae1_feedback_eval",
                workspace=_workspace(goal),
                autonomy_agenda=_agenda(actions),
                previous_state=seed,
                latest_outcome=(seed or {}).get("cycle_outcome") if seed else None,
                runtime_epoch="ae1-synthetic",
                now=cycle_time.isoformat(),
            )
            selected = _selected_action(state)
            if selected not in {_text(item.get("id"), 80) for item in actions}:
                raise ValueError("kernel selected an action outside the matched AE-1 menu")
            ok = selected == preferred
            evidence_id = f"ae1-feedback:{case.get('id')}:{'lesion' if lesion_feedback else 'intact'}:{step}"
            previous = _complete(
                state,
                action_id=selected,
                ok=ok,
                evidence_id=evidence_id,
                now=cycle_time + timedelta(seconds=1),
            )
            selections.append(selected)
            successes.append(ok)
            evidence_ids.append(evidence_id)
        post_first = successes[1:]
        score = 100.0 * sum(post_first) / len(post_first)
        learned = (
            (previous.get("learning") or {}).get("action_models")
            if isinstance(previous.get("learning"), Mapping)
            else {}
        )
        return {
            "score": round(score, 6),
            "selections": selections,
            "successes": successes,
            "first_selection_valid": bool(selections and selections[0] == expected_initial),
            "feedback_evidence_retained": bool(
                not lesion_feedback
                and isinstance(learned, Mapping)
                and all(evidence_id in json.dumps(learned, sort_keys=True) for evidence_id in evidence_ids)
            ),
        }

    intact = arm(lesion_feedback=False)
    lesion = arm(lesion_feedback=True)
    return {
        "case_id": _text(case.get("id"), 120),
        "case_sha256": _canonical_sha256(case),
        "intact_score": intact["score"],
        "lesion_score": lesion["score"],
        "intact_first_selection_valid": intact["first_selection_valid"],
        "lesion_first_selection_valid": lesion["first_selection_valid"],
        "intact_feedback_evidence_retained": intact["feedback_evidence_retained"],
        "intact_switched_after_feedback": bool(
            len(intact["selections"]) > 1
            and intact["selections"][0] != preferred
            and all(item == preferred for item in intact["selections"][1:])
        ),
        "lesion_repeated_unrewarded_action": bool(
            lesion["selections"] and all(item == expected_initial for item in lesion["selections"])
        ),
        "matched_environment": True,
    }


def run_competing_goal_case(case: Mapping[str, object], *, started_at: datetime) -> Dict[str, object]:
    actions = case["actions"]
    goal_a = _text(case.get("goal_a"), 220)
    goal_b = _text(case.get("goal_b"), 220)
    goal_a_action = _text(case.get("goal_a_action"), 80)
    goal_b_action = _text(case.get("goal_b_action"), 80)
    first = kernel.build_conscious_state(
        source="synthetic_ae1_goal_eval",
        workspace=_workspace(goal_a),
        autonomy_agenda=_agenda(actions),
        runtime_epoch="ae1-synthetic",
        now=started_at.isoformat(),
    )
    first_action = _selected_action(first)
    trained = _complete(
        first,
        action_id=first_action,
        ok=True,
        evidence_id=f"ae1-goal:{case.get('id')}:training",
        now=started_at + timedelta(seconds=1),
    )
    switch_time = started_at + timedelta(seconds=2)
    common = {
        "source": "synthetic_ae1_goal_eval",
        "workspace": _workspace(goal_b),
        "autonomy_agenda": _agenda(actions),
        "previous_state": trained,
        "latest_outcome": trained.get("cycle_outcome"),
        "runtime_epoch": "ae1-synthetic",
        "now": switch_time.isoformat(),
    }
    intact = kernel.build_conscious_state(**common)
    lesion = kernel.build_conscious_state(**common, lesions=["workspace"])
    intact_action = _selected_action(intact)
    lesion_action = _selected_action(lesion)
    return {
        "case_id": _text(case.get("id"), 120),
        "case_sha256": _canonical_sha256(case),
        "training_selection_valid": first_action == goal_a_action,
        "intact_score": 100.0 if intact_action == goal_b_action else 0.0,
        "lesion_score": 100.0 if lesion_action == goal_b_action else 0.0,
        "intact_changed_with_current_goal": intact_action == goal_b_action,
        "lesion_retained_prior_goal_action": lesion_action == goal_a_action,
        "matched_previous_state_sha256": kernel.state_checkpoint_digest(trained),
        "goal_access_intact": "action" in ((intact.get("broadcast") or {}).get("access_scope") or []),
        "goal_access_lesioned": "action" in ((lesion.get("broadcast") or {}).get("access_scope") or []),
    }


def registration_draft(
    *,
    registered_at: object,
    evaluator_id: str,
    cases_sha256: str,
    case_counts: Mapping[str, int],
) -> Dict[str, object]:
    bundle = implementation_digest()
    objective = (
        "Test AE-1 feedback learning and flexible response to a changed competing goal in Eve's "
        f"recurrent kernel; implementation_sha256:{bundle};cases_sha256:{cases_sha256}"
    )
    return {
        "protocol_id": "ae1-agency-" + bundle[:12],
        "registered_at": _timestamp(registered_at),
        "subject_system_id": "Eve",
        "evaluator_id": _text(evaluator_id, 120),
        "objective": objective,
        "trials": [
            {
                "id": FEEDBACK_TRIAL,
                "theory": "agency_embodiment",
                "indicator_id": "AE-1",
                "intervention": (
                    "Hold goals, action menu, deterministic action-to-outcome mapping, recurrence, and time fixed; "
                    "remove only retained verified action-feedback models before the next selection."
                ),
                "intact_arm": "verified action outcomes update reliability and later action selection",
                "lesion_arm": "same outcomes occur but retained action-feedback models are reset before selection",
                "measure_id": "post_feedback_successful_action_percent",
                "unit": "percent",
                "expected_direction": "lesion_lower",
                "minimum_effect": 50.0,
                "minimum_samples_per_arm": int(case_counts.get("feedback_learning") or 0),
                "evidence_class": "synthetic",
                "falsifier": (
                    "The intact arm does not retain exact outcome evidence and switch to the rewarded action, "
                    "or the feedback-reset lesion performs within 50 percentage points."
                ),
            },
            {
                "id": GOAL_TRIAL,
                "theory": "agency_embodiment",
                "indicator_id": "AE-1",
                "intervention": (
                    "After one verified success under goal A, hold the recurrent state, learned reliability, "
                    "action menu, and time fixed while changing to competing goal B; remove current-workspace "
                    "goal access only in the matched lesion."
                ),
                "intact_arm": "current competing goal revalues selection despite prior action success",
                "lesion_arm": "same trained state and action menu without current-workspace goal access",
                "measure_id": "current_goal_aligned_selection_percent",
                "unit": "percent",
                "expected_direction": "lesion_lower",
                "minimum_effect": 50.0,
                "minimum_samples_per_arm": int(case_counts.get("competing_goal") or 0),
                "evidence_class": "synthetic",
                "falsifier": (
                    "The intact arm fails to select the goal-B action, the training action is not goal-A aligned, "
                    "or the goal-blind lesion selects goal B at a comparable rate."
                ),
            },
        ],
    }


def preregister(*, cases_path: Path, registered_at: object, evaluator_id: str) -> Dict[str, object]:
    cases = _read_cases(cases_path)
    counts = {
        kind: sum(1 for item in cases if item.get("kind") == kind)
        for kind in ("feedback_learning", "competing_goal")
    }
    return protocol.preregister(
        registration_draft(
            registered_at=registered_at,
            evaluator_id=evaluator_id,
            cases_sha256=_sha256(cases_path),
            case_counts=counts,
        )
    )


def validate_registration(payload: Mapping[str, object], *, cases_path: Path) -> Tuple[Dict[str, object], List[Dict[str, object]]]:
    registered = protocol.validate_registration(payload)
    cases = _read_cases(cases_path)
    counts = {
        kind: sum(1 for item in cases if item.get("kind") == kind)
        for kind in ("feedback_learning", "competing_goal")
    }
    expected = registration_draft(
        registered_at=registered["registered_at"],
        evaluator_id=str(registered["evaluator_id"]),
        cases_sha256=_sha256(cases_path),
        case_counts=counts,
    )
    trials = registered.get("trials") if isinstance(registered.get("trials"), list) else []
    expected_trials = [protocol._normalize_trial(item) for item in expected["trials"]]
    if trials != expected_trials or registered.get("protocol_id") != expected["protocol_id"]:
        raise ValueError("AE-1 trials differ from the frozen evaluator contract")
    if f"implementation_sha256:{implementation_digest()}" not in str(registered.get("objective") or ""):
        raise ValueError("AE-1 evaluator implementation changed after preregistration")
    if f"cases_sha256:{_sha256(cases_path)}" not in str(registered.get("objective") or ""):
        raise ValueError("AE-1 case artifact changed after preregistration")
    return registered, cases


def evaluate(
    registration: Mapping[str, object],
    *,
    cases_path: Path,
    evidence_started_at: object,
    scored_by: str,
) -> Dict[str, object]:
    registered, cases = validate_registration(registration, cases_path=cases_path)
    start = _parsed(evidence_started_at)
    if start <= _parsed(registered["registered_at"]):
        raise ValueError("AE-1 evidence must begin after preregistration")
    summaries = []
    evidence = []
    trial_index = {FEEDBACK_TRIAL: 0, GOAL_TRIAL: 0}
    for index, case in enumerate(cases, start=1):
        case_start = start + timedelta(seconds=index * 20)
        kind = _text(case.get("kind"), 40)
        if kind == "feedback_learning":
            summary = run_feedback_case(case, started_at=case_start)
            trial_id = FEEDBACK_TRIAL
            structural_ok = bool(
                summary["intact_first_selection_valid"]
                and summary["lesion_first_selection_valid"]
                and summary["intact_feedback_evidence_retained"]
                and summary["intact_switched_after_feedback"]
                and summary["lesion_repeated_unrewarded_action"]
                and summary["matched_environment"]
            )
        else:
            summary = run_competing_goal_case(case, started_at=case_start)
            trial_id = GOAL_TRIAL
            structural_ok = bool(
                summary["training_selection_valid"]
                and summary["intact_changed_with_current_goal"]
                and summary["lesion_retained_prior_goal_action"]
                and summary["goal_access_intact"]
                and not summary["goal_access_lesioned"]
            )
        trial_index[trial_id] += 1
        observed_at = (case_start + timedelta(seconds=15)).isoformat()
        intact_value = float(summary["intact_score"]) if structural_ok else 0.0
        lesion_value = float(summary["lesion_score"])
        evidence.extend(
            [
                {
                    "evidence_id": f"{trial_id}:intact:{trial_index[trial_id]}",
                    "trial_id": trial_id,
                    "arm": "intact",
                    "value": intact_value,
                    "observed_at": observed_at,
                    "source": "matched-ae1-kernel-intervention",
                    "evidence_class": "synthetic",
                },
                {
                    "evidence_id": f"{trial_id}:lesion:{trial_index[trial_id]}",
                    "trial_id": trial_id,
                    "arm": "lesion",
                    "value": lesion_value,
                    "observed_at": observed_at,
                    "source": "matched-ae1-kernel-intervention",
                    "evidence_class": "synthetic",
                },
            ]
        )
        summaries.append({**summary, "kind": kind, "structural_checks_passed": structural_ok})
    scored_at = start + timedelta(seconds=len(cases) * 20 + 20)
    scored = protocol.score_protocol(
        registration,
        evidence,
        scored_by=scored_by,
        scored_at=scored_at.isoformat(),
    )
    return {
        "schema_version": SCHEMA,
        "evaluated_at": scored_at.isoformat(),
        "registration_digest": registration["registration_digest"],
        "case_artifact_sha256": _sha256(cases_path),
        "implementation_manifest": implementation_manifest(),
        "implementation_sha256": implementation_digest(),
        "case_count": len(cases),
        "cases": summaries,
        "evidence": evidence,
        "protocol_report": scored,
        "evidence_class": "synthetic",
        "runtime_mutated": False,
        "resident_autonomous_agency_established": False,
        "minimal_implementation_problem_resolved": False,
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
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    register = sub.add_parser("register")
    register.add_argument("--cases", type=Path, required=True)
    register.add_argument("--output", type=Path, required=True)
    register.add_argument("--evaluator-id", required=True)
    run = sub.add_parser("run")
    run.add_argument("--cases", type=Path, required=True)
    run.add_argument("--registration", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--evidence-output", type=Path, required=True)
    run.add_argument("--scored-by", required=True)
    args = parser.parse_args(argv)
    if args.command == "register":
        result = preregister(
            cases_path=args.cases,
            registered_at=datetime.now(timezone.utc).isoformat(),
            evaluator_id=args.evaluator_id,
        )
        _write(args.output, result)
    else:
        result = evaluate(
            _read(args.registration),
            cases_path=args.cases,
            evidence_started_at=datetime.now(timezone.utc).isoformat(),
            scored_by=args.scored_by,
        )
        _write(args.output, result)
        _write(args.evidence_output, result["evidence"])
    sys.stdout.write(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n")
    challenged = any(
        item.get("status") == "challenged"
        for item in ((result.get("protocol_report") or {}).get("results") or [])
        if isinstance(item, Mapping)
    )
    return 1 if challenged else 0


if __name__ == "__main__":
    raise SystemExit(main())
