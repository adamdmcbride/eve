#!/usr/bin/env python3

import argparse
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_TRACE_EXPORT = Path(".eve") / "trace_exports" / "latest_openinference.jsonl"
DEFAULT_REPORT_PATH = Path(".eve") / "oss_lab" / "latest_oss_lab_report.json"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"
DEFAULT_PHOENIX_WORKING_DIR = Path(".eve") / "oss_lab" / "phoenix_preflight"
DEFAULT_TRAINER_LAB_ROOT = Path.home() / "Library" / "Application Support" / "Eve" / "labs"
DEFAULT_TRAINING_DATASET_DIR = Path(".eve") / "training_datasets"
DEFAULT_TRAINER_RECIPE_DIR = Path(".eve") / "oss_lab" / "trainer_recipes"
# Eve Chat owns loopback port 3000. Keep Langfuse on a distinct, configurable
# loopback endpoint so an unrelated HTTP 200 cannot masquerade as observability.
DEFAULT_LANGFUSE_URL = os.environ.get("EVE_LANGFUSE_URL", "http://127.0.0.1:3001")
DEFAULT_PHOENIX_PORT = 6006
COMMAND_TIMEOUT_SECONDS = 20
DISALLOWED_TRAINING_PRIVACY_TIERS = {"hidden", "hidden_probe", "private", "private_holdout", "secret_holdout"}
TRAINER_THREAD_LIMIT_ENV = {
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}

