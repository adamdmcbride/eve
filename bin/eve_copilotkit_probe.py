#!/usr/bin/env python3
"""Probe CopilotKit as an Eve UI/AG-UI substrate candidate.

This script intentionally keeps CopilotKit in an isolated lab until an Eve
adapter proves itself. It may inspect npm metadata, install packages into a
separate lab directory, import the installed packages, mirror upstream source,
and verify Eve's local chat-completions bridge.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_PATH = ROOT / ".eve" / "oss_integration" / "copilotkit" / "latest.json"
DEFAULT_LAB_ROOT = Path.home() / "Library" / "Application Support" / "Eve" / "labs" / "copilotkit_probe"
DEFAULT_MIRROR_PATH = ROOT / "vendor" / "upstreams" / "agent-copilotkit.git"
UPSTREAM_URL = "https://github.com/CopilotKit/CopilotKit.git"
DEFAULT_EVE_BASE_URL = "http://127.0.0.1:8797/v1"
PACKAGES = ["@copilotkit/runtime", "@copilotkit/react-core", "@copilotkit/react-ui"]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def text_tail(text: str, limit: int = 2400) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def command_result(
    command: List[str],
    *,
    cwd: Optional[Path] = None,
    timeout: int = 60,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env=env,
        )
    except FileNotFoundError:
        return {
            "status": "missing",
            "command": command,
            "returncode": None,
            "stdout_tail": "",
            "stderr_tail": "command not found",
        }
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


def parse_json_value(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text.strip().strip('"')


def npm_field(package: str, field: str, timeout: int = 45) -> Dict[str, Any]:
    if not shutil.which("npm"):
        return {"status": "missing", "package": package, "field": field, "value": "", "error": "npm not found"}
    result = command_result(["npm", "view", package, field, "--json"], timeout=timeout)
    value: Any = ""
    if result["status"] == "ok":
        value = parse_json_value(result["stdout_tail"].strip())
    return {
        "status": result["status"],
        "package": package,
        "field": field,
        "value": value,
        "returncode": result["returncode"],
        "stderr_tail": result["stderr_tail"],
    }


def package_metadata() -> Dict[str, Any]:
    packages: List[Dict[str, Any]] = []
    for package in PACKAGES:
        version = npm_field(package, "version")
        license_field = npm_field(package, "license")
        packages.append(
            {
                "package": package,
                "version": version.get("value") or "",
                "license": license_field.get("value") or "",
                "version_status": version["status"],
                "license_status": license_field["status"],
            }
        )
    ready = all(item["version_status"] == "ok" and item["license_status"] == "ok" for item in packages)
    mit = all(str(item["license"]).upper() == "MIT" for item in packages)
    return {
        "schema_id": "eve_copilotkit_package_metadata.v1",
        "status": "ready" if ready and mit else "needs_review",
        "packages": packages,
        "all_mit": mit,
    }


def write_lab_package_json(lab_root: Path) -> None:
    payload = {
        "name": "eve-copilotkit-probe",
        "private": True,
        "type": "module",
        "description": "Isolated Eve lab for CopilotKit package import probing.",
        "dependencies": {package: "latest" for package in PACKAGES},
    }
    lab_root.mkdir(parents=True, exist_ok=True)
    (lab_root / "package.json").write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def npm_lab_status(lab_root: Path) -> Dict[str, Any]:
    package_json = lab_root / "package.json"
    node_modules = lab_root / "node_modules"
    installed_packages = {
        package: (node_modules / package).exists()
        for package in PACKAGES
    }
    return {
        "lab_root": str(lab_root),
        "package_json_exists": package_json.exists(),
        "node_modules_exists": node_modules.exists(),
        "installed_packages": installed_packages,
    }


def install_npm_lab(lab_root: Path, timeout: int = 240) -> Dict[str, Any]:
    write_lab_package_json(lab_root)
    env = os.environ.copy()
    env.update({"COPILOTKIT_TELEMETRY_DISABLED": "1", "DO_NOT_TRACK": "1"})
    result = command_result(["npm", "install", "--ignore-scripts", "--no-audit", "--fund=false"], cwd=lab_root, timeout=timeout, env=env)
    return {
        "schema_id": "eve_copilotkit_npm_install.v1",
        "status": result["status"],
        "lab_root": str(lab_root),
        "returncode": result["returncode"],
        "stdout_tail": result["stdout_tail"],
        "stderr_tail": result["stderr_tail"],
        "used_ignore_scripts": True,
        "telemetry_env": {"COPILOTKIT_TELEMETRY_DISABLED": "1", "DO_NOT_TRACK": "1"},
        "writes_repo_files": False,
    }


def node_import_probe(lab_root: Path, timeout: int = 60) -> Dict[str, Any]:
    if not (lab_root / "node_modules").exists():
        return {
            "schema_id": "eve_copilotkit_node_import_probe.v1",
            "status": "missing_install",
            "lab_root": str(lab_root),
            "packages": {},
        }
    script = r"""
