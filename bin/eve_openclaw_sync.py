#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, IO, List, Optional


ROOT = (
    Path(os.environ["EVE_PROJECT_ROOT"]).expanduser().resolve()
    if os.environ.get("EVE_PROJECT_ROOT", "").strip()
    else Path(__file__).resolve().parents[1]
)
RUNTIME_ROOT = Path.home() / ".eve_runtime"
DEFAULT_WORKSPACE = RUNTIME_ROOT / "openclaw"
PYCACHE_ROOT = Path(os.environ.get("EVE_OPENCLAW_SYNC_PYCACHE", "/tmp/eve_openclaw_sync_pycache"))
LOCK_PATH = Path(os.environ.get("EVE_OPENCLAW_SYNC_LOCK", str(RUNTIME_ROOT / ".eve" / "locks" / "openclaw_sync.lock")))
GENERATED_FILE_XATTRS = ("com.apple.macl", "com.apple.provenance")
STALE_TEMP_MAX_AGE_SECONDS = int(os.environ.get("EVE_OPENCLAW_SYNC_STALE_TEMP_MAX_AGE_SECONDS", "3600"))


def acquire_sync_lock(timeout_seconds: int) -> Optional[IO[str]]:
    try:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        handle = LOCK_PATH.open("a+", encoding="utf-8")
    except OSError as exc:
        print(f"Warning: could not open OpenClaw sync lock {LOCK_PATH}: {exc}", file=sys.stderr)
        return None

    deadline = time.monotonic() + max(0, timeout_seconds)
    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            handle.seek(0)
            handle.truncate()
            handle.write(f"pid={os.getpid()} acquired_at={dt.datetime.now(dt.timezone.utc).isoformat()}\n")
            handle.flush()
            return handle
        except BlockingIOError:
            if time.monotonic() >= deadline:
                print(
                    f"Warning: another OpenClaw sync held {LOCK_PATH} for more than {timeout_seconds}s; skipping this duplicate sync.",
                    file=sys.stderr,
                )
                handle.close()
                return None
            time.sleep(0.25)
        except OSError as exc:
            print(f"Warning: could not acquire OpenClaw sync lock {LOCK_PATH}: {exc}", file=sys.stderr)
            handle.close()
            return None


def release_sync_lock(handle: Optional[IO[str]]) -> None:
    if handle is None:
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def clear_generated_file_xattrs(path: Path) -> None:
    """Generated sync artifacts must stay writable by Eve's launchd runtime."""
    for attr in GENERATED_FILE_XATTRS:
        remover = getattr(os, "removexattr", None)
        removed = False
        try:
            if callable(remover):
                remover(path, attr)
                removed = True
        except (FileNotFoundError, OSError):
            removed = False

        if removed:
            continue

        try:
            if Path("/usr/bin/xattr").exists():
                subprocess.run(
                    ["/usr/bin/xattr", "-d", attr, str(path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    check=False,
                )
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            pass


def cleanup_stale_temp_artifacts(context_dir: Path, *, older_than_seconds: int = STALE_TEMP_MAX_AGE_SECONDS) -> int:
    """Remove old sync temp files left behind by earlier interrupted/denied writes."""
    if older_than_seconds < 0:
        return 0
    cutoff = time.time() - older_than_seconds
    removed = 0
    for pattern in (".eve_status*.tmp.*", ".last_repair*.tmp.*"):
        for path in context_dir.glob(pattern):
            try:
                if not path.is_file() or path.stat().st_mtime > cutoff:
                    continue
                path.unlink()
                removed += 1
            except OSError:
                continue
    return removed


def atomic_write_text(path: Path, content: str) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"Warning: could not create OpenClaw sync directory {path.parent}: {exc}", file=sys.stderr)
        return False

    errors: List[str] = []
    clear_generated_file_xattrs(path)
    try:
        path.write_text(content, encoding="utf-8")
        try:
            path.chmod(0o644)
        except OSError:
            pass
        clear_generated_file_xattrs(path)
        return True
    except OSError as exc:
        errors.append(f"direct write failed: {exc}")

    temp_path = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(path)
        try:
            path.chmod(0o644)
        except OSError:
            pass
        clear_generated_file_xattrs(path)
        return True
    except OSError as exc:
        errors.append(f"atomic replace failed: {exc}")
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except TypeError:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                    pass
        except OSError:
            pass

    try:
        path.write_text(content, encoding="utf-8")
        clear_generated_file_xattrs(path)
        return True
    except OSError as exc:
        errors.append(f"fallback write failed: {exc}")
        if path.exists():
            try:
                try:
                    path.unlink(missing_ok=True)
                except TypeError:
                    path.unlink()
                path.write_text(content, encoding="utf-8")
                try:
                    path.chmod(0o644)
                except OSError:
                    pass
                clear_generated_file_xattrs(path)
                return True
            except OSError as unlink_exc:
                errors.append(f"unlink fallback write failed: {unlink_exc}")

    print(f"Warning: could not update OpenClaw sync artifact {path}: {'; '.join(errors)}", file=sys.stderr)
    return False


def python_file_is_valid(path: Path) -> bool:
    env = dict(os.environ)
    env.setdefault("PYTHONPYCACHEPREFIX", str(PYCACHE_ROOT))
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(path)],
        cwd=str(path.parent),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=env,
    )
    return result.returncode == 0


