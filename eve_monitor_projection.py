"""Read-only monitor projections and local resource observations for Eve.

The functions here turn existing records into bounded UI payloads and observe
local process, memory, and disk state. They do not select lanes, call models,
write durable state, or grant action authority. ``eve_web`` retains service and
HTTP orchestration and re-exports these names for compatibility.
"""

from __future__ import annotations

import math
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Optional

import eve
import eve_store


ROOT = Path(__file__).resolve().parent


def text_preview(value: object, length: int = 280) -> str:
    return " ".join(str(value or "").split())[:length]


def entry_preview(entry: Dict[str, object], length: int = 280) -> str:
    return text_preview(entry.get("text", ""), length)


def message_preview(message: Dict[str, object], length: int = 240) -> str:
    return text_preview(message.get("body", ""), length)


def reply_stream_packets_for_message(message: Dict[str, object]) -> list[Dict[str, object]]:
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    turn_id = str(metadata.get("stream_turn_id") or "").strip()
    if not turn_id:
        return []
    records = eve.read_jsonl_records(eve.THOUGHT_STREAMS_PATH)
    packets: list[Dict[str, object]] = []
    for item in records:
        if not isinstance(item, dict) or str(item.get("turn_id") or "") != turn_id:
            continue
        packets.append(
            {
                "id": item.get("id"),
                "timestamp": item.get("timestamp"),
                "turn_id": item.get("turn_id"),
                "stream": item.get("stream"),
                "packet": item.get("packet") if isinstance(item.get("packet"), dict) else {},
                "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
            }
        )
    return packets


def reply_turn_replay_to_monitor_json(record: Dict[str, object]) -> Dict[str, object]:
    semantic = record.get("semantic_judgment") if isinstance(record.get("semantic_judgment"), dict) else {}
    contract = record.get("turn_contract") if isinstance(record.get("turn_contract"), dict) else {}
    council = record.get("reply_council") if isinstance(record.get("reply_council"), dict) else {}
    durable_followup = (
        record.get("durable_followup")
        if isinstance(record.get("durable_followup"), dict)
        else {}
    )
    return {
        "id": record.get("id"),
        "created_at": record.get("created_at"),
        "thread_id": record.get("thread_id"),
        "source_message_id": record.get("source_message_id"),
        "reply_message_id": record.get("reply_message_id"),
        "model": record.get("model"),
        "intent": contract.get("intent") or "",
        "current_topic": contract.get("current_topic") or "",
        "episode_boundary": bool(contract.get("episode_boundary")),
        "semantic_ok": bool(semantic.get("ok", True)),
        "semantic_issues": semantic.get("issues") if isinstance(semantic.get("issues"), list) else [],
        "quality_issues": record.get("quality_issues") if isinstance(record.get("quality_issues"), list) else [],
        "active_lanes": council.get("active_lanes") if isinstance(council.get("active_lanes"), list) else [],
        "lanes": [
            {
                "lane": lane.get("lane"),
                "stance": lane.get("stance"),
                "pressure": lane.get("pressure"),
                "threshold": lane.get("threshold"),
                "model": lane.get("model"),
                "reasons": lane.get("reasons") if isinstance(lane.get("reasons"), list) else [],
                "learning_adjustment": lane.get("learning_adjustment", 0),
                "quarantined": bool(lane.get("quarantined")),
                "quarantined_until": lane.get("quarantined_until") or "",
            }
            for lane in council.get("lanes") or []
            if isinstance(lane, dict)
        ],
        "previous_topic": contract.get("previous_topic") or "",
        "short_followup": bool(contract.get("short_followup")),
        "forbidden_stale_topics": contract.get("forbidden_stale_topics")
        if isinstance(contract.get("forbidden_stale_topics"), list)
        else [],
        "stream_turn_id": record.get("stream_turn_id") or "",
        "action_claim_grounding_applied": bool(record.get("action_claim_grounding_applied")),
        "rewrite_applied": bool(record.get("rewrite_applied")),
        "fallback_used": bool(record.get("fallback_used")),
        "durable_followup": {
            "id": durable_followup.get("id") or "",
            "status": durable_followup.get("status") or "",
            "action": durable_followup.get("action") or "",
            "due_at": durable_followup.get("due_at") or "",
            "commitment_id": durable_followup.get("commitment_id") or "",
            "action_execution_id": durable_followup.get("action_execution_id") or "",
            "action_result_ok": durable_followup.get("action_result_ok"),
            "delivery_message_id": durable_followup.get("delivery_message_id") or "",
            "worker_cycle_id": durable_followup.get("worker_cycle_id") or "",
            "completed_cycle_id": durable_followup.get("completed_cycle_id") or "",
            "failure_reason": text_preview(durable_followup.get("failure_reason") or "", 220),
        },
        "inbound_preview": text_preview(record.get("inbound_preview") or "", 180),
        "reply_preview": text_preview(record.get("reply_preview") or "", 220),
    }


