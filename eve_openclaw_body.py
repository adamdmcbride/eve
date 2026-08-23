#!/usr/bin/env python3

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import eve_store


ROOT = Path(__file__).resolve().parent
APP_DIR = ROOT / ".eve"
RUNTIME_DIR = Path.home() / ".eve_runtime"
RUNTIME_APP_DIR = RUNTIME_DIR / ".eve"

OPENCLAW_BODY_CONTRACTS_PATH = APP_DIR / "openclaw_body_contracts.json"
RUNTIME_OPENCLAW_BODY_CONTRACTS_PATH = RUNTIME_APP_DIR / "openclaw_body_contracts.json"
OPENCLAW_EVIDENCE_EVENTS_PATH = APP_DIR / "openclaw_evidence_events.jsonl"
RUNTIME_OPENCLAW_EVIDENCE_EVENTS_PATH = RUNTIME_APP_DIR / "openclaw_evidence_events.jsonl"
OPENCLAW_CAPABILITY_ADMISSIONS_PATH = APP_DIR / "openclaw_capability_admissions.jsonl"
RUNTIME_OPENCLAW_CAPABILITY_ADMISSIONS_PATH = RUNTIME_APP_DIR / "openclaw_capability_admissions.jsonl"
OPENCLAW_ACTION_ROUTER_EVENTS_PATH = APP_DIR / "openclaw_action_router_events.jsonl"
RUNTIME_OPENCLAW_ACTION_ROUTER_EVENTS_PATH = RUNTIME_APP_DIR / "openclaw_action_router_events.jsonl"
OPENCLAW_ROUTINE_EVENTS_PATH = APP_DIR / "openclaw_routine_events.jsonl"
RUNTIME_OPENCLAW_ROUTINE_EVENTS_PATH = RUNTIME_APP_DIR / "openclaw_routine_events.jsonl"
OPENCLAW_WORKER_EVENTS_PATH = APP_DIR / "openclaw_worker_events.jsonl"
RUNTIME_OPENCLAW_WORKER_EVENTS_PATH = RUNTIME_APP_DIR / "openclaw_worker_events.jsonl"
OPENCLAW_CHANNEL_EVENTS_PATH = APP_DIR / "openclaw_channel_events.jsonl"
RUNTIME_OPENCLAW_CHANNEL_EVENTS_PATH = RUNTIME_APP_DIR / "openclaw_channel_events.jsonl"
DEFAULT_OPENCLAW_STATE_DIR = Path.home() / ".openclaw-eve-repair"
SENSITIVE_HOOK_KEYS = {
    "apikey",
    "authorization",
    "auth",
    "cfg",
    "config",
    "credential",
    "credentials",
    "deps",
    "messages",
    "models",
    "password",
    "prompt",
    "providers",
    "secret",
    "sessionfilecontent",
    "skillssnapshot",
    "systemprompt",
    "token",
}

