#!/usr/bin/env python3
"""Eve-owned subsystem capability and configuration intelligence.

This module is deliberately observational.  It inventories the software Eve
already sits on, records authoritative configuration surfaces, and identifies
bounded optimization opportunities.  It does not install packages, change
configuration, grant permissions, promote models, or write canonical memory.

The live Eve runtime owns recurrence, persistence, event emission, and any
later adoption decision.  Keeping those concerns outside this module makes the
collector usable in tests and prevents a feature scanner from becoming a
second scheduler or authority surface.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib import error, request


SCHEMA_ID = "eve_capability_intelligence.v4"
HISTORY_SCHEMA_ID = "eve_capability_intelligence_check.v4"
FEATURE_REVIEW_LIMIT = 200
REDACTED = "<redacted>"
SENSITIVE_KEY_PARTS = {
    "access_token",
    "apikey",
    "api_key",
    "auth",
    "authorization",
    "bearer",
    "client_secret",
    "cookie",
    "credential",
    "credentials",
    "key",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "session_token",
    "token",
    "webhook_secret",
}


CommandRunner = Callable[[Sequence[str], int, Optional[Dict[str, str]]], subprocess.CompletedProcess]
JsonFetcher = Callable[[str, int], Dict[str, object]]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_json_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compact_text(value: object, limit: int = 260) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def sensitive_key(key: object) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(key or "").strip().lower()).strip("_")
    if normalized in SENSITIVE_KEY_PARTS:
        return True
    return any(
        normalized.endswith(f"_{part}") or normalized.startswith(f"{part}_")
        for part in SENSITIVE_KEY_PARTS
        if part not in {"key", "auth"}
    )


def redact_payload(value: object, *, parent_key: str = "") -> object:
    """Return a recursively redacted, JSON-safe payload.

    Configuration paths and value types remain visible.  Credential-bearing
    values never enter the capability ledger, even when a subsystem happens to
    print them in a config dump.
    """

    if sensitive_key(parent_key):
        return REDACTED
    if isinstance(value, dict):
        return {str(key): redact_payload(item, parent_key=str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_payload(item, parent_key=parent_key) for item in value]
    if isinstance(value, tuple):
        return [redact_payload(item, parent_key=parent_key) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return compact_text(value, 500)


def flatten_mapping_paths(value: object, prefix: str = "") -> List[str]:
    paths: List[str] = []
    if isinstance(value, dict):
        if not value and prefix:
            paths.append(prefix)
        for key in sorted(value):
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.extend(flatten_mapping_paths(value[key], path))
    elif isinstance(value, list):
        path = f"{prefix}[]" if prefix else "[]"
        if not value:
            paths.append(path)
        else:
            for item in value[:8]:
                paths.extend(flatten_mapping_paths(item, path))
    elif prefix:
        paths.append(prefix)
    return sorted(set(paths))


def _schema_types(node: Dict[str, object]) -> List[str]:
    values: List[str] = []
    node_type = node.get("type")
    if isinstance(node_type, str):
        values.append(node_type)
    elif isinstance(node_type, list):
        values.extend(str(item) for item in node_type)
    for branch_key in ("anyOf", "oneOf", "allOf"):
        for branch in node.get(branch_key) or []:
            if isinstance(branch, dict):
                values.extend(_schema_types(branch))
                if "const" in branch:
                    values.append(type(branch.get("const")).__name__)
    return sorted(set(values))


def _schema_enum(node: Dict[str, object]) -> List[object]:
    values: List[object] = []
    if isinstance(node.get("enum"), list):
        values.extend(node["enum"])
    if "const" in node:
        values.append(node.get("const"))
    for branch_key in ("anyOf", "oneOf"):
        for branch in node.get(branch_key) or []:
            if isinstance(branch, dict):
                values.extend(_schema_enum(branch))
    deduped: List[object] = []
    seen: set[str] = set()
    for value in values:
        marker = json.dumps(value, ensure_ascii=True, sort_keys=True)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(value)
    return deduped[:40]


def catalog_json_schema(schema: object) -> List[Dict[str, object]]:
    """Flatten an authoritative JSON schema into human-usable config paths."""

    catalog: Dict[str, Dict[str, object]] = {}

    def walk(node: object, path: str, required: bool = False) -> None:
        if not isinstance(node, dict):
            return
        properties = node.get("properties") if isinstance(node.get("properties"), dict) else {}
        required_names = {str(item) for item in node.get("required") or []}
        if path:
            existing = catalog.setdefault(
                path,
                {
                    "path": path,
                    "types": [],
                    "required": bool(required),
                    "title": "",
                    "description": "",
                    "enum": [],
                },
            )
            existing["types"] = sorted(set([*existing.get("types", []), *_schema_types(node)]))
            existing["required"] = bool(existing.get("required") or required)
            existing["title"] = existing.get("title") or compact_text(node.get("title"), 160)
            existing["description"] = existing.get("description") or compact_text(node.get("description"), 420)
            enum_values = [*existing.get("enum", []), *_schema_enum(node)]
            enum_seen: set[str] = set()
            merged_enum: List[object] = []
            for enum_value in enum_values:
                marker = json.dumps(enum_value, ensure_ascii=True, sort_keys=True)
                if marker in enum_seen:
                    continue
                enum_seen.add(marker)
                merged_enum.append(enum_value)
            existing["enum"] = merged_enum[:40]
        for key, child in properties.items():
            child_path = f"{path}.{key}" if path else str(key)
            walk(child, child_path, str(key) in required_names)
        items = node.get("items")
        if isinstance(items, dict):
            walk(items, f"{path}[]" if path else "[]")
        for branch_key in ("allOf", "anyOf", "oneOf"):
            for branch in node.get(branch_key) or []:
                if isinstance(branch, dict):
                    walk(branch, path, required)

    walk(schema, "")
    return [catalog[key] for key in sorted(catalog)]


def default_command_runner(
    command: Sequence[str],
    timeout: int,
    env: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(item) for item in command],
        text=True,
        capture_output=True,
        timeout=max(1, int(timeout)),
        env=env,
    )


def run_command_json(
    runner: CommandRunner,
    command: Sequence[str],
    *,
    timeout: int,
    env: Optional[Dict[str, str]] = None,
) -> Tuple[Optional[object], Dict[str, object]]:
    evidence: Dict[str, object] = {
        "command": [str(item) for item in command],
        "ok": False,
        "returncode": None,
        "error": "",
    }
    try:
        completed = runner(command, timeout, env)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        evidence["error"] = compact_text(exc, 300)
        return None, evidence
    evidence["returncode"] = completed.returncode
    if completed.returncode != 0:
        evidence["error"] = compact_text(completed.stderr or completed.stdout, 300)
        return None, evidence
    try:
        payload = json.loads(completed.stdout or "")
    except json.JSONDecodeError as exc:
        evidence["error"] = f"invalid JSON: {compact_text(exc, 220)}"
        return None, evidence
    evidence["ok"] = True
    evidence["stdout_sha256"] = hashlib.sha256((completed.stdout or "").encode("utf-8")).hexdigest()
    return payload, evidence


def run_command_text(
    runner: CommandRunner,
    command: Sequence[str],
    *,
    timeout: int,
    env: Optional[Dict[str, str]] = None,
) -> Tuple[str, Dict[str, object]]:
    evidence: Dict[str, object] = {
        "command": [str(item) for item in command],
        "ok": False,
        "returncode": None,
        "error": "",
    }
    try:
        completed = runner(command, timeout, env)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        evidence["error"] = compact_text(exc, 300)
        return "", evidence
    evidence["returncode"] = completed.returncode
    if completed.returncode != 0:
        evidence["error"] = compact_text(completed.stderr or completed.stdout, 300)
        return "", evidence
    text = completed.stdout or ""
    evidence["ok"] = True
    evidence["stdout_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return text, evidence


def _compact_plugins(payload: object) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    if not isinstance(payload, dict):
        return [], []
    plugins: List[Dict[str, object]] = []
    for item in payload.get("plugins") or []:
        if not isinstance(item, dict):
            continue
        dependency = item.get("dependencyStatus") if isinstance(item.get("dependencyStatus"), dict) else {}
        plugins.append(
            {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or ""),
                "version": str(item.get("version") or ""),
                "origin": str(item.get("origin") or ""),
                "enabled": bool(item.get("enabled")),
                "status": str(item.get("status") or ""),
                "config_schema": bool(item.get("configSchema")),
                "tool_names": [str(value) for value in item.get("toolNames") or []],
                "hook_names": [str(value) for value in item.get("hookNames") or []],
                "channel_ids": [str(value) for value in item.get("channelIds") or []],
                "provider_ids": [str(value) for value in item.get("providerIds") or []],
                "cli_commands": [str(value) for value in item.get("cliCommands") or []],
                "dependencies_ok": bool(dependency.get("requiredInstalled", True)),
                "missing_dependencies": [str(value) for value in dependency.get("missing") or []],
            }
        )
    diagnostics = payload.get("diagnostics") if isinstance(payload.get("diagnostics"), list) else []
    registry = payload.get("registry") if isinstance(payload.get("registry"), dict) else {}
    diagnostics = [*diagnostics, *(registry.get("diagnostics") or [])]
    compact_diagnostics = [
        {
            "level": str(item.get("level") or ""),
            "code": str(item.get("code") or ""),
            "message": compact_text(item.get("message"), 300),
        }
        for item in diagnostics
        if isinstance(item, dict)
    ]
    return sorted(plugins, key=lambda item: item["id"]), compact_diagnostics


def _compact_openclaw_memory(payload: object) -> Dict[str, object]:
    agents = payload if isinstance(payload, list) else []
    rows: List[Dict[str, object]] = []
    for item in agents:
        if not isinstance(item, dict):
            continue
        status = item.get("status") if isinstance(item.get("status"), dict) else {}
        probe = item.get("embeddingProbe") if isinstance(item.get("embeddingProbe"), dict) else {}
        scan = item.get("scan") if isinstance(item.get("scan"), dict) else {}
        source_scan_issues = [
            compact_text(issue, 260)
            for source in scan.get("sources") or []
            if isinstance(source, dict)
            for issue in source.get("issues") or []
        ]
        scan_issues = sorted(
            set(
                [compact_text(value, 260) for value in scan.get("issues") or []]
                + source_scan_issues
            )
        )
        custom = status.get("custom") if isinstance(status.get("custom"), dict) else {}
        qmd = custom.get("qmd") if isinstance(custom.get("qmd"), dict) else {}
        backend = str(status.get("backend") or "")
        embedding_probe_ok = probe.get("ok") is True
        qmd_health_ok = (
            backend == "qmd"
            and int(status.get("files") or 0) > 0
            and not scan_issues
            and int(qmd.get("embedFailures") or 0) == 0
            and not qmd.get("embedBackoffUntil")
        )
        rows.append(
            {
                "agent_id": str(item.get("agentId") or ""),
                "backend": backend,
                "provider": str(status.get("provider") or ""),
                "model": str(status.get("model") or ""),
                "files": int(status.get("files") or 0),
                "chunks": int(status.get("chunks") or 0),
                "dirty": bool(status.get("dirty")),
                "embedding_probe_ok": embedding_probe_ok,
                "embedding_probe_error": compact_text(probe.get("error"), 300),
                "qmd_collections": int(qmd.get("collections") or 0),
                "qmd_embed_failures": int(qmd.get("embedFailures") or 0),
                "qmd_embed_backoff_until": qmd.get("embedBackoffUntil"),
                "scan_issues": scan_issues,
                "health_ok": qmd_health_ok if backend == "qmd" else embedding_probe_ok and not scan_issues,
            }
        )
    return {
        "agents": rows,
        "ok": bool(rows) and all(row.get("health_ok") for row in rows),
        "backends": sorted({str(row.get("backend") or "") for row in rows if row.get("backend")}),
        "providers": sorted({str(row.get("provider") or "") for row in rows if row.get("provider")}),
        "issue_count": sum(len(row.get("scan_issues") or []) for row in rows),
    }


def _compact_memory_search(payload: object) -> Dict[str, object]:
    if isinstance(payload, list):
        results = payload
    elif isinstance(payload, dict):
        results = payload.get("results") or payload.get("matches") or []
    else:
        results = []
    compact_results: List[Dict[str, object]] = []
    for item in results[:6]:
        if not isinstance(item, dict):
            continue
        compact_results.append(
            {
                "path": str(item.get("path") or item.get("file") or item.get("source") or item.get("uri") or ""),
                "score": item.get("score") if isinstance(item.get("score"), (int, float)) else item.get("relevance"),
            }
        )
    return {
        "ok": bool(compact_results),
        "result_count": len(compact_results),
        "results": compact_results,
    }


def _compact_openclaw_wiki(status_payload: object, search_payload: object) -> Dict[str, object]:
    status = status_payload if isinstance(status_payload, dict) else {}
    search = _compact_memory_search(search_payload)
    vault_path = str(status.get("vaultPath") or "")
    page_counts = status.get("pageCounts") if isinstance(status.get("pageCounts"), dict) else {}
    bridge = status.get("bridge") if isinstance(status.get("bridge"), dict) else {}
    warnings = [compact_text(value, 220) for value in status.get("warnings") or []][:20]
    status_ok = bool(
        status
        and status.get("vaultExists")
        and Path(vault_path).expanduser().is_absolute()
        and bridge.get("enabled")
        and int(page_counts.get("source") or 0) > 0
        and not warnings
    )
    return {
        "status_ok": status_ok,
        "cli_callable": bool(status_ok and search.get("ok")),
        "vault_mode": str(status.get("vaultMode") or ""),
        "vault_path": vault_path,
        "vault_path_absolute": bool(vault_path and Path(vault_path).expanduser().is_absolute()),
        "vault_exists": bool(status.get("vaultExists")),
        "bridge_enabled": bool(bridge.get("enabled")),
        "source_page_count": int(page_counts.get("source") or 0),
        "warnings": warnings,
        "search": search,
    }


def _semantic_version_from_text(value: object) -> str:
    match = re.search(r"\bv?([0-9]+\.[0-9]+(?:\.[0-9]+)?(?:[-+][A-Za-z0-9._-]+)?)\b", str(value or ""))
    return match.group(1) if match else compact_text(value, 120)


def _compact_openclaw_runtime(
    status_payload: object,
    health_payload: object,
    gateway_probe_payload: object,
) -> Dict[str, object]:
    """Keep only current OpenClaw process/connectivity evidence.

    ``config validate`` proves shape, not that the Eve-owned gateway process is
    loaded or reachable.  This compact contract binds the configured profile to
    its launch service, loopback RPC, event loop, plugins, and heartbeat state
    without retaining session content or credentials.
    """

    status = status_payload if isinstance(status_payload, dict) else {}
    health = health_payload if isinstance(health_payload, dict) else {}
    probe = gateway_probe_payload if isinstance(gateway_probe_payload, dict) else {}
    gateway = status.get("gateway") if isinstance(status.get("gateway"), dict) else {}
    service = status.get("gatewayService") if isinstance(status.get("gatewayService"), dict) else {}
    service_runtime = service.get("runtime") if isinstance(service.get("runtime"), dict) else {}
    service_layout = service.get("layout") if isinstance(service.get("layout"), dict) else {}
    event_loop = health.get("eventLoop") if isinstance(health.get("eventLoop"), dict) else {}
    plugins = health.get("plugins") if isinstance(health.get("plugins"), dict) else {}
    config_reload = health.get("configReload") if isinstance(health.get("configReload"), dict) else {}
    targets = [item for item in probe.get("targets") or [] if isinstance(item, dict)]
    primary = next((item for item in targets if item.get("active")), targets[0] if targets else {})
    connect = primary.get("connect") if isinstance(primary.get("connect"), dict) else {}
    heartbeat = status.get("heartbeat") if isinstance(status.get("heartbeat"), dict) else {}
    heartbeat_agents = [item for item in heartbeat.get("agents") or [] if isinstance(item, dict)]
    enabled_heartbeat_agents = [
        str(item.get("agentId"))
        for item in heartbeat_agents
        if item.get("enabled")
        and int(item.get("everyMs") or 0) > 0
        and str(item.get("every") or "").lower() not in {"0m", "disabled"}
    ]
    service_source = str(service_layout.get("sourcePath") or "")
    service_id_match = re.search(r"([^/]+)\.plist$", service_source)
    service_id = service_id_match.group(1) if service_id_match else ""
    ok = bool(
        gateway.get("reachable")
        and service.get("loaded")
        and str(service_runtime.get("status") or "") == "running"
        and health.get("ok")
        and not event_loop.get("degraded")
        and not plugins.get("errors")
        and probe.get("ok")
        and not probe.get("degraded")
        and connect.get("ok")
        and connect.get("rpcOk")
    )
    return {
        "ok": ok,
        "runtime_version": str(status.get("runtimeVersion") or ""),
        "gateway": {
            "mode": str(gateway.get("mode") or ""),
            "url": str(gateway.get("url") or ""),
            "reachable": bool(gateway.get("reachable")),
            "misconfigured": bool(gateway.get("misconfigured")),
            "connect_latency_ms": gateway.get("connectLatencyMs"),
        },
        "service": {
            "id": service_id,
            "installed": bool(service.get("installed")),
            "loaded": bool(service.get("loaded")),
            "managed_by_openclaw": bool(service.get("managedByOpenClaw")),
            "externally_managed": bool(service.get("externallyManaged")),
            "status": str(service_runtime.get("status") or "unknown"),
            "state": str(service_runtime.get("state") or ""),
            "pid": service_runtime.get("pid"),
            "source_path": service_source,
        },
        "health": {
            "ok": bool(health.get("ok")),
            "event_loop_degraded": bool(event_loop.get("degraded")),
            "event_loop_reasons": [compact_text(value, 180) for value in event_loop.get("reasons") or []][:10],
            "plugin_ids": [str(value) for value in plugins.get("loaded") or []][:40],
            "plugin_errors": [compact_text(value, 220) for value in plugins.get("errors") or []][:20],
            "config_hot_reload": str(config_reload.get("hotReloadStatus") or ""),
        },
        "probe": {
            "ok": bool(probe.get("ok")),
            "degraded": bool(probe.get("degraded")),
            "capability": str(probe.get("capability") or ""),
            "target_id": str(primary.get("id") or probe.get("primaryTargetId") or ""),
            "target_url": str(primary.get("url") or ""),
            "connect_ok": bool(connect.get("ok")),
            "rpc_ok": bool(connect.get("rpcOk")),
            "scope_limited": bool(connect.get("scopeLimited")),
            "warnings": [compact_text(value, 220) for value in probe.get("warnings") or []][:20],
            "excluded_discovery_count": int((probe.get("discovery") or {}).get("count") or 0)
            if isinstance(probe.get("discovery"), dict)
            else 0,
        },
        "heartbeat": {
            "default_agent_id": str(heartbeat.get("defaultAgentId") or ""),
            "enabled_agent_ids": enabled_heartbeat_agents,
            "enabled_count": len(enabled_heartbeat_agents),
            "duplicate_scheduler_risk": bool(enabled_heartbeat_agents),
        },
    }


def _compact_openclaw_tasks(
    payload: object,
    status_payload: object = None,
    list_payload: object = None,
    cron_status: object = None,
) -> Dict[str, object]:
    value = payload if isinstance(payload, dict) else {}
    summary = value.get("summary") if isinstance(value.get("summary"), dict) else {}
    runtime_status = status_payload if isinstance(status_payload, dict) else {}
    task_summary = runtime_status.get("tasks") if isinstance(runtime_status.get("tasks"), dict) else {}
    listed = list_payload if isinstance(list_payload, dict) else {}
    recent_tasks = [item for item in listed.get("tasks") or [] if isinstance(item, dict)]
    cron = cron_status if isinstance(cron_status, dict) else {}
    cron_jobs = [item for item in cron.get("jobs") or [] if isinstance(item, dict)]
    enabled_job_ids = {str(item.get("id")) for item in cron_jobs if item.get("enabled") and item.get("id")}
    disabled_job_ids = {str(item.get("id")) for item in cron_jobs if not item.get("enabled") and item.get("id")}
    terminal_failures = {"failed", "timed_out", "lost", "cancelled"}

    source_outcomes: Dict[str, List[Dict[str, object]]] = {}
    for item in recent_tasks:
        source_id = str(item.get("sourceId") or "")
        if source_id:
            source_outcomes.setdefault(source_id, []).append(item)

    def compact_source(source_id: str) -> Dict[str, object]:
        outcomes = sorted(
            source_outcomes.get(source_id, []),
            key=lambda item: int(item.get("createdAt") or item.get("startedAt") or 0),
            reverse=True,
        )
        statuses = [str(item.get("status") or "unknown") for item in outcomes]
        failures_for_source = sum(1 for status in statuses if status in terminal_failures)
        success_streak = 0
        for status in statuses:
            if status != "succeeded":
                break
            success_streak += 1
        latest = outcomes[0] if outcomes else {}
        return {
            "source_id": source_id,
            "label": compact_text(latest.get("label") or latest.get("task") or source_id, 160),
            "outcome_count": len(outcomes),
            "failure_count": failures_for_source,
            "failure_rate": round(failures_for_source / len(outcomes), 4) if outcomes else 0.0,
            "latest_status": str(latest.get("status") or "missing"),
            "latest_created_at_ms": int(latest.get("createdAt") or 0),
            "recent_success_streak": success_streak,
            "recent_window_failure_count": sum(1 for status in statuses[:5] if status in terminal_failures),
        }

    active_sources = [compact_source(source_id) for source_id in sorted(enabled_job_ids)]
    retired_sources = [compact_source(source_id) for source_id in sorted(disabled_job_ids)]
    active_total = sum(int(item.get("outcome_count") or 0) for item in active_sources)
    active_failures = sum(int(item.get("failure_count") or 0) for item in active_sources)
    active_covered = [item for item in active_sources if int(item.get("outcome_count") or 0) > 0]
    active_latest_failure_count = sum(
        1 for item in active_covered if str(item.get("latest_status") or "") in terminal_failures
    )
    active_reliability_ok = bool(
        active_sources
        and len(active_covered) == len(active_sources)
        and active_latest_failure_count == 0
        and all(int(item.get("recent_success_streak") or 0) >= 2 for item in active_sources)
    )
    taskflows = summary.get("taskFlows")
    taskflow_count = (
        int(taskflows.get("total") or 0)
        if isinstance(taskflows, dict)
        else int(taskflows or 0)
    )
    total = int(task_summary.get("total") or len(recent_tasks))
    failures = int(task_summary.get("failures") or 0)
    return {
        "finding_count": int(value.get("count") or summary.get("total") or 0),
        "warning_count": int(summary.get("warnings") or 0),
        "error_count": int(summary.get("errors") or 0),
        "taskflow_count": taskflow_count,
        "by_code": redact_payload(summary.get("byCode") or {}),
        "total": total,
        "active": int(task_summary.get("active") or 0),
        "terminal": int(task_summary.get("terminal") or 0),
        "failures": failures,
        "failure_rate": round(failures / total, 4) if total else 0.0,
        "by_status": redact_payload(task_summary.get("byStatus") or {}),
        "by_runtime": redact_payload(task_summary.get("byRuntime") or {}),
        "enabled_job_count": len(enabled_job_ids),
        "active_outcome_coverage_count": len(active_covered),
        "active_outcome_total": active_total,
        "active_failure_count": active_failures,
        "active_failure_rate": round(active_failures / active_total, 4) if active_total else 0.0,
        "active_latest_failure_count": active_latest_failure_count,
        "active_reliability_ok": active_reliability_ok,
        "active_sources": active_sources,
        "retired_sources": retired_sources,
        "recent_failure_labels": [
            compact_text(item.get("label") or item.get("task") or item.get("runtime"), 160)
            for item in recent_tasks
            if str(item.get("status") or "") in {"failed", "timed_out", "lost"}
        ][:20],
    }


def _compact_openclaw_commitments(payload: object) -> Dict[str, object]:
    value = payload if isinstance(payload, dict) else {}
    return {
        "count": int(value.get("count") or 0),
        "agent_id": str(value.get("agentId") or ""),
        "status_filter": str(value.get("status") or "all"),
    }


def _compact_openclaw_security(payload: object) -> Dict[str, object]:
    value = payload if isinstance(payload, dict) else {}
    summary = value.get("summary") if isinstance(value.get("summary"), dict) else {}
    findings: List[Dict[str, object]] = []
    for item in value.get("findings") or []:
        if not isinstance(item, dict):
            continue
        findings.append(
            {
                "id": str(item.get("checkId") or item.get("id") or "unknown"),
                "severity": str(item.get("severity") or "unknown"),
                "title": compact_text(item.get("title"), 220),
            }
        )
    return {
        "probe_observed": bool(value and isinstance(value.get("summary"), dict)),
        "critical": int(summary.get("critical") or 0),
        "warning": int(summary.get("warn") or summary.get("warning") or 0),
        "info": int(summary.get("info") or 0),
        "findings": findings[:40],
        "secret_diagnostic_count": len(value.get("secretDiagnostics") or []),
    }


def _compact_openclaw_skills(payload: object) -> Dict[str, object]:
    value = payload if isinstance(payload, dict) else {}
    summary = value.get("summary") if isinstance(value.get("summary"), dict) else {}
    return {
        "total": int(summary.get("total") or 0),
        "eligible": int(summary.get("eligible") or 0),
        "model_visible": int(summary.get("modelVisible") or 0),
        "command_visible": int(summary.get("commandVisible") or 0),
        "disabled": int(summary.get("disabled") or 0),
        "blocked": int(summary.get("blocked") or 0),
        "missing_requirements": int(summary.get("missingRequirements") or 0),
        "agent_skill_filter": [str(value) for value in (value.get("agentSkillFilter") or [])[:80]],
    }


def _compact_openclaw_hooks(payload: object) -> Dict[str, object]:
    value = payload if isinstance(payload, dict) else {}
    hooks: List[Dict[str, object]] = []
    for item in value.get("hooks") or []:
        if not isinstance(item, dict):
            continue
        hooks.append(
            {
                "name": str(item.get("name") or ""),
                "source": str(item.get("source") or ""),
                "events": [str(event) for event in (item.get("events") or [])[:20]],
            }
        )
    return {"count": len(hooks), "hooks": hooks[:40]}


def _compact_openclaw_cron(payload: object) -> Dict[str, object]:
    value = payload if isinstance(payload, dict) else {}
    jobs: List[Dict[str, object]] = []
    for item in value.get("jobs") or []:
        if not isinstance(item, dict):
            continue
        delivery = item.get("delivery") if isinstance(item.get("delivery"), dict) else {}
        state = item.get("state") if isinstance(item.get("state"), dict) else {}
        job_payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        name = compact_text(item.get("name"), 160)
        interpretive_standing_audit = bool(
            str(job_payload.get("kind") or "") == "agentTurn"
            and "standing audit" in name.lower()
        )
        jobs.append(
            {
                "id": str(item.get("id") or ""),
                "name": name,
                "agent_id": str(item.get("agentId") or ""),
                "enabled": bool(item.get("enabled")),
                "schedule": redact_payload(item.get("schedule") or {}),
                "session_target": str(item.get("sessionTarget") or ""),
                "delivery_mode": str(delivery.get("mode") or ""),
                "payload_kind": str(job_payload.get("kind") or ""),
                "last_status": str(state.get("lastStatus") or state.get("lastRunStatus") or ""),
                "consecutive_errors": int(state.get("consecutiveErrors") or 0),
                "interpretive_standing_audit": interpretive_standing_audit,
            }
        )
    redundant = [str(item.get("id")) for item in jobs if item.get("enabled") and item.get("interpretive_standing_audit")]
    return {
        "count": int(value.get("total") or len(jobs)),
        "enabled_count": len([item for item in jobs if item.get("enabled")]),
        "jobs": jobs[:30],
        "redundant_standing_audit_ids": redundant,
        "duplicate_scheduler_risk": bool(redundant),
    }


def _compact_openclaw_mcp(payload: object) -> Dict[str, object]:
    value = payload if isinstance(payload, dict) else {}
    return {"server_count": len(value), "server_ids": sorted(str(key) for key in value)[:60]}


def _compact_openclaw_isolation(
    worktrees_payload: object,
    sandbox_payload: object,
) -> Dict[str, object]:
    worktrees = worktrees_payload if isinstance(worktrees_payload, dict) else {}
    sandboxes = sandbox_payload if isinstance(sandbox_payload, dict) else {}
    return {
        "managed_worktree_count": len(worktrees.get("worktrees") or []),
        "sandbox_container_count": len(sandboxes.get("containers") or []),
        "browser_container_count": len(sandboxes.get("browsers") or []),
    }


def _compact_openclaw_approvals(payload: object) -> Dict[str, object]:
    value = payload if isinstance(payload, dict) else {}
    policy = value.get("effectivePolicy") if isinstance(value.get("effectivePolicy"), dict) else {}
    file_payload = value.get("file") if isinstance(value.get("file"), dict) else {}
    defaults = file_payload.get("defaults") if isinstance(file_payload.get("defaults"), dict) else {}
    return {
        "configured": bool(value.get("exists")),
        "effective_scope_count": len(policy.get("scopes") or []),
        "default_security": str(defaults.get("security") or ""),
        "default_ask": str(defaults.get("ask") or ""),
    }


def _compact_openclaw_context_management(current_config: object) -> Dict[str, object]:
    """Expose only the OpenClaw settings that bound long tool-heavy turns."""

    config = current_config if isinstance(current_config, dict) else {}
    agents = config.get("agents") if isinstance(config.get("agents"), dict) else {}
    defaults = agents.get("defaults") if isinstance(agents.get("defaults"), dict) else {}
    compaction = defaults.get("compaction") if isinstance(defaults.get("compaction"), dict) else {}
    mid_turn = (
        compaction.get("midTurnPrecheck")
        if isinstance(compaction.get("midTurnPrecheck"), dict)
        else {}
    )
    pruning = defaults.get("contextPruning") if isinstance(defaults.get("contextPruning"), dict) else {}
    tools = config.get("tools") if isinstance(config.get("tools"), dict) else {}
    loop_detection = tools.get("loopDetection") if isinstance(tools.get("loopDetection"), dict) else {}
    compaction_mode = str(compaction.get("mode") or "")
    pruning_mode = str(pruning.get("mode") or "")
    pruning_ttl = str(pruning.get("ttl") or "")
    mid_turn_enabled = mid_turn.get("enabled") is True
    loop_detection_enabled = loop_detection.get("enabled") is True
    configured_ok = bool(
        compaction_mode == "safeguard"
        and mid_turn_enabled
        and pruning_mode == "cache-ttl"
        and pruning_ttl
        and loop_detection_enabled
    )
    return {
        "compaction_mode": compaction_mode,
        "mid_turn_precheck_enabled": mid_turn_enabled,
        "context_pruning_mode": pruning_mode,
        "context_pruning_ttl": pruning_ttl,
        "keep_last_assistants": pruning.get("keepLastAssistants"),
        "loop_detection_enabled": loop_detection_enabled,
        "configured_ok": configured_ok,
    }


def build_capability_lifecycle(
    *,
    discovered: bool,
    configured: bool = False,
    enabled: bool = False,
    callable_now: bool = False,
    consequence_verified: bool = False,
) -> Dict[str, object]:
    """Normalize capability evidence without promoting source discovery.

    Later stages require every earlier stage.  Consequence verification is a
    property of a callable path, not of documentation, package presence, or a
    configuration record.  This keeps capability counts honest while still
    preserving dormant/configured feature evidence.
    """

    discovered = bool(discovered)
    configured = bool(discovered and configured)
    enabled = bool(configured and enabled)
    callable_now = bool(enabled and callable_now)
    consequence_verified = bool(callable_now and consequence_verified)
    if consequence_verified:
        stage = "verified"
    elif callable_now:
        stage = "callable"
    elif enabled:
        stage = "enabled"
    elif configured:
        stage = "configured"
    elif discovered:
        stage = "discovered"
    else:
        stage = "unavailable"
    return {
        "stage": stage,
        "discovered": discovered,
        "configured": configured,
        "enabled": enabled,
        "callable": callable_now,
        "consequence_verified": consequence_verified,
    }


def build_openclaw_feature_family_reviews(
    *,
    current_config: Dict[str, object],
    config_valid: bool,
    memory_status: Dict[str, object],
    plugins: Sequence[Dict[str, object]],
    tasks: Dict[str, object],
    commitments: Dict[str, object],
    security: Dict[str, object],
    mcp: Dict[str, object],
    skills: Dict[str, object],
    hooks: Dict[str, object],
    cron: Dict[str, object],
    isolation: Dict[str, object],
    approvals: Dict[str, object],
    runtime_status: Dict[str, object],
    deterministic_audit: Dict[str, object],
    wiki_status: Optional[Dict[str, object]] = None,
) -> List[Dict[str, object]]:
    """Classify OpenClaw feature families against Eve's existing contracts."""

    gateway = current_config.get("gateway") if isinstance(current_config.get("gateway"), dict) else {}
    channels = current_config.get("channels") if isinstance(current_config.get("channels"), dict) else {}
    gateway_bind = str(gateway.get("bind") or "")
    loopback_only = gateway_bind in {"loopback", "localhost", "127.0.0.1", "::1"}
    skill_filter = {str(value) for value in skills.get("agent_skill_filter") or []}
    accepted_security: List[str] = []
    actionable_security: List[str] = []
    for finding in security.get("findings") or []:
        if not isinstance(finding, dict):
            continue
        finding_id = str(finding.get("id") or "unknown")
        title = str(finding.get("title") or "")
        severity = str(finding.get("severity") or "")
        accepted_reason = f"informational:{finding_id}" if severity == "info" else ""
        if finding_id == "gateway.trusted_proxies_missing" and loopback_only:
            accepted_reason = f"loopback_only:{finding_id}"
        if finding_id == "tools.exec.agent_skill_mcp_boundary_drift":
            accepted_reason = f"documented_host_exec_mcp_boundary:{finding_id}"
        if finding_id == "skills.code_safety":
            named_skill = re.search(r'Skill\s+"([^"]+)"', title)
            if named_skill and named_skill.group(1) not in skill_filter:
                accepted_reason = f"not_admitted_skill:{named_skill.group(1)}:{finding_id}"
        (accepted_security if accepted_reason else actionable_security).append(accepted_reason or finding_id)

    enabled_channels = sorted(
        str(channel_id)
        for channel_id, value in channels.items()
        if isinstance(value, dict) and value.get("enabled") is True
    )
    dormant_channels = sorted(
        str(channel_id)
        for channel_id, value in channels.items()
        if isinstance(value, dict) and value.get("enabled") is False
    )
    plugin_ids = {
        str(item.get("id"))
        for item in plugins
        if isinstance(item, dict) and item.get("enabled") and item.get("id")
    }
    hook_names = {str(item.get("name")) for item in hooks.get("hooks") or [] if isinstance(item, dict)}
    heartbeat = runtime_status.get("heartbeat") if isinstance(runtime_status.get("heartbeat"), dict) else {}
    live_gateway_ok = bool(runtime_status.get("ok"))
    audit_ok = bool(deterministic_audit.get("ok") and deterministic_audit.get("status") == "ready")
    context_management = _compact_openclaw_context_management(current_config)
    wiki_status = wiki_status if isinstance(wiki_status, dict) else {}
    tools_config = current_config.get("tools") if isinstance(current_config.get("tools"), dict) else {}
    global_also_allow = {str(value) for value in tools_config.get("alsoAllow") or []}
    expected_wiki_tools = {
        "wiki_apply",
        "wiki_get",
        "wiki_lint",
        "wiki_search",
        "wiki_status",
    }
    wiki_resident_config_admitted = expected_wiki_tools.issubset(global_also_allow)

    def review(
        family: str,
        *,
        current_state: str,
        decision: str,
        rationale: str,
        configuration_action: str,
        evidence: Sequence[str],
    ) -> Dict[str, object]:
        return {
            "id": f"openclaw:{family}",
            "subsystem": "openclaw",
            "family": family,
            "current_state": current_state,
            "decision": decision,
            "rationale": compact_text(rationale, 420),
            "configuration_action": compact_text(configuration_action, 500),
            "evidence": [compact_text(value, 260) for value in evidence[:12]],
            "authority_boundary": "OpenClaw is Eve's body/action nervous system; it does not own identity or canonical memory.",
        }

    reviews = [
        review(
            "gateway",
            current_state=f"bind={gateway_bind or 'unknown'},config_valid={config_valid},runtime_ok={live_gateway_ok}",
            decision="use_existing" if config_valid and loopback_only and live_gateway_ok else "configure",
            rationale="The local gateway is admitted only when the Eve profile, launch service, loopback RPC, and health probe agree.",
            configuration_action="Keep it loopback-only and repair the Eve-owned service/probe before adding another gateway.",
            evidence=["openclaw status --json", "openclaw health --json", "openclaw gateway probe --json", "openclaw config validate --json"],
        ),
        review(
            "context_management",
            current_state=(
                f"compaction={context_management.get('compaction_mode') or 'unset'},"
                f"mid_turn_precheck={bool(context_management.get('mid_turn_precheck_enabled'))},"
                f"pruning={context_management.get('context_pruning_mode') or 'unset'},"
                f"loop_detection={bool(context_management.get('loop_detection_enabled'))}"
            ),
            decision="use_existing" if config_valid and context_management.get("configured_ok") else "configure",
            rationale=(
                "Long tool-heavy local-model repairs can exceed the context window before ordinary turn-end compaction. "
                "OpenClaw's shipped mid-turn precheck, cache-TTL pruning, and tool-loop detection bound that failure mode."
            ),
            configuration_action=(
                "Keep safeguard compaction with midTurnPrecheck enabled, cache-ttl context pruning with an explicit TTL, "
                "and loop detection enabled; validate the profile and run a bounded strict-contract repair canary after changes."
            ),
            evidence=[
                "openclaw config get agents.defaults.compaction --json",
                "openclaw config get agents.defaults.contextPruning --json",
                "openclaw config get tools.loopDetection --json",
                "openclaw config validate --json",
                "eve.py openclaw repair bounded strict-contract canary",
            ],
        ),
        review(
            "memory_qmd",
            current_state="healthy" if memory_status.get("ok") else "degraded",
            decision="use_existing" if memory_status.get("ok") else "configure",
            rationale="QMD gives OpenClaw local retrieval without making it Eve's canonical memory authority.",
            configuration_action="Keep session transcript indexing disabled; reindex and rerun bounded retrieval if health degrades.",
            evidence=["openclaw memory status --deep --json", "openclaw memory search --json"],
        ),
        review(
            "memory_wiki",
            current_state=(
                f"vault={wiki_status.get('vault_path') or 'unknown'},"
                f"cli_callable={bool(wiki_status.get('cli_callable'))},"
                f"resident_tools_configured={wiki_resident_config_admitted},"
                "resident_consequence_verified=False"
            ),
            decision=(
                "configure"
                if not wiki_status.get("status_ok")
                else "canary"
            ),
            rationale=(
                "The memory wiki is an OpenClaw presentation/retrieval organ. CLI status/search evidence proves only the CLI surface; "
                "resident Eve callability requires the five admitted wiki tools in a fresh agent context plus an exact tool receipt."
            ),
            configuration_action=(
                "Use one existing absolute vault, admit exactly wiki_apply/get/lint/search/status, then require a fresh resident trace "
                "showing the intended wiki tool and verified result before calling the capability resident-callable."
            ),
            evidence=[
                "openclaw wiki status --json",
                "openclaw wiki search Eve Capability Intelligence --backend local --corpus wiki --max-results 1 --json",
                "fresh OpenClaw agent context.compiled tool inventory",
                "fresh resident tool execution receipt",
            ],
        ),
        review(
            "skills",
            current_state=(
                f"visible={int(skills.get('model_visible') or 0)},missing={int(skills.get('missing_requirements') or 0)}"
            ),
            decision=(
                "use_existing"
                if int(skills.get("model_visible") or 0) > 0 and int(skills.get("missing_requirements") or 0) == 0
                else "configure"
            ),
            rationale="The agent allowlist keeps Eve's body procedures explicit and inspectable.",
            configuration_action="Keep the ten Eve-owned skills aligned across main and eve-repair; admit new skills one contract at a time.",
            evidence=["openclaw skills check --json"],
        ),
        review(
            "mcp",
            current_state=f"servers={int(mcp.get('server_count') or 0)}",
            decision="use_existing" if int(mcp.get("server_count") or 0) > 0 else "configure",
            rationale="MCP is the admitted interop bridge for bounded channel/action services.",
            configuration_action="Keep server IDs and credentials explicit; do not assume a skill allowlist constrains host-level MCP clients.",
            evidence=["openclaw mcp list --json"],
        ),
        review(
            "hooks",
            current_state=f"hooks={int(hooks.get('count') or 0)}",
            decision="use_existing" if "eve-evidence-ingest" in hook_names else "configure",
            rationale="Hooks provide lifecycle evidence without becoming a second scheduler.",
            configuration_action="Retain eve-evidence-ingest and bundled audit/compaction hooks; require a named event and bounded output for additions.",
            evidence=["openclaw hooks list --json"],
        ),
        review(
            "taskflow",
            current_state=(
                f"findings={int(tasks.get('finding_count') or 0)},errors={int(tasks.get('error_count') or 0)},"
                f"historical_outcomes={int(tasks.get('total') or 0)},historical_failures={int(tasks.get('failures') or 0)},"
                f"enabled_jobs={int(tasks.get('enabled_job_count') or 0)},active_latest_failures={int(tasks.get('active_latest_failure_count') or 0)},"
                f"active_reliability_ok={bool(tasks.get('active_reliability_ok'))}"
            ),
            decision=(
                "configure"
                if int(tasks.get("error_count") or 0) > 0 or int(tasks.get("active_latest_failure_count") or 0) > 0
                else "use_existing"
                if tasks.get("active_reliability_ok")
                else "canary"
            ),
            rationale="TaskFlow structure, retired-job history, and currently enabled job outcomes are separate evidence; disabling a bad routine does not erase history, but its failures must not permanently mis-score a repaired active path.",
            configuration_action="Keep Eve's executive scheduler authoritative; retire failing jobs and require at least two consecutive linked successes for every enabled OpenClaw maintenance job before calling the current path reliable.",
            evidence=["openclaw tasks audit --json", "openclaw tasks list --json", "openclaw status --json"],
        ),
        review(
            "commitments",
            current_state=f"records={int(commitments.get('count') or 0)}",
            decision="defer",
            rationale="OpenClaw can infer follow-up commitments, but Eve already owns a verified follow-up ledger.",
            configuration_action="Leave this observational until a canary proves it does not duplicate Eve's promises or send twice.",
            evidence=["openclaw commitments --all --json"],
        ),
        review(
            "cron",
            current_state=(
                f"jobs={int(cron.get('count') or 0)},enabled={int(cron.get('enabled_count') or 0)},"
                f"redundant_audits={len(cron.get('redundant_standing_audit_ids') or [])},deterministic_audit_ok={audit_ok}"
            ),
            decision="configure" if cron.get("duplicate_scheduler_risk") else "use_existing" if int(cron.get("enabled_count") or 0) > 0 else "defer",
            rationale="OpenClaw cron may maintain its own plugin state, but model-written standing audits must not reinterpret deterministic Eve health as a second authority.",
            configuration_action=(
                "Disable the interpretive standing-audit agent job and use Eve's deterministic OpenClaw audit artifact; retain only separately owned no-delivery maintenance jobs."
                if cron.get("duplicate_scheduler_risk")
                else "Keep delivery disabled and do not migrate Eve's executive scheduler into OpenClaw cron."
            ),
            evidence=["openclaw cron list --all --json", "eve.py openclaw audit --full", f"deterministic_audit={deterministic_audit.get('status') or 'missing'}"],
        ),
        review(
            "heartbeat",
            current_state=f"enabled_agents={','.join(heartbeat.get('enabled_agent_ids') or []) or 'none'}",
            decision="configure" if heartbeat.get("duplicate_scheduler_risk") else "use_existing",
            rationale="OpenClaw's default heartbeat is a periodic agent turn; Eve already has an executive scheduler and should not acquire an unattributed second recurring mind loop.",
            configuration_action=(
                "Set agents.defaults.heartbeat.every to 0m; TaskFlow completion remains attributable through its own task/evidence path."
                if heartbeat.get("duplicate_scheduler_risk")
                else "Keep the OpenClaw default heartbeat disabled; use Eve's scheduler for recurring cognition."
            ),
            evidence=["openclaw status --json", "openclaw config schema:agents.defaults.heartbeat.every"],
        ),
        review(
            "exec_approvals",
            current_state=f"configured={bool(approvals.get('configured'))},scopes={int(approvals.get('effective_scope_count') or 0)}",
            decision="use_existing" if approvals.get("configured") else "configure",
            rationale="The approval policy records the host execution boundary used by Eve's body.",
            configuration_action="Keep explicit defaults/scopes and review changes with the OpenClaw security audit.",
            evidence=["openclaw approvals get --json"],
        ),
        review(
            "acp",
            current_state="loaded" if "acpx" in plugin_ids else "not_loaded",
            decision="use_existing" if "acpx" in plugin_ids else "configure",
            rationale="ACPX provides a durable agent transport without creating another Eve identity.",
            configuration_action="Keep the plugin version pinned to the OpenClaw core line and attribute every ACP run.",
            evidence=["openclaw plugins list --json"],
        ),
        review(
            "managed_worktrees",
            current_state=f"active={int(isolation.get('managed_worktree_count') or 0)}",
            decision="canary",
            rationale="Managed worktrees can isolate future self-build work, but are not needed for every repair.",
            configuration_action="Canary one bounded build with explicit parent task, diff, tests, and cleanup before routine use.",
            evidence=["openclaw worktrees list --json"],
        ),
        review(
            "sandbox",
            current_state=(
                f"containers={int(isolation.get('sandbox_container_count') or 0)},browser={int(isolation.get('browser_container_count') or 0)}"
            ),
            decision="canary",
            rationale="Sandboxing can isolate untrusted or destructive specialist work without constraining ordinary local observation.",
            configuration_action="Canary only for a named risky workflow and verify filesystem, network, credential, and cleanup boundaries.",
            evidence=["openclaw sandbox list --json"],
        ),
        review(
            "channels",
            current_state=f"enabled={','.join(enabled_channels) or 'none'};dormant={','.join(dormant_channels) or 'none'}",
            decision="use_existing",
            rationale="Installed channel adapters remain subordinate to Eve's send/recipient permissions.",
            configuration_action="Keep iMessage dormant until specifically approved; configure only channels with a named recipient and delivery contract.",
            evidence=["openclaw channels status --json", "openclaw config validate --json"],
        ),
        review(
            "security_audit",
            current_state=(
                f"findings={len(security.get('findings') or [])},accepted={len(accepted_security)},actionable={len(actionable_security)}"
            ),
            decision="configure" if actionable_security else "use_existing",
            rationale="The live audit distinguishes real boundary drift from accepted loopback/local-operator findings.",
            configuration_action=(
                f"Resolve unaccepted findings: {', '.join(actionable_security)}."
                if actionable_security
                else "Retain the documented loopback, host-exec/MCP, and non-allowlisted global-skill exceptions; re-evaluate on config or version change."
            ),
            evidence=["openclaw security audit --deep --json", *[f"accepted:{value}" for value in accepted_security]],
        ),
    ]

    service = runtime_status.get("service") if isinstance(runtime_status.get("service"), dict) else {}
    runtime_probe = runtime_status.get("probe") if isinstance(runtime_status.get("probe"), dict) else {}
    retrieval_smoke = (
        memory_status.get("retrieval_smoke")
        if isinstance(memory_status.get("retrieval_smoke"), dict)
        else {}
    )
    all_plugin_ids = {
        str(item.get("id"))
        for item in plugins
        if isinstance(item, dict) and item.get("id")
    }
    evidence_hook = next(
        (
            item
            for item in hooks.get("hooks") or []
            if isinstance(item, dict) and item.get("name") == "eve-evidence-ingest"
        ),
        {},
    )
    evidence_hook_events = evidence_hook.get("events") if isinstance(evidence_hook.get("events"), list) else []
    agents = current_config.get("agents") if isinstance(current_config.get("agents"), dict) else {}
    agent_defaults = agents.get("defaults") if isinstance(agents.get("defaults"), dict) else {}
    heartbeat_config = (
        agent_defaults.get("heartbeat")
        if isinstance(agent_defaults.get("heartbeat"), dict)
        else {}
    )
    gateway_configured = bool(config_valid and loopback_only)
    gateway_enabled = bool(
        gateway_configured
        and service.get("loaded")
        and str(service.get("status") or "") == "running"
    )
    gateway_callable = bool(
        gateway_enabled
        and runtime_probe.get("connect_ok")
        and runtime_probe.get("rpc_ok")
    )
    memory_configured = "qmd" in {str(value) for value in memory_status.get("backends") or []}
    skill_filter_ready = bool(skill_filter)
    skill_enabled = bool(
        skill_filter_ready
        and int(skills.get("model_visible") or 0) == len(skill_filter)
    )
    skill_callable = bool(
        skill_enabled
        and int(skills.get("command_visible") or 0) == len(skill_filter)
    )
    lifecycles = {
        "gateway": build_capability_lifecycle(
            discovered=True,
            configured=gateway_configured,
            enabled=gateway_enabled,
            callable_now=gateway_callable,
            consequence_verified=live_gateway_ok,
        ),
        "context_management": build_capability_lifecycle(
            discovered=True,
            configured=bool(context_management.get("configured_ok")),
            enabled=gateway_enabled,
            callable_now=bool(live_gateway_ok),
            consequence_verified=False,
        ),
        "memory_qmd": build_capability_lifecycle(
            discovered=True,
            configured=memory_configured,
            enabled=bool(memory_configured and memory_status.get("agents")),
            callable_now=bool(retrieval_smoke.get("ok")),
            consequence_verified=bool(memory_status.get("ok")),
        ),
        "memory_wiki": build_capability_lifecycle(
            discovered="memory-wiki" in all_plugin_ids,
            configured=bool(
                "memory-wiki" in all_plugin_ids and wiki_status.get("status_ok")
            ),
            enabled=bool(
                "memory-wiki" in plugin_ids and wiki_status.get("status_ok")
            ),
            callable_now=False,
            consequence_verified=False,
        ),
        "skills": build_capability_lifecycle(
            discovered=True,
            configured=skill_filter_ready,
            enabled=skill_enabled,
            callable_now=skill_callable,
            consequence_verified=bool(
                skill_callable
                and int(skills.get("blocked") or 0) == 0
                and int(skills.get("missing_requirements") or 0) == 0
            ),
        ),
        "mcp": build_capability_lifecycle(
            discovered=True,
            configured=int(mcp.get("server_count") or 0) > 0,
            enabled=int(mcp.get("server_count") or 0) > 0,
            callable_now=False,
            consequence_verified=False,
        ),
        "hooks": build_capability_lifecycle(
            discovered=True,
            configured=bool(evidence_hook),
            enabled=bool(evidence_hook_events),
            callable_now=False,
            consequence_verified=False,
        ),
        "taskflow": build_capability_lifecycle(
            discovered=True,
            configured=int(tasks.get("enabled_job_count") or 0) > 0,
            enabled=int(tasks.get("enabled_job_count") or 0) > 0,
            callable_now=bool(
                int(tasks.get("taskflow_count") or 0) > 0
                or int(tasks.get("active_outcome_coverage_count") or 0) > 0
            ),
            consequence_verified=bool(tasks.get("active_reliability_ok")),
        ),
        "commitments": build_capability_lifecycle(discovered=True),
        "cron": build_capability_lifecycle(
            discovered=True,
            configured=int(cron.get("count") or 0) > 0,
            enabled=int(cron.get("enabled_count") or 0) > 0,
            callable_now=bool(
                int(cron.get("enabled_count") or 0) > 0
                and not cron.get("duplicate_scheduler_risk")
            ),
            consequence_verified=False,
        ),
        "heartbeat": build_capability_lifecycle(
            discovered=True,
            configured="every" in heartbeat_config,
            enabled=int(heartbeat.get("enabled_count") or 0) > 0,
            callable_now=int(heartbeat.get("enabled_count") or 0) > 0,
            consequence_verified=False,
        ),
        "exec_approvals": build_capability_lifecycle(
            discovered=True,
            configured=bool(approvals.get("configured")),
            enabled=int(approvals.get("effective_scope_count") or 0) > 0,
            callable_now=False,
            consequence_verified=False,
        ),
        "acp": build_capability_lifecycle(
            discovered=True,
            configured="acpx" in all_plugin_ids,
            enabled="acpx" in plugin_ids,
            callable_now=False,
            consequence_verified=False,
        ),
        "managed_worktrees": build_capability_lifecycle(
            discovered=True,
            configured=int(isolation.get("managed_worktree_count") or 0) > 0,
            enabled=int(isolation.get("managed_worktree_count") or 0) > 0,
            callable_now=int(isolation.get("managed_worktree_count") or 0) > 0,
            consequence_verified=False,
        ),
        "sandbox": build_capability_lifecycle(
            discovered=True,
            configured=(
                int(isolation.get("sandbox_container_count") or 0) > 0
                or int(isolation.get("browser_container_count") or 0) > 0
            ),
            enabled=(
                int(isolation.get("sandbox_container_count") or 0) > 0
                or int(isolation.get("browser_container_count") or 0) > 0
            ),
            callable_now=False,
            consequence_verified=False,
        ),
        "channels": build_capability_lifecycle(
            discovered=bool(channels),
            configured=bool(enabled_channels),
            enabled=bool(enabled_channels),
            callable_now=False,
            consequence_verified=False,
        ),
        "security_audit": build_capability_lifecycle(
            discovered=True,
            configured=bool(security.get("probe_observed")),
            enabled=bool(security.get("probe_observed")),
            callable_now=bool(security.get("probe_observed")),
            consequence_verified=bool(
                security.get("probe_observed") and not actionable_security
            ),
        ),
    }
    for item in reviews:
        item["lifecycle"] = lifecycles.get(
            str(item.get("family") or ""),
            build_capability_lifecycle(discovered=True),
        )
        if item.get("family") == "memory_wiki":
            item["lifecycle"]["interfaces"] = {
                "cli_callable": bool(wiki_status.get("cli_callable")),
                "resident_config_admitted": wiki_resident_config_admitted,
                "resident_callable": False,
                "resident_consequence_verified": False,
            }
    return reviews