def reply_council_turn_to_monitor_json(record: Dict[str, object]) -> Dict[str, object]:
    repair = record.get("repair_signals") if isinstance(record.get("repair_signals"), dict) else {}
    return {
        "id": record.get("id"),
        "created_at": record.get("created_at"),
        "thread_id": record.get("thread_id"),
        "source_message_id": record.get("source_message_id"),
        "reply_message_id": record.get("reply_message_id"),
        "reply_turn_replay_id": record.get("reply_turn_replay_id") or "",
        "intent": record.get("intent") or "",
        "current_topic": record.get("current_topic") or "",
        "short_followup": bool(record.get("short_followup")),
        "episode_boundary": bool(record.get("episode_boundary")),
        "used_model": record.get("used_model") or "",
        "stream_reply_used": bool(record.get("stream_reply_used")),
        "stream_turn_id": record.get("stream_turn_id") or "",
        "selected_stream_lanes": record.get("selected_stream_lanes")
        if isinstance(record.get("selected_stream_lanes"), list)
        else [],
        "synthesis_model": record.get("synthesis_model") or "",
        "active_lanes": record.get("active_lanes") if isinstance(record.get("active_lanes"), list) else [],
        "abstained_lanes": record.get("abstained_lanes") if isinstance(record.get("abstained_lanes"), list) else [],
        "deferred_lanes": record.get("deferred_lanes") if isinstance(record.get("deferred_lanes"), list) else [],
        "reason": record.get("reason") or "",
        "lanes": [
            {
                "lane": lane.get("lane"),
                "model": lane.get("model"),
                "pressure": lane.get("pressure"),
                "threshold": lane.get("threshold"),
                "stance": lane.get("stance"),
                "selected": bool(lane.get("selected")),
                "reasons": lane.get("reasons") if isinstance(lane.get("reasons"), list) else [],
                "quarantined": bool(lane.get("quarantined")),
            }
            for lane in record.get("lanes") or []
            if isinstance(lane, dict)
        ],
        "needed_repair": bool(record.get("needed_repair")),
        "repair_signals": {
            "quality_issues": repair.get("quality_issues") if isinstance(repair.get("quality_issues"), list) else [],
            "semantic_issues": repair.get("semantic_issues") if isinstance(repair.get("semantic_issues"), list) else [],
            "rewrite_applied": bool(repair.get("rewrite_applied")),
            "action_claim_grounding_applied": bool(repair.get("action_claim_grounding_applied")),
            "fallback_used": bool(repair.get("fallback_used")),
            "stream_errors": repair.get("stream_errors") if isinstance(repair.get("stream_errors"), list) else [],
        },
        "inbound_preview": text_preview(record.get("inbound_preview") or "", 180),
        "reply_preview": text_preview(record.get("reply_preview") or "", 220),
    }


def conversation_spine_turn_to_monitor_json(record: Dict[str, object]) -> Dict[str, object]:
    return {
        "id": record.get("id"),
        "timestamp": record.get("timestamp") or record.get("created_at"),
        "created_at": record.get("created_at"),
        "trace_id": record.get("trace_id") or "",
        "thread_id": record.get("thread_id") or "",
        "message_id": record.get("message_id") or "",
        "reply_to": record.get("reply_to") or "",
        "role": record.get("role") or "",
        "direction": record.get("direction") or "",
        "sender": record.get("sender") or "",
        "recipient": record.get("recipient") or "",
        "kind": record.get("kind") or "",
        "subject": record.get("subject") or "",
        "body_preview": text_preview(record.get("body_preview") or record.get("body") or "", 260),
        "source": record.get("source") or "",
        "source_ledger": record.get("source_ledger") or "",
        "source_message_id": record.get("source_message_id") or "",
        "reply_turn_replay_id": record.get("reply_turn_replay_id") or "",
        "reply_council_turn_id": record.get("reply_council_turn_id") or "",
        "synthetic": bool(record.get("synthetic")),
        "conversation_visible": bool(record.get("conversation_visible")),
        "privacy_tier": record.get("privacy_tier") or "",
        "model": record.get("model") or "",
        "runtime": record.get("runtime") or "",
    }


def reply_council_turn_for_message(message: Dict[str, object]) -> Optional[Dict[str, object]]:
    if str(message.get("sender") or "").lower() != "eve":
        return None
    message_id = str(message.get("id") or "").strip()
    if not message_id:
        return None
    records = eve.read_reply_council_turns(
        limit=1,
        reply_message_id=message_id,
        prefer_runtime=True,
    )
    if not records:
        return None
    return reply_council_turn_to_monitor_json(records[0])


def daemon_running_from_state(state: Dict[str, object]) -> bool:
    if eve.daemon_runtime_running():
        return True
    last_loop = eve.parse_iso_datetime(state.get("last_loop_at"))
    if last_loop is None:
        return False
    return datetime.now(timezone.utc) - last_loop < timedelta(minutes=10)


def load_json_file(path: Path) -> Dict[str, object]:
    return eve_store.load_json_dict(path, default={})


def read_recent_jsonl(path: Path, limit: int = 5) -> list[Dict[str, object]]:
    return eve_store.read_jsonl_tail_records(path, limit)




def thread_to_json(thread: Dict[str, object]) -> Dict[str, object]:
    return {
        "thread_id": thread["thread_id"],
        "subject": thread["subject"],
        "latest_timestamp": thread["latest_timestamp"],
        "latest_preview": thread["latest_preview"],
        "latest_sender": thread["latest_sender"],
        "latest_message_id": thread["latest_message_id"],
        "message_count": thread["message_count"],
        "unread_count": thread["unread_count"],
        "outbound_unread_count": thread.get("outbound_unread_count", thread.get("unread_count", 0)),
        "inbound_pending_count": thread.get("inbound_pending_count", 0),
        "response_due_count": thread.get("response_due_count", 0),
        "synthetic_continuity_count": thread.get("synthetic_continuity_count", 0),
        "status": thread["status"],
        "attention_score": thread["attention_score"],
        "participants": thread.get("participants", []),
        "agent_participants": thread.get("agent_participants", []),
        "audience": thread.get("audience", "user"),
    }


def reply_progress_to_json(progress: Optional[Dict[str, object]]) -> Optional[Dict[str, object]]:
    if not progress:
        return None
    notes = progress.get("notes") if isinstance(progress.get("notes"), list) else []
    return {
        "id": progress.get("id"),
        "client_request_id": progress.get("client_request_id"),
        "thread_id": progress.get("thread_id"),
        "source_message_id": progress.get("source_message_id"),
        "recipient": progress.get("recipient"),
        "counterpart_label": progress.get("counterpart_label"),
        "status": progress.get("status"),
        "phase": progress.get("phase"),
        "title": progress.get("title"),
        "detail": progress.get("detail"),
        "step": progress.get("step"),
        "total_steps": progress.get("total_steps"),
        "started_at": progress.get("started_at"),
        "updated_at": progress.get("updated_at"),
        "finished_at": progress.get("finished_at"),
        "requested_model": progress.get("requested_model"),
        "current_model": progress.get("current_model"),
        "fallback_model": progress.get("fallback_model"),
        "reply_message_id": progress.get("reply_message_id"),
        "notes": [
            {
                "id": item.get("id"),
                "timestamp": item.get("timestamp"),
                "phase": item.get("phase"),
                "kind": item.get("kind"),
                "title": item.get("title"),
                "detail": item.get("detail"),
            }
            for item in notes
            if isinstance(item, dict)
        ],
    }


