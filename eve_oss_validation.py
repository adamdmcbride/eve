#!/usr/bin/env python3
"""Executable local validation for Eve's dataset and adapter workbench.

This module deliberately owns no scheduler, memory, routing, or promotion
authority.  It turns two previously shallow readiness labels into evidence:

* a DVC snapshot whose train/validation payload can be restored from cache;
* an MLX-LM ``--test`` pass that loads a local model and public validation rows
  without passing ``--train`` or loading an adapter.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


DVC_SNAPSHOT_SCHEMA_ID = "eve_oss_dvc_training_snapshot.v2"
MLX_VALIDATION_SCHEMA_ID = "eve_oss_mlx_no_train_validation.v1"
DISALLOWED_TRAINING_PRIVACY_TIERS = {
    "hidden",
    "hidden_probe",
    "private",
    "private_holdout",
    "secret_holdout",
}
THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "TOKENIZERS_PARALLELISM": "false",
}

CommandRunner = Callable[..., Dict[str, object]]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: int,
    env: Optional[Mapping[str, str]] = None,
) -> Dict[str, object]:
    started_at = utc_now()
    process_env = os.environ.copy()
    process_env.update({str(key): str(value) for key, value in (env or {}).items()})
    try:
        process = subprocess.Popen(
            [str(value) for value in command],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=process_env,
            start_new_session=True,
        )
    except OSError as exc:
        return {
            "status": "error",
            "returncode": None,
            "started_at": started_at,
            "finished_at": utc_now(),
            "stdout_tail": "",
            "stderr_tail": str(exc)[-1000:],
        }
    try:
        stdout, stderr = process.communicate(timeout=max(1, int(timeout)))
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except OSError:
            process.kill()
        try:
            stdout, stderr = process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                process.kill()
            stdout, stderr = process.communicate()
        return {
            "status": "timeout",
            "returncode": None,
            "started_at": started_at,
            "finished_at": utc_now(),
            "stdout_tail": (stdout or "")[-2000:],
            "stderr_tail": (stderr or "")[-2000:],
        }
    return {
        "status": "ok" if process.returncode == 0 else "error",
        "returncode": process.returncode,
        "started_at": started_at,
        "finished_at": utc_now(),
        "stdout_tail": (stdout or "")[-4000:],
        "stderr_tail": (stderr or "")[-4000:],
    }


def read_training_rows(path: Path) -> Tuple[List[Dict[str, object]], List[str]]:
    rows: List[Dict[str, object]] = []
    blockers: List[str] = []
    if not path.exists():
        return rows, [f"missing:{path.name}"]
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                blockers.append(f"invalid_json:{path.name}:{line_number}")
                continue
            if not isinstance(row, dict):
                blockers.append(f"non_object:{path.name}:{line_number}")
                continue
            split = str(row.get("split") or "").strip().lower()
            privacy = str(row.get("privacy_tier") or "").strip().lower()
            if split in DISALLOWED_TRAINING_PRIVACY_TIERS or privacy in DISALLOWED_TRAINING_PRIVACY_TIERS:
                blockers.append(f"disallowed_private_row:{path.name}:{line_number}")
            if row.get("safe_for_training") is False:
                blockers.append(f"unsafe_training_row:{path.name}:{line_number}")
            rows.append(row)
    if not rows:
        blockers.append(f"empty:{path.name}")
    return rows, blockers


def training_file_summary(path: Path) -> Dict[str, object]:
    rows, blockers = read_training_rows(path)
    return {
        "name": path.name,
        "path": str(path),
        "exists": path.exists(),
        "row_count": len(rows),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "sha256": file_sha256(path) if path.exists() else "",
        "blockers": blockers,
        "contains_row_text": False,
    }


def build_dvc_snapshot_manifest(dataset_dir: Path) -> Dict[str, object]:
    train = training_file_summary(dataset_dir / "latest_train.jsonl")
    validation = training_file_summary(dataset_dir / "latest_validation.jsonl")
    blockers = [
        str(blocker)
        for record in (train, validation)
        for blocker in record.get("blockers") or []
    ]
    identity = {
        "schema_id": DVC_SNAPSHOT_SCHEMA_ID,
        "train": {key: train.get(key) for key in ("row_count", "size_bytes", "sha256")},
        "validation": {key: validation.get(key) for key in ("row_count", "size_bytes", "sha256")},
        "private_holdout_included": False,
    }
    snapshot_id = stable_hash(identity)[:20]
    return {
        "schema_id": DVC_SNAPSHOT_SCHEMA_ID,
        "created_at": utc_now(),
        "status": "ready" if not blockers else "blocked",
        "snapshot_id": snapshot_id,
        "content_fingerprint": stable_hash(identity),
        "files": [train, validation],
        "split_counts": {
            "train": train.get("row_count", 0),
            "validation": validation.get("row_count", 0),
        },
        "blockers": sorted(set(blockers)),
        "privacy": {
            "private_holdout_included": False,
            "hidden_probe_material_included": False,
            "row_text_in_manifest": False,
            "payload_is_local_only": True,
        },
    }


def prepare_dvc_payload(dataset_dir: Path, payload_dir: Path) -> Dict[str, object]:
    manifest = build_dvc_snapshot_manifest(dataset_dir)
    if manifest["status"] != "ready":
        return manifest
    payload_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = payload_dir.parent / f".{payload_dir.name}.staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    try:
        shutil.copyfile(dataset_dir / "latest_train.jsonl", staging / "train.jsonl")
        shutil.copyfile(dataset_dir / "latest_validation.jsonl", staging / "validation.jsonl")
        (staging / "snapshot_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        copied = {
            "train": file_sha256(staging / "train.jsonl"),
            "validation": file_sha256(staging / "validation.jsonl"),
        }
        expected = {
            "train": manifest["files"][0]["sha256"],
            "validation": manifest["files"][1]["sha256"],
        }
        if copied != expected:
            manifest["status"] = "blocked"
            manifest["blockers"] = ["payload_copy_hash_mismatch"]
            return manifest
        previous = payload_dir.parent / f".{payload_dir.name}.previous-{uuid.uuid4().hex}"
        if payload_dir.exists():
            os.replace(payload_dir, previous)
        os.replace(staging, payload_dir)
        if previous.exists():
            shutil.rmtree(previous)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    manifest["payload_dir"] = str(payload_dir)
    manifest["payload_files"] = ["train.jsonl", "validation.jsonl", "snapshot_manifest.json"]
    return manifest


def _dvc_environment(site_cache_dir: Path) -> Dict[str, str]:
    return {
        "DVC_NO_ANALYTICS": "1",
        "DVC_SITE_CACHE_DIR": str(site_cache_dir),
        "PYTHONNOUSERSITE": "1",
    }


def perform_dvc_snapshot_restore(
    *,
    dataset_dir: Path,
    payload_dir: Path,
    repo_root: Path,
    dvc_executable: Path,
    timeout: int = 45,
    runner: CommandRunner = run_command,
) -> Dict[str, object]:
    manifest = prepare_dvc_payload(dataset_dir, payload_dir)
    report: Dict[str, object] = {
        "schema_id": DVC_SNAPSHOT_SCHEMA_ID,
        "checked_at": utc_now(),
        "status": "blocked",
        "snapshot": manifest,
        "dvc_executable": str(dvc_executable),
        "commands": {},
        "restore": {},
        "boundary": {
            "local_only": True,
            "remote_upload": False,
            "private_holdout_included": False,
            "changes_live_routing": False,
            "writes_eve_memory": False,
        },
    }
    if manifest.get("status") != "ready":
        report["blockers"] = list(manifest.get("blockers") or [])
        return report
    if not dvc_executable.exists():
        report["blockers"] = ["dvc_executable_missing"]
        return report
    site_cache = repo_root / ".dvc" / "tmp" / "eve_validation_site_cache"
    site_cache.mkdir(parents=True, exist_ok=True)
    env = _dvc_environment(site_cache)
    status_before = runner([str(dvc_executable), "status"], cwd=repo_root, timeout=timeout, env=env)
    report["commands"]["status_before"] = status_before
    if status_before.get("status") != "ok":
        report["blockers"] = ["dvc_status_failed"]
        return report
    relative_payload = payload_dir.relative_to(repo_root)
    add = runner([str(dvc_executable), "add", str(relative_payload)], cwd=repo_root, timeout=timeout, env=env)
    report["commands"]["add"] = add
    sidecar = Path(str(payload_dir) + ".dvc")
    if add.get("status") != "ok" or not sidecar.exists():
        report["blockers"] = ["dvc_add_failed" if add.get("status") != "ok" else "dvc_sidecar_missing"]
        return report
    status_after = runner(
        [str(dvc_executable), "status", str(sidecar.relative_to(repo_root))],
        cwd=repo_root,
        timeout=timeout,
        env=env,
    )
    report["commands"]["status_after"] = status_after
    if status_after.get("status") != "ok":
        report["blockers"] = ["dvc_status_after_add_failed"]
        return report

    with tempfile.TemporaryDirectory(prefix="eve-dvc-restore-") as tmp:
        restore_root = Path(tmp)
        restore_env = _dvc_environment(restore_root / "site-cache")
        init = runner([str(dvc_executable), "init", "--no-scm"], cwd=restore_root, timeout=timeout, env=restore_env)
        report["commands"]["restore_init"] = init
        if init.get("status") != "ok":
            report["blockers"] = ["dvc_restore_repo_init_failed"]
            return report
        cache_dir = repo_root / ".dvc" / "cache"
        config = runner(
            [str(dvc_executable), "config", "cache.dir", str(cache_dir)],
            cwd=restore_root,
            timeout=timeout,
            env=restore_env,
        )
        report["commands"]["restore_cache_config"] = config
        if config.get("status") != "ok":
            report["blockers"] = ["dvc_restore_cache_config_failed"]
            return report
        restore_sidecar = restore_root / sidecar.name
        shutil.copyfile(sidecar, restore_sidecar)
        checkout = runner(
            [str(dvc_executable), "checkout", restore_sidecar.name],
            cwd=restore_root,
            timeout=timeout,
            env=restore_env,
        )
        report["commands"]["restore_checkout"] = checkout
        restored = restore_root / payload_dir.name
        restored_manifest_path = restored / "snapshot_manifest.json"
        if checkout.get("status") != "ok" or not restored_manifest_path.exists():
            report["blockers"] = ["dvc_restore_checkout_failed"]
            return report
        restored_manifest = json.loads(restored_manifest_path.read_text(encoding="utf-8"))
        restored_hashes = {
            "train": file_sha256(restored / "train.jsonl"),
            "validation": file_sha256(restored / "validation.jsonl"),
        }
        expected_hashes = {
            "train": manifest["files"][0]["sha256"],
            "validation": manifest["files"][1]["sha256"],
        }
        restore_ok = bool(
            restored_hashes == expected_hashes
            and restored_manifest.get("content_fingerprint") == manifest.get("content_fingerprint")
        )
        report["restore"] = {
            "verified": restore_ok,
            "snapshot_id": restored_manifest.get("snapshot_id"),
            "content_fingerprint": restored_manifest.get("content_fingerprint"),
            "hashes_match": restored_hashes == expected_hashes,
            "row_text_in_report": False,
        }
    report["sidecar"] = str(sidecar)
    report["status"] = "verified" if report["restore"].get("verified") else "blocked"
    report["blockers"] = [] if report["status"] == "verified" else ["dvc_restore_hash_mismatch"]
    return report


def mlx_chat_record(row: Mapping[str, object]) -> Dict[str, object]:
    prompt = str(row.get("prompt") or "").strip()
    preferred = str(row.get("preferred_response") or "").strip()
    if not prompt or not preferred:
        raise ValueError("row_missing_prompt_or_preferred_response")
    context = row.get("available_context") if isinstance(row.get("available_context"), dict) else {}
    evidence = row.get("tool_action_evidence") if isinstance(row.get("tool_action_evidence"), dict) else {}
    user = (
        f"Prompt: {prompt}\n"
        f"Available context: {json.dumps(context, ensure_ascii=True, sort_keys=True)}\n"
        f"Tool/action evidence: {json.dumps(evidence, ensure_ascii=True, sort_keys=True)}"
    )
    return {
        "messages": [
            {
                "role": "system",
                "content": "You are Eve. Answer from supplied evidence without inventing state or action.",
            },
            {"role": "user", "content": user},
            {"role": "assistant", "content": preferred},
        ]
    }


def _write_mlx_test_data(validation_path: Path, data_dir: Path, limit: int) -> Dict[str, object]:
    rows, blockers = read_training_rows(validation_path)
    if blockers:
        return {"status": "blocked", "blockers": blockers, "row_count": len(rows)}
    selected = rows[: max(1, int(limit))]
    converted: List[Dict[str, object]] = []
    conversion_blockers: List[str] = []
    for index, row in enumerate(selected, start=1):
        try:
            converted.append(mlx_chat_record(row))
        except ValueError as exc:
            conversion_blockers.append(f"row_{index}:{exc}")
    if conversion_blockers or not converted:
        return {"status": "blocked", "blockers": conversion_blockers or ["no_convertible_rows"]}
    data_dir.mkdir(parents=True, exist_ok=True)
    test_path = data_dir / "test.jsonl"
    test_path.write_text(
        "".join(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n" for row in converted),
        encoding="utf-8",
    )
    return {
        "status": "ready",
        "test_path": str(test_path),
        "row_count": len(converted),
        "sha256": file_sha256(test_path),
        "contains_private_holdout": False,
        "contains_row_text_in_report": False,
    }


def _mlx_environment_limited(result: Mapping[str, object]) -> bool:
    text = f"{result.get('stdout_tail') or ''}\n{result.get('stderr_tail') or ''}".lower()
    return any(
        marker in text
        for marker in (
            "no metal device available",
            "metal::load_device",
            "headless, sandboxed, or virtualized",
            "operation not permitted",
        )
    )


def perform_mlx_no_train_validation(
    *,
    validation_path: Path,
    model_path: Path,
    trainer_cli: Path,
    timeout: int = 180,
    row_limit: int = 6,
    runner: CommandRunner = run_command,
) -> Dict[str, object]:
    report: Dict[str, object] = {
        "schema_id": MLX_VALIDATION_SCHEMA_ID,
        "checked_at": utc_now(),
        "status": "blocked",
        "model_path": str(model_path),
        "trainer_cli": str(trainer_cli),
        "no_train_validation_performed": False,
        "blockers": [],
        "boundary": {
            "no_download": True,
            "no_training_started": True,
            "adapter_loaded": False,
            "adapter_written": False,
            "private_holdout_used": False,
            "writes_eve_memory": False,
            "changes_live_routing": False,
        },
    }
    if not model_path.exists():
        report["blockers"] = ["approved_local_base_model_path_missing"]
        return report
    if not trainer_cli.exists():
        report["blockers"] = ["trainer_cli_missing"]
        return report
    with tempfile.TemporaryDirectory(prefix="eve-mlx-no-train-") as tmp:
        workdir = Path(tmp)
        data = _write_mlx_test_data(validation_path, workdir / "data", row_limit)
        report["dataset"] = data
        if data.get("status") != "ready":
            report["blockers"] = list(data.get("blockers") or ["validation_data_blocked"])
            return report
        config_path = workdir / "no_train_validation.yaml"
        config_path.write_text(
            "\n".join(
                [
                    f"model: {json.dumps(str(model_path))}",
                    "train: false",
                    "test: true",
                    "test_batches: 1",
                    f"data: {json.dumps(str(workdir / 'data'))}",
                    'adapter_path: ""',
                    "batch_size: 1",
                    "max_seq_length: 256",
                    "seed: 7",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        command = [str(trainer_cli), "--config", str(config_path)]
        result = runner(
            command,
            cwd=workdir,
            timeout=timeout,
            env={
                **THREAD_ENV,
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "DO_NOT_TRACK": "1",
            },
        )
        report["command"] = command
        report["command_result"] = result
        output = f"{result.get('stdout_tail') or ''}\n{result.get('stderr_tail') or ''}"
        loss_match = re.search(r"Test loss\s+([0-9]+(?:\.[0-9]+)?)", output)
        ppl_match = re.search(r"Test ppl\s+([0-9]+(?:\.[0-9]+)?)", output)
        training_started = bool(re.search(r"(?m)^Training\s*$", output))
        adapter_artifacts = list(workdir.rglob("adapters.safetensors"))
        passed = bool(
            result.get("status") == "ok"
            and loss_match
            and ppl_match
            and "Loading pretrained model" in output
            and "Loading datasets" in output
            and "Testing" in output
            and not training_started
            and not adapter_artifacts
        )
        if passed:
            report.update(
                {
                    "status": "passed",
                    "no_train_validation_performed": True,
                    "metrics": {
                        "test_loss": float(loss_match.group(1)),
                        "test_perplexity": float(ppl_match.group(1)),
                    },
                    "blockers": [],
                }
            )
        elif _mlx_environment_limited(result):
            report.update(
                {
                    "status": "inconclusive_environment",
                    "observation_valid_for_live_downgrade": False,
                    "blockers": ["metal_unavailable_in_current_runner"],
                }
            )
        else:
            report["blockers"] = ["mlx_no_train_validation_failed"]
        report["boundary"]["no_training_started"] = not training_started
        report["boundary"]["adapter_written"] = bool(adapter_artifacts)
    return report
