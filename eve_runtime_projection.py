#!/usr/bin/env python3
"""Read-only runtime status projections for Eve's local API.

This module assembles model-health, model/system activity, and latest-state
read models from existing stores and observations. It does not own caches,
HTTP routes, model calls, lane selection, durable writes, or daemon control.
Those orchestration responsibilities remain in ``eve_web.EveRuntimeService``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict

import eve
from eve_monitor_projection import (
    active_mind_audit_event_to_json,
    activity_lane_to_monitor_json,
    clamp_percent,
    daemon_running_from_state,
    entry_preview,
    human_context_signals_to_monitor_json,
    load_json_file,
    model_call_event_to_monitor_json,
    read_disk_snapshot,
    read_memory_snapshot,
    read_process_table,
    read_recent_jsonl,
    reply_progress_to_json,
    safe_float,
    selected_processes,
    thread_to_json,
)


@dataclass(frozen=True)
class RuntimeProjectionConfig:
    """Composition-owned paths and protocol version for status projection."""

    api_version: int
    model_watchdog_status_path: Path
    model_health_log_path: Path
    runtime_model_watchdog_status_path: Path
    runtime_model_health_log_path: Path


ThreadSummaryReader = Callable[..., list[Dict[str, object]]]
ModelHealthReader = Callable[..., Dict[str, object]]


def build_model_health_payload(
    *,
    config: RuntimeProjectionConfig,
    limit: int = 5,
) -> Dict[str, object]:
    """Project current model residency, probes, lanes, hosts, and checks."""

    status = eve.load_model_watchdog_status(prefer_runtime=True) or load_json_file(
        config.model_watchdog_status_path
    )
    health_log_path = (
        config.runtime_model_health_log_path
        if config.runtime_model_health_log_path.exists()
        else config.model_health_log_path
    )
    recent = read_recent_jsonl(health_log_path, limit=limit)
    eve_config = eve.load_config()
    probes = status.get("probes") if isinstance(status.get("probes"), dict) else {}
    loaded_models = status.get("loaded_models") if isinstance(status.get("loaded_models"), list) else []
    residency = status.get("residency") if isinstance(status.get("residency"), dict) else {}
    actions = status.get("actions") if isinstance(status.get("actions"), list) else []
    preferred_fast = str(status.get("preferred_fast_model") or "")
    preferred_deep = str(status.get("preferred_deep_model") or "")
    effective_fast = str(status.get("effective_fast_model") or preferred_fast)
    effective_deep = str(status.get("effective_deep_model") or preferred_deep)
    effective_fallback = str(status.get("effective_fallback_model") or effective_deep or preferred_deep)
    fast_probe = probes.get(preferred_fast) if isinstance(probes.get(preferred_fast), dict) else {}
    deep_probe = probes.get(preferred_deep) if isinstance(probes.get(preferred_deep), dict) else {}
    lane_records = eve.model_lane_records(eve_config, watchdog_status=status)
    host_records = eve.model_host_records(eve_config, watchdog_status=status)
    summary_parts = [
        f"Fast {effective_fast or 'unknown'}",
        f"Deep {effective_deep or 'unknown'}",
        eve.model_lanes_summary(lane_records),
    ]
    return {
        "updated_at": status.get("timestamp"),
        "preferred_fast_model": preferred_fast,
        "preferred_deep_model": preferred_deep,
        "effective_fast_model": effective_fast,
        "effective_deep_model": effective_deep,
        "effective_fallback_model": effective_fallback,
        "summary": " · ".join(part for part in summary_parts if part),
        "residency": {
            "preferred_fast_loaded": bool(residency.get("preferred_fast_loaded")),
            "preferred_deep_loaded": bool(residency.get("preferred_deep_loaded")),
            "both_preferred_loaded": bool(residency.get("both_preferred_loaded")),
        },
        "loaded_models": [
            {
                "name": item.get("name"),
                "context_length": item.get("context_length"),
                "size_vram": item.get("size_vram"),
                "expires_at": item.get("expires_at"),
            }
            for item in loaded_models
            if isinstance(item, dict)
        ],
        "probes": {
            "fast": fast_probe,
            "deep": deep_probe,
        },
        "lanes": lane_records,
        "hosts": host_records,
        "recent_actions": [str(item) for item in actions[:5]],
        "recent_checks": recent,
    }


def build_activity_payload(*, model_health: Dict[str, object]) -> Dict[str, object]:
    """Project bounded model activity and current local resource observations."""

    lanes = model_health.get("lanes") if isinstance(model_health.get("lanes"), list) else []
    active_store = eve.load_active_model_calls(prefer_runtime=True)
    active_calls = active_store.get("calls") if isinstance(active_store.get("calls"), list) else []
    recent_events = eve.read_perf_events(limit=18, since_minutes=180, category="model_call")
    recent_calls = [
        model_call_event_to_monitor_json(item)
        for item in reversed(recent_events)
        if isinstance(item, dict)
    ]
    activity_lanes = [
        activity_lane_to_monitor_json(item, active_calls, recent_calls)
        for item in lanes
        if isinstance(item, dict)
    ]

    processes = read_process_table()
    cpu_count = max(1, os.cpu_count() or 1)
    total_process_cpu = sum(safe_float(item.get("cpu_percent")) for item in processes)
    cpu_percent = clamp_percent(total_process_cpu / cpu_count)
    load_average = [round(float(item), 2) for item in os.getloadavg()] if hasattr(os, "getloadavg") else []
    memory = read_memory_snapshot()
    disk = read_disk_snapshot()
    top_processes = selected_processes(processes)
    active_count = len(active_calls)
    summary = (
        f"{active_count} model call{'s' if active_count != 1 else ''} running"
        if active_count
        else "No active model calls"
    )
    summary = f"{summary} · CPU {cpu_percent:.0f}% · memory {safe_float(memory.get('used_percent')):.0f}%"

    return {
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "models": {
            "summary": summary,
            "active_calls": active_calls,
            "recent_calls": recent_calls,
            "lanes": activity_lanes,
        },
        "system": {
            "cpu_percent": cpu_percent,
            "cpu_count": cpu_count,
            "load_average": load_average,
            "memory": memory,
            "disk": disk,
            "processes": top_processes,
            "process_count": len(processes),
        },
    }


def build_latest_state(
    *,
    config: RuntimeProjectionConfig,
    ordered_thread_summaries: ThreadSummaryReader,
    model_health_payload: ModelHealthReader,
) -> Dict[str, object]:
    """Assemble the versioned status read model without owning refresh policy."""

    eve_config = eve.load_config()
    state = eve.load_state()
    human_context = eve.load_human_context()
    active_mind = eve.load_active_mind(prefer_runtime=True)
    active_mind_audit = eve.read_active_mind_audit_log(limit=20, prefer_runtime=True)
    ambient_thought = eve.load_ambient_thought(prefer_runtime=True)
    evaluations = eve.read_evaluations(limit=40, since_days=30)
    outcomes = eve.read_outcomes(limit=40, since_days=30)
    scorecard = eve.summarize_scorecard(evaluations)
    outcome_summary = eve.summarize_outcomes(outcomes)
    failure_clusters = eve.read_failure_clusters(limit=10, since_days=60)
    unread = eve.read_messages(recipient="user", status="unread")
    threads = ordered_thread_summaries(limit=24)
    proposals = eve.read_proposals(limit=10)
    governance = eve.governance_status_payload(limit=10, prefer_runtime=True)
    reflections = eve.read_entries_by_kind("reflection", limit=5)
    thoughts = eve.read_entries_by_kind("thought", limit=6)
    waiting_threads = [item for item in threads if item.get("status") == "awaiting_user"]
    response_due_threads = [item for item in threads if eve.thread_summary_response_due_count(item) > 0]
    response_due_messages = sum(eve.thread_summary_response_due_count(item) for item in response_due_threads)
    outbound_unseen_messages = sum(eve.thread_summary_outbound_unread_count(item) for item in threads)
    synthetic_continuity_messages = sum(eve.thread_summary_synthetic_continuity_count(item) for item in threads)
    active_threads = [item for item in threads if item.get("status") != "archived"]
    model_health = model_health_payload(limit=5)
    active_reply = eve.latest_reply_progress(active_only=True)
    return {
        "api_version": config.api_version,
        "config": eve_config,
        "state": state,
        "counts": {
            "journal_entries": len(eve.read_entries()),
            "thoughts": len(eve.read_entries_by_kind("thought")),
            "tensions": len(eve.read_tensions()),
            "experiments": len(eve.read_experiments()),
            "proposals": len(eve.read_proposals()),
            "governance_proposals": governance.get("proposal_count", 0),
            "messages": len(eve.read_messages()),
            "evaluations": len(eve.read_evaluations()),
            "outcomes": len(eve.read_outcomes()),
            "failure_clusters": len(eve.read_failure_clusters()),
            "threads": len(threads),
            "active_threads": len(active_threads),
            "waiting_threads": len(waiting_threads),
            "response_due_threads": len(response_due_threads),
            "response_due_messages": response_due_messages,
            "outbound_unseen_messages": outbound_unseen_messages,
            "synthetic_continuity_messages": synthetic_continuity_messages,
            "unread_messages": len(unread),
        },
        "daemon": {
            "launch_agent_exists": eve.LAUNCH_AGENT_PATH.exists(),
            "runtime_dir": str(eve.RUNTIME_DIR),
            "running": daemon_running_from_state(state),
            "awake": daemon_running_from_state(state) and bool(state.get("current_focus")),
        },
        "active_mind": active_mind,
        "active_mind_audit": [active_mind_audit_event_to_json(item) for item in active_mind_audit],
        "ambient_thought": ambient_thought,
        "active_reply": reply_progress_to_json(active_reply),
        "model_health": model_health,
        "governance": {
            "schema_version": governance.get("schema_version"),
            "generated_at": governance.get("generated_at"),
            "proposal_count": governance.get("proposal_count"),
            "decision_counts": governance.get("decision_counts"),
            "type_counts": governance.get("type_counts"),
            "approval_counts": governance.get("approval_counts"),
            "canary_counts": governance.get("canary_counts"),
            "application_counts": governance.get("application_counts"),
            "watcher_status": governance.get("watcher_status"),
            "watcher_warning_count": governance.get("watcher_warning_count"),
            "blocking_warning_count": governance.get("blocking_warning_count"),
        },
        "human_context": human_context,
        "human_context_signals": human_context_signals_to_monitor_json(human_context),
        "feedback": {
            "scorecard": scorecard,
            "outcomes": outcome_summary,
            "failure_clusters": [
                {
                    "id": item["id"],
                    "title": item.get("title"),
                    "status": item.get("status"),
                    "summary": item.get("summary"),
                    "repair": item.get("exact_repair"),
                }
                for item in failure_clusters
            ],
        },
        "thread_attention": [thread_to_json(item) for item in threads[:8]],
        "latest_reflections": [
            {
                "id": item["id"],
                "timestamp": item["timestamp"],
                "preview": entry_preview(item),
            }
            for item in reflections
        ],
        "latest_thoughts": [
            {
                "id": item["id"],
                "timestamp": item["timestamp"],
                "preview": entry_preview(item),
            }
            for item in thoughts
        ],
        "latest_proposals": [
            {
                "id": item["id"],
                "created_at": item["created_at"],
                "title": item["title"],
                "status": item["status"],
                "summary": item["summary"],
            }
            for item in proposals
        ],
    }