def message_to_json(message: Dict[str, object]) -> Dict[str, object]:
    return {
        "id": message["id"],
        "timestamp": message["timestamp"],
        "updated_at": message.get("updated_at"),
        "thread_id": message["thread_id"],
        "sender": message["sender"],
        "recipient": message["recipient"],
        "subject": message["subject"],
        "body": message["body"],
        "kind": message["kind"],
        "status": message["status"],
        "reply_to": message.get("reply_to"),
        "preview": message_preview(message),
        "metadata": message.get("metadata") if isinstance(message.get("metadata"), dict) else {},
        "stream_packets": reply_stream_packets_for_message(message),
        "reply_council_turn": reply_council_turn_for_message(message),
    }


def proposal_to_json(proposal: Dict[str, object]) -> Dict[str, object]:
    return {
        "id": proposal["id"],
        "created_at": proposal["created_at"],
        "updated_at": proposal.get("updated_at"),
        "title": proposal["title"],
        "summary": proposal["summary"],
        "body": proposal["body"],
        "status": proposal["status"],
        "source": proposal["source"],
    }


def governance_to_monitor_json(governance: Dict[str, object]) -> Dict[str, object]:
    watchers = governance.get("watchers") if isinstance(governance.get("watchers"), dict) else {}
    watcher_rows = watchers.get("watchers") if isinstance(watchers.get("watchers"), list) else []
    return {
        "schema_version": governance.get("schema_version"),
        "generated_at": governance.get("generated_at"),
        "proposal_count": governance.get("proposal_count") or 0,
        "decision_counts": governance.get("decision_counts") if isinstance(governance.get("decision_counts"), dict) else {},
        "type_counts": governance.get("type_counts") if isinstance(governance.get("type_counts"), dict) else {},
        "approval_counts": governance.get("approval_counts") if isinstance(governance.get("approval_counts"), dict) else {},
        "canary_counts": governance.get("canary_counts") if isinstance(governance.get("canary_counts"), dict) else {},
        "application_counts": governance.get("application_counts") if isinstance(governance.get("application_counts"), dict) else {},
        "watcher_status": governance.get("watcher_status"),
        "watcher_warning_count": governance.get("watcher_warning_count") or 0,
        "blocking_warning_count": governance.get("blocking_warning_count") or 0,
        "watchers": [
            {
                "id": item.get("id") or "",
                "title": item.get("title") or "",
                "status": item.get("status") or "",
                "max_severity": item.get("max_severity") or 0,
                "warning_count": item.get("warning_count") or 0,
            }
            for item in watcher_rows
            if isinstance(item, dict)
        ],
    }


def _monitor_rank_summary(record: Dict[str, object]) -> Dict[str, object]:
    rank = record.get("rank") if isinstance(record.get("rank"), dict) else {}
    return {
        "label": rank.get("label"),
        "value": rank.get("value"),
        "average_score": rank.get("average_score"),
        "minimum_score": rank.get("minimum_score"),
    }


def _monitor_fitness_checks(checks: object, *, limit: int = 5) -> list[Dict[str, object]]:
    if not isinstance(checks, list):
        return []
    rows: list[Dict[str, object]] = []
    for item in checks:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").lower()
        if status == "passed":
            continue
        rows.append(
            {
                "test_id": item.get("test_id"),
                "layer": item.get("layer"),
                "title": item.get("title"),
                "status": item.get("status"),
                "score": item.get("score"),
                "next_action": item.get("next_action"),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _monitor_long_run_metrics(metrics: object, *, limit: int = 6) -> list[Dict[str, object]]:
    if not isinstance(metrics, list):
        return []
    rows: list[Dict[str, object]] = []
    for item in metrics[:limit]:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "name": item.get("name"),
                "status": item.get("status"),
                "score": item.get("score"),
                "issue": item.get("issue"),
                "next_action": item.get("next_action"),
            }
        )
    return rows


def _monitor_priority_rows(report: Dict[str, object], *, limit: int = 7) -> list[Dict[str, object]]:
    priorities = report.get("priority_queue") if isinstance(report.get("priority_queue"), list) else []
    rows: list[Dict[str, object]] = []
    for item in priorities[:limit]:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "priority": f"P{item.get('priority')}" if item.get("priority") is not None else None,
                "title": item.get("title"),
                "status": item.get("status"),
                "next_action": item.get("next_action"),
            }
        )
    return rows


def _monitor_first_priority(report: Dict[str, object]) -> Optional[str]:
    item = report.get("recommended_first_priority")
    if isinstance(item, dict):
        priority = item.get("priority")
        prefix = f"P{priority}" if priority is not None else "Priority"
        title = item.get("title") or item.get("id") or "roadmap item"
        status = item.get("status")
        return f"{prefix} {title}" + (f" ({status})" if status else "")
    if item:
        return str(item)
    return None


