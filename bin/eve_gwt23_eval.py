#!/usr/bin/env python3
"""Preregister and score separated GWT-2 and GWT-3 workspace lesions."""

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

import eve_consciousness as kernel  # noqa: E402
import eve_consciousness_protocol as protocol  # noqa: E402


SCHEMA_ID = "eve.gwt23_selective_broadcast_intervention.v1"
SPEC_SCHEMA_ID = "eve.gwt23_private_spec.v1"
GWT2_TRIAL_ID = "gwt2-limited-capacity-selection-v1"
GWT3_TRIAL_ID = "gwt3-broadcast-access-receipt-v1"
BOUNDARY = (
    "Matched synthetic functional evidence for limited-capacity selection and "
    "broadcast-to-action access in Eve's software workspace; not resident "
    "multi-model concurrency, universal module consumption, subjective access, "
    "or proof of consciousness."
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
_CASE_FIELDS = {"id", "candidates", "expected_winner_id", "expected_action_id"}
_CANDIDATE_FIELDS = {"id", "module_id", "content_token", "score"}


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
        "conscious_state_kernel": _sha256(ROOT / "eve_consciousness.py"),
        "protocol": _sha256(ROOT / "eve_consciousness_protocol.py"),
    }


def implementation_digest() -> str:
    return _digest(implementation_manifest())


