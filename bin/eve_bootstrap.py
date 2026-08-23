#!/usr/bin/env python3
"""Preflight and bootstrap a source checkout of Eve.

This installer deliberately stops short of downloading models, enabling hosted
providers, or installing a background service.  It creates the locked Python
environment and, unless asked not to, builds Eve's local runtime mirror.  The
operator chooses models and service installation after reviewing ``eve doctor``.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence


MIN_PYTHON = (3, 12)
MAX_PYTHON = (3, 15)
REQUIRED_SOURCE_FILES = (
    "eve.py",
    "eve_platform.py",
    "pyproject.toml",
    "uv.lock",
)


def source_root() -> Path:
    return Path(__file__).resolve().parents[1]


def supported_python(version: Sequence[int]) -> bool:
    current = tuple(version[:2])
    return MIN_PYTHON <= current < MAX_PYTHON


def check(
    check_id: str,
    status: str,
    detail: str,
    *,
    required: bool,
    remediation: str = "",
) -> dict[str, object]:
    return {
        "id": check_id,
        "status": status,
        "required": required,
        "detail": detail,
        "remediation": remediation,
    }


def preflight_report(
    root: Path,
    *,
    which: Callable[[str], str | None] = shutil.which,
    version: Sequence[int] = sys.version_info,
    system: str | None = None,
) -> dict[str, object]:
    root = root.expanduser().resolve()
    system_name = system or platform.system()
    checks: list[dict[str, object]] = []

    checks.append(
        check(
            "bootstrap_python",
            "pass" if supported_python(version) else "warning",
            "Python %d.%d" % tuple(version[:2]),
            required=False,
            remediation="uv will provision Python 3.12 for Eve's locked environment.",
        )
    )

    missing = [relative for relative in REQUIRED_SOURCE_FILES if not (root / relative).is_file()]
    checks.append(
        check(
            "source_checkout",
            "fail" if missing else "pass",
            "missing: %s" % ", ".join(missing) if missing else "required source files present",
            required=True,
            remediation="Run this command from a complete Eve source checkout.",
        )
    )

    uv_path = which("uv")
    checks.append(
        check(
            "uv",
            "pass" if uv_path else "fail",
            uv_path or "uv was not found on PATH",
            required=True,
            remediation="Install uv from https://docs.astral.sh/uv/ and rerun the preflight.",
        )
    )

    git_path = which("git")
    checks.append(
        check(
            "git",
            "pass" if git_path else "warning",
            git_path or "git was not found on PATH",
            required=False,
            remediation="Install Git to pull updates and contribute changes.",
        )
    )

    llama_path = which("llama-server")
    checks.append(
        check(
            "llama_cpp",
            "pass" if llama_path else "warning",
            llama_path or "llama-server was not found on PATH",
            required=False,
            remediation="Install llama.cpp or configure an existing OpenAI-compatible local model host before starting Eve.",
        )
    )

    if system_name == "Darwin":
        xcode_path = which("xcodebuild")
        checks.append(
            check(
                "xcode_tools",
                "pass" if xcode_path else "warning",
                xcode_path or "xcodebuild was not found on PATH",
                required=False,
                remediation="Install Xcode command-line tools before building Eve.app.",
            )
        )

    failures = [item for item in checks if item["required"] and item["status"] == "fail"]
    warnings = [item for item in checks if item["status"] == "warning"]
    return {
        "schema_version": 1,
        "root": str(root),
        "platform": system_name,
        "ok": not failures,
        "failure_count": len(failures),
        "warning_count": len(warnings),
        "checks": checks,
    }


def venv_python(root: Path, *, system: str | None = None) -> Path:
    if (system or platform.system()) == "Windows":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def install_plan(
    root: Path,
    *,
    uv_path: str = "uv",
    extras: Iterable[str] = (),
    sync_runtime: bool = True,
    system: str | None = None,
) -> list[list[str]]:
    root = root.expanduser().resolve()
    sync_command = [uv_path, "sync", "--python", "3.12", "--frozen"]
    for extra in dict.fromkeys(item.strip() for item in extras if item.strip()):
        sync_command.extend(["--extra", extra])
    commands = [sync_command]
    if sync_runtime:
        python = str(venv_python(root, system=system))
        commands.extend(
            [
                [python, str(root / "eve.py"), "runtime", "sync"],
                [python, str(root / "eve.py"), "runtime", "truth", "--json"],
            ]
        )
    return commands


def command_text(command: Sequence[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def completion_lines(*, runtime_synced: bool) -> tuple[str, ...]:
    if runtime_synced:
        ready = "Eve's source environment and runtime mirror are ready."
    else:
        ready = "Eve's source environment is ready; the runtime mirror was intentionally not created."
    return (
        ready,
        "Next: configure a local llama.cpp host, then run `.venv/bin/python eve.py doctor`.",
        "Background services are not installed automatically.",
    )


def render_report(report: Mapping[str, object]) -> str:
    lines = [
        "Eve source bootstrap preflight",
        "root: %s" % report["root"],
        "platform: %s" % report["platform"],
    ]
    for item in report["checks"]:  # type: ignore[index]
        marker = {"pass": "OK", "warning": "WARN", "fail": "FAIL"}[item["status"]]
        lines.append("[%s] %s: %s" % (marker, item["id"], item["detail"]))
        if item["status"] != "pass" and item.get("remediation"):
            lines.append("  next: %s" % item["remediation"])
    lines.append("result: %s" % ("ready" if report["ok"] else "blocked"))
    return "\n".join(lines)


def execute_install(
    root: Path,
    commands: Sequence[Sequence[str]],
    *,
    env: Mapping[str, str] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    process_env = dict(os.environ if env is None else env)
    process_env.setdefault("PYTHONPYCACHEPREFIX", "/tmp/eve_bootstrap_pycache")
    for command in commands:
        runner(
            list(command),
            cwd=str(root),
            env=process_env,
            text=True,
            check=True,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=source_root(), help="Eve source checkout")
    parser.add_argument("--json", action="store_true", help="Print machine-readable output")
    subparsers = parser.add_subparsers(dest="command", required=True)
    check_parser = subparsers.add_parser("check", help="Check prerequisites without changing the machine")
    check_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    install = subparsers.add_parser("install", help="Create the locked environment and local runtime mirror")
    install.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    install.add_argument("--extra", action="append", default=[], choices=("dev", "infra", "techlab", "oss-lab"))
    install.add_argument("--skip-runtime-sync", action="store_true")
    install.add_argument("--dry-run", action="store_true", help="Print the exact commands without running them")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.expanduser().resolve()
    report = preflight_report(root)
    if args.command == "check":
        print(json.dumps(report, indent=2, sort_keys=True) if args.json else render_report(report))
        return 0 if report["ok"] else 1

    uv_item = next(item for item in report["checks"] if item["id"] == "uv")
    uv_path = str(uv_item["detail"]) if uv_item["status"] == "pass" else "uv"
    commands = install_plan(
        root,
        uv_path=uv_path,
        extras=args.extra,
        sync_runtime=not args.skip_runtime_sync,
    )
    payload = {**report, "dry_run": bool(args.dry_run), "commands": [list(item) for item in commands]}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_report(report))
        print("\nInstall plan:")
        for command in commands:
            print("  " + command_text(command))

    if not report["ok"]:
        return 1
    if args.dry_run:
        return 0
    execute_install(root, commands)
    if not args.json:
        print()
        for line in completion_lines(runtime_synced=not args.skip_runtime_sync):
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