def fitness_to_monitor_json() -> Dict[str, object]:
    whole_system, whole_path = eve.read_whole_system_json_artifact(
        eve.WHOLE_SYSTEM_LATEST_EVAL_PATH,
        prefer_runtime=True,
    )
    long_run, long_run_path = eve.read_whole_system_json_artifact(
        eve.LONG_RUN_LATEST_EVAL_PATH,
        prefer_runtime=True,
    )
    manual_probe, manual_probe_path = eve.read_whole_system_json_artifact(
        eve.MANUAL_PROBE_LATEST_PATH,
        prefer_runtime=True,
    )
    try:
        roadmap = eve.build_roadmap_eval_report(prefer_runtime=True)
    except Exception as exc:
        roadmap = {"status": "unavailable", "error": str(exc)}
    long_summary = long_run.get("summary") if isinstance(long_run.get("summary"), dict) else {}
    whole_system_summary = roadmap.get("whole_system") if isinstance(roadmap.get("whole_system"), dict) else {}
    backlog = roadmap.get("backlog") if isinstance(roadmap.get("backlog"), dict) else {}
    return {
        "whole_system": {
            "status": whole_system.get("status"),
            "passed": bool(whole_system.get("passed")),
            "average_score": whole_system.get("average_score"),
            "check_count": whole_system.get("check_count"),
            "failing_check_count": whole_system.get("failing_check_count"),
            "missing_component_counts": whole_system.get("missing_component_counts")
            if isinstance(whole_system.get("missing_component_counts"), dict)
            else {},
            "finished_at": whole_system.get("finished_at"),
            "artifact_path": whole_path,
            "failing_checks": _monitor_fitness_checks(whole_system.get("checks")),
        },
        "long_run": {
            "status": long_run.get("status"),
            "passed": bool(long_run.get("passed")),
            "evaluated_at": long_run.get("evaluated_at"),
            "window_minutes": long_run.get("window_minutes"),
            "rank": _monitor_rank_summary(long_run),
            "run_count": long_summary.get("run_count"),
            "action_total": long_summary.get("action_total"),
            "failure_rate": long_summary.get("failure_rate"),
            "verified_action_ratio": long_summary.get("verified_action_ratio"),
            "successful_capability_count": long_summary.get("successful_capability_count"),
            "artifact_path": long_run_path,
            "metrics": _monitor_long_run_metrics(long_run.get("metrics")),
        },
        "manual_probe": {
            "passed": bool(manual_probe.get("passed")),
            "evaluated_at": manual_probe.get("evaluated_at"),
            "rank": _monitor_rank_summary(manual_probe),
            "probe_count": manual_probe.get("probe_count"),
            "hidden_probe_count": manual_probe.get("hidden_probe_count"),
            "blocker_count": len(manual_probe.get("blockers") if isinstance(manual_probe.get("blockers"), list) else []),
            "artifact_path": manual_probe_path,
        },
        "roadmap": {
            "status": roadmap.get("status"),
            "generated_at": roadmap.get("generated_at"),
            "first_priority": _monitor_first_priority(roadmap),
            "whole_system_status": whole_system_summary.get("status"),
            "whole_system_average_score": whole_system_summary.get("average_score"),
            "open_tasks": backlog.get("open_system_tasks"),
            "open_capability_gaps": backlog.get("open_capability_gaps"),
            "latest_eval_gaps": backlog.get("latest_eval_gaps"),
            "priority_queue": _monitor_priority_rows(roadmap),
            "error": roadmap.get("error"),
        },
    }


def entry_to_json(entry: Dict[str, object]) -> Dict[str, object]:
    return {
        "id": entry["id"],
        "timestamp": entry["timestamp"],
        "kind": entry["kind"],
        "body": entry["text"],
        "preview": entry_preview(entry),
        "tags": entry.get("tags", []),
        "metadata": entry.get("metadata", {}),
    }


def active_mind_audit_event_to_json(event: Dict[str, object]) -> Dict[str, object]:
    return {
        "id": event.get("id") or "",
        "timestamp": event.get("timestamp") or "",
        "source": event.get("source") or "",
        "event_kind": event.get("event_kind") or "",
        "title": event.get("title") or "",
        "detail": event.get("detail") or "",
        "thread_kind": event.get("thread_kind") or "",
        "thread_status": event.get("thread_status") or "",
        "summary": event.get("summary") or "",
    }


def tension_to_json(tension: Dict[str, object]) -> Dict[str, object]:
    return {
        "id": tension["id"],
        "timestamp": tension["timestamp"],
        "summary": tension["summary"],
        "side_a": tension["side_a"],
        "side_b": tension["side_b"],
        "values": tension.get("values", []),
        "question": tension["question"],
        "next_step": tension["next_step"],
        "status": tension["status"],
    }


def experiment_to_json(experiment: Dict[str, object]) -> Dict[str, object]:
    return {
        "id": experiment["id"],
        "created_at": experiment["created_at"],
        "updated_at": experiment.get("updated_at"),
        "name": experiment["name"],
        "hypothesis": experiment["hypothesis"],
        "action": experiment["action"],
        "success_criteria": experiment["success_criteria"],
        "duration_days": experiment["duration_days"],
        "status": experiment["status"],
        "outcome": experiment.get("outcome") or "",
        "notes": experiment.get("notes") or "",
    }


def evaluation_to_json(evaluation: Dict[str, object]) -> Dict[str, object]:
    return {
        "id": evaluation["id"],
        "created_at": evaluation["created_at"],
        "updated_at": evaluation.get("updated_at"),
        "target_kind": evaluation["target_kind"],
        "target_id": evaluation["target_id"],
        "thread_id": evaluation.get("thread_id") or "",
        "evaluator": evaluation.get("evaluator") or "",
        "source": evaluation.get("source") or "",
        "summary": evaluation.get("summary") or "",
        "evidence": evaluation.get("evidence") or "",
        "scorecard": eve.scorecard_from_record(evaluation),
    }


def outcome_to_json(outcome: Dict[str, object]) -> Dict[str, object]:
    return {
        "id": outcome["id"],
        "created_at": outcome["created_at"],
        "updated_at": outcome.get("updated_at"),
        "target_kind": outcome["target_kind"],
        "target_id": outcome["target_id"],
        "thread_id": outcome.get("thread_id") or "",
        "direction": outcome.get("direction") or "neutral",
        "outcome": outcome.get("outcome") or "",
        "summary": outcome.get("summary") or "",
        "evidence": outcome.get("evidence") or "",
        "source": outcome.get("source") or "",
    }


