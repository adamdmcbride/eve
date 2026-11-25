#!/usr/bin/env python3
"""Run a preregistered matched AE-2 active-sensing linkage intervention."""

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

import eve_active_sensing  # noqa: E402
import eve_active_sensing_adapters as adapters  # noqa: E402
import eve_consciousness_protocol as protocol  # noqa: E402


SCHEMA = "eve.ae2_active_sensing_intervention.v1"
TRIAL_ID = "ae2-exact-action-observation-linkage-v1"
MEASURE_ID = "causally_qualified_belief_update_percent"
BOUNDARY = (
    "Matched synthetic causal-closure intervention for functional AE-2 evidence; "
    "not lived agency, subjective experience, or proof of consciousness."
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


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def evaluator_digest() -> str:
    return hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()


def registration_draft(*, registered_at: object, evaluator_id: str) -> Dict[str, object]:
    implementation = evaluator_digest()
    return {
        "protocol_id": "ae2-active-sensing-linkage-" + implementation[:12],
        "registered_at": _timestamp(registered_at),
        "subject_system_id": "Eve",
        "evaluator_id": str(evaluator_id or "").strip()[:120],
        "objective": (
            "Test whether exact verified action-to-later-observation linkage is "
            "causally necessary for a typed uncertainty update; "
            f"evaluator_sha256:{implementation}"
        ),
        "trials": [
            {
                "id": TRIAL_ID,
                "theory": "agency_embodiment",
                "indicator_id": "AE-2",
                "intervention": (
                    "Hold the verified action and typed post-action snapshot fixed, "
                    "but replace the exact execution-id link in the lesion arm."
                ),
                "intact_arm": "exact execution id links verified action to later observation",
                "lesion_arm": "later observation carries a mismatched execution id",
                "measure_id": MEASURE_ID,
                "unit": "percent",
                "expected_direction": "lesion_lower",
                "minimum_effect": 50.0,
                "minimum_samples_per_arm": 3,
                "evidence_class": "synthetic",
                "falsifier": (
                    "The lesion updates belief at the same rate as intact linkage, "
                    "or intact linkage fails to update on informative typed outcomes."
                ),
            }
        ],
    }


def preregister(*, registered_at: object, evaluator_id: str) -> Dict[str, object]:
    return protocol.preregister(
        registration_draft(registered_at=registered_at, evaluator_id=evaluator_id)
    )


def validate_ae2_registration(payload: Mapping[str, object]) -> Dict[str, object]:
    registered = protocol.validate_registration(payload)
    trials = registered.get("trials") if isinstance(registered.get("trials"), list) else []
    if len(trials) != 1:
        raise ValueError("AE-2 intervention requires exactly one frozen trial")
    trial = trials[0]
    expected = registration_draft(
        registered_at=registered["registered_at"],
        evaluator_id=str(registered["evaluator_id"]),
    )
    expected_trial = protocol._normalize_trial(expected["trials"][0])
    if trial != expected_trial or registered["protocol_id"] != expected["protocol_id"]:
        raise ValueError("AE-2 trial differs from the frozen evaluator contract")
    implementation_marker = f"evaluator_sha256:{evaluator_digest()}"
    if implementation_marker not in str(registered.get("objective") or ""):
        raise ValueError("AE-2 evaluator implementation changed after preregistration")
    return registered


def default_scenarios(base_time: datetime) -> List[Dict[str, object]]:
    def snapshot(at: datetime) -> Dict[str, object]:
        return {
            "timestamp": at.isoformat(),
            "eve_services": {
                "daemon": {"state": "active", "loaded": True},
                "model_watchdog": {"state": "active", "loaded": True},
            },
            "model_status": {
                "preferred_fast_model": "eve-fast",
                "preferred_deep_model": "eve-deep",
                "residency": {"both_preferred_loaded": True},
                "probes": {"eve-fast": {"ok": True}, "eve-deep": {"ok": True}},
            },
        }

    first = snapshot(base_time + timedelta(seconds=2))
    second = snapshot(base_time + timedelta(seconds=12))
    second["model_status"]["probes"]["eve-deep"]["ok"] = False
    third = snapshot(base_time + timedelta(seconds=22))
    third["eve_services"]["daemon"] = {"state": "inactive", "loaded": False}
    return [first, second, third]


def _assert_snapshot_boundary(snapshot: Mapping[str, object]) -> None:
    allowed_top = {"timestamp", "eve_services", "model_status"}
    if set(snapshot) - allowed_top:
        raise ValueError("AE-2 scenarios may contain only typed service-health features")
    services = (
        snapshot.get("eve_services")
        if isinstance(snapshot.get("eve_services"), Mapping)
        else {}
    )
    if set(services) - {"daemon", "model_watchdog"}:
        raise ValueError("AE-2 scenarios contain an unregistered service feature")
    model_status = (
        snapshot.get("model_status")
        if isinstance(snapshot.get("model_status"), Mapping)
        else {}
    )
    if set(model_status) - {
        "preferred_fast_model",
        "preferred_deep_model",
        "residency",
        "probes",
    }:
        raise ValueError("AE-2 scenarios contain an unregistered model feature")


def evaluate_scenarios(
    registration: Mapping[str, object],
    scenarios: Sequence[Mapping[str, object]],
    *,
    evidence_started_at: object,
    scored_by: str,
) -> Dict[str, object]:
    registered = validate_ae2_registration(registration)
    start = _parsed(evidence_started_at)
    if start <= _parsed(registered["registered_at"]):
        raise ValueError("AE-2 evidence must begin after preregistration")
    if len(scenarios) < 3:
        raise ValueError("AE-2 intervention requires at least three matched scenarios")
    evidence: List[Dict[str, object]] = []
    summaries: List[Dict[str, object]] = []
    for index, raw_snapshot in enumerate(scenarios, start=1):
        _assert_snapshot_boundary(raw_snapshot)
        opened_at = start + timedelta(seconds=(index - 1) * 10)
        verified_at = opened_at + timedelta(seconds=1)
        snapshot = dict(raw_snapshot)
        snapshot["timestamp"] = (verified_at + timedelta(seconds=1)).isoformat()
        execution_id = f"ae2-synthetic-execution-{index}"
        opened = adapters.open_service_health_episode(now=opened_at.isoformat())
        attached = adapters.attach_service_health_execution(
            opened,
            {
                "action": adapters.SERVICE_HEALTH_ACTION,
                "execution_id": execution_id,
                "status": "completed",
                "executed": True,
                "execution_tree_status": "SUCCESS",
                "execution_verification_ok": True,
                "execution_summary": "Synthetic matched action receipt.",
            },
            now=verified_at.isoformat(),
        )
        intact = adapters.close_service_health_episode(attached, snapshot)
        lesion_observation = adapters.service_health_observation(attached, snapshot)
        lesion_observation["caused_by_execution_id"] = f"mismatched-{index}"
        lesion = eve_active_sensing.close_with_observation(
            attached, lesion_observation
        )
        observed_at = str(snapshot["timestamp"])
        intact_value = 100.0 if intact.get("consequence_qualified") else 0.0
        lesion_value = 100.0 if lesion.get("consequence_qualified") else 0.0
        evidence.extend(
            [
                {
                    "evidence_id": f"ae2-intact-{index}",
                    "trial_id": TRIAL_ID,
                    "arm": "intact",
                    "value": intact_value,
                    "observed_at": observed_at,
                    "source": "matched-active-sensing-intervention",
                    "evidence_class": "synthetic",
                },
                {
                    "evidence_id": f"ae2-lesion-{index}",
                    "trial_id": TRIAL_ID,
                    "arm": "lesion",
                    "value": lesion_value,
                    "observed_at": observed_at,
                    "source": "matched-active-sensing-intervention",
                    "evidence_class": "synthetic",
                },
            ]
        )
        intact_observation = (
            intact.get("observation")
            if isinstance(intact.get("observation"), Mapping)
            else {}
        )
        summaries.append(
            {
                "scenario": index,
                "snapshot_sha256": _digest(snapshot),
                "outcome": intact_observation.get("outcome"),
                "intact_status": intact.get("status"),
                "lesion_status": lesion.get("status"),
                "intact_information_gain": intact.get("information_gain"),
                "lesion_information_gain": lesion.get("information_gain"),
                "intact_consequence_qualified": bool(
                    intact.get("consequence_qualified")
                ),
                "lesion_consequence_qualified": bool(
                    lesion.get("consequence_qualified")
                ),
                "matched_snapshot": True,
            }
        )
    scored_at = max(_parsed(item["observed_at"]) for item in evidence) + timedelta(
        seconds=1
    )
    report = protocol.score_protocol(
        registration,
        evidence,
        scored_by=scored_by,
        scored_at=scored_at.isoformat(),
    )
    return {
        "schema_version": SCHEMA,
        "evaluated_at": scored_at.isoformat(),
        "registration_digest": registration["registration_digest"],
        "evaluator_sha256": evaluator_digest(),
        "scenario_count": len(summaries),
        "scenarios": summaries,
        "evidence": evidence,
        "protocol_report": report,
        "evidence_class": "synthetic",
        "runtime_mutated": False,
        "action_authority": False,
        "lived_agency_established": False,
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
        start = datetime.now(timezone.utc)
        result = evaluate_scenarios(
            registration,
            default_scenarios(start),
            evidence_started_at=start.isoformat(),
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
