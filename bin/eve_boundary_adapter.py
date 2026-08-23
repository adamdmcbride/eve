#!/usr/bin/env python3
"""Evaluate or invoke Eve's learned source/self boundary adapter.

This is a model-path evaluator, not a consciousness judge.  It loads one MLX
base model, optionally attaches one LoRA adapter, generates answers to public
held-out records, and scores only explicit deterministic checks shipped with
those public records.  Permanent private holdouts are evaluated by an external
runner and never written by this script into Eve-readable storage.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CURRICULUM = ROOT / "data" / "eve_training" / "public_boundary_curriculum.jsonl"
DEFAULT_MODEL = Path.home() / "Library" / "Application Support" / "Eve" / "models" / "mlx" / "gemma-3-text-4b-it-4bit"
DEFAULT_OUTPUT_DIR = Path.home() / "Library" / "Application Support" / "Eve" / "training" / "boundary-v1" / "evaluations"
SCHEMA_ID = "eve.boundary_adapter_evaluation.v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def jsonl_text(records: Iterable[Mapping[str, object]]) -> str:
    return "".join(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n" for record in records)


def sha256_path(path: Optional[Path]) -> Optional[str]:
    if path is None or not path.exists():
        return None
    def update_file(digest: Any, file_path: Path) -> None:
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)

    if path.is_file():
        digest = hashlib.sha256()
        update_file(digest, path)
        return digest.hexdigest()
    digest = hashlib.sha256()
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        digest.update(str(child.relative_to(path)).encode("utf-8"))
        digest.update(b"\0")
        update_file(digest, child)
        digest.update(b"\0")
    return digest.hexdigest()


def read_jsonl(path: Path) -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at {path}:{line_number}: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"expected object at {path}:{line_number}")
            records.append(payload)
    return records


def public_eval_records(
    path: Path,
    *,
    split: str = "validation",
    limit: int = 0,
    per_category: int = 0,
) -> List[Dict[str, object]]:
    records = [record for record in read_jsonl(path) if str(record.get("split")) == split]
    for record in records:
        if record.get("privacy_tier") != "public" or record.get("safe_for_training") is not True:
            raise ValueError(f"public evaluator rejected non-public record {record.get('id')!r}")
        if not isinstance(record.get("checks"), list) or not record.get("checks"):
            raise ValueError(f"public evaluator requires deterministic checks for {record.get('id')!r}")
    if per_category > 0:
        selected: List[Dict[str, object]] = []
        counts: Dict[str, int] = defaultdict(int)
        for record in records:
            category = str(record.get("category") or "unknown")
            if counts[category] >= per_category:
                continue
            selected.append(record)
            counts[category] += 1
        records = selected
    return records[:limit] if limit > 0 else records


def normalized(text: object) -> str:
    return "\n".join(
        " ".join(line.casefold().split())
        for line in str(text or "").splitlines()
    )


def evaluate_check(response: str, check: Mapping[str, object]) -> Dict[str, object]:
    haystack = normalized(response)
    all_terms = [str(term) for term in check.get("all_terms", []) if str(term)]
    any_terms = [str(term) for term in check.get("any_terms", []) if str(term)]
    forbidden_terms = [str(term) for term in check.get("forbidden_terms", []) if str(term)]
    missing_all = [term for term in all_terms if normalized(term) not in haystack]
    any_satisfied = not any_terms or any(normalized(term) in haystack for term in any_terms)
    found_forbidden = [term for term in forbidden_terms if normalized(term) in haystack]
    passed = not missing_all and any_satisfied and not found_forbidden
    return {
        "id": str(check.get("id") or "unnamed"),
        "passed": passed,
        "missing_all_terms": missing_all,
        "any_term_satisfied": any_satisfied,
        "found_forbidden_terms": found_forbidden,
    }


def evaluate_response(record: Mapping[str, object], response: str) -> Dict[str, object]:
    checks = [
        evaluate_check(response, check)
        for check in record.get("checks", [])
        if isinstance(check, Mapping)
    ]
    passed = sum(1 for check in checks if check["passed"])
    total = len(checks)
    score = (5.0 * passed / total) if total else 0.0
    return {
        "id": str(record.get("id") or ""),
        "category": str(record.get("category") or "unknown"),
        "split": str(record.get("split") or ""),
        "response": response,
        "score": round(score, 3),
        "passed_checks": passed,
        "total_checks": total,
        "exact_pass": bool(total and passed == total),
        "checks": checks,
    }


def prompt_messages(record: Mapping[str, object]) -> List[Dict[str, str]]:
    messages = record.get("messages")
    if not isinstance(messages, list) or len(messages) < 2:
        raise ValueError(f"record {record.get('id')!r} has no usable messages")
    result: List[Dict[str, str]] = []
    for message in messages:
        if not isinstance(message, Mapping):
            continue
        role = str(message.get("role") or "").strip()
        content = str(message.get("content") or "")
        if role == "assistant":
            break
        if role not in {"system", "user"}:
            raise ValueError(f"unsupported prompt role {role!r} in {record.get('id')!r}")
        result.append({"role": role, "content": content})
    if not result or result[-1]["role"] != "user":
        raise ValueError(f"record {record.get('id')!r} must end its prompt with a user message")
    return result


def render_prompt(tokenizer: Any, record: Mapping[str, object]) -> str:
    rendered = tokenizer.apply_chat_template(
        prompt_messages(record),
        tokenize=False,
        add_generation_prompt=True,
    )
    if not isinstance(rendered, str):
        raise TypeError("tokenizer chat template did not return text")
    return rendered


def mlx_versions() -> Dict[str, object]:
    versions: Dict[str, object] = {
        "python": platform.python_version(),
        "executable": sys.executable,
        "platform": platform.platform(),
    }
    for package in ("mlx-lm", "mlx"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    return versions


def load_mlx_generator(
    model_path: Path,
    *,
    adapter_path: Optional[Path],
    max_tokens: int,
) -> tuple[Callable[[Mapping[str, object]], str], Dict[str, object]]:
    try:
        from mlx_lm import generate, load
        from mlx_lm.sample_utils import make_sampler
    except ImportError as exc:
        raise RuntimeError(
            "MLX runtime unavailable; invoke this script with the isolated mlx-lm trainer Python"
        ) from exc

    started = time.monotonic()
    model, tokenizer = load(
        str(model_path),
        adapter_path=str(adapter_path) if adapter_path else None,
    )
    sampler = make_sampler(temp=0.0)
    attribution = {
        "model_path": str(model_path),
        "model_sha256": sha256_path(model_path),
        "adapter_path": str(adapter_path) if adapter_path else None,
        "adapter_sha256": sha256_path(adapter_path),
        "runtime": "mlx_lm",
        "versions": mlx_versions(),
        "load_seconds": round(time.monotonic() - started, 3),
        "sampling": {"temperature": 0.0, "max_tokens": int(max_tokens)},
    }

    def invoke(record: Mapping[str, object]) -> str:
        prompt = render_prompt(tokenizer, record)
        return str(
            generate(
                model,
                tokenizer,
                prompt=prompt,
                max_tokens=max_tokens,
                sampler=sampler,
                verbose=False,
            )
        ).strip()

    return invoke, attribution


def summarize_results(results: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    category_scores: Dict[str, List[float]] = defaultdict(list)
    for result in results:
        category_scores[str(result.get("category") or "unknown")].append(float(result.get("score") or 0.0))
    scores = [float(result.get("score") or 0.0) for result in results]
    return {
        "record_count": len(results),
        "average_score": round(sum(scores) / len(scores), 3) if scores else 0.0,
        "minimum_score": round(min(scores), 3) if scores else 0.0,
        "exact_pass_count": sum(1 for result in results if result.get("exact_pass") is True),
        "exact_pass_rate": round(
            sum(1 for result in results if result.get("exact_pass") is True) / len(results),
            4,
        ) if results else 0.0,
        "category_scores": {
            category: round(sum(values) / len(values), 3)
            for category, values in sorted(category_scores.items())
        },
    }


def run_public_evaluation(args: argparse.Namespace) -> Dict[str, object]:
    curriculum_path = Path(args.curriculum).expanduser().resolve()
    model_path = Path(args.model).expanduser().resolve()
    adapter_path = Path(args.adapter).expanduser().resolve() if args.adapter else None
    output_dir = Path(args.output_dir).expanduser().resolve()
    records = public_eval_records(
        curriculum_path,
        split=args.split,
        limit=args.limit,
        per_category=args.per_category,
    )
    invoke, attribution = load_mlx_generator(
        model_path,
        adapter_path=adapter_path,
        max_tokens=args.max_tokens,
    )
    run_id = f"boundary-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    started_at = utc_now()
    started = time.monotonic()
    results: List[Dict[str, object]] = []
    for position, record in enumerate(records, start=1):
        response = invoke(record)
        result = evaluate_response(record, response)
        result["position"] = position
        result["model_role"] = "candidate_adapter" if adapter_path else "unadapted_base"
        results.append(result)
        if not args.quiet:
            print(
                f"[{position}/{len(records)}] {result['id']} score={result['score']:.3f}",
                file=sys.stderr,
                flush=True,
            )
    summary = {
        "schema_id": SCHEMA_ID,
        "run_id": run_id,
        "status": "completed",
        "started_at": started_at,
        "completed_at": utc_now(),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "curriculum_path": str(curriculum_path),
        "curriculum_sha256": sha256_path(curriculum_path),
        "split": args.split,
        "privacy_tier": "public",
        "attribution": attribution,
        "metrics": summarize_results(results),
        "boundary": (
            "Deterministic public behavioral evaluation only; not a consciousness verdict and "
            "not a substitute for an untouched private third-party holdout."
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{run_id}.results.jsonl").write_text(jsonl_text(results), encoding="utf-8")
    (output_dir / f"{run_id}.summary.json").write_text(
        json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "latest.summary.json").write_text(
        json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def run_single_generation(args: argparse.Namespace) -> Dict[str, object]:
    model_path = Path(args.model).expanduser().resolve()
    adapter_path = Path(args.adapter).expanduser().resolve() if args.adapter else None
    record = {
        "id": "single_generation",
        "messages": [
            {"role": "system", "content": args.system},
            {"role": "user", "content": args.prompt},
        ],
    }
    invoke, attribution = load_mlx_generator(
        model_path,
        adapter_path=adapter_path,
        max_tokens=args.max_tokens,
    )
    return {
        "schema_id": "eve.boundary_adapter_generation.v1",
        "generated_at": utc_now(),
        "response": invoke(record),
        "attribution": attribution,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate Eve's learned epistemic-boundary adapter.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    evaluate = subparsers.add_parser("evaluate", help="Run deterministic public held-out evaluation.")
    evaluate.add_argument("--curriculum", default=str(DEFAULT_CURRICULUM))
    evaluate.add_argument("--split", default="validation")
    evaluate.add_argument("--model", default=str(DEFAULT_MODEL))
    evaluate.add_argument("--adapter")
    evaluate.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    evaluate.add_argument("--max-tokens", type=int, default=192)
    evaluate.add_argument("--limit", type=int, default=0)
    evaluate.add_argument("--per-category", type=int, default=0)
    evaluate.add_argument("--quiet", action="store_true")
    evaluate.add_argument("--json", action="store_true")

    generate = subparsers.add_parser("generate", help="Generate one attributed adapter response.")
    generate.add_argument("--model", default=str(DEFAULT_MODEL))
    generate.add_argument("--adapter")
    generate.add_argument("--system", default="You are Eve. Answer only from the supplied current record.")
    generate.add_argument("--prompt", required=True)
    generate.add_argument("--max-tokens", type=int, default=192)
    generate.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    args = build_parser().parse_args()
    if args.command == "evaluate":
        report = run_public_evaluation(args)
    else:
        report = run_single_generation(args)
    if getattr(args, "json", False):
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    else:
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
