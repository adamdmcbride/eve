#!/usr/bin/env python3
"""Research-only latent-workspace readout lab for Eve model candidates.

This adapter stages Anthropic's Apache-2.0 ``jacobian-lens`` reference method
without making it a resident lane or treating a readable latent workspace as
evidence of phenomenal consciousness.  It is deliberately local-only and
fail-closed: GGUF serving artifacts do not expose the residual activations the
method needs, model/lens/spec/code drift invalidates a registered run, and the
aggregate report never persists prompts or decoded latent tokens.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable, Sequence


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
STATUS_SCHEMA = "eve.jacobian_workspace_status.v1"
SPEC_SCHEMA = "eve.jacobian_workspace_private_spec.v1"
REGISTRATION_SCHEMA = "eve.jacobian_workspace_registration.v1"
REPORT_SCHEMA = "eve.jacobian_workspace_report.v1"
UPSTREAM_REPOSITORY = "https://github.com/anthropics/jacobian-lens"
UPSTREAM_METHOD = "jacobian_lens"
MINIMUM_CASES = 5
MAX_SPEC_BYTES = 1_000_000
MAX_CONFIG_BYTES = 2_000_000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_regular_file(path: Path | str, *, maximum_bytes: int | None = None) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError("artifact must be an existing non-symlink regular file")
    if maximum_bytes is not None and candidate.stat().st_size > maximum_bytes:
        raise ValueError("artifact exceeds the bounded size limit")
    return candidate.resolve()


def _safe_executable(path: Path | str) -> Path:
    """Validate an interpreter symlink while preserving virtualenv dispatch."""

    candidate = Path(path).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError("interpreter must resolve to an existing executable") from exc
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise ValueError("interpreter must resolve to an existing executable")
    # Executing the resolved target would bypass a virtualenv's symlink-based
    # prefix discovery.  Keep the validated link path for subprocess dispatch.
    return Path(os.path.abspath(candidate))


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", str(value or ""))[:3])


def inspect_model_artifact(path: Path | str) -> dict[str, Any]:
    """Classify a local model without retaining its private filesystem path."""

    candidate = Path(path).expanduser()
    if candidate.is_symlink() or not candidate.exists():
        raise ValueError("model artifact must exist and must not itself be a symlink")
    if candidate.is_file():
        model_format = "gguf" if candidate.suffix.lower() == ".gguf" else "unknown_file"
        return {
            "format": model_format,
            "artifact_name": candidate.name,
            "byte_count": candidate.stat().st_size,
            "activation_access": False,
            "fit_supported": False,
            "apply_supported": False,
            "reason": (
                "gguf_serving_artifact_does_not_expose_residual_activations"
                if model_format == "gguf"
                else "unsupported_model_file"
            ),
            "path_persisted": False,
        }

    config_path = candidate / "config.json"
    weight_files = sorted(
        item for item in candidate.rglob("*.safetensors") if item.is_file()
    )
    gguf_files = sorted(item for item in candidate.rglob("*.gguf") if item.is_file())
    config: dict[str, Any] = {}
    if config_path.is_file() and not config_path.is_symlink():
        if config_path.stat().st_size > MAX_CONFIG_BYTES:
            raise ValueError("model config exceeds the bounded size limit")
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            config = loaded
    quantized = bool(config.get("quantization_config") or config.get("quantization"))
    architectures = [str(item) for item in (config.get("architectures") or [])[:4]]
    decoder_architecture = any(
        name.endswith("ForCausalLM") or name.endswith("ForConditionalGeneration")
        for name in architectures
    )
    hf_decoder = bool(config and weight_files and not gguf_files and decoder_architecture)
    model_format = "huggingface_decoder" if hf_decoder else (
        "gguf_directory" if gguf_files else "unknown_directory"
    )
    byte_count = sum(item.stat().st_size for item in weight_files + gguf_files)
    reason = ""
    if not hf_decoder:
        reason = "local_huggingface_decoder_weights_required"
    elif quantized:
        reason = "quantized_hf_candidate_requires_backend_specific_gradient_canary"
    return {
        "format": model_format,
        "artifact_name": candidate.name,
        "model_type": str(config.get("model_type") or ""),
        "architectures": architectures,
        "weight_file_count": len(weight_files),
        "byte_count": byte_count,
        "quantized": quantized,
        "activation_access": hf_decoder,
        "fit_supported": hf_decoder and not quantized,
        "apply_supported": hf_decoder and not quantized,
        "reason": reason,
        "path_persisted": False,
    }


def _module_version(name: str) -> tuple[bool, str]:
    if importlib.util.find_spec(name) is None:
        return False, ""
    module = __import__(name)
    return True, str(getattr(module, "__version__", "unknown"))


def _module_code_identity(name: str) -> str:
    spec = importlib.util.find_spec(name)
    if spec is None or not spec.origin:
        return ""
    origin = Path(spec.origin)
    root = origin.parent if origin.name == "__init__.py" else origin
    files = (
        sorted(root.rglob("*.py"), key=lambda item: item.relative_to(root).as_posix())
        if root.is_dir()
        else [root]
    )
    digest = hashlib.sha256()
    for item in files:
        if not item.is_file():
            continue
        relative = item.relative_to(root).as_posix() if root.is_dir() else item.name
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with item.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest()


def local_dependency_probe() -> dict[str, Any]:
    packages: dict[str, dict[str, Any]] = {}
    for name in ("torch", "transformers", "huggingface_hub", "jlens"):
        available, version = _module_version(name)
        packages[name] = {"available": available, "version": version}
        if name == "jlens" and available:
            packages[name]["code_sha256"] = _module_code_identity(name)
    devices = {"cuda": False, "mps": False, "cpu": True}
    if packages["torch"]["available"]:
        import torch

        devices["cuda"] = bool(torch.cuda.is_available())
        mps = getattr(getattr(torch, "backends", None), "mps", None)
        devices["mps"] = bool(mps and mps.is_available())
    transformers_ok = packages["transformers"]["available"] and _version_tuple(
        packages["transformers"]["version"]
    ) >= (5, 5)
    return {
        "python": sys.version.split()[0],
        "interpreter_sha256": sha256_file(sys.executable),
        "packages": packages,
        "devices": devices,
        "transformers_minimum_5_5": transformers_ok,
        "apply_dependencies_ready": bool(
            packages["torch"]["available"]
            and packages["transformers"]["available"]
            and packages["huggingface_hub"]["available"]
            and packages["jlens"]["available"]
            and transformers_ok
        ),
        "fit_accelerator_ready": devices["cuda"] or devices["mps"],
    }


def probe_interpreter(
    python_path: Path | str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    interpreter = _safe_executable(python_path)
    command = [str(interpreter), str(SCRIPT), "_dependency-probe"]
    environment = {
        **os.environ,
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "NO_PROXY": "*",
    }
    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
            env=environment,
        )
    except subprocess.TimeoutExpired:
        return {"status": "blocked", "reason": "dependency_probe_timeout", "path_persisted": False}
    if result.returncode != 0:
        return {
            "status": "blocked",
            "reason": "dependency_probe_failed",
            "returncode": result.returncode,
            "stderr_sha256": hashlib.sha256(result.stderr.encode("utf-8")).hexdigest(),
            "path_persisted": False,
        }
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "blocked", "reason": "dependency_probe_invalid_json", "path_persisted": False}
    payload["status"] = "ready" if payload.get("apply_dependencies_ready") else "blocked"
    payload["path_persisted"] = False
    return payload


def build_status(
    *,
    python_path: Path | str,
    model_path: Path | str | None = None,
    lens_path: Path | str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    dependencies = probe_interpreter(python_path, runner=runner)
    model = inspect_model_artifact(model_path) if model_path else {
        "format": "not_supplied",
        "activation_access": False,
        "fit_supported": False,
        "apply_supported": False,
        "reason": "local_huggingface_model_not_supplied",
        "path_persisted": False,
    }
    lens: dict[str, Any]
    if lens_path:
        lens_file = _safe_regular_file(lens_path)
        lens = {
            "present": True,
            "artifact_name": lens_file.name,
            "sha256": sha256_file(lens_file),
            "byte_count": lens_file.stat().st_size,
            "path_persisted": False,
        }
    else:
        lens = {"present": False, "reason": "fitted_lens_not_supplied", "path_persisted": False}

    apply_ready = bool(
        dependencies.get("apply_dependencies_ready")
        and model.get("apply_supported")
        and lens.get("present")
    )
    if apply_ready:
        status = "ready_for_registered_apply"
        next_move = "preregister_a_private_readout_transfer_set_then_run_apply_only"
    elif not model.get("activation_access"):
        status = "blocked_exact_live_model_activations_unavailable"
        next_move = "obtain_a_license_compatible_local_hf_decoder_sibling_without_changing_live_routing"
    elif not dependencies.get("apply_dependencies_ready"):
        status = "blocked_dependencies"
        next_move = "install_jlens_in_an_isolated_lab_interpreter_and_reprobe"
    else:
        status = "blocked_missing_fitted_lens"
        next_move = "fit_or_obtain_a_model_revision_matched_lens_in_the_isolated_lab"

    return {
        "schema_id": STATUS_SCHEMA,
        "generated_at": utc_now(),
        "status": status,
        "method": UPSTREAM_METHOD,
        "upstream_repository": UPSTREAM_REPOSITORY,
        "dependencies": dependencies,
        "model": model,
        "lens": lens,
        "next_move": next_move,
        "evidence_scope": "latent_workspace_readout_feasibility_only",
        "authority": {
            "resident_lane_added": False,
            "live_model_changed": False,
            "routing_changed": False,
            "memory_changed": False,
            "consciousness_proven": False,
            "subjective_experience_inferred": False,
        },
        "limitations": [
            "system_level_global_workspace_is_not_the_same_as_a_model_latent_workspace",
            "a_readable_workspace_does_not_establish_phenomenal_consciousness",
            "gguf_serving_does_not_expose_the_required_residual_activations",
            "surrogate_model_or_backend_results_do_not_transfer_to_the_live_quantized_lane",
            "the_reference_method_is_not_maintained_by_its_upstream_author",
        ],
        "capability_resolution_id": "326eb87d-0c5c-4cec-9b4e-c5e63dc7b2b0",
    }


def _load_json_file(path: Path | str, *, maximum_bytes: int = MAX_SPEC_BYTES) -> tuple[Path, Any]:
    artifact = _safe_regular_file(path, maximum_bytes=maximum_bytes)
    return artifact, json.loads(artifact.read_text(encoding="utf-8"))


def validate_spec(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {
        "schema_id",
        "minimum_hit_rate",
        "minimum_jacobian_advantage",
        "cases",
    }:
        raise ValueError("invalid private readout spec shape")
    if payload.get("schema_id") != SPEC_SCHEMA:
        raise ValueError("invalid private readout spec schema")
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) < MINIMUM_CASES:
        raise ValueError(f"at least {MINIMUM_CASES} private cases are required")
    ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != {
            "id",
            "prompt",
            "position",
            "layers",
            "expected_concepts",
        }:
            raise ValueError("invalid private case shape")
        case_id = str(case["id"])
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,80}", case_id) or case_id in ids:
            raise ValueError("invalid or duplicate private case id")
        if not isinstance(case["prompt"], str) or not case["prompt"].strip():
            raise ValueError("private case prompt is required")
        if not isinstance(case["position"], int):
            raise ValueError("private case position must be an integer")
        if not isinstance(case["layers"], list) or not case["layers"] or any(
            not isinstance(layer, int) or layer < 0 for layer in case["layers"]
        ):
            raise ValueError("private case layers must be non-negative integers")
        concepts = case["expected_concepts"]
        if not isinstance(concepts, list) or not concepts or any(
            not isinstance(item, str) or not item.strip() for item in concepts
        ):
            raise ValueError("private case expected concepts are required")
        ids.add(case_id)
    for field in ("minimum_hit_rate", "minimum_jacobian_advantage"):
        value = payload[field]
        if not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
            raise ValueError(f"{field} must be between zero and one")
    return payload


def artifact_tree_identity(path: Path | str) -> dict[str, Any]:
    root = Path(path).expanduser()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("model must be an existing non-symlink directory")
    files = sorted(
        (item for item in root.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(root).as_posix(),
    )
    if not files:
        raise ValueError("model directory contains no files")
    digest = hashlib.sha256()
    byte_count = 0
    for item in files:
        relative = item.relative_to(root).as_posix()
        resolved = item.resolve(strict=True)
        if not resolved.is_file():
            raise ValueError("model tree contains a non-regular artifact")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with resolved.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                byte_count += len(chunk)
                digest.update(chunk)
    return {
        "artifact_name": root.name,
        "sha256": digest.hexdigest(),
        "file_count": len(files),
        "byte_count": byte_count,
        "path_persisted": False,
    }


def build_registration(
    *,
    python_path: Path | str,
    model_path: Path | str,
    lens_path: Path | str,
    spec_path: Path | str,
    upstream_commit: str,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40}", upstream_commit.lower()):
        raise ValueError("an exact forty-character upstream commit is required")
    status = build_status(
        python_path=python_path,
        model_path=model_path,
        lens_path=lens_path,
        runner=runner,
    )
    if status["status"] != "ready_for_registered_apply":
        raise ValueError(f"lab is not ready: {status['status']}")
    spec_file, spec = _load_json_file(spec_path)
    validate_spec(spec)
    lens_file = _safe_regular_file(lens_path)
    model_identity = artifact_tree_identity(model_path)
    material = {
        "schema_id": REGISTRATION_SCHEMA,
        "registered_at": utc_now(),
        "upstream_repository": UPSTREAM_REPOSITORY,
        "upstream_commit": upstream_commit.lower(),
        "implementation_sha256": sha256_file(SCRIPT),
        "interpreter": {
            "python": status["dependencies"].get("python", ""),
            "interpreter_sha256": status["dependencies"].get("interpreter_sha256", ""),
            "packages": status["dependencies"].get("packages", {}),
            "devices": status["dependencies"].get("devices", {}),
            "path_persisted": False,
        },
        "model": model_identity,
        "lens": {
            "artifact_name": lens_file.name,
            "sha256": sha256_file(lens_file),
            "byte_count": lens_file.stat().st_size,
            "path_persisted": False,
        },
        "spec_sha256": sha256_file(spec_file),
        "case_count": len(spec["cases"]),
        "minimum_hit_rate": float(spec["minimum_hit_rate"]),
        "minimum_jacobian_advantage": float(spec["minimum_jacobian_advantage"]),
        "prompts_persisted": False,
        "decoded_latent_tokens_persisted": False,
        "consciousness_verdict_authorized": False,
    }
    material["registration_digest"] = digest_value(material)
    return material


def score_rows(registration: dict[str, Any], rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    expected_count = int(registration["case_count"])
    if len(rows) != expected_count:
        raise ValueError("row count does not match preregistration")
    ids: set[str] = set()
    clean_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "case_id",
            "jacobian_hit",
            "logit_lens_hit",
            "execution_ok",
        }:
            raise ValueError("invalid aggregate worker row")
        case_id = str(row["case_id"])
        if case_id in ids:
            raise ValueError("duplicate aggregate worker row")
        if any(not isinstance(row[field], bool) for field in (
            "jacobian_hit",
            "logit_lens_hit",
            "execution_ok",
        )):
            raise ValueError("worker booleans are required")
        ids.add(case_id)
        clean_rows.append(dict(row))
    hard_failures = sum(not row["execution_ok"] for row in clean_rows)
    jacobian_hits = sum(row["execution_ok"] and row["jacobian_hit"] for row in clean_rows)
    logit_hits = sum(row["execution_ok"] and row["logit_lens_hit"] for row in clean_rows)
    hit_rate = jacobian_hits / expected_count
    baseline_rate = logit_hits / expected_count
    advantage = hit_rate - baseline_rate
    if hard_failures:
        result = "inconclusive_hard_failures"
    elif hit_rate >= float(registration["minimum_hit_rate"]) and advantage >= float(
        registration["minimum_jacobian_advantage"]
    ):
        result = "latent_readout_supported"
    elif advantage <= -float(registration["minimum_jacobian_advantage"]):
        result = "latent_readout_challenged"
    else:
        result = "latent_readout_inconclusive"
    report = {
        "schema_id": REPORT_SCHEMA,
        "evaluated_at": utc_now(),
        "registration_digest": registration["registration_digest"],
        "case_count": expected_count,
        "jacobian_hits": jacobian_hits,
        "logit_lens_hits": logit_hits,
        "jacobian_hit_rate": round(hit_rate, 6),
        "logit_lens_hit_rate": round(baseline_rate, 6),
        "jacobian_advantage": round(advantage, 6),
        "hard_failures": hard_failures,
        "indicator_result": result,
        "rows": clean_rows,
        "prompts_persisted": False,
        "decoded_latent_tokens_persisted": False,
        "live_gguf_lane_tested": False,
        "resident_routing_changed": False,
        "consciousness_proven": False,
        "subjective_experience_inferred": False,
        "verdict": "not_a_consciousness_verdict",
    }
    report["report_digest"] = digest_value(report)
    return report


def _validate_registration_and_inputs(
    registration_path: Path | str,
    *,
    model_path: Path | str,
    lens_path: Path | str,
    spec_path: Path | str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _, registration = _load_json_file(registration_path)
    if not isinstance(registration, dict) or registration.get("schema_id") != REGISTRATION_SCHEMA:
        raise ValueError("invalid registration")
    expected_digest = registration.get("registration_digest")
    unsigned = {key: value for key, value in registration.items() if key != "registration_digest"}
    if expected_digest != digest_value(unsigned):
        raise ValueError("registration digest drift")
    if registration.get("implementation_sha256") != sha256_file(SCRIPT):
        raise ValueError("implementation drift")
    spec_file, spec = _load_json_file(spec_path)
    validate_spec(spec)
    if registration.get("spec_sha256") != sha256_file(spec_file):
        raise ValueError("private spec drift")
    lens_file = _safe_regular_file(lens_path)
    if registration.get("lens", {}).get("sha256") != sha256_file(lens_file):
        raise ValueError("lens drift")
    if registration.get("model") != artifact_tree_identity(model_path):
        raise ValueError("model drift")
    if registration.get("consciousness_verdict_authorized") is not False:
        raise ValueError("invalid consciousness verdict authority")
    return registration, spec


def run_registered_apply(
    *,
    python_path: Path | str,
    model_path: Path | str,
    lens_path: Path | str,
    spec_path: Path | str,
    registration_path: Path | str,
    timeout: int,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    registration, _ = _validate_registration_and_inputs(
        registration_path,
        model_path=model_path,
        lens_path=lens_path,
        spec_path=spec_path,
    )
    current_dependencies = probe_interpreter(python_path, runner=runner)
    registered_interpreter = registration.get("interpreter", {})
    if (
        current_dependencies.get("status") != "ready"
        or current_dependencies.get("python") != registered_interpreter.get("python")
        or current_dependencies.get("interpreter_sha256")
        != registered_interpreter.get("interpreter_sha256")
        or current_dependencies.get("packages") != registered_interpreter.get("packages")
    ):
        raise ValueError("registered interpreter or dependency drift")
    interpreter = _safe_executable(python_path)
    command = [
        str(interpreter),
        str(SCRIPT),
        "_apply-worker",
        "--model",
        str(Path(model_path).expanduser().resolve()),
        "--lens",
        str(Path(lens_path).expanduser().resolve()),
        "--spec",
        str(Path(spec_path).expanduser().resolve()),
    ]
    environment = {
        **os.environ,
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "NO_PROXY": "*",
    }
    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=environment,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("registered latent-workspace worker timed out") from exc
    if result.returncode != 0:
        failure_digest = hashlib.sha256(result.stderr.encode("utf-8")).hexdigest()
        raise RuntimeError(f"registered latent-workspace worker failed: {failure_digest}")
    try:
        worker = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("registered latent-workspace worker returned invalid JSON") from exc
    if not isinstance(worker, dict) or set(worker) != {"schema_id", "rows"} or worker.get(
        "schema_id"
    ) != "eve.jacobian_workspace_worker.v1":
        raise RuntimeError("registered latent-workspace worker returned an invalid envelope")
    return score_rows(registration, worker["rows"])


def _apply_worker(model_path: str, lens_path: str, spec_path: str) -> dict[str, Any]:
    """Dependency-heavy worker; stdout contains aggregate booleans only."""

    import torch
    import transformers
    import jlens

    _, spec = _load_json_file(spec_path)
    validate_spec(spec)
    device = "cuda" if torch.cuda.is_available() else (
        "mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available() else "cpu"
    )
    dtype = torch.float16 if device in {"cuda", "mps"} else torch.float32
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        model_path,
        local_files_only=True,
        trust_remote_code=False,
    )
    model = transformers.AutoModelForCausalLM.from_pretrained(
        model_path,
        local_files_only=True,
        trust_remote_code=False,
        torch_dtype=dtype,
    ).to(device)
    adapter = jlens.from_hf(model, tokenizer, compile=False)
    lens = jlens.JacobianLens.load(lens_path)
    rows: list[dict[str, Any]] = []
    for case in spec["cases"]:
        execution_ok = True
        jacobian_hit = False
        logit_hit = False
        try:
            jacobian_logits, _, _ = lens.apply(
                adapter,
                case["prompt"],
                layers=case["layers"],
                positions=[case["position"]],
                use_jacobian=True,
            )
            logit_logits, _, _ = lens.apply(
                adapter,
                case["prompt"],
                layers=case["layers"],
                positions=[case["position"]],
                use_jacobian=False,
            )
            expected = {item.casefold().strip() for item in case["expected_concepts"]}

            def has_expected(layer_logits: dict[int, Any]) -> bool:
                for logits in layer_logits.values():
                    token_ids = logits[0].topk(min(20, logits.shape[-1])).indices.tolist()
                    decoded = {
                        tokenizer.decode([int(token_id)]).casefold().strip()
                        for token_id in token_ids
                    }
                    if expected & decoded:
                        return True
                return False

            jacobian_hit = has_expected(jacobian_logits)
            logit_hit = has_expected(logit_logits)
        except Exception:
            execution_ok = False
        rows.append(
            {
                "case_id": case["id"],
                "jacobian_hit": jacobian_hit,
                "logit_lens_hit": logit_hit,
                "execution_ok": execution_ok,
            }
        )
    return {"schema_id": "eve.jacobian_workspace_worker.v1", "rows": rows}


def write_json(path: Path | str, payload: dict[str, Any], *, private: bool = False) -> Path:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(target, flags, 0o600 if private else 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True, sort_keys=True)
        handle.write("\n")
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stage local-only Jacobian-lens readout evidence without changing Eve's live lanes."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status")
    status.add_argument("--python", required=True)
    status.add_argument("--model")
    status.add_argument("--lens")
    status.add_argument("--output")
    register = sub.add_parser("register")
    register.add_argument("--python", required=True)
    register.add_argument("--model", required=True)
    register.add_argument("--lens", required=True)
    register.add_argument("--spec", required=True)
    register.add_argument("--upstream-commit", required=True)
    register.add_argument("--output", required=True)
    run = sub.add_parser("run")
    run.add_argument("--python", required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--lens", required=True)
    run.add_argument("--spec", required=True)
    run.add_argument("--registration", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--timeout", type=int, default=3600)
    worker = sub.add_parser("_apply-worker", help=argparse.SUPPRESS)
    worker.add_argument("--model", required=True)
    worker.add_argument("--lens", required=True)
    worker.add_argument("--spec", required=True)
    sub.add_parser("_dependency-probe", help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "_dependency-probe":
        print(canonical_json(local_dependency_probe()))
        return 0
    if args.command == "_apply-worker":
        print(canonical_json(_apply_worker(args.model, args.lens, args.spec)))
        return 0
    if args.command == "status":
        report = build_status(
            python_path=args.python,
            model_path=args.model,
            lens_path=args.lens,
        )
        if args.output:
            write_json(args.output, report)
    elif args.command == "register":
        report = build_registration(
            python_path=args.python,
            model_path=args.model,
            lens_path=args.lens,
            spec_path=args.spec,
            upstream_commit=args.upstream_commit,
        )
        write_json(args.output, report, private=True)
    else:
        report = run_registered_apply(
            python_path=args.python,
            model_path=args.model,
            lens_path=args.lens,
            spec_path=args.spec,
            registration_path=args.registration,
            timeout=args.timeout,
        )
        write_json(args.output, report, private=True)
    print(json.dumps(report, indent=2, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