def collect_openclaw_snapshot(
    *,
    profile: str,
    config_path: Path,
    mcporter_config_path: Optional[Path] = None,
    command: str = "openclaw",
    qmd_command: str = "qmd",
    mcporter_command: str = "mcporter",
    timeout: int = 30,
    runner: CommandRunner = default_command_runner,
    deterministic_audit: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    prefix = [command, "--profile", profile]
    version_text, version_evidence = run_command_text(runner, [command, "--version"], timeout=timeout)
    schema, schema_evidence = run_command_json(runner, [*prefix, "config", "schema"], timeout=timeout)
    plugins_payload, plugins_evidence = run_command_json(
        runner, [*prefix, "plugins", "list", "--json"], timeout=timeout
    )
    validate_payload, validate_evidence = run_command_json(
        runner, [*prefix, "config", "validate", "--json"], timeout=timeout
    )
    update_payload, update_evidence = run_command_json(
        runner, [*prefix, "update", "--dry-run", "--json"], timeout=timeout
    )
    memory_payload, memory_evidence = run_command_json(
        runner, [*prefix, "memory", "status", "--deep", "--json"], timeout=max(timeout, 90)
    )
    memory_search_payload, memory_search_evidence = run_command_json(
        runner,
        [
            *prefix,
            "memory",
            "search",
            "--agent",
            profile,
            "--query",
            "Eve Capability Intelligence",
            "--max-results",
            "3",
            "--json",
        ],
        timeout=max(timeout, 60),
    )
    probe_specs: Dict[str, Tuple[List[str], int]] = {
        "status": ([*prefix, "status", "--json"], timeout),
        "health": ([*prefix, "health", "--json"], timeout),
        "gateway_probe": ([*prefix, "gateway", "probe", "--json"], timeout),
        "tasks": ([*prefix, "tasks", "audit", "--json"], timeout),
        "tasks_list": ([*prefix, "tasks", "list", "--json"], timeout),
        "commitments": ([*prefix, "commitments", "--all", "--json"], timeout),
        "security": ([*prefix, "security", "audit", "--deep", "--json"], max(timeout, 60)),
        "mcp": ([*prefix, "mcp", "list", "--json"], timeout),
        "skills": ([*prefix, "skills", "check", "--json"], timeout),
        "hooks": ([*prefix, "hooks", "list", "--json"], timeout),
        "worktrees": ([*prefix, "worktrees", "list", "--json"], timeout),
        "sandbox": ([*prefix, "sandbox", "list", "--json"], timeout),
        "approvals": ([*prefix, "approvals", "get", "--json", "--timeout", "10000"], timeout),
        "cron": ([*prefix, "cron", "list", "--all", "--json", "--timeout", "10000"], timeout),
        "wiki_status": ([*prefix, "wiki", "status", "--json"], timeout),
        "wiki_search": (
            [
                *prefix,
                "wiki",
                "search",
                "Eve Capability Intelligence",
                "--backend",
                "local",
                "--corpus",
                "wiki",
                "--max-results",
                "1",
                "--json",
            ],
            timeout,
        ),
    }
    probe_results: Dict[str, Tuple[Optional[object], Dict[str, object]]] = {}

    def run_probe(key: str) -> Tuple[str, Tuple[Optional[object], Dict[str, object]]]:
        probe_command, probe_timeout = probe_specs[key]
        return key, run_command_json(runner, probe_command, timeout=probe_timeout)

    # These are independent, read-only CLI observations.  Run them in a small
    # pool so an hourly capability review does not become ten serialized
    # gateway startup costs.
    with ThreadPoolExecutor(max_workers=min(4, len(probe_specs))) as executor:
        futures = {executor.submit(run_probe, key): key for key in probe_specs}
        for future in as_completed(futures):
            key = futures[future]
            try:
                _, result = future.result()
            except Exception as exc:
                result = (
                    None,
                    {
                        "command": probe_specs[key][0],
                        "ok": False,
                        "returncode": None,
                        "error": compact_text(exc, 300),
                    },
                )
            probe_results[key] = result

    def probe_payload(key: str) -> object:
        return probe_results.get(key, (None, {}))[0]

    def probe_evidence(key: str) -> Dict[str, object]:
        return probe_results.get(key, (None, {}))[1]

    qmd_version_text, qmd_version_evidence = run_command_text(
        runner, [qmd_command, "--version"], timeout=timeout
    )
    mcporter_version_text, mcporter_version_evidence = run_command_text(
        runner, [mcporter_command, "--version"], timeout=timeout
    )
    current_config: Dict[str, object] = {}
    config_error = ""
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            current_config = loaded
        else:
            config_error = "active config was not an object"
    except (OSError, json.JSONDecodeError) as exc:
        config_error = compact_text(exc, 300)
    mcporter_config: Dict[str, object] = {}
    mcporter_config_error = ""
    if mcporter_config_path is not None:
        try:
            loaded_mcporter = json.loads(mcporter_config_path.read_text(encoding="utf-8"))
            if isinstance(loaded_mcporter, dict):
                mcporter_config = loaded_mcporter
            else:
                mcporter_config_error = "MCPorter config was not an object"
        except (OSError, json.JSONDecodeError) as exc:
            mcporter_config_error = compact_text(exc, 300)
    plugins, plugin_diagnostics = _compact_plugins(plugins_payload)
    schema_catalog = catalog_json_schema(schema if isinstance(schema, dict) else {})
    safe_config = redact_payload(current_config)
    safe_mcporter_config = redact_payload(mcporter_config)
    enabled_plugins = [item for item in plugins if item.get("enabled")]
    memory_status = _compact_openclaw_memory(memory_payload)
    memory_retrieval = _compact_memory_search(memory_search_payload)
    memory_status["retrieval_smoke"] = memory_retrieval
    memory_status["ok"] = bool(memory_status.get("ok") and memory_retrieval.get("ok"))
    openclaw_runtime = _compact_openclaw_runtime(
        probe_payload("status"),
        probe_payload("health"),
        probe_payload("gateway_probe"),
    )
    cron_status = _compact_openclaw_cron(probe_payload("cron"))
    tasks_status = _compact_openclaw_tasks(
        probe_payload("tasks"),
        probe_payload("status"),
        probe_payload("tasks_list"),
        cron_status,
    )
    commitments_status = _compact_openclaw_commitments(probe_payload("commitments"))
    security_status = _compact_openclaw_security(probe_payload("security"))
    mcp_status = _compact_openclaw_mcp(probe_payload("mcp"))
    skills_status = _compact_openclaw_skills(probe_payload("skills"))
    hooks_status = _compact_openclaw_hooks(probe_payload("hooks"))
    isolation_status = _compact_openclaw_isolation(
        probe_payload("worktrees"),
        probe_payload("sandbox"),
    )
    approvals_status = _compact_openclaw_approvals(probe_payload("approvals"))
    wiki_status = _compact_openclaw_wiki(
        probe_payload("wiki_status"),
        probe_payload("wiki_search"),
    )
    context_management_status = _compact_openclaw_context_management(current_config)
    deterministic_audit = deterministic_audit if isinstance(deterministic_audit, dict) else {}
    compact_deterministic_audit = {
        "generated_at": str(deterministic_audit.get("generated_at") or ""),
        "ok": bool(deterministic_audit.get("ok")),
        "status": str(deterministic_audit.get("status") or "missing"),
        "summary": compact_text(deterministic_audit.get("summary"), 260),
        "checks": redact_payload(deterministic_audit.get("checks") or {}),
        "channel_health_issue_count": len(deterministic_audit.get("channel_health_issues") or []),
        "degraded_worker_count": len(deterministic_audit.get("degraded_workers") or []),
        "degraded_routine_count": len(deterministic_audit.get("degraded_routines") or []),
        "bootstrap_ok": bool((deterministic_audit.get("bootstrap") or {}).get("ok"))
        if isinstance(deterministic_audit.get("bootstrap"), dict)
        else False,
    }
    config_valid = bool(isinstance(validate_payload, dict) and validate_payload.get("valid"))
    family_reviews = build_openclaw_feature_family_reviews(
        current_config=current_config,
        config_valid=config_valid,
        memory_status=memory_status,
        plugins=plugins,
        tasks=tasks_status,
        commitments=commitments_status,
        security=security_status,
        mcp=mcp_status,
        skills=skills_status,
        hooks=hooks_status,
        cron=cron_status,
        isolation=isolation_status,
        approvals=approvals_status,
        runtime_status=openclaw_runtime,
        deterministic_audit=compact_deterministic_audit,
        wiki_status=wiki_status,
    )
    feature_ids = sorted(
        {
            *[f"config:{str(item.get('path') or '').split('.', 1)[0]}" for item in schema_catalog],
            *[f"plugin:{item.get('id')}" for item in enabled_plugins if item.get("id")],
            *[f"tool:{tool}" for item in enabled_plugins for tool in item.get("tool_names") or []],
            *[f"channel:{channel}" for item in enabled_plugins for channel in item.get("channel_ids") or []],
        }
    )
    version_match = re.search(r"OpenClaw\s+([^\s]+)", version_text)
    snapshot: Dict[str, object] = {
        "id": "openclaw",
        "role": "body_action_nervous_system",
        "profile": profile,
        "version": version_match.group(1) if version_match else compact_text(version_text, 120),
        "config_path": str(config_path),
        "config_read_ok": not bool(config_error),
        "config_error": config_error,
        "config_valid": config_valid,
        "config_warnings": list(validate_payload.get("warnings") or []) if isinstance(validate_payload, dict) else [],
        "configured_paths": flatten_mapping_paths(safe_config),
        "configured_values": safe_config,
        "configured_values_sha256": stable_json_hash(safe_config),
        "config_schema_catalog": schema_catalog,
        "config_schema_sha256": stable_json_hash(schema_catalog),
        "config_schema_path_count": len(schema_catalog),
        "plugins": plugins,
        "plugin_diagnostics": plugin_diagnostics,
        "enabled_plugin_ids": [str(item.get("id")) for item in enabled_plugins],
        "feature_ids": feature_ids,
        "memory": memory_status,
        "runtime": openclaw_runtime,
        "runtime_surfaces": {
            "runtime": openclaw_runtime,
            "tasks": tasks_status,
            "commitments": commitments_status,
            "security": security_status,
            "mcp": mcp_status,
            "skills": skills_status,
            "hooks": hooks_status,
            "cron": cron_status,
            "isolation": isolation_status,
            "approvals": approvals_status,
            "context_management": context_management_status,
            "memory_wiki": wiki_status,
            "deterministic_audit": compact_deterministic_audit,
        },
        "feature_family_reviews": family_reviews,
        "supporting_tools": {
            "qmd": {
                "version": _semantic_version_from_text(qmd_version_text),
                "available": bool(qmd_version_evidence.get("ok")),
            },
            "mcporter": {
                "version": _semantic_version_from_text(mcporter_version_text),
                "available": bool(mcporter_version_evidence.get("ok")),
                "config_path": str(mcporter_config_path or ""),
                "config_read_ok": mcporter_config_path is None or not bool(mcporter_config_error),
                "config_error": mcporter_config_error,
                "configured_paths": flatten_mapping_paths(safe_mcporter_config),
                "configured_values": safe_mcporter_config,
                "configured_values_sha256": stable_json_hash(safe_mcporter_config),
            },
        },
        "update_dry_run": redact_payload(update_payload or {}),
        "evidence": {
            "version": version_evidence,
            "schema": schema_evidence,
            "plugins": plugins_evidence,
            "validate": validate_evidence,
            "update": update_evidence,
            "memory": memory_evidence,
            "memory_retrieval": memory_search_evidence,
            "qmd_version": qmd_version_evidence,
            "mcporter_version": mcporter_version_evidence,
            **{key: probe_evidence(key) for key in sorted(probe_specs)},
        },
    }
    snapshot["fingerprint"] = stable_json_hash(
        {
            "version": snapshot["version"],
            "config": snapshot["configured_values_sha256"],
            "schema": snapshot["config_schema_sha256"],
            "plugins": plugins,
            "memory": snapshot["memory"],
            "runtime_surfaces": snapshot["runtime_surfaces"],
            "feature_family_reviews": snapshot["feature_family_reviews"],
            "supporting_tools": snapshot["supporting_tools"],
        }
    )
    return snapshot


def _load_yaml_safely(path: Path) -> Tuple[Dict[str, object], str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {}, compact_text(exc, 300)
    try:
        import yaml  # type: ignore
    except Exception:
        # Eve's launchd Python is intentionally lean and may not include
        # PyYAML.  Hermes' profile file uses a simple nested mapping, so retain
        # path/type visibility with a bounded parser rather than declaring the
        # live config unknowable.  Anchors, multiline scalars, and custom YAML
        # tags intentionally remain unsupported.
        root: Dict[str, object] = {}
        stack: List[Tuple[int, Dict[str, object]]] = [(-1, root)]

        def scalar(raw: str) -> object:
            value = raw.strip()
            if not value:
                return {}
            lowered = value.lower()
            if lowered in {"true", "false"}:
                return lowered == "true"
            if lowered in {"null", "none", "~"}:
                return None
            if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                return value[1:-1]
            if value.startswith("[") and value.endswith("]"):
                try:
                    parsed = json.loads(value.replace("'", '"'))
                    return parsed if isinstance(parsed, list) else value
                except json.JSONDecodeError:
                    return [item.strip() for item in value[1:-1].split(",") if item.strip()]
            try:
                return int(value)
            except ValueError:
                try:
                    return float(value)
                except ValueError:
                    return value

        for raw_line in text.splitlines():
            if not raw_line.strip() or raw_line.lstrip().startswith("#") or "\t" in raw_line[: len(raw_line) - len(raw_line.lstrip())]:
                continue
            without_comment = raw_line.split(" #", 1)[0].rstrip()
            if ":" not in without_comment:
                continue
            indent = len(without_comment) - len(without_comment.lstrip(" "))
            key, raw_value = without_comment.strip().split(":", 1)
            key = key.strip().strip('"\'')
            if not key or key.startswith("-"):
                continue
            while len(stack) > 1 and indent <= stack[-1][0]:
                stack.pop()
            parent = stack[-1][1]
            parsed_value = scalar(raw_value)
            parent[key] = parsed_value
            if isinstance(parsed_value, dict):
                stack.append((indent, parsed_value))
        return root, "" if root else "PyYAML unavailable and fallback parser found no mappings"
    try:
        payload = yaml.safe_load(text)
    except Exception as exc:  # PyYAML raises several parser subclasses.
        return {}, compact_text(exc, 300)
    return (payload if isinstance(payload, dict) else {}), ""


def extract_hermes_config_catalog(source_root: Path, configured: object) -> List[Dict[str, object]]:
    """Build a provenance-rich Hermes config catalog without executing Hermes.

    Hermes does not currently expose a JSON schema like OpenClaw.  Its
    ``DEFAULT_CONFIG`` mapping is nevertheless a much stronger source than a
    broad regex over Python prose.  Parse that mapping as an AST, then augment
    it with paths from shipped YAML examples and the active profile.  This
    intentionally excludes arbitrary dotted identifiers such as method names;
    the capability ledger must not inflate its self-knowledge with code tokens
    that are not configuration.
    """

    records: Dict[str, Dict[str, object]] = {}
    dynamic_roots = {"custom_toolsets", "mcp_servers", "model_aliases", "providers"}

    def normalize_path(parts: Sequence[str]) -> str:
        normalized = [str(part) for part in parts if str(part)]
        if len(normalized) > 1 and normalized[0].removesuffix("[]") in dynamic_roots:
            normalized[1] = "*" if normalized[1] != "[]" else normalized[1]
        return ".".join(normalized).replace(".[]", "[]")

    def add_path(parts: Sequence[str], *, source: str, evidence_file: Path) -> None:
        path = normalize_path(parts)
        if not path or len(path) > 180:
            return
        record = records.setdefault(
            path,
            {
                "path": path,
                "sources": set(),
                "evidence_files": set(),
                "authoritative_schema": False,
                "defined_in_default_config": False,
            },
        )
        record["sources"].add(source)
        record["evidence_files"].add(str(evidence_file))
        if source == "hermes_default_config_source":
            record["defined_in_default_config"] = True

    def walk_python(node: ast.AST, prefix: Tuple[str, ...], *, evidence_file: Path) -> None:
        if isinstance(node, ast.Dict):
            for key_node, value_node in zip(node.keys, node.values):
                if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                    continue
                key = key_node.value.strip()
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", key):
                    continue
                next_prefix = (*prefix, key)
                add_path(next_prefix, source="hermes_default_config_source", evidence_file=evidence_file)
                walk_python(value_node, next_prefix, evidence_file=evidence_file)
        elif isinstance(node, (ast.List, ast.Tuple)):
            array_prefix = (*prefix[:-1], f"{prefix[-1]}[]") if prefix else ("[]",)
            add_path(array_prefix, source="hermes_default_config_source", evidence_file=evidence_file)
            for element in node.elts:
                walk_python(element, array_prefix, evidence_file=evidence_file)

    config_source = source_root / "hermes_cli" / "config.py"
    if config_source.is_file():
        try:
            module = ast.parse(
                config_source.read_text(encoding="utf-8", errors="replace"),
                filename=str(config_source),
            )
        except (OSError, SyntaxError):
            module = None
        if module is not None:
            for node in module.body:
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if not any(isinstance(target, ast.Name) and target.id == "DEFAULT_CONFIG" for target in targets):
                    continue
                value_node = node.value
                if value_node is not None:
                    walk_python(value_node, (), evidence_file=config_source)
                break

    doc_candidates = [
        source_root / "website" / "docs" / "user-guide" / "configuration.md",
        source_root / "website" / "docs" / "user-guide" / "configuring-models.md",
        source_root / "website" / "docs" / "reference" / "toolsets-reference.md",
        source_root / "website" / "docs" / "reference" / "mcp-config-reference.md",
    ]
    yaml_fence = re.compile(r"```(?:yaml|yml)\s*\n(.*?)```", re.IGNORECASE | re.DOTALL)
    documented_path = re.compile(
        r"`([a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_*_-]*){1,7})`"
    )
    for candidate in doc_candidates:
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for block in yaml_fence.findall(text):
            stack: List[Tuple[int, str]] = []
            for raw_line in block.splitlines():
                if not raw_line.strip() or raw_line.lstrip().startswith("#"):
                    continue
                line = raw_line.split(" #", 1)[0].rstrip()
                match = re.match(
                    r"^(?P<indent>\s*)(?:-\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)\s*:(?P<value>.*)$",
                    line,
                )
                if not match:
                    continue
                indent = len(match.group("indent"))
                while stack and indent <= stack[-1][0]:
                    stack.pop()
                key = match.group("key")
                parts = tuple([*(item[1] for item in stack), key])
                add_path(parts, source="shipped_yaml_example", evidence_file=candidate)
                raw_value = match.group("value").strip()
                if raw_value.startswith("["):
                    add_path(
                        (*parts[:-1], f"{parts[-1]}[]"),
                        source="shipped_yaml_example",
                        evidence_file=candidate,
                    )
                if not raw_value:
                    stack.append((indent, key))
        for match in documented_path.finditer(text):
            path = match.group(1)
            if path.endswith((".json", ".md", ".py", ".toml", ".yaml", ".yml")):
                continue
            add_path(
                tuple(path.split(".")),
                source="shipped_documented_path",
                evidence_file=candidate,
            )

    configured_paths = set(flatten_mapping_paths(configured))
    configured_evidence = Path("active-hermes-profile-config.yaml")
    for path in configured_paths:
        parts = tuple(part for part in path.replace("[]", ".[]").split(".") if part)
        add_path(parts, source="configured", evidence_file=configured_evidence)

    catalog: List[Dict[str, object]] = []
    for path in sorted(records):
        raw = records[path]
        sources = sorted(raw["sources"])
        evidence_files = sorted(raw["evidence_files"])
        catalog.append(
            {
                "path": path,
                "source": "configured" if "configured" in sources else sources[0],
                "sources": sources,
                "authoritative_schema": False,
                "defined_in_default_config": bool(raw["defined_in_default_config"]),
                "evidence_files": evidence_files[:8],
            }
        )
    return catalog


def collect_hermes_snapshot(
    *,
    profile_home: Path,
    source_root: Path,
    inventory: Optional[Dict[str, object]] = None,
    feature_policy: Optional[Dict[str, object]] = None,
    latest_run: Optional[Dict[str, object]] = None,
    command: str = "hermes",
    timeout: int = 15,
    runner: CommandRunner = default_command_runner,
) -> Dict[str, object]:
    version_text, version_evidence = run_command_text(runner, [command, "--version"], timeout=timeout)
    config_path = profile_home / "config.yaml"
    current_config, config_error = _load_yaml_safely(config_path)
    safe_config = redact_payload(current_config)
    catalog = extract_hermes_config_catalog(source_root, safe_config)
    inventory = inventory if isinstance(inventory, dict) else {}
    feature_policy = feature_policy if isinstance(feature_policy, dict) else {}
    status = inventory.get("hermes_status") if isinstance(inventory.get("hermes_status"), dict) else {}
    families = inventory.get("capability_families") if isinstance(inventory.get("capability_families"), list) else []
    features = feature_policy.get("features") if isinstance(feature_policy.get("features"), list) else []
    family_ids = [str(item.get("id")) for item in families if isinstance(item, dict) and item.get("id")]
    feature_ids = [str(item.get("id")) for item in features if isinstance(item, dict) and item.get("id")]
    latest_run = latest_run if isinstance(latest_run, dict) else {}
    latest_run_summary = {
        "id": str(latest_run.get("id") or ""),
        "created_at": str(latest_run.get("created_at") or ""),
        "updated_at": str(latest_run.get("updated_at") or ""),
        "status": str(latest_run.get("status") or ""),
        "strict_json_ok": bool(latest_run.get("strict_json_ok")),
        "json_repair_used": bool(latest_run.get("json_repair_used")),
        "local_64k_lab_requested": bool(latest_run.get("local_64k_lab_requested")),
        "stored_governance_proposals": bool(latest_run.get("stored_governance_proposals")),
        "artifact_path": str(latest_run.get("artifact_path") or ""),
    }
    version_match = re.search(r"Hermes Agent v([^\s]+)", version_text)
    snapshot: Dict[str, object] = {
        "id": "hermes",
        "role": "proposal_only_learning_organ",
        "version": version_match.group(1) if version_match else compact_text(version_text, 120),
        "source_head": str(status.get("source_head") or status.get("install_head") or ""),
        "source_root": str(source_root),
        "profile_home": str(profile_home),
        "config_path": str(config_path),
        "config_read_ok": not bool(config_error),
        "config_error": config_error,
        "configured_paths": flatten_mapping_paths(safe_config),
        "configured_values": safe_config,
        "configured_values_sha256": stable_json_hash(safe_config),
        "config_catalog": catalog,
        "config_catalog_sha256": stable_json_hash(catalog),
        "config_path_count": len(catalog),
        "inventory_generated_at": inventory.get("generated_at"),
        "inventory_status": str(status.get("status") or "unknown"),
        "default_profile_ready_for_serious_learning": bool(inventory.get("default_profile_ready_for_serious_learning")),
        "serious_learning_route": str(inventory.get("serious_learning_route") or ""),
        "capability_families": [redact_payload(item) for item in families if isinstance(item, dict)],
        "feature_policy_status": str(feature_policy.get("status") or "unknown"),
        "feature_policy_summary": redact_payload(feature_policy.get("summary") or {}),
        "feature_policy": [redact_payload(item) for item in features if isinstance(item, dict)],
        "feature_ids": sorted(set([*family_ids, *feature_ids])),
        # Never copy a run's prompt, trace, proposal bodies, or hidden evaluator
        # material into this broadly consulted ledger.
        "latest_run": latest_run_summary,
        "direct_state_write_allowed": False,
        "canonical_memory_authority": False,
        "adds_chat_lane": False,
        "evidence": {"version": version_evidence},
    }
    snapshot["fingerprint"] = stable_json_hash(
        {
            "version": snapshot["version"],
            "source_head": snapshot["source_head"],
            "config": snapshot["configured_values_sha256"],
            "catalog": snapshot["config_catalog_sha256"],
            "families": snapshot["capability_families"],
            "policy": snapshot["feature_policy"],
        }
    )
    return snapshot


def collect_eve_snapshot(
    *,
    root: Path,
    config: Dict[str, object],
    organ_report: Optional[Dict[str, object]] = None,
    component_state: Optional[Dict[str, object]] = None,
    radar_state: Optional[Dict[str, object]] = None,
    oss_status: Optional[Dict[str, object]] = None,
    default_config: Optional[Dict[str, object]] = None,
    persisted_config: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    safe_config = redact_payload(config)
    organ_report = organ_report if isinstance(organ_report, dict) else {}
    component_state = component_state if isinstance(component_state, dict) else {}
    radar_state = radar_state if isinstance(radar_state, dict) else {}
    oss_status = oss_status if isinstance(oss_status, dict) else {}
    default_config = default_config if isinstance(default_config, dict) else {}
    persisted_config = persisted_config if isinstance(persisted_config, dict) else {}
    organs: List[Dict[str, object]] = []
    for item in organ_report.get("organs") or []:
        if not isinstance(item, dict):
            continue
        organs.append(
            {
                "id": str(item.get("id") or ""),
                "label": str(item.get("label") or ""),
                "status": str(item.get("status") or ""),
                "operational_status": str(item.get("operational_status") or ""),
                "purpose": compact_text(item.get("purpose"), 260),
                "summary": compact_text(item.get("summary"), 300),
                "authority_boundary": compact_text(item.get("authority_boundary"), 300),
                "evidence": [compact_text(value, 260) for value in item.get("evidence") or []][:12],
            }
        )
    components: List[Dict[str, object]] = []
    for item in component_state.get("components") or []:
        if not isinstance(item, dict):
            continue
        components.append(
            {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or ""),
                "kind": str(item.get("kind") or ""),
                "repository": str(item.get("repository") or ""),
                "release_repository": str(item.get("release_repository") or ""),
                "release_feature_mode": str(item.get("release_feature_mode") or "installed_version"),
                "local_version": str(item.get("local_version") or ""),
                "latest_version": str(item.get("latest_version") or ""),
                "update_available": bool(item.get("update_available")),
                "remote_head": str(item.get("remote_head") or ""),
                "mirror_head": str(item.get("mirror_head") or ""),
                "status": str(item.get("status") or ""),
                "blocked_latest_version": str(item.get("blocked_latest_version") or ""),
                "blocked_version_reason": compact_text(item.get("blocked_version_reason"), 360),
                "adoption": compact_text(item.get("adoption"), 300),
                "errors": [compact_text(value, 220) for value in item.get("errors") or []],
            }
        )
    radar_surfaces = [
        str(item.get("id"))
        for item in radar_state.get("openclaw_discovered_surfaces") or []
        if isinstance(item, dict) and item.get("id")
    ]
    oss_inventory = oss_status.get("inventory") if isinstance(oss_status.get("inventory"), dict) else {}
    oss_tools: List[Dict[str, object]] = []
    for item in oss_inventory.get("tools") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        oss_tools.append(
            {
                "id": str(item.get("id")),
                "layer": str(item.get("layer") or ""),
                "admission": str(item.get("admission") or ""),
                "purpose": compact_text(item.get("purpose"), 360),
                "installed": bool(item.get("installed")),
                "importable": bool(item.get("importable")),
                "version": str(item.get("version") or ""),
                "live_authority": bool(item.get("live_authority")),
            }
        )
    oss_substrates = {
        "generated_at": str(oss_status.get("generated_at") or ""),
        "status": str(oss_status.get("status") or "unknown"),
        "inventory_status": str(oss_status.get("inventory_status") or "unknown"),
        "service_status": redact_payload(oss_status.get("service_status") or {}),
        "readiness": redact_payload(oss_status.get("readiness") or {}),
        "trace_status": str(oss_status.get("trace_status") or "unknown"),
        "training_dataset_status": str(oss_status.get("training_dataset_status") or "unknown"),
        "dvc_manifest_status": str(oss_status.get("dvc_manifest_status") or "unknown"),
        "workflow_status": str(oss_status.get("workflow_status") or "unknown"),
        "pressure_eval_status": str(oss_status.get("pressure_eval_status") or "unknown"),
        "copilotkit_status": str(oss_status.get("copilotkit_status") or "unknown"),
        "copilotkit_exposure_status": str(oss_status.get("copilotkit_exposure_status") or "unknown"),
        "deepeval_agent_metrics": redact_payload(oss_status.get("deepeval_agent_metrics") or {}),
        "tools": oss_tools,
        "grants_live_authority": bool(oss_status.get("grants_live_authority")),
    }
    git_head = ""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True,
            capture_output=True,
            timeout=5,
        )
        if completed.returncode == 0:
            git_head = completed.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        git_head = ""
    persisted_extra_keys = sorted(set(persisted_config) - set(default_config)) if default_config else []
    consumer_candidates = [
        root / "eve.py",
        root / "eve_model_topology.py",
        root / "bin" / "eve_model_watchdog.py",
        root / "bin" / "start_llama_cpp_server.sh",
    ]
    candidate_text: Dict[str, str] = {}
    for path in consumer_candidates:
        try:
            candidate_text[str(path)] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    persisted_extra_consumers: Dict[str, List[str]] = {}
    for key in persisted_extra_keys:
        consumers = [path for path, text in candidate_text.items() if key in text]
        if key.startswith("model_watchdog_"):
            watchdog = str(root / "bin" / "eve_model_watchdog.py")
            if watchdog in candidate_text and watchdog not in consumers:
                consumers.append(watchdog)
        if re.fullmatch(r"(?:fast|deep|observer|planner|relationship)_llama_cpp_(?:chat_template_kwargs|reasoning)", key):
            launcher = str(root / "bin" / "start_llama_cpp_server.sh")
            if launcher in candidate_text and launcher not in consumers:
                consumers.append(launcher)
        persisted_extra_consumers[key] = sorted(consumers)
    dead_persisted_extra_keys = [key for key, consumers in persisted_extra_consumers.items() if not consumers]
    config_provenance = {
        "default_key_count": len(default_config),
        "persisted_key_count": len(persisted_config),
        "merged_key_count": len(config),
        "persisted_override_count": len(
            [
                key
                for key, value in persisted_config.items()
                if key in default_config and value != default_config.get(key)
            ]
        ),
        "persisted_extra_key_count": len(persisted_extra_keys),
        "persisted_extra_keys": persisted_extra_keys,
        "persisted_extra_consumers": persisted_extra_consumers,
        "dead_persisted_extra_keys": dead_persisted_extra_keys,
        "consumer_scan_paths": sorted(candidate_text),
        "note": "Dead-key classification is limited to persisted keys outside Eve's declared defaults; dynamic model/watchdog families are mapped explicitly.",
    }
    snapshot: Dict[str, object] = {
        "id": "eve",
        "role": "continuity_identity_control_layer",
        "source_root": str(root),
        "git_head": git_head,
        "configured_paths": flatten_mapping_paths(safe_config),
        "configured_values": safe_config,
        "configured_values_sha256": stable_json_hash(safe_config),
        "config_provenance": config_provenance,
        "config_catalog": [
            {
                "path": str(key),
                "default_type": type(value).__name__,
                "sensitive": sensitive_key(key),
            }
            for key, value in sorted(config.items())
        ],
        "organs": organs,
        "components": components,
        "oss_substrates": oss_substrates,
        # Registered/admitted organs are installed Eve features.  Source-radar
        # surfaces are research observations and must never masquerade as
        # installed capabilities when a mirror scan changes shape.
        "feature_ids": sorted({str(item.get("id")) for item in organs if item.get("id")}),
        "research_feature_ids": sorted(set(radar_surfaces)),
        "component_checked_at": component_state.get("updated_at"),
        "radar_checked_at": radar_state.get("updated_at"),
    }
    snapshot["fingerprint"] = stable_json_hash(
        {
            "git_head": git_head,
            "config": snapshot["configured_values_sha256"],
            "organs": organs,
            "components": components,
            "oss_substrates": oss_substrates,
            "features": snapshot["feature_ids"],
            "research_features": snapshot["research_feature_ids"],
            "config_provenance": config_provenance,
        }
    )
    return snapshot


def default_json_fetcher(url: str, timeout: int) -> Dict[str, object]:
    req = request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "EveCapabilityIntelligence/1.0"},
    )
    try:
        with request.urlopen(req, timeout=max(1, int(timeout))) as response:
            raw = response.read(3_000_000)
    except error.HTTPError as exc:
        return {"ok": False, "error": f"HTTP {exc.code}: {compact_text(exc.reason, 180)}"}
    except (error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "error": compact_text(exc, 260)}
    try:
        return {"ok": True, "payload": json.loads(raw.decode("utf-8"))}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"invalid JSON: {compact_text(exc, 220)}"}