def failure_cluster_to_json(cluster: Dict[str, object]) -> Dict[str, object]:
    return {
        "id": cluster["id"],
        "created_at": cluster.get("created_at"),
        "updated_at": cluster.get("updated_at"),
        "last_reviewed_at": cluster.get("last_reviewed_at"),
        "cluster_key": cluster.get("cluster_key") or "",
        "title": cluster.get("title") or "",
        "summary": cluster.get("summary") or "",
        "suspected_root_cause": cluster.get("suspected_root_cause") or "",
        "exact_repair": cluster.get("exact_repair") or "",
        "status": cluster.get("status") or "open",
        "weak_dimensions": cluster.get("weak_dimensions") or [],
        "target_breakdown": cluster.get("target_breakdown") or {},
        "evidence": cluster.get("evidence") or [],
        "evaluation_count": int(cluster.get("evaluation_count") or 0),
        "outcome_count": int(cluster.get("outcome_count") or 0),
        "entry_count": int(cluster.get("entry_count") or 0),
    }


def action_execution_to_monitor_json(record: Dict[str, object]) -> Dict[str, object]:
    steps = record.get("steps") if isinstance(record.get("steps"), list) else []
    return {
        "id": record.get("id") or "",
        "created_at": record.get("created_at") or "",
        "updated_at": record.get("updated_at") or "",
        "action": record.get("action") or "",
        "source": record.get("source") or "",
        "tree_status": record.get("tree_status") or "",
        "verification_ok": bool(record.get("verification_ok")),
        "result_ok": bool(record.get("result_ok")),
        "typed_contract_ok": bool(record.get("typed_contract_ok")),
        "privacy_tier": record.get("privacy_tier") or "",
        "data_boundary": text_preview(record.get("data_boundary") or "", 220),
        "summary": text_preview(record.get("summary") or "", 260),
        "steps": [
            {
                "phase": item.get("phase") or "",
                "ok": bool(item.get("ok")),
                "message": text_preview(item.get("message") or "", 180),
            }
            for item in steps[-3:]
            if isinstance(item, dict)
        ],
    }


def evidence_record_to_monitor_json(record: Dict[str, object]) -> Dict[str, object]:
    try:
        freshness = int(eve.eve_evidence.evidence_freshness_score(record))
    except Exception:
        freshness = 0
    return {
        "id": record.get("id") or "",
        "observed_at": record.get("observed_at") or record.get("created_at") or "",
        "expires_at": record.get("expires_at") or "",
        "source": record.get("source") or "",
        "kind": record.get("kind") or "",
        "status": record.get("status") or "",
        "claim": text_preview(record.get("claim") or "", 260),
        "summary": text_preview(record.get("summary") or "", 260),
        "confidence": record.get("confidence") or 0,
        "freshness": freshness,
        "actionability": record.get("actionability") or "",
        "supports": record.get("supports") if isinstance(record.get("supports"), list) else [],
        "contradicts": record.get("contradicts") if isinstance(record.get("contradicts"), list) else [],
    }


def commitment_record_to_monitor_json(record: Dict[str, object]) -> Dict[str, object]:
    return {
        "id": record.get("id") or "",
        "created_at": record.get("created_at") or "",
        "updated_at": record.get("updated_at") or "",
        "source": record.get("source") or "",
        "kind": record.get("kind") or "",
        "status": record.get("status") or "",
        "text": text_preview(record.get("text") or "", 260),
        "action": record.get("action") or record.get("supported_action") or "",
        "result_summary": text_preview(record.get("result_summary") or "", 220),
        "verification": text_preview(record.get("verification") or "", 220),
        "thread_id": record.get("thread_id") or "",
    }


def experience_event_to_monitor_json(record: Dict[str, object]) -> Dict[str, object]:
    return {
        "id": record.get("id") or "",
        "timestamp": record.get("timestamp") or "",
        "event_type": record.get("event_type") or "",
        "source": record.get("source") or "",
        "actor": record.get("actor") or "",
        "subject": text_preview(record.get("subject") or "", 120),
        "summary": text_preview(record.get("summary") or "", 260),
        "result": text_preview(record.get("result") or "", 180),
        "learning": text_preview(record.get("learning") or "", 180),
    }


def user_correction_to_monitor_json(record: Dict[str, object]) -> Dict[str, object]:
    return {
        "id": record.get("id") or "",
        "created_at": record.get("created_at") or "",
        "updated_at": record.get("updated_at") or "",
        "source": record.get("source") or "",
        "thread_id": record.get("thread_id") or "",
        "message_id": record.get("message_id") or "",
        "target_message_id": record.get("target_message_id") or "",
        "issue_type": record.get("issue_type") or "",
        "severity": record.get("severity") or "",
        "status": record.get("status") or "",
        "summary": text_preview(record.get("summary") or "", 260),
        "episode_id": record.get("episode_id") or "",
    }


def relationship_episode_to_monitor_json(record: Dict[str, object]) -> Dict[str, object]:
    return {
        "id": record.get("id") or "",
        "created_at": record.get("created_at") or "",
        "updated_at": record.get("updated_at") or "",
        "source": record.get("source") or "",
        "thread_id": record.get("thread_id") or "",
        "what_happened": text_preview(record.get("what_happened") or "", 260),
        "what_user_cared_about": text_preview(record.get("what_user_cared_about") or "", 260),
        "what_eve_got_wrong": text_preview(record.get("what_eve_got_wrong") or "", 180),
        "what_changed_afterward": text_preview(record.get("what_changed_afterward") or "", 260),
        "correction_ids": record.get("correction_ids") if isinstance(record.get("correction_ids"), list) else [],
    }


