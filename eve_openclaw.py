#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import eve_store


ROOT = Path(__file__).resolve().parent
APP_DIR = ROOT / ".eve"
RUNTIME_DIR = Path.home() / ".eve_runtime"
RUNTIME_APP_DIR = RUNTIME_DIR / ".eve"
STATE_PATH = APP_DIR / "state.json"
RUNTIME_STATE_PATH = RUNTIME_APP_DIR / "state.json"
ACTIVE_MIND_PATH = APP_DIR / "active_mind.json"
RUNTIME_ACTIVE_MIND_PATH = RUNTIME_APP_DIR / "active_mind.json"
GLOBAL_WORKSPACE_PATH = APP_DIR / "global_workspace.json"
RUNTIME_GLOBAL_WORKSPACE_PATH = RUNTIME_APP_DIR / "global_workspace.json"
OPENCLAW_STATUS_PATH = APP_DIR / "openclaw_status.json"
RUNTIME_OPENCLAW_STATUS_PATH = RUNTIME_APP_DIR / "openclaw_status.json"
OPENCLAW_SYNC_HISTORY_PATH = APP_DIR / "openclaw_sync_history.jsonl"
RUNTIME_OPENCLAW_SYNC_HISTORY_PATH = RUNTIME_APP_DIR / "openclaw_sync_history.jsonl"
INSTALL_SCRIPT = ROOT / "bin" / "install_eve_openclaw.sh"
SYNC_SCRIPT = ROOT / "bin" / "eve_openclaw_sync.py"
REPAIR_SCRIPT = ROOT / "bin" / "eve_openclaw_repair.py"
OPENCLAW_COMMAND_PATHS = [
    "/opt/homebrew/bin/openclaw",
    "/usr/local/bin/openclaw",
    "/opt/homebrew/lib/node_modules/openclaw/dist/index.js",
]

DEFAULT_OPENCLAW_STATUS = {
    "updated_at": None,
    "enabled": False,
    "profile": "eve-repair",
    "agent": "main",
    "workspace": "",
    "state_dir": "",
    "gateway_port": 19011,
    "command_available": False,
    "installed": False,
    "workspace_exists": False,
    "profile_config_exists": False,
    "plugins_allow_explicit": False,
    "plugins_allow_ok": False,
    "plugins_allow_count": 0,
    "plugins_allow_entries": [],
    "plugins_allow_error": "",
    "memory_wiki_enabled": False,
    "memory_wiki_vault_path": "",
    "memory_wiki_vault_path_explicit": False,
    "memory_wiki_vault_path_absolute": False,
    "memory_wiki_vault_exists": False,
    "memory_wiki_vault_config_ok": True,
    "memory_wiki_vault_error": "",
    "config_validation_checked_at": None,
    "config_valid": None,
    "config_validation_path": "",
    "config_validation_issues": [],
    "config_validation_summary": "",
    "config_validation_returncode": None,
    "config_validation_authoritative": None,
    "config_validation_environment_limited": False,
    "config_validation_last_authoritative_valid": None,
    "config_validation_last_authoritative_checked_at": None,
    "gateway_reachable": False,
    "gateway_status_ok": False,
    "gateway_status_output": "",
    "gateway_probe_checked_at": None,
    "gateway_probe_authoritative": None,
    "gateway_probe_environment_limited": False,
    "gateway_probe_summary": "",
    "gateway_last_authoritative_reachable": None,
    "gateway_last_authoritative_checked_at": None,
    "last_install_at": None,
    "last_install_ok": None,
    "last_install_summary": "",
    "last_sync_at": None,
    "last_sync_ok": None,
    "last_sync_summary": "",
    "last_sync_error": "",
    "sync_health_summary": "",
    "last_memory_probe_at": None,
    "memory_status_ok": None,
    "memory_status_severity": "",
    "memory_capability_available": None,
    "memory_status_summary": "",
    "memory_status_returncode": None,
    "memory_provider": "",
    "memory_model": "",
    "memory_files": 0,
    "memory_chunks": 0,
    "memory_dirty": None,
    "memory_embedding_ok": None,
    "memory_embedding_error": "",
    "memory_probe_checked_at": None,
    "memory_probe_authoritative": None,
    "memory_probe_environment_limited": False,
    "memory_probe_summary": "",
    "memory_last_authoritative_status_ok": None,
    "memory_last_authoritative_probe_at": None,
    "last_repair_at": None,
    "last_repair_ok": None,
    "last_repair_summary": "",
    "last_repair_issue": "",
    "last_repair_next_step": "",
    "last_repair_status": "",
    "last_repair_verified": "",
    "last_error": "",
    "summary": "OpenClaw sidecar not configured yet.",
}

