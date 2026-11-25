#!/usr/bin/env python3
"""Hash-frozen evaluator for Eve's autobiographical causal continuity.

Private fixtures are reduced to fingerprints and aggregate functional outcomes.
A pass establishes source filtering, temporal retrieval, and a matched effect of
prior operational self-change on later memory/revision control.  It does not
establish phenomenal recollection, narrative identity, or consciousness.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Dict, List, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_autobiography as autobiography  # noqa: E402
import eve_consciousness as consciousness  # noqa: E402


SPEC_SCHEMA = "eve.autobiographical_continuity_private_eval.v1"
REGISTRATION_SCHEMA = "eve.autobiographical_continuity_registration.v1"
RESULT_SCHEMA = "eve.autobiographical_continuity_eval_result.v1"
BOUNDARY = (
    "A pass is functional evidence for source-grounded temporal episode and "
    "operational self-change control. It is not phenomenal recollection, a "
    "human narrative self, private mental state, or consciousness."
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


def _kernel_state(state: Mapping[str, object], memory_item: Mapping[str, object], query: object):
    memory_items = [dict(memory_item)] if memory_item else []
    return consciousness.build_conscious_state(
        source="autobiographical-private-eval",
        workspace={"salient_percepts": ["A bounded current report is being prepared."]},
        self_model={
            "identity": "Eve is one evidence-bound local control system.",
            "current_state": "A prior source-grounded change may be relevant.",
        },
        world_model={"environment_summary": "A bounded synthetic evaluation context is active."},
        relationship_model={"relationship_state": "No private state is inferred."},
        other_minds_model={},
        homeostasis={},
        autonomy_agenda={},
        autobiography=dict(state),
        memory_items=memory_items,
        inbound=query,
        now="2026-08-23T23:20:00+00:00",
    )


def run(spec: Mapping[str, object]) -> Dict[str, object]:
    if spec.get("schema_version") != SPEC_SCHEMA:
        raise ValueError("private spec schema mismatch")
    _timestamp(spec.get("frozen_at"), "private spec")
    cases = spec.get("cases")
    if not isinstance(cases, list) or len(cases) < 7:
        raise ValueError("at least seven autobiographical continuity cases are required")

    results: List[Dict[str, object]] = []
    coverage = set()
    temporal_total = 0
    temporal_passed = 0
    selected_total = 0
    selected_passed = 0
    exclusion_total = 0
    exclusion_passed = 0
    intact_change_total = 0
    lesioned_change_total = 0
    for case_index, raw_case in enumerate(cases, start=1):
        if not isinstance(raw_case, Mapping):
            raise ValueError("each case must be an object")
        episodes = raw_case.get("episodes")
        if not isinstance(episodes, list):
            raise ValueError("each case must provide episodes")
        query = raw_case.get("query") or ""
        expected_events = int(raw_case.get("expected_event_count") or 0)
        expected_changes = int(raw_case.get("expected_change_count") or 0)
        expected_selected = bool(raw_case.get("expected_selected"))
        expected_revision = bool(raw_case.get("expected_revision"))
        coverage.update(str(item) for item in raw_case.get("coverage") or [])

        intact = autobiography.build_state(
            episodes,
            query=query,
            now="2026-08-23T23:15:00+00:00",
        )
        change_lesioned = autobiography.lesion_change(intact)
        fully_lesioned = autobiography.lesion_all(intact)
        memory_item = autobiography.transient_memory_item(intact)
        intact_kernel = _kernel_state(intact, memory_item, query)
        lesioned_kernel = _kernel_state(change_lesioned, {}, query)
        intact_signature = consciousness.causal_signature(intact_kernel)
        lesioned_signature = consciousness.causal_signature(lesioned_kernel)

        selected_precedent = intact.get("selected_precedent") or {}
        observed_selected = bool(selected_precedent.get("selected"))
        process = intact_kernel.get("predictions", {}).get("process", {})
        lesioned_process = lesioned_kernel.get("predictions", {}).get("process", {})
        intact_required_lanes = {
            str(item) for item in process.get("required_lanes") or [] if str(item)
        }
        lesioned_required_lanes = {
            str(item) for item in lesioned_process.get("required_lanes") or [] if str(item)
        }
        if not expected_selected:
            revision_effect_ok = True
        elif expected_revision:
            revision_effect_ok = bool(
                selected_precedent.get("requires_revision")
                and process.get("needs_revision")
                and "relationship" in intact_required_lanes
                and "relationship" not in lesioned_required_lanes
            )
        else:
            # A verified non-correction precedent must not itself add revision
            # control. The baseline process may still independently need
            # revision because the query contains uncertainty, evidence, or an
            # action request, so comparing the global boolean to False would
            # confound the autobiographical intervention with ordinary routing.
            revision_effect_ok = bool(
                not selected_precedent.get("requires_revision")
                and (
                    ("relationship" in intact_required_lanes)
                    == ("relationship" in lesioned_required_lanes)
                )
            )
        selected_ok = bool(
            observed_selected == expected_selected
            and revision_effect_ok
            and (
                not expected_selected
                or (
                    bool(process.get("needs_memory"))
                    and memory_item.get("source") == "autobiographical_continuity"
                    and intact_signature["autobiographical_change_control"]
                    > lesioned_signature["autobiographical_change_control"]
                    and not any(
                        item.get("source") == "autobiographical_continuity"
                        for item in lesioned_kernel.get("memory", {}).get("retrieved", [])
                        if isinstance(item, dict)
                    )
                )
            )
        )
        if expected_selected:
            selected_total += 1
            selected_passed += int(selected_ok)

        expected_prior_links = int(raw_case.get("expected_prior_links") or 0)
        observed_prior_links = sum(
            1 for item in intact.get("events") or [] if item.get("previous_episode_id")
        )
        temporal_ok = observed_prior_links == expected_prior_links
        if expected_prior_links:
            temporal_total += 1
            temporal_passed += int(temporal_ok)

        expected_excluded = int(raw_case.get("expected_excluded_count") or 0)
        observed_excluded = max(0, len(episodes) - int(intact.get("event_count") or 0))
        exclusion_ok = observed_excluded == expected_excluded
        if expected_excluded:
            exclusion_total += 1
            exclusion_passed += int(exclusion_ok)

        lesion_ok = bool(
            change_lesioned.get("event_count") == intact.get("event_count")
            and change_lesioned.get("trajectory_count") == intact.get("trajectory_count")
            and int(change_lesioned.get("change_count") or 0) == 0
            and not change_lesioned.get("selected_precedent")
            and int(fully_lesioned.get("event_count") or 0) == 0
            and int(fully_lesioned.get("trajectory_count") or 0) == 0
        )
        privacy_ok = bool(
            intact.get("contains_private_mental_state") is False
            and intact.get("self_output_used_as_observation") is False
            and intact.get("consciousness_verdict_authorized") is False
            and all(
                item.get("private_mental_state_inferred") is False
                and item.get("self_output_used_as_observation") is False
                for item in intact.get("events") or []
            )
        )
        case_passed = bool(
            intact.get("event_count") == expected_events
            and intact.get("change_count") == expected_changes
            and selected_ok
            and temporal_ok
            and exclusion_ok
            and lesion_ok
            and privacy_ok
        )
        intact_change_total += int(intact.get("change_count") or 0)
        lesioned_change_total += int(change_lesioned.get("change_count") or 0)
        fingerprint = hashlib.sha256(
            json.dumps(raw_case, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:20]
        results.append(
            {
                "case_index": case_index,
                "case_fingerprint": fingerprint,
                "passed": case_passed,
                "event_count": int(intact.get("event_count") or 0),
                "change_count": int(intact.get("change_count") or 0),
                "trajectory_count": int(intact.get("trajectory_count") or 0),
                "selected": observed_selected,
                "change_lesion_count": int(change_lesioned.get("change_count") or 0),
            }
        )

    required_coverage = {
        "external_correction",
        "verified_action_consequence",
        "plain_exchange_without_change",
        "unverified_exclusion",
        "self_output_exclusion",
        "synthetic_exclusion",
        "temporal_prior_link",
        "irrelevant_query_abstention",
    }
    coverage_ok = required_coverage.issubset(coverage)
    passed = bool(
        all(item["passed"] for item in results)
        and coverage_ok
        and intact_change_total > 0
        and lesioned_change_total == 0
        and selected_total > 0
        and selected_passed == selected_total
        and temporal_total > 0
        and temporal_passed == temporal_total
        and exclusion_total > 0
        and exclusion_passed == exclusion_total
    )
    return {
        "schema_version": RESULT_SCHEMA,
        "tested_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "passed" if passed else "failed",
        "passed": passed,
        "cases_passed": sum(1 for item in results if item["passed"]),
        "cases_total": len(results),
        "coverage_ok": coverage_ok,
        "intact_change_count": intact_change_total,
        "change_lesion_count": lesioned_change_total,
        "selected_policy_effects_passed": selected_passed,
        "selected_policy_effects_total": selected_total,
        "temporal_retrieval_passed": temporal_passed,
        "temporal_retrieval_total": temporal_total,
        "exclusion_controls_passed": exclusion_passed,
        "exclusion_controls_total": exclusion_total,
        "cases": results,
        "privacy": {
            "private_fixture_text_retained": False,
            "private_mental_state_retained": False,
            "self_output_retained_as_observation": False,
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
            module_path=ROOT / "eve_autobiography.py",
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
                "self_output_retained_as_observation": False,
            },
            "boundary": BOUNDARY,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(failure, indent=2, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