TOOL_REGISTRY: List[Dict[str, str]] = [
    {
        "id": "openinference_semconv",
        "distribution": "openinference-semantic-conventions",
        "import_name": "openinference.semconv",
        "layer": "trace_provenance",
        "admission": "lab_only",
        "purpose": "Keep Eve trace exports aligned with OpenInference/OpenTelemetry semantics.",
    },
    {
        "id": "phoenix",
        "distribution": "arize-phoenix",
        "import_name": "phoenix",
        "layer": "trace_ui_and_evals",
        "admission": "lab_only",
        "purpose": "Local trace UI and eval workbench for exported OpenInference spans.",
    },
    {
        "id": "langfuse",
        "distribution": "langfuse",
        "import_name": "langfuse",
        "layer": "trace_ui_and_evals",
        "admission": "lab_only",
        "purpose": "Alternate observability client; requires an explicit local/server endpoint before use.",
    },
    {
        "id": "dvc",
        "distribution": "dvc",
        "import_name": "dvc",
        "layer": "dataset_versioning",
        "admission": "lab_only",
        "purpose": "Version curated eval/training datasets after privacy tiering and holdout split.",
    },
    {
        "id": "deepeval",
        "distribution": "deepeval",
        "import_name": "deepeval",
        "layer": "eval_framework",
        "admission": "lab_only",
        "purpose": "Local regression-style LLM evals for public, non-hidden test slices.",
    },
    {
        "id": "ragas",
        "distribution": "ragas",
        "import_name": "ragas",
        "layer": "eval_framework",
        "admission": "lab_only",
        "purpose": "RAG and grounding evals for memory/context retrieval quality.",
    },
    {
        "id": "langgraph",
        "distribution": "langgraph",
        "import_name": "langgraph",
        "layer": "workflow_lab",
        "admission": "lab_only",
        "purpose": "Durable workflow prototype for one bounded detect-plan-act-verify-reflect lab loop.",
    },
    {
        "id": "peft",
        "distribution": "peft",
        "import_name": "peft",
        "layer": "adapter_training",
        "admission": "lab_only",
        "purpose": "LoRA/adapter training experiments from verified Eve episodes.",
    },
    {
        "id": "axolotl",
        "distribution": "axolotl",
        "import_name": "axolotl",
        "layer": "adapter_training_candidate",
        "admission": "compatibility_gated",
        "purpose": "Heavy trainer candidate; keep out of the main venv until hardware/Python gates pass.",
    },
    {
        "id": "llamafactory",
        "distribution": "llamafactory",
        "import_name": "llamafactory",
        "layer": "adapter_training_candidate",
        "admission": "source_install_gated",
        "purpose": "Heavy trainer candidate; official path is source clone plus editable install.",
    },
    {
        "id": "unsloth",
        "distribution": "unsloth",
        "import_name": "unsloth",
        "layer": "adapter_training_candidate",
        "admission": "python_version_gated",
        "purpose": "Fast trainer/studio candidate; current official macOS training gate excludes Python 3.14.",
    },
    {
        "id": "mlx_lm",
        "distribution": "mlx-lm",
        "import_name": "mlx_lm",
        "layer": "apple_silicon_adapter_training",
        "admission": "isolated_lab_only",
        "purpose": "Apple Silicon native MLX LoRA/QLoRA candidate; keep isolated from the main runtime venv.",
    },
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def text_tail(text: str, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def eve_project_root_candidates() -> List[Path]:
    raw_candidates: List[object] = [
        PROJECT_ROOT,
        os.environ.get("EVE_SOURCE_DIR"),
        os.environ.get("EVE_PROJECT_ROOT"),
        Path.home() / "Documents" / "Finances" / "Eve",
    ]
    candidates: List[Path] = []
    seen: set[str] = set()
    for raw in raw_candidates:
        if not raw:
            continue
        try:
            candidate = Path(str(raw)).expanduser().resolve()
        except OSError:
            continue
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if (candidate / "bin" / "eve_oss_lab.py").exists():
            candidates.append(candidate)
    return candidates or [PROJECT_ROOT]


def resolve_executable(name: str) -> str:
    candidates = [Path(sys.executable).parent / name]
    candidates.extend(root / ".venv" / "bin" / name for root in eve_project_root_candidates())
    candidates.append(Path.cwd() / ".venv" / "bin" / name)
    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return shutil.which(name) or ""


def run_command(command: List[str], timeout: int = COMMAND_TIMEOUT_SECONDS, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
    except FileNotFoundError:
        return {"status": "missing", "command": command, "returncode": None, "stdout_tail": "", "stderr_tail": "command not found"}
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "timeout",
            "command": command,
            "returncode": None,
            "stdout_tail": text_tail(exc.stdout or ""),
            "stderr_tail": text_tail(exc.stderr or ""),
        }
    return {
        "status": "ok" if completed.returncode == 0 else "error",
        "command": command,
        "returncode": completed.returncode,
        "stdout_tail": text_tail(completed.stdout or ""),
        "stderr_tail": text_tail(completed.stderr or ""),
    }


def merged_env(overrides: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env = os.environ.copy()
    if overrides:
        env.update(overrides)
    return env


def package_version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return ""


def importable(import_name: str) -> bool:
    try:
        return importlib.util.find_spec(import_name) is not None
    except (ImportError, ValueError):
        return False


def resolve_inventory_python() -> str:
    override = os.environ.get("EVE_OSS_INVENTORY_PYTHON", "").strip()
    candidates = [Path(override).expanduser()] if override else []
    candidates.extend(root / ".venv" / "bin" / "python" for root in eve_project_root_candidates())
    candidates.extend([DEFAULT_PROJECT_PYTHON, Path(sys.executable)])
    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return sys.executable


def probe_inventory_environment(
    registry: Optional[List[Dict[str, str]]] = None,
    *,
    python_executable: str = "",
) -> Dict[str, Any]:
    requested = [
        {
            "id": str(tool.get("id") or ""),
            "distribution": str(tool.get("distribution") or ""),
            "import_name": str(tool.get("import_name") or ""),
        }
        for tool in (registry or TOOL_REGISTRY)
    ]
    probe_python = python_executable or resolve_inventory_python()
    script = """
import importlib.metadata
import importlib.util
import json
import sys

requested = json.loads(sys.argv[1])
tools = {}
for item in requested:
    distribution = str(item.get("distribution") or "")
    import_name = str(item.get("import_name") or "")
    try:
        version = importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        version = ""
    try:
        importable = bool(import_name and importlib.util.find_spec(import_name) is not None)
    except (ImportError, ModuleNotFoundError, ValueError):
        importable = False
    tools[str(item.get("id") or distribution)] = {
        "version": version,
        "installed": bool(version),
        "importable": importable,
    }
print(json.dumps({
    "python_executable": sys.executable,
    "python_version": sys.version.split()[0],
    "tools": tools,
}, sort_keys=True))
""".strip()
    result = run_command(
        [probe_python, "-c", script, json.dumps(requested, separators=(",", ":"))],
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    if result.get("status") == "ok":
        try:
            payload = json.loads(str(result.get("stdout_tail") or ""))
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict) and isinstance(payload.get("tools"), dict):
            return {
                "status": "ok",
                "controller_python": sys.executable,
                "requested_python": probe_python,
                **payload,
            }

    fallback_tools: Dict[str, Dict[str, Any]] = {}
    for item in requested:
        fallback_tools[item["id"]] = {
            "version": package_version(item["distribution"]),
            "installed": bool(package_version(item["distribution"])),
            "importable": importable(item["import_name"]),
        }
    return {
        "status": "fallback_current_interpreter",
        "controller_python": sys.executable,
        "requested_python": probe_python,
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "tools": fallback_tools,
        "error": str(result.get("stderr_tail") or result.get("stdout_tail") or "environment probe failed"),
    }


def build_inventory() -> Dict[str, Any]:
    environment = probe_inventory_environment()
    probed_tools = environment.get("tools") if isinstance(environment.get("tools"), dict) else {}
    tools: List[Dict[str, Any]] = []
    for tool in TOOL_REGISTRY:
        probe = probed_tools.get(tool["id"]) if isinstance(probed_tools.get(tool["id"]), dict) else {}
        version = str(probe.get("version") or "")
        is_importable = bool(probe.get("importable"))
        tools.append(
            {
                **tool,
                "installed": bool(version),
                "importable": is_importable,
                "version": version,
                "live_authority": False,
            }
        )
    installed_count = sum(1 for tool in tools if tool["installed"] and tool["importable"])
    gated = [tool for tool in tools if not tool["installed"] or not tool["importable"]]
    return {
        "schema_id": "eve_oss_lab_inventory.v2",
        "generated_at": utc_now(),
        "status": "ready" if installed_count >= 8 else "partial",
        "installed_importable_count": installed_count,
        "tool_count": len(tools),
        "tools": tools,
        "gated_tools": [
            {
                "id": tool["id"],
                "admission": tool["admission"],
                "purpose": tool["purpose"],
            }
            for tool in gated
        ],
        "environment": {
            "status": environment.get("status"),
            "controller_python": environment.get("controller_python") or sys.executable,
            "requested_python": environment.get("requested_python") or "",
            "probe_python": environment.get("python_executable") or "",
            "probe_python_version": environment.get("python_version") or "",
            "error": environment.get("error") or "",
        },
        "boundary": {
            "lab_only": True,
            "grants_live_authority": False,
            "writes_eve_memory": False,
            "promotes_models": False,
        },
    }


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                records.append({"_invalid_json": True, "line_number": line_number})
                continue
            records.append(payload if isinstance(payload, dict) else {"_invalid_record": True, "line_number": line_number})
    return records


def safe_label(value: Any) -> str:
    text = str(value or "unspecified")
    if re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", text):
        return text
    return "redacted_label"


def summarize_training_split(path: Path) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "row_count": 0,
        "invalid_json_count": 0,
        "disallowed_privacy_row_count": 0,
        "privacy_tiers": {},
        "source_counts": {},
        "missing_required_counts": {},
    }
    if not path.exists():
        return summary

    privacy_tiers: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    missing_required_counts: Counter[str] = Counter()
    required_fields = ("prompt", "preferred_response", "privacy_tier")
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError:
                summary["invalid_json_count"] += 1
                continue
            if not isinstance(row, dict):
                summary["invalid_json_count"] += 1
                continue
            summary["row_count"] += 1
            privacy_tier = safe_label(row.get("privacy_tier"))
            source = safe_label(row.get("source") or row.get("example_source"))
            privacy_tiers[privacy_tier] += 1
            source_counts[source] += 1
            if privacy_tier.lower() in DISALLOWED_TRAINING_PRIVACY_TIERS:
                summary["disallowed_privacy_row_count"] += 1
            for field in required_fields:
                value = row.get(field)
                if value is None or value == "":
                    missing_required_counts[field] += 1

    summary["privacy_tiers"] = dict(sorted(privacy_tiers.items()))
    summary["source_counts"] = dict(source_counts.most_common(8))
    summary["missing_required_counts"] = dict(sorted(missing_required_counts.items()))
    return summary


def training_dataset_snapshot(dataset_dir: Optional[Path] = None) -> Dict[str, Any]:
    dataset_dir = (dataset_dir or DEFAULT_TRAINING_DATASET_DIR).expanduser()
    train = summarize_training_split(dataset_dir / "latest_train.jsonl")
    validation = summarize_training_split(dataset_dir / "latest_validation.jsonl")
    latest_manifest = dataset_dir / "latest.json"
    blocked_reasons: List[str] = []
    for split_name, split in (("train", train), ("validation", validation)):
        if not split["exists"]:
            blocked_reasons.append(f"{split_name}_missing")
        if split["invalid_json_count"]:
            blocked_reasons.append(f"{split_name}_invalid_json")
        if split["disallowed_privacy_row_count"]:
            blocked_reasons.append(f"{split_name}_disallowed_privacy_rows")
        if split["row_count"] == 0:
            blocked_reasons.append(f"{split_name}_empty")
    status = "ready" if not blocked_reasons else "blocked"
    return {
        "schema_id": "eve_oss_lab_training_dataset_snapshot.v1",
        "generated_at": utc_now(),
        "status": status,
        "dataset_dir": str(dataset_dir),
        "latest_manifest": str(latest_manifest),
        "latest_manifest_exists": latest_manifest.exists(),
        "splits": {
            "train": train,
            "validation": validation,
        },
        "blocked_reasons": blocked_reasons,
        "contains_row_text": False,
        "private_holdout_policy": "Private holdout rows stay outside Eve-readable project/runtime state.",
    }


def render_llamafactory_recipe(dataset_dir: Path, output_dir: Path) -> str:
    dataset_info_path = output_dir / "llamafactory_dataset_info.json"
    lines = [
        "# Eve LLaMA-Factory recipe generated by bin/eve_oss_lab.py",
        "# Recipe only: do_train is false and no model is downloaded or trained by this file.",
        'model_name_or_path: "REPLACE_WITH_APPROVED_LOCAL_BASE_MODEL_PATH"',
        "stage: sft",
        "do_train: false",
        "finetuning_type: lora",
        "lora_target: all",
        f"dataset_dir: {json.dumps(str(output_dir.resolve()))}",
        "dataset: eve_curated_train",
        "eval_dataset: eve_curated_validation",
        "template: default",
        "cutoff_len: 4096",
        f"output_dir: {json.dumps(str((output_dir / 'llamafactory_shadow_output').resolve()))}",
        "per_device_train_batch_size: 1",
        "gradient_accumulation_steps: 8",
        "learning_rate: 0.0002",
        "num_train_epochs: 1.0",
        "logging_steps: 10",
        "save_steps: 100",
        "report_to: none",
        "overwrite_output_dir: false",
        f"# dataset_info: {dataset_info_path.name}",
        f"# source_train_jsonl: {dataset_dir / 'latest_train.jsonl'}",
        f"# source_validation_jsonl: {dataset_dir / 'latest_validation.jsonl'}",
    ]
    return "\n".join(lines) + "\n"


def build_llamafactory_dataset_info(dataset_dir: Path) -> Dict[str, Any]:
    return {
        "eve_curated_train": {
            "file_name": str((dataset_dir / "latest_train.jsonl").resolve()),
            "formatting": "alpaca",
            "columns": {
                "prompt": "prompt",
                "response": "preferred_response",
            },
        },
        "eve_curated_validation": {
            "file_name": str((dataset_dir / "latest_validation.jsonl").resolve()),
            "formatting": "alpaca",
            "columns": {
                "prompt": "prompt",
                "response": "preferred_response",
            },
        },
    }


def build_unsloth_recipe(dataset_dir: Path, output_dir: Path) -> Dict[str, Any]:
    return {
        "schema_id": "eve_unsloth_recipe.v1",
        "status": "recipe_only",
        "no_training_started": True,
        "base_model": "REPLACE_WITH_APPROVED_LOCAL_BASE_MODEL_PATH",
        "train_jsonl": str((dataset_dir / "latest_train.jsonl").resolve()),
        "validation_jsonl": str((dataset_dir / "latest_validation.jsonl").resolve()),
        "output_dir": str((output_dir / "unsloth_shadow_output").resolve()),
        "max_seq_length": 4096,
        "load_in_4bit": True,
        "lora": {
            "r": 16,
            "alpha": 16,
            "dropout": 0.05,
            "target_modules": "review_before_training",
        },
        "promotion_boundary": "shadow_only_until_validation_holdout_rollback_governance_and_user_approval_pass",
    }


def render_mlx_lm_recipe(output_dir: Path) -> str:
    lines = [
        "# Eve MLX-LM LoRA recipe generated by bin/eve_oss_lab.py",
        "# Recipe only: train is false and no model is downloaded or trained by this file.",
        'model: "REPLACE_WITH_APPROVED_LOCAL_MLX_MODEL_PATH"',
        "train: false",
        f"data: {json.dumps(str((output_dir / 'mlx_lm_data').resolve()))}",
        "fine_tune_type: lora",
        "batch_size: 1",
        "iters: 10",
        "learning_rate: 0.0001",
        "num_layers: 8",
        "grad_checkpoint: true",
        "max_seq_length: 4096",
        f"adapter_path: {json.dumps(str((output_dir / 'mlx_lm_adapters').resolve()))}",
        "report_to: none",
        "seed: 7",
        "# Required launch env for this Mac lab:",
        "# OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1",
        "# Data directory must contain MLX-LM local files named train.jsonl and optional valid.jsonl.",
        "# Eve source rows stay in .eve/training_datasets/latest_train.jsonl and latest_validation.jsonl.",
    ]
    return "\n".join(lines) + "\n"


def build_mlx_lm_data_plan(dataset_dir: Path, output_dir: Path) -> Dict[str, Any]:
    return {
        "schema_id": "eve_mlx_lm_data_plan.v1",
        "status": "plan_only",
        "no_training_started": True,
        "recommended_data_dir": str((output_dir / "mlx_lm_data").resolve()),
        "required_files": ["train.jsonl", "valid.jsonl"],
        "source_train_jsonl": str((dataset_dir / "latest_train.jsonl").resolve()),
        "source_validation_jsonl": str((dataset_dir / "latest_validation.jsonl").resolve()),
        "recommended_format": "completion",
        "recommended_mapping": {
            "prompt": "prompt",
            "completion": "preferred_response",
        },
        "contains_row_text": False,
        "private_holdout_policy": "Do not copy private holdout rows into MLX-LM data.",
    }


def build_axolotl_gate(output_dir: Path) -> Dict[str, Any]:
    return {
        "schema_id": "eve_axolotl_gate.v1",
        "status": "not_installed_hardware_gated",
        "no_training_started": True,
        "recipe_dir": str(output_dir.resolve()),
        "reason": "Axolotl stays out of Eve's main venv and this Mac does not expose the NVIDIA/AMD trainer profile expected by the current Axolotl path.",
        "safe_next_step": "Only create an Axolotl recipe in a GPU-matched isolated trainer environment with enough verified disk headroom.",
    }


def trainer_recipe_plan(dataset_dir: Optional[Path] = None, output_dir: Optional[Path] = None, write: bool = False) -> Dict[str, Any]:
    dataset_dir = (dataset_dir or DEFAULT_TRAINING_DATASET_DIR).expanduser()
    output_dir = (output_dir or DEFAULT_TRAINER_RECIPE_DIR).expanduser()
    snapshot = training_dataset_snapshot(dataset_dir)
    recipe_files: Dict[str, str] = {}
    missing_recipe_ids: List[str] = []
    stale_recipe_ids: List[str] = []
    status = "ready_to_write" if snapshot["status"] == "ready" else "blocked"

    dataset_info = build_llamafactory_dataset_info(dataset_dir)
    paths_and_payloads = {
        "llamafactory_recipe": (output_dir / "llamafactory_eve_sft_recipe.yaml", render_llamafactory_recipe(dataset_dir, output_dir)),
        "llamafactory_dataset_info": (
            output_dir / "llamafactory_dataset_info.json",
            json.dumps(dataset_info, indent=2, ensure_ascii=True) + "\n",
        ),
        "unsloth_recipe": (
            output_dir / "unsloth_eve_sft_recipe.json",
            json.dumps(build_unsloth_recipe(dataset_dir, output_dir), indent=2, ensure_ascii=True) + "\n",
        ),
        "mlx_lm_recipe": (output_dir / "mlx_lm_lora_recipe.yaml", render_mlx_lm_recipe(output_dir)),
        "mlx_lm_data_plan": (
            output_dir / "mlx_lm_data_plan.json",
            json.dumps(build_mlx_lm_data_plan(dataset_dir, output_dir), indent=2, ensure_ascii=True) + "\n",
        ),
        "axolotl_gate": (
            output_dir / "axolotl_gate.json",
            json.dumps(build_axolotl_gate(output_dir), indent=2, ensure_ascii=True) + "\n",
        ),
    }

    def normalized_recipe_text(value: str) -> str:
        # Source and runtime dataset mirrors are byte-identical but have
        # different absolute roots.  Recipe validity depends on the stable
        # `latest_*.jsonl` and recipe contracts, not which mirror inspected it.
        dataset_aliases = {
            str(dataset_dir),
            str(dataset_dir.resolve()),
            str(DEFAULT_TRAINING_DATASET_DIR),
            str(DEFAULT_TRAINING_DATASET_DIR.resolve()),
            str((Path.home() / ".eve_runtime" / ".eve" / "training_datasets").resolve()),
        }
        output_aliases = {
            str(output_dir),
            str(output_dir.resolve()),
            str(DEFAULT_TRAINER_RECIPE_DIR),
            str(DEFAULT_TRAINER_RECIPE_DIR.resolve()),
            str((Path.home() / ".eve_runtime" / ".eve" / "oss_lab" / "trainer_recipes").resolve()),
        }
        normalized = value
        for alias in sorted(dataset_aliases, key=len, reverse=True):
            normalized = normalized.replace(alias, "<EVE_TRAINING_DATASET_DIR>")
        for alias in sorted(output_aliases, key=len, reverse=True):
            normalized = normalized.replace(alias, "<EVE_TRAINER_RECIPE_DIR>")
        return normalized

    if write and snapshot["status"] == "ready":
        output_dir.mkdir(parents=True, exist_ok=True)
        for key, (path, payload) in paths_and_payloads.items():
            path.write_text(payload, encoding="utf-8")
            recipe_files[key] = str(path)
        status = "written"
    elif write:
        status = "blocked"
    elif snapshot["status"] == "ready":
        for key, (path, expected_payload) in paths_and_payloads.items():
            if not path.is_file():
                missing_recipe_ids.append(key)
                continue
            recipe_files[key] = str(path)
            try:
                actual_payload = path.read_text(encoding="utf-8")
            except OSError:
                stale_recipe_ids.append(key)
                continue
            if normalized_recipe_text(actual_payload) != normalized_recipe_text(expected_payload):
                stale_recipe_ids.append(key)
        if not missing_recipe_ids and not stale_recipe_ids:
            status = "written_current"
        elif recipe_files:
            status = "stale_or_incomplete"

    return {
        "schema_id": "eve_oss_lab_trainer_recipe_plan.v1",
        "generated_at": utc_now(),
        "status": status,
        "write_performed": bool(write and snapshot["status"] == "ready"),
        "output_dir": str(output_dir),
        "dataset_snapshot": snapshot,
        "recipe_files": recipe_files,
        "expected_recipe_count": len(paths_and_payloads),
        "existing_recipe_count": len(recipe_files),
        "missing_recipe_ids": missing_recipe_ids,
        "stale_recipe_ids": stale_recipe_ids,
        "boundary": {
            "lab_only": True,
            "no_training_started": True,
            "downloads_models": False,
            "writes_eve_memory": False,
            "promotes_models": False,
            "includes_private_holdout_rows": False,
            "contains_row_text": False,
        },
        "safe_next_step": (
            "Review the generated recipe placeholders, choose an approved local base model, then run a supervised dry-run in one isolated trainer venv."
            if status in {"written", "written_current"}
            else "Regenerate the stale or incomplete no-training recipe set before using a trainer gate."
            if status == "stale_or_incomplete"
            else "Run with `--write-trainer-recipes` to generate recipe files from the ready curated dataset."
            if status == "ready_to_write"
            else "Build or repair Eve's curated train/validation dataset before writing trainer recipes."
        ),
    }


def validate_trace_record(record: Dict[str, Any]) -> List[str]:
    problems: List[str] = []
    context = record.get("context") if isinstance(record.get("context"), dict) else {}
    attributes = record.get("attributes") if isinstance(record.get("attributes"), dict) else {}
    if record.get("_invalid_json"):
        return ["invalid_json"]
    if record.get("_invalid_record"):
        return ["invalid_record"]
    if record.get("schema_version") != "eve_openinference_span.v1":
        problems.append("schema_version")
    if not record.get("name"):
        problems.append("name")
    if not context.get("trace_id"):
        problems.append("trace_id")
    if not context.get("span_id"):
        problems.append("span_id")
    if not attributes.get("openinference.span.kind"):
        problems.append("openinference_span_kind")
    if record.get("status_code") not in {"OK", "ERROR"}:
        problems.append("status_code")
    return problems


def trace_workbench(trace_path: Path) -> Dict[str, Any]:
    records = read_jsonl(trace_path)
    kind_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    problem_counts: Counter[str] = Counter()
    sample_problems: List[Dict[str, Any]] = []

    for index, record in enumerate(records, start=1):
        attributes = record.get("attributes") if isinstance(record.get("attributes"), dict) else {}
        kind_counts[str(attributes.get("openinference.span.kind") or "UNKNOWN")] += 1
        status_counts[str(record.get("status_code") or "UNKNOWN")] += 1
        problems = validate_trace_record(record)
        for problem in problems:
            problem_counts[problem] += 1
        if problems and len(sample_problems) < 8:
            sample_problems.append({"index": index, "problems": problems, "name": record.get("name") or ""})

    status = "missing" if not trace_path.exists() else "ready"
    if records and problem_counts:
        status = "needs_cleanup"
    elif not records and trace_path.exists():
        status = "empty"
    return {
        "schema_id": "eve_oss_lab_trace_workbench.v1",
        "generated_at": utc_now(),
        "status": status,
        "trace_path": str(trace_path),
        "record_count": len(records),
        "kind_counts": dict(kind_counts),
        "status_counts": dict(status_counts),
        "problem_counts": dict(problem_counts),
        "sample_problems": sample_problems,
        "collector_required": False,
        "safe_next_step": (
            "Run a bounded Phoenix/Langfuse server preflight, then import/send this export only if the local UI is reachable."
            if status == "ready"
            else "Regenerate or clean the local OpenInference JSONL export before attaching a trace UI."
        ),
    }


def url_status(url: str, timeout: float = 1.0) -> Dict[str, Any]:
    def response_record(response: Any, *, http_error: str = "") -> Dict[str, Any]:
        raw = response.read(16384)
        text = raw.decode("utf-8", errors="replace")
        content_type = str(response.headers.get("Content-Type") or "")
        parsed: Any = None
        if "json" in content_type.lower() or text.lstrip().startswith(("{", "[")):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
        status_code = getattr(response, "status", None) or getattr(response, "code", None)
        return {
            "reachable": bool(status_code is not None and 200 <= int(status_code) < 400),
            "responded": True,
            "status_code": status_code,
            "content_type": content_type,
            "body_json": parsed,
            "body_preview": " ".join(text.split())[:500],
            "error": http_error,
        }

    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json, text/html;q=0.8"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response_record(response)
    except urllib.error.HTTPError as exc:
        return response_record(exc, http_error=f"HTTP {exc.code}: {exc.reason}")
    except urllib.error.URLError as exc:
        return {
            "reachable": False,
            "responded": False,
            "status_code": None,
            "content_type": "",
            "body_json": None,
            "body_preview": "",
            "error": str(exc.reason),
        }
    except Exception as exc:  # pragma: no cover - defensive around platform URL handlers
        return {
            "reachable": False,
            "responded": False,
            "status_code": None,
            "content_type": "",
            "body_json": None,
            "body_preview": "",
            "error": str(exc),
        }


def phoenix_runtime_status(url: Optional[str] = None) -> Dict[str, Any]:
    """Describe the Phoenix service that is reachable *now*.

    A bounded Phoenix preflight starts and then stops a temporary process.  Its
    historical ``server_ready`` result is useful canary evidence, but it is not
    proof that a service is still running.  Keep that distinction explicit and
    verify Phoenix identity through its installed ``/healthz`` and ``/readyz``
    routes so another HTTP listener cannot masquerade as Phoenix.
    """

    base_url = (url or f"http://127.0.0.1:{DEFAULT_PHOENIX_PORT}").rstrip("/")
    local = url_status(base_url, timeout=1.0)
    health = url_status(f"{base_url}/healthz", timeout=1.0)
    ready = url_status(f"{base_url}/readyz", timeout=1.0)
    identity_verified = bool(
        health.get("responded")
        and str(health.get("body_preview") or "").strip().upper() == "OK"
    )
    if identity_verified and health.get("reachable") and ready.get("reachable"):
        status = "running"
    elif identity_verified:
        status = "degraded"
    elif any(item.get("responded") for item in (local, health, ready)):
        status = "port_conflict"
    else:
        status = "not_running"
    return {
        "schema_id": "eve_oss_phoenix_runtime_status.v1",
        "checked_at": utc_now(),
        "status": status,
        "url": base_url,
        "server_identity": "phoenix" if identity_verified else "other_http_service" if status == "port_conflict" else "none",
        "server_identity_verified": identity_verified,
        "local_url_status": local,
        "health_url_status": health,
        "ready_url_status": ready,
        "currently_running": status == "running",
        "observational_only": True,
    }


def langfuse_runtime_status(url: str = DEFAULT_LANGFUSE_URL) -> Dict[str, Any]:
    """Describe the Langfuse service reachable now without probing installers."""

    base_url = url.rstrip("/")
    local = url_status(base_url, timeout=1.0)
    health = url_status(
        f"{base_url}/api/public/health?failIfDatabaseUnavailable=true",
        timeout=1.0,
    )
    ready = url_status(f"{base_url}/api/public/ready", timeout=1.0)
    health_json = health.get("body_json") if isinstance(health.get("body_json"), dict) else {}
    health_status = str(health_json.get("status") or "").strip().lower()
    identity_verified = bool(
        health_json
        and "status" in health_json
        and health_status in {"ok", "healthy", "ready", "unhealthy", "error", "degraded"}
    )
    if identity_verified and health.get("reachable") and ready.get("reachable"):
        status = "running"
    elif identity_verified:
        status = "degraded"
    elif any(item.get("responded") for item in (local, health, ready)):
        status = "port_conflict"
    else:
        status = "not_running"
    return {
        "schema_id": "eve_oss_langfuse_runtime_status.v1",
        "checked_at": utc_now(),
        "status": status,
        "url": base_url,
        "server_identity": "langfuse" if identity_verified else "other_http_service" if status == "port_conflict" else "none",
        "server_identity_verified": identity_verified,
        "local_url_status": local,
        "health_url_status": health,
        "ready_url_status": ready,
        "currently_running": status == "running",
        "observational_only": True,
    }


def service_runtime_status(
    *,
    phoenix_url: Optional[str] = None,
    langfuse_url: str = DEFAULT_LANGFUSE_URL,
) -> Dict[str, Any]:
    """Return current service truth, independently of historical preflights."""

    return {
        "schema_id": "eve_oss_service_runtime_status.v1",
        "checked_at": utc_now(),
        "phoenix": phoenix_runtime_status(phoenix_url),
        "langfuse": langfuse_runtime_status(langfuse_url),
        "observational_only": True,
        "starts_services": False,
    }


def cleanup_new_phoenix_sqlite_artifacts(working_dir: Path, before: set[str]) -> List[str]:
    removed: List[str] = []
    for path in working_dir.glob("phoenix.db*"):
        resolved = str(path.resolve())
        if resolved in before:
            continue
        try:
            path.unlink()
            removed.append(str(path))
        except OSError:
            continue
    return removed


def phoenix_preflight(run_server: bool = False, timeout_seconds: int = 20, port: int = DEFAULT_PHOENIX_PORT, working_dir: Optional[Path] = None) -> Dict[str, Any]:
    working_dir = (working_dir or DEFAULT_PHOENIX_WORKING_DIR).expanduser()
    executable = resolve_executable("phoenix")
    result: Dict[str, Any] = {
        "schema_id": "eve_oss_lab_phoenix_preflight.v1",
        "generated_at": utc_now(),
        "status": "missing_cli",
        "package_version": package_version("arize-phoenix"),
        "executable": executable,
        "server_attempted": run_server,
        "url": f"http://127.0.0.1:{port}",
        "working_dir": str(working_dir),
        "lab_only": True,
        "grants_live_authority": False,
    }
    if not executable:
        result["safe_next_step"] = (
            "Run `UV_PROJECT_ENVIRONMENT=.venv uv sync --extra dev --extra infra "
            "--extra oss-lab --inexact` before attempting Phoenix. Keep the incompatible "
            "techlab extra in `.venv-techlab`."
        )
        return result

    help_result = run_command([executable, "--help"], timeout=25)
    result["cli_help"] = help_result
    if help_result["status"] != "ok":
        result["status"] = "cli_error"
        result["safe_next_step"] = (
            "Treat Phoenix UI boot as blocked on this Python/dependency path; use the JSON trace workbench "
            "or a supervised Langfuse lab until NumPy/PyArrow imports have a fresh local proof."
        )
        return result
    if not run_server:
        result["status"] = "cli_ready"
        result["safe_next_step"] = "Run with `--preflight-phoenix-server` when ready to test a bounded local UI boot."
        return result

    working_dir.mkdir(parents=True, exist_ok=True)
    before = {str(path.resolve()) for path in working_dir.glob("phoenix.db*")}
    log_path = working_dir / "phoenix_preflight.log"
    env = os.environ.copy()
    env.update(
        {
            "PHOENIX_HOST": "127.0.0.1",
            "PHOENIX_PORT": str(port),
            "PHOENIX_WORKING_DIR": str(working_dir.resolve()),
            "PHOENIX_SQL_DATABASE_URL": f"sqlite:///{(working_dir / 'phoenix.db').resolve()}",
            "PHOENIX_TELEMETRY_ENABLED": "false",
            "PHOENIX_ALLOW_EXTERNAL_RESOURCES": "false",
        }
    )
    ready = False
    started = False
    proc: Optional[subprocess.Popen[str]] = None
    with log_path.open("w", encoding="utf-8") as log_file:
        try:
            proc = subprocess.Popen([executable, "serve"], stdout=log_file, stderr=subprocess.STDOUT, text=True, env=env)
            started = True
            deadline = time.monotonic() + max(1, timeout_seconds)
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    break
                if url_status(result["url"], timeout=0.75)["reachable"]:
                    ready = True
                    break
                time.sleep(0.5)
        except FileNotFoundError:
            result["status"] = "missing_cli"
        finally:
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
    log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    removed = cleanup_new_phoenix_sqlite_artifacts(working_dir, before)
    result.update(
        {
            "status": "server_ready" if ready else ("server_timeout" if started else result["status"]),
            "preflight_passed": bool(ready),
            "service_left_running": False,
            "process_returncode": proc.returncode if proc else None,
            "log_path": str(log_path),
            "log_tail": text_tail(log_text),
            "removed_sqlite_artifacts": removed,
            "safe_next_step": (
                "Import one local trace export into the Phoenix UI in a supervised lab run."
                if ready
                else "Treat Phoenix UI boot as blocked or slow on this Python/runtime path; use the JSON workbench or test Langfuse next."
            ),
        }
    )
    return result


def langfuse_preflight(url: str = DEFAULT_LANGFUSE_URL) -> Dict[str, Any]:
    sdk_environment = probe_inventory_environment(
        [
            {
                "id": "langfuse",
                "distribution": "langfuse",
                "import_name": "langfuse",
            }
        ]
    )
    sdk_probe = (
        sdk_environment.get("tools", {}).get("langfuse", {})
        if isinstance(sdk_environment.get("tools"), dict)
        else {}
    )
    sdk_version = str(sdk_probe.get("version") or "")
    docker = run_command(["docker", "--version"], timeout=5)
    compose = run_command(["docker", "compose", "version"], timeout=5)
    runtime = langfuse_runtime_status(url)
    base_url = str(runtime.get("url") or url.rstrip("/"))
    local = runtime["local_url_status"]
    health = runtime["health_url_status"]
    ready = runtime["ready_url_status"]
    identity_verified = bool(runtime.get("server_identity_verified"))
    docker_ready = docker["status"] == "ok" and compose["status"] == "ok"
    sdk_ready = bool(sdk_version) and bool(sdk_probe.get("importable"))
    if runtime.get("status") == "running":
        status = "server_ready"
    elif runtime.get("status") == "degraded":
        status = "server_degraded"
    elif runtime.get("status") == "port_conflict":
        status = "port_conflict"
    else:
        status = "ready_to_start" if sdk_ready and docker_ready else "blocked"
    return {
        "schema_id": "eve_oss_lab_langfuse_preflight.v1",
        "generated_at": utc_now(),
        "status": status,
        "sdk_version": sdk_version,
        "sdk_importable": bool(sdk_probe.get("importable")),
        "sdk_probe_python": sdk_environment.get("python_executable") or "",
        "sdk_probe_status": sdk_environment.get("status") or "unknown",
        "docker": docker,
        "docker_compose": compose,
        "local_url": url,
        "local_url_status": local,
        "health_url_status": health,
        "ready_url_status": ready,
        "runtime_status": runtime,
        "server_identity": "langfuse" if identity_verified else "other_http_service" if local.get("responded") else "none",
        "server_identity_verified": identity_verified,
        "port_conflict": status == "port_conflict",
        "lab_only": True,
        "grants_live_authority": False,
        "safe_next_step": (
            "Use a supervised Docker Compose lab stack only if Phoenix remains blocked and local traces need a UI."
            if status == "ready_to_start"
            else "Inspect the already-running local Langfuse stack."
            if status == "server_ready"
            else "The Langfuse health endpoint responded but readiness did not pass; inspect the local stack before sending traces."
            if status == "server_degraded"
            else f"{base_url} is occupied by a different HTTP service. Choose a separate loopback port before starting Langfuse."
            if status == "port_conflict"
            else "Install/start Docker Desktop before considering a local Langfuse stack."
        ),
    }


def parse_uv_dry_run(output: str) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "would_download_count": 0,
        "would_install_count": 0,
        "would_uninstall_count": 0,
        "would_install": [],
        "would_uninstall": [],
    }
    for field, pattern in (
        ("would_download_count", r"Would download (\d+) packages?"),
        ("would_install_count", r"Would install (\d+) packages?"),
        ("would_uninstall_count", r"Would uninstall (\d+) packages?"),
    ):
        match = re.search(pattern, output)
        if match:
            summary[field] = int(match.group(1))
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("+ "):
            summary["would_install"].append(stripped[2:])
        elif stripped.startswith("- "):
            summary["would_uninstall"].append(stripped[2:])
    return summary


def run_uv_resolver_dry_run(command: List[str], timeout: int) -> Dict[str, Any]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError:
        return {
            "status": "missing",
            "command": command,
            "returncode": None,
            "stdout_tail": "",
            "stderr_tail": "command not found",
            **parse_uv_dry_run(""),
        }
    except subprocess.TimeoutExpired as exc:
        combined = f"{exc.stdout or ''}\n{exc.stderr or ''}"
        return {
            "status": "timeout",
            "command": command,
            "returncode": None,
            "stdout_tail": text_tail(exc.stdout or ""),
            "stderr_tail": text_tail(exc.stderr or ""),
            **parse_uv_dry_run(combined),
        }
    combined = f"{completed.stdout or ''}\n{completed.stderr or ''}"
    return {
        "status": "ok" if completed.returncode == 0 else "error",
        "command": command,
        "returncode": completed.returncode,
        "stdout_tail": text_tail(completed.stdout or ""),
        "stderr_tail": text_tail(completed.stderr or ""),
        **parse_uv_dry_run(combined),
    }


def trainer_lab_envs(lab_root: Optional[Path] = None, verify: bool = False) -> List[Dict[str, Any]]:
    lab_root = (lab_root or DEFAULT_TRAINER_LAB_ROOT).expanduser()
    known_envs = [
        {
            "id": "llamafactory",
            "name": "llamafactory-py313",
            "expected_cli": "llamafactory-cli",
            "verify_args": ["version"],
            "distribution": "llamafactory",
            "source_subdir": "LLaMA-Factory",
            "framework": "torch",
        },
        {
            "id": "unsloth",
            "name": "unsloth-studio-py313",
            "expected_cli": "unsloth",
            "verify_args": ["--help"],
            "distribution": "unsloth",
            "source_subdir": "",
            "framework": "torch",
        },
        {
            "id": "mlx_lm",
            "names": ["mlx-lm-py314", "mlx-lm-py313"],
            "expected_cli": "mlx_lm.lora",
            "verify_args": ["--help"],
            "distribution": "mlx-lm",
            "source_subdir": "",
            "framework": "mlx",
            "env_overrides": TRAINER_THREAD_LIMIT_ENV,
        },
    ]
    envs: List[Dict[str, Any]] = []
    for env in known_envs:
        candidate_names = list(env.get("names") or [env["name"]])
        candidate_paths = [lab_root / "trainer-venvs" / name for name in candidate_names]
        venv_path = next(
            (
                path
                for path in candidate_paths
                if (path / "bin" / "python").exists()
                and (path / "bin" / env["expected_cli"]).exists()
            ),
            candidate_paths[0],
        )
        source_path = lab_root / "sources" / env["source_subdir"] if env.get("source_subdir") else None
        python_path = venv_path / "bin" / "python"
        cli_path = venv_path / "bin" / env["expected_cli"]
        record: Dict[str, Any] = {
            "id": env["id"],
            "name": venv_path.name,
            "candidate_names": candidate_names,
            "status": "installed" if python_path.exists() and cli_path.exists() else "missing",
            "venv_path": str(venv_path),
            "source_path": str(source_path) if source_path else "",
            "python_exists": python_path.exists(),
            "cli_exists": cli_path.exists(),
            "main_venv_safe": False,
            "lab_only": True,
        }
        if verify and record["status"] == "installed":
            check_env = merged_env(env.get("env_overrides"))
            record["required_env"] = env.get("env_overrides", {})
            record["cli_version_check"] = run_command([str(cli_path), *env["verify_args"]], timeout=30, env=check_env)
            if env.get("framework") == "mlx":
                record["framework_check"] = run_command(
                    [
                        str(python_path),
                        "-c",
                        "import importlib.metadata, mlx.core as mx; "
                        "from mlx_lm import utils; import mlx_lm.lora; "
                        f"print('{env['distribution']}=' + importlib.metadata.version('{env['distribution']}')); "
                        "print('mlx=' + importlib.metadata.version('mlx')); "
                        "print('numpy=' + importlib.metadata.version('numpy')); "
                        "print('pyarrow=' + importlib.metadata.version('pyarrow')); "
                        "print('safetensors=' + importlib.metadata.version('safetensors')); "
                        "print('default_device=' + str(mx.default_device()))",
                    ],
                    timeout=30,
                    env=check_env,
                )
            else:
                record["framework_check"] = run_command(
                    [
                        str(python_path),
                        "-c",
                        "import importlib.metadata, torch; "
                        f"print('{env['distribution']}=' + importlib.metadata.version('{env['distribution']}')); "
                        "print('torch=' + torch.__version__); "
                        "print('mps_available=' + str(torch.backends.mps.is_available()))",
                    ],
                    timeout=30,
                    env=check_env,
                )
                record["torch_check"] = record["framework_check"]
            record["status"] = (
                "verified"
                if record["cli_version_check"]["status"] == "ok" and record["framework_check"]["status"] == "ok"
                else "needs_attention"
            )
        envs.append(record)
    return envs


def trainer_candidate_preflight(run_dry_run: bool = False, dry_run_timeout: int = 60, verify_envs: bool = False) -> Dict[str, Any]:
    current_python = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    machine = platform.machine()
    system = platform.system()
    uv = shutil.which("uv") or ""
    candidates: List[Dict[str, Any]] = [
        {
            "id": "peft",
            "status": "installed_lab",
            "main_venv_safe": True,
            "reason": "PEFT is already installed as Eve's lightweight adapter-training library.",
            "distribution": "peft",
            "version": package_version("peft"),
        },
        {
            "id": "axolotl",
            "status": "isolate_before_install",
            "main_venv_safe": False,
            "reason": "Axolotl is a heavy trainer stack; keep it out of Eve's main runtime venv unless an isolated trainer venv passes resolver and hardware gates.",
            "distribution": "axolotl",
        },
        {
            "id": "llamafactory",
            "status": "isolate_before_install",
            "main_venv_safe": False,
            "reason": "LLaMA-Factory brings web UI, trainer, Torch, and metric dependencies that should not rewrite Eve's main runtime environment.",
            "distribution": "llamafactory",
        },
        {
            "id": "unsloth",
            "status": "python_version_blocked_in_main_venv",
            "main_venv_safe": False,
            "reason": f"Eve's main venv is Python {current_python}; use a Python 3.11-3.13 isolated trainer env before testing Unsloth.",
            "distribution": "unsloth",
        },
        {
            "id": "mlx_lm",
            "status": "isolated_lab_preferred",
            "main_venv_safe": False,
            "reason": "MLX-LM is Apple Silicon native and is installed in an isolated Python 3.13 lab with thread-limit env guards so trainer dependencies do not destabilize Eve's main runtime.",
            "distribution": "mlx-lm",
        },
    ]
    if run_dry_run and uv:
        for candidate in candidates:
            if candidate["id"] == "peft":
                continue
            command = [
                uv,
                "pip",
                "install",
                "--dry-run",
                "--python-version",
                "3.13",
                "--python-platform",
                "aarch64-apple-darwin",
                "--no-python-downloads",
                candidate["distribution"],
            ]
            candidate["resolver_dry_run"] = run_uv_resolver_dry_run(command, timeout=dry_run_timeout)
            if candidate["resolver_dry_run"].get("would_uninstall_count", 0):
                candidate["reason"] += " The resolver would uninstall or replace main-runtime packages if run against the shared environment."
    return {
        "schema_id": "eve_oss_lab_trainer_candidate_preflight.v1",
        "generated_at": utc_now(),
        "status": "isolated_env_required",
        "current_python": current_python,
        "platform": {"system": system, "machine": machine},
        "commands": {
            "uv": bool(uv),
            "git": bool(shutil.which("git")),
            "docker": bool(shutil.which("docker")),
            "nvidia_smi": bool(shutil.which("nvidia-smi")),
            "nvcc": bool(shutil.which("nvcc")),
        },
        "dry_run_performed": run_dry_run and bool(uv),
        "recommended_install_root": str(DEFAULT_TRAINER_LAB_ROOT / "trainer-venvs"),
        "isolated_envs": trainer_lab_envs(verify=verify_envs),
        "verify_envs_performed": verify_envs,
        "candidates": candidates,
        "boundary": {
            "lab_only": True,
            "grants_live_authority": False,
            "writes_eve_memory": False,
            "promotes_models": False,
        },
        "safe_next_step": "Create one isolated Python 3.13 trainer venv outside the iCloud-backed checkout, then install exactly one trainer candidate at a time.",
    }


def service_preflight(run_phoenix_server: bool = False, phoenix_timeout_seconds: int = 20, phoenix_port: int = DEFAULT_PHOENIX_PORT, phoenix_working_dir: Optional[Path] = None) -> Dict[str, Any]:
    return {
        "schema_id": "eve_oss_lab_service_preflight.v1",
        "generated_at": utc_now(),
        "phoenix": phoenix_preflight(
            run_server=run_phoenix_server,
            timeout_seconds=phoenix_timeout_seconds,
            port=phoenix_port,
            working_dir=phoenix_working_dir,
        ),
        "langfuse": langfuse_preflight(),
    }


def build_report(
    trace_path: Optional[Path] = None,
    run_phoenix_server: bool = False,
    phoenix_timeout_seconds: int = 20,
    phoenix_port: int = DEFAULT_PHOENIX_PORT,
    phoenix_working_dir: Optional[Path] = None,
    trainer_dry_run: bool = False,
    verify_trainer_envs: bool = False,
    training_dataset_dir: Optional[Path] = None,
    trainer_recipe_dir: Optional[Path] = None,
    write_trainer_recipes: bool = False,
) -> Dict[str, Any]:
    return {
        "schema_id": "eve_oss_lab_report.v1",
        "generated_at": utc_now(),
        "inventory": build_inventory(),
        "trace_workbench": trace_workbench(trace_path or DEFAULT_TRACE_EXPORT),
        "service_preflight": service_preflight(
            run_phoenix_server=run_phoenix_server,
            phoenix_timeout_seconds=phoenix_timeout_seconds,
            phoenix_port=phoenix_port,
            phoenix_working_dir=phoenix_working_dir,
        ),
        "trainer_candidate_preflight": trainer_candidate_preflight(
            run_dry_run=trainer_dry_run,
            verify_envs=verify_trainer_envs,
        ),
        "trainer_recipe_plan": trainer_recipe_plan(
            dataset_dir=training_dataset_dir,
            output_dir=trainer_recipe_dir,
            write=write_trainer_recipes,
        ),
    }


def write_json(path: Path, payload: Dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


def print_summary(report: Dict[str, Any]) -> None:
    inventory = report["inventory"]
    trace = report["trace_workbench"]
    service = report["service_preflight"]
    trainers = report["trainer_candidate_preflight"]
    print(f"Eve OSS lab: inventory={inventory['status']} trace={trace['status']}")
    print(f"installed_importable: {inventory['installed_importable_count']}/{inventory['tool_count']}")
    print(f"trace_records: {trace['record_count']} kinds={trace['kind_counts']}")
    print(f"phoenix: {service['phoenix']['status']} langfuse: {service['langfuse']['status']}")
    print(f"trainers: {trainers['status']} dry_run={trainers['dry_run_performed']}")
    print(f"trainer_recipes: {report['trainer_recipe_plan']['status']} write={report['trainer_recipe_plan']['write_performed']}")
    gated = inventory.get("gated_tools") or []
    if gated:
        print("gated_tools: " + ", ".join(str(tool["id"]) for tool in gated))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect Eve's OSS lab tool admission and local trace workbench readiness.")
    parser.add_argument("--trace-jsonl", default=str(DEFAULT_TRACE_EXPORT), help="OpenInference JSONL trace export to inspect.")
    parser.add_argument("--output", default=str(DEFAULT_REPORT_PATH), help="JSON report output path.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a compact summary.")
    parser.add_argument("--no-write", action="store_true", help="Do not write the report artifact.")
    parser.add_argument("--preflight-phoenix-server", action="store_true", help="Attempt a bounded local Phoenix server boot, then stop it.")
    parser.add_argument("--phoenix-timeout", type=int, default=20, help="Seconds to wait for bounded Phoenix server readiness.")
    parser.add_argument("--phoenix-port", type=int, default=DEFAULT_PHOENIX_PORT, help="Local Phoenix port for the bounded server preflight.")
    parser.add_argument("--phoenix-working-dir", default=str(DEFAULT_PHOENIX_WORKING_DIR), help="Phoenix preflight working directory.")
    parser.add_argument("--trainer-dry-run", action="store_true", help="Run uv resolver dry-runs for gated trainer candidates without installing them.")
    parser.add_argument("--verify-trainer-envs", action="store_true", help="Run CLI/import verification for installed isolated trainer lab environments.")
    parser.add_argument("--training-dataset-dir", default=str(DEFAULT_TRAINING_DATASET_DIR), help="Curated Eve training dataset directory.")
    parser.add_argument("--trainer-recipe-dir", default=str(DEFAULT_TRAINER_RECIPE_DIR), help="Output directory for no-training trainer recipes.")
    parser.add_argument("--write-trainer-recipes", action="store_true", help="Write no-training trainer recipes over the curated dataset shape.")
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_report(
        Path(args.trace_jsonl).expanduser(),
        run_phoenix_server=args.preflight_phoenix_server,
        phoenix_timeout_seconds=args.phoenix_timeout,
        phoenix_port=args.phoenix_port,
        phoenix_working_dir=Path(args.phoenix_working_dir).expanduser(),
        trainer_dry_run=args.trainer_dry_run,
        verify_trainer_envs=args.verify_trainer_envs,
        training_dataset_dir=Path(args.training_dataset_dir).expanduser(),
        trainer_recipe_dir=Path(args.trainer_recipe_dir).expanduser(),
        write_trainer_recipes=args.write_trainer_recipes,
    )
    if not args.no_write:
        write_json(Path(args.output).expanduser(), report)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True))
    else:
        print_summary(report)
    trace_status = report["trace_workbench"]["status"]
    return 0 if trace_status in {"ready", "empty", "missing"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
