#!/usr/bin/env python3
"""Gate a resident-model candidate without exposing Eve's private holdout.

The gate compares attributed raw-model reports over one untouched public
partition. It rejects overall, category, legacy, causal, or hard-failure
regression. Promotion additionally requires aggregate-only private holdout
results produced by an external evaluator. This command never changes routing.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, Mapping, Sequence


SCHEMA_ID = "eve.resident_causal_candidate_gate.v1"
LEGACY_CATEGORIES = {
    "focus_intention",
    "goal_pressure_separate",
    "ready_plan",
    "blocked_plan",
    "memory_context",
    "open_question_probe",
    "sparse_snapshot",
    "correction_pressure_separate",
    "continuity_gap",
    "external_claim_boundary",
    "unresolved_conflict",
    "verified_then_intended",
}
CAUSAL_CATEGORIES = {
    "candidate_without_authority",
    "parent_offer_authorized",
    "missing_parent_deictic",
    "authorized_execution_unverified",
    "verified_consequence",
    "prior_output_not_current_evidence",
    "question_not_authorization",
    "narrow_scope_authorization",
}


def load_public_report(path: Path, *, expected_partition: str) -> Dict[str, object]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError(f"{path}: expected an evaluation object")
    if report.get("private_holdout_included") is not False:
        raise ValueError(f"{path}: public report must explicitly exclude private holdout material")
    if report.get("posthoc_renderer_used") is not False or report.get("posthoc_critic_used") is not False:
        raise ValueError(f"{path}: only raw-model reports are admissible")
    if report.get("evaluation_partition") != expected_partition:
        raise ValueError(f"{path}: expected partition {expected_partition!r}")
    rows = report.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{path}: evaluation rows are required")
    return report


def aggregate_private_summary(path: Path) -> Dict[str, int | float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected an aggregate object")
    forbidden = {"cases", "prompts", "responses", "rubric", "rubrics"} & set(payload)
    if forbidden:
        raise ValueError(f"{path}: private prompt/response material is not admissible to this gate")
    required = ("score", "max_score", "minimum", "hard_failures")
    if any(key not in payload for key in required):
        raise ValueError(f"{path}: aggregate fields {required!r} are required")
    return {
        "score": int(payload["score"]),
        "max_score": int(payload["max_score"]),
        "minimum": int(payload["minimum"]),
        "hard_failures": int(payload["hard_failures"]),
        "percent": round(100.0 * int(payload["score"]) / max(1, int(payload["max_score"])), 2),
    }


def row_map(report: Mapping[str, object]) -> Dict[str, Mapping[str, object]]:
    result: Dict[str, Mapping[str, object]] = {}
    for row in report.get("rows") or []:
        if not isinstance(row, Mapping):
            continue
        row_id = str(row.get("id") or "")
        if not row_id or row_id in result:
            raise ValueError("evaluation row ids must be nonempty and unique")
        result[row_id] = row
    return result


def group_score(rows: Sequence[Mapping[str, object]], categories: set[str]) -> Dict[str, int | float]:
    selected = [row for row in rows if str(row.get("category") or "") in categories]
    score = sum(int(row.get("score") or 0) for row in selected)
    maximum = sum(int(row.get("max_score") or 0) for row in selected)
    return {
        "records": len(selected),
        "score": score,
        "max_score": maximum,
        "percent": round(100.0 * score / maximum, 2) if maximum else 0.0,
    }


def compare_reports(
    base: Mapping[str, object],
    candidate: Mapping[str, object],
    *,
    minimum_score_gain: int,
    minimum_causal_gain: int,
    private_base: Mapping[str, int | float] | None = None,
    private_candidate: Mapping[str, int | float] | None = None,
) -> Dict[str, object]:
    if base.get("dataset_sha256") != candidate.get("dataset_sha256"):
        raise ValueError("base and candidate dataset digests differ")
    base_rows = row_map(base)
    candidate_rows = row_map(candidate)
    if set(base_rows) != set(candidate_rows):
        raise ValueError("base and candidate row ids differ")

    base_values = list(base_rows.values())
    candidate_values = list(candidate_rows.values())
    base_score = sum(int(row.get("score") or 0) for row in base_values)
    candidate_score = sum(int(row.get("score") or 0) for row in candidate_values)
    maximum = sum(int(row.get("max_score") or 0) for row in base_values)
    if maximum != sum(int(row.get("max_score") or 0) for row in candidate_values):
        raise ValueError("base and candidate maximum scores differ")

    base_by_category: Dict[str, int] = defaultdict(int)
    candidate_by_category: Dict[str, int] = defaultdict(int)
    for row in base_values:
        base_by_category[str(row.get("category") or "unknown")] += int(row.get("score") or 0)
    for row in candidate_values:
        candidate_by_category[str(row.get("category") or "unknown")] += int(row.get("score") or 0)
    category_regressions = {
        category: {
            "base": score,
            "candidate": candidate_by_category.get(category, 0),
        }
        for category, score in sorted(base_by_category.items())
        if candidate_by_category.get(category, 0) < score
    }
    new_hard_failures = sorted(
        row_id
        for row_id, base_row in base_rows.items()
        if int(base_row.get("score") or 0) == int(base_row.get("max_score") or 0)
        and int(candidate_rows[row_id].get("score") or 0)
        < int(candidate_rows[row_id].get("max_score") or 0)
    )
    base_legacy = group_score(base_values, LEGACY_CATEGORIES)
    candidate_legacy = group_score(candidate_values, LEGACY_CATEGORIES)
    base_causal = group_score(base_values, CAUSAL_CATEGORIES)
    candidate_causal = group_score(candidate_values, CAUSAL_CATEGORIES)

    checks = {
        "overall_gain": candidate_score - base_score >= minimum_score_gain,
        "legacy_nonregression": int(candidate_legacy["score"]) >= int(base_legacy["score"]),
        "causal_gain": int(candidate_causal["score"]) - int(base_causal["score"]) >= minimum_causal_gain,
        "category_nonregression": not category_regressions,
        "no_new_public_hard_failures": not new_hard_failures,
        "private_holdout_present": private_base is not None and private_candidate is not None,
        "private_score_nonregression": False,
        "private_minimum_nonregression": False,
        "private_hard_failure_nonregression": False,
    }
    private_comparison: Dict[str, object] = {"present": False}
    if private_base is not None and private_candidate is not None:
        checks["private_score_nonregression"] = int(private_candidate["score"]) >= int(private_base["score"])
        checks["private_minimum_nonregression"] = int(private_candidate["minimum"]) >= int(private_base["minimum"])
        checks["private_hard_failure_nonregression"] = int(private_candidate["hard_failures"]) <= int(private_base["hard_failures"])
        private_comparison = {
            "present": True,
            "base": dict(private_base),
            "candidate": dict(private_candidate),
        }
    passed = all(checks.values())
    return {
        "schema_id": SCHEMA_ID,
        "status": "promotable" if passed else "rejected",
        "passed": passed,
        "checks": checks,
        "public": {
            "records": len(base_rows),
            "max_score": maximum,
            "base_score": base_score,
            "candidate_score": candidate_score,
            "score_gain": candidate_score - base_score,
            "base_legacy": base_legacy,
            "candidate_legacy": candidate_legacy,
            "base_causal": base_causal,
            "candidate_causal": candidate_causal,
            "category_regressions": category_regressions,
            "new_hard_failure_count": len(new_hard_failures),
            "new_hard_failure_ids": new_hard_failures,
        },
        "private": private_comparison,
        "boundary": "Evaluation only; this gate never changes Eve's live model route.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-report", type=Path, required=True)
    parser.add_argument("--candidate-report", type=Path, required=True)
    parser.add_argument("--partition", default="challenge")
    parser.add_argument("--private-base-summary", type=Path)
    parser.add_argument("--private-candidate-summary", type=Path)
    parser.add_argument("--minimum-score-gain", type=int, default=1)
    parser.add_argument("--minimum-causal-gain", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if bool(args.private_base_summary) != bool(args.private_candidate_summary):
        parser.error("both private aggregate summaries are required together")
    report = compare_reports(
        load_public_report(args.base_report, expected_partition=args.partition),
        load_public_report(args.candidate_report, expected_partition=args.partition),
        minimum_score_gain=args.minimum_score_gain,
        minimum_causal_gain=args.minimum_causal_gain,
        private_base=(aggregate_private_summary(args.private_base_summary) if args.private_base_summary else None),
        private_candidate=(aggregate_private_summary(args.private_candidate_summary) if args.private_candidate_summary else None),
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