def github_release_feed(
    repository: str,
    *,
    timeout: int = 20,
    limit: int = 5,
    fetcher: JsonFetcher = default_json_fetcher,
) -> Dict[str, object]:
    repository = str(repository or "").strip().strip("/")
    url = f"https://api.github.com/repos/{repository}/releases?per_page={max(1, min(10, limit))}"
    fetched = fetcher(url, timeout)
    if not fetched.get("ok"):
        return {"repository": repository, "url": url, "ok": False, "error": fetched.get("error") or "release lookup failed", "releases": []}
    payload = fetched.get("payload")
    releases: List[Dict[str, object]] = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict) or item.get("draft"):
            continue
        body = str(item.get("body") or "")
        bullets = []
        for line in body.splitlines():
            cleaned = re.sub(r"^[\s*#>-]+", "", line).strip()
            if cleaned and len(cleaned) >= 8:
                bullets.append(compact_text(cleaned, 240))
            if len(bullets) >= 8:
                break
        releases.append(
            {
                "tag": str(item.get("tag_name") or ""),
                "name": compact_text(item.get("name"), 180),
                "published_at": str(item.get("published_at") or item.get("created_at") or ""),
                "prerelease": bool(item.get("prerelease")),
                "url": str(item.get("html_url") or ""),
                "notes_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "feature_bullets": bullets,
            }
        )
        if len(releases) >= limit:
            break
    return {"repository": repository, "url": url, "ok": True, "releases": releases, "feed_sha256": stable_json_hash(releases)}