OPENCLAW_BODY_SUBSTRATE_ID = "openclaw_body_action_nervous_system"
OPENCLAW_BODY_INTEGRATION_LAYERS = [
    "eve_brain",
    "typed_eve_action_contracts",
    "openclaw_body_bus",
    "evidence_bridge",
    "operator_safety_gates",
]
OPENCLAW_BODY_CONTRACT_ORDER = [
    "openclaw_gateway_status",
    "openclaw_sync_context",
    "openclaw_action_router",
    "openclaw_repair_heartbeat",
    "openclaw_task_list",
    "openclaw_hook_event_ingest",
    "openclaw_mcp_conversation_read",
    "openclaw_mcp_message_send",
    "openclaw_capability_model_smoke",
    "openclaw_skill_smoke_test",
    "openclaw_plugin_admission",
]
OPENCLAW_ROUTER_ACTION_ORDER = [
    "status_snapshot",
    "sync_context",
    "activity_ingest",
    "memory_wiki_health",
    "contracts_refresh",
    "admission_audit",
    "repair_diagnose",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_text(value: object, *, fallback: str = "", limit: int = 240) -> str:
    if value is None:
        return fallback
    text = " ".join(str(value).split())
    if not text:
        return fallback
    if limit > 0 and len(text) > limit:
        return text[: max(0, limit - 1)].rstrip() + "..."
    return text


def normalize_text_list(values: object, *, limit: int = 12, item_limit: int = 160) -> List[str]:
    if not isinstance(values, list):
        return []
    normalized: List[str] = []
    seen: set[str] = set()
    for value in values:
        text = normalize_text(value, limit=item_limit)
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
        if len(normalized) >= limit:
            break
    return normalized


def parse_mixed_json(text: str) -> object:
    stripped = text.strip()
    if not stripped:
        return {}
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    for index, character in enumerate(stripped):
        if character not in "{[":
            continue
        try:
            return json.loads(stripped[index:])
        except json.JSONDecodeError:
            continue
    return {"raw": normalize_text(stripped, limit=1200)}


def compact_json_value(value: object, *, max_chars: int = 1600) -> object:
    if isinstance(value, dict):
        compacted: Dict[str, object] = {}
        for key, item in value.items():
            compacted[str(key)] = compact_json_value(item, max_chars=max_chars)
        return compacted
    if isinstance(value, list):
        return [compact_json_value(item, max_chars=max_chars) for item in value]
    if isinstance(value, str):
        return normalize_text(value, limit=max_chars)
    return value


def paths_equivalent(left: Path, right: Path) -> bool:
    try:
        return left.expanduser().resolve(strict=False) == right.expanduser().resolve(strict=False)
    except OSError:
        return str(left.expanduser()) == str(right.expanduser())


def sanitize_hook_value(value: object, *, depth: int = 0, max_list: int = 10) -> object:
    if depth > 5:
        return "[truncated]"
    if isinstance(value, dict):
        sanitized: Dict[str, object] = {}
        for key, item in value.items():
            normalized_key = "".join(character for character in str(key).lower() if character.isalnum())
            if normalized_key in SENSITIVE_HOOK_KEYS or any(sensitive in normalized_key for sensitive in ["token", "secret", "password", "apikey"]):
                sanitized[str(key)] = "[redacted]"
                continue
            sanitized[str(key)] = sanitize_hook_value(item, depth=depth + 1, max_list=max_list)
        return sanitized
    if isinstance(value, list):
        return [sanitize_hook_value(item, depth=depth + 1, max_list=max_list) for item in value[:max_list]]
    if isinstance(value, str):
        return normalize_text(value, limit=500)
    return value


def parsed_json_has_payload(value: object) -> bool:
    if isinstance(value, dict):
        return bool(value) and "raw" not in value
    if isinstance(value, list):
        return True
    return value is not None


def run_openclaw_json_command(args: Sequence[str], *, timeout: int = 20) -> Dict[str, object]:
    command = ["openclaw", "--profile", "eve-repair", *args]
    try:
        result = subprocess.run(
            command,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "ok": False,
            "command": command,
            "returncode": None,
            "error": normalize_text(exc, limit=400),
            "payload": {},
        }
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    payload = parse_mixed_json(stdout)
    if not parsed_json_has_payload(payload) and stderr.strip():
        stderr_payload = parse_mixed_json(stderr)
        if parsed_json_has_payload(stderr_payload):
            payload = stderr_payload
    return {
        "ok": result.returncode == 0,
        "command": command,
        "returncode": result.returncode,
        "stdout_excerpt": normalize_text(stdout, limit=300),
        "stderr_excerpt": normalize_text(stderr, limit=300),
        "payload": compact_json_value(payload),
    }


def read_task_rows_from_sqlite(state_dir: Path, *, limit: int = 25) -> Dict[str, object]:
    db_path = state_dir / "tasks" / "runs.sqlite"
    if not db_path.exists():
        return {
            "ok": False,
            "source": str(db_path),
            "error": "OpenClaw task SQLite store not found.",
            "tasks": [],
        }
    query = """
        SELECT task_id, runtime, task_kind, source_id, requester_session_key, owner_key,
               scope_kind, child_session_key, agent_id, run_id, label, task, status,
               delivery_status, notify_policy, created_at, started_at, ended_at,
               last_event_at, error, progress_summary, terminal_summary, terminal_outcome
        FROM task_runs
        ORDER BY COALESCE(last_event_at, created_at) DESC
        LIMIT ?
    """
    try:
        connection = sqlite3.connect(str(db_path))
        connection.row_factory = sqlite3.Row
        rows = connection.execute(query, (limit,)).fetchall()
    except sqlite3.Error as exc:
        return {
            "ok": False,
            "source": str(db_path),
            "error": normalize_text(exc, limit=400),
            "tasks": [],
        }
    finally:
        try:
            connection.close()  # type: ignore[name-defined]
        except Exception:
            pass
    return {
        "ok": True,
        "source": str(db_path),
        "tasks": [compact_json_value(dict(row), max_chars=400) for row in rows],
    }


def read_session_activity(state_dir: Path, *, limit: int = 8) -> Dict[str, object]:
    agents_dir = state_dir / "agents"
    candidate_agents: List[str] = []
    for preferred in ["eve-repair", "main"]:
        if (agents_dir / preferred / "sessions").exists():
            candidate_agents.append(preferred)
    if agents_dir.exists():
        for agent_dir in sorted(item for item in agents_dir.iterdir() if item.is_dir()):
            if agent_dir.name not in candidate_agents and (agent_dir / "sessions").exists():
                candidate_agents.append(agent_dir.name)

    total_active_sessions = 0
    active_session_summaries: List[Dict[str, object]] = []
    trajectory_paths: List[Path] = []
    for agent_id in candidate_agents:
        sessions_dir = agents_dir / agent_id / "sessions"
        sessions_index = eve_store.load_json_dict(sessions_dir / "sessions.json", default={})
        total_active_sessions += len(sessions_index)
        for session_key, session in sessions_index.items():
            if not isinstance(session, dict):
                continue
            active_session_summaries.append(
                {
                    "agent_id": agent_id,
                    "session_key": normalize_text(session_key, limit=160),
                    "session_id": normalize_text(session.get("sessionId"), limit=120),
                    "status": normalize_text(session.get("status"), limit=80),
                    "model_provider": normalize_text(session.get("modelProvider"), limit=80),
                    "model": normalize_text(session.get("model"), limit=80),
                    "updated_at": session.get("updatedAt"),
                    "session_file": normalize_text(session.get("sessionFile"), limit=260),
                }
            )
        trajectory_paths.extend(sessions_dir.glob("*.trajectory.jsonl"))
    trajectory_paths = sorted(
        trajectory_paths,
        key=lambda item: item.stat().st_mtime if item.exists() else 0,
        reverse=True,
    )[:limit]
    sessions: List[Dict[str, object]] = []
    for path in trajectory_paths:
        records = eve_store.read_jsonl_tail_records(path, 20)
        event_types = normalize_text_list([record.get("type") for record in records], limit=12, item_limit=80)
        latest = records[-1] if records else {}
        sessions.append(
            {
                "agent_id": path.parent.parent.name,
                "session_id": path.name.replace(".trajectory.jsonl", ""),
                "path": str(path),
                "latest_ts": normalize_text(latest.get("ts"), limit=80),
                "latest_type": normalize_text(latest.get("type"), limit=100),
                "event_types": event_types,
                "event_count_sampled": len(records),
            }
        )
    return {
        "ok": True,
        "source": str(agents_dir),
        "agents_checked": candidate_agents,
        "active_session_count": total_active_sessions,
        "active_sessions": active_session_summaries[:limit],
        "recent_trajectories": sessions,
    }


def build_openclaw_activity_events(
    *,
    state_dir: Path = DEFAULT_OPENCLAW_STATE_DIR,
    include_sessions: bool = False,
    limit: int = 25,
    command_timeout: int = 20,
) -> List[Dict[str, object]]:
    created_at = utc_now()
    task_cli = run_openclaw_json_command(["tasks", "list", "--json"], timeout=command_timeout)
    task_db = read_task_rows_from_sqlite(state_dir, limit=limit)
    hooks = run_openclaw_json_command(["hooks", "list", "--json"], timeout=command_timeout)
    mcp = run_openclaw_json_command(["mcp", "list", "--json"], timeout=command_timeout)

    task_payload = {
        "cli": task_cli,
        "sqlite": task_db,
    }
    task_count = 0
    cli_payload = task_cli.get("payload") if isinstance(task_cli.get("payload"), dict) else {}
    if isinstance(cli_payload.get("tasks"), list):
        task_count = len(cli_payload["tasks"])
    if task_count == 0 and isinstance(task_db.get("tasks"), list):
        task_count = len(task_db["tasks"])

    hooks_payload = hooks.get("payload") if isinstance(hooks.get("payload"), dict) else {}
    hook_count = len(hooks_payload.get("hooks") or []) if isinstance(hooks_payload.get("hooks"), list) else 0
    mcp_payload = mcp.get("payload") if isinstance(mcp.get("payload"), dict) else {}
    mcp_count = len(mcp_payload) if isinstance(mcp_payload, dict) else 0

    events: List[Dict[str, object]] = [
        build_openclaw_activity_event(
            event_type="openclaw_task_snapshot",
            created_at=created_at,
            source="openclaw_tasks_cli_and_sqlite",
            status="ready" if task_cli.get("ok") or task_db.get("ok") else "degraded",
            summary=f"OpenClaw task snapshot captured {task_count} task record(s).",
            payload=task_payload,
        ),
        build_openclaw_activity_event(
            event_type="openclaw_hook_inventory",
            created_at=created_at,
            source="openclaw_hooks_cli",
            status="ready" if hooks.get("ok") else "degraded",
            summary=f"OpenClaw hook inventory captured {hook_count} hook(s).",
            payload=hooks,
        ),
        build_openclaw_activity_event(
            event_type="openclaw_mcp_inventory",
            created_at=created_at,
            source="openclaw_mcp_cli",
            status="ready" if mcp.get("ok") else "degraded",
            summary=f"OpenClaw MCP inventory captured {mcp_count} configured entr{'y' if mcp_count == 1 else 'ies'}.",
            payload=mcp,
        ),
    ]
    if include_sessions:
        sessions = read_session_activity(state_dir, limit=min(limit, 12))
        trajectory_count = len(sessions.get("recent_trajectories") or []) if isinstance(sessions.get("recent_trajectories"), list) else 0
        events.append(
            build_openclaw_activity_event(
                event_type="openclaw_session_activity_snapshot",
                created_at=created_at,
                source="openclaw_session_trajectories",
                status="ready" if sessions.get("ok") else "degraded",
                summary=f"OpenClaw session activity snapshot captured {trajectory_count} recent trajectory file(s).",
                payload=sessions,
            )
        )
    return events


def _contract(
    contract_id: str,
    *,
    purpose: str,
    permission_level: str,
    openclaw_surface: List[str],
    input_schema: Dict[str, object],
    output_schema: Dict[str, object],
    verification_command: str,
    rollback: str,
    owning_lane: str,
    safety_gate: str,
    writes: Optional[List[str]] = None,
) -> Dict[str, object]:
    return {
        "id": contract_id,
        "purpose": purpose,
        "permission_level": permission_level,
        "openclaw_surface": openclaw_surface,
        "input_schema": input_schema,
        "output_schema": output_schema,
        "verification_command": verification_command,
        "rollback": rollback,
        "owning_lane": owning_lane,
        "safety_gate": safety_gate,
        "adds_chat_lane": False,
        "canonical_memory_authority": False,
        "writes": writes or [],
    }


def openclaw_body_contract_registry() -> Dict[str, Dict[str, object]]:
    return {
        "openclaw_gateway_status": _contract(
            "openclaw_gateway_status",
            purpose="Read OpenClaw gateway/profile health as Eve body-bus sensor input.",
            permission_level="read_only",
            openclaw_surface=["python3 eve.py openclaw status", "openclaw --profile eve-repair gateway status"],
            input_schema={"type": "object", "properties": {"include_gateway_probe": {"type": "boolean"}}, "additionalProperties": False},
            output_schema={"required": ["gateway_reachable", "summary", "memory_status_severity"], "type": "object"},
            verification_command="python3 eve.py openclaw status",
            rollback="No mutation is performed; discard stale status and re-read live status.",
            owning_lane="observer",
            safety_gate="Loopback-only, read-only status probe.",
            writes=[".eve/openclaw_evidence_events.jsonl"],
        ),
        "openclaw_sync_context": _contract(
            "openclaw_sync_context",
            purpose="Sync Eve runtime status into the OpenClaw repair workspace with provenance.",
            permission_level="operator_safe",
            openclaw_surface=["python3 eve.py openclaw sync"],
            input_schema={"type": "object", "properties": {"append_memory": {"type": "boolean"}}, "additionalProperties": False},
            output_schema={"required": ["ok", "last_sync_at", "sync_health_summary"], "type": "object"},
            verification_command="python3 eve.py openclaw status",
            rollback="Do not revert context files; record degraded artifact writes and rerun only after lock clears.",
            owning_lane="observer",
            safety_gate="Serialized writer lock; no model/provider change; no hosted fallback.",
            writes=["openclaw/context/eve_status.md", "openclaw/context/eve_status.json", ".eve/openclaw_sync_history.jsonl"],
        ),
        "openclaw_action_router": _contract(
            "openclaw_action_router",
            purpose="Route Eve intentions to allowlisted OpenClaw body actions, execute the bounded action, and record evidence.",
            permission_level="mixed_allowlisted",
            openclaw_surface=[
                "python3 eve.py openclaw action --intent <goal>",
                "python3 eve.py openclaw action --action status_snapshot|sync_context|activity_ingest|contracts_refresh|admission_audit|repair_diagnose",
            ],
            input_schema={
                "type": "object",
                "required": ["intent"],
                "properties": {
                    "intent": {"type": "string"},
                    "action": {"type": "string", "enum": list(OPENCLAW_ROUTER_ACTION_ORDER)},
                    "include_sessions": {"type": "boolean"},
                    "dry_run": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
            output_schema={"required": ["ok", "action", "executed", "event_id"], "type": "object"},
            verification_command="python3 eve.py openclaw action --intent 'verify OpenClaw body router' --dry-run --json",
            rollback="Router events are append-only evidence; disable a routed capability by removing it from the allowlist and leaving historical records intact.",
            owning_lane="planner",
            safety_gate="Allowlisted actions only; no installs, deletes, external sends, hosted provider changes, or unreviewed skill/plugin/MCP enablement.",
            writes=[".eve/openclaw_action_router_events.jsonl", ".eve/openclaw_evidence_events.jsonl"],
        ),
        "openclaw_repair_heartbeat": _contract(
            "openclaw_repair_heartbeat",
            purpose="Run one bounded repair or diagnosis turn after a fresh status sync.",
            permission_level="approval_gated",
            openclaw_surface=["python3 eve.py openclaw repair", "python3 eve.py openclaw repair --diagnose-only"],
            input_schema={"type": "object", "properties": {"diagnose_only": {"type": "boolean"}, "message": {"type": "string"}}, "additionalProperties": False},
            output_schema={"required": ["last_repair_summary", "last_repair_issue", "last_repair_next_step"], "type": "object"},
            verification_command="python3 eve.py openclaw status",
            rollback="Stop on destructive/auth-gated ambiguity; preserve repair summary and ask for approval before risky changes.",
            owning_lane="planner",
            safety_gate="One bounded issue; no secrets, deletes, hosted providers, broad model swaps, or unapproved restarts.",
            writes=["openclaw/context/last_repair.md", ".eve/openclaw_status.json"],
        ),
        "openclaw_task_list": _contract(
            "openclaw_task_list",
            purpose="Mirror OpenClaw detached-task state into Eve's evidence model.",
            permission_level="read_only",
            openclaw_surface=["openclaw --profile eve-repair tasks list --json", "openclaw --profile eve-repair tasks audit --json"],
            input_schema={"type": "object", "properties": {"limit": {"type": "integer"}}, "additionalProperties": False},
            output_schema={"required": ["tasks", "issues"], "type": "object"},
            verification_command="openclaw --profile eve-repair tasks audit --json",
            rollback="No mutation is performed; stale task records stay OpenClaw-owned and Eve marks them as evidence only.",
            owning_lane="observer",
            safety_gate="Read-only task ledger; no polling loops for push-driven work.",
            writes=[".eve/openclaw_evidence_events.jsonl"],
        ),
        "openclaw_hook_event_ingest": _contract(
            "openclaw_hook_event_ingest",
            purpose="Normalize OpenClaw gateway/session/tool hook events into Eve evidence.",
            permission_level="operator_safe",
            openclaw_surface=["openclaw --profile eve-repair hooks list", "OpenClaw Gateway hook callbacks"],
            input_schema={"type": "object", "required": ["event_type", "payload"], "additionalProperties": True},
            output_schema={"required": ["event_id", "event_type", "canonical_memory_authority"], "type": "object"},
            verification_command="python3 eve.py openclaw evidence --limit 5",
            rollback="Disable the hook entry and leave already-ingested evidence as attributed historical records.",
            owning_lane="observer",
            safety_gate="Hooks may ingest events but must not perform side effects unless separately admitted.",
            writes=[".eve/openclaw_evidence_events.jsonl"],
        ),
        "openclaw_mcp_conversation_read": _contract(
            "openclaw_mcp_conversation_read",
            purpose="Read routed OpenClaw channel conversations through MCP without sending messages.",
            permission_level="approval_gated",
            openclaw_surface=["openclaw mcp serve", "messages_read", "conversation_get"],
            input_schema={"type": "object", "required": ["conversation_id"], "additionalProperties": False},
            output_schema={"required": ["conversation_id", "messages", "route_metadata"], "type": "object"},
            verification_command="openclaw --profile eve-repair mcp list",
            rollback="Disconnect the MCP bridge; do not persist private content outside explicit evidence records.",
            owning_lane="relationship",
            safety_gate="Requires conversation/data-boundary approval; read does not imply reply permission.",
            writes=[".eve/openclaw_evidence_events.jsonl"],
        ),
        "openclaw_mcp_message_send": _contract(
            "openclaw_mcp_message_send",
            purpose="Send a reply through an existing OpenClaw-routed conversation.",
            permission_level="specific_approval_required",
            openclaw_surface=["openclaw mcp serve", "messages_send"],
            input_schema={"type": "object", "required": ["conversation_id", "message"], "additionalProperties": False},
            output_schema={"required": ["sent", "conversation_id", "delivery_state"], "type": "object"},
            verification_command="python3 eve.py openclaw evidence --limit 5",
            rollback="Cannot unsend; record delivery state and follow up with correction only after explicit approval.",
            owning_lane="relationship",
            safety_gate="External communication requires specific approval and current-route verification.",
            writes=[".eve/action_executions.jsonl", ".eve/openclaw_evidence_events.jsonl"],
        ),
        "openclaw_capability_model_smoke": _contract(
            "openclaw_capability_model_smoke",
            purpose="Run a one-shot OpenClaw local model smoke test and normalize runtime-error text before Eve trusts the result.",
            permission_level="read_only",
            openclaw_surface=["python3 eve.py openclaw model-smoke --model <provider/model> --local"],
            input_schema={
                "type": "object",
                "required": ["model", "prompt"],
                "properties": {
                    "model": {"type": "string"},
                    "prompt": {"type": "string"},
                    "expect_contains": {"type": "string"},
                    "local": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
            output_schema={"required": ["ok", "model", "output_texts", "failure_reasons"], "type": "object"},
            verification_command="python3 eve.py openclaw model-smoke --model llamacpp/eve-fast --json",
            rollback="No model routing is changed; discard failed smoke evidence and use the native Eve model exerciser for promotion decisions.",
            owning_lane="observer",
            safety_gate="Read-only local model probe; does not promote, reconfigure, send externally, or add a chat lane.",
            writes=[".eve/openclaw_evidence_events.jsonl"],
        ),
        "openclaw_skill_smoke_test": _contract(
            "openclaw_skill_smoke_test",
            purpose="Test a candidate OpenClaw skill in a bounded read-only or sandboxed mode before admission.",
            permission_level="approval_gated",
            openclaw_surface=["openclaw skills info <name> --json", "openclaw skills check --json"],
            input_schema={"type": "object", "required": ["skill_id", "source"], "additionalProperties": False},
            output_schema={"required": ["skill_id", "ok", "permissions", "data_boundary"], "type": "object"},
            verification_command="openclaw --profile eve-repair skills check --json",
            rollback="Remove or disable the skill directory/config entry before exposing it to Eve.",
            owning_lane="planner",
            safety_gate="No marketplace/community skill becomes callable without source review and a data-boundary note.",
            writes=[".eve/openclaw_capability_admissions.jsonl"],
        ),
        "openclaw_plugin_admission": _contract(
            "openclaw_plugin_admission",
            purpose="Review and record an OpenClaw plugin/MCP/ACP capability before Eve can use it.",
            permission_level="approval_gated",
            openclaw_surface=["openclaw plugins list", "openclaw plugins install <source>", "openclaw mcp set <id>"],
            input_schema={"type": "object", "required": ["candidate_id", "candidate_type", "source"], "additionalProperties": True},
            output_schema={"required": ["candidate_id", "decision", "permission_level", "rollback"], "type": "object"},
            verification_command="python3 eve.py openclaw admission list --full",
            rollback="Disable plugin/MCP entry, remove installed files if approved by operator, and mark admission revoked.",
            owning_lane="planner",
            safety_gate="Admission record required before enablement; deny list wins; hosted providers stay permission-gated.",
            writes=[".eve/openclaw_capability_admissions.jsonl"],
        ),
    }


def openclaw_body_contracts() -> List[Dict[str, object]]:
    registry = openclaw_body_contract_registry()
    return [dict(registry[contract_id]) for contract_id in OPENCLAW_BODY_CONTRACT_ORDER]


def openclaw_action_router_registry() -> Dict[str, Dict[str, object]]:
    return {
        "status_snapshot": {
            "id": "status_snapshot",
            "purpose": "Collect live OpenClaw gateway, memory, sync, and repair status and record it as Eve evidence.",
            "contract_id": "openclaw_gateway_status",
            "permission_level": "read_only",
            "owning_lane": "observer",
            "verification_command": "python3 eve.py openclaw status",
            "safety_gate": "Read-only status probe; no tool execution beyond gateway/memory health checks.",
            "writes": [".eve/openclaw_status.json", ".eve/openclaw_evidence_events.jsonl"],
        },
        "sync_context": {
            "id": "sync_context",
            "purpose": "Refresh Eve's status artifacts into the OpenClaw workspace, then record the result.",
            "contract_id": "openclaw_sync_context",
            "permission_level": "operator_safe",
            "owning_lane": "observer",
            "verification_command": "python3 eve.py openclaw status",
            "safety_gate": "Serialized context sync only; no memory append unless explicitly requested by the caller.",
            "writes": ["openclaw/context/eve_status*.md", ".eve/openclaw_sync_history.jsonl", ".eve/openclaw_evidence_events.jsonl"],
        },
        "activity_ingest": {
            "id": "activity_ingest",
            "purpose": "Ingest OpenClaw tasks, hooks, MCP inventory, and optional session activity into Eve evidence.",
            "contract_id": "openclaw_task_list",
            "permission_level": "read_only",
            "owning_lane": "observer",
            "verification_command": "python3 eve.py openclaw evidence --ingest-activity --full",
            "safety_gate": "Evidence-only ingest; does not send messages, install plugins, or mutate OpenClaw capability state.",
            "writes": [".eve/openclaw_evidence_events.jsonl"],
        },
        "memory_wiki_health": {
            "id": "memory_wiki_health",
            "purpose": "Check OpenClaw local memory, memory-wiki, and dreaming support health without changing memory authority.",
            "contract_id": "openclaw_action_router",
            "permission_level": "read_only",
            "owning_lane": "observer",
            "verification_command": "openclaw --profile eve-repair memory status --deep --json && openclaw --profile eve-repair wiki status --json",
            "safety_gate": "Read-only memory/wiki status probe; no active transcript indexing, hosted fallback, or memory mutation.",
            "writes": [".eve/openclaw_action_router_events.jsonl", ".eve/openclaw_evidence_events.jsonl"],
        },
        "contracts_refresh": {
            "id": "contracts_refresh",
            "purpose": "Refresh Eve's typed body-bus contract snapshot from current OpenClaw status.",
            "contract_id": "openclaw_action_router",
            "permission_level": "operator_safe",
            "owning_lane": "planner",
            "verification_command": "python3 eve.py openclaw contracts --refresh-status --save --full",
            "safety_gate": "Writes only Eve-side contract snapshots; does not expand OpenClaw authority.",
            "writes": [".eve/openclaw_body_contracts.json"],
        },
        "admission_audit": {
            "id": "admission_audit",
            "purpose": "Inspect admitted/pending OpenClaw skills, plugins, MCP, and capability records before expanding authority.",
            "contract_id": "openclaw_plugin_admission",
            "permission_level": "read_only",
            "owning_lane": "planner",
            "verification_command": "python3 eve.py openclaw admission list --full",
            "safety_gate": "Audit-only; installing, enabling, or approving capability surfaces remains a separate admission action.",
            "writes": [".eve/openclaw_action_router_events.jsonl", ".eve/openclaw_evidence_events.jsonl"],
        },
        "repair_diagnose": {
            "id": "repair_diagnose",
            "purpose": "Run one diagnose-only OpenClaw repair pass through the dedicated eve-repair agent.",
            "contract_id": "openclaw_repair_heartbeat",
            "permission_level": "approval_gated",
            "owning_lane": "planner",
            "verification_command": "python3 eve.py openclaw repair --diagnose-only --json",
            "safety_gate": "Diagnose-only by default; no destructive changes, external sends, installs, or auth edits.",
            "writes": [".eve/openclaw_status.json", "openclaw/context/last_repair.md", ".eve/openclaw_action_router_events.jsonl"],
        },
    }


def openclaw_router_action_ids() -> List[str]:
    return list(OPENCLAW_ROUTER_ACTION_ORDER)


def infer_openclaw_router_action(intent: object) -> str:
    lowered = " ".join(str(intent or "").lower().split())
    if not lowered:
        return "status_snapshot"
    if any(cue in lowered for cue in ("repair", "diagnose", "self-test", "self test", "triage", "fix")):
        return "repair_diagnose"
    if any(cue in lowered for cue in ("admission", "admit", "skill", "plugin", "plugins", "capability", "capabilities", "allowlist", "approve surface")):
        return "admission_audit"
    if any(cue in lowered for cue in ("memory", "wiki", "dream", "dreaming", "semantic search", "retrieval health")):
        return "memory_wiki_health"
    if any(cue in lowered for cue in ("task", "tasks", "hook", "hooks", "mcp", "activity", "what ran", "background work", "session activity")):
        return "activity_ingest"
    if any(cue in lowered for cue in ("sync", "context", "status artifact", "workspace snapshot")):
        return "sync_context"
    if any(cue in lowered for cue in ("contract", "contracts", "body bus", "body-bus", "typed action")):
        return "contracts_refresh"
    return "status_snapshot"


def build_openclaw_action_plan(
    *,
    intent: object,
    requested_action: object = "",
    source: str = "manual",
    include_sessions: bool = False,
) -> Dict[str, object]:
    registry = openclaw_action_router_registry()
    action = normalize_text(requested_action, fallback="", limit=80)
    if not action:
        action = infer_openclaw_router_action(intent)
    if action not in registry:
        raise ValueError(f"Unsupported OpenClaw router action: {action}")
    spec = registry[action]
    return {
        "id": str(uuid.uuid4()),
        "created_at": utc_now(),
        "source": normalize_text(source, fallback="manual", limit=80),
        "intent": normalize_text(intent, fallback=action, limit=500),
        "action": action,
        "purpose": spec["purpose"],
        "contract_id": spec["contract_id"],
        "permission_level": spec["permission_level"],
        "owning_lane": spec["owning_lane"],
        "include_sessions": bool(include_sessions),
        "requires_specific_approval": spec["permission_level"] in {"approval_gated", "specific_approval_required"},
        "safety_gate": spec["safety_gate"],
        "verification_command": spec["verification_command"],
        "writes": list(spec.get("writes") or []),
        "adds_chat_lane": False,
        "canonical_memory_authority": False,
    }


def build_openclaw_body_contract_report(status: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    status = status or {}
    memory_ready = str(status.get("memory_status_severity") or "").lower() in {"ready", "ok"}
    gateway_ready = bool(status.get("gateway_reachable"))
    sync_recovered = "recovered" in str(status.get("sync_health_summary") or "").lower() or bool(status.get("last_sync_ok"))
    return {
        "generated_at": utc_now(),
        "substrate_id": OPENCLAW_BODY_SUBSTRATE_ID,
        "principle": "Eve remains the brain; OpenClaw is the local body bus behind typed action contracts and evidence gates.",
        "integration_layers": list(OPENCLAW_BODY_INTEGRATION_LAYERS),
        "resident_chat_lane_delta": 0,
        "status": {
            "gateway_ready": gateway_ready,
            "memory_ready": memory_ready,
            "sync_recovered": sync_recovered,
            "summary": normalize_text(status.get("summary"), fallback="OpenClaw status not attached.", limit=260),
        },
        "contracts": openclaw_body_contracts(),
    }


def write_contract_report(report: Dict[str, object]) -> Dict[str, object]:
    eve_store.write_json_dict(OPENCLAW_BODY_CONTRACTS_PATH, report, ensure_ascii=True)
    try:
        eve_store.write_json_dict(RUNTIME_OPENCLAW_BODY_CONTRACTS_PATH, report, ensure_ascii=True)
    except OSError:
        pass
    return report


def load_contract_report(*, prefer_runtime: bool = False) -> Dict[str, object]:
    path = RUNTIME_OPENCLAW_BODY_CONTRACTS_PATH if prefer_runtime else OPENCLAW_BODY_CONTRACTS_PATH
    return eve_store.load_json_dict(path, default={})


def build_status_evidence_event(status: Dict[str, object], *, source: str = "openclaw_status") -> Dict[str, object]:
    event_type = "openclaw_status_snapshot"
    return {
        "id": str(uuid.uuid4()),
        "created_at": utc_now(),
        "event_type": event_type,
        "source": normalize_text(source, fallback="openclaw_status", limit=120),
        "substrate_id": OPENCLAW_BODY_SUBSTRATE_ID,
        "canonical_memory_authority": False,
        "body_bus_layer": "openclaw_body_bus",
        "status": "ready" if status.get("gateway_reachable") else "degraded",
        "summary": normalize_text(status.get("summary"), fallback="OpenClaw status snapshot recorded.", limit=300),
        "payload": {
            "gateway_reachable": bool(status.get("gateway_reachable")),
            "memory_status_severity": normalize_text(status.get("memory_status_severity"), fallback="", limit=80),
            "memory_provider": normalize_text(status.get("memory_provider"), fallback="", limit=80),
            "memory_capability_available": bool(status.get("memory_capability_available")),
            "last_sync_at": normalize_text(status.get("last_sync_at"), fallback="", limit=80),
            "sync_health_summary": normalize_text(status.get("sync_health_summary"), fallback="", limit=260),
            "last_repair_at": normalize_text(status.get("last_repair_at"), fallback="", limit=80),
            "last_repair_summary": normalize_text(status.get("last_repair_summary"), fallback="", limit=260),
        },
    }


def build_openclaw_activity_event(
    *,
    event_type: str,
    created_at: str,
    source: str,
    status: str,
    summary: str,
    payload: Dict[str, object],
) -> Dict[str, object]:
    return {
        "id": str(uuid.uuid4()),
        "created_at": created_at,
        "event_type": normalize_text(event_type, fallback="openclaw_activity_snapshot", limit=120),
        "source": normalize_text(source, fallback="openclaw_activity", limit=120),
        "substrate_id": OPENCLAW_BODY_SUBSTRATE_ID,
        "canonical_memory_authority": False,
        "body_bus_layer": "openclaw_body_bus",
        "status": normalize_text(status, fallback="degraded", limit=80),
        "summary": normalize_text(summary, fallback="OpenClaw activity snapshot recorded.", limit=300),
        "payload": compact_json_value(payload),
    }


def build_hook_callback_event(raw_event: Dict[str, object], *, source: str = "openclaw_workspace_hook") -> Dict[str, object]:
    event_type = normalize_text(raw_event.get("type"), fallback="unknown", limit=80)
    action = normalize_text(raw_event.get("action"), fallback="", limit=80)
    session_key = normalize_text(raw_event.get("sessionKey"), fallback="", limit=160)
    timestamp = normalize_text(raw_event.get("timestamp"), fallback=utc_now(), limit=80)
    summary_parts = [event_type]
    if action:
        summary_parts.append(action)
    if session_key:
        summary_parts.append(session_key)
    return {
        "id": str(uuid.uuid4()),
        "created_at": utc_now(),
        "event_type": "openclaw_hook_callback",
        "source": normalize_text(source, fallback="openclaw_workspace_hook", limit=120),
        "substrate_id": OPENCLAW_BODY_SUBSTRATE_ID,
        "canonical_memory_authority": False,
        "body_bus_layer": "openclaw_body_bus",
        "status": "ready",
        "summary": "OpenClaw hook callback observed: " + " / ".join(summary_parts),
        "payload": {
            "hook_type": event_type,
            "hook_action": action,
            "session_key": session_key,
            "timestamp": timestamp,
            "event": sanitize_hook_value(raw_event),
        },
    }


def append_evidence_event(event: Dict[str, object]) -> Dict[str, object]:
    record = dict(event)
    record.setdefault("id", str(uuid.uuid4()))
    record.setdefault("created_at", utc_now())
    record.setdefault("substrate_id", OPENCLAW_BODY_SUBSTRATE_ID)
    record["canonical_memory_authority"] = False
    eve_store.append_jsonl_record(OPENCLAW_EVIDENCE_EVENTS_PATH, record, ensure_ascii=True)
    if not paths_equivalent(OPENCLAW_EVIDENCE_EVENTS_PATH, RUNTIME_OPENCLAW_EVIDENCE_EVENTS_PATH):
        try:
            eve_store.append_jsonl_record(RUNTIME_OPENCLAW_EVIDENCE_EVENTS_PATH, record, ensure_ascii=True)
        except OSError:
            pass
    return record


def build_openclaw_action_router_event(plan: Dict[str, object], result: Dict[str, object]) -> Dict[str, object]:
    action = normalize_text(plan.get("action"), fallback="unknown", limit=80)
    executed = bool(result.get("executed"))
    ok = bool(result.get("ok"))
    status = "ready" if ok else "dry_run" if result.get("dry_run") else "degraded"
    summary = normalize_text(
        result.get("summary"),
        fallback=f"OpenClaw action router handled {action}.",
        limit=300,
    )
    return {
        "id": str(uuid.uuid4()),
        "created_at": utc_now(),
        "event_type": "openclaw_action_router_execution",
        "source": normalize_text(plan.get("source"), fallback="manual", limit=120),
        "substrate_id": OPENCLAW_BODY_SUBSTRATE_ID,
        "canonical_memory_authority": False,
        "body_bus_layer": "typed_eve_action_contracts",
        "action": action,
        "contract_id": normalize_text(plan.get("contract_id"), fallback="", limit=120),
        "permission_level": normalize_text(plan.get("permission_level"), fallback="", limit=80),
        "executed": executed,
        "ok": ok,
        "status": status,
        "summary": summary,
        "plan": compact_json_value(plan),
        "payload": compact_json_value(result),
    }


def append_openclaw_action_router_event(event: Dict[str, object]) -> Dict[str, object]:
    record = dict(event)
    record.setdefault("id", str(uuid.uuid4()))
    record.setdefault("created_at", utc_now())
    record.setdefault("event_type", "openclaw_action_router_execution")
    record.setdefault("substrate_id", OPENCLAW_BODY_SUBSTRATE_ID)
    record["canonical_memory_authority"] = False
    eve_store.append_jsonl_record(OPENCLAW_ACTION_ROUTER_EVENTS_PATH, record, ensure_ascii=True)
    if not paths_equivalent(OPENCLAW_ACTION_ROUTER_EVENTS_PATH, RUNTIME_OPENCLAW_ACTION_ROUTER_EVENTS_PATH):
        try:
            eve_store.append_jsonl_record(RUNTIME_OPENCLAW_ACTION_ROUTER_EVENTS_PATH, record, ensure_ascii=True)
        except OSError:
            pass
    return record


def read_openclaw_action_router_events(*, limit: Optional[int] = None, prefer_runtime: bool = False) -> List[Dict[str, object]]:
    path = RUNTIME_OPENCLAW_ACTION_ROUTER_EVENTS_PATH if prefer_runtime else OPENCLAW_ACTION_ROUTER_EVENTS_PATH
    records = eve_store.read_jsonl_tail_records(path, limit) if limit else eve_store.read_jsonl_records(path)
    records.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return records[:limit] if limit else records


def append_openclaw_routine_event(event: Dict[str, object]) -> Dict[str, object]:
    record = dict(event)
    record.setdefault("id", str(uuid.uuid4()))
    record.setdefault("created_at", utc_now())
    record.setdefault("event_type", "openclaw_routine")
    record.setdefault("substrate_id", OPENCLAW_BODY_SUBSTRATE_ID)
    record["canonical_memory_authority"] = False
    eve_store.append_jsonl_record(OPENCLAW_ROUTINE_EVENTS_PATH, record, ensure_ascii=True)
    if not paths_equivalent(OPENCLAW_ROUTINE_EVENTS_PATH, RUNTIME_OPENCLAW_ROUTINE_EVENTS_PATH):
        try:
            eve_store.append_jsonl_record(RUNTIME_OPENCLAW_ROUTINE_EVENTS_PATH, record, ensure_ascii=True)
        except OSError:
            pass
    return record


def read_openclaw_routine_events(*, limit: Optional[int] = None, prefer_runtime: bool = False) -> List[Dict[str, object]]:
    path = RUNTIME_OPENCLAW_ROUTINE_EVENTS_PATH if prefer_runtime else OPENCLAW_ROUTINE_EVENTS_PATH
    records = eve_store.read_jsonl_tail_records(path, limit) if limit else eve_store.read_jsonl_records(path)
    records.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return records[:limit] if limit else records


def append_openclaw_worker_event(event: Dict[str, object]) -> Dict[str, object]:
    record = dict(event)
    record.setdefault("id", str(uuid.uuid4()))
    record.setdefault("created_at", utc_now())
    record.setdefault("event_type", "openclaw_worker")
    record.setdefault("substrate_id", OPENCLAW_BODY_SUBSTRATE_ID)
    record["canonical_memory_authority"] = False
    eve_store.append_jsonl_record(OPENCLAW_WORKER_EVENTS_PATH, record, ensure_ascii=True)
    if not paths_equivalent(OPENCLAW_WORKER_EVENTS_PATH, RUNTIME_OPENCLAW_WORKER_EVENTS_PATH):
        try:
            eve_store.append_jsonl_record(RUNTIME_OPENCLAW_WORKER_EVENTS_PATH, record, ensure_ascii=True)
        except OSError:
            pass
    return record


def read_openclaw_worker_events(*, limit: Optional[int] = None, prefer_runtime: bool = False) -> List[Dict[str, object]]:
    path = RUNTIME_OPENCLAW_WORKER_EVENTS_PATH if prefer_runtime else OPENCLAW_WORKER_EVENTS_PATH
    records = eve_store.read_jsonl_tail_records(path, limit) if limit else eve_store.read_jsonl_records(path)
    records.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return records[:limit] if limit else records


def append_openclaw_channel_event(event: Dict[str, object]) -> Dict[str, object]:
    record = dict(event)
    record.setdefault("id", str(uuid.uuid4()))
    record.setdefault("created_at", utc_now())
    record.setdefault("event_type", "openclaw_channel_event")
    record.setdefault("substrate_id", OPENCLAW_BODY_SUBSTRATE_ID)
    record["canonical_memory_authority"] = False
    eve_store.append_jsonl_record(OPENCLAW_CHANNEL_EVENTS_PATH, record, ensure_ascii=True)
    if not paths_equivalent(OPENCLAW_CHANNEL_EVENTS_PATH, RUNTIME_OPENCLAW_CHANNEL_EVENTS_PATH):
        try:
            eve_store.append_jsonl_record(RUNTIME_OPENCLAW_CHANNEL_EVENTS_PATH, record, ensure_ascii=True)
        except OSError:
            pass
    return record


def read_openclaw_channel_events(*, limit: Optional[int] = None, prefer_runtime: bool = False) -> List[Dict[str, object]]:
    path = RUNTIME_OPENCLAW_CHANNEL_EVENTS_PATH if prefer_runtime else OPENCLAW_CHANNEL_EVENTS_PATH
    records = eve_store.read_jsonl_tail_records(path, limit) if limit else eve_store.read_jsonl_records(path)
    records.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return records[:limit] if limit else records


def read_evidence_events(*, limit: Optional[int] = None, prefer_runtime: bool = False) -> List[Dict[str, object]]:
    path = RUNTIME_OPENCLAW_EVIDENCE_EVENTS_PATH if prefer_runtime else OPENCLAW_EVIDENCE_EVENTS_PATH
    records = eve_store.read_jsonl_tail_records(path, limit) if limit else eve_store.read_jsonl_records(path)
    records.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return records[:limit] if limit else records


def sanitize_existing_hook_evidence_events(*, paths: Optional[Sequence[Path]] = None) -> Dict[str, object]:
    targets = list(paths or [OPENCLAW_EVIDENCE_EVENTS_PATH, RUNTIME_OPENCLAW_EVIDENCE_EVENTS_PATH])
    sanitized_at = utc_now()
    report: Dict[str, object] = {
        "sanitized_at": sanitized_at,
        "changed_records": 0,
        "checked_records": 0,
        "files": [],
    }
    for path in targets:
        file_report: Dict[str, object] = {
            "path": str(path),
            "exists": path.exists(),
            "checked_records": 0,
            "changed_records": 0,
            "backup_path": "",
        }
        if not path.exists():
            report["files"].append(file_report)
            continue
        records = eve_store.read_jsonl_records(path)
        changed_records: List[Dict[str, object]] = []
        changed = 0
        for record in records:
            file_report["checked_records"] = int(file_report["checked_records"]) + 1
            report["checked_records"] = int(report["checked_records"]) + 1
            if record.get("event_type") != "openclaw_hook_callback":
                changed_records.append(record)
                continue
            payload = record.get("payload")
            if not isinstance(payload, dict) or not isinstance(payload.get("event"), dict):
                changed_records.append(record)
                continue
            sanitized_event = sanitize_hook_value(payload["event"])
            if sanitized_event == payload["event"]:
                changed_records.append(record)
                continue
            new_payload = dict(payload)
            new_payload["event"] = sanitized_event
            new_record = dict(record)
            new_record["payload"] = new_payload
            new_record["redaction_reviewed_at"] = sanitized_at
            new_record["redaction_revision"] = "openclaw_hook_sensitive_context_v2"
            changed_records.append(new_record)
            changed += 1
        if changed:
            backup_path = path.with_name(f"{path.name}.pre_redaction_{sanitized_at.replace(':', '-').replace('+', '-')}.bak")
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup_path)
            eve_store.write_jsonl_records(path, changed_records, ensure_ascii=True)
            file_report["backup_path"] = str(backup_path)
        file_report["changed_records"] = changed
        report["changed_records"] = int(report["changed_records"]) + changed
        report["files"].append(file_report)
    return report


def build_evidence_bridge_report(status: Dict[str, object], *, latest_limit: int = 5, prefer_runtime: bool = False) -> Dict[str, object]:
    latest_events = read_evidence_events(limit=latest_limit, prefer_runtime=prefer_runtime)
    event_counts: Dict[str, int] = {}
    for event in latest_events:
        event_type = str(event.get("event_type") or "unknown")
        event_counts[event_type] = event_counts.get(event_type, 0) + 1
    return {
        "generated_at": utc_now(),
        "substrate_id": OPENCLAW_BODY_SUBSTRATE_ID,
        "bridge": "openclaw_event_evidence_bridge",
        "canonical_memory_authority": False,
        "current_status_event": build_status_evidence_event(status, source="current_status_preview"),
        "latest_event_counts": event_counts,
        "latest_events": latest_events,
        "writes": [str(OPENCLAW_EVIDENCE_EVENTS_PATH)],
    }


def create_admission_record(
    *,
    candidate_id: str,
    candidate_type: str,
    source: str,
    capability: str,
    permission_level: str = "pending_review",
    data_boundary: str = "unknown",
    decision: str = "pending_review",
    verification_command: str = "",
    rollback: str = "",
    notes: str = "",
) -> Dict[str, object]:
    record = {
        "id": str(uuid.uuid4()),
        "created_at": utc_now(),
        "candidate_id": normalize_text(candidate_id, fallback="unknown", limit=160),
        "candidate_type": normalize_text(candidate_type, fallback="unknown", limit=80),
        "source": normalize_text(source, fallback="unknown", limit=260),
        "capability": normalize_text(capability, fallback="unknown", limit=220),
        "permission_level": normalize_text(permission_level, fallback="pending_review", limit=80),
        "data_boundary": normalize_text(data_boundary, fallback="unknown", limit=260),
        "decision": normalize_text(decision, fallback="pending_review", limit=80),
        "verification_command": normalize_text(verification_command, fallback="", limit=260),
        "rollback": normalize_text(rollback, fallback="", limit=260),
        "notes": normalize_text(notes, fallback="", limit=500),
        "enabled_for_eve": decision == "approved",
        "adds_chat_lane": False,
        "canonical_memory_authority": False,
    }
    eve_store.append_jsonl_record(OPENCLAW_CAPABILITY_ADMISSIONS_PATH, record, ensure_ascii=True)
    if not paths_equivalent(OPENCLAW_CAPABILITY_ADMISSIONS_PATH, RUNTIME_OPENCLAW_CAPABILITY_ADMISSIONS_PATH):
        try:
            eve_store.append_jsonl_record(RUNTIME_OPENCLAW_CAPABILITY_ADMISSIONS_PATH, record, ensure_ascii=True)
        except OSError:
            pass
    return record


def read_admission_records(*, limit: Optional[int] = None, prefer_runtime: bool = False) -> List[Dict[str, object]]:
    path = RUNTIME_OPENCLAW_CAPABILITY_ADMISSIONS_PATH if prefer_runtime else OPENCLAW_CAPABILITY_ADMISSIONS_PATH
    records = eve_store.read_jsonl_tail_records(path, limit) if limit else eve_store.read_jsonl_records(path)
    records.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return records[:limit] if limit else records


def format_contract_report(report: Dict[str, object], *, full: bool = False) -> str:
    lines = [
        "OpenClaw body/action contracts",
        f"generated_at: {report.get('generated_at') or 'unknown'}",
        f"principle: {report.get('principle') or 'unknown'}",
        f"resident_chat_lane_delta: {report.get('resident_chat_lane_delta')}",
        "layers: " + " -> ".join(str(item) for item in report.get("integration_layers", [])),
    ]
    status = report.get("status") if isinstance(report.get("status"), dict) else {}
    lines.append(
        "status: "
        f"gateway_ready={'yes' if status.get('gateway_ready') else 'no'}, "
        f"memory_ready={'yes' if status.get('memory_ready') else 'no'}, "
        f"sync_recovered={'yes' if status.get('sync_recovered') else 'no'}"
    )
    for contract in report.get("contracts", []):
        if not isinstance(contract, dict):
            continue
        lines.append(f"- {contract.get('id')}: {contract.get('permission_level')} | owner={contract.get('owning_lane')}")
        lines.append(f"  purpose: {normalize_text(contract.get('purpose'), limit=260)}")
        lines.append(f"  gate: {normalize_text(contract.get('safety_gate'), limit=260)}")
        if full:
            surfaces = contract.get("openclaw_surface") if isinstance(contract.get("openclaw_surface"), list) else []
            lines.append(f"  surfaces: {', '.join(str(item) for item in surfaces)}")
            lines.append(f"  verify: {contract.get('verification_command') or 'unknown'}")
            lines.append(f"  rollback: {normalize_text(contract.get('rollback'), limit=260)}")
    return "\n".join(lines)


def format_evidence_report(report: Dict[str, object], *, full: bool = False) -> str:
    current = report.get("current_status_event") if isinstance(report.get("current_status_event"), dict) else {}
    lines = [
        "OpenClaw evidence bridge",
        f"generated_at: {report.get('generated_at') or 'unknown'}",
        f"canonical_memory_authority: {'yes' if report.get('canonical_memory_authority') else 'no'}",
        f"current_status: {current.get('status') or 'unknown'} - {normalize_text(current.get('summary'), limit=260)}",
    ]
    counts = report.get("latest_event_counts") if isinstance(report.get("latest_event_counts"), dict) else {}
    if counts:
        lines.append("latest_event_counts: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    lines.append("latest_events:")
    events = report.get("latest_events") if isinstance(report.get("latest_events"), list) else []
    if not events:
        lines.append("- none recorded")
    for event in events:
        if not isinstance(event, dict):
            continue
        lines.append(f"- {event.get('created_at')}: {event.get('event_type')} | {normalize_text(event.get('summary'), limit=220)}")
        if full:
            lines.append(f"  source: {event.get('source')}")
            lines.append(f"  payload: {json.dumps(event.get('payload') or {}, ensure_ascii=True, sort_keys=True)}")
    return "\n".join(lines)


def format_openclaw_action_result(result: Dict[str, object], *, full: bool = False) -> str:
    plan = result.get("plan") if isinstance(result.get("plan"), dict) else {}
    event = result.get("router_event") if isinstance(result.get("router_event"), dict) else {}
    lines = [
        "OpenClaw action router",
        f"action: {result.get('action') or plan.get('action') or 'unknown'}",
        f"executed: {'yes' if result.get('executed') else 'no'}",
        f"ok: {'yes' if result.get('ok') else 'no'}",
        f"summary: {normalize_text(result.get('summary'), fallback='none recorded', limit=300)}",
        f"event_id: {event.get('id') or result.get('event_id') or 'none'}",
        f"contract: {plan.get('contract_id') or 'unknown'}",
        f"permission: {plan.get('permission_level') or 'unknown'}",
        f"verify: {plan.get('verification_command') or 'unknown'}",
    ]
    if full:
        lines.append(f"safety_gate: {normalize_text(plan.get('safety_gate'), fallback='none recorded', limit=300)}")
        lines.append(f"writes: {', '.join(str(item) for item in (plan.get('writes') or []))}")
        if result.get("evidence_event_ids"):
            lines.append(f"evidence_event_ids: {', '.join(str(item) for item in result.get('evidence_event_ids') or [])}")
        if result.get("issues"):
            lines.append(f"issues: {json.dumps(result.get('issues'), ensure_ascii=True, sort_keys=True)}")
    return "\n".join(lines)


def format_admission_records(records: Iterable[Dict[str, object]], *, full: bool = False) -> str:
    lines = ["OpenClaw capability admissions"]
    any_record = False
    for record in records:
        any_record = True
        lines.append(
            f"- {record.get('candidate_id')}: {record.get('candidate_type')} | "
            f"decision={record.get('decision')} | permission={record.get('permission_level')}"
        )
        lines.append(f"  capability: {normalize_text(record.get('capability'), limit=220)}")
        if full:
            lines.append(f"  source: {record.get('source')}")
            lines.append(f"  data_boundary: {normalize_text(record.get('data_boundary'), limit=260)}")
            lines.append(f"  verify: {record.get('verification_command') or 'not recorded'}")
            lines.append(f"  rollback: {record.get('rollback') or 'not recorded'}")
            if record.get("notes"):
                lines.append(f"  notes: {normalize_text(record.get('notes'), limit=260)}")
    if not any_record:
        lines.append("- none recorded")
    return "\n".join(lines)