def eve_command_root() -> Path:
    runtime_eve = RUNTIME_ROOT / "eve.py"
    if runtime_eve.exists() and python_file_is_valid(runtime_eve):
        return RUNTIME_ROOT
    return ROOT


def build_commands() -> List[tuple[str, List[str]]]:
    eve_root = eve_command_root()
    eve_script = eve_root / "eve.py"
    return [
        ("doctor", [sys.executable, str(eve_script), "doctor"]),
        ("tasks", [sys.executable, str(eve_script), "task", "list", "--limit", "12", "--full"]),
        ("maintenance", [sys.executable, str(eve_script), "maintenance", "list", "--limit", "12", "--full"]),
        ("proposals", [sys.executable, str(eve_script), "proposal", "list", "--limit", "12", "--full"]),
        ("failures", [sys.executable, str(eve_script), "failure", "list", "--limit", "10"]),
        ("uncertainty", [sys.executable, str(eve_script), "uncertainty", "list", "--limit", "10", "--full"]),
        ("judgment", [sys.executable, str(eve_script), "judgment", "list", "--limit", "10", "--full"]),
        ("memory_status", [sys.executable, str(eve_script), "memory", "status"]),
        ("openclaw_status", [sys.executable, str(eve_script), "openclaw", "status", "--no-memory-probe"]),
    ]


def run_command(command: List[str], timeout: int = 120, cwd: Path | None = None) -> Dict[str, object]:
    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd or ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except OSError as exc:
        return {
            "cmd": command,
            "returncode": 127,
            "stdout": "",
            "stderr": f"Command could not start: {exc}",
        }

    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return {
            "cmd": command,
            "returncode": process.returncode,
            "stdout": (stdout or "").strip(),
            "stderr": (stderr or "").strip(),
        }
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except OSError:
            pass
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass
            stdout, stderr = process.communicate()
        timeout_message = f"Command timed out after {timeout} seconds: {' '.join(command)}"
        stderr_text = "\n".join(part for part in ((stderr or "").strip(), timeout_message) if part)
        return {
            "cmd": command,
            "returncode": 124,
            "stdout": (stdout or "").strip(),
            "stderr": stderr_text,
            "timed_out": True,
        }


def build_status_payload() -> Dict[str, object]:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    command_root = eve_command_root()
    commands = {name: run_command(command, cwd=command_root) for name, command in build_commands()}
    return {
        "generated_at": now,
        "repo_root": str(ROOT),
        "command_root": str(command_root),
        "commands": commands,
    }


def compact_text(value: object, *, limit: int = 700) -> str:
    text = " ".join(str(value or "").split())
    if limit > 0 and len(text) > limit:
        return text[: max(0, limit - 1)].rstrip() + "…"
    return text