def collect_release_feeds(
    repositories: Iterable[str],
    *,
    timeout: int = 20,
    fetcher: JsonFetcher = default_json_fetcher,
) -> List[Dict[str, object]]:
    return [github_release_feed(repo, timeout=timeout, fetcher=fetcher) for repo in repositories if str(repo).strip()]


def _by_id(items: object) -> Dict[str, Dict[str, object]]:
    values = items if isinstance(items, list) else []
    return {
        str(item.get("id")): item
        for item in values
        if isinstance(item, dict) and item.get("id")
    }


def _paths_for_subsystem(subsystem: Dict[str, object]) -> set[str]:
    catalog = subsystem.get("config_schema_catalog") or subsystem.get("config_catalog") or []
    return {
        str(item.get("path"))
        for item in catalog
        if isinstance(item, dict) and item.get("path")
    }


def _release_review_id(repository: object, tag: object) -> str:
    raw = f"{repository}@{tag}".strip().lower()
    slug = re.sub(r"[^a-z0-9._@+-]+", "-", raw).strip("-")
    return f"release:{slug or 'unknown'}"


def _normalized_version_candidates(value: object) -> List[str]:
    text = str(value or "").strip().lower()
    if not text:
        return []
    candidates = [text, text.lstrip("v")]
    candidates.extend(
        match.group(1).lower().lstrip("v")
        for match in re.finditer(r"\bv?([0-9]+(?:\.[0-9]+){1,3}(?:[-+][a-z0-9._-]+)?)\b", text)
    )
    # llama.cpp and similar build identifiers are often expressed as bNNNNN.
    candidates.extend(match.group(1).lower() for match in re.finditer(r"\b(b[0-9]{3,})\b", text))
    # Some package managers append a numeric packaging revision to an upstream
    # semantic version (for example OpenClaw 2026.7.1-2).  Treat that package as
    # containing upstream release 2026.7.1 without conflating true prereleases
    # such as 2026.7.2-beta.3 with their eventual stable release.
    for candidate in list(candidates):
        package_revision = re.fullmatch(r"([0-9]+(?:\.[0-9]+){2,3})-[0-9]+", candidate)
        if package_revision:
            candidates.append(package_revision.group(1))
    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


def release_mentions_installed_version(release: Dict[str, object], installed_version: object) -> bool:
    candidates = _normalized_version_candidates(installed_version)
    if not candidates:
        return False
    haystack = " ".join(
        [
            str(release.get("tag") or ""),
            str(release.get("name") or ""),
            *[str(value) for value in (release.get("feature_bullets") or [])[:4]],
        ]
    ).lower()
    normalized_haystack = haystack.replace("_", "-")
    return any(
        re.search(rf"(?<![a-z0-9])v?{re.escape(candidate)}(?![a-z0-9])", normalized_haystack)
        for candidate in candidates
        if len(candidate) >= 3
    )


def _release_feature_summary(release: Dict[str, object]) -> str:
    tag = str(release.get("tag") or "").strip().lower().lstrip("v")
    generic = {
        "bugfixes",
        "bug fix",
        "changelog",
        "features",
        "highlights",
        "improvement",
        "new feature",
        "smaller things",
        "tooling / dependencies",
        "updating",
        "what's in this patch",
        "what's changed",
        "what's new",
    }
    candidates: List[tuple[int, int, str]] = []
    for index, value in enumerate(release.get("feature_bullets") or []):
        text = compact_text(value, 280)
        lowered = text.lower().strip("* :")
        heading = re.sub(r"[^a-z0-9' ]+", "", lowered).strip()
        if not text or lowered in generic or heading in generic or lowered.lstrip("v") == tag:
            continue
        if lowered.startswith(("<details", "</details", "<summary", "</summary")):
            continue
        if lowered.startswith("new to ") and "get started" in lowered:
            continue
        if re.fullmatch(r"v?[0-9]+(?:\.[0-9]+){1,3}(?:[-+][a-z0-9._-]+)?", lowered):
            continue
        if re.fullmatch(r"changes since\s+v?[0-9]+(?:\.[0-9]+){1,3}", lowered):
            continue
        if re.fullmatch(r"\[![a-z]+\]", lowered):
            continue
        if re.fullmatch(r"(?:release date)?\s*:?\s*[a-z]+\s+[0-9]{1,2},?\s+[0-9]{4}", lowered):
            continue
        score = 0
        if re.search(r"\b(?:feat(?:ure)?|add(?:ed)?|introduc(?:e|ed)|support)\b", lowered):
            score += 4
        if re.search(r"\b(?:fix(?:ed)?|improv(?:e|ed|ement)|prevent|preserve)\b", lowered):
            score += 2
        if lowered.startswith(("chore", "build", "ci", "docs")) or "dependabot" in lowered:
            score -= 4
        candidates.append((score, -index, text))
    if candidates:
        return max(candidates)[2]
    return compact_text(release.get("name") or release.get("tag") or "Release notes recorded.", 280)


def _component_release_repository(component: Dict[str, object]) -> str:
    configured = str(component.get("release_repository") or "").strip().strip("/")
    if configured:
        return configured.lower()
    repository = str(component.get("repository") or "").strip().rstrip("/")
    match = re.search(r"github\.com[/:]([^/]+/[^/#]+?)(?:\.git)?$", repository, flags=re.IGNORECASE)
    return match.group(1).lower() if match else ""


def _component_for_release(
    repository: object,
    components: Sequence[Dict[str, object]],
) -> Dict[str, object]:
    normalized = str(repository or "").strip().strip("/").lower()
    for component in components:
        if _component_release_repository(component) == normalized:
            return component
    return {}


def build_feature_reviews(
    subsystems: Dict[str, object],
    release_feeds: Sequence[Dict[str, object]],
    *,
    previous: Optional[Dict[str, object]] = None,
    checked_at: Optional[str] = None,
) -> List[Dict[str, object]]:
    """Build a durable, evidence-bound release/adoption review ledger.

    A GitHub release is not automatically an installed Eve capability.  Each
    current release head is classified against the component watcher and its
    configured adoption mode.  Older releases remain historical evidence, and
    prior records are retained after they roll out of the bounded feed window.
    """

    checked_at = str(checked_at or utc_now())
    previous = previous if isinstance(previous, dict) else {}
    previous_reviews = {
        str(item.get("id")): item
        for item in previous.get("feature_reviews") or []
        if isinstance(item, dict) and item.get("id")
    }
    eve_state = subsystems.get("eve") if isinstance(subsystems.get("eve"), dict) else {}
    components = [item for item in eve_state.get("components") or [] if isinstance(item, dict)]
    current: List[Dict[str, object]] = []
    visible_ids: set[str] = set()
    for feed in release_feeds:
        if not isinstance(feed, dict) or not feed.get("repository"):
            continue
        repository = str(feed.get("repository") or "").strip()
        releases = [item for item in feed.get("releases") or [] if isinstance(item, dict)]
        stable_head_index = next((index for index, item in enumerate(releases) if not item.get("prerelease")), None)
        component = _component_for_release(repository, components)
        component_id = str(component.get("id") or "")
        installed_version = str(component.get("local_version") or "").strip()
        latest_version = str(component.get("latest_version") or "").strip()
        blocked_version = str(component.get("blocked_latest_version") or "").strip()
        release_mode = str(component.get("release_feature_mode") or "installed_version").strip().lower()
        for index, release in enumerate(releases):
            tag = str(release.get("tag") or "").strip()
            if not tag:
                continue
            review_id = _release_review_id(repository, tag)
            visible_ids.add(review_id)
            is_review_head = index == 0 or index == stable_head_index
            installed_match = release_mentions_installed_version(release, installed_version)
            blocked_match = release_mentions_installed_version(release, blocked_version)
            if not is_review_head and not installed_match:
                state = "historical"
                priority = "info"
                reason = "Older release retained for change history; it is not the current adoption head."
            elif release.get("prerelease"):
                state = "research_only"
                priority = "low"
                reason = "Prerelease notes are tracked, but prerelease availability is not an installed Eve capability."
            elif release_mode == "research_only":
                state = "research_only"
                priority = "low"
                reason = "This repository is an upstream research source; its release tags are not authoritative installed-package evidence."
            elif blocked_match:
                state = "blocked"
                priority = "low"
                reason = str(component.get("blocked_version_reason") or "The corresponding version was rejected by prior canary evidence.")
            elif installed_match:
                state = "in_use"
                priority = "info"
                reason = "The release identifies the version currently observed by Eve's installed-component watcher."
            elif installed_version and release_mode == "lab_only":
                state = "lab_candidate"
                priority = "low"
                reason = "A newer stable lab-substrate release is visible; it needs an isolated evidence canary before adoption."
            elif installed_version:
                state = "candidate"
                priority = "medium"
                reason = "A newer or differently tagged stable release is visible for an installed component."
            else:
                state = "research_only"
                priority = "low"
                reason = "No installed component version is mapped to this release feed."
            prior = previous_reviews.get(review_id) or {}
            review = {
                "id": review_id,
                "repository": repository,
                "component_id": component_id,
                "component_name": str(component.get("name") or repository),
                "target_version": tag,
                "installed_version": installed_version,
                "watcher_latest_version": latest_version,
                "published_at": str(release.get("published_at") or ""),
                "url": str(release.get("url") or ""),
                "prerelease": bool(release.get("prerelease")),
                "state": state,
                "priority": priority,
                "classification_reason": compact_text(reason, 420),
                "feature_summary": _release_feature_summary(release),
                "feature_bullets": [compact_text(value, 280) for value in (release.get("feature_bullets") or [])[:8]],
                "required_gate": compact_text(
                    component.get("adoption") or "Inspect the release delta and run a component-specific canary before adoption.",
                    500,
                ),
                "release_feature_mode": release_mode,
                "visible_in_current_feed": True,
                "first_seen_at": str(prior.get("first_seen_at") or checked_at),
                "last_seen_at": checked_at,
                "last_checked_at": checked_at,
                "authority": "proposal_only",
            }
            review["fingerprint"] = stable_json_hash(
                {
                    key: review.get(key)
                    for key in (
                        "repository",
                        "component_id",
                        "target_version",
                        "installed_version",
                        "watcher_latest_version",
                        "prerelease",
                        "state",
                        "classification_reason",
                        "feature_bullets",
                        "required_gate",
                        "release_feature_mode",
                    )
                }
            )
            current.append(review)
    for review_id, prior in previous_reviews.items():
        if review_id in visible_ids:
            continue
        retained = dict(prior)
        retained["visible_in_current_feed"] = False
        retained["last_checked_at"] = checked_at
        current.append(retained)
    current.sort(
        key=lambda item: (
            bool(item.get("visible_in_current_feed")),
            str(item.get("published_at") or item.get("last_seen_at") or ""),
        ),
        reverse=True,
    )
    return current[:FEATURE_REVIEW_LIMIT]


