#!/usr/bin/env python3
"""Run a preregistered GWT-4 state-dependent query-succession intervention."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Dict, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_consciousness  # noqa: E402
import eve_consciousness_protocol as protocol  # noqa: E402


SCHEMA = "eve.gwt4_query_succession_intervention.v1"
TRIAL_ID = "gwt4-state-dependent-query-succession-v1"
MEASURE_ID = "verified_query_chain_completion_percent"
BOUNDARY = (
    "Matched synthetic evidence for the GWT-4 state-dependent query-selection "
    "edge; not resident autonomous module querying, subjective experience, or "
    "proof of consciousness."
)


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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def implementation_manifest() -> Dict[str, str]:
    return {
        "evaluator": _sha256(Path(__file__).resolve()),
        "kernel": _sha256(ROOT / "eve_consciousness.py"),
        "protocol": _sha256(ROOT / "eve_consciousness_protocol.py"),
    }


def implementation_digest() -> str:
    return hashlib.sha256(
        json.dumps(
            implementation_manifest(),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def registration_draft(*, registered_at: object, evaluator_id: str) -> Dict[str, object]:
    bundle = implementation_digest()
    return {
        "protocol_id": "gwt4-query-succession-" + bundle[:12],
        "registered_at": _timestamp(registered_at),
        "subject_system_id": "Eve",
        "evaluator_id": str(evaluator_id or "").strip()[:120],
        "objective": (
            "Test whether a verified first module result can change the next "
            "module query through globally broadcast state, compared with the "
            "same recurrent state and learned reliability after lesioning only "
            f"broadcast-to-action coupling; implementation_sha256:{bundle}"
        ),
        "trials": [
            {
                "id": TRIAL_ID,
                "theory": "global_workspace",
                "indicator_id": "GWT-4",
                "intervention": (
                    "Hold the previous verified query, typed next-module result, "
                    "action menu, recurrent state, learned reliability, and time "
                    "fixed; remove only broadcast-to-action coupling."
                ),
                "intact_arm": (
                    "globally broadcast typed result can revalue and select the "
                    "next module query"
                ),
                "lesion_arm": (
                    "same state and result with broadcast-to-action coupling removed"
                ),
                "measure_id": MEASURE_ID,
                "unit": "percent",
                "expected_direction": "lesion_lower",
                "minimum_effect": 50.0,
                "minimum_samples_per_arm": 6,
                "evidence_class": "synthetic",
                "falsifier": (
                    "Intact query chains fail to complete, the lesion completes "
                    "at the same rate, or the matched inputs/causal first-query "
                    "receipts do not hold."
                ),
            }
        ],
    }


def preregister(*, registered_at: object, evaluator_id: str) -> Dict[str, object]:
    return protocol.preregister(
        registration_draft(
            registered_at=registered_at,
            evaluator_id=evaluator_id,
        )
    )


def validate_registration(payload: Mapping[str, object]) -> Dict[str, object]:
    registered = protocol.validate_registration(payload)
    trials = registered.get("trials") if isinstance(registered.get("trials"), list) else []
    if len(trials) != 1:
        raise ValueError("GWT-4 query intervention requires exactly one frozen trial")
    expected = registration_draft(
        registered_at=registered["registered_at"],
        evaluator_id=str(registered["evaluator_id"]),
    )
    if (
        trials[0] != protocol._normalize_trial(expected["trials"][0])
        or registered["protocol_id"] != expected["protocol_id"]
    ):
        raise ValueError("GWT-4 query trial differs from the frozen evaluator contract")
    marker = f"implementation_sha256:{implementation_digest()}"
    if marker not in str(registered.get("objective") or ""):
        raise ValueError("GWT-4 evaluator implementation changed after preregistration")
    return registered


def evaluate(
    registration: Mapping[str, object],
    *,
    evidence_started_at: object,
    scored_by: str,
) -> Dict[str, object]:
    registered = validate_registration(registration)
    start = _parsed(evidence_started_at)
    if start <= _parsed(registered["registered_at"]):
        raise ValueError("GWT-4 evidence must begin after preregistration")
    suite = eve_consciousness.run_state_dependent_query_succession_suite()
    cases = suite.get("cases") if isinstance(suite.get("cases"), list) else []
    if len(cases) < 6:
        raise ValueError("GWT-4 intervention requires six matched cases")
    evidence = []
    summaries = []
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, Mapping):
            raise ValueError("GWT-4 suite returned a malformed case")
        observed_at = (start + timedelta(seconds=index)).isoformat()
        intact = 100.0 if case.get("intact_chain_completed") is True else 0.0
        lesion = 100.0 if case.get("lesion_chain_completed") is True else 0.0
        evidence.extend(
            [
                {
                    "evidence_id": f"gwt4-intact-{index}",
                    "trial_id": TRIAL_ID,
                    "arm": "intact",
                    "value": intact,
                    "observed_at": observed_at,
                    "source": "matched-state-dependent-query-intervention",
                    "evidence_class": "synthetic",
                },
                {
                    "evidence_id": f"gwt4-lesion-{index}",
                    "trial_id": TRIAL_ID,
                    "arm": "lesion",
                    "value": lesion,
                    "observed_at": observed_at,
                    "source": "matched-state-dependent-query-intervention",
                    "evidence_class": "synthetic",
                },
            ]
        )
        summaries.append(
            {
                "case_id": case.get("case_id"),
                "matched_input_sha256": case.get("matched_input_sha256"),
                "query_result_sha256": case.get("query_result_sha256"),
                "causal_result_valid": bool(case.get("causal_result_valid")),
                "intact_chain_completed": bool(case.get("intact_chain_completed")),
                "lesion_chain_completed": bool(case.get("lesion_chain_completed")),
                "intact_target_broadcast_alignment": int(
                    case.get("intact_target_broadcast_alignment") or 0
                ),
                "lesion_target_broadcast_alignment": int(
                    case.get("lesion_target_broadcast_alignment") or 0
                ),
            }
        )
    scored_at = start + timedelta(seconds=len(cases) + 1)
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
        "implementation_manifest": implementation_manifest(),
        "implementation_sha256": implementation_digest(),
        "case_count": len(cases),
        "cases": summaries,
        "evidence": evidence,
        "protocol_report": scored,
        "kernel_suite_passed": bool(suite.get("passed")),
        "evidence_class": "synthetic",
        "runtime_mutated": False,
        "resident_autonomous_querying_established": False,
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
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    register = sub.add_parser("register")
    register.add_argument("--output", type=Path, required=True)
    register.add_argument("--evaluator-id", required=True)
    run = sub.add_parser("run")
    run.add_argument("--registration", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--evidence-output", type=Path, required=True)
    run.add_argument("--scored-by", required=True)
    args = parser.parse_args()

    if args.command == "register":
        result = preregister(
            registered_at=datetime.now(timezone.utc).isoformat(),
            evaluator_id=args.evaluator_id,
        )
        _write(args.output, result)
    else:
        registration = _read(args.registration)
        result = evaluate(
            registration,
            evidence_started_at=datetime.now(timezone.utc).isoformat(),
            scored_by=args.scored_by,
        )
        _write(args.output, result)
        _write(args.evidence_output, result["evidence"])
    sys.stdout.write(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n")
    trial = (
        result.get("protocol_report", {}).get("results", [{}])[0]
        if isinstance(result.get("protocol_report"), Mapping)
        else {}
    )
    return 1 if trial.get("status") == "challenged" else 0


if __name__ == "__main__":
    raise SystemExit(main())