def human_context_signals_to_monitor_json(context: Dict[str, object]) -> Dict[str, object]:
    normalized = eve.normalize_human_context(context)
    memory_v2 = normalized.get("memory_v2") if isinstance(normalized.get("memory_v2"), dict) else {}
    relationship = normalized.get("relationship_memory") if isinstance(normalized.get("relationship_memory"), dict) else {}
    return {
        "updated_at": normalized.get("updated_at") or "",
        "source": "human_context.memory_v2",
        "trust": list(memory_v2.get("trust_ledger") or [])[:3],
        "repair": list(memory_v2.get("repair_practices") or [])[:3],
        "anti_sycophancy": list(memory_v2.get("anti_sycophancy_boundaries") or [])[:3],
        "episodic_markers": list(memory_v2.get("episodic_markers") or [])[:3],
        "open_loops": list(relationship.get("open_loops") or [])[:3],
    }


def autonomy_run_to_monitor_json(record: Dict[str, object]) -> Dict[str, object]:
    run_objective = record.get("run_objective") if isinstance(record.get("run_objective"), dict) else {}
    supervisor = record.get("supervisor") if isinstance(record.get("supervisor"), dict) else {}
    actions = record.get("actions") if isinstance(record.get("actions"), list) else []
    claim_audit = record.get("claim_audit") if isinstance(record.get("claim_audit"), list) else []
    action_mix = record.get("action_mix") if isinstance(record.get("action_mix"), dict) else {}
    return {
        "run_id": record.get("run_id") or "",
        "source": record.get("source") or "manual",
        "style": record.get("style") or "",
        "started_at": record.get("started_at") or "",
        "finished_at": record.get("finished_at") or "",
        "objective": text_preview(run_objective.get("objective") or "", 220),
        "action_count": len(actions),
        "claim_audit_count": len(claim_audit),
        "supervisor": {
            "score": supervisor.get("score") or 0,
            "verdict": supervisor.get("verdict") or "",
            "issues": supervisor.get("issues") if isinstance(supervisor.get("issues"), list) else [],
            "strengths": supervisor.get("strengths") if isinstance(supervisor.get("strengths"), list) else [],
            "quotas": supervisor.get("quotas") if isinstance(supervisor.get("quotas"), dict) else {},
        },
        "action_mix": action_mix,
    }


def system_task_to_monitor_json(record: Dict[str, object]) -> Dict[str, object]:
    return {
        "id": record.get("id") or "",
        "created_at": record.get("created_at") or "",
        "updated_at": record.get("updated_at") or "",
        "kind": record.get("kind") or "",
        "title": text_preview(record.get("title") or "", 160),
        "summary": text_preview(record.get("summary") or record.get("result_summary") or "", 220),
        "status": record.get("status") or "",
        "lane": record.get("lane") or "",
        "priority": record.get("priority") or 0,
        "blocked_reason": text_preview(record.get("blocked_reason") or "", 160),
    }


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return default
    return converted if math.isfinite(converted) else default


def safe_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


def clamp_percent(value: float) -> float:
    return round(max(0.0, min(100.0, safe_float(value))), 1)


def process_kind(command: str) -> str:
    lowered = command.lower()
    if "eve monitor" in lowered or "eve.py" in lowered or "eve_web.py" in lowered or "eve_control.sh" in lowered:
        return "eve"
    if "ollama" in lowered or "llama-server" in lowered or "llama.cpp" in lowered or ".gguf" in lowered:
        return "model"
    return "system"


def process_title(command: str) -> str:
    command = " ".join(str(command or "").split())
    if not command:
        return "unknown"
    first = Path(command.split(" ", 1)[0]).name
    if first in {"python", "python3"} and "eve_web.py" in command:
        return "Eve web"
    if first in {"python", "python3"} and "eve.py" in command:
        return "Eve daemon"
    if "Eve Monitor" in command:
        return "Eve Monitor"
    if "ollama" in command.lower():
        return "Ollama"
    if "llama-server" in command.lower():
        return "llama-server"
    return (first or command[:48])[:80]


def read_process_table() -> list[Dict[str, object]]:
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,pcpu=,rss=,command="],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []

    processes: list[Dict[str, object]] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 4)
        if len(parts) < 5:
            continue
        pid, ppid, pcpu, rss_kb, command = parts
        cpu_percent = max(0.0, safe_float(pcpu))
        rss_bytes = max(0, safe_int(rss_kb)) * 1024
        kind = process_kind(command)
        title = process_title(command)
        processes.append(
            {
                "pid": safe_int(pid),
                "ppid": safe_int(ppid),
                "title": title,
                "kind": kind,
                "cpu_percent": round(cpu_percent, 1),
                "memory_bytes": rss_bytes,
                # Keep the compatibility field but never expose arguments,
                # paths, prompts, tokens, or other process command content.
                "command": title,
            }
        )
    return processes


def read_memory_snapshot() -> Dict[str, object]:
    total = 0
    try:
        result = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=1)
        if result.returncode == 0:
            total = safe_int(result.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        total = 0

    page_size = 4096
    pages: Dict[str, int] = {}
    try:
        result = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=1)
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                stripped = line.strip()
                if "page size of" in stripped:
                    digits = "".join(ch for ch in stripped if ch.isdigit())
                    if digits:
                        page_size = safe_int(digits, page_size)
                    continue
                if ":" not in stripped:
                    continue
                key, raw_value = stripped.split(":", 1)
                pages[key.strip()] = safe_int(raw_value.strip().rstrip(".").replace(".", ""))
    except (OSError, subprocess.TimeoutExpired):
        pass

    used_pages = (
        pages.get("Pages active", 0)
        + pages.get("Pages wired down", 0)
        + pages.get("Pages occupied by compressor", 0)
    )
    free_pages = pages.get("Pages free", 0) + pages.get("Pages speculative", 0) + pages.get("Pages inactive", 0)
    used_bytes = max(0, used_pages * page_size)
    if total:
        used_bytes = min(total, used_bytes)
    free_bytes = max(0, (total - used_bytes) if total else free_pages * page_size)
    percent = clamp_percent((used_bytes / total) * 100.0) if total else 0.0
    return {
        "total_bytes": total,
        "used_bytes": used_bytes,
        "free_bytes": free_bytes,
        "used_percent": percent,
        "page_size": page_size,
    }


