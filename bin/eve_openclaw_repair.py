#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import selectors
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path


ROOT = (
    Path(os.environ["EVE_PROJECT_ROOT"]).expanduser().resolve()
    if os.environ.get("EVE_PROJECT_ROOT", "").strip()
    else Path(__file__).resolve().parents[1]
)
DEFAULT_PROFILE = "eve-repair"
DEFAULT_WORKSPACE = ROOT / "openclaw"
DEFAULT_AGENT = "eve-repair"
SYNC_SCRIPT = ROOT / "bin" / "eve_openclaw_sync.py"
OPENCLAW_COMMAND_PATHS = [
    "/opt/homebrew/bin/openclaw",
    "/usr/local/bin/openclaw",
    "/opt/homebrew/lib/node_modules/openclaw/dist/index.js",
]


DEFAULT_REPAIR_PROMPT = """You are Eve's OpenClaw self-repair sidecar working inside the Eve repository.

Read the workspace instructions and the latest context/eve_status_brief.md snapshot first.
Then do exactly one bounded repair cycle:
0. Inspect the fresh logs and current doctor output before deciding anything is broken.
   Treat the newest "Generated at" snapshot in context/eve_status_brief.md as authoritative if it conflicts with older session memory.
   Read the full context/eve_status.md only for a targeted excerpt after the brief identifies a concrete gap.
   Before calling a loop stale or frozen, compare its last timestamp against the configured interval in the context.
   A job that is not due yet is not drift.
   Prefer the current "Background cadence" and "service_health_summary" over isolated old daemon log lines.
   If the daemon loop is fresh and degraded signals are none, treat older daemon.err.log entries as historical noise unless they are newer than the current loop or still reproducible.
   For OpenClaw context settings, use only supported schema keys. Current focused contextLimits keys are memoryGetMaxChars, memoryGetDefaultLines, toolResultMaxChars, and postCompactionMaxChars. Do not recommend unsupported keys such as contextWindow, contextWindowLimit, or maxContext.
1. Identify the highest-leverage issue you can verify locally.
2. Prefer a fix that improves reliability, self-repair, maintenance, or operator clarity.
3. Make the smallest real change that resolves the issue.
4. Verify with an exact command.
5. Summarize what changed, what you verified, and what still remains.

Do not do broad refactors, model migrations, or destructive cleanup unless the evidence clearly requires it.
Do not change auth files, secrets, or unrelated UI polish.
If a fix would be risky or ambiguous, stop after diagnosis and write the smallest safe next step instead.
Return exactly one strict JSON object and no prose:
{"status":"repaired|diagnosed|blocked","issue":"...","action":"...","verified":"...","next_step":"..."}
"""

STRICT_RESPONSE_CONTRACT = """Output contract, non-negotiable:
- Return exactly one raw JSON object only.
- Do not include markdown, code fences, labels, analysis, or prose before or after the object.
- Required keys: status, issue, action, verified, next_step.
- status must be exactly one of: repaired, diagnosed, blocked.
- issue, action, verified, and next_step must be strings.
- If you made no edit, use status "diagnosed".
- If you cannot safely proceed, use status "blocked".
"""

CONTINUATION_PROMPT = """Continue the same repair turn from the tool results already gathered.
Do not narrate and do not call another tool unless the previous tool result is truly missing.
Return the final raw JSON object now, using the required keys and allowed status values.
"""

CONTRACT_RETRY_PROMPT = """Your previous assistant message violated the output contract.
Do not call tools.
Use the facts already gathered in this session and return exactly one raw JSON object only.
No markdown, no code fence, no explanation, no lead-in text.
"""

HARD_FAILURE_MARKERS = (
    "context overflow",
    "prompt too large",
    "roles must alternate",
    "message ordering conflict",
    "agent couldn't generate a response",
    "tool use failed",
    "rawerror",
)


def enforce_response_contract(message: str) -> str:
    prompt = message.strip()
    if not prompt:
        prompt = DEFAULT_REPAIR_PROMPT.strip()
    return f"{prompt}\n\n{STRICT_RESPONSE_CONTRACT.strip()}"