STRICT_REPAIR_STATUSES = {"repaired", "diagnosed", "blocked"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_boolish(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def normalize_text(value: object, fallback: str = "", limit: int = 240) -> str:
    if value is None:
        return fallback
    text = " ".join(str(value).split())
    if not text:
        return fallback
    if limit > 0 and len(text) > limit:
        return text[: max(0, limit - 1)].rstrip() + "…"
    return text


def repair_contract_complete(status: Dict[str, object]) -> bool:
    if not parse_boolish(status.get("last_repair_ok"), default=False):
        return False
    repair_status = normalize_text(status.get("last_repair_status"), fallback="", limit=40)
    if repair_status not in STRICT_REPAIR_STATUSES:
        return False
    return bool(
        normalize_text(status.get("last_repair_issue"), fallback="", limit=80)
        and normalize_text(status.get("last_repair_next_step"), fallback="", limit=80)
        and normalize_text(status.get("last_repair_verified"), fallback="", limit=80)
    )


def sanitize_legacy_repair_status(status: Dict[str, object]) -> Dict[str, object]:
    if not status.get("last_repair_at") or not parse_boolish(status.get("last_repair_ok"), default=False):
        return status
    if repair_contract_complete(status):
        return status
    legacy_summary = normalize_text(status.get("last_repair_summary"), fallback="", limit=220)
    status["last_repair_ok"] = False
    status["last_repair_summary"] = "Legacy non-contract repair result ignored as success."
    status["last_repair_status"] = "legacy_non_contract"
    status["last_repair_issue"] = normalize_text(
        status.get("last_repair_issue"),
        fallback="Legacy OpenClaw repair result did not satisfy the strict JSON contract.",
        limit=220,
    )
    status["last_repair_next_step"] = normalize_text(
        status.get("last_repair_next_step"),
        fallback="Rerun repair through the strict JSON wrapper only if fresh evidence still shows a live blocker.",
        limit=220,
    )
    status["last_error"] = normalize_text(
        status.get("last_error"),
        fallback=f"Legacy OpenClaw repair result ignored as success: {legacy_summary or 'missing strict repair contract'}",
        limit=260,
    )
    return status


def parse_iso_datetime(value: object) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def openclaw_status_freshness(status: Dict[str, object]) -> datetime:
    return (
        parse_iso_datetime(status.get("last_sync_at"))
        or parse_iso_datetime(status.get("last_repair_at"))
        or parse_iso_datetime(status.get("updated_at"))
        or datetime.min.replace(tzinfo=timezone.utc)
    )


def runtime_status_path() -> Path:
    return RUNTIME_OPENCLAW_STATUS_PATH


def local_status_path() -> Path:
    return OPENCLAW_STATUS_PATH


def load_openclaw_status(prefer_runtime: bool = False) -> Dict[str, object]:
    if prefer_runtime:
        primary = eve_store.load_json_dict(runtime_status_path(), default=DEFAULT_OPENCLAW_STATUS)
        secondary = eve_store.load_json_dict(local_status_path(), default=DEFAULT_OPENCLAW_STATUS)
    else:
        primary = eve_store.load_json_dict(local_status_path(), default=DEFAULT_OPENCLAW_STATUS)
        secondary = eve_store.load_json_dict(runtime_status_path(), default=DEFAULT_OPENCLAW_STATUS)
    merged = dict(DEFAULT_OPENCLAW_STATUS)
    older, newer = (primary, secondary)
    if openclaw_status_freshness(primary) >= openclaw_status_freshness(secondary):
        older, newer = (secondary, primary)
    merged.update(older)
    merged.update(newer)
    return sanitize_legacy_repair_status(merged)


def save_openclaw_status(payload: Dict[str, object]) -> Dict[str, object]:
    merged = dict(DEFAULT_OPENCLAW_STATUS)
    merged.update(payload)
    merged["updated_at"] = utc_now()
    try:
        eve_store.write_json_dict(local_status_path(), merged)
    except OSError:
        pass
    if ROOT != RUNTIME_DIR and not str(ROOT).endswith(".eve_runtime"):
        try:
            eve_store.write_json_dict(runtime_status_path(), merged)
        except OSError:
            pass
    return merged


def openclaw_state_paths() -> list[Path]:
    paths: list[Path] = []
    for path in (STATE_PATH, RUNTIME_STATE_PATH):
        if path not in paths:
            paths.append(path)
    return paths


def stale_sync_repair_text(value: object) -> bool:
    text = normalize_text(value, fallback="", limit=500).lower()
    if not text:
        return False
    return any(marker in text for marker in ("sync", "context artifact", "eve_status", "timing out", "timeout", "killed"))


def stale_openclaw_attention_text(value: object) -> bool:
    text = normalize_text(value, fallback="", limit=700).lower()
    if not text or "openclaw" not in text:
        return False
    if "recovered cleanly" in text or "recovered by successful" in text:
        return False
    return any(
        marker in text
        for marker in (
            "persistent timeout",
            "sync timeout",
            "sync timeouts",
            "sync is fai",
            "sync is failing",
            "sync loop",
            "sync path",
            "sync failure",
            "sync failures",
            "sync commands are timing out",
            "context artifact",
            "could not be updated",
            "timing out/killed",
            "bottleneck",
            "saturated",
        )
    )


def recovered_sync_text(status: Dict[str, object]) -> str:
    sync_at = normalize_text(status.get("last_sync_at"), fallback=utc_now(), limit=80)
    return f"OpenClaw sync recovered cleanly at {sync_at}; monitor for recurrence without treating older sync failures as current evidence."


def replace_stale_openclaw_attention(value: object, replacement: str) -> object:
    if isinstance(value, str):
        return replacement if stale_openclaw_attention_text(value) else value
    if isinstance(value, list):
        cleaned: list[object] = []
        for item in value:
            new_item = replace_stale_openclaw_attention(item, replacement)
            if new_item not in cleaned:
                cleaned.append(new_item)
        return cleaned
    if isinstance(value, dict):
        return {key: replace_stale_openclaw_attention(item, replacement) for key, item in value.items()}
    return value


def openclaw_attention_surface_paths() -> list[Path]:
    paths: list[Path] = []
    for path in (ACTIVE_MIND_PATH, RUNTIME_ACTIVE_MIND_PATH, GLOBAL_WORKSPACE_PATH, RUNTIME_GLOBAL_WORKSPACE_PATH):
        if path not in paths:
            paths.append(path)
    return paths


def record_openclaw_sync_recovery_context(status: Dict[str, object]) -> int:
    if not parse_boolish(status.get("last_sync_ok"), default=False):
        return 0
    replacement = recovered_sync_text(status)
    updated = 0

    for path in openclaw_attention_surface_paths():
        try:
            changed = False

            def mutate(payload: Dict[str, object]) -> None:
                nonlocal changed
                cleaned = replace_stale_openclaw_attention(payload, replacement)
                if isinstance(cleaned, dict) and cleaned != payload:
                    payload.clear()
                    payload.update(cleaned)
                    payload["openclaw_recovery_note"] = replacement
                    changed = True

            eve_store.mutate_json_dict(path, mutate, default={})
            if changed:
                updated += 1
        except OSError:
            continue
    return updated


def record_openclaw_sync_state(status: Dict[str, object]) -> int:
    """Mirror a verified sync result into Eve's live state so old repair loops stop dominating attention."""
    sync_at = normalize_text(status.get("last_sync_at"), fallback=utc_now(), limit=80)
    summary = normalize_text(status.get("summary"), fallback="", limit=220)
    sync_summary = normalize_text(status.get("last_sync_summary"), fallback=summary, limit=260)
    sync_ok = parse_boolish(status.get("last_sync_ok"), default=False)
    updated = 0

    def mutate(state: Dict[str, object]) -> None:
        state["last_openclaw_sync_at"] = sync_at
        state["last_openclaw_sync_ok"] = sync_ok
        state["last_openclaw_sync_summary"] = sync_summary
        if summary:
            state["openclaw_summary"] = summary
        if sync_ok and stale_sync_repair_text(state.get("last_openclaw_repair_issue")):
            state["last_openclaw_repair_status"] = "recovered_by_sync"
            state["last_openclaw_repair_issue"] = f"Recovered by successful OpenClaw sync at {sync_at}."
            state["last_openclaw_repair_next_step"] = "Monitor for recurrence; do not retry the stale sync repair without new failure evidence."

    for path in openclaw_state_paths():
        try:
            eve_store.mutate_json_dict(path, mutate, default={})
            updated += 1
        except OSError:
            continue
    if sync_ok:
        record_openclaw_sync_recovery_context(status)
    return updated


def load_openclaw_sync_history(prefer_runtime: bool = False) -> list[Dict[str, object]]:
    if prefer_runtime:
        primary = eve_store.read_jsonl_records(RUNTIME_OPENCLAW_SYNC_HISTORY_PATH)
        secondary = eve_store.read_jsonl_records(OPENCLAW_SYNC_HISTORY_PATH)
    else:
        primary = eve_store.read_jsonl_records(OPENCLAW_SYNC_HISTORY_PATH)
        secondary = eve_store.read_jsonl_records(RUNTIME_OPENCLAW_SYNC_HISTORY_PATH)
    merged: list[Dict[str, object]] = []
    seen: set[str] = set()
    for record in [*primary, *secondary]:
        record_id = normalize_text(record.get("id"), fallback="", limit=120)
        key = record_id or json.dumps(record, sort_keys=True, ensure_ascii=True)
        if key in seen:
            continue
        seen.add(key)
        merged.append(record)
    merged.sort(
        key=lambda item: parse_iso_datetime(item.get("timestamp"))
        or datetime.min.replace(tzinfo=timezone.utc)
    )
    return merged


def append_openclaw_sync_history(event: Dict[str, object]) -> Dict[str, object]:
    record = {
        "id": str(event.get("id") or utc_now()),
        "timestamp": str(event.get("timestamp") or utc_now()),
        "ok": bool(event.get("ok")),
        "summary": normalize_text(event.get("summary"), fallback="", limit=260),
        "error": normalize_text(event.get("error"), fallback="", limit=260),
        "returncode": int(event.get("returncode") or 0),
        "command_root": normalize_text(event.get("command_root"), fallback="", limit=220),
        "workspace": normalize_text(event.get("workspace"), fallback="", limit=220),
    }
    history_paths = [OPENCLAW_SYNC_HISTORY_PATH]
    if RUNTIME_OPENCLAW_SYNC_HISTORY_PATH != OPENCLAW_SYNC_HISTORY_PATH:
        history_paths.append(RUNTIME_OPENCLAW_SYNC_HISTORY_PATH)
    for history_path in history_paths:
        try:
            eve_store.append_jsonl_record(history_path, record, ensure_ascii=True)
        except OSError:
            pass
    return record


def summarize_openclaw_sync_health(events: list[Dict[str, object]]) -> str:
    if not events:
        return "No OpenClaw sync history yet."
    recent = events[-8:]
    failures = [item for item in recent if not bool(item.get("ok"))]
    latest = recent[-1]
    if not failures:
        return f"OpenClaw sync stable across the last {len(recent)} run(s)."
    latest_failure = failures[-1]
    return (
        f"{len(failures)} of the last {len(recent)} OpenClaw sync run(s) failed. "
        f"Latest failure: {normalize_text(latest_failure.get('error') or latest_failure.get('summary'), fallback='unknown error', limit=180)}"
        if not bool(latest.get("ok"))
        else f"{len(failures)} recent OpenClaw sync failure(s), but the latest run recovered."
    )


def openclaw_enabled(config: Dict[str, object]) -> bool:
    return parse_boolish(config.get("openclaw_enabled"), default=True)


def openclaw_profile(config: Dict[str, object]) -> str:
    value = normalize_text(config.get("openclaw_profile"), fallback="eve-repair", limit=120)
    return value or "eve-repair"


def openclaw_agent(config: Dict[str, object]) -> str:
    value = normalize_text(config.get("openclaw_agent"), fallback="eve-repair", limit=120)
    return value or "eve-repair"


def openclaw_workspace(config: Dict[str, object]) -> Path:
    raw = str(config.get("openclaw_workspace") or (RUNTIME_DIR / "openclaw"))
    return Path(raw).expanduser().resolve()


def openclaw_gateway_port(config: Dict[str, object]) -> int:
    try:
        return max(1, int(config.get("openclaw_gateway_port") or 19011))
    except (TypeError, ValueError):
        return 19011


def openclaw_state_dir(config: Dict[str, object]) -> Path:
    raw = str(config.get("openclaw_state_dir") or (Path.home() / f".openclaw-{openclaw_profile(config)}"))
    return Path(raw).expanduser().resolve()


def openclaw_profile_config_path(config: Dict[str, object]) -> Path:
    return openclaw_state_dir(config) / "openclaw.json"


def openclaw_plugin_allow_fields(config: Dict[str, object]) -> Dict[str, object]:
    """Read only the non-secret plugin allow-list contract from the profile.

    Old repair narratives repeatedly described ``plugins.allow`` as empty even
    after the profile had been repaired.  Making this small fact part of the
    typed current status lets callers compare a remembered/self-authored claim
    with the live profile instead of trusting prose from an older cycle.
    """

    path = openclaw_profile_config_path(config)
    result: Dict[str, object] = {
        "plugins_allow_explicit": False,
        "plugins_allow_ok": False,
        "plugins_allow_count": 0,
        "plugins_allow_entries": [],
        "plugins_allow_error": "",
    }
    if not path.is_file():
        result["plugins_allow_error"] = "profile config missing"
        return result
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result["plugins_allow_error"] = normalize_text(
            exc, fallback="profile config unreadable", limit=180
        )
        return result
    plugins = payload.get("plugins") if isinstance(payload, dict) else None
    if not isinstance(plugins, dict) or "allow" not in plugins:
        result["plugins_allow_error"] = "plugins.allow is not explicit"
        return result
    result["plugins_allow_explicit"] = True
    raw_entries = plugins.get("allow")
    if not isinstance(raw_entries, list):
        result["plugins_allow_error"] = "plugins.allow is not a list"
        return result
    entries = []
    for item in raw_entries:
        value = normalize_text(item, fallback="", limit=120)
        if value and value not in entries:
            entries.append(value)
    result["plugins_allow_entries"] = entries[:64]
    result["plugins_allow_count"] = len(entries)
    result["plugins_allow_ok"] = bool(entries)
    if not entries:
        result["plugins_allow_error"] = "plugins.allow is empty"
    return result


def openclaw_memory_wiki_fields(config: Dict[str, object]) -> Dict[str, object]:
    """Expose the live wiki vault path without accepting cwd-relative state.

    OpenClaw wiki subcommands may have different working directories.  A
    relative vault path can therefore create multiple apparently healthy
    vaults.  Eve admits the bridge only when an enabled profile names one
    existing absolute vault.
    """

    result: Dict[str, object] = {
        "memory_wiki_enabled": False,
        "memory_wiki_vault_path": "",
        "memory_wiki_vault_path_explicit": False,
        "memory_wiki_vault_path_absolute": False,
        "memory_wiki_vault_exists": False,
        "memory_wiki_vault_config_ok": True,
        "memory_wiki_vault_error": "",
    }
    path = openclaw_profile_config_path(config)
    if not path.is_file():
        return result
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result["memory_wiki_vault_config_ok"] = False
        result["memory_wiki_vault_error"] = normalize_text(
            exc, fallback="profile config unreadable", limit=180
        )
        return result
    plugins = payload.get("plugins") if isinstance(payload, dict) else None
    entries = (
        plugins.get("entries")
        if isinstance(plugins, dict) and isinstance(plugins.get("entries"), dict)
        else {}
    )
    wiki = entries.get("memory-wiki") if isinstance(entries.get("memory-wiki"), dict) else {}
    enabled = wiki.get("enabled") is True
    wiki_config = wiki.get("config") if isinstance(wiki.get("config"), dict) else {}
    vault = wiki_config.get("vault") if isinstance(wiki_config.get("vault"), dict) else {}
    raw_path = normalize_text(vault.get("path"), fallback="", limit=520)
    expanded = Path(raw_path).expanduser() if raw_path else None
    absolute = bool(expanded and expanded.is_absolute())
    exists = bool(absolute and expanded and expanded.is_dir())
    result.update(
        {
            "memory_wiki_enabled": enabled,
            "memory_wiki_vault_path": str(expanded) if expanded else "",
            "memory_wiki_vault_path_explicit": bool(raw_path),
            "memory_wiki_vault_path_absolute": absolute,
            "memory_wiki_vault_exists": exists,
        }
    )
    if not enabled:
        return result
    if not raw_path:
        error = "enabled memory-wiki plugin has no explicit vault.path"
    elif not absolute:
        error = "enabled memory-wiki vault.path must be absolute; relative paths can split the vault by working directory"
    elif not exists:
        error = "enabled memory-wiki absolute vault path does not exist"
    else:
        error = ""
    result["memory_wiki_vault_config_ok"] = not bool(error)
    result["memory_wiki_vault_error"] = error
    return result


def openclaw_command_available() -> bool:
    return openclaw_command() is not None


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


def parse_reply_json(text: str) -> Optional[Dict[str, object]]:
    candidate = strip_json_fence(text)
    if not candidate:
        return None
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def parse_noisy_json_payload(text: object) -> object:
    raw = str(text or "")
    if not raw.strip():
        return None
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char not in "[{":
            continue
        try:
            payload, _ = decoder.raw_decode(raw[index:])
        except json.JSONDecodeError:
            continue
        return payload
    return None


def parse_labeled_reply(text: object) -> Dict[str, object]:
    parsed: Dict[str, object] = {}
    for raw_line in str(text or "").splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        normalized_key = "_".join(key.strip().lower().split())
        normalized_value = normalize_text(value, fallback="", limit=300)
        if normalized_key and normalized_value:
            parsed[normalized_key] = normalized_value
    return parsed


def gateway_reachable(port: int, host: str = "127.0.0.1", timeout_seconds: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def openclaw_command() -> Optional[str]:
    env_path = os.environ.get("OPENCLAW_BIN")
    candidates = [env_path, shutil.which("openclaw"), *OPENCLAW_COMMAND_PATHS]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.exists():
            return str(path)
    return shutil.which("openclaw")


def openclaw_env() -> Dict[str, str]:
    env = os.environ.copy()
    path_parts = [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/Applications/Codex.app/Contents/Resources",
        env.get("PATH", ""),
    ]
    env["PATH"] = ":".join(part for part in path_parts if part)
    return env


def run(command: list[str], *, cwd: Optional[Path] = None, timeout: int = 1200) -> subprocess.CompletedProcess[str]:
    def stream_text(value: object) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value or "")

    try:
        return subprocess.run(
            command,
            cwd=str(cwd or ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=openclaw_env(),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = normalize_text(stream_text(exc.stdout or exc.output), fallback="", limit=4000)
        stderr_text = normalize_text(stream_text(exc.stderr), fallback="", limit=3600)
        timeout_text = f"Command timed out after {timeout} seconds: {' '.join(command)}"
        stderr = f"{timeout_text}\n{stderr_text}".strip() if stderr_text else timeout_text
        return subprocess.CompletedProcess(command, 124, stdout=stdout, stderr=stderr)


def sync_artifact_write_degraded(*parts: object) -> bool:
    output = "\n".join(str(part or "") for part in parts).lower()
    markers = (
        "one or more context artifacts could not be updated",
        "could not update openclaw sync artifact",
        "could not append openclaw memory note",
        "could not create openclaw context directory",
        "could not create openclaw memory directory",
    )
    return any(marker in output for marker in markers)


def build_openclaw_summary(status: Dict[str, object]) -> str:
    if not parse_boolish(status.get("enabled"), default=False):
        return "OpenClaw sidecar disabled."
    if not parse_boolish(status.get("command_available"), default=False):
        return "OpenClaw sidecar enabled, but the `openclaw` CLI is missing."
    if not parse_boolish(status.get("installed"), default=False):
        return "OpenClaw sidecar enabled, but the Eve profile is not installed yet."
    if status.get("config_valid") is False:
        validation_summary = normalize_text(
            status.get("config_validation_summary"),
            fallback="the active profile failed OpenClaw schema and plugin validation",
            limit=180,
        )
        return f"OpenClaw profile is invalid even though the gateway may still be reachable: {validation_summary}"
    if status.get("config_valid") is None and status.get("config_validation_environment_limited"):
        validation_summary = normalize_text(
            status.get("config_validation_summary"),
            fallback="the restricted execution environment could not validate the active profile",
            limit=180,
        )
        return f"OpenClaw profile validation is inconclusive, not failed: {validation_summary}"
    if status.get("memory_wiki_enabled") and not status.get("memory_wiki_vault_config_ok"):
        wiki_summary = normalize_text(
            status.get("memory_wiki_vault_error"),
            fallback="the enabled memory-wiki bridge does not resolve to one existing absolute vault",
            limit=220,
        )
        return f"OpenClaw memory-wiki vault is misconfigured: {wiki_summary}"
    if status.get("memory_status_ok") is None and status.get("memory_probe_environment_limited"):
        memory_summary = normalize_text(
            status.get("memory_probe_summary"),
            fallback="the restricted execution environment could not load the memory command",
            limit=180,
        )
        return f"OpenClaw memory validation is inconclusive, not degraded: {memory_summary}"
    if status.get("memory_status_ok") is False:
        memory_summary = normalize_text(
            status.get("memory_status_summary") or status.get("memory_embedding_error"),
            fallback="memory search provider is degraded",
            limit=180,
        )
        return f"OpenClaw reachable, but memory search is degraded: {memory_summary}"
    sync_summary = normalize_text(status.get("last_sync_summary"), fallback="", limit=180)
    sync_health = normalize_text(status.get("sync_health_summary"), fallback="", limit=180).lower()
    if sync_summary and (
        parse_boolish(status.get("last_sync_ok"), default=False)
        or "stable across" in sync_health
        or "latest run recovered" in sync_health
    ):
        return f"OpenClaw reachable. Latest sync recovered cleanly: {sync_summary}"
    if not parse_boolish(status.get("gateway_reachable"), default=False):
        return "OpenClaw sidecar is installed, but the local gateway is not reachable."
    repair_summary = normalize_text(status.get("last_repair_summary"), fallback="", limit=220)
    if repair_summary:
        if repair_contract_complete(status):
            return f"OpenClaw reachable. Last strict repair: {repair_summary}"
        if status.get("last_repair_status") == "legacy_non_contract":
            return "OpenClaw reachable. Last repair record was legacy non-contract evidence; rerun repair only if fresh status is degraded."
        return f"OpenClaw reachable. Last repair attempt: {repair_summary}"
    if sync_summary:
        return f"OpenClaw reachable. Last sync: {sync_summary}"
    return "OpenClaw sidecar installed and reachable."


def memory_auth_unavailable(provider: str, error: str) -> bool:
    text = f"{provider} {error}".lower()
    markers = (
        "could not load credentials",
        "missing credentials",
        "no credentials",
        "not logged in",
        "not authenticated",
        "unauthorized",
        "api key",
        "aws_profile",
        "aws_access_key_id",
        "aws_secret_access_key",
    )
    return any(marker in text for marker in markers)


def memory_auth_unavailable_reason(provider: str, error: str) -> str:
    lowered = error.lower()
    if provider.lower() == "bedrock" and "could not load credentials" in lowered:
        return "AWS credentials are not configured"
    return normalize_text(error, fallback="provider credentials are not configured", limit=180)


def openclaw_memory_probe_environment_limited(output: object) -> bool:
    """Return true only for the known restricted plugin-loader signature."""

    text = str(output or "").lower()
    permission_limited = (
        "[state/db] skipped permission hardening" in text
        and "eperm: operation not permitted" in text
    )
    memory_command_hidden = (
        'does not know the command "memory"' in text
        or "runtime extension entry not found" in text
    )
    return permission_limited and memory_command_hidden


def openclaw_memory_status_fields(
    payload: object,
    *,
    returncode: int = 0,
    output: object = "",
) -> Dict[str, object]:
    checked_at = utc_now()
    environment_limited = openclaw_memory_probe_environment_limited(output)
    record: Dict[str, object] = {}
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and isinstance(item.get("status"), dict):
                record = item
                break
    elif isinstance(payload, dict):
        record = payload

    status = record.get("status") if isinstance(record.get("status"), dict) else {}
    embedding_probe = (
        record.get("embeddingProbe")
        if isinstance(record.get("embeddingProbe"), dict)
        else {}
    )
    provider = normalize_text(status.get("provider"), fallback="", limit=80)
    model = normalize_text(status.get("model"), fallback="", limit=160)
    embedding_ok = embedding_probe.get("ok")
    embedding_error = normalize_text(embedding_probe.get("error"), fallback="", limit=220)
    auth_unavailable = embedding_ok is False and memory_auth_unavailable(provider, embedding_error)
    ok: Optional[bool] = (
        None
        if environment_limited
        else bool(record) and returncode == 0 and (embedding_ok is not False or auth_unavailable)
    )
    capability_available: Optional[bool] = (
        None
        if environment_limited
        else bool(record) and returncode == 0 and embedding_ok is not False
    )

    try:
        files = int(status.get("files") or 0) if isinstance(status, dict) else 0
    except (TypeError, ValueError):
        files = 0
    try:
        chunks = int(status.get("chunks") or 0) if isinstance(status, dict) else 0
    except (TypeError, ValueError):
        chunks = 0
    dirty = status.get("dirty") if isinstance(status, dict) else None

    if environment_limited:
        severity = "inconclusive"
        summary = (
            "Restricted execution environment hid the OpenClaw memory command; "
            "preserve the last authoritative host result."
        )
    elif ok and capability_available:
        provider_detail = f" via {provider}" if provider else ""
        model_detail = f" ({model})" if model else ""
        severity = "ready"
        summary = (
            f"Memory search ready{provider_detail}{model_detail}; "
            f"{files} indexed file(s), {chunks} chunk(s)."
        )
    elif ok:
        provider_detail = f" via {provider}" if provider else ""
        severity = "unavailable"
        reason = memory_auth_unavailable_reason(provider, embedding_error)
        summary = f"Memory embeddings unavailable{provider_detail}: {reason}"
    else:
        severity = "degraded"
        reason = embedding_error or normalize_text(
            output,
            fallback="OpenClaw memory status probe failed.",
            limit=180,
        )
        provider_detail = f" via {provider}" if provider else ""
        summary = f"Memory search degraded{provider_detail}: {reason}"

    return {
        "last_memory_probe_at": checked_at if not environment_limited else None,
        "memory_status_ok": ok,
        "memory_status_severity": severity,
        "memory_capability_available": capability_available,
        "memory_status_summary": normalize_text(summary, fallback="", limit=260),
        "memory_status_returncode": returncode,
        "memory_provider": provider,
        "memory_model": model,
        "memory_files": files,
        "memory_chunks": chunks,
        "memory_dirty": dirty if isinstance(dirty, bool) else None,
        "memory_embedding_ok": embedding_ok if isinstance(embedding_ok, bool) else None,
        "memory_embedding_error": embedding_error,
        "memory_probe_checked_at": checked_at,
        "memory_probe_authoritative": not environment_limited,
        "memory_probe_environment_limited": environment_limited,
        "memory_probe_summary": normalize_text(summary, fallback="", limit=260),
        "memory_last_authoritative_status_ok": ok if not environment_limited else None,
        "memory_last_authoritative_probe_at": checked_at if not environment_limited else None,
    }


def probe_openclaw_memory_status(config: Dict[str, object], *, timeout: int = 90) -> Dict[str, object]:
    command_path = openclaw_command()
    if not command_path:
        return openclaw_memory_status_fields(
            None,
            returncode=127,
            output="OpenClaw CLI is missing.",
        )
    result = run(
        [
            command_path,
            "--profile",
            openclaw_profile(config),
            "memory",
            "status",
            "--deep",
            "--json",
        ],
        timeout=timeout,
    )
    output = ((result.stdout or "") + ("\n" + result.stderr if result.stderr else "")).strip()
    diagnostic_output = result.stderr if result.returncode == 124 and result.stderr else output
    payload = parse_noisy_json_payload(output)
    return openclaw_memory_status_fields(
        payload,
        returncode=result.returncode,
        output=diagnostic_output,
    )


def openclaw_config_validation_environment_limited(
    output: object,
    issues: list[Dict[str, str]],
) -> bool:
    """Recognize the exact restricted-runtime false negative seen under Codex.

    OpenClaw resolves runtime plugin extensions relative to its executable
    environment.  A filesystem-restricted caller can both fail state-database
    hardening with EPERM and hide an otherwise installed runtime extension.
    That paired signature is inconclusive.  A normal plugin/config issue, or
    any additional issue, remains an authoritative validation failure.
    """

    text = str(output or "").lower()
    permission_limited = (
        "[state/db] skipped permission hardening" in text
        and "eperm: operation not permitted" in text
    )
    extension_only = bool(issues) and all(
        str(item.get("path") or "") == "plugins.allow"
        and "runtime extension entry not found" in str(item.get("message") or "").lower()
        for item in issues
    )
    return permission_limited and extension_only


def openclaw_config_validation_fields(
    payload: object,
    *,
    returncode: int = 0,
    output: object = "",
) -> Dict[str, object]:
    record = payload if isinstance(payload, dict) else {}
    raw_issues = record.get("issues") if isinstance(record.get("issues"), list) else []
    issues = []
    for item in raw_issues:
        if not isinstance(item, dict):
            continue
        path = normalize_text(item.get("path"), fallback="config", limit=160)
        message = normalize_text(item.get("message"), fallback="validation failed", limit=260)
        issues.append({"path": path, "message": message})
    checked_at = utc_now()
    environment_limited = openclaw_config_validation_environment_limited(output, issues)
    declared_valid = record.get("valid")
    valid: Optional[bool] = None if environment_limited else bool(declared_valid is True and returncode == 0)
    config_path = normalize_text(record.get("path"), fallback="", limit=320)
    if environment_limited:
        first = issues[0]
        summary = (
            "Restricted execution environment made validation inconclusive; "
            f"the sandbox-only probe reported {first['path']}: {first['message']}"
        )
    elif valid:
        summary = "Active OpenClaw profile passed schema and plugin validation."
    elif issues:
        first = issues[0]
        summary = f"{first['path']}: {first['message']}"
        if len(issues) > 1:
            summary += f" (+{len(issues) - 1} more issue(s))"
    else:
        summary = normalize_text(
            output,
            fallback="OpenClaw config validation did not return a valid structured result.",
            limit=260,
        )
    return {
        "config_validation_checked_at": checked_at,
        "config_valid": valid,
        "config_validation_path": config_path,
        "config_validation_issues": issues[:20],
        "config_validation_summary": normalize_text(summary, fallback="config validation failed", limit=320),
        "config_validation_returncode": returncode,
        "config_validation_authoritative": not environment_limited,
        "config_validation_environment_limited": environment_limited,
        "config_validation_last_authoritative_valid": valid if not environment_limited else None,
        "config_validation_last_authoritative_checked_at": checked_at if not environment_limited else None,
    }


def probe_openclaw_config_validation(
    config: Dict[str, object],
    *,
    timeout: int = 30,
) -> Dict[str, object]:
    command_path = openclaw_command()
    if not command_path:
        return openclaw_config_validation_fields(
            None,
            returncode=127,
            output="OpenClaw CLI is missing.",
        )
    result = run(
        [
            command_path,
            "--profile",
            openclaw_profile(config),
            "config",
            "validate",
            "--json",
        ],
        timeout=timeout,
    )
    output = ((result.stdout or "") + ("\n" + result.stderr if result.stderr else "")).strip()
    payload = parse_noisy_json_payload(output)
    return openclaw_config_validation_fields(
        payload,
        returncode=result.returncode,
        output=output,
    )


def openclaw_gateway_probe_environment_limited(output: object) -> bool:
    """Recognize a running/listening gateway whose loopback probe was sandboxed."""

    text = str(output or "").lower()
    permission_limited = (
        "connect eperm" in text
        or (
            "[state/db] skipped permission hardening" in text
            and "eperm: operation not permitted" in text
        )
    )
    service_running = (
        "runtime: running" in text
        or "listening: 127.0.0.1" in text
        or "port 19011 is already in use" in text
    )
    return permission_limited and service_running


def collect_openclaw_status(
    config: Dict[str, object],
    *,
    prefer_runtime: bool = False,
    include_gateway_probe: bool = False,
    include_memory_probe: bool = False,
    include_config_probe: Optional[bool] = None,
) -> Dict[str, object]:
    status = dict(DEFAULT_OPENCLAW_STATUS)
    status.update(load_openclaw_status(prefer_runtime=prefer_runtime))
    sync_history = load_openclaw_sync_history(prefer_runtime=prefer_runtime)
    status["enabled"] = openclaw_enabled(config)
    status["profile"] = openclaw_profile(config)
    status["agent"] = openclaw_agent(config)
    status["workspace"] = str(openclaw_workspace(config))
    status["state_dir"] = str(openclaw_state_dir(config))
    status["gateway_port"] = openclaw_gateway_port(config)
    status["command_available"] = openclaw_command_available()
    status["workspace_exists"] = openclaw_workspace(config).exists()
    status["profile_config_exists"] = openclaw_profile_config_path(config).exists()
    status.update(openclaw_plugin_allow_fields(config))
    status.update(openclaw_memory_wiki_fields(config))
    status["installed"] = bool(
        status["command_available"]
        and status["workspace_exists"]
        and status["profile_config_exists"]
    )
    previous_gateway_reachable = status.get("gateway_last_authoritative_reachable")
    previous_gateway_checked_at = status.get("gateway_last_authoritative_checked_at")
    if (
        previous_gateway_reachable is None
        and status.get("gateway_probe_authoritative") is not False
        and status.get("updated_at")
    ):
        previous_gateway_reachable = status.get("gateway_reachable")
        previous_gateway_checked_at = status.get("updated_at")
    previous_gateway_status_ok = status.get("gateway_status_ok")
    status["gateway_reachable"] = gateway_reachable(int(status["gateway_port"]))
    command_path = openclaw_command()
    if include_gateway_probe and command_path and status["profile_config_exists"]:
        result = run(
            [command_path, "--profile", str(status["profile"]), "gateway", "status"],
            timeout=60,
        )
        output = ((result.stdout or "") + ("\n" + result.stderr if result.stderr else "")).strip()
        checked_at = utc_now()
        environment_limited = openclaw_gateway_probe_environment_limited(output)
        status["gateway_status_output"] = normalize_text(output, fallback="", limit=1200)
        status["gateway_probe_checked_at"] = checked_at
        status["gateway_probe_authoritative"] = not environment_limited
        status["gateway_probe_environment_limited"] = environment_limited
        status["gateway_probe_summary"] = (
            "Restricted execution environment could not authoritatively probe the running loopback gateway."
            if environment_limited
            else "OpenClaw gateway probe completed in the host execution environment."
        )
        if environment_limited:
            if previous_gateway_reachable is not None:
                status["gateway_reachable"] = previous_gateway_reachable
                status["gateway_status_ok"] = previous_gateway_status_ok
                status["gateway_last_authoritative_reachable"] = previous_gateway_reachable
                status["gateway_last_authoritative_checked_at"] = previous_gateway_checked_at
            else:
                status["gateway_status_ok"] = False
        else:
            status["gateway_status_ok"] = result.returncode == 0 and "Connectivity probe: ok" in output
            authoritative_reachable = bool(status["gateway_reachable"] or status["gateway_status_ok"])
            status["gateway_last_authoritative_reachable"] = authoritative_reachable
            status["gateway_last_authoritative_checked_at"] = checked_at
    else:
        status["gateway_status_ok"] = bool(status["gateway_reachable"])
    should_probe_config = include_gateway_probe if include_config_probe is None else include_config_probe
    if should_probe_config and command_path and status["profile_config_exists"]:
        previous_authoritative_valid = status.get("config_validation_last_authoritative_valid")
        previous_authoritative_checked_at = status.get("config_validation_last_authoritative_checked_at")
        if previous_authoritative_valid is None and status.get("config_validation_authoritative") is not False:
            previous_authoritative_valid = status.get("config_valid")
            previous_authoritative_checked_at = status.get("config_validation_checked_at")
        config_probe = probe_openclaw_config_validation(config)
        status.update(config_probe)
        if config_probe.get("config_validation_environment_limited") and previous_authoritative_valid is not None:
            status["config_valid"] = previous_authoritative_valid
            status["config_validation_last_authoritative_valid"] = previous_authoritative_valid
            status["config_validation_last_authoritative_checked_at"] = previous_authoritative_checked_at
    if include_memory_probe and command_path and status["profile_config_exists"]:
        memory_field_names = (
            "last_memory_probe_at",
            "memory_status_ok",
            "memory_status_severity",
            "memory_capability_available",
            "memory_status_summary",
            "memory_status_returncode",
            "memory_provider",
            "memory_model",
            "memory_files",
            "memory_chunks",
            "memory_dirty",
            "memory_embedding_ok",
            "memory_embedding_error",
        )
        previous_memory = {name: status.get(name) for name in memory_field_names}
        previous_memory_status_ok = status.get("memory_last_authoritative_status_ok")
        previous_memory_probe_at = status.get("memory_last_authoritative_probe_at")
        if previous_memory_status_ok is None and status.get("memory_probe_authoritative") is not False:
            previous_memory_status_ok = status.get("memory_status_ok")
            previous_memory_probe_at = status.get("last_memory_probe_at")
        memory_probe = probe_openclaw_memory_status(config)
        status.update(memory_probe)
        if memory_probe.get("memory_probe_environment_limited") and previous_memory_status_ok is not None:
            for name, value in previous_memory.items():
                status[name] = value
            status["memory_last_authoritative_status_ok"] = previous_memory_status_ok
            status["memory_last_authoritative_probe_at"] = previous_memory_probe_at
    if sync_history:
        latest_sync = sync_history[-1]
        latest_sync_at = normalize_text(latest_sync.get("timestamp"), fallback="", limit=80)
        if parse_iso_datetime(latest_sync_at) and (
            parse_iso_datetime(latest_sync_at)
            >= (parse_iso_datetime(status.get("last_sync_at")) or datetime.min.replace(tzinfo=timezone.utc))
        ):
            status["last_sync_at"] = latest_sync_at
            status["last_sync_ok"] = bool(latest_sync.get("ok"))
            status["last_sync_summary"] = normalize_text(
                latest_sync.get("summary") or latest_sync.get("error"),
                fallback=status.get("last_sync_summary") or "",
                limit=260,
            )
            status["last_sync_error"] = normalize_text(latest_sync.get("error"), fallback="", limit=260)
    recent_failures = [item for item in sync_history[-8:] if not bool(item.get("ok"))]
    status["sync_health_summary"] = summarize_openclaw_sync_health(sync_history)
    status["recent_sync_failures"] = len(recent_failures)
    status["summary"] = build_openclaw_summary(status)
    return status


def install_openclaw(
    config: Dict[str, object],
    *,
    install_daemon: bool = True,
    timeout: int = 600,
) -> Dict[str, object]:
    command = [str(INSTALL_SCRIPT)]
    if install_daemon:
        command.append("--install-daemon")
    result = run(command, timeout=timeout)
    status = collect_openclaw_status(config, include_gateway_probe=True)
    status.update(
        {
            "last_install_at": utc_now(),
            "last_install_ok": result.returncode == 0,
            "last_install_summary": normalize_text(
                result.stdout or result.stderr or "OpenClaw install completed.",
                fallback="OpenClaw install completed.",
                limit=260,
            ),
        }
    )
    if result.returncode != 0:
        status["last_error"] = normalize_text(result.stderr or result.stdout, fallback="OpenClaw install failed.", limit=260)
    else:
        status["last_error"] = ""
    status["summary"] = build_openclaw_summary(status)
    save_openclaw_status(status)
    return {
        "ok": result.returncode == 0,
        "status": status,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "returncode": result.returncode,
    }


def ensure_gateway_running(config: Dict[str, object], *, timeout: int = 120) -> Dict[str, object]:
    profile = openclaw_profile(config)
    install_result = run(["openclaw", "--profile", profile, "gateway", "install"], timeout=timeout)
    start_result = run(["openclaw", "--profile", profile, "gateway", "start"], timeout=timeout)
    status = collect_openclaw_status(config, include_gateway_probe=True)
    status["summary"] = build_openclaw_summary(status)
    save_openclaw_status(status)
    return {
        "ok": install_result.returncode == 0 and start_result.returncode == 0,
        "status": status,
        "stdout": "\n".join(filter(None, [install_result.stdout.strip(), start_result.stdout.strip()])),
        "stderr": "\n".join(filter(None, [install_result.stderr.strip(), start_result.stderr.strip()])),
        "returncode": start_result.returncode if start_result.returncode != 0 else install_result.returncode,
    }


def sync_openclaw(
    config: Dict[str, object],
    *,
    append_memory: bool = False,
    timeout: int = 180,
) -> Dict[str, object]:
    command = [sys.executable, str(SYNC_SCRIPT), "--workspace", str(openclaw_workspace(config))]
    if append_memory:
        command.append("--append-memory")
    result = run(command, timeout=timeout)
    command_root = ""
    if result.stdout:
        for line in result.stdout.splitlines():
            lowered = line.lower().strip()
            if lowered.startswith("command root:"):
                command_root = line.split(":", 1)[1].strip()
                break
    sync_summary = normalize_text(
        result.stdout or result.stderr or "OpenClaw sync completed.",
        fallback="OpenClaw sync completed.",
        limit=260,
    )
    sync_error = normalize_text(result.stderr or "", fallback="", limit=260)
    artifact_write_degraded = sync_artifact_write_degraded(result.stdout, result.stderr)
    sync_ok = result.returncode == 0 and not artifact_write_degraded
    status = collect_openclaw_status(config, include_gateway_probe=False)
    status.update(
        {
            "last_sync_at": utc_now(),
            "last_sync_ok": sync_ok,
            "last_sync_summary": sync_summary,
            "last_sync_error": "" if sync_ok else sync_error,
        }
    )
    if not sync_ok:
        status["last_error"] = normalize_text(result.stderr or result.stdout, fallback="OpenClaw sync failed.", limit=260)
    else:
        status["last_error"] = ""
    append_openclaw_sync_history(
        {
            "timestamp": status["last_sync_at"],
            "ok": sync_ok,
            "summary": sync_summary,
            "error": "" if sync_ok else sync_error or normalize_text(result.stderr or result.stdout, fallback="", limit=260),
            "returncode": result.returncode,
            "command_root": command_root,
            "workspace": str(openclaw_workspace(config)),
        }
    )
    status["sync_health_summary"] = summarize_openclaw_sync_health(load_openclaw_sync_history())
    status["summary"] = build_openclaw_summary(status)
    save_openclaw_status(status)
    record_openclaw_sync_state(status)
    return {
        "ok": sync_ok,
        "status": status,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "returncode": result.returncode,
        "artifact_write_degraded": artifact_write_degraded,
    }


def repair_openclaw(
    config: Dict[str, object],
    *,
    message: Optional[str] = None,
    timeout: Optional[int] = None,
    skip_sync: bool = False,
) -> Dict[str, object]:
    command = [
        sys.executable,
        str(REPAIR_SCRIPT),
        "--profile",
        openclaw_profile(config),
        "--workspace",
        str(openclaw_workspace(config)),
        "--agent",
        openclaw_agent(config),
        "--timeout",
        str(int(timeout or config.get("openclaw_timeout_seconds") or 900)),
        "--json",
    ]
    if skip_sync:
        command.append("--skip-sync")
    if message:
        command.extend(["--message", message])
    result = run(command, timeout=int(timeout or config.get("openclaw_timeout_seconds") or 900) + 120)

    payload: Dict[str, object] = {}
    if result.stdout.strip():
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            payload = parsed

    raw_reply = str(payload.get("reply") or result.stdout or result.stderr or "")
    reply = normalize_text(raw_reply, fallback="", limit=600)
    parsed_reply = payload.get("parsed_reply") if isinstance(payload.get("parsed_reply"), dict) else None
    if not parsed_reply:
        parsed_reply = parse_reply_json(raw_reply) if raw_reply else None
    if not parsed_reply and raw_reply:
        fallback_reply = parse_labeled_reply(raw_reply)
        if fallback_reply:
            parsed_reply = fallback_reply

    repair_status_value = normalize_text((parsed_reply or {}).get("status") or "", fallback="", limit=60)
    hard_failures = payload.get("hard_failures") if isinstance(payload.get("hard_failures"), list) else []
    payload_error = normalize_text(payload.get("error"), fallback="", limit=260)
    strict_repair_ok = bool(
        result.returncode == 0
        and isinstance(parsed_reply, dict)
        and repair_status_value in {"repaired", "diagnosed", "blocked"}
        and not hard_failures
        and not payload_error
    )

    status = collect_openclaw_status(config, include_gateway_probe=False)
    repair_issue = normalize_text((parsed_reply or {}).get("issue") or "", fallback="", limit=220)
    repair_next_step = normalize_text(
        (parsed_reply or {}).get("next_step") or (parsed_reply or {}).get("safest_next_step") or "",
        fallback="",
        limit=220,
    )
    repair_verified = normalize_text((parsed_reply or {}).get("verified") or "", fallback="", limit=220)
    status.update(
        {
            "last_repair_at": utc_now(),
            "last_repair_ok": strict_repair_ok,
            "last_repair_summary": normalize_text(
                (parsed_reply or {}).get("action")
                or repair_issue
                or payload_error
                or reply
                or "OpenClaw repair turn completed.",
                fallback="OpenClaw repair turn completed.",
                limit=260,
            ),
            "last_repair_issue": repair_issue,
            "last_repair_next_step": repair_next_step,
            "last_repair_status": repair_status_value,
            "last_repair_verified": repair_verified,
        }
    )
    if not strict_repair_ok:
        status["last_error"] = normalize_text(
            payload_error or result.stderr or result.stdout,
            fallback="OpenClaw repair failed or did not return strict JSON.",
            limit=260,
        )
    else:
        status["last_error"] = ""
    status["summary"] = build_openclaw_summary(status)
    save_openclaw_status(status)

    return {
        "ok": strict_repair_ok,
        "status": status,
        "reply": payload.get("reply") or result.stdout.strip(),
        "parsed_reply": parsed_reply or {},
        "payload": payload,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "returncode": result.returncode,
    }