def interesting_lines(value: object, *, limit: int = 8) -> List[str]:
    markers = (
        "degraded",
        "failure",
        "failed",
        "blocked",
        "stale",
        "gateway",
        "sync",
        "daemon",
        "background cadence",
        "service_health_summary",
        "last loop",
        "memory",
        "openclaw",
        "warning",
    )
    lines: List[str] = []
    for raw_line in str(value or "").splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue
        lowered = line.lower()
        if any(marker in lowered for marker in markers):
            lines.append(line)
        if len(lines) >= limit:
            break
    if not lines:
        for raw_line in str(value or "").splitlines():
            line = " ".join(raw_line.split())
            if line:
                lines.append(line)
            if len(lines) >= min(3, limit):
                break
    return lines


def summarize_command(name: str, result: Dict[str, object]) -> Dict[str, object]:
    stdout = str(result.get("stdout") or "")
    stderr = str(result.get("stderr") or "")
    signal_lines = interesting_lines("\n".join(part for part in [stdout, stderr] if part), limit=8)
    return {
        "name": name,
        "returncode": result.get("returncode"),
        "command": " ".join(result.get("cmd") or []),
        "stdout_chars": len(stdout),
        "stderr_chars": len(stderr),
        "signals": [compact_text(line, limit=220) for line in signal_lines],
        "stderr_excerpt": compact_text(stderr, limit=700),
    }


def build_brief_payload(payload: Dict[str, object]) -> Dict[str, object]:
    commands = payload.get("commands", {})
    summarized: Dict[str, object] = {}
    if isinstance(commands, dict):
        for name, result in commands.items():
            if isinstance(result, dict):
                summarized[name] = summarize_command(str(name), result)
    return {
        "generated_at": payload.get("generated_at"),
        "repo_root": payload.get("repo_root"),
        "command_root": payload.get("command_root"),
        "commands": summarized,
    }


def render_brief_markdown(payload: Dict[str, object]) -> str:
    lines = [
        "# Eve Runtime Snapshot Brief",
        "",
        f"- Generated at: `{payload.get('generated_at')}`",
        f"- Repo root: `{payload.get('repo_root')}`",
        f"- Command root: `{payload.get('command_root')}`",
        "",
        "Use this brief as OpenClaw's first repair context. Read the full `eve_status.md` only for a named excerpt after the brief identifies a concrete gap.",
        "",
    ]
    commands = payload.get("commands", {})
    if isinstance(commands, dict):
        for name, result in commands.items():
            if not isinstance(result, dict):
                continue
            lines.extend(
                [
                    f"## {name}",
                    "",
                    f"- Return code: `{result.get('returncode')}`",
                    f"- Output size: stdout {result.get('stdout_chars')}, stderr {result.get('stderr_chars')}",
                    f"- Command: `{result.get('command')}`",
                    "",
                ]
            )
            signals = result.get("signals") if isinstance(result.get("signals"), list) else []
            if signals:
                lines.append("Signals:")
                lines.extend(f"- {signal}" for signal in signals[:8])
                lines.append("")
            if result.get("stderr_excerpt"):
                lines.extend(["Stderr excerpt:", "", "```text", str(result.get("stderr_excerpt")), "```", ""])
    return "\n".join(lines).rstrip() + "\n"


