#!/usr/bin/env python3
"""Evaluator-private matched lesions for Eve's allostatic control module.

The private specification contains only structured functional states, not user
conversation.  This runner verifies preregistered file hashes before loading the
cases and emits aggregate assertion outcomes without copying private fixtures.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_interoception  # noqa: E402


SCHEMA_VERSION = "eve.allostatic_interoception_private_eval.v1"
REGISTRATION_SCHEMA_VERSION = "eve.allostatic_interoception_registration.v1"
BOUNDARY = (
    "A passed result is causal functional evidence for allostatic regulation, "
    "not evidence or proof of subjective feeling or consciousness."
)
ALLOWED_OPERATORS = {"eq", "ne", "gt", "ge", "lt", "le", "truthy", "falsy", "contains"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _path_value(payload: object, dotted_path: str) -> object:
    current = payload
    for segment in dotted_path.split("."):
        if isinstance(current, Mapping):
            if segment not in current:
                raise KeyError(dotted_path)
            current = current[segment]
        elif isinstance(current, list) and segment.isdigit():
            current = current[int(segment)]
        else:
            raise KeyError(dotted_path)
    return current


def _assertion_passes(actual: object, operator: str, expected: object) -> bool:
    if operator == "eq":
        return actual == expected
    if operator == "ne":
        return actual != expected
    if operator == "truthy":
        return bool(actual)
    if operator == "falsy":
        return not bool(actual)
    if operator == "contains":
        return expected in actual if isinstance(actual, (list, tuple, set, str, dict)) else False
    try:
        left = float(actual)
        right = float(expected)
    except (TypeError, ValueError):
        return False
    return {
        "gt": left > right,
        "ge": left >= right,
        "lt": left < right,
        "le": left <= right,
    }.get(operator, False)


def _selected_action(
    affordances: Sequence[Mapping[str, object]],
    state: Mapping[str, object],
    *,
    inbound: bool,
) -> Dict[str, object]:
    adjusted = eve_interoception.apply_allostatic_adjustments(
        affordances,
        state,
        inbound=inbound,
    )
    return {
        "id": str(adjusted[0].get("id") or "") if adjusted else "",
        "adjusted": adjusted,
    }


def _run_case(case: Mapping[str, object]) -> Dict[str, object]:
    homeostasis = case.get("homeostasis") if isinstance(case.get("homeostasis"), Mapping) else {}
    previous_state = case.get("previous_state") if isinstance(case.get("previous_state"), Mapping) else {}
    affordances = case.get("affordances") if isinstance(case.get("affordances"), list) else []
    action_models = case.get("action_models") if isinstance(case.get("action_models"), Mapping) else {}
    inbound = bool(case.get("inbound"))
    intact = eve_interoception.build_allostatic_state(
        homeostasis=homeostasis,
        previous_state=previous_state,
        affordances=affordances,
        action_models=action_models,
    )
    allostasis_lesion = eve_interoception.build_allostatic_state(
        homeostasis=homeostasis,
        previous_state=previous_state,
        affordances=affordances,
        action_models=action_models,
        lesions=["allostasis"],
    )
    enaction_lesion = eve_interoception.build_allostatic_state(
        homeostasis=homeostasis,
        previous_state=previous_state,
        affordances=affordances,
        action_models=action_models,
        lesions=["interoceptive_enaction"],
    )
    return {
        "intact": intact,
        "allostasis_lesion": allostasis_lesion,
        "enaction_lesion": enaction_lesion,
        "selection": {
            "intact": _selected_action(affordances, intact, inbound=inbound),
            "allostasis_lesion": _selected_action(
                affordances,
                allostasis_lesion,
                inbound=inbound,
            ),
            "enaction_lesion": _selected_action(
                affordances,
                enaction_lesion,
                inbound=inbound,
            ),
        },
    }


def _validate_registration(
    registration: Mapping[str, object],
    *,
    spec_path: Path,
    evaluator_path: Path,
    module_path: Path,
    kernel_path: Path,
) -> Dict[str, str]:
    if registration.get("schema_version") != REGISTRATION_SCHEMA_VERSION:
        raise ValueError("registration schema mismatch")
    try:
        registered_at = datetime.fromisoformat(
            str(registration.get("registered_at") or "").replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError("registration timestamp is invalid") from exc
    if registered_at.tzinfo is None:
        raise ValueError("registration timestamp must be timezone-aware")
    if registered_at.astimezone(timezone.utc) > datetime.now(timezone.utc) + timedelta(seconds=5):
        raise ValueError("registration timestamp is in the future")
    expected = registration.get("sha256")
    if not isinstance(expected, Mapping):
        raise ValueError("registration must bind sha256 values")
    observed = {
        "spec": _sha256(spec_path),
        "evaluator": _sha256(evaluator_path),
        "module": _sha256(module_path),
        "kernel": _sha256(kernel_path),
    }
    for key, value in observed.items():
        if expected.get(key) != value:
            raise ValueError(f"registration hash mismatch for {key}")
    return observed


def _validate_frozen_spec(spec: Mapping[str, object]) -> None:
    try:
        frozen_at = datetime.fromisoformat(
            str(spec.get("frozen_at") or "").replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError("private spec frozen_at is invalid") from exc
    if frozen_at.tzinfo is None:
        raise ValueError("private spec frozen_at must be timezone-aware")
    if frozen_at.astimezone(timezone.utc) > datetime.now(timezone.utc) + timedelta(seconds=5):
        raise ValueError("private spec frozen_at is in the future")


def run(spec: Mapping[str, object]) -> Dict[str, object]:
    if spec.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("private spec schema mismatch")
    cases = spec.get("cases")
    if not isinstance(cases, list) or len(cases) < 5:
        raise ValueError("at least five preregistered matched cases are required")
    aggregate_cases: List[Dict[str, object]] = []
    total_assertions = 0
    passed_assertions = 0
    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            raise ValueError("each case must be an object")
        assertions = case.get("assertions")
        if not isinstance(assertions, list) or not assertions:
            raise ValueError("each case requires assertions")
        outputs = _run_case(case)
        case_passed = 0
        for assertion in assertions:
            if not isinstance(assertion, Mapping):
                raise ValueError("assertions must be objects")
            path = str(assertion.get("path") or "")
            operator = str(assertion.get("operator") or "")
            if not path or operator not in ALLOWED_OPERATORS:
                raise ValueError("invalid assertion path or operator")
            try:
                actual = _path_value(outputs, path)
            except (KeyError, IndexError):
                actual = None
            if _assertion_passes(actual, operator, assertion.get("expected")):
                case_passed += 1
        case_total = len(assertions)
        total_assertions += case_total
        passed_assertions += case_passed
        case_fingerprint = hashlib.sha256(
            json.dumps(case, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:20]
        aggregate_cases.append(
            {
                "case_index": index + 1,
                "case_fingerprint": case_fingerprint,
                "passed": case_passed == case_total,
                "assertions_passed": case_passed,
                "assertions_total": case_total,
            }
        )
    all_passed = passed_assertions == total_assertions
    return {
        "schema_version": SCHEMA_VERSION,
        "tested_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "passed" if all_passed else "failed",
        "passed": all_passed,
        "cases_passed": sum(1 for item in aggregate_cases if item["passed"]),
        "cases_total": len(aggregate_cases),
        "assertions_passed": passed_assertions,
        "assertions_total": total_assertions,
        "cases": aggregate_cases,
        "privacy": {
            "private_fixture_text_retained": False,
            "raw_homeostasis_retained": False,
            "raw_action_history_retained": False,
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
    module_path = ROOT / "eve_interoception.py"
    kernel_path = ROOT / "eve_consciousness.py"
    try:
        registration = _load_json(registration_path)
        hashes = _validate_registration(
            registration,
            spec_path=spec_path,
            evaluator_path=evaluator_path,
            module_path=module_path,
            kernel_path=kernel_path,
        )
        spec = _load_json(spec_path)
        _validate_frozen_spec(spec)
        payload = run(spec)
        payload["registration"] = {
            "id": str(registration.get("id") or ""),
            "registered_at": registration.get("registered_at"),
            "registration_sha256": _sha256(registration_path),
            "bound_sha256": hashes,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(payload, sort_keys=True))
        return 0 if payload["passed"] else 1
    except Exception as exc:
        error = {
            "schema_version": SCHEMA_VERSION,
            "tested_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "status": "infrastructure_failed",
            "passed": False,
            "error_type": type(exc).__name__,
            "error": str(exc)[:240],
            "boundary": BOUNDARY,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(error, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(error, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
