#!/usr/bin/env python3
"""Preflight and bootstrap a source checkout of Eve.

This installer deliberately stops short of downloading models, enabling hosted
providers, or installing a background service.  It creates the locked Python
environment, installs a relocation-safe ``eve`` source command, and, unless
asked not to, builds Eve's local runtime mirror.  The operator chooses models
and service installation after reviewing ``eve doctor``.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence


MIN_PYTHON = (3, 12)
MAX_PYTHON = (3, 15)
BOOTSTRAP_REPORT_SCHEMA_VERSION = 2
REQUIRED_SOURCE_FILES = (
    "eve.py",
    "eve_platform.py",
    "pyproject.toml",
    "uv.lock",
)
INSTALL_OUTPUT_TAIL_BYTES = 8 * 1024


class InstallCommandError(RuntimeError):
    """Describe one failed install step without losing partial-progress truth."""

    def __init__(
        self,
        *,
        command_index: int,
        command: Sequence[str],
        returncode: int | None,
        output_tail: str = "",
        cause: BaseException | None = None,
    ) -> None:
        self.command_index = command_index
        self.command = tuple(command)
        self.returncode = returncode
        self.output_tail = output_tail
        self.cause = cause
        if returncode is None:
            detail = str(cause) if cause else "the command could not be started"
        else:
            detail = f"the command exited with code {returncode}"
        super().__init__(detail)


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
        "schema_version": BOOTSTRAP_REPORT_SCHEMA_VERSION,
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


def source_cli_path(root: Path, *, system: str | None = None) -> Path:
    """Return the source-install launcher path for the current platform."""

    if (system or platform.system()) == "Windows":
        return root / ".venv" / "Scripts" / "eve.cmd"
    return root / ".venv" / "bin" / "eve"


def source_cli_content(*, system: str | None = None) -> str:
    """Build a relocation-safe launcher for a source checkout.

    This deliberately remains a source launcher rather than pretending the
    monolith is already a distributable Python package.  Both forms resolve
    ``eve.py`` relative to the launcher inside ``.venv`` so moving or renaming
    the checkout does not leave an embedded absolute path behind.
    """

    if (system or platform.system()) == "Windows":
        return (
            "@echo off\r\n"
            "setlocal\r\n"
            'set "SCRIPT_DIR=%~dp0"\r\n'
            'for %%I in ("%SCRIPT_DIR%\\..\\..") do set "ROOT_DIR=%%~fI"\r\n'
            '"%SCRIPT_DIR%python.exe" "%ROOT_DIR%\\eve.py" %*\r\n'
            "exit /b %ERRORLEVEL%\r\n"
        )
    return (
        "#!/bin/sh\n"
        "set -eu\n"
        'SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"\n'
        'ROOT_DIR="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd -P)"\n'
        'exec "${SCRIPT_DIR}/python" "${ROOT_DIR}/eve.py" "$@"\n'
    )


def install_source_cli(root: Path, *, system: str | None = None) -> Path:
    """Atomically install the stable ``eve`` source-checkout command."""

    root = root.expanduser().resolve()
    python = venv_python(root, system=system)
    if not python.is_file():
        raise FileNotFoundError(
            f"Eve's locked interpreter is missing at {python}; run `uv sync --frozen` first."
        )
    if not (root / "eve.py").is_file():
        raise FileNotFoundError(f"Eve's compatibility entrypoint is missing at {root / 'eve.py'}.")

    destination = source_cli_path(root, system=system)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=str(destination.parent),
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(source_cli_content(system=system))
            handle.flush()
            os.fsync(handle.fileno())
        if (system or platform.system()) != "Windows":
            temporary.chmod(
                stat.S_IRUSR
                | stat.S_IWUSR
                | stat.S_IXUSR
                | stat.S_IRGRP
                | stat.S_IXGRP
                | stat.S_IROTH
                | stat.S_IXOTH
            )
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


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
    python = str(venv_python(root, system=system))
    commands.append(
        [
            python,
            str(root / "bin" / "eve_bootstrap.py"),
            "--root",
            str(root),
            "install-cli",
        ]
    )
    if sync_runtime:
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
        "Next: configure a local llama.cpp host, then run `.venv/bin/eve doctor`.",
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


def install_output_tail(handle, *, limit: int = INSTALL_OUTPUT_TAIL_BYTES) -> str:
    """Read a bounded UTF-8 tail from a seekable binary command-output file."""

    handle.flush()
    handle.seek(0, os.SEEK_END)
    size = handle.tell()
    start = max(0, size - max(1, limit))
    handle.seek(start)
    output = handle.read().decode("utf-8", errors="replace").strip()
    return f"…\n{output}" if start > 0 and output else output


def execute_install(
    root: Path,
    commands: Sequence[Sequence[str]],
    *,
    env: Mapping[str, str] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    isolate_output: bool = False,
) -> list[dict[str, object]]:
    process_env = dict(os.environ if env is None else env)
    process_env.setdefault(
        "PYTHONPYCACHEPREFIX",
        str(Path(tempfile.gettempdir()) / "eve_bootstrap_pycache"),
    )
    receipts: list[dict[str, object]] = []
    for index, command in enumerate(commands):
        command_parts = list(command)
        try:
            if isolate_output:
                with tempfile.TemporaryFile(mode="w+b") as command_output:
                    try:
                        completed = runner(
                            command_parts,
                            cwd=str(root),
                            env=process_env,
                            text=True,
                            check=True,
                            stdout=command_output,
                            stderr=subprocess.STDOUT,
                        )
                    except subprocess.CalledProcessError as exc:
                        raise InstallCommandError(
                            command_index=index,
                            command=command_parts,
                            returncode=exc.returncode,
                            output_tail=install_output_tail(command_output),
                            cause=exc,
                        ) from exc
            else:
                completed = runner(
                    command_parts,
                    cwd=str(root),
                    env=process_env,
                    text=True,
                    check=True,
                )
        except InstallCommandError:
            raise
        except subprocess.CalledProcessError as exc:
            raise InstallCommandError(
                command_index=index,
                command=command_parts,
                returncode=exc.returncode,
                cause=exc,
            ) from exc
        except OSError as exc:
            raise InstallCommandError(
                command_index=index,
                command=command_parts,
                returncode=None,
                cause=exc,
            ) from exc

        returncode = int(getattr(completed, "returncode", 0))
        receipts.append({"command_index": index, "command": command_parts, "returncode": returncode})
    return receipts


def install_failure_payload(
    payload: Mapping[str, object],
    failure: InstallCommandError,
) -> dict[str, object]:
    result = {
        **payload,
        "ok": False,
        "install_status": "failed",
        "completed_command_count": failure.command_index,
        "failed_command_index": failure.command_index,
        "failed_command": list(failure.command),
        "returncode": failure.returncode,
        "error": str(failure),
        "rollback_performed": False,
    }
    if failure.output_tail:
        result["output_tail"] = failure.output_tail
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=source_root(), help="Eve source checkout")
    parser.add_argument("--json", action="store_true", help="Print machine-readable output")
    subparsers = parser.add_subparsers(dest="command", required=True)
    check_parser = subparsers.add_parser("check", help="Check prerequisites without changing the machine")
    check_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    install_cli = subparsers.add_parser(
        "install-cli",
        help="Install the relocation-safe eve command into the locked source environment",
    )
    install_cli.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    install = subparsers.add_parser("install", help="Create the locked environment and local runtime mirror")
    install.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    install.add_argument("--extra", action="append", default=[], choices=("dev", "infra", "techlab", "oss-lab"))
    install.add_argument("--skip-runtime-sync", action="store_true")
    install.add_argument("--dry-run", action="store_true", help="Print the exact commands without running them")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.expanduser().resolve()
    if args.command == "install-cli":
        try:
            path = install_source_cli(root)
        except (FileNotFoundError, OSError) as exc:
            if args.json:
                print(
                    json.dumps(
                        {
                            "schema_version": BOOTSTRAP_REPORT_SCHEMA_VERSION,
                            "ok": False,
                            "error": str(exc),
                        },
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                print(f"Could not install Eve's source command: {exc}", file=sys.stderr)
            return 1
        payload = {
            "schema_version": BOOTSTRAP_REPORT_SCHEMA_VERSION,
            "ok": True,
            "launcher": str(path),
            "source_root": str(root),
        }
        print(json.dumps(payload, indent=2, sort_keys=True) if args.json else f"Installed Eve source command at {path}")
        return 0

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
    payload = {
        **report,
        "dry_run": bool(args.dry_run),
        "commands": [list(item) for item in commands],
        "completed_command_count": 0,
    }
    if not args.json:
        print(render_report(report))
        print("\nInstall plan:")
        for command in commands:
            print("  " + command_text(command))

    if not report["ok"]:
        if args.json:
            print(json.dumps({**payload, "install_status": "blocked"}, indent=2, sort_keys=True))
        return 1
    if args.dry_run:
        if args.json:
            print(json.dumps({**payload, "install_status": "planned"}, indent=2, sort_keys=True))
        return 0
    try:
        receipts = execute_install(root, commands, isolate_output=args.json)
    except InstallCommandError as exc:
        failure = install_failure_payload(payload, exc)
        if args.json:
            print(json.dumps(failure, indent=2, sort_keys=True))
        else:
            print(
                f"\nInstall stopped at step {exc.command_index + 1} of {len(commands)}: "
                f"{command_text(exc.command)}",
                file=sys.stderr,
            )
            print(f"Reason: {exc}", file=sys.stderr)
            if exc.output_tail:
                print("Command output (bounded tail):", file=sys.stderr)
                print(exc.output_tail, file=sys.stderr)
            print("No later install steps were run; completed earlier steps were not rolled back.", file=sys.stderr)
        return 1
    if args.json:
        print(
            json.dumps(
                {
                    **payload,
                    "install_status": "completed",
                    "completed_command_count": len(receipts),
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print()
        for line in completion_lines(runtime_synced=not args.skip_runtime_sync):
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
