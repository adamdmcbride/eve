#!/usr/bin/env python3
"""Typed, durable Eve Chat transport and follow-up protocol helpers.

This module parses explicit follow-up intent, derives bounded due times and
supported checks, normalizes external chat transport identities, and formats
compact persistence/delivery records. It does not schedule work, mutate state,
call a model, or own an HTTP route.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import eve
import eve_http_security
from eve_openai_compat import (
    latest_openai_user_content,
    normalize_openai_identifier,
    visible_openai_message_text,
)


EVE_CHAT_FOLLOWUP_POLL_ORIGINS = {
    "http://127.0.0.1:3000",
    "http://localhost:3000",
}
EVE_CHAT_FOLLOWUP_SUPPORTED_ACTIONS = {
    "service_health_check",
    "updates_status",
    "openclaw_log_check",
    "openclaw_sync_check",
    "cleanup_candidate_check",
}
EVE_CHAT_FOLLOWUP_MAX_DELAY_SECONDS = 7 * 24 * 60 * 60
EVE_CHAT_FOLLOWUP_WAIT_SLICE_SECONDS = 5.0
EVE_CHAT_FOLLOWUP_LEASE_SECONDS = 15 * 60

def canonical_eve_chat_local_origin(value: object) -> str:
    """Return a fixed allowlist value rather than reflecting a request header."""
    origin = eve_http_security.canonical_loopback_origin(value)
    return origin if origin in EVE_CHAT_FOLLOWUP_POLL_ORIGINS else ""


def eve_chat_followup_requested(messages: list[Dict[str, str]]) -> bool:
    latest = " ".join(latest_openai_user_content(messages).lower().split())
    if not latest:
        return False
    request_phrases = (
        "respond back",
        "get back to me",
        "let me know",
        "tell me when",
        "message me",
        "follow up",
        "send me",
    )
    deferred_phrases = (
        "when you",
        "after you",
        "once you",
        "when it",
        "when that",
        "when ready",
        "when its ready",
        "when it's ready",
        "later",
        "have checked",
        "have an answer",
        "finished",
        "done",
    )
    explicit_delivery_request = any(phrase in latest for phrase in request_phrases)
    relative_delay = eve_chat_followup_delay_seconds(messages) > 0
    no_new_prompt = any(
        phrase in latest
        for phrase in (
            "without another message",
            "without me sending another message",
            "without another prompt",
            "without me prompting",
            "without prompting me",
            "without me asking again",
            "without asking again",
            "do not wait for another message",
            "don't wait for another message",
        )
    )
    deferred_request = (
        relative_delay
        or no_new_prompt
        or any(phrase in latest for phrase in deferred_phrases)
    )
    action_cue = any(
        cue in latest
        for cue in (
            "check",
            "inspect",
            "run",
            "review",
            "look up",
            "find out",
            "diagnose",
            "verify",
        )
    )
    result_cue = any(
        cue in latest
        for cue in (
            "result",
            "answer",
            "outcome",
            "finding",
            "status",
            "what you find",
        )
    )
    delivery_verb = any(
        cue in latest
        for cue in (
            "return",
            "place",
            "put",
            "post",
            "insert",
            "add",
            "deliver",
            "write back",
        )
    )
    same_thread_destination = bool(
        re.search(
            r"\b(?:this|the same|same|this exact|the exact|exact|current|original)\s+"
            r"(?:chat|thread|conversation)\b",
            latest,
        )
    )
    semantic_same_thread_request = (
        action_cue
        and result_cue
        and delivery_verb
        and (same_thread_destination or no_new_prompt)
    )
    return deferred_request and (explicit_delivery_request or semantic_same_thread_request)


def eve_chat_followup_delay_seconds(messages: list[Dict[str, str]]) -> int:
    """Extract a bounded relative delay from the latest user request."""
    latest = " ".join(latest_openai_user_content(messages).lower().split())
    if re.search(r"\btomorrow\b", latest):
        return min(EVE_CHAT_FOLLOWUP_MAX_DELAY_SECONDS, 24 * 60 * 60)

    number_words = (
        "zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
        "thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
        "twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|and"
    )
    amount_pattern = rf"(?:\d{{1,6}}|(?:{number_words})(?:[-\s]+(?:{number_words})){{0,5}})"
    unit_pattern = r"seconds?|secs?|minutes?|mins?|hours?|hrs?|days?"
    match = re.search(
        rf"\b(?:in|after)\s+(?P<amount>{amount_pattern})\s*(?P<unit>{unit_pattern})\b",
        latest,
    ) or re.search(
        rf"\b(?P<amount>{amount_pattern})\s*(?P<unit>{unit_pattern})\s+"
        r"(?:from\s+now|later)\b",
        latest,
    )
    if not match:
        return 0

    amount_text = match.group("amount").replace("-", " ").strip()
    if amount_text.isdigit():
        amount = int(amount_text)
    else:
        small = {
            "zero": 0,
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
            "eleven": 11,
            "twelve": 12,
            "thirteen": 13,
            "fourteen": 14,
            "fifteen": 15,
            "sixteen": 16,
            "seventeen": 17,
            "eighteen": 18,
            "nineteen": 19,
        }
        tens = {
            "twenty": 20,
            "thirty": 30,
            "forty": 40,
            "fifty": 50,
            "sixty": 60,
            "seventy": 70,
            "eighty": 80,
            "ninety": 90,
        }
        amount = 0
        subtotal = 0
        for token in amount_text.split():
            if token == "and":
                continue
            if token in small:
                subtotal += small[token]
            elif token in tens:
                subtotal += tens[token]
            elif token == "hundred":
                subtotal = max(1, subtotal) * 100
            else:
                return 0
        amount += subtotal

    unit = match.group("unit")
    multiplier = 1
    if unit.startswith(("minute", "min")):
        multiplier = 60
    elif unit.startswith(("hour", "hr")):
        multiplier = 60 * 60
    elif unit.startswith("day"):
        multiplier = 24 * 60 * 60
    return max(0, min(EVE_CHAT_FOLLOWUP_MAX_DELAY_SECONDS, amount * multiplier))


def eve_chat_followup_due_at(
    messages: list[Dict[str, str]],
    *,
    now: Optional[datetime] = None,
) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return (current + timedelta(seconds=eve_chat_followup_delay_seconds(messages))).replace(
        microsecond=0
    ).isoformat()


def eve_chat_followup_seconds_until_due(record: Dict[str, object]) -> float:
    due_at = eve.parse_iso_datetime(record.get("due_at"))
    if due_at is None:
        return 0.0
    return max(0.0, (due_at - datetime.now(timezone.utc)).total_seconds())


def eve_chat_followup_action_for_messages(messages: list[Dict[str, str]]) -> str:
    visible_text = visible_openai_message_text(messages).lower()
    if any(token in visible_text for token in ("upgrade", "upgrades", "update", "updates", "newer", "online", "version")):
        return "updates_status"
    if any(token in visible_text for token in ("openclaw log", "gateway log", "latest log")):
        return "openclaw_log_check"
    if any(token in visible_text for token in ("openclaw sync", "sync openclaw", "openclaw status")):
        return "openclaw_sync_check"
    if any(token in visible_text for token in ("cleanup", "clean up", "disk cleanup", "candidate cleanup")):
        return "cleanup_candidate_check"
    return "service_health_check"


def dict_field(payload: object, key: str) -> object:
    if isinstance(payload, dict):
        return payload.get(key)
    return None


def first_transport_value(*values: object) -> object:
    for value in values:
        if isinstance(value, str) and not value.strip():
            continue
        if value is not None:
            return value
    return ""


def openai_chat_transport_metadata(payload: Dict[str, object]) -> Dict[str, str]:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    transport = payload.get("_eve_chat_transport") if isinstance(payload.get("_eve_chat_transport"), dict) else {}
    user_message = payload.get("user_message") if isinstance(payload.get("user_message"), dict) else {}
    return {
        "openwebui_chat_id": normalize_openai_identifier(
            first_transport_value(
                dict_field(transport, "openwebui_chat_id"),
                dict_field(metadata, "chat_id"),
                dict_field(payload, "chat_id"),
            ),
            label="OpenWebUI chat id",
        ),
        "openwebui_user_message_id": normalize_openai_identifier(
            first_transport_value(
                dict_field(transport, "openwebui_user_message_id"),
                dict_field(metadata, "user_message_id"),
                dict_field(user_message, "id"),
            ),
            label="OpenWebUI user message id",
        ),
        "openwebui_assistant_message_id": normalize_openai_identifier(
            first_transport_value(
                dict_field(transport, "openwebui_assistant_message_id"),
                dict_field(metadata, "message_id"),
                dict_field(payload, "id"),
            ),
            label="OpenWebUI assistant message id",
        ),
        "origin": normalize_openai_identifier(
            dict_field(transport, "origin"),
            label="transport origin",
            maximum_characters=512,
        ),
    }


def openai_chat_evaluation_metadata(payload: Dict[str, object]) -> Dict[str, object]:
    """Admit explicit evaluator provenance without trusting arbitrary metadata."""
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    evaluation = payload.get("_eve_evaluation") if isinstance(payload.get("_eve_evaluation"), dict) else {}
    merged = {**metadata, **evaluation}
    conversation_class = str(merged.get("conversation_class") or "").strip().lower()
    explicitly_synthetic = eve.parse_explicit_trueish(merged.get("synthetic"))
    if not explicitly_synthetic and conversation_class not in {
        "synthetic",
        "synthetic_eval",
        "evaluation",
        "probe",
    }:
        return {}
    return {
        "synthetic": True,
        "conversation_class": "synthetic_eval",
        "source": eve.normalize_text_value(
            merged.get("source"),
            fallback="external_hidden_evaluator",
            limit=80,
        ),
        "evaluation_id": eve.normalize_text_value(
            merged.get("evaluation_id") or merged.get("id"),
            fallback="",
            limit=120,
        ),
    }


def openai_chat_thread_id(transport: Dict[str, str]) -> Optional[str]:
    chat_id = normalize_openai_identifier(
        transport.get("openwebui_chat_id"),
        label="OpenWebUI chat id",
    )
    if not chat_id:
        return None
    digest = hashlib.sha256(chat_id.encode("utf-8")).hexdigest()[:32]
    return f"eve-chat-openwebui-{digest}"


def eve_chat_followup_ack_text(action: str, followup_id: str, due_at: str = "") -> str:
    action_label = action.replace("_", " ")
    timing = f" I will run it at or after {due_at}." if due_at else ""
    return (
        "Yes. I queued this as an Eve Chat follow-up and made it durable, so I can resume it after a "
        "backend restart and put the verified result in this same conversation without "
        "you sending another message. "
        f"Follow-up id: {followup_id}. Check: {action_label}.{timing}"
    )


def eve_chat_followup_delivery_text(record: Dict[str, object], result: Dict[str, object]) -> str:
    action = str(record.get("requested_action") or "service_health_check")
    response = str(result.get("response") or "").strip()
    summary = str(result.get("summary") or "").strip()
    verification = "yes" if result.get("verification_ok") or result.get("ok") else "no"
    backend = str(result.get("backend") or result.get("execution_backend") or "eve_local_runtime").strip()
    body = response or summary or f"{action.replace('_', ' ')} finished."
    return "\n".join(
        [
            "FOLLOW_UP_READY: I finished the check you asked me to continue.",
            f"ACTION: {action}",
            f"RESULT: {body}",
            f"EVIDENCE: verification_ok={verification}; backend={backend}; source=eve_chat_followup",
        ]
    )


def durable_eve_chat_followup_action_result(
    action: str,
    result: Dict[str, object],
) -> Dict[str, object]:
    verification_ok = eve.action_result_verified_for_completion(result)
    return {
        "action": action,
        "executed": bool(result.get("executed")),
        "ok": bool(result.get("ok")) and verification_ok,
        "summary": eve.normalize_text_value(
            result.get("execution_summary") or result.get("summary") or result.get("response"),
            fallback=f"{action.replace('_', ' ')} finished.",
            limit=1200,
        ),
        "response": eve.normalize_text_value(
            result.get("response") or result.get("execution_summary") or result.get("summary"),
            fallback=f"{action.replace('_', ' ')} finished.",
            limit=4000,
        ),
        "execution_id": eve.normalize_text_value(
            result.get("execution_id") or result.get("id"), fallback="", limit=120
        ),
        "execution_tree_status": eve.normalize_text_value(
            result.get("execution_tree_status") or result.get("tree_status"),
            fallback="unknown",
            limit=80,
        ),
        "execution_verification_ok": verification_ok,
        "verification_ok": verification_ok,
        "backend": eve.normalize_text_value(
            result.get("execution_backend") or result.get("backend"),
            fallback="eve_local_runtime",
            limit=80,
        ),
        "recovered_from_action_ledger": bool(result.get("recovered_from_action_ledger")),
    }


def recover_eve_chat_followup_action_result(record: Dict[str, object]) -> Dict[str, object]:
    stored = record.get("action_result") if isinstance(record.get("action_result"), dict) else {}
    if stored.get("execution_id"):
        return dict(stored)
    followup_id = str(record.get("id") or "")
    action = str(record.get("requested_action") or "service_health_check")
    expected_source = f"chat_followup:{followup_id}"
    for execution in eve.read_action_executions(limit=160, prefer_runtime=True):
        if str(execution.get("source") or "") != expected_source:
            continue
        if str(execution.get("action") or "") != action:
            continue
        recovered = {
            "action": action,
            "executed": True,
            "ok": eve.action_execution_verified(execution),
            "summary": execution.get("summary") or f"{action.replace('_', ' ')} finished.",
            "response": execution.get("summary") or f"{action.replace('_', ' ')} finished.",
            "execution_id": execution.get("id") or "",
            "execution_tree_status": execution.get("tree_status") or "unknown",
            "execution_verification_ok": eve.action_execution_verified(execution),
            "verification_ok": eve.action_execution_verified(execution),
            "backend": execution.get("backend") or "eve_local_runtime",
            "recovered_from_action_ledger": True,
        }
        return durable_eve_chat_followup_action_result(action, recovered)
    return {}