import fs from "node:fs/promises";
const packages = ["@copilotkit/runtime", "@copilotkit/react-core", "@copilotkit/react-ui"];
const result = {};
for (const packageName of packages) {
  const packageJson = JSON.parse(await fs.readFile(`node_modules/${packageName}/package.json`, "utf8"));
  result[packageName] = {
    version: packageJson.version || "",
    license: packageJson.license || "",
    module: packageJson.module || "",
    main: packageJson.main || "",
    exports_type: typeof packageJson.exports,
    import_ok: false,
    export_sample: []
  };
}
try {
  const runtime = await import("@copilotkit/runtime");
  result["@copilotkit/runtime"].import_ok = true;
  result["@copilotkit/runtime"].export_sample = Object.keys(runtime).slice(0, 20);
  try {
    const { CopilotRuntime, OpenAIAdapter } = runtime;
    const adapter = new OpenAIAdapter({ model: "eve" });
    const copilotRuntime = new CopilotRuntime({ actions: [] });
    result.__adapter_probe = {
      status: "ready",
      openai_adapter_constructed: true,
      copilot_runtime_constructed: true,
      adapter_provider: adapter.provider || "",
      adapter_model: adapter.model || "",
      adapter_has_process: typeof adapter.process === "function",
      adapter_has_language_model: typeof adapter.getLanguageModel === "function",
      runtime_key_sample: Object.keys(copilotRuntime).slice(0, 12)
    };
  } catch (error) {
    result.__adapter_probe = {
      status: "blocked",
      error: String(error && error.message ? error.message : error)
    };
  }
} catch (error) {
  result["@copilotkit/runtime"].import_error = String(error && error.message ? error.message : error);
  result.__adapter_probe = { status: "blocked", error: result["@copilotkit/runtime"].import_error };
}
console.log(JSON.stringify(result));
"""
    env = os.environ.copy()
    env.update({"COPILOTKIT_TELEMETRY_DISABLED": "1", "DO_NOT_TRACK": "1"})
    result = command_result(["node", "--input-type=module", "-e", script], cwd=lab_root, timeout=timeout, env=env)
    packages: Dict[str, Any] = {}
    if result["status"] == "ok":
        try:
            packages = json.loads(result["stdout_tail"])
        except json.JSONDecodeError:
            packages = {}
    return {
        "schema_id": "eve_copilotkit_node_import_probe.v1",
        "status": (
            "ready"
            if result["status"] == "ok"
            and packages.get("@copilotkit/runtime", {}).get("import_ok")
            and packages.get("__adapter_probe", {}).get("status") == "ready"
            else result["status"]
        ),
        "lab_root": str(lab_root),
        "packages": packages,
        "adapter_probe": packages.get("__adapter_probe", {}),
        "returncode": result["returncode"],
        "stderr_tail": result["stderr_tail"],
        "telemetry_env": {"COPILOTKIT_TELEMETRY_DISABLED": "1", "DO_NOT_TRACK": "1"},
    }


def mirror_status(mirror_path: Path) -> Dict[str, Any]:
    if not mirror_path.exists():
        return {
            "schema_id": "eve_copilotkit_mirror.v1",
            "status": "missing",
            "mirror_path": str(mirror_path),
            "upstream_url": UPSTREAM_URL,
        }
    head = command_result(["git", f"--git-dir={mirror_path}", "rev-parse", "--short", "HEAD"], timeout=20)
    remotes = command_result(["git", f"--git-dir={mirror_path}", "remote", "-v"], timeout=20)
    return {
        "schema_id": "eve_copilotkit_mirror.v1",
        "status": "ready" if head["status"] == "ok" else "needs_attention",
        "mirror_path": str(mirror_path),
        "upstream_url": UPSTREAM_URL,
        "head": head["stdout_tail"].strip(),
        "remotes": remotes["stdout_tail"].strip().splitlines(),
        "returncode": head["returncode"],
        "stderr_tail": head["stderr_tail"],
    }


def ensure_mirror(mirror_path: Path, timeout: int = 300) -> Dict[str, Any]:
    if mirror_path.exists():
        fetch = command_result(["git", f"--git-dir={mirror_path}", "fetch", "--prune", "origin"], timeout=timeout)
        status = mirror_status(mirror_path)
        status["fetch"] = fetch
        return status
    mirror_path.parent.mkdir(parents=True, exist_ok=True)
    clone = command_result(["git", "clone", "--mirror", "--depth=1", UPSTREAM_URL, str(mirror_path)], timeout=timeout)
    status = mirror_status(mirror_path)
    status["clone"] = clone
    if clone["status"] != "ok":
        status["status"] = clone["status"]
        status["stderr_tail"] = clone["stderr_tail"]
    return status


def http_json(url: str, *, method: str = "GET", payload: Optional[Dict[str, Any]] = None, timeout: int = 45) -> Dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            try:
                parsed: Any = json.loads(body)
            except json.JSONDecodeError:
                parsed = body
            return {"status": "ok", "status_code": getattr(response, "status", None), "json": parsed, "error": ""}
    except urllib.error.HTTPError as exc:
        return {"status": "http_error", "status_code": exc.code, "json": {}, "error": text_tail(exc.read().decode("utf-8", errors="replace"))}
    except Exception as exc:
        return {"status": "error", "status_code": None, "json": {}, "error": str(exc)}


def eve_backend_probe(base_url: str, timeout: int = 45) -> Dict[str, Any]:
    models = http_json(f"{base_url.rstrip('/')}/models", timeout=10)
    completion_payload = {
        "model": "eve",
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": "CopilotKit compatibility probe: reply with exactly copilotkit-probe-ok.",
            }
        ],
        "temperature": 0,
    }
    completion = http_json(f"{base_url.rstrip('/')}/chat/completions", method="POST", payload=completion_payload, timeout=timeout)
    model_ids = []
    if isinstance(models.get("json"), dict):
        data = models["json"].get("data") or []
        if isinstance(data, list):
            model_ids = [str(item.get("id")) for item in data if isinstance(item, dict)]
    content = ""
    if isinstance(completion.get("json"), dict):
        choices = completion["json"].get("choices") or []
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
            content = str(message.get("content") or "")
    ready = models["status"] == "ok" and "eve" in model_ids and completion["status"] == "ok" and bool(content)
    return {
        "schema_id": "eve_copilotkit_eve_backend_probe.v1",
        "status": "ready" if ready else "blocked",
        "base_url": base_url,
        "models_status": models["status"],
        "model_ids": model_ids,
        "completion_status": completion["status"],
        "completion_status_code": completion["status_code"],
        "reply_excerpt": content[:240],
        "conversation_recorded_by_eve": True,
        "adapter_needed": "CopilotKit expects a CopilotKit/AG-UI runtime endpoint; Eve currently exposes OpenAI-compatible local chat completions.",
    }


def build_report(args: argparse.Namespace) -> Dict[str, Any]:
    lab_root = Path(args.lab_root).expanduser()
    mirror_path = Path(args.mirror_path).expanduser()
    report: Dict[str, Any] = {
        "schema_id": "eve_copilotkit_probe_report.v1",
        "generated_at": utc_now(),
        "source": {
            "name": "CopilotKit",
            "repo": "https://github.com/CopilotKit/CopilotKit",
            "docs": "https://docs.copilotkit.ai",
            "upstream_url": UPSTREAM_URL,
            "latest_release_observed": "v1.57.1",
        },
        "fit_for_eve": {
            "useful_for": [
                "React agent chat UI",
                "AG-UI event protocol",
                "generative UI",
                "shared agent/UI state",
                "human-in-the-loop workflows",
            ],
            "not_eve_identity": True,
            "not_memory_authority": True,
            "not_live_model_router": True,
            "requires_adapter_before_live_chat": True,
        },
        "package_metadata": package_metadata(),
        "mirror": ensure_mirror(mirror_path, timeout=args.mirror_timeout) if args.mirror else mirror_status(mirror_path),
        "npm_lab": npm_lab_status(lab_root),
        "npm_install": None,
        "node_import_probe": None,
        "eve_backend_probe": None,
        "boundary": {
            "lab_only": True,
            "writes_repo_files": False,
            "writes_lab_files": bool(args.install_npm_lab),
            "writes_eve_memory": False,
            "changes_live_chat_ui": False,
            "changes_model_routing": False,
            "external_network_used": True,
        },
        "next_step": "Build an Eve-owned CopilotKit runtime adapter that maps AG-UI/CopilotKit events to Eve's local /v1 chat bridge and reply-progress stream.",
    }
    if args.install_npm_lab:
        report["npm_install"] = install_npm_lab(lab_root, timeout=args.npm_timeout)
        report["npm_lab"] = npm_lab_status(lab_root)
        report["node_import_probe"] = node_import_probe(lab_root)
    elif args.import_probe:
        report["node_import_probe"] = node_import_probe(lab_root)
    if args.probe_eve_backend:
        report["eve_backend_probe"] = eve_backend_probe(args.eve_base_url, timeout=args.eve_timeout)

    required = [
        report["package_metadata"]["status"] == "ready",
        report["mirror"]["status"] == "ready" if args.mirror else True,
        (report["node_import_probe"] or {}).get("status") == "ready" if args.install_npm_lab or args.import_probe else True,
        (report["eve_backend_probe"] or {}).get("status") == "ready" if args.probe_eve_backend else True,
    ]
    report["status"] = "ready" if all(required) else "partial"
    return report


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe CopilotKit as an Eve UI/AG-UI substrate candidate.")
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    parser.add_argument("--no-write", action="store_true", help="Do not write the latest report artifact.")
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--lab-root", default=str(DEFAULT_LAB_ROOT))
    parser.add_argument("--mirror-path", default=str(DEFAULT_MIRROR_PATH))
    parser.add_argument("--mirror", action="store_true", help="Clone or refresh the local ignored upstream mirror.")
    parser.add_argument("--install-npm-lab", action="store_true", help="Install CopilotKit packages in the isolated lab root.")
    parser.add_argument("--import-probe", action="store_true", help="Run the node import probe against an existing lab install.")
    parser.add_argument("--probe-eve-backend", action="store_true", help="Send one compatibility request through Eve's local /v1 backend.")
    parser.add_argument("--eve-base-url", default=DEFAULT_EVE_BASE_URL)
    parser.add_argument("--npm-timeout", type=int, default=240)
    parser.add_argument("--mirror-timeout", type=int, default=300)
    parser.add_argument("--eve-timeout", type=int, default=45)
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    report = build_report(args)
    if not args.no_write:
        report_path = Path(args.report_path).expanduser()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(report_path.parent), delete=False) as handle:
            json.dump(report, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
            tmp_name = handle.name
        os.replace(tmp_name, report_path)
        report["report_path"] = str(report_path)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True))
    else:
        print(f"CopilotKit probe: {report['status']}")
        if not args.no_write:
            print(f"Report: {Path(args.report_path).expanduser()}")
    return 0 if report["status"] in {"ready", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
