#!/usr/bin/env python3
"""Run Eve's Gemma 4 MTP lab without changing live lane routing."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shlex
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LAB_DIR = ROOT / ".eve" / "gemma4_mtp_lab"
MODEL_DIR = LAB_DIR / "models"
LATEST_REPORT = LAB_DIR / "latest.json"
HISTORY_REPORT = LAB_DIR / "history.jsonl"
DEFAULT_LLAMA_SERVER = ROOT / ".eve" / "runtime_tools" / "llama-cpp" / "b8946" / "llama-server"
DEFAULT_ATOMIC_LLAMA_SERVER = (
    ROOT
    / ".eve"
    / "runtime_tools"
    / "atomic-llama-cpp-turboquant-feature-gemma-mtp"
    / "build-eve"
    / "bin"
    / "llama-server"
)


CANDIDATES: dict[str, dict[str, Any]] = {
    "e4b-local-gguf": {
        "lane": "fast",
        "target_repo": "google/gemma-4-E4B-it",
        "assistant_repo": "google/gemma-4-E4B-it-assistant",
        "target_path": ROOT / "models" / "lane_trials" / "gemma4-e4b-q4" / "gemma-4-E4B-RotorQuant-Q4_K_M.gguf",
        "assistant_filename": "gemma-4-E4B-it-assistant.Q4_K_M.gguf",
        "assistant_url": (
            "https://huggingface.co/AtomicChat/gemma-4-E4B-it-assistant-GGUF/resolve/main/"
            "gemma-4-E4B-it-assistant.Q4_K_M.gguf"
        ),
        "assistant_bytes": 78_575_008,
        "assistant_source": "AtomicChat/gemma-4-E4B-it-assistant-GGUF",
        "note": (
            "Uses Eve's already-local E4B GGUF target plus a llama.cpp-compatible assistant GGUF. "
            "This is a lab compatibility smoke, not a live lane promotion."
        ),
    },
    "e2b-lab-gguf": {
        "lane": "fast",
        "target_repo": "google/gemma-4-E2B-it",
        "assistant_repo": "google/gemma-4-E2B-it-assistant",
        "target_hf_repo": "ggml-org/gemma-4-E2B-it-GGUF:Q4_K_M",
        "assistant_filename": "gemma-4-E2B-it-assistant.Q4_K_M.gguf",
        "assistant_url": (
            "https://huggingface.co/AtomicChat/gemma-4-E2B-it-assistant-GGUF/resolve/main/"
            "gemma-4-E2B-it-assistant.Q4_K_M.gguf"
        ),
        "assistant_bytes": 78_132_640,
        "assistant_source": "AtomicChat/gemma-4-E2B-it-assistant-GGUF",
        "note": (
            "Smallest plausible fast-lane target-plus-drafter experiment. Target GGUF is not "
            "downloaded automatically by this script because Eve's disk headroom is currently tight."
        ),
    },
}


class LabError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value)!r}")


def write_report(report: dict[str, Any]) -> None:
    LAB_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, indent=2, sort_keys=True, default=json_default) + "\n"
    LATEST_REPORT.write_text(payload, encoding="utf-8")
    with HISTORY_REPORT.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, sort_keys=True, default=json_default) + "\n")


def url_json(url: str, timeout: float = 20.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "eve-gemma4-mtp-lab"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def http_json(method: str, url: str, body: dict[str, Any] | None = None, timeout: float = 20.0) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json", "User-Agent": "eve-gemma4-mtp-lab"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
        return json.loads(raw or "{}")


def download_file(url: str, path: Path, expected_bytes: int | None, allow_download: bool) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        size = path.stat().st_size
        return {
            "status": "cached" if expected_bytes is None or size == expected_bytes else "size_mismatch",
            "path": str(path),
            "bytes": size,
            "expected_bytes": expected_bytes,
        }
    if not allow_download:
        return {
            "status": "missing_download_not_allowed",
            "path": str(path),
            "expected_bytes": expected_bytes,
            "next": "rerun with --allow-download to fetch the assistant GGUF",
        }

    tmp_path = path.with_suffix(path.suffix + ".part")
    start = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": "eve-gemma4-mtp-lab"})
    with urllib.request.urlopen(request, timeout=60) as response, tmp_path.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
    tmp_path.replace(path)
    size = path.stat().st_size
    return {
        "status": "downloaded" if expected_bytes is None or size == expected_bytes else "size_mismatch",
        "path": str(path),
        "bytes": size,
        "expected_bytes": expected_bytes,
        "seconds": round(time.monotonic() - start, 3),
    }


def llama_supports_draft(server_bin: Path) -> dict[str, Any]:
    if not server_bin.exists():
        return {"status": "missing", "path": str(server_bin)}
    if not os.access(server_bin, os.X_OK):
        return {"status": "not_executable", "path": str(server_bin)}
    proc = subprocess.run(
        [str(server_bin), "--help"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=20,
        check=False,
    )
    text = proc.stdout
    spec_type_line = ""
    for line in text.splitlines():
        if "--spec-type" in line:
            spec_type_line = line.strip()
            break
    required_any = {
        "model_draft": ["--model-draft", "--spec-draft-model"],
        "hf_repo_draft": ["--hf-repo-draft", "--spec-draft-hf"],
        "draft_n_max": ["--draft", "--spec-draft-n-max"],
        "draft_n_min": ["--draft-min", "--spec-draft-n-min"],
        "draft_p_min": ["--draft-p-min", "--spec-draft-p-min"],
        "spec_type": ["--spec-type"],
    }
    missing = [name for name, flags in required_any.items() if not any(flag in text for flag in flags)]
    draft_count_flag = "--spec-draft-n-max" if "--spec-draft-n-max" in text else "--draft"
    draft_min_flag = "--spec-draft-n-min" if "--spec-draft-n-min" in text else "--draft-min"
    supports_mtp = "--mtp-head" in text and "mtp" in spec_type_line
    return {
        "status": "supported" if not missing else "missing_flags",
        "path": str(server_bin),
        "returncode": proc.returncode,
        "missing_flags": missing,
        "draft_count_flag": draft_count_flag,
        "draft_min_flag": draft_min_flag,
        "supports_mtp_head": supports_mtp,
        "spec_type_line": spec_type_line,
    }


def hf_repo_probe(repo: str) -> dict[str, Any]:
    try:
        data = url_json(f"https://huggingface.co/api/models/{repo}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"repo": repo, "status": "probe_failed", "error": f"{exc.__class__.__name__}: {exc}"}
    return {
        "repo": repo,
        "status": "ok",
        "library_name": data.get("library_name"),
        "pipeline_tag": data.get("pipeline_tag"),
        "license": (data.get("cardData") or {}).get("license"),
        "gated": data.get("gated"),
        "lastModified": data.get("lastModified"),
        "siblings": [item.get("rfilename") for item in data.get("siblings", [])],
        "safetensors_parameters": (data.get("safetensors") or {}).get("parameters"),
        "gguf": data.get("gguf"),
    }


def candidate_paths(candidate: dict[str, Any]) -> dict[str, Any]:
    target_path = candidate.get("target_path")
    assistant_path = MODEL_DIR / str(candidate["assistant_filename"])
    return {
        "target_path": Path(target_path) if target_path else None,
        "assistant_path": assistant_path,
    }


def build_llama_command(
    candidate: dict[str, Any],
    server_bin: Path,
    target_path: Path,
    assistant_path: Path,
    port: int,
    alias: str,
    ctx_size: int,
    draft_tokens: int,
    draft_count_flag: str = "--draft",
    draft_min_flag: str = "--draft-min",
    llama_flavor: str = "draft",
    draft_block_size: int = 2,
) -> list[str]:
    command = [
        str(server_bin),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--ctx-size",
        str(ctx_size),
        "--threads",
        "8",
        "--threads-batch",
        "8",
        "--ubatch-size",
        "512",
        "--flash-attn",
        "on" if llama_flavor == "gemma4-mtp" else "auto",
        "--parallel",
        "1",
        "--gpu-layers",
        "all",
        "--slot-prompt-similarity",
        "0.20",
        "--slots",
        "--cache-prompt",
        "--alias",
        alias,
        "--model",
        str(target_path),
    ]
    if llama_flavor == "gemma4-mtp":
        command.extend(
            [
                "--mtp-head",
                str(assistant_path),
                "--spec-type",
                "mtp",
                "--draft-block-size",
                str(max(2, int(draft_block_size or 2))),
                draft_count_flag,
                str(draft_tokens),
                draft_min_flag,
                "1",
                "--draft-p-min",
                "0.75",
                "--gpu-layers-draft",
                "all",
                "--no-webui",
            ]
        )
    else:
        command.extend(
            [
                "--model-draft",
                str(assistant_path),
                draft_count_flag,
                str(draft_tokens),
                draft_min_flag,
                "1",
                "--draft-p-min",
                "0.75",
                "--gpu-layers-draft",
                "all",
                "--threads-draft",
                "4",
                "--threads-batch-draft",
                "4",
            ]
        )
    return command


def wait_for_models(port: int, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            data = http_json("GET", f"http://127.0.0.1:{port}/v1/models", timeout=3)
            return {"status": "ready", "models": data.get("data", data)}
        except Exception as exc:  # noqa: BLE001 - this is an operator-facing readiness loop.
            last_error = f"{exc.__class__.__name__}: {exc}"
            time.sleep(1.0)
    return {"status": "timeout", "last_error": last_error}


def run_probe(port: int, alias: str, timeout: float) -> dict[str, Any]:
    body = {
        "model": alias,
        "messages": [
            {
                "role": "system",
                "content": "Return exactly one compact JSON object with keys status, message, and boundary.",
            },
            {
                "role": "user",
                "content": "Say whether this temporary Gemma 4 MTP lab server is running. Do not discuss promotion.",
            },
        ],
        "max_tokens": 96,
        "temperature": 0,
    }
    start = time.monotonic()
    data = http_json("POST", f"http://127.0.0.1:{port}/v1/chat/completions", body=body, timeout=timeout)
    elapsed = time.monotonic() - start
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    usage = data.get("usage") or {}
    return {
        "status": "ok",
        "seconds": round(elapsed, 3),
        "content": message.get("content", ""),
        "finish_reason": choice.get("finish_reason"),
        "usage": usage,
    }


def run_transformers_smoke(args: argparse.Namespace) -> dict[str, Any]:
    start = time.monotonic()
    try:
        import torch  # type: ignore
        from transformers import AutoModelForCausalLM, AutoProcessor  # type: ignore
    except Exception as exc:  # noqa: BLE001 - report missing lab deps directly.
        return {
            "status": "blocked",
            "error": f"{exc.__class__.__name__}: {exc}",
            "next": "run with .venv-techlab/bin/python after installing torch/accelerate/safetensors",
        }

    target_id = args.transformers_target
    assistant_id = args.transformers_assistant or f"{target_id}-assistant"
    dtype = torch.bfloat16 if args.torch_dtype == "bfloat16" else torch.float16
    load_kwargs: dict[str, Any] = {"torch_dtype": dtype}
    if args.device == "auto":
        load_kwargs["device_map"] = "auto"

    try:
        processor = AutoProcessor.from_pretrained(target_id)
        target_model = AutoModelForCausalLM.from_pretrained(target_id, **load_kwargs)
        assistant_model = AutoModelForCausalLM.from_pretrained(assistant_id, **load_kwargs)
        if args.device != "auto":
            target_model = target_model.to(args.device)
            assistant_model = assistant_model.to(args.device)

        messages = [{"role": "user", "content": args.prompt}]
        input_text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = processor(text=input_text, return_tensors="pt").to(target_model.device)
        generate_start = time.monotonic()
        outputs = target_model.generate(
            **inputs,
            assistant_model=assistant_model,
            max_new_tokens=args.max_new_tokens,
            do_sample=False,
        )
        generated = processor.decode(outputs[0], skip_special_tokens=True)
        generated_tokens = int(outputs.shape[-1] - inputs["input_ids"].shape[-1])
        return {
            "status": "passed",
            "target": target_id,
            "assistant": assistant_id,
            "device": str(target_model.device),
            "dtype": args.torch_dtype,
            "seconds_total": round(time.monotonic() - start, 3),
            "seconds_generate": round(time.monotonic() - generate_start, 3),
            "generated_tokens": generated_tokens,
            "response": generated[-1200:],
        }
    except Exception as exc:  # noqa: BLE001 - keep exact lab error in report.
        return {
            "status": "blocked",
            "target": target_id,
            "assistant": assistant_id,
            "device": args.device,
            "dtype": args.torch_dtype,
            "seconds_total": round(time.monotonic() - start, 3),
            "error": f"{exc.__class__.__name__}: {exc}",
        }


def terminate_process(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        proc.wait(timeout=5)


def run_llama_smoke(args: argparse.Namespace, candidate: dict[str, Any], download: dict[str, Any]) -> dict[str, Any]:
    paths = candidate_paths(candidate)
    target_path = args.target_path or paths["target_path"]
    assistant_path = args.assistant_path or paths["assistant_path"]
    server_bin = args.llama_server
    alias = args.alias
    if target_path is None:
        raise LabError("Candidate has no local target path; provide --target-path.")
    target_path = Path(target_path)
    assistant_path = Path(assistant_path)
    if not target_path.exists():
        raise LabError(f"Target GGUF is missing: {target_path}")
    if not assistant_path.exists():
        raise LabError(f"Assistant GGUF is missing: {assistant_path}")
    if download.get("status") == "size_mismatch":
        raise LabError(f"Assistant GGUF size mismatch: {assistant_path}")

    support = llama_supports_draft(server_bin)
    if support.get("status") != "supported":
        raise LabError(f"llama-server draft support is not ready: {support}")
    if args.llama_flavor == "gemma4-mtp" and not support.get("supports_mtp_head"):
        raise LabError(f"llama-server does not expose Gemma 4 MTP head support: {support}")
    command = build_llama_command(
        candidate,
        server_bin=server_bin,
        target_path=target_path,
        assistant_path=assistant_path,
        port=args.port,
        alias=alias,
        ctx_size=args.ctx_size,
        draft_tokens=args.draft_tokens,
        draft_count_flag=str(support.get("draft_count_flag") or "--draft"),
        draft_min_flag=str(support.get("draft_min_flag") or "--draft-min"),
        llama_flavor=args.llama_flavor,
        draft_block_size=args.draft_block_size,
    )
    if args.dry_run:
        return {
            "status": "dry_run",
            "flavor": args.llama_flavor,
            "command": command,
            "command_text": " ".join(shlex.quote(item) for item in command),
        }

    LAB_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LAB_DIR / f"{alias}.log"
    trace_path = LAB_DIR / f"{alias}-mtp-trace.ndjson"
    if args.llama_flavor == "gemma4-mtp" and trace_path.exists():
        trace_path.unlink()
    env = os.environ.copy()
    if args.llama_flavor == "gemma4-mtp" and args.trace_mtp:
        env["LLAMA_MTP_ACC_TRACE"] = str(trace_path)
        env.setdefault("MTP_PRESET", "throughput")
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
            env=env,
        )
        try:
            readiness = wait_for_models(args.port, args.startup_timeout)
            if readiness.get("status") != "ready":
                return {
                    "status": "server_not_ready",
                    "command": command,
                    "log_path": str(log_path),
                    "readiness": readiness,
                    "returncode": proc.poll(),
                }
            probe = run_probe(args.port, alias, args.probe_timeout)
            trace_lines: list[str] = []
            trace_has_mtp = False
            if args.llama_flavor == "gemma4-mtp" and trace_path.exists():
                trace_lines = trace_path.read_text(encoding="utf-8", errors="replace").splitlines()
                trace_has_mtp = any('"evt":"mtp_draft"' in line for line in trace_lines) and any(
                    '"evt":"mtp_accept"' in line for line in trace_lines
                )
            return {
                "status": "passed" if args.llama_flavor != "gemma4-mtp" or trace_has_mtp else "probe_without_mtp_trace",
                "flavor": args.llama_flavor,
                "command": command,
                "log_path": str(log_path),
                "trace_path": str(trace_path) if args.llama_flavor == "gemma4-mtp" else "",
                "trace_events": len(trace_lines),
                "trace_has_mtp": trace_has_mtp,
                "pid": proc.pid,
                "readiness": readiness,
                "probe": probe,
                "returncode": proc.poll(),
            }
        except Exception as exc:  # noqa: BLE001 - preserve the exact smoke failure in the report.
            return {
                "status": "probe_failed",
                "flavor": args.llama_flavor,
                "command": command,
                "log_path": str(log_path),
                "trace_path": str(trace_path) if args.llama_flavor == "gemma4-mtp" else "",
                "error": f"{exc.__class__.__name__}: {exc}",
                "returncode": proc.poll(),
            }
        finally:
            if not args.keep_server:
                terminate_process(proc)


def resolve_llama_server(args: argparse.Namespace) -> None:
    if args.llama_server:
        args.llama_server = Path(args.llama_server)
        return
    if args.llama_flavor == "gemma4-mtp" and DEFAULT_ATOMIC_LLAMA_SERVER.exists():
        args.llama_server = DEFAULT_ATOMIC_LLAMA_SERVER
        return
    args.llama_server = DEFAULT_LLAMA_SERVER


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    candidate = dict(CANDIDATES[args.candidate])
    candidate["target_path"] = str(candidate["target_path"]) if candidate.get("target_path") else None
    candidate["assistant_local_path"] = str((MODEL_DIR / str(candidate["assistant_filename"])).resolve())
    server_support = llama_supports_draft(args.llama_server)
    official_target = hf_repo_probe(str(candidate["target_repo"])) if args.network else {"status": "skipped"}
    official_assistant = hf_repo_probe(str(candidate["assistant_repo"])) if args.network else {"status": "skipped"}
    community_assistant = (
        hf_repo_probe(str(candidate["assistant_source"])) if args.network and "/" in str(candidate["assistant_source"]) else {"status": "skipped"}
    )
    transformers_target = hf_repo_probe(str(args.transformers_target)) if args.network else {"status": "skipped"}
    transformers_assistant_id = args.transformers_assistant or f"{args.transformers_target}-assistant"
    transformers_assistant = hf_repo_probe(str(transformers_assistant_id)) if args.network else {"status": "skipped"}
    download = download_file(
        str(candidate["assistant_url"]),
        MODEL_DIR / str(candidate["assistant_filename"]),
        int(candidate["assistant_bytes"]),
        args.allow_download and args.mode in {"download", "all", "llama-smoke"},
    )

    report: dict[str, Any] = {
        "generated_at": utc_now(),
        "status": "preflight",
        "mode": args.mode,
        "candidate_id": args.candidate,
        "candidate": candidate,
        "boundaries": {
            "live_routing_changed": False,
            "live_lane_promotion": False,
            "existing_lane_only": True,
            "no_sixth_lane": True,
        },
        "server_support": server_support,
        "hf": {
            "official_target": official_target,
            "official_assistant": official_assistant,
            "community_assistant_gguf": community_assistant,
            "transformers_target": transformers_target,
            "transformers_assistant": transformers_assistant,
        },
        "download": download,
        "interpretation": [
            "Official Google Gemma 4 MTP repos are Transformers/safetensors repos.",
            "Eve's live provider is llama.cpp, so a llama.cpp smoke needs GGUF target and GGUF assistant files.",
            "The official Transformers smoke uses the target model's generate(..., assistant_model=...) path.",
            "This script runs only temporary lab aliases and records evidence; it does not alter .eve/config.json or launchd lanes.",
        ],
    }

    if args.mode in {"transformers-smoke", "all-transformers"}:
        smoke = run_transformers_smoke(args)
        report["transformers_smoke"] = smoke
        report["status"] = "passed" if smoke.get("status") == "passed" else "blocked"
    elif args.mode in {"llama-smoke", "all"}:
        try:
            smoke = run_llama_smoke(args, CANDIDATES[args.candidate], download)
        except LabError as exc:
            smoke = {"status": "blocked", "flavor": args.llama_flavor, "error": str(exc)}
        report["llama_smoke"] = smoke
        smoke_status = str(smoke.get("status") or "")
        report["status"] = "passed" if smoke_status == "passed" else "dry_run" if smoke_status == "dry_run" else "blocked"
    elif args.mode == "download":
        report["status"] = "passed" if download.get("status") in {"cached", "downloaded"} else "blocked"
    return report


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", choices=sorted(CANDIDATES), default="e4b-local-gguf")
    parser.add_argument(
        "--mode",
        choices=["preflight", "download", "llama-smoke", "all", "transformers-smoke", "all-transformers"],
        default="preflight",
    )
    parser.add_argument("--allow-download", action="store_true", help="Allow fetching the small assistant GGUF for the lab.")
    parser.add_argument("--network", action="store_true", help="Probe Hugging Face metadata before running.")
    parser.add_argument("--write", action="store_true", help=f"Write {LATEST_REPORT} and append history.")
    parser.add_argument("--dry-run", action="store_true", help="Build commands without starting llama-server.")
    parser.add_argument("--keep-server", action="store_true", help="Leave the temporary server running after a successful smoke.")
    parser.add_argument("--port", type=int, default=8096)
    parser.add_argument("--alias", default="eve-gemma4-e4b-mtp-lab")
    parser.add_argument("--ctx-size", type=int, default=4096)
    parser.add_argument("--draft-tokens", type=int, default=8)
    parser.add_argument("--draft-block-size", type=int, default=2)
    parser.add_argument("--llama-flavor", choices=["draft", "gemma4-mtp"], default="draft")
    parser.add_argument("--trace-mtp", action="store_true", help="Record Gemma 4 MTP draft/accept trace evidence when using --llama-flavor gemma4-mtp.")
    parser.add_argument("--startup-timeout", type=float, default=120.0)
    parser.add_argument("--probe-timeout", type=float, default=120.0)
    parser.add_argument("--llama-server", type=Path)
    parser.add_argument("--target-path", type=Path)
    parser.add_argument("--assistant-path", type=Path)
    parser.add_argument("--transformers-target", default="google/gemma-4-E2B-it")
    parser.add_argument("--transformers-assistant", default="")
    parser.add_argument("--device", choices=["auto", "mps", "cpu"], default="auto")
    parser.add_argument("--torch-dtype", choices=["bfloat16", "float16"], default="bfloat16")
    parser.add_argument("--max-new-tokens", type=int, default=48)
    parser.add_argument(
        "--prompt",
        default=(
            "Return exactly one compact JSON object with keys status and boundary saying this "
            "Gemma 4 MTP Transformers smoke is running locally."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    resolve_llama_server(args)
    report = build_report(args)
    if args.write:
        write_report(report)
    print(json.dumps(report, indent=2, sort_keys=True, default=json_default))
    return 0 if report.get("status") in {"passed", "dry_run"} or args.mode == "preflight" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