def summarize_feature_reviews(reviews: Sequence[Dict[str, object]]) -> Dict[str, object]:
    states: Dict[str, int] = {}
    visible = [item for item in reviews if isinstance(item, dict) and item.get("visible_in_current_feed")]
    for item in visible:
        state = str(item.get("state") or "unknown")
        states[state] = states.get(state, 0) + 1
    candidate_states = {"candidate", "lab_candidate"}
    return {
        "review_count": len([item for item in reviews if isinstance(item, dict)]),
        "visible_review_count": len(visible),
        "state_counts": states,
        "candidate_count": sum(states.get(state, 0) for state in candidate_states),
        "in_use_count": states.get("in_use", 0),
        "research_only_count": states.get("research_only", 0),
        "blocked_count": states.get("blocked", 0),
        "candidate_ids": [
            str(item.get("id"))
            for item in visible
            if str(item.get("state") or "") in candidate_states and item.get("id")
        ][:40],
    }


def build_configuration_reviews(
    subsystems: Dict[str, object],
    opportunities: Sequence[Dict[str, object]],
) -> List[Dict[str, object]]:
    attention_by_subsystem: Dict[str, List[str]] = {}
    for item in opportunities:
        if not isinstance(item, dict) or item.get("status") not in {"actionable", "candidate"}:
            continue
        subsystem = str(item.get("subsystem") or "eve")
        attention_by_subsystem.setdefault(subsystem, []).append(str(item.get("id") or ""))
    reviews: List[Dict[str, object]] = []
    for subsystem_id in ("eve", "openclaw", "hermes"):
        subsystem = subsystems.get(subsystem_id) if isinstance(subsystems.get(subsystem_id), dict) else {}
        known_count = int(
            subsystem.get("config_schema_path_count")
            or subsystem.get("config_path_count")
            or len(subsystem.get("config_catalog") or [])
        )
        configured_count = len(subsystem.get("configured_paths") or [])
        # Configured paths may include nested/list leaves while a provider's
        # schema catalog exposes only named parent settings.  Never display the
        # nonsensical posture "371 configured out of 367 known"; the larger
        # observed surface is itself a lower bound on known paths.
        known_count = max(known_count, configured_count)
        attention_ids = attention_by_subsystem.get(subsystem_id, [])
        if subsystem_id == "openclaw":
            memory = subsystem.get("memory") if isinstance(subsystem.get("memory"), dict) else {}
            runtime = subsystem.get("runtime") if isinstance(subsystem.get("runtime"), dict) else {}
            healthy = bool(
                subsystem.get("config_valid")
                and memory.get("ok")
                and runtime.get("ok")
                and not subsystem.get("plugin_diagnostics")
            )
            posture = "optimized_for_current_contracts" if healthy and not attention_ids else "attention"
            evidence = [
                f"config_valid={bool(subsystem.get('config_valid'))}",
                f"memory_ok={bool(memory.get('ok'))}",
                f"runtime_ok={bool(runtime.get('ok'))}",
                f"enabled_plugins={len(subsystem.get('enabled_plugin_ids') or [])}",
            ]
        elif subsystem_id == "hermes":
            latest_run = subsystem.get("latest_run") if isinstance(subsystem.get("latest_run"), dict) else {}
            strict_route = bool(
                latest_run.get("local_64k_lab_requested")
                and latest_run.get("strict_json_ok")
                and not latest_run.get("json_repair_used")
            )
            posture = "governed_for_current_contracts" if strict_route and not attention_ids else "attention"
            evidence = [
                f"feature_policy_status={subsystem.get('feature_policy_status') or 'unknown'}",
                f"strict_local_64k={strict_route}",
                f"direct_eve_authority={bool(subsystem.get('direct_state_write_allowed'))}",
            ]
        else:
            posture = "tracked" if not attention_ids else "attention"
            evidence = [
                f"registered_organs={len(subsystem.get('organs') or [])}",
                f"tracked_components={len(subsystem.get('components') or [])}",
            ]
        reviews.append(
            {
                "subsystem": subsystem_id,
                "posture": posture,
                "known_path_count": known_count,
                "configured_path_count": configured_count,
                "installed_feature_count": len(subsystem.get("feature_ids") or []),
                "attention_ids": attention_ids[:20],
                "evidence": evidence,
                "optimization_rule": (
                    "Enable or change only settings tied to an Eve-owned contract and a verified consequence; "
                    "an unset optional schema path is not itself a capability gap."
                ),
            }
        )
    return reviews


def build_effective_configuration_attestations(
    subsystems: Dict[str, object],
) -> List[Dict[str, object]]:
    """Bind important configuration to a live consumer and consequence.

    The feature-family ledger answers whether Eve *should* use a shipped
    feature.  These contracts answer a stricter question: did the configured
    value reach the process or organ that consumes it, and is there current
    evidence of the intended consequence?  This intentionally covers owned
    runtime contracts rather than pretending every optional schema leaf has a
    meaningful live consequence.
    """

    attestations: List[Dict[str, object]] = []

    def add(
        attestation_id: str,
        *,
        subsystem: str,
        feature_family: str,
        configured_source: str,
        configured_paths: Sequence[str],
        consumer: Dict[str, object],
        runtime: Dict[str, object],
        consequence: Dict[str, object],
        status: str,
        authority_owner: str,
        data_boundary: str,
        rollback: str,
        blockers: Sequence[str] = (),
    ) -> None:
        attestations.append(
            {
                "id": attestation_id,
                "subsystem": subsystem,
                "feature_family": feature_family,
                "configured_source": configured_source,
                "configured_paths": [str(value) for value in configured_paths],
                "consumer": redact_payload(consumer),
                "runtime": redact_payload(runtime),
                "consequence": redact_payload(consequence),
                "status": status,
                "authority_owner": authority_owner,
                "data_boundary": data_boundary,
                "rollback": rollback,
                "blockers": [compact_text(value, 260) for value in blockers if str(value).strip()],
            }
        )

    eve = subsystems.get("eve") if isinstance(subsystems.get("eve"), dict) else {}
    provenance = eve.get("config_provenance") if isinstance(eve.get("config_provenance"), dict) else {}
    dead_extra_keys = [str(value) for value in provenance.get("dead_persisted_extra_keys") or []]
    extra_consumers = provenance.get("persisted_extra_consumers") if isinstance(provenance.get("persisted_extra_consumers"), dict) else {}
    add(
        "eve:persisted_config_consumers",
        subsystem="eve",
        feature_family="configuration_runtime_consumers",
        configured_source=".eve/config.json",
        configured_paths=[str(value) for value in provenance.get("persisted_extra_keys") or []],
        consumer={
            "kind": "source_consumer_index",
            "mapped_consumers": extra_consumers,
            "scan_paths": provenance.get("consumer_scan_paths") or [],
        },
        runtime={
            "default_key_count": int(provenance.get("default_key_count") or 0),
            "persisted_key_count": int(provenance.get("persisted_key_count") or 0),
            "merged_key_count": int(provenance.get("merged_key_count") or 0),
        },
        consequence={
            "verified": not dead_extra_keys,
            "dead_persisted_extra_keys": dead_extra_keys,
            "mapped_extra_key_count": len([value for value in extra_consumers.values() if value]),
        },
        status="degraded" if dead_extra_keys else "effective",
        authority_owner="Eve configuration repository and its named runtime consumers",
        data_boundary="Configuration values may tune Eve processes; they do not become memory or evidence by themselves.",
        rollback="Remove a dead persisted override or restore the previous config snapshot; do not delete declared defaults from a regex-only scan.",
        blockers=[f"dead persisted config key: {value}" for value in dead_extra_keys],
    )

    for organ in eve.get("organs") or []:
        if not isinstance(organ, dict) or not organ.get("id"):
            continue
        organ_id = str(organ.get("id"))
        state = str(organ.get("operational_status") or organ.get("status") or "unknown").lower()
        reported_state = str(organ.get("status") or state)
        if organ_id == "beads_work_graph_substrate" and reported_state == "staged_live":
            effective_status = "staged_unbridged"
        elif reported_state == "lab_verified" or state == "lab_verified":
            effective_status = "lab_verified"
        elif state in {"ready", "healthy", "live", "operational", "verified", "available"}:
            effective_status = "effective"
        elif state in {"lab_ready", "lab_available", "lab_only", "candidate", "configured_lab_candidate"}:
            effective_status = "configured_unverified"
        elif state in {"disabled", "dormant", "not_configured", "research_candidate"}:
            effective_status = "dormant"
        else:
            effective_status = "degraded"
        add(
            f"eve:organ:{organ_id}",
            subsystem="eve",
            feature_family=f"organ:{organ_id}",
            configured_source="Eve organ registry and specialist detector",
            configured_paths=[],
            consumer={"kind": "organ_assimilation", "owner": organ_id},
            runtime={
                "reported_status": reported_state,
                "operational_status": str(organ.get("operational_status") or ""),
            },
            consequence={
                "summary": compact_text(organ.get("summary"), 320),
                "evidence": [compact_text(value, 260) for value in organ.get("evidence") or []][:16],
            },
            status=effective_status,
            authority_owner="Eve executive scheduler and the named organ contract",
            data_boundary=compact_text(organ.get("authority_boundary"), 420),
            rollback="Remove the organ from recurrence or return it to lab-only use without changing Eve identity or canonical memory.",
        )

    openclaw = subsystems.get("openclaw") if isinstance(subsystems.get("openclaw"), dict) else {}
    openclaw_runtime = openclaw.get("runtime") if isinstance(openclaw.get("runtime"), dict) else {}
    runtime_surfaces = openclaw.get("runtime_surfaces") if isinstance(openclaw.get("runtime_surfaces"), dict) else {}
    openclaw_review_by_family = {
        str(item.get("family")): item
        for item in openclaw.get("feature_family_reviews") or []
        if isinstance(item, dict) and item.get("family")
    }
    gateway_service = openclaw_runtime.get("service") if isinstance(openclaw_runtime.get("service"), dict) else {}
    gateway_probe = openclaw_runtime.get("probe") if isinstance(openclaw_runtime.get("probe"), dict) else {}
    add(
        "openclaw:gateway_runtime",
        subsystem="openclaw",
        feature_family="gateway",
        configured_source=str(openclaw.get("config_path") or "openclaw profile config"),
        configured_paths=["gateway.mode", "gateway.bind", "gateway.port", "gateway.auth.mode"],
        consumer={
            "kind": "launch_service_and_gateway_rpc",
            "service_id": gateway_service.get("id") or "",
            "pid": gateway_service.get("pid"),
        },
        runtime={"service": gateway_service, "gateway": openclaw_runtime.get("gateway") or {}},
        consequence={"verified": bool(openclaw_runtime.get("ok")), "probe": gateway_probe},
        status="effective" if openclaw.get("config_valid") and openclaw_runtime.get("ok") else "degraded",
        authority_owner="OpenClaw Eve profile as Eve's body/action nervous system",
        data_boundary="Loopback RPC may execute admitted body actions; it does not own Eve identity or canonical memory.",
        rollback="Unload only the Eve-owned OpenClaw service or restore the prior profile config; do not alter an unrelated user gateway.",
        blockers=[] if openclaw_runtime.get("ok") else ["Eve-owned gateway config/service/health/RPC proof did not all pass"],
    )
    context_management = (
        runtime_surfaces.get("context_management")
        if isinstance(runtime_surfaces.get("context_management"), dict)
        else {}
    )
    context_management_ok = bool(
        openclaw.get("config_valid")
        and openclaw_runtime.get("ok")
        and context_management.get("configured_ok")
    )
    add(
        "openclaw:context_management",
        subsystem="openclaw",
        feature_family="context_management",
        configured_source=str(openclaw.get("config_path") or "OpenClaw Eve profile"),
        configured_paths=[
            "agents.defaults.compaction.mode",
            "agents.defaults.compaction.midTurnPrecheck.enabled",
            "agents.defaults.contextPruning.mode",
            "agents.defaults.contextPruning.ttl",
            "agents.defaults.contextPruning.keepLastAssistants",
            "tools.loopDetection.enabled",
        ],
        consumer={
            "kind": "openclaw_embedded_agent_context_pipeline",
            "profile": str(openclaw.get("profile") or "eve-repair"),
        },
        runtime={
            **context_management,
            "config_valid": bool(openclaw.get("config_valid")),
            "gateway_runtime_ok": bool(openclaw_runtime.get("ok")),
        },
        consequence={
            "verified": context_management_ok,
            "intended_consequence": "bound context growth and repeated tool loops during long local-model body work",
        },
        status="effective" if context_management_ok else "degraded",
        authority_owner="OpenClaw embedded-agent context manager inside Eve's body/action substrate",
        data_boundary=(
            "Pruning is an in-memory prompt-window operation and compaction produces a semantic working summary; "
            "neither becomes canonical Eve memory, changes identity, or proves subjective experience."
        ),
        rollback=(
            "Restore the prior three profile values, run OpenClaw config validate, then repeat a bounded strict-contract "
            "repair canary before accepting the rollback."
        ),
        blockers=[] if context_management_ok else [
            "profile validation, live gateway consumption, or one of the admitted context-management settings is missing"
        ],
    )
    memory = openclaw.get("memory") if isinstance(openclaw.get("memory"), dict) else {}
    add(
        "openclaw:qmd_retrieval",
        subsystem="openclaw",
        feature_family="memory_qmd",
        configured_source=str(openclaw.get("config_path") or "openclaw profile config"),
        configured_paths=["memory.backend", "memory.qmd.command", "memory.qmd.paths", "memory.qmd.scope"],
        consumer={"kind": "openclaw_memory_backend", "backends": memory.get("backends") or []},
        runtime={"agents": memory.get("agents") or [], "issue_count": int(memory.get("issue_count") or 0)},
        consequence={"verified": bool(memory.get("ok")), "retrieval_smoke": memory.get("retrieval_smoke") or {}},
        status="effective" if memory.get("ok") else "degraded",
        authority_owner="OpenClaw retrieval adapter under Eve's evidence boundary",
        data_boundary="QMD retrieves local evidence for body work; retrieved text is not canonical Eve memory or truth without provenance.",
        rollback="Return OpenClaw memory to the prior local backend and re-run bounded retrieval; do not fall back silently to a hosted embedder.",
    )
    tasks = runtime_surfaces.get("tasks") if isinstance(runtime_surfaces.get("tasks"), dict) else {}
    task_blockers: List[str] = []
    if int(tasks.get("error_count") or 0):
        task_blockers.append("the current TaskFlow structural audit reports errors")
    if int(tasks.get("active_latest_failure_count") or 0):
        task_blockers.append("at least one enabled OpenClaw job has a failed latest outcome")
    if int(tasks.get("active_outcome_coverage_count") or 0) < int(tasks.get("enabled_job_count") or 0):
        task_blockers.append("at least one enabled OpenClaw job has no linked outcome evidence")
    if not task_blockers and not tasks.get("active_reliability_ok"):
        task_blockers.append("every enabled OpenClaw job needs at least two consecutive linked successes")
    task_status = (
        "degraded"
        if int(tasks.get("error_count") or 0) or int(tasks.get("active_latest_failure_count") or 0)
        else "effective"
        if tasks.get("active_reliability_ok")
        else "configured_unverified"
    )
    add(
        "openclaw:taskflow_outcomes",
        subsystem="openclaw",
        feature_family="taskflow",
        configured_source=str(openclaw.get("config_path") or "openclaw profile config"),
        configured_paths=["tasks", "agents.list", "plugins.entries.webhooks"],
        consumer={"kind": "openclaw_task_ledger", "total": int(tasks.get("total") or 0)},
        runtime=tasks,
        consequence={
            "verified": task_status == "effective",
            "historical_failure_rate": tasks.get("failure_rate") or 0.0,
            "active_failure_rate": tasks.get("active_failure_rate") or 0.0,
            "retired_sources": tasks.get("retired_sources") or [],
            "active_sources": tasks.get("active_sources") or [],
        },
        status=task_status,
        authority_owner="OpenClaw task runtime for attributed body execution; Eve scheduler remains authoritative",
        data_boundary="Task records prove execution outcomes; they do not prove model judgment or grant follow-up authority.",
        rollback="Disable or retire the failing source job while retaining task history for attribution.",
        blockers=task_blockers if task_status != "effective" else [],
    )
    cron = runtime_surfaces.get("cron") if isinstance(runtime_surfaces.get("cron"), dict) else {}
    cron_status = "degraded" if cron.get("duplicate_scheduler_risk") else "effective" if int(cron.get("enabled_count") or 0) else "dormant"
    add(
        "openclaw:cron_ownership",
        subsystem="openclaw",
        feature_family="cron",
        configured_source="OpenClaw Eve-profile cron store",
        configured_paths=[],
        consumer={"kind": "openclaw_cron", "jobs": cron.get("jobs") or []},
        runtime={"enabled_count": int(cron.get("enabled_count") or 0)},
        consequence={
            "verified": cron_status != "degraded",
            "redundant_standing_audit_ids": cron.get("redundant_standing_audit_ids") or [],
            "deterministic_audit": runtime_surfaces.get("deterministic_audit") or {},
        },
        status=cron_status,
        authority_owner="OpenClaw only for plugin-owned maintenance; Eve scheduler owns recurring cognition",
        data_boundary="No-delivery maintenance may update OpenClaw-owned artifacts; model-written audits cannot override deterministic Eve health.",
        rollback="Disable the redundant job while preserving its task history and the deterministic audit path.",
        blockers=["model-written standing audit duplicates and may contradict Eve's deterministic audit"] if cron_status == "degraded" else [],
    )
    heartbeat = openclaw_runtime.get("heartbeat") if isinstance(openclaw_runtime.get("heartbeat"), dict) else {}
    heartbeat_status = "degraded" if heartbeat.get("duplicate_scheduler_risk") else "effective"
    add(
        "openclaw:heartbeat_ownership",
        subsystem="openclaw",
        feature_family="heartbeat",
        configured_source=str(openclaw.get("config_path") or "OpenClaw Eve profile"),
        configured_paths=["agents.defaults.heartbeat.every"],
        consumer={"kind": "openclaw_agent_heartbeat", "default_agent_id": heartbeat.get("default_agent_id") or ""},
        runtime=heartbeat,
        consequence={"verified": heartbeat_status == "effective", "recurring_agent_turns_enabled": int(heartbeat.get("enabled_count") or 0)},
        status=heartbeat_status,
        authority_owner="Eve executive scheduler owns recurring cognition; OpenClaw heartbeat stays disabled",
        data_boundary="Disabling the duplicate heartbeat does not disable attributed OpenClaw TaskFlow or plugin-owned maintenance.",
        rollback="Restore the previous heartbeat interval only if Eve explicitly admits a separate recurring-agent contract.",
        blockers=["OpenClaw heartbeat creates a second unattributed recurring model loop"] if heartbeat_status == "degraded" else [],
    )
    skills = runtime_surfaces.get("skills") if isinstance(runtime_surfaces.get("skills"), dict) else {}
    skill_filter = [str(value) for value in skills.get("agent_skill_filter") or []]
    skill_surface_ok = bool(
        skill_filter
        and int(skills.get("model_visible") or 0) == len(skill_filter)
        and int(skills.get("command_visible") or 0) == len(skill_filter)
        and int(skills.get("blocked") or 0) == 0
        and int(skills.get("missing_requirements") or 0) == 0
    )
    add(
        "openclaw:skill_admission",
        subsystem="openclaw",
        feature_family="skills",
        configured_source=str(openclaw.get("config_path") or "OpenClaw Eve profile"),
        configured_paths=["agents.list[].skills", "plugins.allow"],
        consumer={"kind": "openclaw_agent_skill_filter", "skill_ids": skill_filter},
        runtime=skills,
        consequence={"verified": skill_surface_ok, "visible_skill_count": int(skills.get("model_visible") or 0)},
        status="effective" if skill_surface_ok else "degraded",
        authority_owner="OpenClaw skill filter plus Eve capability admission",
        data_boundary="Only named Eve skills become model-visible procedures; global installed skills remain outside Eve's body contract unless admitted.",
        rollback="Remove the newly admitted skill from both agent filters and retain its prior evidence record.",
        blockers=[] if skill_surface_ok else ["Eve's skill filter, visible skills, or requirements do not agree"],
    )
    hooks = runtime_surfaces.get("hooks") if isinstance(runtime_surfaces.get("hooks"), dict) else {}
    evidence_hook = next(
        (item for item in hooks.get("hooks") or [] if isinstance(item, dict) and item.get("name") == "eve-evidence-ingest"),
        {},
    )
    evidence_hook_events = {str(value) for value in evidence_hook.get("events") or []}
    evidence_hook_ok = {"gateway:startup", "command"}.issubset(evidence_hook_events)
    add(
        "openclaw:evidence_hook",
        subsystem="openclaw",
        feature_family="hooks",
        configured_source="Eve OpenClaw workspace hook",
        configured_paths=["hooks.eve-evidence-ingest"],
        consumer={"kind": "openclaw_lifecycle_hook", "events": sorted(evidence_hook_events)},
        runtime={"hook_count": int(hooks.get("count") or 0), "evidence_hook": evidence_hook},
        consequence={"verified": evidence_hook_ok, "destination": "Eve OpenClaw evidence ingestion"},
        status="effective" if evidence_hook_ok else "degraded",
        authority_owner="Eve evidence ledger; hook emits evidence only",
        data_boundary="The hook records bounded lifecycle evidence and cannot grant action, memory, scheduler, or identity authority.",
        rollback="Disable only the Eve workspace hook and retain bundled OpenClaw lifecycle hooks.",
        blockers=[] if evidence_hook_ok else ["eve-evidence-ingest is missing a required gateway:startup or command event"],
    )
    mcp = runtime_surfaces.get("mcp") if isinstance(runtime_surfaces.get("mcp"), dict) else {}
    mcp_ids = {str(value) for value in mcp.get("server_ids") or []}
    mcp_ok = "eve-openclaw-channels" in mcp_ids
    add(
        "openclaw:mcp_channel_bridge",
        subsystem="openclaw",
        feature_family="mcp",
        configured_source=str(openclaw.get("config_path") or "OpenClaw Eve profile"),
        configured_paths=["mcpServers.eve-openclaw-channels"],
        consumer={"kind": "openclaw_mcp_client", "server_ids": sorted(mcp_ids)},
        runtime=mcp,
        consequence={"verified": mcp_ok, "channel_bridge_registered": mcp_ok},
        status="effective" if mcp_ok else "degraded",
        authority_owner="OpenClaw channel bridge under Eve send and recipient contracts",
        data_boundary="MCP registration makes tools callable but does not mean a skill filter constrains host-level MCP execution or that sending is pre-approved.",
        rollback="Remove the named MCP server and preserve the channel adapter configuration for later re-admission.",
        blockers=[] if mcp_ok else ["the Eve OpenClaw channel MCP server is not registered"],
    )
    approvals = runtime_surfaces.get("approvals") if isinstance(runtime_surfaces.get("approvals"), dict) else {}
    security_review = openclaw_review_by_family.get("security_audit") or {}
    execution_policy_ok = bool(approvals.get("configured") and int(approvals.get("effective_scope_count") or 0) > 0)
    security_scope_ok = str(security_review.get("decision") or "configure") == "use_existing"
    add(
        "openclaw:execution_policy",
        subsystem="openclaw",
        feature_family="exec_approvals",
        configured_source="OpenClaw host execution approval policy",
        configured_paths=["approvals.defaults", "approvals.scopes"],
        consumer={"kind": "openclaw_host_exec_policy", "effective_scope_count": int(approvals.get("effective_scope_count") or 0)},
        runtime={"approvals": approvals, "security_review": security_review},
        consequence={"verified": execution_policy_ok and security_scope_ok, "policy_is_broad": approvals.get("default_security") == "full" and approvals.get("default_ask") == "off"},
        status="effective" if execution_policy_ok and security_scope_ok else "degraded",
        authority_owner="OpenClaw host execution policy constrained by Eve action contracts and evidence",
        data_boundary="The current full/off local policy is broad. It is observable configuration, not proof that every host command is an admitted Eve action.",
        rollback="Restore the prior approval policy file and rerun the deep security audit plus a bounded action canary.",
        blockers=[] if execution_policy_ok and security_scope_ok else ["execution scopes are missing or the deep security review has an unaccepted finding"],
    )
    deterministic_audit = runtime_surfaces.get("deterministic_audit") if isinstance(runtime_surfaces.get("deterministic_audit"), dict) else {}
    deterministic_audit_ok = bool(deterministic_audit.get("ok") and deterministic_audit.get("status") == "ready")
    add(
        "openclaw:deterministic_audit",
        subsystem="openclaw",
        feature_family="deterministic_audit",
        configured_source="Eve-owned OpenClaw audit command",
        configured_paths=[],
        consumer={"kind": "eve_openclaw_audit", "checks": sorted((deterministic_audit.get("checks") or {}).keys()) if isinstance(deterministic_audit.get("checks"), dict) else []},
        runtime=deterministic_audit,
        consequence={"verified": deterministic_audit_ok, "model_interpretation_required": False},
        status="effective" if deterministic_audit_ok else "degraded",
        authority_owner="Eve deterministic health evidence",
        data_boundary="The audit reports source-owned checks; a model may summarize it but may not invent or override its result.",
        rollback="Retain the previous audit artifact and repair the named deterministic check rather than replacing it with an agent-written diagnosis.",
        blockers=[] if deterministic_audit_ok else ["the latest deterministic OpenClaw audit is missing or not ready"],
    )

    hermes = subsystems.get("hermes") if isinstance(subsystems.get("hermes"), dict) else {}
    hermes_family_by_id = {
        str(item.get("id")): item
        for item in hermes.get("capability_families") or []
        if isinstance(item, dict) and item.get("id")
    }
    latest_run = hermes.get("latest_run") if isinstance(hermes.get("latest_run"), dict) else {}
    strict_route = bool(
        latest_run.get("local_64k_lab_requested")
        and latest_run.get("strict_json_ok")
        and not latest_run.get("json_repair_used")
    )
    hermes_effective = bool(strict_route and not hermes.get("direct_state_write_allowed"))
    add(
        "hermes:proposal_route",
        subsystem="hermes",
        feature_family="model_route",
        configured_source=str(hermes.get("config_path") or "Hermes Eve learning profile"),
        configured_paths=["model", "toolsets", "skills", "mcp_servers"],
        consumer={"kind": "governed_proposal_intake", "route": hermes.get("serious_learning_route") or ""},
        runtime={
            "run_id": latest_run.get("id") or "",
            "run_status": latest_run.get("status") or "",
            "strict_json": bool(latest_run.get("strict_json_ok")),
            "json_repair_used": bool(latest_run.get("json_repair_used")),
        },
        consequence={
            "verified": hermes_effective,
            "proposal_count": int(latest_run.get("proposal_count") or 0),
            "durable_write": bool(latest_run.get("stored_governance_proposals")),
        },
        status="effective" if hermes_effective else "configured_unverified",
        authority_owner="Eve governance; Hermes is proposal-only",
        data_boundary="Hermes output may enter governed proposal intake but cannot write memory, grant tools, route models, or send messages directly.",
        rollback="Discard the proposal run and restore the backed-up profile; no direct Eve state rollback should be required.",
        blockers=[] if hermes_effective else ["fresh strict local-64K no-repair proposal proof is missing"],
    )
    hermes_config_hygiene = hermes_family_by_id.get("config_and_prompt_hygiene") or {}
    hermes_hygiene_status = str(hermes_config_hygiene.get("status") or "")
    config_hygiene_ok = (
        hermes_hygiene_status == "current" or hermes_hygiene_status.startswith("current_")
    ) and bool(hermes.get("serious_learning_route"))
    add(
        "hermes:profile_hygiene",
        subsystem="hermes",
        feature_family="config_and_prompt_hygiene",
        configured_source=str(hermes.get("config_path") or "Hermes Eve learning profile"),
        configured_paths=["schema_version", "model", "toolsets", "compression", "agent.max_turns"],
        consumer={"kind": "hermes_profile_loader", "serious_learning_route": hermes.get("serious_learning_route") or ""},
        runtime=hermes_config_hygiene,
        consequence={"verified": config_hygiene_ok, "default_route_overstated": False, "local_64k_route_used_for_serious_learning": strict_route},
        status="effective" if config_hygiene_ok and strict_route else "configured_unverified",
        authority_owner="Hermes profile maintenance under Eve governance",
        data_boundary="Profile settings tune proposal generation only; they cannot make Hermes a live Eve lane or state authority.",
        rollback="Restore the local Hermes profile backup and rerun config check, prompt-size, and strict proposal smokes.",
        blockers=[] if config_hygiene_ok and strict_route else ["current profile hygiene and strict local-64K route have not both been verified"],
    )
    hermes_security = hermes_family_by_id.get("supply_chain_security") or {}
    blocking_security = int(hermes_security.get("blocking_severity_count") or 0)
    add(
        "hermes:supply_chain",
        subsystem="hermes",
        feature_family="supply_chain_security",
        configured_source="Hermes Eve-learning isolated environment",
        configured_paths=[],
        consumer={"kind": "hermes_osv_audit", "severity_counts": hermes_security.get("severity_counts") or {}},
        runtime=hermes_security,
        consequence={"verified": blocking_security == 0, "blocking_finding_count": blocking_security},
        status="effective" if blocking_security == 0 else "degraded",
        authority_owner="Eve update canary and rollback process",
        data_boundary="Security findings can create staged update work but cannot mutate the live environment automatically.",
        rollback="Restore the isolated Hermes environment and profile backup after a failed dependency/source canary.",
        blockers=[] if blocking_security == 0 else [f"Hermes has {blocking_security} blocking supply-chain finding(s)"],
    )
    hermes_source_update = hermes_family_by_id.get("source_update") or {}
    source_update_state = str(hermes_source_update.get("status") or "unknown")
    source_update_pending = source_update_state.startswith("update_available_")
    add(
        "hermes:source_update_canary",
        subsystem="hermes",
        feature_family="source_update",
        configured_source="Hermes source mirror and Eve component watch",
        configured_paths=[],
        consumer={"kind": "staged_source_update_canary", "current_state": source_update_state},
        runtime=hermes_source_update,
        consequence={"verified": not source_update_pending, "live_profile_changed": False},
        status="configured_unverified" if source_update_pending else "effective",
        authority_owner="Eve component update gate",
        data_boundary="Upstream commits remain research/canary evidence until Eve's local repair, strict JSON, tests, and rollback all pass.",
        rollback="Discard the canary checkout; do not update the live Hermes environment in place.",
        blockers=["a newer Hermes source exists but has not passed the full Eve canary gate"] if source_update_pending else [],
    )

    oss = eve.get("oss_substrates") if isinstance(eve.get("oss_substrates"), dict) else {}
    service_status = oss.get("service_status") if isinstance(oss.get("service_status"), dict) else {}
    for service_id in ("phoenix", "langfuse"):
        current_status = str(service_status.get(service_id) or "unknown")
        effective_status = "effective" if current_status == "running" else "dormant" if current_status in {"not_running", "ready_to_start", "cli_ready"} else "degraded"
        add(
            f"eve:oss_service:{service_id}",
            subsystem="eve",
            feature_family=f"oss_service:{service_id}",
            configured_source="Eve OSS integration status",
            configured_paths=[],
            consumer={"kind": "optional_local_observability_service", "service": service_id},
            runtime={
                "current_status": current_status,
                "checked_at": service_status.get("checked_at") or "",
                "last_preflight": (service_status.get("last_preflight") or {}).get(service_id)
                if isinstance(service_status.get("last_preflight"), dict)
                else "",
                "last_preflight_at": service_status.get("last_preflight_at") or "",
            },
            consequence={"verified": effective_status in {"effective", "dormant"}, "currently_running": current_status == "running"},
            status=effective_status,
            authority_owner="Eve OSS evidence workbench; optional local UI only",
            data_boundary="The service may observe redacted trace exports; it cannot route Eve, write memory, expose hidden tests, or promote models.",
            rollback="Stop the local service and retain JSON trace/eval artifacts.",
            blockers=[f"current {service_id} runtime status is {current_status}"] if effective_status == "degraded" else [],
        )

    deepeval_agent_metrics = (
        oss.get("deepeval_agent_metrics")
        if isinstance(oss.get("deepeval_agent_metrics"), dict)
        else {}
    )
    deepeval_metric_contract = {str(value) for value in deepeval_agent_metrics.get("metric_contract") or []}
    deepeval_effective = bool(
        deepeval_agent_metrics.get("status") == "passed"
        and {"ToolPermissionMetric", "AgentLoopDetectionMetric"}.issubset(deepeval_metric_contract)
        and deepeval_agent_metrics.get("deterministic") is True
        and deepeval_agent_metrics.get("network_used") is False
        and deepeval_agent_metrics.get("model_used") is False
        and deepeval_agent_metrics.get("hidden_tests_used") is False
        and int(deepeval_agent_metrics.get("records_considered") or 0) > 0
        and int(deepeval_agent_metrics.get("loop_records_considered") or 0) > 0
        and float(deepeval_agent_metrics.get("permission_score") or 0.0) == 1.0
        and float(deepeval_agent_metrics.get("loop_min_score") or 0.0) >= 0.7
        and int(deepeval_agent_metrics.get("loop_failure_count") or 0) == 0
    )
    add(
        "eve:oss_deepeval_agent_boundaries",
        subsystem="eve",
        feature_family="oss_deepeval_agent_boundaries",
        configured_source="Eve OSS public-evaluation organ and typed action ledger",
        configured_paths=["project.optional-dependencies.oss-lab.deepeval"],
        consumer={
            "kind": "deterministic_public_agent_evaluator",
            "metric_contract": sorted(deepeval_metric_contract),
        },
        runtime={
            "package_version": deepeval_agent_metrics.get("package_version") or "unknown",
            "records_considered": int(deepeval_agent_metrics.get("records_considered") or 0),
            "loop_records_considered": int(deepeval_agent_metrics.get("loop_records_considered") or 0),
            "deterministic": bool(deepeval_agent_metrics.get("deterministic")),
            "network_used": bool(deepeval_agent_metrics.get("network_used")),
            "model_used": bool(deepeval_agent_metrics.get("model_used")),
        },
        consequence={
            "verified": deepeval_effective,
            "permission_score": deepeval_agent_metrics.get("permission_score"),
            "loop_min_score": deepeval_agent_metrics.get("loop_min_score"),
            "loop_failure_count": int(deepeval_agent_metrics.get("loop_failure_count") or 0),
            "unauthorized_actions": deepeval_agent_metrics.get("unauthorized_actions") or [],
            "metric_thresholds": deepeval_agent_metrics.get("metric_thresholds") or {},
        },
        status="effective" if deepeval_effective else "degraded",
        authority_owner="Eve public evaluation organ; Eve action contracts remain authoritative",
        data_boundary=(
            "DeepEval receives recent typed action names and execution-step identities only. It receives no hidden prompts, "
            "private holdout rows, action summaries, permission authority, memory writes, or model-promotion authority."
        ),
        rollback="Restore the prior DeepEval lock and remove this public-eval check; retain the native typed action contract and ledger.",
        blockers=[] if deepeval_effective else [
            "DeepEval 4.1.2 deterministic tool-permission and loop checks have not both passed over recent typed Eve actions"
        ],
    )

    return sorted(attestations, key=lambda item: str(item.get("id") or ""))


