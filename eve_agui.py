"""Typed CopilotKit/AG-UI protocol adapter for Eve's local chat surface.

This module translates admitted AG-UI JSON into Eve's existing local
OpenAI-compatible request contract and projects bounded progress events back to
the UI.  It owns protocol shape only; it does not select lanes, call models,
write memory, or grant action authority.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

import eve_http_json
from eve_openai_compat import (
    MAX_OPENAI_COMPAT_MESSAGE_CHARS,
    OPENAI_COMPAT_MODEL_ID,
    latest_openai_user_content,
    normalize_openai_chat_messages,
    normalize_openai_identifier,
    openai_message_content_text,
)


COPILOTKIT_AGUI_PROTOCOL = "eve_copilotkit_agui_v1"
MAX_AGUI_MODEL_CHARACTERS = 80
MAX_AGUI_EVENT_ID_CHARACTERS = 160
MAX_AGUI_EVENT_TYPE_CHARACTERS = 64


def _coalesced_identifier(
    payload: dict[str, Any],
    keys: tuple[str, ...],
    *,
    label: str,
) -> str:
    values: list[str] = []
    for key in keys:
        if key not in payload or payload[key] is None:
            continue
        normalized = normalize_openai_identifier(payload[key], label=label)
        if normalized:
            values.append(normalized)
    if len(set(values)) > 1:
        raise eve_http_json.JSONFieldError(f"Conflicting {label} aliases")
    return values[0] if values else ""


def _optional_object_field(payload: dict[str, Any], key: str, *, label: str) -> dict[str, Any]:
    value = payload.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise eve_http_json.JSONFieldError(f"{label} must be a JSON object")
    return value


def _optional_prompt(payload: dict[str, Any], key: str, *, label: str) -> str:
    if key not in payload or payload[key] is None:
        return ""
    return eve_http_json.require_text_value(
        payload[key],
        label=label,
        maximum_characters=MAX_OPENAI_COMPAT_MESSAGE_CHARS,
        multiline=True,
    )


def _validate_message_shapes(messages: object) -> None:
    if not isinstance(messages, list):
        return
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role is not None and not isinstance(role, str):
            raise eve_http_json.JSONFieldError(f"messages[{index}].role must be text")
        if isinstance(role, str):
            eve_http_json.require_text_value(
                role,
                label=f"messages[{index}].role",
                maximum_characters=32,
                required=True,
            )
        content = message.get("content")
        if content is not None and not isinstance(content, (str, list)):
            raise eve_http_json.JSONFieldError(
                f"messages[{index}].content must be text or a content-parts array"
            )
        if not isinstance(content, list):
            if isinstance(content, str):
                eve_http_json.require_text_value(
                    content,
                    label=f"messages[{index}].content",
                    maximum_characters=MAX_OPENAI_COMPAT_MESSAGE_CHARS,
                    multiline=True,
                )
            continue
        for part_index, part in enumerate(content):
            if isinstance(part, str):
                eve_http_json.require_text_value(
                    part,
                    label=f"messages[{index}].content[{part_index}]",
                    maximum_characters=MAX_OPENAI_COMPAT_MESSAGE_CHARS,
                    multiline=True,
                )
                continue
            if not isinstance(part, dict):
                raise eve_http_json.JSONFieldError(
                    f"messages[{index}].content[{part_index}] must be text or an object"
                )
            part_type = part.get("type")
            if part_type is not None and not isinstance(part_type, str):
                raise eve_http_json.JSONFieldError(
                    f"messages[{index}].content[{part_index}].type must be text"
                )
            if isinstance(part_type, str):
                eve_http_json.require_text_value(
                    part_type,
                    label=f"messages[{index}].content[{part_index}].type",
                    maximum_characters=48,
                    required=True,
                )
            if part_type in {"text", "input_text"}:
                text = part.get("text")
                if text is not None and not isinstance(text, str):
                    raise eve_http_json.JSONFieldError(
                        f"messages[{index}].content[{part_index}].text must be text"
                    )
                if isinstance(text, str):
                    eve_http_json.require_text_value(
                        text,
                        label=f"messages[{index}].content[{part_index}].text",
                        maximum_characters=MAX_OPENAI_COMPAT_MESSAGE_CHARS,
                        multiline=True,
                    )
        if len(openai_message_content_text(content)) > MAX_OPENAI_COMPAT_MESSAGE_CHARS:
            raise eve_http_json.JSONFieldError(f"messages[{index}].content is too long")


def normalize_copilotkit_agui_messages(payload: object) -> list[dict[str, str]]:
    fields = dict(eve_http_json.require_json_object(payload))
    input_payload = _optional_object_field(fields, "input", label="AG-UI input")

    messages = fields.get("messages")
    if isinstance(messages, list) and not messages:
        messages = None
    if messages is None:
        messages = input_payload.get("messages")
        if isinstance(messages, list) and not messages:
            messages = None
    if messages is None:
        prompt = _optional_prompt(fields, "prompt", label="AG-UI prompt")
        if not prompt:
            prompt = _optional_prompt(input_payload, "prompt", label="AG-UI input prompt")
        if not prompt:
            prompt = _optional_prompt(input_payload, "message", label="AG-UI input message")
        if prompt:
            messages = [{"role": "user", "content": prompt}]
    _validate_message_shapes(messages)
    return normalize_openai_chat_messages(messages)


def prefixed_agui_event_id(prefix: str, source_id: str) -> str:
    normalized_prefix = eve_http_json.require_text_value(
        prefix,
        label="AG-UI event id prefix",
        maximum_characters=32,
        required=True,
    )
    normalized_source = normalize_openai_identifier(
        source_id,
        label="AG-UI event id source",
        allow_empty=False,
    )
    candidate = f"{normalized_prefix}-{normalized_source}"
    if len(candidate) <= MAX_AGUI_EVENT_ID_CHARACTERS:
        return candidate
    digest = hashlib.sha256(normalized_source.encode("utf-8")).hexdigest()[:24]
    source_budget = (
        MAX_AGUI_EVENT_ID_CHARACTERS
        - len(normalized_prefix)
        - len(digest)
        - 2
    )
    return f"{normalized_prefix}-{normalized_source[:source_budget]}-{digest}"


def copilotkit_agui_context(payload: object) -> dict[str, object]:
    fields = dict(eve_http_json.require_json_object(payload))
    messages = normalize_copilotkit_agui_messages(fields)
    thread_id = _coalesced_identifier(
        fields,
        ("threadId", "thread_id", "chat_id"),
        label="AG-UI thread id",
    )
    if not thread_id:
        thread_id = f"eve-chat-agui-thread-{uuid.uuid4().hex}"
    run_id = _coalesced_identifier(
        fields,
        ("runId", "run_id"),
        label="AG-UI run id",
    )
    if not run_id:
        run_id = f"eve-chat-agui-run-{uuid.uuid4().hex}"
    client_request_id = _coalesced_identifier(
        fields,
        ("client_request_id", "user"),
        label="AG-UI client request id",
    )
    if not client_request_id:
        client_request_id = run_id
    model = normalize_openai_identifier(
        fields.get("model"),
        label="AG-UI model",
        maximum_characters=MAX_AGUI_MODEL_CHARACTERS,
    ) or OPENAI_COMPAT_MODEL_ID
    return {
        "thread_id": thread_id,
        "run_id": run_id,
        "client_request_id": client_request_id,
        "messages": messages,
        "latest_user": latest_openai_user_content(messages),
        "activity_message_id": prefixed_agui_event_id("activity", run_id),
        "text_message_id": prefixed_agui_event_id("msg", run_id),
        "openai_payload": {
            "model": model,
            "messages": messages,
            "client_request_id": client_request_id,
            "user": client_request_id,
            "chat_id": thread_id,
            "metadata": {
                "protocol": COPILOTKIT_AGUI_PROTOCOL,
                "thread_id": thread_id,
                "run_id": run_id,
            },
        },
    }


def agui_timestamp_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def agui_event(event_type: object, **fields: object) -> dict[str, object]:
    normalized_type = eve_http_json.require_text_value(
        event_type,
        label="AG-UI event type",
        maximum_characters=MAX_AGUI_EVENT_TYPE_CHARACTERS,
        required=True,
    )
    event: dict[str, object] = {
        "type": normalized_type,
        "timestamp": agui_timestamp_ms(),
    }
    event.update({key: value for key, value in fields.items() if value is not None})
    return event


def copilotkit_agui_progress_content(
    job: dict[str, object] | None,
    *,
    status: str = "queued",
) -> dict[str, object]:
    if not job:
        return {
            "status": status,
            "phase": "queued",
            "title": "Starting Eve reply",
            "detail": "Eve Chat handed the run to the local Eve runtime.",
            "notes": [],
            "source": "eve_reply_progress",
        }
    notes = job.get("notes") if isinstance(job.get("notes"), list) else []
    return {
        "status": str(job.get("status") or status),
        "phase": str(job.get("phase") or ""),
        "title": str(job.get("title") or ""),
        "detail": str(job.get("detail") or ""),
        "step": job.get("step"),
        "total_steps": job.get("total_steps"),
        "current_model": str(job.get("current_model") or job.get("requested_model") or ""),
        "thread_id": str(job.get("thread_id") or ""),
        "reply_message_id": str(job.get("reply_message_id") or ""),
        "notes": notes[-4:],
        "source": "eve_reply_progress",
    }


def copilotkit_agui_completion_reply(
    completion: dict[str, object],
) -> tuple[str, str, dict[str, object]]:
    choices = completion.get("choices") if isinstance(completion.get("choices"), list) else []
    first_choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = first_choice.get("message") if isinstance(first_choice.get("message"), dict) else {}
    eve_metadata = completion.get("eve") if isinstance(completion.get("eve"), dict) else {}
    reply_text = str(message.get("content") or "")
    reply_message_id = str(
        eve_metadata.get("reply_message_id")
        or completion.get("id")
        or f"msg-{uuid.uuid4().hex}"
    )
    return reply_text, reply_message_id, eve_metadata
