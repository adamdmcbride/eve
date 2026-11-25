#!/usr/bin/env python3
"""Durable same-thread follow-up lifecycle for Eve Chat.

This service owns queueing, worker deduplication, leases, restart recovery,
verified action execution, idempotent delivery, and commitment/replay joins.
The composition root injects mutation serialization and compatible callback
seams. The service does not route ordinary replies, select model lanes, expose
HTTP, or broaden the admitted follow-up action set.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Dict, Optional

import eve
from eve_chat_protocol import (
    durable_eve_chat_followup_action_result,
    eve_chat_followup_ack_text,
    eve_chat_followup_action_for_messages,
    eve_chat_followup_delivery_text,
    eve_chat_followup_due_at,
    eve_chat_followup_seconds_until_due,
)
from eve_monitor_projection import message_to_json
from eve_openai_compat import latest_openai_user_content


@dataclass(frozen=True)
class EveChatFollowupPolicy:
    lease_seconds: int
    wait_slice_seconds: float
    supported_actions: frozenset[str]


@dataclass(frozen=True)
class EveChatFollowupHooks:
    """Composition callbacks preserving service locks and legacy patch seams."""

    run_mutation: Callable[[Callable[[], object]], object]
    start_worker: Callable[[str], None]
    existing_delivery: Callable[[str, str], Dict[str, object]]
    complete_cycle: Callable[..., Dict[str, object]]
    recover_action_result: Callable[[Dict[str, object]], Dict[str, object]]


class EveChatFollowupService:
    def __init__(
        self,
        *,
        policy_provider: Callable[[], EveChatFollowupPolicy],
        hooks: EveChatFollowupHooks,
    ) -> None:
        self._policy_provider = policy_provider
        self._hooks = hooks
        self._followup_workers_lock = threading.Lock()
        self._active_followup_workers: set[str] = set()

    def _policy(self) -> EveChatFollowupPolicy:
        return self._policy_provider()

    def _run_mutation(self, operation: Callable[[], object]):
        return self._hooks.run_mutation(operation)

    def eve_chat_followups(
        self,
        *,
        status: Optional[str] = None,
        surface: Optional[str] = None,
        include_seen: bool = False,
        limit: int = 50,
    ) -> Dict[str, object]:
        records = eve.read_eve_chat_followups(
            status=status,
            surface=surface,
            include_seen=include_seen,
            limit=limit,
        )
        return {
            "items": records,
            "count": len(records),
            "generated_at": eve.utc_now(),
        }

    def mark_eve_chat_followup_seen(self, followup_id: str) -> Dict[str, object]:
        def operation() -> Dict[str, object]:
            try:
                return eve.mark_eve_chat_followup_seen(followup_id)
            except SystemExit as exc:
                raise LookupError(str(exc)) from exc

        return self._run_mutation(operation)

    def queue_eve_chat_followup(
        self,
        *,
        messages: list[Dict[str, str]],
        result: Dict[str, object],
        client_request_id: str,
        transport: Dict[str, str],
        evaluation_metadata: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        evaluation = evaluation_metadata if isinstance(evaluation_metadata, dict) else {}
        if evaluation.get("synthetic"):
            raise ValueError("Synthetic evaluator turns cannot queue lived Eve Chat follow-ups.")
        reply = result.get("reply") if isinstance(result.get("reply"), dict) else {}
        source_user_message_id = ""
        for message in reversed(result.get("messages", [])):
            if isinstance(message, dict) and message.get("sender") == "user" and message.get("recipient") == "eve":
                source_user_message_id = str(message.get("id") or "")
                break
        policy = self._policy()
        action = eve_chat_followup_action_for_messages(messages)
        if action not in policy.supported_actions:
            action = "service_health_check"
        due_at = eve_chat_followup_due_at(messages)
        replay: Dict[str, object] = {}
        reply_id = str(reply.get("id") or "")
        if reply_id:
            try:
                replays = eve.read_reply_turn_replays(
                    limit=1,
                    reply_message_id=reply_id,
                    prefer_runtime=True,
                )
                if replays:
                    replay = replays[0]
            except Exception:
                replay = {}

        def operation() -> Dict[str, object]:
            followup = eve.create_eve_chat_followup(
                requested_action=action,
                prompt=latest_openai_user_content(messages),
                thread_id=str(result.get("thread_id") or ""),
                source_user_message_id=source_user_message_id,
                source_reply_message_id=str(reply.get("id") or ""),
                openwebui_chat_id=transport.get("openwebui_chat_id", ""),
                openwebui_user_message_id=transport.get("openwebui_user_message_id", ""),
                openwebui_assistant_message_id=transport.get("openwebui_assistant_message_id", ""),
                client_request_id=client_request_id,
                due_at=due_at,
                source_cycle_id=str(replay.get("conscious_cycle_id") or ""),
                reply_turn_replay_id=str(replay.get("id") or ""),
                faculty_contributors=(
                    replay.get("faculty_contributors")
                    if isinstance(replay.get("faculty_contributors"), list)
                    else []
                ),
                synthetic=False,
                metadata={
                    "origin": transport.get("origin", ""),
                    "delivery_surface": "eve_chat_thread",
                    "ui_delivery": "polling_api",
                    "durable_restart_recovery": True,
                },
            )
            if str(followup.get("schema") or "") == "eve_chat_followup.v2":
                commitment = eve.record_commitment(
                    source="eve_chat_followup",
                    text=(
                        f"Return the verified `{action}` result to the same Eve Chat thread at or after {due_at}."
                    ),
                    kind="commitment",
                    status="executing",
                    action=action,
                    supported_action=action,
                    verification="Pending durable local action and same-thread delivery.",
                    thread_id=str(result.get("thread_id") or ""),
                    inbound_message_id=source_user_message_id,
                    reply_message_id=str(reply.get("id") or ""),
                    metadata={
                        "followup_id": str(followup.get("id") or ""),
                        "due_at": due_at,
                        "source_cycle_id": str(replay.get("conscious_cycle_id") or ""),
                        "reply_turn_replay_id": str(replay.get("id") or ""),
                    },
                )
                followup = eve.update_eve_chat_followup_record(
                    str(followup["id"]),
                    commitment_id=str(commitment.get("id") or ""),
                )
            ack_text = eve_chat_followup_ack_text(action, str(followup["id"]), due_at)
            if reply_id:
                reply_metadata = reply.get("metadata") if isinstance(reply.get("metadata"), dict) else {}
                updated_reply = eve.update_message_record(
                    reply_id,
                    body=ack_text,
                    metadata={
                        **reply_metadata,
                        "eve_chat_followup_id": followup["id"],
                        "eve_chat_followup_action": action,
                        "eve_chat_followup_delivery": "queued",
                        "eve_chat_followup_due_at": due_at,
                        "eve_chat_followup_durable": True,
                        "ui_delivery": "polling_api",
                    },
                )
                result["reply"] = message_to_json(updated_reply)
            replay_id = str(replay.get("id") or "")
            if replay_id:
                try:
                    eve.update_reply_turn_replay_followup(
                        replay_id,
                        followup_id=str(followup.get("id") or ""),
                        status=str(followup.get("status") or "queued"),
                        action=action,
                        due_at=due_at,
                        commitment_id=str(followup.get("commitment_id") or ""),
                        visible_reply=ack_text,
                    )
                except Exception as exc:
                    eve.append_entry(
                        "reply_followup_join_failed",
                        "The durable follow-up was queued, but its reply replay could not be joined.",
                        metadata={
                            "followup_id": str(followup.get("id") or ""),
                            "reply_turn_replay_id": replay_id,
                            "error": eve.normalize_text_value(exc, fallback="unknown", limit=300),
                        },
                    )
            followup["ack_text"] = ack_text
            return followup

        followup = self._run_mutation(operation)
        self._hooks.start_worker(str(followup["id"]))
        return followup

    def start_eve_chat_followup_worker(self, followup_id: str) -> None:
        clean_id = str(followup_id or "").strip()
        if not clean_id:
            return
        with self._followup_workers_lock:
            if clean_id in self._active_followup_workers:
                return
            self._active_followup_workers.add(clean_id)
        worker = threading.Thread(
            target=self.run_eve_chat_followup_worker,
            args=(clean_id,),
            daemon=True,
            name=f"eve-chat-followup-{clean_id[:8]}",
        )
        worker.start()

    def resume_eve_chat_followups(self) -> Dict[str, object]:
        """Resume durable intentions left waiting or interrupted by a restart."""

        records = eve.read_eve_chat_followups(include_seen=True, limit=0)
        recoverable = [
            record
            for record in records
            if str(record.get("status") or "queued")
            not in eve.EVE_CHAT_FOLLOWUP_TERMINAL_STATUSES
        ]
        for record in recoverable:
            self._hooks.start_worker(str(record.get("id") or ""))
        return {
            "checked_at": eve.utc_now(),
            "recoverable_count": len(recoverable),
            "followup_ids": [str(record.get("id") or "") for record in recoverable],
        }

    def _existing_eve_chat_followup_delivery(
        self,
        followup_id: str,
        thread_id: str,
    ) -> Dict[str, object]:
        if not thread_id:
            return {}
        try:
            messages = eve.read_messages(
                thread_id=thread_id,
                limit=240,
                prefer_runtime=True,
            )
        except Exception:
            return {}
        for message in reversed(messages):
            metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
            if (
                str(metadata.get("eve_chat_followup_id") or "") == followup_id
                and str(metadata.get("eve_chat_followup_delivery") or "") == "result"
            ):
                return dict(message)
        return {}

    def _complete_eve_chat_followup_cycle(
        self,
        *,
        record: Dict[str, object],
        action: str,
        result: Dict[str, object],
        delivery_message_id: str,
        opened_state: Dict[str, object],
    ) -> Dict[str, object]:
        if not opened_state.get("cycle_id"):
            return {}
        verified = eve.action_result_verified_for_completion(result)
        attempt = {
            "attempt_index": int(record.get("attempt_count") or 1),
            "stage": "durable_followup",
            "menu_label": action,
            "action_id": action,
            "execution_id": result.get("execution_id") or "",
            "executed": bool(result.get("executed")),
            "tree_status": result.get("execution_tree_status") or "unknown",
            "verification_ok": verified,
            "summary": result.get("summary") or result.get("response") or "",
            "expected_signal": "A verified local action result delivered to the originating Eve Chat thread.",
            "persisted": True,
        }
        return eve.complete_recurrent_conscious_cycle(
            actual_process={
                "lanes": [],
                "model": "deterministic-executive-scheduler",
                "tools_used": [action],
                "action_id": action,
                "action_attempts": [attempt],
                "revision_used": False,
                "fallback_used": False,
            },
            outcome={
                "ok": verified,
                "observed": True,
                "delivery_ok": bool(delivery_message_id),
                "summary": result.get("summary") or result.get("response") or "Follow-up completed.",
                "thread_id": record.get("thread_id") or "",
                "source_message_id": record.get("source_user_message_id") or "",
                "reply_message_id": delivery_message_id,
                "originating_cycle_id": record.get("source_cycle_id") or "",
                "followup_id": record.get("id") or "",
            },
            source="chat_followup_completion",
            opened_state=opened_state,
        )

    def run_eve_chat_followup_worker(self, followup_id: str) -> None:
        worker_id = f"pid:{os.getpid()}:{uuid.uuid4().hex}"
        opened_state: Dict[str, object] = {}
        policy = self._policy()
        try:
            while True:
                record = eve.eve_chat_followup_record(followup_id)
                if str(record.get("status") or "") in eve.EVE_CHAT_FOLLOWUP_TERMINAL_STATUSES:
                    return
                seconds_until_due = eve_chat_followup_seconds_until_due(record)
                if seconds_until_due > 0:
                    if str(record.get("status") or "") != "waiting":
                        self._run_mutation(
                            lambda: eve.update_eve_chat_followup_record(
                                followup_id,
                                status="waiting",
                            )
                        )
                    time.sleep(min(policy.wait_slice_seconds, seconds_until_due))
                    continue
                claim = eve.claim_eve_chat_followup_record(
                    followup_id,
                    worker_id=worker_id,
                    lease_seconds=policy.lease_seconds,
                )
                if claim.get("claimed"):
                    record = claim.get("record") if isinstance(claim.get("record"), dict) else record
                    break
                if claim.get("reason") == "terminal":
                    return
                if claim.get("reason") in {"leased", "not_due"}:
                    time.sleep(policy.wait_slice_seconds)
                    continue
                return

            config = eve.load_config()
            action = str(record.get("requested_action") or "service_health_check")
            if action not in policy.supported_actions:
                action = "service_health_check"

            opened_state = eve.build_recurrent_conscious_state(
                source="chat_followup_worker",
                inbound=(
                    f"Resume durable same-thread follow-up {followup_id} for admitted action {action}. "
                    "The originating user request and due time are preserved in the durable follow-up record."
                ),
                persist=True,
            )
            record = self._run_mutation(
                lambda: eve.update_eve_chat_followup_record(
                    followup_id,
                    started_at=str(record.get("started_at") or eve.utc_now()),
                    worker_cycle_id=str(opened_state.get("cycle_id") or ""),
                )
            )

            result = self._hooks.recover_action_result(record)
            if not result:
                raw_result = eve.run_operational_action_tree(
                    action,
                    config,
                    source=f"chat_followup:{followup_id}",
                    persist=True,
                )
                result = durable_eve_chat_followup_action_result(action, raw_result)
            else:
                result = durable_eve_chat_followup_action_result(action, result)
            record = self._run_mutation(
                lambda: eve.update_eve_chat_followup_record(
                    followup_id,
                    status="result_ready",
                    action_result=result,
                    action_execution_id=str(result.get("execution_id") or ""),
                    action_completed_at=eve.utc_now(),
                    action_result_summary=eve.normalize_text_value(
                        result.get("summary"), fallback="", limit=1200
                    ),
                    action_result_ok=eve.action_result_verified_for_completion(result),
                )
            )
            delivery_text = eve_chat_followup_delivery_text(record, result)
            record = self._run_mutation(
                lambda: eve.update_eve_chat_followup_record(
                    followup_id,
                    status="delivering",
                    delivery_text=delivery_text,
                )
            )
            thread_id = str(record.get("thread_id") or "")
            delivery_message = self._hooks.existing_delivery(followup_id, thread_id)
            if not delivery_message:
                delivery_message = self._run_mutation(
                    lambda: eve.create_message(
                        sender="eve",
                        recipient="user",
                        subject="Eve Chat follow-up",
                        body=delivery_text,
                        kind="reply",
                        thread_id=thread_id or None,
                        reply_to=str(
                            record.get("source_user_message_id")
                            or record.get("source_reply_message_id")
                            or ""
                        )
                        or None,
                        status="unread",
                        metadata={
                            "surface": "eve_chat_ui",
                            "eve_chat_followup_id": followup_id,
                            "eve_chat_followup_action": action,
                            "eve_chat_followup_delivery": "result",
                            "action_result": result,
                            "model": "eve-chat-followup-worker",
                            "runtime": "eve_local_chat_backend",
                            "scheduler": "durable_eve_chat_followup_v2",
                            "source_cycle_id": record.get("source_cycle_id") or "",
                            "worker_cycle_id": opened_state.get("cycle_id") or "",
                            "ui_delivery": "polling_api",
                        },
                        notify=False,
                    )
                )
            delivery_message_id = str(delivery_message.get("id") or "")
            completed_cycle = self._hooks.complete_cycle(
                record=record,
                action=action,
                result=result,
                delivery_message_id=delivery_message_id,
                opened_state=opened_state,
            )
            commitment_id = str(record.get("commitment_id") or "")
            if commitment_id:
                try:
                    eve.update_commitment_record(
                        commitment_id,
                        status=(
                            "completed"
                            if eve.action_result_verified_for_completion(result)
                            else "blocked"
                        ),
                        result_summary=eve.normalize_text_value(
                            result.get("summary"), fallback="Follow-up completed.", limit=500
                        ),
                        verification=(
                            "Verified action and same-thread delivery."
                            if eve.action_result_verified_for_completion(result) and delivery_message_id
                            else "Action or same-thread delivery did not verify cleanly."
                        ),
                        action_execution_ids=[str(result.get("execution_id") or "")],
                        metadata={
                            "followup_id": followup_id,
                            "delivery_message_id": delivery_message_id,
                            "worker_cycle_id": str(opened_state.get("cycle_id") or ""),
                            "completed_cycle_id": str(completed_cycle.get("cycle_id") or ""),
                        },
                    )
                except Exception:
                    pass
            final_record = self._run_mutation(
                lambda: eve.update_eve_chat_followup_record(
                    followup_id,
                    status="delivered",
                    delivery_text=delivery_text,
                    delivery_message_id=delivery_message_id,
                    delivered_at=eve.utc_now(),
                    completed_conscious_cycle_id=str(completed_cycle.get("cycle_id") or ""),
                    lease_expires_at="",
                    worker_id="",
                    action_result_summary=eve.normalize_text_value(
                        result.get("summary"), fallback="", limit=1200
                    ),
                    action_result_ok=eve.action_result_verified_for_completion(result),
                )
            )
            replay_id = str(final_record.get("reply_turn_replay_id") or "")
            if replay_id:
                self._run_mutation(
                    lambda: eve.update_reply_turn_replay_followup(
                        replay_id,
                        followup_id=followup_id,
                        status="delivered",
                        action=action,
                        due_at=str(final_record.get("due_at") or ""),
                        commitment_id=str(final_record.get("commitment_id") or ""),
                        action_execution_id=str(result.get("execution_id") or ""),
                        action_result_ok=eve.action_result_verified_for_completion(result),
                        delivery_message_id=delivery_message_id,
                        worker_cycle_id=str(opened_state.get("cycle_id") or ""),
                        completed_cycle_id=str(completed_cycle.get("cycle_id") or ""),
                    )
                )
        except Exception as exc:
            def failure_operation() -> Dict[str, object]:
                reason = str(exc)
                try:
                    record = eve.update_eve_chat_followup_record(
                        followup_id,
                        status="failed",
                        failure_reason=eve.normalize_text_value(reason, fallback="unknown", limit=500),
                        delivered_at=eve.utc_now(),
                        delivery_text=(
                            "FOLLOW_UP_FAILED: I tried to finish the queued Eve Chat follow-up, "
                            f"but the worker failed before delivery. REASON: {reason}"
                        ),
                        lease_expires_at="",
                        worker_id="",
                    )
                    commitment_id = str(record.get("commitment_id") or "")
                    if commitment_id:
                        try:
                            eve.update_commitment_record(
                                commitment_id,
                                status="blocked",
                                result_summary=f"Durable follow-up worker failed: {reason}",
                                verification="Worker failure recorded; no verified same-thread completion.",
                            )
                        except Exception:
                            pass
                    replay_id = str(record.get("reply_turn_replay_id") or "")
                    if replay_id:
                        try:
                            eve.update_reply_turn_replay_followup(
                                replay_id,
                                followup_id=followup_id,
                                status="failed",
                                action=str(record.get("requested_action") or ""),
                                due_at=str(record.get("due_at") or ""),
                                commitment_id=commitment_id,
                                action_execution_id=str(record.get("action_execution_id") or ""),
                                action_result_ok=False,
                                worker_cycle_id=str(opened_state.get("cycle_id") or ""),
                                failure_reason=reason,
                            )
                        except Exception:
                            pass
                    return record
                except SystemExit as update_exc:
                    raise LookupError(str(update_exc)) from update_exc

            self._run_mutation(failure_operation)
        finally:
            with self._followup_workers_lock:
                self._active_followup_workers.discard(followup_id)
