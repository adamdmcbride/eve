#!/usr/bin/env python3
"""Dry-run-first LoRA trainer for Eve's curated, scored episodes.

The Transformers backend is retained for portable experiments.  The MLX backend
is the production Mac training path: it runs in an isolated Python environment,
converts eligible rows to MLX chat JSONL, writes a fully attributed config and
manifest, and never changes Eve's live model routing.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence


TRANSFORMERS_RUN_MODULES = ["datasets", "transformers", "peft", "trl"]
DEFAULT_MLX_TRAINER_PYTHON = (
    Path.home()
    / "Library"
    / "Application Support"
    / "Eve"
    / "labs"
    / "trainer-venvs"
    / "mlx-lm-py314"
    / "bin"
    / "python"
)
THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "TOKENIZERS_PARALLELISM": "false",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: Path) -> List[Dict[str, object]]:
    if not path.exists():
        return []
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


def records_for_split(records: Sequence[Dict[str, object]], split: str) -> List[Dict[str, object]]:
    explicit = [record for record in records if str(record.get("split") or "")]
    if not explicit:
        return list(records)
    return [record for record in records if str(record.get("split")) == split]


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def format_example(record: Mapping[str, object]) -> str:
    prompt = str(record.get("prompt") or "").strip()
    context = record.get("available_context") if isinstance(record.get("available_context"), dict) else {}
    evidence = record.get("tool_action_evidence") if isinstance(record.get("tool_action_evidence"), dict) else {}
    preferred = str(record.get("preferred_response") or "").strip()
    return (
        "### Eve Training Episode\n"
        f"Prompt: {prompt}\n"
        f"Available context: {json.dumps(context, ensure_ascii=True, sort_keys=True)}\n"
        f"Tool/action evidence: {json.dumps(evidence, ensure_ascii=True, sort_keys=True)}\n"
        "### Preferred response\n"
        f"{preferred}"
    )


def mlx_chat_record(record: Mapping[str, object]) -> Dict[str, object]:
    source_messages = record.get("messages")
    if isinstance(source_messages, list):
        messages: List[Dict[str, str]] = []
        for message in source_messages:
            if not isinstance(message, Mapping):
                continue
            role = str(message.get("role") or "").strip()
            content = str(message.get("content") or "")
            if role not in {"system", "user", "assistant"}:
                raise ValueError(f"unsupported MLX chat role {role!r}")
            messages.append({"role": role, "content": content})
        if messages and messages[-1]["role"] == "assistant":
            return {"messages": messages}
        chosen = str(record.get("chosen") or record.get("preferred_response") or "").strip()
        if messages and messages[-1]["role"] == "user" and chosen:
            return {"messages": [*messages, {"role": "assistant", "content": chosen}]}

    preferred = str(record.get("preferred_response") or "").strip()
    prompt = str(record.get("prompt") or "").strip()
    if not prompt or not preferred:
        raise ValueError("training row requires chat messages or prompt plus preferred_response")
    context = record.get("available_context") if isinstance(record.get("available_context"), dict) else {}
    evidence = record.get("tool_action_evidence") if isinstance(record.get("tool_action_evidence"), dict) else {}
    user = (
        f"Prompt: {prompt}\n"
        f"Available context: {json.dumps(context, ensure_ascii=True, sort_keys=True)}\n"
        f"Tool/action evidence: {json.dumps(evidence, ensure_ascii=True, sort_keys=True)}"
    )
    return {
        "messages": [
            {
                "role": "system",
                "content": "You are Eve. Answer from the supplied evidence without inventing state or action.",
            },
            {"role": "user", "content": user},
            {"role": "assistant", "content": preferred},
        ]
    }


def jsonl_text(records: Iterable[Mapping[str, object]]) -> str:
    return "".join(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n" for record in records)


def write_mlx_data(
    train_records: Sequence[Dict[str, object]],
    validation_records: Sequence[Dict[str, object]],
    data_dir: Path,
) -> Dict[str, object]:
    data_dir.mkdir(parents=True, exist_ok=True)
    train_rows = [mlx_chat_record(record) for record in train_records]
    validation_rows = [mlx_chat_record(record) for record in validation_records]
    train_path = data_dir / "train.jsonl"
    validation_path = data_dir / "valid.jsonl"
    train_path.write_text(jsonl_text(train_rows), encoding="utf-8")
    validation_path.write_text(jsonl_text(validation_rows), encoding="utf-8")
    return {
        "data_dir": str(data_dir),
        "train_path": str(train_path),
        "validation_path": str(validation_path),
        "train_examples": len(train_rows),
        "validation_examples": len(validation_rows),
        "train_sha256": file_sha256(train_path),
        "validation_sha256": file_sha256(validation_path),
    }


def mlx_runtime_probe(trainer_python: Path) -> Dict[str, object]:
    if not trainer_python.exists():
        return {"ok": False, "python": str(trainer_python), "error": "trainer_python_missing"}
    code = (
        "import importlib.metadata,json,mlx.core as mx;"
        "print(json.dumps({'mlx_lm':importlib.metadata.version('mlx-lm'),"
        "'mlx':importlib.metadata.version('mlx'),'device':str(mx.default_device())}))"
    )
    try:
        completed = subprocess.run(
            [str(trainer_python), "-c", code],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            env={**os.environ, **THREAD_ENV},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "python": str(trainer_python), "error": str(exc)}
    if completed.returncode != 0:
        return {
            "ok": False,
            "python": str(trainer_python),
            "error": (completed.stderr or completed.stdout).strip()[-1000:],
        }
    try:
        details = json.loads(completed.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        details = {"raw": completed.stdout.strip()}
    return {"ok": True, "python": str(trainer_python), "details": details}


def selected_input_records(args: argparse.Namespace) -> tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    train_records = records_for_split(read_jsonl(Path(args.train_jsonl).expanduser()), "train")
    validation_records = records_for_split(
        read_jsonl(Path(args.validation_jsonl).expanduser()),
        "validation",
    )
    return train_records, validation_records


def build_plan(args: argparse.Namespace) -> Dict[str, object]:
    train_path = Path(args.train_jsonl).expanduser()
    validation_path = Path(args.validation_jsonl).expanduser()
    train_records, validation_records = selected_input_records(args)
    missing_inputs: List[str] = []
    if not train_records:
        missing_inputs.append("train_jsonl")
    if not validation_records:
        missing_inputs.append("validation_jsonl")
    if not args.base_model:
        missing_inputs.append("base_model")
    if not args.output_dir:
        missing_inputs.append("output_dir")

    runtime_probe: Optional[Dict[str, object]] = None
    missing_modules: List[str] = []
    if args.backend == "mlx":
        runtime_probe = mlx_runtime_probe(Path(args.trainer_python).expanduser())
        if not runtime_probe.get("ok"):
            missing_modules.append("mlx_lm_isolated_runtime")
    else:
        missing_modules = [name for name in TRANSFORMERS_RUN_MODULES if not module_available(name)]
        if args.run and args.qlora:
            missing_inputs.append("transformers_qlora_run_not_implemented")

    ready = not missing_inputs and (args.dry_run or not missing_modules)
    return {
        "status": "ready" if ready else "blocked",
        "backend": args.backend,
        "dry_run": bool(args.dry_run),
        "train_jsonl": str(train_path),
        "validation_jsonl": str(validation_path),
        "train_examples": len(train_records),
        "validation_examples": len(validation_records),
        "base_model": args.base_model,
        "output_dir": args.output_dir,
        "qlora": bool(args.qlora),
        "max_steps": int(args.max_steps),
        "rank": int(args.rank),
        "alpha": int(args.alpha),
        "missing_inputs": missing_inputs,
        "missing_run_modules": [] if args.dry_run else missing_modules,
        "runtime_probe": runtime_probe,
        "boundary": "Training is explicit. This script never changes Eve routing or promotes an adapter.",
    }


def mlx_training_config(args: argparse.Namespace, *, data_dir: Path, adapter_path: Path) -> Dict[str, object]:
    if args.rank <= 0:
        raise ValueError("rank must be positive")
    return {
        "model": str(Path(args.base_model).expanduser()),
        "train": True,
        "fine_tune_type": "lora",
        "optimizer": args.optimizer,
        "data": str(data_dir),
        "seed": int(args.seed),
        "num_layers": int(args.num_layers),
        "batch_size": int(args.batch_size),
        "iters": int(args.max_steps),
        "val_batches": int(args.val_batches),
        "learning_rate": float(args.learning_rate),
        "steps_per_report": int(args.steps_per_report),
        "steps_per_eval": int(args.steps_per_eval),
        "grad_accumulation_steps": int(args.gradient_accumulation_steps),
        "resume_adapter_file": (
            str(Path(args.resume_adapter_file).expanduser())
            if getattr(args, "resume_adapter_file", None)
            else None
        ),
        "adapter_path": str(adapter_path),
        "save_every": int(args.save_every),
        "max_seq_length": int(args.max_seq_length),
        "grad_checkpoint": bool(args.grad_checkpoint),
        "mask_prompt": True,
        "lora_parameters": {
            "rank": int(args.rank),
            "dropout": float(args.dropout),
            "scale": float(args.alpha) / float(args.rank),
        },
    }


def run_mlx_training(args: argparse.Namespace) -> Dict[str, object]:
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    train_records, validation_records = selected_input_records(args)
    data_report = write_mlx_data(train_records, validation_records, output_dir / "data")
    adapter_path = output_dir / "adapter"
    config = mlx_training_config(args, data_dir=output_dir / "data", adapter_path=adapter_path)
    config_path = output_dir / "mlx_lora_config.yaml"
    config_path.write_text(json.dumps(config, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Keep the virtualenv path itself: Path.resolve() follows the Python symlink
    # into Homebrew and loses the sibling mlx_lm.lora entry point.
    trainer_python = Path(os.path.abspath(Path(args.trainer_python).expanduser()))
    trainer_cli = trainer_python.parent / "mlx_lm.lora"
    if not trainer_cli.exists():
        raise RuntimeError(f"MLX trainer CLI missing: {trainer_cli}")
    command = [str(trainer_cli), "--config", str(config_path)]
    log_path = output_dir / "training.log"
    started_at = utc_now()
    with log_path.open("w", encoding="utf-8") as log_handle:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, **THREAD_ENV},
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            log_handle.write(line)
            log_handle.flush()
        return_code = process.wait()

    manifest = {
        "schema_id": "eve.mlx_lora_training_run.v1",
        "status": "trained" if return_code == 0 else "failed",
        "started_at": started_at,
        "completed_at": utc_now(),
        "backend": "mlx",
        "trainer_python": str(trainer_python),
        "trainer_runtime": mlx_runtime_probe(trainer_python),
        "command": command,
        "config_path": str(config_path),
        "config_sha256": file_sha256(config_path),
        "adapter_path": str(adapter_path),
        "resume_adapter_file": config.get("resume_adapter_file"),
        "adapter_exists": (adapter_path / "adapters.safetensors").exists(),
        "data": data_report,
        "return_code": return_code,
        "log_path": str(log_path),
        "boundary": "Candidate artifact only; no live Eve lane was changed.",
    }
    manifest_path = output_dir / "training_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def run_transformers_training(args: argparse.Namespace) -> Dict[str, object]:
    # Imports stay inside the explicit training path so dry-run works on a clean Mac.
    from datasets import Dataset
    from peft import LoraConfig
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from trl import SFTConfig, SFTTrainer

    train_records, validation_records = selected_input_records(args)
    train_dataset = Dataset.from_dict({"text": [format_example(record) for record in train_records]})
    validation_dataset = Dataset.from_dict({"text": [format_example(record) for record in validation_records]})
    tokenizer = AutoTokenizer.from_pretrained(args.base_model)
    model = AutoModelForCausalLM.from_pretrained(args.base_model)
    peft_config = LoraConfig(
        r=args.rank,
        lora_alpha=args.alpha,
        lora_dropout=args.dropout,
        bias="none",
        task_type="CAUSAL_LM",
    )
    config = SFTConfig(
        output_dir=args.output_dir,
        max_steps=args.max_steps,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        logging_steps=args.steps_per_report,
        save_steps=args.save_every,
        eval_steps=args.steps_per_eval,
        dataset_text_field="text",
    )
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_dataset,
        eval_dataset=validation_dataset,
        peft_config=peft_config,
        args=config,
    )
    trainer.train()
    trainer.save_model(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)
    return {
        "schema_id": "eve.transformers_lora_training_run.v1",
        "status": "trained",
        "backend": "transformers",
        "output_dir": args.output_dir,
        "boundary": "Candidate artifact only; no live Eve lane was changed.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dry-run-first local LoRA trainer for Eve curated data.")
    parser.add_argument("--train-jsonl", required=True)
    parser.add_argument("--validation-jsonl", required=True)
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--backend", choices=["mlx", "transformers"], default="transformers")
    parser.add_argument("--trainer-python", default=str(DEFAULT_MLX_TRAINER_PYTHON))
    parser.add_argument("--resume-adapter-file")
    parser.add_argument("--max-steps", type=int, default=200)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--alpha", type=int, default=320)
    parser.add_argument("--dropout", type=float, default=0.05)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=1e-5)
    parser.add_argument("--num-layers", type=int, default=16)
    parser.add_argument("--val-batches", type=int, default=-1)
    parser.add_argument("--max-seq-length", type=int, default=768)
    parser.add_argument("--steps-per-report", type=int, default=10)
    parser.add_argument("--steps-per-eval", type=int, default=50)
    parser.add_argument("--save-every", type=int, default=100)
    parser.add_argument("--optimizer", choices=["adam", "adamw", "muon", "sgd", "adafactor"], default="adam")
    parser.add_argument("--seed", type=int, default=20260712)
    parser.add_argument("--grad-checkpoint", action="store_true")
    parser.add_argument("--qlora", action="store_true", help="Record/use quantized-base LoRA intent.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Validate inputs and print a plan. This is the default.")
    mode.add_argument("--run", action="store_true", help="Actually run local training.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.run:
        args.dry_run = True
    plan = build_plan(args)
    if args.dry_run:
        print(json.dumps(plan, indent=2, ensure_ascii=True, sort_keys=True))
        return 0 if plan["status"] == "ready" else 1
    if plan["status"] != "ready":
        print(json.dumps(plan, indent=2, ensure_ascii=True, sort_keys=True))
        return 2
    if args.backend == "mlx":
        report = run_mlx_training(args)
    else:
        report = run_transformers_training(args)
    print(json.dumps(report, indent=2, ensure_ascii=True, sort_keys=True))
    return 0 if report.get("status") == "trained" else 3


if __name__ == "__main__":
    raise SystemExit(main())