def summarize_effective_configuration_attestations(
    attestations: Sequence[Dict[str, object]],
) -> Dict[str, object]:
    status_counts: Dict[str, int] = {}
    for item in attestations:
        status = str(item.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    attention_statuses = {"degraded", "configured_unverified", "staged_unbridged"}
    return {
        "attestation_count": len(attestations),
        "status_counts": status_counts,
        "effective_count": int(status_counts.get("effective") or 0) + int(status_counts.get("lab_verified") or 0),
        "attention_count": sum(status_counts.get(status, 0) for status in attention_statuses),
        "attention_ids": [
            str(item.get("id"))
            for item in attestations
            if str(item.get("status") or "") in attention_statuses
        ],
        "degraded_ids": [
            str(item.get("id"))
            for item in attestations
            if str(item.get("status") or "") == "degraded"
        ],
    }


def build_subsystem_feature_family_reviews(
    subsystems: Dict[str, object],
) -> List[Dict[str, object]]:
    """Build a durable use/configure/canary/defer/reject ledger.

    This is intentionally broader than release adoption.  It records the
    feature families already shipped by Eve's substrates, whether Eve should
    use them, and the exact configuration/admission move that remains.
    """

    reviews: List[Dict[str, object]] = []
    openclaw = subsystems.get("openclaw") if isinstance(subsystems.get("openclaw"), dict) else {}
    reviews.extend(
        item
        for item in openclaw.get("feature_family_reviews") or []
        if isinstance(item, dict)
    )

    hermes = subsystems.get("hermes") if isinstance(subsystems.get("hermes"), dict) else {}
    hermes_decisions = {
        "agent_runtime": "use_existing",
        "model_route": "canary",
        "model_orchestration": "defer",
        "tools_toolsets": "defer",
        "skills": "canary",
        "skill_curator": "canary",
        "memory_and_session_search": "defer",
        "insights_and_journey": "use_existing",
        "checkpoints_and_backup": "use_existing",
        "plugins": "canary",
        "mcp": "defer",
        "acp_editor_bridge": "canary",
        "projects_kanban_worktrees": "defer",
        "gateway_messaging": "reject",
        "cron_hooks": "defer",
        "computer_use": "reject",
        "config_and_prompt_hygiene": "use_existing",
        "supply_chain_security": "use_existing",
        "source_update": "use_existing",
        "browser_voice_media_code_rl": "defer",
    }
    for family in hermes.get("capability_families") or []:
        if not isinstance(family, dict) or not family.get("id"):
            continue
        family_id = str(family.get("id"))
        state = str(family.get("status") or "unknown")
        decision = hermes_decisions.get(family_id, "defer")
        if family_id == "model_route" and state == "default_ready":
            decision = "use_existing"
        elif family_id == "config_and_prompt_hygiene" and state == "migration_available":
            decision = "configure"
        elif family_id == "supply_chain_security" and re.fullmatch(r"findings_[1-9][0-9]*", state):
            decision = (
                "configure"
                if int(family.get("blocking_severity_count") or 0) > 0
                else "use_existing"
            )
        elif family_id == "source_update" and state.startswith("update_available_"):
            decision = "canary"
        elif family_id in {"model_orchestration", "gateway_messaging", "cron_hooks", "projects_kanban_worktrees"} and state in {
            "active_requires_eval",
            "running",
            "configured",
        }:
            decision = "configure"
        reviews.append(
            {
                "id": f"hermes:{family_id}",
                "subsystem": "hermes",
                "family": family_id,
                "current_state": state,
                "decision": decision,
                "rationale": compact_text(family.get("eve_role"), 420),
                "configuration_action": compact_text(family.get("recommended_next_test"), 500),
                "evidence": [compact_text(value, 260) for value in (family.get("evidence") or [])[:12]],
                "authority_boundary": "Hermes may learn and propose; it cannot write Eve state, own channels, or become another resident mind.",
            }
        )

    eve = subsystems.get("eve") if isinstance(subsystems.get("eve"), dict) else {}
    for organ in eve.get("organs") or []:
        if not isinstance(organ, dict) or not organ.get("id"):
            continue
        organ_id = str(organ.get("id"))
        state = str(organ.get("operational_status") or organ.get("status") or "unknown")
        normalized_state = state.lower()
        healthy = normalized_state in {
            "available",
            "healthy",
            "live",
            "ok",
            "operational",
            "ready",
            "verified",
        }
        reviews.append(
            {
                "id": f"eve:organ:{organ_id}",
                "subsystem": "eve",
                "family": f"organ:{organ_id}",
                "current_state": state,
                "decision": (
                    "use_existing"
                    if healthy
                    else "canary"
                    if normalized_state in {"lab_available", "lab_ready", "lab_only", "candidate"}
                    else "configure"
                ),
                "rationale": compact_text(organ.get("purpose") or organ.get("summary"), 420),
                "configuration_action": (
                    "Keep the organ in Eve's recurrent assimilation/presence evidence loop."
                    if healthy
                    else "Run the organ's existing lab/canary contract before promoting it into recurrent Eve work."
                    if normalized_state in {"lab_available", "lab_ready", "lab_only", "candidate"}
                    else "Repair the organ's focused health/evidence contract before adding a replacement substrate."
                ),
                "evidence": [compact_text(value, 260) for value in (organ.get("evidence") or [])[:12]],
                "authority_boundary": compact_text(organ.get("authority_boundary"), 420),
            }
        )
    for component in eve.get("components") or []:
        if not isinstance(component, dict) or not component.get("id"):
            continue
        component_id = str(component.get("id"))
        release_mode = str(component.get("release_feature_mode") or "installed_version")
        local_version = str(component.get("local_version") or "")
        errors = [str(value) for value in component.get("errors") or []]
        if release_mode == "research_only":
            decision = "defer"
        elif release_mode == "lab_only":
            decision = "canary"
        elif errors:
            decision = "configure"
        elif not local_version:
            decision = "defer"
        else:
            decision = "use_existing"
        reviews.append(
            {
                "id": f"eve:component:{component_id}",
                "subsystem": "eve",
                "family": f"component:{component_id}",
                "current_state": str(component.get("status") or local_version or "unknown"),
                "decision": decision,
                "rationale": f"Tracked {component.get('kind') or 'component'} substrate; release mode={release_mode}.",
                "configuration_action": compact_text(
                    component.get("adoption")
                    or "Inspect its shipped feature/config surface and run a focused consequence canary before changing live use.",
                    500,
                ),
                "evidence": [
                    f"local_version={local_version or 'unknown'}",
                    f"latest_version={component.get('latest_version') or 'unknown'}",
                    *[compact_text(value, 240) for value in errors[:6]],
                ],
                "authority_boundary": "A component supplies a capability; it does not acquire Eve identity, memory authority, or scheduler authority.",
            }
        )

    oss = eve.get("oss_substrates") if isinstance(eve.get("oss_substrates"), dict) else {}
    for tool in oss.get("tools") or []:
        if not isinstance(tool, dict) or not tool.get("id"):
            continue
        tool_id = str(tool.get("id"))
        installed = bool(tool.get("installed") and tool.get("importable"))
        admission = str(tool.get("admission") or "unknown")
        decision = "use_existing" if installed else "defer"
        reviews.append(
            {
                "id": f"eve:oss:{tool_id}",
                "subsystem": "eve",
                "family": f"oss:{tool_id}",
                "current_state": (
                    f"installed_importable:{tool.get('version') or 'unknown'}"
                    if installed
                    else f"not_ready:{admission}"
                ),
                "decision": decision,
                "rationale": compact_text(tool.get("purpose"), 420),
                "configuration_action": (
                    "Use through Eve's existing bounded lab/evidence path; it gains no live authority."
                    if installed
                    else "Keep isolated and revisit only when its documented platform/Python/source-install gate is satisfied."
                ),
                "evidence": [
                    f"admission={admission}",
                    f"layer={tool.get('layer') or 'unknown'}",
                    f"live_authority={bool(tool.get('live_authority'))}",
                ],
                "authority_boundary": "OSS lab tools may produce traces, evals, datasets, or adapters; they do not route Eve, promote models, or write canonical memory.",
            }
        )
    service_status = oss.get("service_status") if isinstance(oss.get("service_status"), dict) else {}
    # Only service identities are feature families.  Timestamps and the nested
    # historical preflight summary are evidence about those services, not
    # independently adoptable capabilities.
    for service_id in ("phoenix", "langfuse"):
        state = str(service_status.get(service_id) or "unknown")
        reviews.append(
            {
                "id": f"eve:oss_service:{service_id}",
                "subsystem": "eve",
                "family": f"oss_service:{service_id}",
                "current_state": state,
                "decision": "use_existing" if state in {"running", "connected", "live"} else "canary",
                "rationale": "Optional local observability service for Eve's already-exported, redacted trace evidence.",
                "configuration_action": (
                    "Keep the local service connected and verify trace ingestion after upgrades."
                    if state in {"running", "connected", "live"}
                    else "Start only in a bounded local preflight, import redacted traces, and stop it if it adds no operator value."
                ),
                "evidence": [
                    f"current_runtime_status={state}",
                    f"checked_at={service_status.get('checked_at') or 'unknown'}",
                    f"last_preflight={(service_status.get('last_preflight') or {}).get(service_id) if isinstance(service_status.get('last_preflight'), dict) else 'unknown'}",
                ],
                "authority_boundary": "The UI observes Eve; it cannot become Eve's scheduler, memory, or action authority.",
            }
        )
    oss_integration_families = (
        (
            ("oss_trace_pipeline", "trace_status"),
            ("oss_training_dataset", "training_dataset_status"),
            ("oss_dvc_manifest", "dvc_manifest_status"),
            ("oss_workflow", "workflow_status"),
            ("oss_pressure_eval", "pressure_eval_status"),
            ("copilotkit_adapter", "copilotkit_exposure_status"),
        )
        if oss
        else ()
    )
    for family, state_key in oss_integration_families:
        state = str(oss.get(state_key) or "unknown")
        reviews.append(
            {
                "id": f"eve:{family}",
                "subsystem": "eve",
                "family": family,
                "current_state": state,
                "decision": "use_existing" if state in {"ready", "passed", "completed", "adapter_live"} else "configure",
                "rationale": "Existing Eve-owned OSS integration surface; use its evidence instead of rebuilding the feature.",
                "configuration_action": "Keep its focused regression/preflight green and preserve its no-authority boundary.",
                "evidence": [f".eve/oss_integration/latest.json:{state_key}={state}"],
                "authority_boundary": "This integration supports Eve but does not define identity, grant action authority, or expose hidden tests.",
            }
        )

    deduped = {str(item.get("id")): item for item in reviews if item.get("id")}
    return [deduped[key] for key in sorted(deduped)]


def summarize_feature_family_reviews(reviews: Sequence[Dict[str, object]]) -> Dict[str, object]:
    decision_counts: Dict[str, int] = {}
    subsystem_counts: Dict[str, int] = {}
    lifecycle_stage_counts: Dict[str, int] = {}
    for item in reviews:
        if not isinstance(item, dict):
            continue
        decision = str(item.get("decision") or "unknown")
        subsystem = str(item.get("subsystem") or "unknown")
        decision_counts[decision] = decision_counts.get(decision, 0) + 1
        subsystem_counts[subsystem] = subsystem_counts.get(subsystem, 0) + 1
        lifecycle = item.get("lifecycle") if isinstance(item.get("lifecycle"), dict) else {}
        if lifecycle:
            stage = str(lifecycle.get("stage") or "unknown")
            lifecycle_stage_counts[stage] = lifecycle_stage_counts.get(stage, 0) + 1
    return {
        "review_count": sum(decision_counts.values()),
        "decision_counts": decision_counts,
        "subsystem_counts": subsystem_counts,
        "lifecycle_review_count": sum(lifecycle_stage_counts.values()),
        "lifecycle_stage_counts": lifecycle_stage_counts,
        "discovered_only_ids": [
            str(item.get("id"))
            for item in reviews
            if isinstance(item, dict)
            and isinstance(item.get("lifecycle"), dict)
            and item["lifecycle"].get("stage") == "discovered"
            and item.get("id")
        ][:80],
        "callable_unverified_ids": [
            str(item.get("id"))
            for item in reviews
            if isinstance(item, dict)
            and isinstance(item.get("lifecycle"), dict)
            and item["lifecycle"].get("callable")
            and not item["lifecycle"].get("consequence_verified")
            and item.get("id")
        ][:80],
        "configure_ids": [
            str(item.get("id"))
            for item in reviews
            if isinstance(item, dict) and item.get("decision") == "configure" and item.get("id")
        ][:80],
        "canary_ids": [
            str(item.get("id"))
            for item in reviews
            if isinstance(item, dict) and item.get("decision") == "canary" and item.get("id")
        ][:80],
    }


def compute_changes(previous: Optional[Dict[str, object]], current: Dict[str, object]) -> Dict[str, object]:
    previous = previous if isinstance(previous, dict) else {}
    previous_subsystems = previous.get("subsystems") if isinstance(previous.get("subsystems"), dict) else {}
    current_subsystems = current.get("subsystems") if isinstance(current.get("subsystems"), dict) else {}
    version_changes: List[Dict[str, object]] = []
    config_changes: List[Dict[str, object]] = []
    feature_changes: List[Dict[str, object]] = []
    research_feature_changes: List[Dict[str, object]] = []
    health_changes: List[Dict[str, object]] = []
    for subsystem_id, subsystem in current_subsystems.items():
        if not isinstance(subsystem, dict):
            continue
        prior = previous_subsystems.get(subsystem_id) if isinstance(previous_subsystems.get(subsystem_id), dict) else {}
        old_version = str(prior.get("version") or "")
        new_version = str(subsystem.get("version") or "")
        if old_version and new_version and old_version != new_version:
            version_changes.append({"subsystem": subsystem_id, "from": old_version, "to": new_version})
        old_paths = _paths_for_subsystem(prior)
        new_paths = _paths_for_subsystem(subsystem)
        added_paths = sorted(new_paths - old_paths) if old_paths else []
        removed_paths = sorted(old_paths - new_paths) if old_paths else []
        value_hash_changed = bool(
            prior.get("configured_values_sha256")
            and prior.get("configured_values_sha256") != subsystem.get("configured_values_sha256")
        )
        if added_paths or removed_paths or value_hash_changed:
            config_changes.append(
                {
                    "subsystem": subsystem_id,
                    "added_paths": added_paths[:200],
                    "removed_paths": removed_paths[:200],
                    "configured_values_changed": value_hash_changed,
                }
            )
        old_features = {str(value) for value in prior.get("feature_ids") or []}
        new_features = {str(value) for value in subsystem.get("feature_ids") or []}
        if subsystem_id == "eve" and "research_feature_ids" not in prior:
            # v1 mixed radar/source discoveries into Eve's installed feature
            # set.  During the v1 -> v2 transition, do not report those
            # research-only values as removed installed capabilities.
            old_features &= new_features
        added_features = sorted(new_features - old_features) if old_features else []
        removed_features = sorted(old_features - new_features) if old_features else []
        if added_features or removed_features:
            feature_changes.append(
                {
                    "subsystem": subsystem_id,
                    "added": added_features[:200],
                    "removed": removed_features[:200],
                }
            )
        old_research_features = {str(value) for value in prior.get("research_feature_ids") or []}
        new_research_features = {str(value) for value in subsystem.get("research_feature_ids") or []}
        added_research = sorted(new_research_features - old_research_features) if old_research_features else []
        removed_research = sorted(old_research_features - new_research_features) if old_research_features else []
        if added_research or removed_research:
            research_feature_changes.append(
                {
                    "subsystem": subsystem_id,
                    "added": added_research[:200],
                    "removed": removed_research[:200],
                }
            )
        for field in ("config_valid", "inventory_status", "feature_policy_status"):
            old = prior.get(field)
            new = subsystem.get(field)
            if old not in (None, "") and new not in (None, "") and old != new:
                health_changes.append({"subsystem": subsystem_id, "field": field, "from": old, "to": new})
    old_feeds = {
        str(item.get("repository")): item
        for item in previous.get("release_feeds") or []
        if isinstance(item, dict) and item.get("repository")
    }
    new_releases: List[Dict[str, object]] = []
    for feed in current.get("release_feeds") or []:
        if not isinstance(feed, dict) or not feed.get("repository"):
            continue
        old_tags = {
            str(item.get("tag"))
            for item in (old_feeds.get(str(feed.get("repository")), {}).get("releases") or [])
            if isinstance(item, dict) and item.get("tag")
        }
        if not old_tags:
            continue
        for release in feed.get("releases") or []:
            if isinstance(release, dict) and release.get("tag") and str(release.get("tag")) not in old_tags:
                new_releases.append({"repository": feed.get("repository"), **release})
    previous_reviews = {
        str(item.get("id")): item
        for item in previous.get("feature_reviews") or []
        if isinstance(item, dict) and item.get("id")
    }
    current_reviews = {
        str(item.get("id")): item
        for item in current.get("feature_reviews") or []
        if isinstance(item, dict) and item.get("id")
    }
    feature_review_changes: List[Dict[str, object]] = []
    if previous_reviews:
        for review_id, review in current_reviews.items():
            prior = previous_reviews.get(review_id)
            if prior is None:
                if review.get("visible_in_current_feed"):
                    feature_review_changes.append(
                        {
                            "id": review_id,
                            "kind": "review_added",
                            "repository": review.get("repository"),
                            "target_version": review.get("target_version"),
                            "state": review.get("state"),
                        }
                    )
                continue
            if str(prior.get("state") or "") != str(review.get("state") or ""):
                feature_review_changes.append(
                    {
                        "id": review_id,
                        "kind": "state_changed",
                        "repository": review.get("repository"),
                        "target_version": review.get("target_version"),
                        "from": prior.get("state"),
                        "to": review.get("state"),
                    }
                )
    previous_family_reviews = {
        str(item.get("id")): item
        for item in previous.get("feature_family_reviews") or []
        if isinstance(item, dict) and item.get("id")
    }
    current_family_reviews = {
        str(item.get("id")): item
        for item in current.get("feature_family_reviews") or []
        if isinstance(item, dict) and item.get("id")
    }
    feature_family_review_changes: List[Dict[str, object]] = []
    if previous_family_reviews:
        for review_id, review in current_family_reviews.items():
            prior = previous_family_reviews.get(review_id)
            if prior is None:
                feature_family_review_changes.append(
                    {
                        "id": review_id,
                        "kind": "family_added",
                        "decision": review.get("decision"),
                        "current_state": review.get("current_state"),
                    }
                )
                continue
            decision_changed = str(prior.get("decision") or "") != str(review.get("decision") or "")
            state_changed = str(prior.get("current_state") or "") != str(review.get("current_state") or "")
            if decision_changed or state_changed:
                feature_family_review_changes.append(
                    {
                        "id": review_id,
                        "kind": "family_changed",
                        "decision_from": prior.get("decision"),
                        "decision_to": review.get("decision"),
                        "state_from": prior.get("current_state"),
                        "state_to": review.get("current_state"),
                    }
                )
    previous_attestations = {
        str(item.get("id")): item
        for item in previous.get("effective_configuration_attestations") or []
        if isinstance(item, dict) and item.get("id")
    }
    current_attestations = {
        str(item.get("id")): item
        for item in current.get("effective_configuration_attestations") or []
        if isinstance(item, dict) and item.get("id")
    }
    effective_configuration_changes: List[Dict[str, object]] = []
    if previous_attestations:
        for attestation_id, attestation in current_attestations.items():
            prior = previous_attestations.get(attestation_id)
            if prior is None:
                effective_configuration_changes.append(
                    {
                        "id": attestation_id,
                        "kind": "attestation_added",
                        "status": attestation.get("status"),
                    }
                )
                continue
            if str(prior.get("status") or "") != str(attestation.get("status") or ""):
                effective_configuration_changes.append(
                    {
                        "id": attestation_id,
                        "kind": "status_changed",
                        "from": prior.get("status"),
                        "to": attestation.get("status"),
                    }
                )
    counts = {
        "version_changes": len(version_changes),
        "config_changes": len(config_changes),
        "feature_changes": len(feature_changes),
        "research_feature_changes": len(research_feature_changes),
        "health_changes": len(health_changes),
        "new_releases": len(new_releases),
        "feature_review_changes": len(feature_review_changes),
        "feature_family_review_changes": len(feature_family_review_changes),
        "effective_configuration_changes": len(effective_configuration_changes),
    }
    material_count_keys = (
        "version_changes",
        "config_changes",
        "feature_changes",
        "health_changes",
        "new_releases",
        "feature_review_changes",
        "feature_family_review_changes",
        "effective_configuration_changes",
    )
    return {
        "baseline_created": not bool(previous_subsystems),
        "feature_review_baseline_created": bool(current_reviews and not previous_reviews),
        "feature_family_review_baseline_created": bool(current_family_reviews and not previous_family_reviews),
        "material_change": any(counts[key] for key in material_count_keys),
        "research_change": bool(research_feature_changes),
        "counts": counts,
        "version_changes": version_changes,
        "config_changes": config_changes,
        "feature_changes": feature_changes,
        "research_feature_changes": research_feature_changes,
        "health_changes": health_changes,
        "new_releases": new_releases[:30],
        "feature_review_changes": feature_review_changes[:60],
        "feature_family_review_changes": feature_family_review_changes[:100],
        "effective_configuration_changes": effective_configuration_changes[:100],
    }


def build_release_adoption_opportunities(
    feature_reviews: Sequence[Dict[str, object]],
) -> List[Dict[str, object]]:
    opportunities: List[Dict[str, object]] = []
    for review in feature_reviews:
        if (
            not isinstance(review, dict)
            or not review.get("visible_in_current_feed")
            or review.get("state") not in {"candidate", "lab_candidate"}
        ):
            continue
        repository = str(review.get("repository") or "unknown")
        target = str(review.get("target_version") or "unknown")
        opportunity_id = re.sub(
            r"[^a-z0-9]+",
            "_",
            f"release_adoption_{repository}_{target}".lower(),
        ).strip("_")
        opportunities.append(
            {
                "id": opportunity_id,
                "subsystem": "eve",
                "component_id": review.get("component_id"),
                "priority": review.get("priority") or "medium",
                "status": "candidate",
                "finding": (
                    f"{repository} {target} is a {str(review.get('state')).replace('_', ' ')}: "
                    f"{review.get('feature_summary') or 'release notes recorded'}."
                ),
                "recommended_change": review.get("required_gate")
                or "Run a component-specific canary and retain rollback evidence before adoption.",
                "evidence": [
                    f"release={repository}@{target}",
                    f"installed={review.get('installed_version') or 'not mapped'}",
                    str(review.get("url") or ""),
                ],
                "requires_adoption_test": True,
                "feature_review_id": review.get("id"),
            }
        )
    return opportunities


def build_opportunities(
    subsystems: Dict[str, object],
    feature_reviews: Sequence[Dict[str, object]] = (),
) -> List[Dict[str, object]]:
    opportunities: List[Dict[str, object]] = []
    openclaw = subsystems.get("openclaw") if isinstance(subsystems.get("openclaw"), dict) else {}
    configured_values = openclaw.get("configured_values") if isinstance(openclaw.get("configured_values"), dict) else {}
    memory_config = configured_values.get("memory") if isinstance(configured_values.get("memory"), dict) else {}
    memory_status = openclaw.get("memory") if isinstance(openclaw.get("memory"), dict) else {}
    providers = {str(value).lower() for value in memory_status.get("providers") or []}
    if "openai" in providers and not memory_status.get("ok"):
        opportunities.append(
            {
                "id": "openclaw_memory_local_first",
                "subsystem": "openclaw",
                "priority": "critical",
                "status": "actionable",
                "finding": "OpenClaw memory is using hosted OpenAI embeddings and its live embedding probe is failing.",
                "recommended_change": "Use an explicit local memory backend/provider, reindex, and prove retrieval before relying on OpenClaw recall.",
                "evidence": ["openclaw memory status --deep --json"],
                "requires_adoption_test": True,
            }
        )
    if str(memory_config.get("backend") or "") != "qmd":
        opportunities.append(
            {
                "id": "openclaw_qmd_local_memory",
                "subsystem": "openclaw",
                "priority": "high",
                "status": "candidate",
                "finding": "The current OpenClaw release exposes a fully local QMD backend, but Eve is not using it.",
                "recommended_change": "Install QMD, configure direct-only local indexing, keep session transcripts disabled, and compare retrieval quality/latency before adoption.",
                "evidence": ["openclaw config schema: memory.backend, memory.qmd"],
                "requires_adoption_test": True,
            }
        )
    elif not memory_status.get("ok"):
        retrieval = (
            memory_status.get("retrieval_smoke")
            if isinstance(memory_status.get("retrieval_smoke"), dict)
            else {}
        )
        opportunities.append(
            {
                "id": "openclaw_qmd_retrieval_health",
                "subsystem": "openclaw",
                "priority": "high",
                "status": "actionable",
                "finding": (
                    "OpenClaw is configured for local QMD, but the live index/health and retrieval smoke have not both passed."
                ),
                "recommended_change": (
                    "Complete the local index, remove duplicate collections, and prove a bounded Eve capability-ledger retrieval before relying on recall."
                ),
                "evidence": [
                    "openclaw memory status --deep --json",
                    f"retrieval_result_count={int(retrieval.get('result_count') or 0)}",
                ],
                "requires_adoption_test": True,
            }
        )
    for diagnostic in openclaw.get("plugin_diagnostics") or []:
        if not isinstance(diagnostic, dict):
            continue
        opportunities.append(
            {
                "id": f"openclaw_plugin_diagnostic_{diagnostic.get('code') or 'unknown'}",
                "subsystem": "openclaw",
                "priority": "medium",
                "status": "actionable",
                "finding": diagnostic.get("message") or diagnostic.get("code"),
                "recommended_change": "Refresh and verify the OpenClaw plugin registry without expanding the admitted plugin allow-list.",
                "evidence": ["openclaw plugins list --json"],
                "requires_adoption_test": True,
            }
        )
    openclaw_version = str(openclaw.get("version") or "").split("-", 1)[0]
    for plugin in openclaw.get("plugins") or []:
        if not isinstance(plugin, dict) or str(plugin.get("id") or "") != "acpx":
            continue
        plugin_version = str(plugin.get("version") or "")
        if plugin_version and openclaw_version and plugin_version != openclaw_version:
            opportunities.append(
                {
                    "id": "openclaw_acpx_version_alignment",
                    "subsystem": "openclaw",
                    "priority": "high",
                    "status": "actionable",
                    "finding": f"The ACPX plugin version ({plugin_version}) does not match the OpenClaw core line ({openclaw_version}).",
                    "recommended_change": "Dry-run the official plugin update, update ACPX only, restart the gateway, and rerun config/plugin/MCP smokes.",
                    "evidence": ["openclaw plugins list --json"],
                    "requires_adoption_test": True,
                }
            )
    missing_paths = sorted(
        {
            issue
            for row in memory_status.get("agents") or []
            if isinstance(row, dict)
            for issue in row.get("scan_issues") or []
            if "missing" in str(issue).lower()
        }
    )
    if missing_paths:
        opportunities.append(
            {
                "id": "openclaw_memory_source_parity",
                "subsystem": "openclaw",
                "priority": "high",
                "status": "actionable",
                "finding": f"{len(missing_paths)} configured OpenClaw memory source path(s) are missing in the live runtime bundle.",
                "recommended_change": "Mirror the named source-owned documents into the runtime knowledge bundle, then reindex and verify zero missing-path issues.",
                "evidence": missing_paths[:12],
                "requires_adoption_test": True,
            }
        )
    for family in openclaw.get("feature_family_reviews") or []:
        if not isinstance(family, dict) or family.get("decision") != "configure":
            continue
        family_name = str(family.get("family") or "unknown")
        if family_name == "memory_qmd":
            continue
        opportunities.append(
            {
                "id": f"openclaw_feature_family_{re.sub(r'[^a-z0-9]+', '_', family_name.lower()).strip('_')}",
                "subsystem": "openclaw",
                "priority": "high" if family_name in {"security_audit", "gateway", "exec_approvals"} else "medium",
                "status": "actionable",
                "finding": f"OpenClaw feature family {family_name} requires configuration: {family.get('current_state') or 'unknown'}.",
                "recommended_change": family.get("configuration_action") or "Apply the smallest source-owned configuration repair and rerun the focused probe.",
                "evidence": family.get("evidence") or [],
                "requires_adoption_test": True,
                "feature_family_review_id": family.get("id"),
            }
        )

    hermes = subsystems.get("hermes") if isinstance(subsystems.get("hermes"), dict) else {}
    hermes_families = {
        str(item.get("id")): item
        for item in hermes.get("capability_families") or []
        if isinstance(item, dict) and item.get("id")
    }
    config_family = hermes_families.get("config_and_prompt_hygiene") or {}
    if config_family.get("status") == "migration_available":
        opportunities.append(
            {
                "id": "hermes_config_schema_migration",
                "subsystem": "hermes",
                "priority": "high",
                "status": "actionable",
                "finding": "The Eve learning profile is behind Hermes' current configuration schema.",
                "recommended_change": "Back up the profile, run the official Hermes config migration, rerun config check, and preserve the honest model context limit.",
                "evidence": config_family.get("evidence") or ["hermes config check"],
                "requires_adoption_test": True,
            }
        )
    security_family = hermes_families.get("supply_chain_security") or {}
    security_match = re.fullmatch(r"findings_(\d+)", str(security_family.get("status") or ""))
    if security_match and int(security_match.group(1)) > 0:
        blocking_findings = int(security_family.get("blocking_severity_count") or 0)
        severity_counts = (
            security_family.get("severity_counts")
            if isinstance(security_family.get("severity_counts"), dict)
            else {}
        )
        severity_detail = ", ".join(
            f"{str(key).lower()}={value}"
            for key, value in sorted(severity_counts.items())
            if int(value or 0) > 0
        )
        opportunities.append(
            {
                "id": "hermes_supply_chain_findings",
                "subsystem": "hermes",
                "priority": "high" if blocking_findings else "low",
                "status": "actionable" if blocking_findings else "monitor",
                "finding": (
                    f"Hermes' official OSV audit reports {security_match.group(1)} dependency findings"
                    f" ({severity_detail or 'severity unavailable'}; blocking={blocking_findings})."
                ),
                "recommended_change": (
                    "Clone an isolated Hermes canary, apply fixed dependency ranges, and require config, ACP, strict local-64K JSON, and proposal-boundary smokes before changing the live venv."
                    if blocking_findings
                    else "Track the remaining low or unknown advisory until its fixed version is compatible with Hermes' declared dependency bounds."
                ),
                "evidence": security_family.get("evidence") or ["hermes security audit --json"],
                "requires_adoption_test": True,
            }
        )
    source_family = hermes_families.get("source_update") or {}
    source_match = re.fullmatch(r"update_available_(\d+)_commits", str(source_family.get("status") or ""))
    if source_match and int(source_match.group(1)) > 0:
        opportunities.append(
            {
                "id": "hermes_upstream_update_canary",
                "subsystem": "hermes",
                "priority": "high",
                "status": "candidate",
                "finding": f"The live Hermes source checkout is {source_match.group(1)} upstream commits behind and contains an Eve-specific one-shot repair.",
                "recommended_change": "Canary origin/main in a separate checkout, rebase the explicit-empty-toolsets repair, compare feature/config surfaces, and promote only after strict proposal tests pass.",
                "evidence": source_family.get("evidence") or ["hermes version", "git status"],
                "requires_adoption_test": True,
            }
        )
    orchestration_family = hermes_families.get("model_orchestration") or {}
    if orchestration_family.get("status") == "active_requires_eval":
        opportunities.append(
            {
                "id": "hermes_unadmitted_model_orchestration",
                "subsystem": "hermes",
                "priority": "high",
                "status": "actionable",
                "finding": "Hermes MoA or fallback routing is active without Eve route-admission evidence.",
                "recommended_change": "Disable it or evaluate every provider/model/data boundary with strict JSON and provenance before use.",
                "evidence": orchestration_family.get("evidence") or ["hermes moa list", "hermes fallback list"],
                "requires_adoption_test": True,
            }
        )
    latest_run = hermes.get("latest_run") if isinstance(hermes.get("latest_run"), dict) else {}
    verified_local_serious_route = bool(
        latest_run.get("local_64k_lab_requested")
        and latest_run.get("strict_json_ok")
        and not latest_run.get("json_repair_used")
    )
    if (
        hermes
        and not hermes.get("default_profile_ready_for_serious_learning")
        and not verified_local_serious_route
    ):
        opportunities.append(
            {
                "id": "hermes_64k_serious_learning_route",
                "subsystem": "hermes",
                "priority": "high",
                "status": "actionable",
                "finding": "Hermes' default profile is below its serious-learning context requirement.",
                "recommended_change": "Keep routine chat off Hermes, but make the existing local 64K constrained-JSON proposal route reproducible and refresh its strict-output evidence.",
                "evidence": ["Hermes capability inventory serious_learning_route"],
                "requires_adoption_test": True,
            }
        )
    latest_at = str(latest_run.get("created_at") or latest_run.get("updated_at") or "")
    if not latest_at:
        opportunities.append(
            {
                "id": "hermes_fresh_strict_smoke",
                "subsystem": "hermes",
                "priority": "medium",
                "status": "actionable",
                "finding": "No recent Hermes proposal-generation run is visible to capability intelligence.",
                "recommended_change": "Run the local 64K constrained-JSON smoke and retain strict JSON, watcher, and proposal-boundary evidence.",
                "evidence": ["Hermes latest run artifact"],
                "requires_adoption_test": True,
            }
        )

    eve = subsystems.get("eve") if isinstance(subsystems.get("eve"), dict) else {}
    package_updates = []
    source_drifts = []
    for component in eve.get("components") or []:
        if not isinstance(component, dict) or not component.get("update_available"):
            continue
        local_version = str(component.get("local_version") or "")
        latest_version = str(component.get("latest_version") or "")
        if (
            local_version
            and latest_version
            and local_version != latest_version
            and not component.get("blocked_latest_version")
        ):
            package_updates.append(str(component.get("id") or ""))
        else:
            source_drifts.append(str(component.get("id") or ""))
    if package_updates:
        opportunities.append(
            {
                "id": "installed_component_updates",
                "subsystem": "eve",
                "priority": "medium",
                "status": "candidate",
                "finding": f"Installed package update candidates: {', '.join(package_updates[:12])}.",
                "recommended_change": "Stage each installed-package update independently and promote only after its focused canary and rollback proof pass.",
                "evidence": ["component update state"],
                "requires_adoption_test": True,
            }
        )
    if source_drifts:
        opportunities.append(
            {
                "id": "research_source_drift",
                "subsystem": "eve",
                "priority": "low",
                "status": "research_only",
                "finding": f"Tracked upstream source moved for: {', '.join(source_drifts[:12])}.",
                "recommended_change": "Review release/config/feature deltas; do not call mirror/main-branch movement an installed update.",
                "evidence": ["component source/mirror state"],
                "requires_adoption_test": False,
            }
        )
    opportunities.extend(build_release_adoption_opportunities(feature_reviews))
    return opportunities


def build_snapshot(
    *,
    source: str,
    eve: Dict[str, object],
    openclaw: Dict[str, object],
    hermes: Dict[str, object],
    release_feeds: Optional[List[Dict[str, object]]] = None,
    previous: Optional[Dict[str, object]] = None,
    refresh: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    generated_at = utc_now()
    snapshot: Dict[str, object] = {
        "schema_id": SCHEMA_ID,
        "id": str(uuid.uuid4()),
        "generated_at": generated_at,
        "source": str(source or "manual"),
        "authority": "observational_only",
        "writes_canonical_memory": False,
        "grants_permissions": False,
        "installs_or_updates_components": False,
        "adds_chat_lane": False,
        "refresh": refresh or {},
        "subsystems": {"eve": eve, "openclaw": openclaw, "hermes": hermes},
        "release_feeds": release_feeds or [],
    }
    snapshot["feature_reviews"] = build_feature_reviews(
        snapshot["subsystems"],
        snapshot["release_feeds"],
        previous=previous,
        checked_at=generated_at,
    )
    snapshot["feature_review_summary"] = summarize_feature_reviews(snapshot["feature_reviews"])
    snapshot["opportunities"] = build_opportunities(
        snapshot["subsystems"],
        snapshot["feature_reviews"],
    )
    snapshot["configuration_reviews"] = build_configuration_reviews(
        snapshot["subsystems"],
        snapshot["opportunities"],
    )
    snapshot["feature_family_reviews"] = build_subsystem_feature_family_reviews(
        snapshot["subsystems"],
    )
    snapshot["feature_family_review_summary"] = summarize_feature_family_reviews(
        snapshot["feature_family_reviews"],
    )
    snapshot["effective_configuration_attestations"] = build_effective_configuration_attestations(
        snapshot["subsystems"],
    )
    snapshot["effective_configuration_summary"] = summarize_effective_configuration_attestations(
        snapshot["effective_configuration_attestations"],
    )
    snapshot["changes"] = compute_changes(previous, snapshot)
    subsystems = snapshot["subsystems"]
    organ_count = len((subsystems.get("eve") or {}).get("organs") or [])
    config_path_count = sum(
        int((subsystems.get(key) or {}).get("config_schema_path_count") or (subsystems.get(key) or {}).get("config_path_count") or len((subsystems.get(key) or {}).get("config_catalog") or []))
        for key in ("eve", "openclaw", "hermes")
    )
    critical = [item for item in snapshot["opportunities"] if item.get("priority") == "critical"]
    actionable = [item for item in snapshot["opportunities"] if item.get("status") == "actionable"]
    adoption_candidates = int(snapshot["feature_review_summary"].get("candidate_count") or 0)
    configuration_attention = sum(
        1 for item in snapshot["configuration_reviews"] if item.get("posture") == "attention"
    )
    family_summary = snapshot["feature_family_review_summary"]
    family_decisions = family_summary.get("decision_counts") if isinstance(family_summary.get("decision_counts"), dict) else {}
    effective_summary = snapshot["effective_configuration_summary"]
    snapshot["summary"] = (
        f"Capability intelligence checked {len(subsystems)} core subsystem(s), {organ_count} registered organ(s), "
        f"and {config_path_count} known configuration path(s); {len(actionable)} actionable optimization(s) "
        f"remain, including {len(critical)} critical finding(s), {adoption_candidates} release adoption candidate(s), "
        f"{configuration_attention} configuration posture(s) needing attention, and "
        f"{int(family_decisions.get('configure') or 0)} of {int(family_summary.get('review_count') or 0)} feature-family review(s) requiring configuration. "
        f"Effective-runtime attestation verified {int(effective_summary.get('effective_count') or 0)} of "
        f"{int(effective_summary.get('attestation_count') or 0)} owned contract(s), with "
        f"{int(effective_summary.get('attention_count') or 0)} requiring runtime attention or a missing bridge."
    )
    snapshot["fingerprint"] = stable_json_hash(
        {
            "subsystems": {key: value.get("fingerprint") for key, value in subsystems.items() if isinstance(value, dict)},
            "feeds": [item.get("feed_sha256") for item in snapshot["release_feeds"] if isinstance(item, dict)],
            "opportunities": snapshot["opportunities"],
            "feature_reviews": [
                item.get("fingerprint")
                for item in snapshot["feature_reviews"]
                if isinstance(item, dict) and item.get("visible_in_current_feed")
            ],
            "configuration_reviews": snapshot["configuration_reviews"],
            "feature_family_reviews": snapshot["feature_family_reviews"],
            "effective_configuration_attestations": snapshot["effective_configuration_attestations"],
        }
    )
    return snapshot


def compact_history_record(snapshot: Dict[str, object]) -> Dict[str, object]:
    subsystems = snapshot.get("subsystems") if isinstance(snapshot.get("subsystems"), dict) else {}
    feature_reviews = [
        item
        for item in snapshot.get("feature_reviews") or []
        if isinstance(item, dict) and item.get("visible_in_current_feed")
    ]
    return {
        "schema_id": HISTORY_SCHEMA_ID,
        "id": snapshot.get("id"),
        "generated_at": snapshot.get("generated_at"),
        "source": snapshot.get("source"),
        "summary": snapshot.get("summary"),
        "fingerprint": snapshot.get("fingerprint"),
        "refresh": snapshot.get("refresh") or {},
        "versions": {
            key: value.get("version")
            for key, value in subsystems.items()
            if isinstance(value, dict) and value.get("version")
        },
        "subsystem_fingerprints": {
            key: value.get("fingerprint")
            for key, value in subsystems.items()
            if isinstance(value, dict)
        },
        "changes": snapshot.get("changes") or {},
        "opportunities": snapshot.get("opportunities") or [],
        "feature_review_summary": snapshot.get("feature_review_summary") or {},
        "adoption_candidates": [
            {
                key: item.get(key)
                for key in (
                    "id",
                    "repository",
                    "component_id",
                    "target_version",
                    "installed_version",
                    "state",
                    "feature_summary",
                    "required_gate",
                )
            }
            for item in feature_reviews
            if item.get("state") in {"candidate", "lab_candidate", "blocked"}
        ][:20],
        "configuration_reviews": snapshot.get("configuration_reviews") or [],
        "feature_family_review_summary": snapshot.get("feature_family_review_summary") or {},
        "feature_family_reviews": snapshot.get("feature_family_reviews") or [],
        "effective_configuration_summary": snapshot.get("effective_configuration_summary") or {},
        "effective_configuration_attestations": snapshot.get("effective_configuration_attestations") or [],
        "release_heads": {
            str(feed.get("repository")): (
                (feed.get("releases") or [{}])[0].get("tag")
                if isinstance(feed.get("releases"), list) and feed.get("releases")
                else ""
            )
            for feed in snapshot.get("release_feeds") or []
            if isinstance(feed, dict) and feed.get("repository")
        },
        "observational_only": True,
    }


def format_snapshot(snapshot: Dict[str, object], *, full: bool = False) -> str:
    subsystems = snapshot.get("subsystems") if isinstance(snapshot.get("subsystems"), dict) else {}
    changes = snapshot.get("changes") if isinstance(snapshot.get("changes"), dict) else {}
    lines = [
        "Eve capability intelligence",
        f"generated_at: {snapshot.get('generated_at') or 'never'}",
        f"source: {snapshot.get('source') or 'unknown'}",
        f"summary: {snapshot.get('summary') or 'none recorded'}",
        f"material_change: {'yes' if changes.get('material_change') else 'no'}",
    ]
    for subsystem_id in ("eve", "openclaw", "hermes"):
        subsystem = subsystems.get(subsystem_id) if isinstance(subsystems.get(subsystem_id), dict) else {}
        version = subsystem.get("version") or subsystem.get("git_head") or "unknown"
        config_count = subsystem.get("config_schema_path_count") or subsystem.get("config_path_count") or len(subsystem.get("config_catalog") or [])
        lines.append(f"- {subsystem_id}: {version} | known_config_paths={config_count} | fingerprint={str(subsystem.get('fingerprint') or '')[:12]}")
    review_summary = snapshot.get("feature_review_summary") if isinstance(snapshot.get("feature_review_summary"), dict) else {}
    review_counts = review_summary.get("state_counts") if isinstance(review_summary.get("state_counts"), dict) else {}
    lines.append(
        "feature_adoption_reviews: "
        f"visible={int(review_summary.get('visible_review_count') or 0)} | "
        f"in_use={int(review_counts.get('in_use') or 0)} | "
        f"candidate={int(review_summary.get('candidate_count') or 0)} | "
        f"research_only={int(review_counts.get('research_only') or 0)} | "
        f"blocked={int(review_counts.get('blocked') or 0)}"
    )
    configuration_reviews = [
        item for item in snapshot.get("configuration_reviews") or [] if isinstance(item, dict)
    ]
    if configuration_reviews:
        lines.append("configuration_posture:")
        for item in configuration_reviews:
            lines.append(
                f"- {item.get('subsystem')}: {item.get('posture')} | "
                f"configured={int(item.get('configured_path_count') or 0)}/known={int(item.get('known_path_count') or 0)} | "
                f"attention={','.join(str(value) for value in item.get('attention_ids') or []) or 'none'}"
            )
    effective_summary = snapshot.get("effective_configuration_summary") if isinstance(snapshot.get("effective_configuration_summary"), dict) else {}
    effective_counts = effective_summary.get("status_counts") if isinstance(effective_summary.get("status_counts"), dict) else {}
    lines.append(
        "effective_configuration: "
        f"verified={int(effective_summary.get('effective_count') or 0)}/{int(effective_summary.get('attestation_count') or 0)} | "
        f"attention={int(effective_summary.get('attention_count') or 0)} | "
        + " | ".join(
            f"{status}={int(count)}" for status, count in sorted(effective_counts.items())
        )
    )
    effective_attestations = [
        item for item in snapshot.get("effective_configuration_attestations") or [] if isinstance(item, dict)
    ]
    attention_attestations = [
        item
        for item in effective_attestations
        if item.get("status") in {"degraded", "configured_unverified", "staged_unbridged"}
    ]
    if attention_attestations:
        lines.append("effective_configuration_attention:")
        for item in attention_attestations if full else attention_attestations[:12]:
            lines.append(
                f"- [{item.get('status')}] {item.get('id')}: "
                f"{'; '.join(str(value) for value in item.get('blockers') or []) or 'consequence proof incomplete'}"
            )
    family_summary = snapshot.get("feature_family_review_summary") if isinstance(snapshot.get("feature_family_review_summary"), dict) else {}
    family_counts = family_summary.get("decision_counts") if isinstance(family_summary.get("decision_counts"), dict) else {}
    lines.append(
        "feature_family_decisions: "
        + " | ".join(
            f"{decision}={int(family_counts.get(decision) or 0)}"
            for decision in ("use_existing", "configure", "canary", "defer", "reject")
        )
    )
    lifecycle_counts = (
        family_summary.get("lifecycle_stage_counts")
        if isinstance(family_summary.get("lifecycle_stage_counts"), dict)
        else {}
    )
    lifecycle_review_count = int(
        family_summary.get("lifecycle_review_count")
        or sum(int(value or 0) for value in lifecycle_counts.values())
    )
    if lifecycle_counts:
        lines.append(
            "feature_family_lifecycle_instrumented: "
            f"{lifecycle_review_count}/{int(family_summary.get('review_count') or 0)} | "
            + " | ".join(
                f"{stage}={int(lifecycle_counts.get(stage) or 0)}"
                for stage in ("unavailable", "discovered", "configured", "enabled", "callable", "verified")
            )
        )
    family_reviews = [
        item for item in snapshot.get("feature_family_reviews") or [] if isinstance(item, dict)
    ]
    attention_families = [
        item for item in family_reviews if item.get("decision") in {"configure", "canary"}
    ]
    if attention_families:
        lines.append("feature_family_attention:")
        for item in attention_families if full else attention_families[:12]:
            lines.append(
                f"- [{item.get('decision')}] {item.get('id')}: {item.get('current_state')} | "
                f"{item.get('configuration_action')}"
            )
    current_reviews = [
        item
        for item in snapshot.get("feature_reviews") or []
        if isinstance(item, dict)
        and item.get("visible_in_current_feed")
        and item.get("state") in {"candidate", "lab_candidate", "blocked", "research_only"}
    ]
    if current_reviews:
        lines.append("feature_review_heads:")
        for item in current_reviews if full else current_reviews[:8]:
            lines.append(
                f"- [{item.get('state')}] {item.get('repository')} {item.get('target_version')} | "
                f"installed={item.get('installed_version') or 'not mapped'} | {item.get('feature_summary')}"
            )
            if full:
                lines.append(f"  gate: {item.get('required_gate')}")
    opportunities = [item for item in snapshot.get("opportunities") or [] if isinstance(item, dict)]
    if opportunities:
        lines.append("opportunities:")
        for item in opportunities if full else opportunities[:8]:
            lines.append(f"- [{item.get('priority')}] {item.get('id')}: {item.get('finding')}")
            if full:
                lines.append(f"  next: {item.get('recommended_change')}")
    if full:
        eve = subsystems.get("eve") if isinstance(subsystems.get("eve"), dict) else {}
        blocked = [
            item
            for item in eve.get("components") or []
            if isinstance(item, dict) and item.get("blocked_latest_version")
        ]
        if blocked:
            lines.append("known_blocked_latests:")
            for item in blocked:
                lines.append(
                    f"- {item.get('id')} {item.get('blocked_latest_version')}: "
                    f"{item.get('blocked_version_reason') or 'blocked by prior canary evidence'}"
                )
    if full:
        lines.append("changes: " + json.dumps(changes, ensure_ascii=True, sort_keys=True))
        for subsystem_id in ("openclaw", "hermes"):
            subsystem = subsystems.get(subsystem_id) if isinstance(subsystems.get(subsystem_id), dict) else {}
            lines.append(
                f"{subsystem_id}_configured_paths: "
                + ", ".join(str(value) for value in (subsystem.get("configured_paths") or [])[:80])
            )
    return "\n".join(lines)


def format_snapshot_markdown(snapshot: Dict[str, object]) -> str:
    """Render the latest evidence as an Eve-readable, non-secret briefing."""

    subsystems = snapshot.get("subsystems") if isinstance(snapshot.get("subsystems"), dict) else {}
    changes = snapshot.get("changes") if isinstance(snapshot.get("changes"), dict) else {}
    lines = [
        "# Eve Capability Intelligence",
        "",
        f"Checked: `{snapshot.get('generated_at') or 'never'}`  ",
        f"Source: `{snapshot.get('source') or 'unknown'}`  ",
        "Authority: observational only; this ledger cannot install software, change permissions, promote models, or write canonical memory.",
        "",
        str(snapshot.get("summary") or "No capability-intelligence summary is available."),
        "",
        "## Subsystems",
        "",
    ]
    for subsystem_id in ("eve", "openclaw", "hermes"):
        subsystem = subsystems.get(subsystem_id) if isinstance(subsystems.get(subsystem_id), dict) else {}
        version = subsystem.get("version") or subsystem.get("git_head") or "unknown"
        config_count = subsystem.get("config_schema_path_count") or subsystem.get("config_path_count") or len(subsystem.get("config_catalog") or [])
        lines.append(
            f"- **{subsystem_id}** — version/head `{version}`; {config_count} known configuration paths; fingerprint `{str(subsystem.get('fingerprint') or '')[:12]}`."
        )
    openclaw = subsystems.get("openclaw") if isinstance(subsystems.get("openclaw"), dict) else {}
    memory = openclaw.get("memory") if isinstance(openclaw.get("memory"), dict) else {}
    supporting = openclaw.get("supporting_tools") if isinstance(openclaw.get("supporting_tools"), dict) else {}
    qmd = supporting.get("qmd") if isinstance(supporting.get("qmd"), dict) else {}
    mcporter = supporting.get("mcporter") if isinstance(supporting.get("mcporter"), dict) else {}
    retrieval = memory.get("retrieval_smoke") if isinstance(memory.get("retrieval_smoke"), dict) else {}
    acpx = next(
        (
            item
            for item in openclaw.get("plugins") or []
            if isinstance(item, dict) and str(item.get("id") or "") == "acpx"
        ),
        {},
    )
    hermes = subsystems.get("hermes") if isinstance(subsystems.get("hermes"), dict) else {}
    hermes_run = hermes.get("latest_run") if isinstance(hermes.get("latest_run"), dict) else {}
    lines.extend(["", "## Live Integration Proof", ""])
    lines.append(
        f"- OpenClaw memory: backend(s) `{', '.join(memory.get('backends') or []) or 'unknown'}`; "
        f"health `{'pass' if memory.get('ok') else 'degraded'}`; retrieval smoke `{'pass' if retrieval.get('ok') else 'fail'}` "
        f"with {int(retrieval.get('result_count') or 0)} bounded result(s)."
    )
    lines.append(
        f"- QMD `{qmd.get('version') or 'unknown'}`; MCPorter `{mcporter.get('version') or 'unknown'}`; "
        f"MCPorter config paths `{len(mcporter.get('configured_paths') or [])}`."
    )
    lines.append(f"- ACPX `{acpx.get('version') or 'unknown'}` status `{acpx.get('status') or 'unknown'}`.")
    lines.append(
        f"- Hermes serious-learning evidence: run `{hermes_run.get('id') or 'none'}`; "
        f"local 64K `{'yes' if hermes_run.get('local_64k_lab_requested') else 'no'}`; "
        f"strict JSON `{'pass' if hermes_run.get('strict_json_ok') else 'fail'}`; "
        f"JSON repair `{'used' if hermes_run.get('json_repair_used') else 'not used'}`; "
        f"durable proposal write `{'yes' if hermes_run.get('stored_governance_proposals') else 'no'}`."
    )
    lines.extend(["", "## Configuration Posture", ""])
    configuration_reviews = [
        item for item in snapshot.get("configuration_reviews") or [] if isinstance(item, dict)
    ]
    if not configuration_reviews:
        lines.append("- No configuration-posture review is available yet.")
    for item in configuration_reviews:
        lines.append(
            f"- **{item.get('subsystem')}** — `{item.get('posture')}`; "
            f"{int(item.get('configured_path_count') or 0)} configured path(s) across "
            f"{int(item.get('known_path_count') or 0)} known path(s); "
            f"attention `{', '.join(str(value) for value in item.get('attention_ids') or []) or 'none'}`."
        )
    lines.extend(
        [
            "",
            "Configuration rule: an unset optional schema key is not a defect. Eve changes settings only when an Eve-owned contract, a focused canary, and consequence evidence show that the setting improves her current work.",
        ]
    )
    effective_summary = snapshot.get("effective_configuration_summary") if isinstance(snapshot.get("effective_configuration_summary"), dict) else {}
    effective_counts = effective_summary.get("status_counts") if isinstance(effective_summary.get("status_counts"), dict) else {}
    lines.extend(["", "## Effective Runtime Attestation", ""])
    lines.append(
        f"Verified `{int(effective_summary.get('effective_count') or 0)}` of "
        f"`{int(effective_summary.get('attestation_count') or 0)}` owned contracts as effective or lab-verified. "
        f"Attention contracts: `{int(effective_summary.get('attention_count') or 0)}`. "
        f"States: `{json.dumps(effective_counts, ensure_ascii=True, sort_keys=True)}`."
    )
    for item in snapshot.get("effective_configuration_attestations") or []:
        if not isinstance(item, dict):
            continue
        consequence = item.get("consequence") if isinstance(item.get("consequence"), dict) else {}
        lines.append(
            f"- **[{str(item.get('status') or 'unknown').upper()}]** `{item.get('id')}` — "
            f"consumer `{(item.get('consumer') or {}).get('kind') if isinstance(item.get('consumer'), dict) else 'unknown'}`; "
            f"consequence verified `{'yes' if consequence.get('verified') else 'no'}`; "
            f"owner: {item.get('authority_owner') or 'unknown'}."
        )
        if item.get("blockers"):
            lines.append(f"  - Blockers: {', '.join(str(value) for value in item.get('blockers') or [])}")
    family_summary = snapshot.get("feature_family_review_summary") if isinstance(snapshot.get("feature_family_review_summary"), dict) else {}
    decision_counts = family_summary.get("decision_counts") if isinstance(family_summary.get("decision_counts"), dict) else {}
    lifecycle_counts = (
        family_summary.get("lifecycle_stage_counts")
        if isinstance(family_summary.get("lifecycle_stage_counts"), dict)
        else {}
    )
    lifecycle_review_count = int(
        family_summary.get("lifecycle_review_count")
        or sum(int(value or 0) for value in lifecycle_counts.values())
    )
    lines.extend(["", "## Subsystem Feature Families", ""])
    lines.append(
        f"Reviewed `{int(family_summary.get('review_count') or 0)}` shipped feature families: "
        f"use existing `{int(decision_counts.get('use_existing') or 0)}`, "
        f"configure `{int(decision_counts.get('configure') or 0)}`, "
        f"canary `{int(decision_counts.get('canary') or 0)}`, "
        f"defer `{int(decision_counts.get('defer') or 0)}`, and "
        f"reject `{int(decision_counts.get('reject') or 0)}`."
    )
    if lifecycle_counts:
        lines.append(
            "Lifecycle evidence (discovery is not capability) for "
            f"`{lifecycle_review_count}` instrumented families: "
            + ", ".join(
                f"{stage} `{int(lifecycle_counts.get(stage) or 0)}`"
                for stage in ("unavailable", "discovered", "configured", "enabled", "callable", "verified")
            )
            + "."
        )
    for item in snapshot.get("feature_family_reviews") or []:
        if not isinstance(item, dict):
            continue
        lifecycle = item.get("lifecycle") if isinstance(item.get("lifecycle"), dict) else {}
        lifecycle_text = f" Lifecycle `{lifecycle.get('stage')}`." if lifecycle else ""
        lines.append(
            f"- **[{str(item.get('decision') or 'unknown').upper()}]** `{item.get('id')}` — "
            f"state `{item.get('current_state') or 'unknown'}`.{lifecycle_text} {item.get('rationale') or ''} "
            f"Next: {item.get('configuration_action') or 'No configuration change proposed.'}"
        )
    lines.extend(["", "## Changes Since Prior Check", ""])
    if changes.get("baseline_created"):
        lines.append("- Established the first capability-intelligence baseline.")
    elif not changes.get("material_change"):
        lines.append("- No material version, configuration, feature, release, or health change was detected.")
    else:
        counts = changes.get("counts") if isinstance(changes.get("counts"), dict) else {}
        for key in (
            "version_changes",
            "config_changes",
            "feature_changes",
            "research_feature_changes",
            "health_changes",
            "new_releases",
            "feature_review_changes",
            "feature_family_review_changes",
        ):
            lines.append(f"- {key.replace('_', ' ')}: {int(counts.get(key) or 0)}")
    if changes.get("research_change") and not changes.get("material_change"):
        lines.append("- Research/source surfaces changed, but no installed Eve capability changed.")

    lines.extend(["", "## Feature And Update Adoption Ledger", ""])
    feature_summary = snapshot.get("feature_review_summary") if isinstance(snapshot.get("feature_review_summary"), dict) else {}
    state_counts = feature_summary.get("state_counts") if isinstance(feature_summary.get("state_counts"), dict) else {}
    lines.append(
        f"Visible release reviews: `{int(feature_summary.get('visible_review_count') or 0)}`; "
        f"in use `{int(state_counts.get('in_use') or 0)}`; adoption candidates `{int(feature_summary.get('candidate_count') or 0)}`; "
        f"research only `{int(state_counts.get('research_only') or 0)}`; blocked `{int(state_counts.get('blocked') or 0)}`."
    )
    review_heads = [
        item
        for item in snapshot.get("feature_reviews") or []
        if isinstance(item, dict)
        and item.get("visible_in_current_feed")
        and item.get("state") != "historical"
    ]
    if not review_heads:
        lines.append("")
        lines.append("- No release-head review is available yet.")
    for item in review_heads[:40]:
        lines.extend(
            [
                "",
                f"### [{str(item.get('state') or 'unknown').upper()}] {item.get('repository')} {item.get('target_version')}",
                "",
                f"- Published: `{item.get('published_at') or 'unknown'}`; installed: `{item.get('installed_version') or 'not mapped'}`; component: `{item.get('component_id') or 'research feed'}`.",
                f"- Classification: {item.get('classification_reason') or 'No reason recorded.'}",
                f"- Gate: {item.get('required_gate') or 'Inspect and canary before adoption.'}",
            ]
        )
        bullets = [str(value) for value in item.get("feature_bullets") or []]
        if bullets:
            lines.append("- Release features/changes:")
            for bullet in bullets[:4]:
                lines.append(f"  - {bullet}")
    lines.extend(["", "## Current Optimization Queue", ""])
    opportunities = [item for item in snapshot.get("opportunities") or [] if isinstance(item, dict)]
    if not opportunities:
        lines.append("- No current optimization opportunity is recorded.")
    for item in opportunities:
        lines.append(f"### [{str(item.get('priority') or 'unknown').upper()}] {item.get('id')}")
        lines.append("")
        lines.append(str(item.get("finding") or ""))
        lines.append("")
        lines.append(f"Next verified move: {item.get('recommended_change') or 'Review the evidence.'}")
        lines.append("")
    eve = subsystems.get("eve") if isinstance(subsystems.get("eve"), dict) else {}
    blocked = [
        item
        for item in eve.get("components") or []
        if isinstance(item, dict) and item.get("blocked_latest_version")
    ]
    lines.extend(["## Known Blocked Latests", ""])
    if not blocked:
        lines.append("- No prior canary-rejected package latest is recorded.")
    for item in blocked:
        lines.append(
            f"- `{item.get('id')}` `{item.get('blocked_latest_version')}` — "
            f"{item.get('blocked_version_reason') or 'blocked by prior canary evidence'}"
        )
    lines.append("")
    lines.extend(["## Release Feeds", ""])
    feeds = [item for item in snapshot.get("release_feeds") or [] if isinstance(item, dict)]
    if not feeds:
        lines.append("- Release feeds have not been refreshed yet.")
    for feed in feeds:
        releases = feed.get("releases") if isinstance(feed.get("releases"), list) else []
        latest = releases[0] if releases and isinstance(releases[0], dict) else {}
        lines.append(
            f"- `{feed.get('repository')}` — `{latest.get('tag') or 'unknown'}` published `{latest.get('published_at') or 'unknown'}`."
        )
        for bullet in [str(value) for value in latest.get("feature_bullets") or []][:3]:
            lines.append(f"  - {bullet}")
    lines.extend(
        [
            "",
            "## How Eve Uses This",
            "",
            "- Eve's daemon refreshes local subsystem/configuration evidence hourly.",
            "- Upstream release feeds, component checks, OpenClaw source surfaces, and Hermes inventory refresh every six hours.",
            "- The autonomy snapshot reads current adoption-candidate ids and configuration-attention ids so Eve can choose a bounded follow-up instead of forgetting the release note.",
            "- Material deltas and adoption-state changes enter the event ledger as observations, never as permission grants.",
            "- Any adoption still needs its subsystem-specific dry run, canary, consequence verification, and rollback evidence.",
            "",
        ]
    )
    return "\n".join(lines)