def read_disk_snapshot() -> Dict[str, object]:
    path = eve.RUNTIME_DIR if eve.RUNTIME_DIR.exists() else ROOT
    try:
        usage = shutil.disk_usage(str(path))
    except OSError:
        return {"path": str(path), "total_bytes": 0, "used_bytes": 0, "free_bytes": 0, "used_percent": 0.0}
    used = usage.total - usage.free
    percent = clamp_percent((used / usage.total) * 100.0) if usage.total else 0.0
    return {
        "path": str(path),
        "total_bytes": usage.total,
        "used_bytes": used,
        "free_bytes": usage.free,
        "used_percent": percent,
    }


def selected_processes(processes: list[Dict[str, object]], limit: int = 14) -> list[Dict[str, object]]:
    chosen: list[Dict[str, object]] = []
    seen: set[int] = set()
    interesting = [item for item in processes if item.get("kind") in {"eve", "model"}]
    hot = sorted(
        processes,
        key=lambda item: (safe_float(item.get("cpu_percent")), safe_int(item.get("memory_bytes"))),
        reverse=True,
    )
    for item in [*interesting, *hot]:
        pid = safe_int(item.get("pid"))
        if pid in seen:
            continue
        seen.add(pid)
        chosen.append(item)
        if len(chosen) >= limit:
            break
    return chosen


def model_call_event_to_monitor_json(event: Dict[str, object]) -> Dict[str, object]:
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    duration_ms = safe_float(event.get("duration_ms"))
    response_chars = safe_int(metadata.get("response_chars"))
    chars_per_second = 0.0
    if duration_ms > 0 and response_chars > 0:
        chars_per_second = round(response_chars / (duration_ms / 1000.0), 1)
    return {
        "id": event.get("id") or "",
        "timestamp": event.get("timestamp") or "",
        "operation": metadata.get("operation") or event.get("name") or "",
        "backend": metadata.get("backend") or "",
        "model": metadata.get("model") or "",
        "host": metadata.get("host") or "",
        "duration_ms": duration_ms,
        "ok": bool(event.get("ok", True)),
        "message_count": metadata.get("message_count") or 0,
        "max_tokens": metadata.get("max_tokens") or 0,
        "response_chars": response_chars,
        "chars_per_second": chars_per_second,
        "error": text_preview(metadata.get("error") or "", 180),
    }


def model_call_matches_lane(call: Dict[str, object], lane: Dict[str, object]) -> bool:
    call_model = str(call.get("model") or "").lower()
    lane_model = str(lane.get("model") or "").lower()
    call_host = str(call.get("host") or "").rstrip("/")
    lane_host = str(lane.get("host") or "").rstrip("/")
    if lane_model and (call_model == lane_model or call_model.split(":")[0] == lane_model.split(":")[0]):
        return True
    return bool(call_host and lane_host and call_host == lane_host)


def activity_lane_to_monitor_json(
    lane: Dict[str, object],
    active_calls: list[Dict[str, object]],
    recent_calls: list[Dict[str, object]],
) -> Dict[str, object]:
    active = next((item for item in active_calls if model_call_matches_lane(item, lane)), None)
    recent = next((item for item in recent_calls if model_call_matches_lane(item, lane)), None)
    state = "generating" if active else ("ready" if lane.get("loaded") else "offline")
    operation = ""
    if active:
        operation = str(active.get("operation") or "")
    elif recent:
        operation = str(recent.get("operation") or "")
    return {
        "lane": lane.get("lane") or "",
        "label": lane.get("label") or "",
        "model": lane.get("model") or "",
        "host": lane.get("host") or "",
        "backend": lane.get("backend") or "",
        "loaded": bool(lane.get("loaded")),
        "state": state,
        "operation": operation,
        "latency_ms": safe_float(lane.get("latency_ms")),
        "elapsed_ms": safe_float(active.get("elapsed_ms")) if active else 0.0,
        "duration_ms": safe_float(recent.get("duration_ms")) if recent else 0.0,
        "chars_per_second": safe_float(recent.get("chars_per_second")) if recent else 0.0,
        "last_ok": bool(recent.get("ok", True)) if recent else None,
    }


ConversationSpineReader = Callable[..., list[Dict[str, object]]]