def render_markdown(payload: Dict[str, object]) -> str:
    lines = [
        "# Eve Runtime Snapshot",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Repo root: `{payload['repo_root']}`",
        f"- Command root: `{payload.get('command_root')}`",
        "",
        "Use `eve_status_brief.md` as the first OpenClaw repair context. This full snapshot is for targeted follow-up excerpts.",
        "",
    ]
    commands = payload.get("commands", {})
    for name, result in commands.items():
        if not isinstance(result, dict):
            continue
        lines.extend(
            [
                f"## {name}",
                "",
                f"- Return code: `{result.get('returncode')}`",
                f"- Command: `{ ' '.join(result.get('cmd') or []) }`",
                "",
                "```text",
                (result.get("stdout") or "(no stdout)")[:4000],
                "```",
            ]
        )
        stderr = result.get("stderr") or ""
        if stderr:
            lines.extend(["", "```text", stderr[:1600], "```"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def append_memory_note(workspace: Path, payload: Dict[str, object]) -> bool:
    # Operational status belongs in context/last_repair.md (current-state,
    # atomically overwritten), never in memory/YYYY-MM-DD.md: the dreaming
    # pipeline ingests the daily notes, and repair boilerplate there gets
    # promoted into MEMORY.md as noise (see 2026-05-23 incident).
    context_dir = workspace / "context"
    try:
        context_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"Warning: could not create OpenClaw context directory {context_dir}: {exc}", file=sys.stderr)
        return False
    repair_path = context_dir / "last_repair.md"

    brief = build_brief_payload(payload)
    commands = brief.get("commands", {}) if isinstance(brief.get("commands"), dict) else {}

    entry_lines = [
        f"## Sync {payload['generated_at']}",
        "",
        "Compact repair context refresh:",
        "",
    ]
    for name in ["doctor", "tasks", "maintenance", "openclaw_status"]:
        result = commands.get(name)
        if not isinstance(result, dict):
            continue
        entry_lines.extend([f"### {name}", ""])
        signals = result.get("signals") if isinstance(result.get("signals"), list) else []
        if signals:
            entry_lines.extend(f"- {signal}" for signal in signals[:5])
        else:
            entry_lines.append("- no compact signal")
        entry_lines.append("")

    return atomic_write_text(repair_path, "\n".join(entry_lines).rstrip() + "\n")


def write_lived_daily_note(workspace: Path) -> bool:
    """Write today's LIVED daily note from real material: the user's and Eve's actual
    exchanges (messages.jsonl) and the relationship memory (human_context.json).

    The dreaming pipeline ingests memory/YYYY-MM-DD.md daily notes — this is what
    lets Eve dream about her life with the user instead of her own telemetry. Keep
    operational status OUT of these files (it goes to context/last_repair.md).
    Also refreshes context/eve_lived_brief.md for heartbeat turns."""
    eve_dir = RUNTIME_ROOT / ".eve"
    now = dt.datetime.now(dt.timezone.utc)
    today = dt.datetime.now().strftime("%Y-%m-%d")
    cutoff = now - dt.timedelta(hours=24)

    exchanges: List[str] = []
    messages_path = eve_dir / "messages.jsonl"
    if messages_path.exists():
        try:
            for line in messages_path.read_text(encoding="utf-8").splitlines()[-200:]:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = msg.get("timestamp") or ""
                try:
                    when = dt.datetime.fromisoformat(ts)
                except ValueError:
                    continue
                if when < cutoff:
                    continue
                sender = msg.get("sender") or "?"
                body = (msg.get("body") or "").strip().replace("\n", " ")
                if not body:
                    continue
                exchanges.append(f"- {when.strftime('%H:%M')} {sender}: {body[:240]}")
        except OSError as exc:
            print(f"Warning: could not read messages for lived note: {exc}", file=sys.stderr)

    relationship_lines: List[str] = []
    preoccupations: List[str] = []
    context_path = eve_dir / "human_context.json"
    if context_path.exists():
        try:
            human = json.loads(context_path.read_text(encoding="utf-8"))
            relationship = human.get("relationship_memory") or {}
            for key, label in [("open_loops", "Open loop"), ("care_notes", "Care note")]:
                values = relationship.get(key)
                if isinstance(values, list):
                    relationship_lines.extend(f"- {label}: {str(v)[:240]}" for v in values[:5])
                elif isinstance(values, str) and values.strip():
                    relationship_lines.append(f"- {label}: {values.strip()[:240]}")
            self_model = human.get("self_model") or {}
            current = self_model.get("current_preoccupations")
            if isinstance(current, list):
                preoccupations = [str(v)[:200] for v in current[:3]]
            elif isinstance(current, str) and current.strip():
                preoccupations = [current.strip()[:200]]
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Warning: could not read human context for lived note: {exc}", file=sys.stderr)

    if not exchanges and not relationship_lines and not preoccupations:
        print("No lived material in the last 24h; skipping lived daily note.")
        return True

    marker = f"<!-- eve-lived-note:{today} -->"
    lines = [marker, f"## Lived notes — {today}", ""]
    if exchanges:
        lines.extend(["### Today with the user", "", *exchanges[-20:], ""])
    if relationship_lines:
        lines.extend(["### Relationship threads", "", *relationship_lines, ""])
    if preoccupations:
        lines.extend(["### On my mind", "", *(f"- {p}" for p in preoccupations), ""])
    note = "\n".join(lines).rstrip() + "\n"

    memory_dir = workspace / "memory"
    try:
        memory_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"Warning: could not create OpenClaw memory directory {memory_dir}: {exc}", file=sys.stderr)
        return False
    memory_path = memory_dir / f"{today}.md"
    try:
        existing = memory_path.read_text(encoding="utf-8") if memory_path.exists() else ""
    except OSError:
        existing = ""
    if marker in existing:
        # one lived section per day: replace from the marker onward
        existing = existing.split(marker)[0].rstrip() + ("\n\n" if existing.split(marker)[0].strip() else "")
    ok = atomic_write_text(memory_path, existing + note)
    clear_generated_file_xattrs(memory_path)

    brief = ["# Lived brief", "", f"Updated {now.isoformat(timespec='seconds')}", "", note]
    ok_brief = atomic_write_text(workspace / "context" / "eve_lived_brief.md", "\n".join(brief))
    if ok and ok_brief:
        print(f"Wrote lived daily note to {memory_path} and refreshed eve_lived_brief.md")
    return ok and ok_brief


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Eve runtime state into the OpenClaw repair workspace.")
    parser.add_argument("--workspace", default=str(DEFAULT_WORKSPACE), help="OpenClaw workspace path.")
    parser.add_argument("--append-memory", action="store_true", help="Append a short note to today's OpenClaw memory log.")
    parser.add_argument("--lived-note", action="store_true", help="Write today's lived daily note (real exchanges + relationship memory) for the dreaming pipeline.")
    parser.add_argument(
        "--lock-timeout",
        type=int,
        default=int(os.environ.get("EVE_OPENCLAW_SYNC_LOCK_TIMEOUT", "120")),
        help="Seconds to wait for another OpenClaw sync writer before skipping this duplicate run.",
    )
    args = parser.parse_args()

    lock_handle = acquire_sync_lock(args.lock_timeout)
    if lock_handle is None:
        print("Command root: unavailable")
        print("Skipped duplicate OpenClaw sync because another sync writer is already active.")
        return 0

    workspace = Path(args.workspace).expanduser().resolve()
    try:
        context_dir = workspace / "context"
        try:
            context_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(f"Warning: could not create OpenClaw context directory {context_dir}: {exc}", file=sys.stderr)

        payload = build_status_payload()
        brief_payload = build_brief_payload(payload)
        write_results = [
            atomic_write_text(context_dir / "eve_status.json", json.dumps(payload, indent=2) + "\n"),
            atomic_write_text(context_dir / "eve_status.md", render_markdown(payload)),
            atomic_write_text(context_dir / "eve_status_brief.json", json.dumps(brief_payload, indent=2) + "\n"),
            atomic_write_text(context_dir / "eve_status_brief.md", render_brief_markdown(brief_payload)),
        ]

        if args.append_memory:
            write_results.append(append_memory_note(workspace, payload))

        if args.lived_note:
            write_results.append(write_lived_daily_note(workspace))

        print(f"Command root: {payload.get('command_root')}")
        if all(write_results):
            removed_temps = cleanup_stale_temp_artifacts(context_dir)
            if removed_temps:
                print(f"Removed {removed_temps} stale OpenClaw sync temp artifact(s) from {context_dir}")
            print(f"Wrote OpenClaw sync artifacts into {context_dir}")
        else:
            print(f"OpenClaw sync completed, but one or more context artifacts could not be updated in {context_dir}")
        return 0
    finally:
        release_sync_lock(lock_handle)


if __name__ == "__main__":
    raise SystemExit(main())