def parse_json_object(text: str) -> dict:
    candidate = text.strip()
    if not candidate:
        return {}
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def extract_cli_reply_text(text: str) -> str:
    """Extract the final assistant text from OpenClaw's CLI JSON envelope."""
    payload = parse_json_object(text)
    if not payload:
        return ""
    for key in ("reply", "text", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    payloads = payload.get("payloads")
    if isinstance(payloads, list):
        for item in reversed(payloads):
            if not isinstance(item, dict):
                continue
            value = item.get("text")
            if isinstance(value, str) and value.strip():
                return value.strip()
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    for key in ("finalAssistantVisibleText", "finalAssistantRawText"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def openclaw_needs_continuation(stdout: str, stderr: str) -> bool:
    for text in (stdout, stderr):
        payload = parse_json_object(text)
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        completion = meta.get("completion") if isinstance(meta.get("completion"), dict) else {}
        stop_reason = str(meta.get("stopReason") or completion.get("stopReason") or completion.get("finishReason") or "").lower()
        if stop_reason in {"tooluse", "tool_use", "tool-use"}:
            return True
        if payload.get("replayInvalid") is True and stop_reason:
            return True
    lowered = f"{stdout}\n{stderr}".lower()
    return '"stopreason":"tooluse"' in lowered or '"stopreason": "tooluse"' in lowered


def repair_contract_retry_needed(stdout: str, stderr: str) -> bool:
    for text in (stdout, stderr):
        payload = parse_json_object(text)
        error = str(payload.get("error") or "").lower()
        if error:
            if "strict json" in error or "missing required keys" in error:
                return True
            if "status must be" in error or "values must be strings" in error:
                return True
            if "assistant did not return a final strict json" in error:
                return True
        reply = extract_cli_reply_text(text)
        if reply:
            _, contract_error = parse_strict_repair_json(reply)
            if contract_error:
                return True
    return False


def run(command: list[str], cwd: Path | None = None, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    env = openclaw_env()
    return subprocess.run(
        command,
        cwd=str(cwd or ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )


def openclaw_command() -> str:
    candidates = [os.environ.get("OPENCLAW_BIN"), shutil.which("openclaw"), *OPENCLAW_COMMAND_PATHS]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.exists():
            return str(path)
    raise SystemExit("OpenClaw CLI was not found. Expected `openclaw` on PATH or at /opt/homebrew/bin/openclaw.")


def openclaw_env() -> dict[str, str]:
    env = os.environ.copy()
    path_parts = [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/Applications/Codex.app/Contents/Resources",
        env.get("PATH", ""),
    ]
    env["PATH"] = ":".join(part for part in path_parts if part)
    return env


def openclaw_state_dir(profile: str) -> Path:
    env_override = os.environ.get("OPENCLAW_EVE_STATE_DIR")
    if env_override:
        return Path(env_override).expanduser().resolve()
    return (Path.home() / f".openclaw-{profile}").resolve()


def openclaw_session_file(profile: str, agent: str, session_id: str | None = None) -> Path | None:
    sessions_dir = openclaw_state_dir(profile) / "agents" / agent / "sessions"
    if session_id:
        direct = sessions_dir / f"{session_id}.jsonl"
        if direct.exists():
            return direct.resolve()
    sessions_index = sessions_dir / "sessions.json"
    if not sessions_index.exists():
        return None
    try:
        data = json.loads(sessions_index.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    preferred_keys = []
    if session_id:
        preferred_keys.extend(
            [
                f"agent:{agent}:explicit:{session_id}",
                f"agent:{agent}:{session_id}",
                session_id,
            ]
        )
    preferred_keys.append(f"agent:{agent}:main")
    session_meta = None
    for key in preferred_keys:
        candidate = data.get(key)
        if isinstance(candidate, dict):
            session_meta = candidate
            break
    if not isinstance(session_meta, dict):
        for key, value in data.items():
            if session_id and key.startswith(f"agent:{agent}:") and key.endswith(session_id) and isinstance(value, dict):
                session_meta = value
                break
            if not session_id and key.startswith(f"agent:{agent}:") and isinstance(value, dict):
                session_meta = value
                break
    if not isinstance(session_meta, dict):
        return None

    session_id = session_meta.get("sessionId")
    if not session_id:
        return None

    codex_meta = sessions_dir / f"{session_id}.jsonl.codex-app-server.json"
    if codex_meta.exists():
        try:
            meta = json.loads(codex_meta.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
        session_file = meta.get("sessionFile")
        if isinstance(session_file, str) and session_file:
            return Path(session_file).expanduser().resolve()

    return (sessions_dir / f"{session_id}.jsonl").resolve()


def extract_assistant_reply(message_line: dict) -> str | None:
    message = message_line.get("message")
    if not isinstance(message, dict):
        return None
    if message.get("role") != "assistant":
        return None
    content = message.get("content")
    if isinstance(content, str):
        text = content.strip()
        return text or None
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = str(item.get("text", "")).strip()
                if text:
                    parts.append(text)
        if parts:
            return "\n".join(parts)
    return None


def message_has_tool_call(message_line: dict) -> bool:
    message = message_line.get("message")
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    if not isinstance(content, list):
        return False
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").lower()
        if item_type in {"toolcall", "tool_call", "tool-use", "tooluse", "tool_use"}:
            return True
        if "toolCall" in item or "toolUse" in item:
            return True
    return False


def extract_hard_failure(message_line: dict) -> str | None:
    event_type = str(message_line.get("type") or message_line.get("event") or "").lower()
    if not (
        "error" in event_type
        or message_line.get("error")
        or message_line.get("rawError")
        or message_line.get("raw_error")
    ):
        return None
    text = json.dumps(message_line, ensure_ascii=False).lower()
    for marker in HARD_FAILURE_MARKERS:
        if marker in text:
            return marker
    return None


def strip_json_fence(text: str) -> str:
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    return candidate


def parse_strict_repair_json(text: str) -> tuple[dict | None, str]:
    candidate = strip_json_fence(text)
    if not candidate:
        return None, "empty reply"
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return None, f"reply was not strict JSON: {exc}"
    if not isinstance(payload, dict):
        return None, "reply JSON was not an object"
    required = ["status", "issue", "action", "verified", "next_step"]
    missing = [key for key in required if key not in payload]
    if missing:
        return None, f"reply JSON missing required keys: {', '.join(missing)}"
    status = str(payload.get("status") or "").strip().lower()
    if status not in {"repaired", "diagnosed", "blocked"}:
        return None, "reply JSON status must be repaired, diagnosed, or blocked"
    non_string = [key for key in required if not isinstance(payload.get(key), str)]
    if non_string:
        return None, f"reply JSON values must be strings: {', '.join(non_string)}"
    return payload, ""


def normalize_openclaw_agent_result(
    stdout: str,
    stderr: str,
    returncode: int,
) -> dict:
    """Normalize session-watcher and current OpenClaw CLI result envelopes.

    OpenClaw 2026.7.1 can finish a local turn before the session watcher sees
    the final transcript append.  In that case stdout is the CLI envelope with
    ``payloads[].text`` rather than Eve's watcher envelope.  Normalize both so
    prose-wrapped JSON triggers the existing same-session contract retry and
    can never become a false repair success.
    """
    payload = parse_json_object(stdout)
    if not payload:
        return {}
    reply = extract_cli_reply_text(stdout)
    existing_reply = payload.get("reply")
    if isinstance(existing_reply, str) and existing_reply.strip():
        reply = existing_reply.strip()

    parsed_reply = (
        payload.get("parsed_reply")
        if isinstance(payload.get("parsed_reply"), dict)
        and payload.get("parsed_reply")
        else None
    )
    contract_error = ""
    if parsed_reply is not None:
        parsed_reply, contract_error = parse_strict_repair_json(
            json.dumps(parsed_reply, ensure_ascii=False)
        )
    elif reply:
        parsed_reply, contract_error = parse_strict_repair_json(reply)

    hard_failures = [
        str(item)
        for item in payload.get("hard_failures", [])
        if str(item).strip()
    ] if isinstance(payload.get("hard_failures"), list) else []
    lowered_stderr = stderr.lower()
    for marker in HARD_FAILURE_MARKERS:
        if marker in lowered_stderr and marker not in hard_failures:
            hard_failures.append(marker)

    existing_error = str(payload.get("error") or "").strip()
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    replay_invalid = bool(payload.get("replayInvalid") is True or meta.get("replayInvalid") is True)
    error = existing_error or contract_error
    if replay_invalid and not error:
        error = "OpenClaw reported replayInvalid for the final assistant response"
    if hard_failures and not error:
        error = f"OpenClaw hard failure: {', '.join(hard_failures)}"
    ok = bool(
        returncode == 0
        and isinstance(parsed_reply, dict)
        and not error
        and not hard_failures
        and not replay_invalid
    )
    return {
        "ok": ok,
        "reply": reply,
        "parsed_reply": parsed_reply or {},
        "error": error,
        "hard_failures": hard_failures,
        "source": str(payload.get("source") or "openclaw_cli_json"),
        "replay_invalid": replay_invalid,
    }


def read_new_session_events(session_file: Path, offset: int) -> tuple[int, list[dict]]:
    if not session_file.exists():
        return offset, []
    with session_file.open("rb") as handle:
        handle.seek(offset)
        chunk = handle.read()
        new_offset = handle.tell()
    if not chunk:
        return new_offset, []

    events: list[dict] = []
    for raw_line in chunk.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            line = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        events.append(line)
    return new_offset, events


def terminate_process_group(process: subprocess.Popen[bytes], grace_seconds: int = 5) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return
        time.sleep(0.1)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass


def run_openclaw_agent(
    command: list[str],
    profile: str,
    agent: str,
    session_id: str,
    cwd: Path | None = None,
    timeout: int = 600,
) -> tuple[int, str, str]:
    session_file = openclaw_session_file(profile, agent, session_id=session_id)
    session_offset = session_file.stat().st_size if session_file and session_file.exists() else 0
    process = subprocess.Popen(
        command,
        cwd=str(cwd or ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        start_new_session=True,
        env=openclaw_env(),
    )
    selector = selectors.DefaultSelector()
    assert process.stdout is not None
    assert process.stderr is not None
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")

    stdout_parts: list[bytes] = []
    stderr_parts: list[bytes] = []
    deadline = time.monotonic() + timeout
    latest_reply = ""
    latest_reply_error = ""
    latest_message: dict | None = None
    hard_failures: list[str] = []

    def payload(
        *,
        ok: bool,
        reply: str = "",
        parsed_reply: dict | None = None,
        error: str = "",
    ) -> str:
        return json.dumps(
            {
                "ok": ok,
                "reply": reply,
                "parsed_reply": parsed_reply or {},
                "error": error,
                "hard_failures": hard_failures,
                "source": "session_log",
                "session_id": session_id,
                "session_file": str(session_file) if session_file else "",
                "message": latest_message.get("message") if isinstance(latest_message, dict) else {},
            },
            ensure_ascii=False,
        )

    def inspect_events(events: list[dict]) -> tuple[dict | None, str]:
        nonlocal latest_reply, latest_reply_error, latest_message
        for event in events:
            failure = extract_hard_failure(event)
            if failure and failure not in hard_failures:
                hard_failures.append(failure)
            reply = extract_assistant_reply(event)
            if not reply:
                continue
            latest_message = event
            latest_reply = reply
            if message_has_tool_call(event):
                continue
            parsed, error = parse_strict_repair_json(reply)
            latest_reply_error = error
            if parsed:
                return parsed, reply
        return None, ""

    def stderr_hard_failure() -> str:
        text = b"".join(stderr_parts).decode("utf-8", errors="replace").lower()
        for marker in HARD_FAILURE_MARKERS:
            if marker in text:
                return marker
        return ""

    try:
        while time.monotonic() < deadline:
            events = selector.select(timeout=0.2)
            for key, _ in events:
                chunk = os.read(key.fileobj.fileno(), 4096)
                if not chunk:
                    try:
                        selector.unregister(key.fileobj)
                    except Exception:
                        pass
                    continue
                if key.data == "stdout":
                    stdout_parts.append(chunk)
                else:
                    stderr_parts.append(chunk)

            if session_file is None:
                session_file = openclaw_session_file(profile, agent, session_id=session_id)
                if session_file and session_file.exists():
                    session_offset = 0

            if session_file is not None:
                session_offset, events = read_new_session_events(session_file, session_offset)
                parsed, reply = inspect_events(events)
                if parsed is not None:
                    failure = stderr_hard_failure()
                    if failure:
                        hard_failures.append(failure)
                        terminate_process_group(process)
                        return 2, payload(ok=False, reply=reply, error=f"OpenClaw hard failure: {failure}"), b"".join(stderr_parts).decode("utf-8", errors="replace").strip()
                    terminate_process_group(process)
                    return 0, payload(ok=True, reply=reply, parsed_reply=parsed), b"".join(stderr_parts).decode("utf-8", errors="replace").strip()

            if not events and process.poll() is not None:
                break
    finally:
        selector.close()

    if process.poll() is None:
        terminate_process_group(process)

    if session_file is None:
        session_file = openclaw_session_file(profile, agent, session_id=session_id)
        if session_file and session_file.exists():
            session_offset = 0

    if session_file is not None:
        session_offset, events = read_new_session_events(session_file, session_offset)
        parsed, reply = inspect_events(events)
        if parsed is not None:
            failure = stderr_hard_failure()
            if failure:
                hard_failures.append(failure)
                if process.poll() is None:
                    terminate_process_group(process)
                return 2, payload(ok=False, reply=reply, error=f"OpenClaw hard failure: {failure}"), b"".join(stderr_parts).decode("utf-8", errors="replace").strip()
            return 0, payload(ok=True, reply=reply, parsed_reply=parsed), b"".join(stderr_parts).decode("utf-8", errors="replace").strip()

    stdout_text = b"".join(stdout_parts).decode("utf-8", errors="replace").strip()
    stderr_text = b"".join(stderr_parts).decode("utf-8", errors="replace").strip()
    failure = stderr_hard_failure()
    if failure and failure not in hard_failures:
        hard_failures.append(failure)
    if latest_reply:
        error = latest_reply_error or "assistant did not return a final strict JSON repair object"
        return 2, payload(ok=False, reply=latest_reply, error=error), stderr_text
    if hard_failures:
        return 2, payload(ok=False, error=f"OpenClaw hard failure: {', '.join(hard_failures)}"), stderr_text
    if time.monotonic() >= deadline:
        return 124, payload(ok=False, error="OpenClaw repair turn timed out"), stderr_text

    return (
        process.returncode or 0,
        stdout_text,
        stderr_text,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one bounded OpenClaw self-repair turn for Eve.")
    parser.add_argument("--profile", default=DEFAULT_PROFILE, help="OpenClaw profile name.")
    parser.add_argument("--workspace", default=str(DEFAULT_WORKSPACE), help="OpenClaw workspace path.")
    parser.add_argument("--agent", default=DEFAULT_AGENT, help="OpenClaw agent id.")
    parser.add_argument("--message", default=DEFAULT_REPAIR_PROMPT, help="Prompt to send to the OpenClaw agent.")
    parser.add_argument("--timeout", type=int, default=900, help="OpenClaw agent timeout in seconds.")
    parser.add_argument("--session-id", help="Explicit OpenClaw session id for this repair turn.")
    parser.add_argument("--skip-sync", action="store_true", help="Skip the pre-run sync step.")
    parser.add_argument("--json", action="store_true", help="Print raw JSON from OpenClaw when available.")
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    if not workspace.exists():
        raise SystemExit(f"OpenClaw workspace does not exist: {workspace}. Run bin/install_eve_openclaw.sh first.")

    if not args.skip_sync:
        sync_result = run([sys.executable, str(SYNC_SCRIPT), "--workspace", str(workspace)], timeout=180)
        if sync_result.returncode != 0:
            raise SystemExit(sync_result.stderr.strip() or sync_result.stdout.strip() or "OpenClaw sync failed.")

    session_id = args.session_id or f"eve-repair-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{uuid.uuid4().hex[:8]}"
    openclaw_bin = openclaw_command()
    prompt = enforce_response_contract(args.message)
    returncode = 1
    stdout = ""
    stderr = ""
    for attempt in range(3):
        if attempt == 0:
            turn_prompt = prompt
        elif openclaw_needs_continuation(stdout, stderr):
            turn_prompt = enforce_response_contract(CONTINUATION_PROMPT)
        else:
            turn_prompt = enforce_response_contract(CONTRACT_RETRY_PROMPT)
        returncode, stdout, stderr = run_openclaw_agent(
            [
                openclaw_bin,
                "--profile",
                args.profile,
                "agent",
                "--agent",
                args.agent,
                "--session-id",
                session_id,
                "--local",
                "--json",
                "--timeout",
                str(args.timeout),
                "--message",
                turn_prompt,
            ],
            profile=args.profile,
            agent=args.agent,
            session_id=session_id,
            cwd=ROOT,
            timeout=args.timeout + 60,
        )
        normalized = normalize_openclaw_agent_result(
            stdout,
            stderr,
            returncode,
        )
        if normalized:
            stdout = json.dumps(normalized, ensure_ascii=False)
            returncode = 0 if normalized.get("ok") is True else 2
        if returncode == 0:
            break
        if not openclaw_needs_continuation(stdout, stderr) and not repair_contract_retry_needed(stdout, stderr):
            break
    if returncode != 0:
        if args.json and stdout.strip():
            print(stdout.strip())
        raise SystemExit(stderr.strip() or stdout.strip() or "OpenClaw repair turn failed.")

    if args.json:
        print(stdout.strip())
        return 0

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        print(stdout.strip())
        return 0

    if isinstance(payload, dict):
        reply = payload.get("reply") or payload.get("text") or payload.get("message")
        if reply:
            print(str(reply).strip())
            return 0
    print(stdout.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