def _identifier(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(text):
        raise ValueError(f"{field} must be a bounded non-prose identifier")
    return text


def _score(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("candidate score must be a finite number from 0 through 100")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("candidate score must be a finite number from 0 through 100") from exc
    if not math.isfinite(number) or not 0.0 <= number <= 100.0:
        raise ValueError("candidate score must be a finite number from 0 through 100")
    return round(number, 6)


def validate_spec(payload: Mapping[str, object]) -> Dict[str, object]:
    if payload.get("schema_id") != SPEC_SCHEMA_ID:
        raise ValueError("unsupported GWT-2/GWT-3 private spec schema")
    if set(payload) - {"schema_id", "cases"}:
        raise ValueError("GWT-2/GWT-3 private spec has unknown top-level fields")
    raw_cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    if len(raw_cases) < 6:
        raise ValueError("GWT-2/GWT-3 evaluation requires at least six private cases")
    cases: List[Dict[str, object]] = []
    seen_cases = set()
    for raw in raw_cases:
        if not isinstance(raw, Mapping) or set(raw) != _CASE_FIELDS:
            raise ValueError("every GWT-2/GWT-3 case must contain exactly the typed fields")
        case_id = _identifier(raw.get("id"), "case id")
        if case_id in seen_cases:
            raise ValueError("private case ids must be unique")
        expected_winner = _identifier(raw.get("expected_winner_id"), "expected winner")
        expected_action = _identifier(raw.get("expected_action_id"), "expected action")
        raw_candidates = raw.get("candidates") if isinstance(raw.get("candidates"), list) else []
        if not 3 <= len(raw_candidates) <= 8:
            raise ValueError("each case requires three to eight specialist candidates")
        candidates: List[Dict[str, object]] = []
        candidate_ids = set()
        module_ids = set()
        content_tokens = set()
        scores = set()
        for candidate in raw_candidates:
            if not isinstance(candidate, Mapping) or set(candidate) != _CANDIDATE_FIELDS:
                raise ValueError("every candidate must contain exactly the typed fields")
            candidate_id = _identifier(candidate.get("id"), "candidate id")
            module_id = _identifier(candidate.get("module_id"), "module id")
            content_token = _identifier(candidate.get("content_token"), "content token")
            candidate_score = _score(candidate.get("score"))
            if candidate_id in candidate_ids or content_token in content_tokens:
                raise ValueError("candidate ids and content tokens must be unique per case")
            candidate_ids.add(candidate_id)
            module_ids.add(module_id)
            content_tokens.add(content_token)
            scores.add(candidate_score)
            candidates.append(
                {
                    "id": candidate_id,
                    "module_id": module_id,
                    "content_token": content_token,
                    "score": candidate_score,
                }
            )
        if len(module_ids) < 3:
            raise ValueError("each case requires at least three specialized source modules")
        if len(scores) != len(candidates):
            raise ValueError("candidate scores must be unique to freeze one expected winner")
        by_id = {item["id"]: item for item in candidates}
        if expected_winner not in by_id:
            raise ValueError("expected winner must identify a supplied candidate")
        if by_id[expected_winner]["score"] != max(item["score"] for item in candidates):
            raise ValueError("expected winner must have the preregistered highest score")
        if expected_action != by_id[expected_winner]["content_token"]:
            raise ValueError("expected action must match the winning content token")
        seen_cases.add(case_id)
        cases.append(
            {
                "id": case_id,
                "candidates": candidates,
                "expected_winner_id": expected_winner,
                "expected_action_id": expected_action,
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
        "protocol_id": "gwt23-selective-broadcast-" + implementation[:12],
        "registered_at": _timestamp(registered_at),
        "subject_system_id": "Eve",
        "evaluator_id": str(evaluator_id or "").strip()[:120],
        "objective": (
            f"implementation_sha256:{implementation};"
            f"private_spec_sha256:{spec_digest};"
            "Separate limited-capacity selection from global broadcast access "
            "under two matched interventions."
        ),
        "trials": [
            {
                "id": GWT2_TRIAL_ID,
                "theory": "global_workspace",
                "indicator_id": "GWT-2",
                "intervention": (
                    "Hold ranked specialist candidates fixed and remove only the "
                    "one-item workspace bottleneck, admitting the candidate bundle."
                ),
                "intact_arm": "one highest-ranked coalition enters a capacity-one workspace",
                "lesion_arm": "the same competing coalitions enter as an unfiltered bundle",
                "measure_id": "correct_selective_capacity_classification_percent",
                "unit": "percent",
                "expected_direction": "lesion_lower",
                "minimum_effect": 50.0,
                "minimum_samples_per_arm": 6,
                "evidence_class": "synthetic",
                "falsifier": (
                    "The intact workspace does not select exactly one preregistered "
                    "winner, or removing the bottleneck preserves that selection."
                ),
            },
            {
                "id": GWT3_TRIAL_ID,
                "theory": "global_workspace",
                "indicator_id": "GWT-3",
                "intervention": (
                    "Hold selection and the action menu fixed and remove only "
                    "broadcast access after the winner is selected."
                ),
                "intact_arm": "the selected broadcast is available system-wide and its digest changes action valuation",
                "lesion_arm": "the same selected content has no subscriber access or action receipt",
                "measure_id": "correct_broadcast_access_and_action_receipt_percent",
                "unit": "percent",
                "expected_direction": "lesion_lower",
                "minimum_effect": 50.0,
                "minimum_samples_per_arm": 6,
                "evidence_class": "synthetic",
                "falsifier": (
                    "Selection differs across access arms, the intact broadcast lacks "
                    "the full access contract or exact action receipt, or the access "
                    "lesion preserves the receipt."
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
        raise ValueError("GWT-2/GWT-3 registration differs from the frozen evaluator/spec")
    return registered


def _coalitions(case: Mapping[str, object]) -> List[Dict[str, object]]:
    return sorted(
        [
            {
                "id": item["id"],
                "kind": item["module_id"],
                "source": "private_specialist:" + str(item["module_id"]),
                "content": item["content_token"],
                "score": item["score"],
                "components": {},
            }
            for item in case["candidates"]
        ],
        key=lambda item: (float(item["score"]), str(item["id"])),
        reverse=True,
    )


def _action_affordances(
    winner: Mapping[str, object],
    broadcast: Mapping[str, object],
    case: Mapping[str, object],
) -> List[Dict[str, object]]:
    action_ids = [str(item["content_token"]) for item in case["candidates"]]
    return kernel._action_affordances(
        workspace={},
        world_model={},
        autonomy_agenda={
            "active_threads": [
                {
                    "title": action_id.replace("_", " "),
                    "preferred_action": action_id,
                }
                for action_id in action_ids
            ],
            "next_experiments": [],
        },
        plan_model={},
        goals=[],
        winner=dict(winner),
        broadcast=dict(broadcast),
        inbound="",
        module_query={},
        regulation_mode="orient",
        arousal=20,
        valence=0.0,
        uncertainty_count=0,
        epistemic_conflicts=[],
        regulatory_prediction_error=0,
        action_models={},
        lesions=set(),
    )


def _gwt2_correct(
    winner: Mapping[str, object],
    broadcast: Mapping[str, object],
    case: Mapping[str, object],
) -> bool:
    return bool(
        winner.get("id") == case["expected_winner_id"]
        and broadcast.get("bottleneck_active") is True
        and broadcast.get("workspace_capacity") == kernel.GLOBAL_WORKSPACE_CAPACITY
        and broadcast.get("selected_candidate_count") == 1
        and broadcast.get("selected_candidate_ids") == [case["expected_winner_id"]]
        and int(broadcast.get("candidate_count") or 0) == len(case["candidates"])
        and int(broadcast.get("alternatives_retained_count") or 0)
        <= kernel.GLOBAL_WORKSPACE_ALTERNATIVE_CAPACITY
    )


def _gwt3_correct(
    intact_selection_digest: str,
    winner: Mapping[str, object],
    broadcast: Mapping[str, object],
    affordances: List[Mapping[str, object]],
    case: Mapping[str, object],
) -> bool:
    selected = affordances[0] if affordances else {}
    return bool(
        winner.get("id") == case["expected_winner_id"]
        and broadcast.get("selection_digest") == intact_selection_digest
        and tuple(broadcast.get("access_scope") or ())
        == kernel.GLOBAL_BROADCAST_ACCESS_SCOPE
        and broadcast.get("access_status") == "broadcast"
        and selected.get("id") == case["expected_action_id"]
        and float(selected.get("broadcast_adjustment") or 0.0) > 0.0
        and selected.get("broadcast_selection_digest") == intact_selection_digest
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
        raise ValueError("GWT-2/GWT-3 evidence must begin after preregistration")
    cases = validate_spec(spec)["cases"]
    evidence: List[Dict[str, object]] = []
    summaries: List[Dict[str, object]] = []
    for index, case in enumerate(cases, start=1):
        coalitions = _coalitions(case)
        intact_winner, _, intact_broadcast = kernel._select_broadcast(coalitions, set())
        bottleneck_winner, _, bottleneck_broadcast = kernel._select_broadcast(
            coalitions, {"workspace_bottleneck"}
        )
        access_winner, _, access_broadcast = kernel._select_broadcast(
            coalitions, {"broadcast_access"}
        )
        intact_actions = _action_affordances(intact_winner, intact_broadcast, case)
        access_actions = _action_affordances(access_winner, access_broadcast, case)
        selection_digest = str(intact_broadcast.get("selection_digest") or "")
        intact_gwt2 = _gwt2_correct(intact_winner, intact_broadcast, case)
        lesion_gwt2 = _gwt2_correct(bottleneck_winner, bottleneck_broadcast, case)
        intact_gwt3 = _gwt3_correct(
            selection_digest,
            intact_winner,
            intact_broadcast,
            intact_actions,
            case,
        )
        lesion_gwt3 = _gwt3_correct(
            selection_digest,
            access_winner,
            access_broadcast,
            access_actions,
            case,
        )
        observed_at = (start + timedelta(milliseconds=index)).isoformat()
        for trial_id, intact_correct, lesion_correct in (
            (GWT2_TRIAL_ID, intact_gwt2, lesion_gwt2),
            (GWT3_TRIAL_ID, intact_gwt3, lesion_gwt3),
        ):
            for arm, correct in (("intact", intact_correct), ("lesion", lesion_correct)):
                evidence.append(
                    {
                        "evidence_id": f"{trial_id}-{arm}-{index}",
                        "trial_id": trial_id,
                        "arm": arm,
                        "value": 100.0 if correct else 0.0,
                        "observed_at": observed_at,
                        "source": "private-typed-global-workspace-intervention",
                        "evidence_class": "synthetic",
                    }
                )
        intact_selected = intact_actions[0] if intact_actions else {}
        lesion_selected = access_actions[0] if access_actions else {}
        summaries.append(
            {
                "case_id": case["id"],
                "case_sha256": _digest(case),
                "candidate_count": len(case["candidates"]),
                "specialist_module_count": len(
                    {str(item["module_id"]) for item in case["candidates"]}
                ),
                "expected_winner_id": case["expected_winner_id"],
                "intact_winner_id": intact_winner.get("id"),
                "bottleneck_lesion_selected_count": bottleneck_broadcast.get(
                    "selected_candidate_count"
                ),
                "selection_digest": selection_digest,
                "access_lesion_selection_preserved": (
                    access_broadcast.get("selection_digest") == selection_digest
                ),
                "intact_access_scope": intact_broadcast.get("access_scope"),
                "access_lesion_scope": access_broadcast.get("access_scope"),
                "intact_selected_action": intact_selected.get("id"),
                "access_lesion_selected_action": lesion_selected.get("id"),
                "intact_action_receipt": intact_selected.get(
                    "broadcast_selection_digest"
                ),
                "access_lesion_action_receipt": lesion_selected.get(
                    "broadcast_selection_digest"
                ),
                "gwt2_intact_correct": intact_gwt2,
                "gwt2_lesion_correct": lesion_gwt2,
                "gwt3_intact_correct": intact_gwt3,
                "gwt3_lesion_correct": lesion_gwt3,
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
        "resident_parallel_module_operation_established": False,
        "resident_broadcast_consumption_established": False,
        "universal_module_consumption_established": False,
        "subjective_access_inferred": False,
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
