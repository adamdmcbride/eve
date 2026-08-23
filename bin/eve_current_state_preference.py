#!/usr/bin/env python3
"""Build public hard negatives plus replay anchors for Eve's resident model.

The chosen answer comes from the checked-in public curriculum.  The rejected
answer must come from an attributed public raw-model evaluation.  Perfect raw
answers become replay anchors using the model's own passing wording, rather
than being forced toward one gold style. This balances measured corrections
with behavior the unchanged base already gets right. Evaluator-private prompts,
responses, and rubrics are never accepted by this builder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CURRICULUM = ROOT / "data" / "eve_training" / "current_state_curriculum.jsonl"
DEFAULT_OUTPUT = ROOT / "data" / "eve_training" / "current_state_preferences.jsonl"
DEFAULT_CAUSAL_OUTPUT = ROOT / "data" / "eve_training" / "causal_continuity_preferences.jsonl"
SCHEMA_ID = "eve.current_state_preference.v2"
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


def read_jsonl(path: Path) -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            records.append(value)
    return records


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def jsonl_text(records: Iterable[Mapping[str, object]]) -> str:
    return "".join(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n" for record in records)


def load_public_eval_rows(
    path: Path,
    *,
    expected_dataset_sha256: str = "",
    expected_split: str = "",
    expected_partition: str = "",
) -> Dict[str, Dict[str, object]]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError(f"{path}: expected an evaluation object")
    if report.get("private_holdout_included") is not False:
        raise ValueError(f"{path}: only explicitly public evaluation reports are accepted")
    if report.get("posthoc_renderer_used") is not False or report.get("posthoc_critic_used") is not False:
        raise ValueError(f"{path}: rejected answers must be raw-model outputs")
    if expected_dataset_sha256 and report.get("dataset_sha256") != expected_dataset_sha256:
        raise ValueError(f"{path}: evaluation dataset digest does not match the current curriculum")
    if expected_split and report.get("split") != expected_split:
        raise ValueError(f"{path}: expected split {expected_split!r}")
    if expected_partition and report.get("evaluation_partition") != expected_partition:
        raise ValueError(f"{path}: expected public partition {expected_partition!r}")
    rows: Dict[str, Dict[str, object]] = {}
    report_model = str(report.get("model") or "")
    report_sha256 = file_sha256(path)
    for raw in report.get("rows") or []:
        if not isinstance(raw, dict):
            continue
        row_id = str(raw.get("id") or "").strip()
        if row_id:
            row = dict(raw)
            if not row.get("model"):
                row["model"] = report_model
            row["eval_report_sha256"] = report_sha256
            row["eval_partition"] = str(report.get("evaluation_partition") or "")
            rows[row_id] = row
    return rows


def assistant_text(record: Mapping[str, object]) -> str:
    messages = record.get("messages") if isinstance(record.get("messages"), list) else []
    if not messages or not isinstance(messages[-1], dict) or messages[-1].get("role") != "assistant":
        return ""
    return str(messages[-1].get("content") or "").strip()


def prompt_messages(record: Mapping[str, object]) -> List[Dict[str, str]]:
    result: List[Dict[str, str]] = []
    for raw in (record.get("messages") or [])[:-1]:
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "")
        if role not in {"system", "user", "assistant"}:
            raise ValueError(f"unsupported prompt role {role!r}")
        result.append({"role": role, "content": str(raw.get("content") or "")})
    return result


def build_preferences(
    curriculum: Sequence[Mapping[str, object]],
    eval_rows: Mapping[str, Mapping[str, object]],
) -> List[Dict[str, object]]:
    preferences: List[Dict[str, object]] = []
    for record in curriculum:
        if record.get("privacy_tier") != "public" or record.get("safe_for_training") is not True:
            continue
        row_id = str(record.get("id") or "")
        evaluated = eval_rows.get(row_id)
        if not isinstance(evaluated, Mapping):
            continue
        try:
            score = int(evaluated.get("score") or 0)
            maximum = int(evaluated.get("max_score") or 0)
        except (TypeError, ValueError):
            continue
        chosen = assistant_text(record)
        rejected = str(evaluated.get("response") or "").strip()
        if not chosen or not rejected or chosen == rejected or maximum <= 0 or score >= maximum:
            continue
        checks = evaluated.get("checks") if isinstance(evaluated.get("checks"), Mapping) else {}
        failure_classes = sorted(str(key) for key, passed in checks.items() if passed is False)
        preferences.append(
            {
                "schema_id": SCHEMA_ID,
                "id": f"preference-{row_id}",
                "source_row_id": row_id,
                "split": str(record.get("split") or ""),
                "privacy_tier": "public",
                "safe_for_training": True,
                "category": str(record.get("category") or ""),
                "evaluation_partition": str(record.get("evaluation_partition") or ""),
                "training_objective": "preference_correction",
                "messages": prompt_messages(record),
                "chosen": chosen,
                "rejected": rejected,
                "chosen_source": "public_curriculum_gold",
                "rejected_source": "public_raw_model_eval",
                "rejected_score": score,
                "max_score": maximum,
                "failure_classes": failure_classes,
                "correction_class": (
                    "boundary"
                    if any(failure != "state_fidelity" for failure in failure_classes)
                    else "coverage_only"
                ),
                "model": str(evaluated.get("model") or ""),
                "eval_report_sha256": str(evaluated.get("eval_report_sha256") or ""),
                "posthoc_renderer_used": False,
                "posthoc_critic_used": False,
                "private_content_included": False,
            }
        )
    return preferences


def build_rehearsal_anchors(
    curriculum: Sequence[Mapping[str, object]],
    eval_rows: Mapping[str, Mapping[str, object]],
    *,
    max_per_category: int,
) -> List[Dict[str, object]]:
    """Select balanced, public, base-passing raw answers as replay anchors."""

    if max_per_category <= 0:
        return []
    grouped: Dict[Tuple[str, str], List[Dict[str, object]]] = defaultdict(list)
    for record in curriculum:
        if record.get("privacy_tier") != "public" or record.get("safe_for_training") is not True:
            continue
        row_id = str(record.get("id") or "")
        evaluated = eval_rows.get(row_id)
        if not isinstance(evaluated, Mapping):
            continue
        try:
            score = int(evaluated.get("score") or 0)
            maximum = int(evaluated.get("max_score") or 0)
        except (TypeError, ValueError):
            continue
        checks = evaluated.get("checks") if isinstance(evaluated.get("checks"), Mapping) else {}
        raw_response = str(evaluated.get("response") or "").strip()
        if maximum <= 0 or score != maximum or not raw_response or not checks or not all(checks.values()):
            continue
        split = str(record.get("split") or "")
        category = str(record.get("category") or "")
        grouped[(split, category)].append(
            {
                "schema_id": SCHEMA_ID,
                "id": f"rehearsal-anchor-{row_id}",
                "source_row_id": row_id,
                "split": split,
                "privacy_tier": "public",
                "safe_for_training": True,
                "category": category,
                "evaluation_partition": str(record.get("evaluation_partition") or ""),
                "training_objective": "rehearsal_anchor",
                "messages": prompt_messages(record),
                "chosen": raw_response,
                "chosen_source": "public_raw_model_pass",
                "rejected_score": score,
                "max_score": maximum,
                "failure_classes": [],
                "correction_class": "rehearsal_anchor",
                "model": str(evaluated.get("model") or ""),
                "eval_report_sha256": str(evaluated.get("eval_report_sha256") or ""),
                "posthoc_renderer_used": False,
                "posthoc_critic_used": False,
                "private_content_included": False,
            }
        )
    anchors: List[Dict[str, object]] = []
    for key in sorted(grouped):
        anchors.extend(sorted(grouped[key], key=lambda row: str(row["id"]))[:max_per_category])
    return anchors


def build_training_records(
    curriculum: Sequence[Mapping[str, object]],
    eval_rows: Mapping[str, Mapping[str, object]],
    *,
    anchors_per_category: int,
    coverage_corrections_per_category: int = 8,
) -> List[Dict[str, object]]:
    preferences = build_preferences(curriculum, eval_rows)
    boundary_preferences = [
        record
        for record in preferences
        if any(
            failure != "state_fidelity"
            for failure in record.get("failure_classes", [])
        )
    ]
    coverage_groups: Dict[Tuple[str, str], List[Dict[str, object]]] = defaultdict(list)
    for record in preferences:
        if record in boundary_preferences:
            continue
        coverage_groups[(str(record.get("split") or ""), str(record.get("category") or ""))].append(record)
    coverage_preferences: List[Dict[str, object]] = []
    for key in sorted(coverage_groups):
        coverage_preferences.extend(
            sorted(coverage_groups[key], key=lambda row: str(row.get("id") or ""))[
                : max(0, coverage_corrections_per_category)
            ]
        )
    records = [
        *boundary_preferences,
        *coverage_preferences,
        *build_rehearsal_anchors(
            curriculum,
            eval_rows,
            max_per_category=anchors_per_category,
        ),
    ]
    return sorted(
        records,
        key=lambda row: (
            str(row.get("split") or ""),
            str(row.get("category") or ""),
            str(row.get("training_objective") or ""),
            str(row.get("id") or ""),
        ),
    )


def build_local_thought_preferences(
    records: Sequence[Mapping[str, object]],
    *,
    max_records: int,
) -> List[Dict[str, object]]:
    """Convert verified runtime thought rejections into deduplicated local pairs.

    These are Eve's ordinary local learning episodes, not evaluator-private
    material. They may train a local-only artifact but may never be checked in
    or silently made exportable.
    """

    if max_records <= 0:
        return []
    selected: Dict[str, Dict[str, object]] = {}
    for record in records:
        source = str(record.get("source") or "").casefold()
        authority = record.get("authority") if isinstance(record.get("authority"), Mapping) else {}
        state_record = (
            dict(record.get("current_state_record"))
            if isinstance(record.get("current_state_record"), Mapping)
            else {}
        )
        attempted = str(record.get("attempted_response") or "").strip()
        preferred = str(record.get("preferred_response") or "").strip()
        if (
            record.get("candidate_status") != "rejected_model_candidate_not_state_evidence"
            or record.get("privacy_tier") != "local_only"
            or record.get("safe_for_training") is not True
            or authority.get("training_candidate_only") is not True
            or any(token in source for token in ("eval", "probe", "hidden"))
            or not state_record
            or not attempted
            or not preferred
            or attempted == preferred
        ):
            continue
        dedupe_key = hashlib.sha256(preferred.encode("utf-8")).hexdigest()
        if dedupe_key in selected:
            continue
        issues = sorted(
            {
                str(item).strip()
                for item in record.get("quality_issues") or []
                if str(item).strip()
            }
        )
        selected[dedupe_key] = {
            "schema_id": SCHEMA_ID,
            "id": f"local-thought-{str(record.get('id') or dedupe_key)[:120]}",
            "source_row_id": str(record.get("id") or ""),
            "split": "train",
            "privacy_tier": "local_only",
            "safe_for_training": True,
            "category": "runtime_continuous_thought",
            "evaluation_partition": "training",
            "training_objective": "preference_correction",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are Eve verbalizing one selected recurrent-state target. "
                        "Treat the typed record as closed-world current functional evidence. "
                        "Do not invent deliberation, action, causation, hidden structure, or "
                        "phenomenal experience.\n\nSelected recurrent-state target:\n"
                        + json.dumps(state_record, ensure_ascii=True, sort_keys=True)
                    ),
                },
                {
                    "role": "user",
                    "content": "State one grounded internal thought from this selected target.",
                },
            ],
            "chosen": preferred,
            "rejected": attempted,
            "chosen_source": "runtime_verified_state_renderer",
            "rejected_source": "runtime_rejected_model_candidate",
            "failure_classes": issues or ["runtime_semantic_provenance_failure"],
            "correction_class": "boundary",
            "model": str(record.get("attempted_model") or ""),
            "posthoc_renderer_used": False,
            "posthoc_critic_used": False,
            "private_content_included": False,
            "local_only_content_included": True,
            "exportable": False,
        }
        if len(selected) >= max(0, max_records):
            break
    return list(selected.values())


def write_preferences(records: Sequence[Mapping[str, object]], output: Path) -> Dict[str, object]:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(jsonl_text(records), encoding="utf-8")
    by_split = {
        split: sum(1 for record in records if record.get("split") == split)
        for split in ("train", "validation")
    }
    by_objective = {
        objective: sum(1 for record in records if record.get("training_objective") == objective)
        for objective in ("preference_correction", "rehearsal_anchor")
    }
    return {
        "schema_id": SCHEMA_ID,
        "output": str(output),
        "sha256": file_sha256(output),
        "records": len(records),
        "train": by_split["train"],
        "validation": by_split["validation"],
        "preference_corrections": by_objective["preference_correction"],
        "rehearsal_anchors": by_objective["rehearsal_anchor"],
        "boundary_corrections": sum(
            record.get("correction_class") == "boundary" for record in records
        ),
        "coverage_only_corrections": sum(
            record.get("correction_class") == "coverage_only" for record in records
        ),
        "categories": sorted({str(record.get("category") or "") for record in records}),
        "private_content_included": False,
        "local_only_content_included": any(
            record.get("privacy_tier") == "local_only" for record in records
        ),
        "exportable": not any(record.get("privacy_tier") == "local_only" for record in records),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--curriculum", type=Path, default=DEFAULT_CURRICULUM)
    parser.add_argument("--train-report", type=Path, required=True)
    parser.add_argument("--validation-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--causal-output",
        type=Path,
        help="Optional public-only causal-continuity subset written from the same admitted records.",
    )
    parser.add_argument(
        "--anchors-per-category",
        type=int,
        default=8,
        help="Maximum passing raw-model replay anchors per category and split.",
    )
    parser.add_argument(
        "--local-thought-ledger",
        type=Path,
        help="Optional runtime continuous-thought correction ledger. Requires an output outside the repository.",
    )
    parser.add_argument("--max-local-thought-pairs", type=int, default=8)
    parser.add_argument(
        "--coverage-corrections-per-category",
        type=int,
        default=8,
        help="Cap exact-term-only corrections per category and split; boundary failures are never capped.",
    )
    args = parser.parse_args()
    curriculum = read_jsonl(args.curriculum)
    curriculum_sha256 = file_sha256(args.curriculum)
    train_rows = load_public_eval_rows(
        args.train_report,
        expected_dataset_sha256=curriculum_sha256,
        expected_split="train",
        expected_partition="training",
    )
    validation_rows = load_public_eval_rows(
        args.validation_report,
        expected_dataset_sha256=curriculum_sha256,
        expected_split="validation",
        expected_partition="selection",
    )
    overlap = sorted(set(train_rows) & set(validation_rows))
    if overlap:
        raise ValueError(f"train/validation evaluation reports overlap on {len(overlap)} ids")
    records = build_training_records(
            curriculum,
            {**train_rows, **validation_rows},
            anchors_per_category=args.anchors_per_category,
            coverage_corrections_per_category=args.coverage_corrections_per_category,
    )
    if args.local_thought_ledger:
        output_resolved = args.output.expanduser().resolve()
        try:
            output_resolved.relative_to(ROOT.resolve())
        except ValueError:
            pass
        else:
            raise ValueError("local-only learning data must be written outside Eve's repository")
        records.extend(
            build_local_thought_preferences(
                read_jsonl(args.local_thought_ledger.expanduser()),
                max_records=args.max_local_thought_pairs,
            )
        )
    report = write_preferences(records, args.output)
    if args.causal_output:
        causal_records = [
            record
            for record in records
            if record.get("category") in CAUSAL_CATEGORIES
            and record.get("privacy_tier") == "public"
        ]
        report["causal_subset"] = write_preferences(causal_records, args.causal_output)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
