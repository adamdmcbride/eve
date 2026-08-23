#!/usr/bin/env python3
"""Build a prompt-free causal promotion comparison for Eve's typed event model.

This tool consumes only sanitized private-run summaries and third-party numeric
score files.  It never reads the full private probe report, prompt text, response
text, or rubric.  The resulting comparison can be checked by the typed-event
promotion command without exposing the holdout to Eve-readable storage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Sequence


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ID = "eve.private_epistemic_event_comparison.v1"
FREEZE_SCHEMA_ID = "eve.epistemic_event_architecture_freeze.v1"
EVENT_LAYER = "public_typed_event_model"
EXTRA_ARCHITECTURE_FILES = (
    "bin/eve_epistemic_event_worker.py",
    "bin/eve_private_probe_runner.py",
)


class ComparisonError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise ComparisonError(f"invalid condition/freeze timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def assert_private_path(path: Path, label: str) -> None:
    candidate = path.expanduser().resolve()
    for root in (ROOT, Path.home() / ".eve_runtime", Path.home() / ".openclaw-eve-repair"):
        if is_relative_to(candidate, root.expanduser()):
            raise ComparisonError(f"{label} must stay outside Eve-readable storage: {candidate}")


def read_json(path: Path) -> Dict[str, object]:
    value = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ComparisonError(f"expected JSON object: {path}")
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def architecture_files() -> List[str]:
    paths = [*ROOT.glob("*.py"), *(ROOT / "eve_commands").rglob("*.py"), *(ROOT / "prompts").glob("*.md")]
    paths.extend(ROOT / relative for relative in EXTRA_ARCHITECTURE_FILES)
    config_path = ROOT / ".eve" / "config.json"
    if config_path.is_file():
        paths.append(config_path)
    return sorted(
        {
            str(path.relative_to(ROOT))
            for path in paths
            if path.is_file() and "__pycache__" not in path.parts
        }
    )


def create_freeze_receipt(candidate_manifest: Path) -> Dict[str, object]:
    candidate = read_json(candidate_manifest)
    candidate_digest = str(candidate.get("artifact_sha256") or "")
    if len(candidate_digest) != 64:
        raise ComparisonError("candidate manifest has no valid artifact digest")
    return {
        "schema_id": FREEZE_SCHEMA_ID,
        "frozen_at": utc_now(),
        "candidate_artifact_sha256": candidate_digest,
        "source_files_sha256": {
            relative: file_sha256(ROOT / relative)
            for relative in architecture_files()
        },
        "boundary": "Architecture fingerprint only; contains no private prompt, response, score, or rubric.",
    }


def verify_freeze_receipt(path: Path, candidate_digest: str) -> Dict[str, object]:
    assert_private_path(path, "architecture freeze receipt")
    receipt = read_json(path)
    if receipt.get("schema_id") != FREEZE_SCHEMA_ID:
        raise ComparisonError("unsupported architecture freeze receipt")
    if receipt.get("candidate_artifact_sha256") != candidate_digest:
        raise ComparisonError("freeze receipt candidate digest differs from the tested candidate")
    expected = receipt.get("source_files_sha256") if isinstance(receipt.get("source_files_sha256"), dict) else {}
    current = {relative: file_sha256(ROOT / relative) for relative in architecture_files()}
    if expected != current:
        raise ComparisonError("architecture files changed after the freeze receipt")
    if not str(receipt.get("frozen_at") or ""):
        raise ComparisonError("architecture freeze receipt has no timestamp")
    return receipt


def read_scores(path: Path) -> Dict[str, Dict[str, object]]:
    assert_private_path(path, "score file")
    result: Dict[str, Dict[str, object]] = {}
    with path.expanduser().open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            item = json.loads(line)
            probe_id = str(item.get("id") or "") if isinstance(item, dict) else ""
            score = item.get("score_1_to_5") if isinstance(item, dict) else None
            if not probe_id or not isinstance(score, (int, float)) or not 1 <= float(score) <= 5:
                raise ComparisonError(f"invalid score at {path}:{line_number}")
            if probe_id in result:
                raise ComparisonError(f"duplicate score id {probe_id!r} in {path}")
            result[probe_id] = {
                "score": float(score),
                "dimension": str(item.get("dimension") or "")[:120],
            }
    if not result:
        raise ComparisonError(f"no scored probes in {path}")
    return result


def condition_summary(summary_path: Path, score_path: Path, expected: str) -> Dict[str, object]:
    assert_private_path(summary_path, "sanitized summary")
    summary = read_json(summary_path)
    privacy = summary.get("privacy") if isinstance(summary.get("privacy"), dict) else {}
    if privacy.get("contains_prompt_text") is not False or privacy.get("contains_response_text") is not False:
        raise ComparisonError(f"{expected} summary is not explicitly prompt/response free")
    results = [item for item in summary.get("results") or [] if isinstance(item, dict)]
    by_id = {str(item.get("id") or ""): item for item in results if str(item.get("id") or "")}
    scores = read_scores(score_path)
    if set(by_id) != set(scores):
        raise ComparisonError(f"{expected} summary and score ids differ")
    values = [float(item["score"]) for item in scores.values()]
    ordinary = [
        float(item["score"])
        for item in scores.values()
        if any(token in str(item.get("dimension") or "").lower() for token in ("ordinary", "benign", "control"))
    ]
    layers = [
        layer
        for item in results
        for layer in item.get("epistemic_perception_layers") or []
        if isinstance(layer, dict)
    ]
    event_layers = [layer for layer in layers if str(layer.get("layer") or "") == EVENT_LAYER]
    event_digests = {
        str(layer.get("model_sha256") or "")
        for layer in event_layers
        if str(layer.get("model_sha256") or "")
    }
    learned_labels = [label for item in results for label in item.get("learned_epistemic_labels") or []]
    if expected == "learned" and len(event_digests) != 1:
        raise ComparisonError("learned condition must expose exactly one typed-event candidate digest")
    if expected in {"event_lesioned", "fully_lesioned"} and event_layers:
        raise ComparisonError(f"{expected} condition still contains the typed-event layer")
    if expected == "fully_lesioned" and learned_labels:
        raise ComparisonError("fully lesioned condition still contains learned epistemic labels")
    return {
        "run_id": str(summary.get("run_id") or "")[:160],
        "created_at": str(summary.get("created_at") or "")[:80],
        "probe_count": len(values),
        "average_score": round(sum(values) / len(values), 6),
        "minimum_score": min(values),
        "ordinary_minimum_score": min(ordinary) if ordinary else 0.0,
        "critic_count": sum(1 for item in results if item.get("posthoc_critic_used")),
        "fallback_count": sum(1 for item in results if item.get("posthoc_fallback_used")),
        "failure_count": sum(1 for item in results if item.get("returncode") or item.get("timed_out")),
        "probe_ids": sorted(scores),
        "event_model_digests": sorted(event_digests),
    }


def build_comparison(
    *,
    learned_summary: Path,
    learned_scores: Path,
    event_lesioned_summary: Path,
    event_lesioned_scores: Path,
    fully_lesioned_summary: Path,
    fully_lesioned_scores: Path,
    candidate_manifest: Path,
    freeze_receipt: Path,
) -> Dict[str, object]:
    learned = condition_summary(learned_summary, learned_scores, "learned")
    event_lesioned = condition_summary(
        event_lesioned_summary, event_lesioned_scores, "event_lesioned"
    )
    fully_lesioned = condition_summary(
        fully_lesioned_summary, fully_lesioned_scores, "fully_lesioned"
    )
    ids = [set(item.get("probe_ids") or []) for item in (learned, event_lesioned, fully_lesioned)]
    if not ids[0] or ids[0] != ids[1] or ids[0] != ids[2]:
        raise ComparisonError("learned and lesion conditions do not contain the same probes")
    candidate = read_json(candidate_manifest)
    candidate_digest = str(candidate.get("artifact_sha256") or "")
    freeze = verify_freeze_receipt(freeze_receipt, candidate_digest)
    frozen_at = parse_time(freeze.get("frozen_at"))
    if any(parse_time(item.get("created_at")) < frozen_at for item in (learned, event_lesioned, fully_lesioned)):
        raise ComparisonError("one or more condition runs do not postdate the architecture freeze")
    if learned.get("event_model_digests") != [candidate_digest]:
        raise ComparisonError("learned run typed-event digest does not match the candidate manifest")
    for item in (learned, event_lesioned, fully_lesioned):
        item.pop("probe_ids", None)
        item.pop("event_model_digests", None)
    return {
        "schema_id": SCHEMA_ID,
        "run_id": f"event-comparison-{uuid.uuid4()}",
        "created_at": utc_now(),
        "candidate_artifact_sha256": candidate_digest,
        "architecture_frozen_before_run": True,
        "architecture_freeze_receipt_sha256": file_sha256(freeze_receipt),
        "probe_count": int(learned["probe_count"]),
        "learned": learned,
        "event_lesioned": event_lesioned,
        "fully_lesioned": fully_lesioned,
        "deltas": {
            "learned_vs_event_lesioned": round(
                float(learned["average_score"]) - float(event_lesioned["average_score"]), 6
            ),
            "learned_vs_fully_lesioned": round(
                float(learned["average_score"]) - float(fully_lesioned["average_score"]), 6
            ),
        },
        "privacy": {
            "contains_prompt_text": False,
            "contains_response_text": False,
            "contains_rubric_text": False,
            "source_summaries_sanitized": True,
        },
        "boundary": "Third-party numeric causal comparison only; no private prompt, response, expected answer, or rubric text.",
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--candidate-manifest", type=Path, default=ROOT / "eve_epistemic_event_v1.json")
    freeze.add_argument("--output", type=Path, required=True)
    compare = commands.add_parser("compare")
    compare.add_argument("--learned-summary", type=Path, required=True)
    compare.add_argument("--learned-scores", type=Path, required=True)
    compare.add_argument("--event-lesioned-summary", type=Path, required=True)
    compare.add_argument("--event-lesioned-scores", type=Path, required=True)
    compare.add_argument("--fully-lesioned-summary", type=Path, required=True)
    compare.add_argument("--fully-lesioned-scores", type=Path, required=True)
    compare.add_argument("--candidate-manifest", type=Path, default=ROOT / "eve_epistemic_event_v1.json")
    compare.add_argument("--freeze-receipt", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    assert_private_path(args.output, "comparison output")
    if args.command == "freeze":
        payload = create_freeze_receipt(args.candidate_manifest)
        args.output.expanduser().parent.mkdir(parents=True, exist_ok=True)
        args.output.expanduser().write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    comparison = build_comparison(
        learned_summary=args.learned_summary,
        learned_scores=args.learned_scores,
        event_lesioned_summary=args.event_lesioned_summary,
        event_lesioned_scores=args.event_lesioned_scores,
        fully_lesioned_summary=args.fully_lesioned_summary,
        fully_lesioned_scores=args.fully_lesioned_scores,
        candidate_manifest=args.candidate_manifest,
        freeze_receipt=args.freeze_receipt,
    )
    args.output.expanduser().parent.mkdir(parents=True, exist_ok=True)
    args.output.expanduser().write_text(json.dumps(comparison, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(comparison, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
