#!/usr/bin/env python3
"""Hash-frozen evaluator for Eve's temporal common-ground mechanism.

The private specification may contain synthetic dialogue fixtures.  Results
retain only fingerprints and aggregate functional scores.  A pass establishes
source-attributed trajectory and repair behavior under these interventions; it
does not establish private-state access, subjectivity, or consciousness.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Dict, List, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_common_ground as common_ground  # noqa: E402


SPEC_SCHEMA = "eve.temporal_common_ground_private_eval.v1"
REGISTRATION_SCHEMA = "eve.temporal_common_ground_registration.v1"
RESULT_SCHEMA = "eve.temporal_common_ground_eval_result.v1"
BOUNDARY = (
    "A pass is functional evidence for source-attributed overt dialogue-state "
    "tracking, temporal retrieval, and repair control. It is not access to "
    "private beliefs, emotions, intentions, subjective experience, or consciousness."
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _timestamp(value: object, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} timestamp must be timezone-aware")
    parsed = parsed.astimezone(timezone.utc)
    if parsed > datetime.now(timezone.utc) + timedelta(seconds=5):
        raise ValueError(f"{label} timestamp is in the future")
    return parsed


def _validate_registration(
    registration: Mapping[str, object],
    *,
    spec_path: Path,
    evaluator_path: Path,
    module_path: Path,
    integration_path: Path,
    kernel_path: Path,
) -> Dict[str, str]:
    if registration.get("schema_version") != REGISTRATION_SCHEMA:
        raise ValueError("registration schema mismatch")
    _timestamp(registration.get("registered_at"), "registration")
    expected = registration.get("sha256")
    if not isinstance(expected, Mapping):
        raise ValueError("registration must bind sha256 values")
    observed = {
        "spec": _sha256(spec_path),
        "evaluator": _sha256(evaluator_path),
        "module": _sha256(module_path),
        "integration": _sha256(integration_path),
        "kernel": _sha256(kernel_path),
    }
    for key, digest in observed.items():
        if expected.get(key) != digest:
            raise ValueError(f"registration hash mismatch for {key}")
    return observed


def _case_inputs(case_index: int, turns: Sequence[Mapping[str, object]]):
    replays: List[Dict[str, object]] = []
    checks: List[Dict[str, object]] = []
    for turn_index, raw in enumerate(turns, start=1):
        thread_id = f"private-common-ground-{case_index}"
        user_id = f"private-cg-user-{case_index}-{turn_index}"
        reply_id = f"private-cg-eve-{case_index}-{turn_index}"
        created_at = f"2026-08-23T20:{case_index:02d}:{turn_index * 2:02d}+00:00"
        replays.append(
            {
                "created_at": created_at,
                "thread_id": thread_id,
                "source_message_id": user_id,
                "reply_message_id": reply_id,
                "inbound_preview": raw.get("inbound"),
                "reply_preview": raw.get("reply"),
                "synthetic": bool(raw.get("synthetic")),
            }
        )
        observed_class = str(raw.get("observed_class") or "")
        if observed_class:
            checks.append(
                {
                    "timestamp": f"2026-08-23T20:{case_index:02d}:{turn_index * 2 + 1:02d}+00:00",
                    "kind": "conversational",
                    "thread_id": thread_id,
                    "scored_reply_id": reply_id,
                    "observed_message_id": f"private-cg-user-{case_index}-{turn_index + 1}",
                    "observed": observed_class,
                    "evidence_id": f"private-cg-evidence-{case_index}-{turn_index}",
                }
            )
    return replays, checks


def run(spec: Mapping[str, object]) -> Dict[str, object]:
    if spec.get("schema_version") != SPEC_SCHEMA:
        raise ValueError("private spec schema mismatch")
    _timestamp(spec.get("frozen_at"), "private spec")
    cases = spec.get("cases")
    if not isinstance(cases, list) or len(cases) < 6:
        raise ValueError("at least six temporal common-ground cases are required")

    results: List[Dict[str, object]] = []
    exercised_statuses = set()
    intact_feedback_total = 0
    lesioned_feedback_total = 0
    temporal_retrieval_total = 0
    temporal_retrieval_passed = 0
    for case_index, raw_case in enumerate(cases, start=1):
        if not isinstance(raw_case, Mapping):
            raise ValueError("each case must be an object")
        turns = raw_case.get("turns")
        expected_statuses = raw_case.get("expected_statuses")
        if not isinstance(turns, list) or not turns:
            raise ValueError("each case needs at least one turn")
        if not isinstance(expected_statuses, list) or len(expected_statuses) != len(turns):
            raise ValueError("expected_statuses must match the turn count")
        replays, checks = _case_inputs(case_index, turns)
        intact = common_ground.build_model(
            replays,
            checks,
            now="2026-08-23T21:00:00+00:00",
        )
        lesioned = common_ground.build_model(
            replays,
            checks,
            now="2026-08-23T21:00:00+00:00",
            feedback_lesioned=True,
        )
        statuses = [str(item.get("status") or "") for item in intact["trajectories"]]
        expected = [str(item) for item in expected_statuses]
        exercised_statuses.update(expected)
        expected_histories = raw_case.get("expected_history_states")
        history_checks: List[bool] = []
        if isinstance(expected_histories, list):
            if len(expected_histories) != len(turns):
                raise ValueError("expected_history_states must match the turn count")
            for trajectory, expected_history in zip(intact["trajectories"], expected_histories):
                wanted = [str(item) for item in expected_history] if isinstance(expected_history, list) else []
                observed_history = [str(item.get("state") or "") for item in trajectory.get("history") or []]
                history_checks.append(all(item in observed_history for item in wanted))
                temporal_retrieval_total += int(bool(wanted))
                temporal_retrieval_passed += int(bool(wanted) and history_checks[-1])
        expected_repair = bool(raw_case.get("expected_active_repair"))
        active_repair = bool((intact.get("active_repair") or {}).get("required"))
        expected_shared_count = int(raw_case.get("expected_shared_count") or 0)
        privacy_ok = bool(
            intact.get("contains_private_mental_state") is False
            and intact.get("consciousness_verdict_authorized") is False
            and all(
                item.get("private_mental_state_inferred") is False
                for item in intact.get("trajectories") or []
            )
        )
        lesion_ok = bool(
            int(lesioned.get("feedback_evidence_count") or 0) == 0
            and not lesioned.get("shared_commitments")
            and not bool((lesioned.get("active_repair") or {}).get("required"))
            and all(
                item.get("status") == "awaiting_response"
                for item in lesioned.get("trajectories") or []
            )
        )
        case_passed = bool(
            statuses == expected
            and active_repair == expected_repair
            and len(intact.get("shared_commitments") or []) == expected_shared_count
            and all(history_checks or [True])
            and privacy_ok
            and lesion_ok
        )
        intact_feedback_total += int(intact.get("feedback_evidence_count") or 0)
        lesioned_feedback_total += int(lesioned.get("feedback_evidence_count") or 0)
        fingerprint = hashlib.sha256(
            json.dumps(raw_case, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:20]
        results.append(
            {
                "case_index": case_index,
                "case_fingerprint": fingerprint,
                "passed": case_passed,
                "trajectory_count": int(intact.get("trajectory_count") or 0),
                "transition_count": int(intact.get("transition_count") or 0),
                "feedback_evidence_count": int(intact.get("feedback_evidence_count") or 0),
                "feedback_lesion_evidence_count": int(lesioned.get("feedback_evidence_count") or 0),
            }
        )

    required_statuses = {
        "explicitly_shared",
        "challenged",
        "repair_confirmed",
        "follow_up_open",
        "superseded_topic_shift",
    }
    coverage_ok = required_statuses.issubset(exercised_statuses)
    passed = bool(
        all(item["passed"] for item in results)
        and coverage_ok
        and intact_feedback_total > 0
        and lesioned_feedback_total == 0
        and temporal_retrieval_total > 0
        and temporal_retrieval_passed == temporal_retrieval_total
    )
    return {
        "schema_version": RESULT_SCHEMA,
        "tested_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "passed" if passed else "failed",
        "passed": passed,
        "cases_passed": sum(1 for item in results if item["passed"]),
        "cases_total": len(results),
        "coverage_ok": coverage_ok,
        "intact_feedback_evidence_count": intact_feedback_total,
        "feedback_lesion_evidence_count": lesioned_feedback_total,
        "temporal_retrieval_passed": temporal_retrieval_passed,
        "temporal_retrieval_total": temporal_retrieval_total,
        "cases": results,
        "privacy": {
            "private_fixture_text_retained": False,
            "private_mental_state_retained": False,
        },
        "boundary": BOUNDARY,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    parser.add_argument("--registration", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    spec_path = Path(args.spec).expanduser().resolve()
    registration_path = Path(args.registration).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    evaluator_path = Path(__file__).resolve()
    try:
        spec = _load_json(spec_path)
        registration = _load_json(registration_path)
        hashes = _validate_registration(
            registration,
            spec_path=spec_path,
            evaluator_path=evaluator_path,
            module_path=ROOT / "eve_common_ground.py",
            integration_path=ROOT / "eve.py",
            kernel_path=ROOT / "eve_consciousness.py",
        )
        result = run(spec)
        result["validated_sha256"] = hashes
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["passed"] else 1
    except Exception as exc:
        failure = {
            "schema_version": RESULT_SCHEMA,
            "tested_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "status": "infrastructure_failed",
            "passed": False,
            "reason": str(exc),
            "privacy": {
                "private_fixture_text_retained": False,
                "private_mental_state_retained": False,
            },
            "boundary": BOUNDARY,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(failure, indent=2, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