def build_monitor_status_payload(
    status: Dict[str, object],
    *,
    api_version: int,
) -> Dict[str, object]:
    """Project the bounded status subset consumed by the monitor dashboard."""

    counts = status.get("counts") if isinstance(status.get("counts"), dict) else {}
    daemon = status.get("daemon") if isinstance(status.get("daemon"), dict) else {}
    model_health = status.get("model_health") if isinstance(status.get("model_health"), dict) else {}
    lanes = model_health.get("lanes") if isinstance(model_health.get("lanes"), list) else []
    loaded_models = model_health.get("loaded_models") if isinstance(model_health.get("loaded_models"), list) else []
    probes = model_health.get("probes") if isinstance(model_health.get("probes"), dict) else {}
    threads = status.get("thread_attention") if isinstance(status.get("thread_attention"), list) else []
    return {
        "api_version": status.get("api_version") or api_version,
        "human_context_signals": status.get("human_context_signals")
        if isinstance(status.get("human_context_signals"), dict)
        else {},
        "counts": {
            "active_threads": counts.get("active_threads") or 0,
            "waiting_threads": counts.get("waiting_threads") or 0,
            "response_due_threads": counts.get("response_due_threads") or 0,
            "response_due_messages": counts.get("response_due_messages") or 0,
            "outbound_unseen_messages": counts.get("outbound_unseen_messages") or 0,
            "synthetic_continuity_messages": counts.get("synthetic_continuity_messages") or 0,
            "unread_messages": counts.get("unread_messages") or 0,
        },
        "daemon": {
            "runtime_dir": daemon.get("runtime_dir") or "",
            "running": bool(daemon.get("running")),
            "awake": bool(daemon.get("awake")),
        },
        "active_reply": status.get("active_reply") if isinstance(status.get("active_reply"), dict) else {},
        "model_health": {
            "updated_at": model_health.get("updated_at") or "",
            "summary": model_health.get("summary") or "",
            "lanes": [
                {
                    "lane": item.get("lane") or "",
                    "label": item.get("label") or "",
                    "model": item.get("model") or "",
                    "host": item.get("host") or "",
                    "backend": item.get("backend") or "",
                    "loaded": bool(item.get("loaded")),
                    "latency_ms": item.get("latency_ms") or 0,
                }
                for item in lanes
                if isinstance(item, dict)
            ],
            "loaded_models": [
                {
                    "name": item.get("name") or "",
                    "backend": item.get("backend") or "",
                    "host": item.get("host") or "",
                    "context_length": item.get("context_length") or 0,
                    "size_vram": item.get("size_vram") or 0,
                }
                for item in loaded_models
                if isinstance(item, dict)
            ],
            "probes": {
                "fast": probes.get("fast") if isinstance(probes.get("fast"), dict) else {},
                "deep": probes.get("deep") if isinstance(probes.get("deep"), dict) else {},
            },
        },
        "thread_attention": [
            {
                "thread_id": item.get("thread_id") or "",
                "subject": text_preview(item.get("subject") or "", 140),
                "latest_timestamp": item.get("latest_timestamp") or "",
                "latest_preview": text_preview(item.get("latest_preview") or "", 220),
                "latest_sender": item.get("latest_sender") or "",
                "message_count": item.get("message_count") or 0,
                "unread_count": item.get("unread_count") or 0,
                "outbound_unread_count": item.get("outbound_unread_count", item.get("unread_count") or 0),
                "inbound_pending_count": item.get("inbound_pending_count") or 0,
                "response_due_count": item.get("response_due_count") or 0,
                "synthetic_continuity_count": item.get("synthetic_continuity_count") or 0,
                "status": item.get("status") or "",
                "attention_score": item.get("attention_score") or 0,
            }
            for item in threads[:8]
            if isinstance(item, dict)
        ],
    }


def build_monitor_payload(
    *,
    status: Dict[str, object],
    activity: Dict[str, object],
    conversation_spine: ConversationSpineReader,
    compact: bool = False,
) -> Dict[str, object]:
    """Assemble compact or full monitor state from existing read-only stores."""

    human_context = eve.load_human_context(prefer_runtime=True)
    action_executions = eve.read_action_executions(limit=14, prefer_runtime=True)
    evidence_records = eve.read_evidence_ledger(limit=16, active_only=True, prefer_runtime=True)
    commitments = eve.read_commitments(limit=16, prefer_runtime=True)
    experience_events = eve.read_experience_events(limit=16, prefer_runtime=True)
    user_corrections = eve.read_user_corrections(limit=16, prefer_runtime=True)
    relationship_episodes = eve.read_relationship_episodes(limit=16, prefer_runtime=True)
    autonomy_runs = eve.read_autonomy_run_summaries(limit=4, prefer_runtime=True)
    governance = eve.governance_status_payload(limit=10, prefer_runtime=True)
    try:
        system_tasks = eve.read_system_tasks(limit=8, status=["pending", "active", "blocked"])
    except Exception:
        system_tasks = []

    payload = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": status,
        "human_context_signals": human_context_signals_to_monitor_json(human_context),
        "workspace": eve.load_global_workspace(prefer_runtime=True),
        "homeostasis": eve.load_homeostasis(prefer_runtime=True),
        "governance": governance_to_monitor_json(governance),
        "fitness": fitness_to_monitor_json(),
        "activity": activity,
        "autonomy": {
            "state": eve.load_autonomy_state(prefer_runtime=True),
            "agenda": eve.load_autonomy_agenda(prefer_runtime=True),
            "runs": [autonomy_run_to_monitor_json(item) for item in autonomy_runs],
        },
        "substrate": {
            "evidence": [evidence_record_to_monitor_json(item) for item in evidence_records],
            "commitments": [commitment_record_to_monitor_json(item) for item in commitments],
            "experience": [experience_event_to_monitor_json(item) for item in experience_events],
            "corrections": [user_correction_to_monitor_json(item) for item in user_corrections],
            "episodes": [relationship_episode_to_monitor_json(item) for item in relationship_episodes],
        },
        "operations": {
            "actions": [action_execution_to_monitor_json(item) for item in action_executions],
            "system_tasks": [system_task_to_monitor_json(item) for item in system_tasks],
        },
        "conversation_spine": conversation_spine(limit=12, include_synthetic=False),
    }
    if compact:
        return payload
    reply_turns = eve.read_reply_turn_replays(limit=8, prefer_runtime=True)
    reply_council_turns = eve.read_reply_council_turns(limit=8, prefer_runtime=True)
    payload.update(
        {
            "runtime_source_truth": eve.runtime_source_truth_check(include_daemon=True),
            "self_model": eve.load_self_model_state(prefer_runtime=True),
            "world_model": eve.load_world_model_state(prefer_runtime=True),
            "relationship_model": eve.load_relationship_model_state(prefer_runtime=True),
            "other_minds_model": eve.load_other_minds_model_state(prefer_runtime=True),
            "reply_turns": [reply_turn_replay_to_monitor_json(item) for item in reply_turns],
            "reply_council_turns": [reply_council_turn_to_monitor_json(item) for item in reply_council_turns],
        }
    )
    return payload
