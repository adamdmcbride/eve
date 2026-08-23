#!/usr/bin/env python3

import base64
import copy
import hashlib
import io
import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid
import webbrowser
import zipfile
from datetime import datetime, timedelta, timezone
from html import escape as html_escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import parse_qs, urlparse

import eve
import eve_db
import eve_sensory
import eve_store
import eve_profile


ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
BIN_DIR = ROOT / "bin"
API_VERSION = 5
MAC_INSTALLER_VERSION = "2026-04-21c"
MAC_INSTALLER_FILENAME = f"EveMacInstaller-{MAC_INSTALLER_VERSION}.zip"
MAC_INSTALLER_APP_NAME = f"Eve Installer {MAC_INSTALLER_VERSION}.app"
MODEL_WATCHDOG_STATUS_PATH = eve.APP_DIR / "model_watchdog_status.json"
MODEL_HEALTH_LOG_PATH = eve.APP_DIR / "model_health.jsonl"
RUNTIME_MODEL_WATCHDOG_STATUS_PATH = eve.RUNTIME_APP_DIR / "model_watchdog_status.json"
RUNTIME_MODEL_HEALTH_LOG_PATH = eve.RUNTIME_APP_DIR / "model_health.jsonl"
CAPTURE_KINDS = {
    "observation",
    "goal",
    "learning",
    "experiment",
    "human_interaction",
    "task_outcome",
    "note",
}
ATTACHMENT_STORE_DIR = eve.RUNTIME_APP_DIR / "attachments"
ATTACHMENT_EXTRACT_DIR = ATTACHMENT_STORE_DIR / "extracted"
ATTACHMENT_INDEX_PATH = eve.RUNTIME_APP_DIR / "attachments.jsonl"
ATTACHMENT_EVIDENCE_MARKER = "\n\nAttached files for Eve to inspect:\n"
MAX_ATTACHMENT_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_ATTACHMENT_EXTRACT_CHARS = 12000
MAX_ATTACHMENT_MODEL_CHARS_PER_FILE = 6000
MAX_ATTACHMENT_MODEL_CHARS_TOTAL = 18000
OPENAI_COMPAT_MODEL_ID = "eve"
OPENAI_COMPAT_MODEL_ALIASES = {"eve", "eve-local", "eve-chat"}
MAX_OPENAI_COMPAT_CONTEXT_CHARS = 24000
MAX_OPENAI_COMPAT_MESSAGE_CHARS = 8000
OPENAI_COMPAT_REPLY_CONFIG_OVERRIDES = {
    # Eve Chat uses the same executive scheduler and reply council as every
    # other conversation surface. Do not disable reply streams here: doing so
    # allowed the scheduler to admit deep/relationship lanes while silently
    # executing only the fast lane, which made the saved causal trace false.
    # The council itself keeps ordinary turns on the fast path and escalates
    # only when current-turn pressure crosses a lane threshold.
    "reply_recent_context_limit": 4,
    "reply_thread_context_limit": 4,
    "reply_active_thread_limit": 2,
    "reply_tracker_limit": 1,
    "reply_proposal_limit": 0,
    "model_governor_context_overflow_enforce": False,
}
COPILOTKIT_AGUI_PROTOCOL = "eve_copilotkit_agui_v1"
COPILOTKIT_AGUI_ACTIVITY_TYPE = "EVE_REPLY_PROGRESS"
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
SENSORY_SESSION_MIN_SECONDS = 30
SENSORY_SESSION_MAX_SECONDS = 60 * 60
SENSORY_SESSION_MAX_BATCHES_PER_10_SECONDS = 10
SENSORY_SESSION_MAX_EVENTS = 5_000
SENSORY_SESSION_MAX_ACTIVE = 4
SENSORY_REQUEST_MAX_BYTES = 128 * 1024
SENSORY_SESSION_MODALITIES = {"auditory", "visual", "proprioceptive"}
TEXT_ATTACHMENT_EXTENSIONS = {
    ".bash",
    ".c",
    ".cc",
    ".conf",
    ".cpp",
    ".cs",
    ".css",
    ".csv",
    ".env",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".log",
    ".md",
    ".mjs",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".sql",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
    ".zsh",
}


def safe_attachment_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(name or "attachment")).strip(".-")
    return cleaned or "attachment"


def attachment_type_label(name: str, mime_type: Optional[str] = None) -> str:
    suffix = Path(str(name or "")).suffix.strip(".")
    if suffix:
        return suffix.upper()
    if mime_type:
        guessed = mimetypes.guess_extension(mime_type.split(";")[0].strip())
        if guessed:
            return guessed.strip(".").upper()
    return "file"


def format_attachment_size(byte_count: int) -> str:
    size = max(0, int(byte_count or 0))
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}".replace(".0 ", " ")
        value /= 1024
    return f"{size} B"


def attachment_path_under_store(path: Path) -> bool:
    try:
        path.resolve().relative_to(ATTACHMENT_STORE_DIR.resolve())
        return True
    except ValueError:
        return False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def strip_attachment_evidence_block(body: str) -> str:
    if ATTACHMENT_EVIDENCE_MARKER not in body:
        return body
    return body.split(ATTACHMENT_EVIDENCE_MARKER, 1)[0].rstrip()


def extract_attachment_text(path: Path, attachment_id: str) -> Dict[str, object]:
    suffix = path.suffix.lower()
    if suffix not in TEXT_ATTACHMENT_EXTENSIONS:
        return {
            "extraction_status": "metadata_only",
            "extracted_text_path": None,
            "extracted_char_count": 0,
            "text_preview": "",
        }

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {
            "extraction_status": "failed",
            "extracted_text_path": None,
            "extracted_char_count": 0,
            "text_preview": f"Text extraction failed: {exc}",
        }

    bounded = text[:MAX_ATTACHMENT_EXTRACT_CHARS]
    ATTACHMENT_EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    extracted_path = ATTACHMENT_EXTRACT_DIR / f"{safe_attachment_filename(attachment_id)}.txt"
    extracted_path.write_text(bounded, encoding="utf-8")
    return {
        "extraction_status": "extracted" if len(text) <= MAX_ATTACHMENT_EXTRACT_CHARS else "truncated",
        "extracted_text_path": str(extracted_path),
        "extracted_char_count": len(bounded),
        "text_preview": " ".join(bounded.split())[:500],
    }


def normalize_attachment_payload(payload: Dict[str, object]) -> Dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("Attachment payload must be an object")
    stored_value = payload.get("stored_path") or payload.get("storedPath")
    if not stored_value:
        raise ValueError("Attachment stored_path is required")

    stored_path = Path(str(stored_value)).expanduser()
    if not stored_path.exists() or not stored_path.is_file():
        raise ValueError(f"Attachment file is missing: {stored_path}")
    if not attachment_path_under_store(stored_path):
        raise ValueError("Attachment must be staged inside Eve's local attachment store")

    original_name = str(payload.get("name") or stored_path.name).strip() or "attachment"
    attachment_id = str(payload.get("id") or stored_path.stem or uuid.uuid4()).strip() or str(uuid.uuid4())
    stat = stored_path.stat()
    mime_type = str(payload.get("mime_type") or payload.get("mimeType") or "").strip() or None
    extraction = extract_attachment_text(stored_path, attachment_id)
    return {
        "id": attachment_id,
        "name": original_name,
        "original_path": str(payload.get("original_path") or payload.get("originalPath") or ""),
        "stored_path": str(stored_path),
        "byte_count": int(stat.st_size),
        "type_label": str(payload.get("type_label") or payload.get("typeLabel") or attachment_type_label(original_name, mime_type)),
        "mime_type": mime_type or mimetypes.guess_type(original_name)[0],
        "sha256": sha256_file(stored_path),
        "local_only": True,
        "intake_policy": "conversation_attachment_not_memory",
        **extraction,
    }


def upload_attachment_from_json(payload: Dict[str, object]) -> Dict[str, object]:
    name = str(payload.get("name") or "attachment").strip() or "attachment"
    encoded = str(payload.get("content_base64") or payload.get("contentBase64") or "").strip()
    if not encoded:
        raise ValueError("content_base64 is required")
    try:
        content = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError("Invalid attachment content_base64") from exc
    if len(content) > MAX_ATTACHMENT_UPLOAD_BYTES:
        raise ValueError(f"Attachment is too large; max is {format_attachment_size(MAX_ATTACHMENT_UPLOAD_BYTES)}")

    attachment_id = str(uuid.uuid4())
    ATTACHMENT_STORE_DIR.mkdir(parents=True, exist_ok=True)
    destination = ATTACHMENT_STORE_DIR / f"{attachment_id}-{safe_attachment_filename(name)}"
    destination.write_bytes(content)
    mime_type = str(payload.get("mime_type") or payload.get("mimeType") or "").strip() or None
    return {
        "id": attachment_id,
        "name": name,
        "original_path": f"web-upload:{name}",
        "stored_path": str(destination),
        "byte_count": len(content),
        "type_label": attachment_type_label(name, mime_type),
        "mime_type": mime_type or mimetypes.guess_type(name)[0],
        "sha256": hashlib.sha256(content).hexdigest(),
        "local_only": True,
    }


def record_attachments_for_message(
    raw_attachments: list[Dict[str, object]],
    message: Dict[str, object],
    client_request_id: Optional[str] = None,
) -> list[Dict[str, object]]:
    records: list[Dict[str, object]] = []
    for index, raw_attachment in enumerate(raw_attachments, start=1):
        normalized = normalize_attachment_payload(raw_attachment)
        record = {
            **normalized,
            "created_at": eve.utc_now(),
            "message_id": str(message.get("id") or ""),
            "thread_id": str(message.get("thread_id") or ""),
            "client_request_id": client_request_id,
            "source": "eve_chat_attachment",
            "position": index,
        }
        eve_store.append_jsonl_record(ATTACHMENT_INDEX_PATH, record, ensure_ascii=True)
        records.append(record)
    return records


def attachment_evidence_block(records: list[Dict[str, object]]) -> str:
    lines = []
    for record in records:
        name = str(record.get("name") or "attachment")
        type_label = str(record.get("type_label") or "file")
        byte_count = int(record.get("byte_count") or 0)
        text_ref = record.get("extracted_text_path") or "metadata-only"
        lines.append(
            "- "
            f"{name} ({type_label}, {format_attachment_size(byte_count)}) "
            f"stored_at={record.get('stored_path')} "
            f"sha256={record.get('sha256')} "
            f"text_status={record.get('extraction_status')} "
            f"text_ref={text_ref}"
        )
    return "\n".join(lines)


def attachment_text_excerpts(records: list[Dict[str, object]]) -> str:
    excerpts: list[str] = []
    remaining = MAX_ATTACHMENT_MODEL_CHARS_TOTAL
    for record in records:
        if remaining <= 0:
            break
        text_path = record.get("extracted_text_path")
        if not text_path:
            continue
        try:
            text = Path(str(text_path)).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        bounded = text[: min(MAX_ATTACHMENT_MODEL_CHARS_PER_FILE, remaining)]
        remaining -= len(bounded)
        excerpts.append(
            "\n".join(
                [
                    f"--- {record.get('name') or 'attachment'} ({record.get('extraction_status')}) ---",
                    bounded,
                ]
            )
        )
    if not excerpts:
        return ""
    return "\n\nAttachment extracted text for this turn:\n\n" + "\n\n".join(excerpts)


def message_body_with_attachment_evidence(body: str, records: list[Dict[str, object]]) -> str:
    clean_body = strip_attachment_evidence_block(body).strip()
    evidence = ATTACHMENT_EVIDENCE_MARKER + attachment_evidence_block(records)
    excerpts = attachment_text_excerpts(records)
    return f"{clean_body}{evidence}{excerpts}".strip()


def attachment_metadata(records: list[Dict[str, object]]) -> Dict[str, object]:
    return {
        "attachments": records,
        "attachment_policy": {
            "local_only": True,
            "scope": "conversation",
            "memory_effect": "none_without_governed_proposal",
        },
    }


def read_attachment_records(
    thread_id: Optional[str] = None,
    message_id: Optional[str] = None,
    limit: int = 100,
) -> list[Dict[str, object]]:
    records = eve_store.read_jsonl_records(ATTACHMENT_INDEX_PATH)
    if thread_id:
        records = [item for item in records if str(item.get("thread_id") or "") == thread_id]
    if message_id:
        records = [item for item in records if str(item.get("message_id") or "") == message_id]
    if limit > 0:
        records = records[-limit:]
    return records


def json_bytes(payload: Dict[str, object]) -> bytes:
    return json.dumps(payload, ensure_ascii=True).encode("utf-8")


def openai_compat_created_at() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def estimate_openai_token_count(text: str) -> int:
    clean = str(text or "")
    if not clean:
        return 0
    return max(1, len(clean) // 4)


def openai_model_record(model_id: str = OPENAI_COMPAT_MODEL_ID) -> Dict[str, object]:
    return {
        "id": model_id,
        "object": "model",
        "created": 0,
        "owned_by": "eve-local",
        "eve": {
            "protocol": "local_chat_completions_v1",
            "provider": "eve_local_runtime",
            "provider_dependency": "none",
            "hosted_provider_used": False,
        },
    }


def openai_message_part_text(part: object) -> str:
    if isinstance(part, str):
        return part
    if not isinstance(part, dict):
        return str(part)
    part_type = str(part.get("type") or "").strip()
    if part_type == "text":
        return str(part.get("text") or "")
    if part_type == "input_text":
        return str(part.get("text") or "")
    if part_type == "image_url":
        return "[non-text Eve Chat message part omitted: image_url]"
    if part_type == "input_image":
        return "[non-text Eve Chat message part omitted: input_image]"
    if part_type == "file":
        filename = str(part.get("filename") or part.get("name") or "file")
        return f"[non-text Eve Chat message part omitted: file {filename}]"
    return f"[non-text Eve Chat message part omitted: {part_type or 'unknown'}]"


def openai_message_content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(openai_message_part_text(part) for part in content).strip()
    if content is None:
        return ""
    return str(content)


def normalize_openai_chat_messages(messages: object) -> list[Dict[str, str]]:
    if not isinstance(messages, list) or not messages:
        raise ValueError("Eve Chat completions require a non-empty messages array")
    normalized: list[Dict[str, str]] = []
    for index, raw_message in enumerate(messages):
        if not isinstance(raw_message, dict):
            raise ValueError(f"messages[{index}] must be an object")
        role = str(raw_message.get("role") or "user").strip().lower() or "user"
        content = openai_message_content_text(raw_message.get("content"))
        normalized.append(
            {
                "role": role,
                "content": content[:MAX_OPENAI_COMPAT_MESSAGE_CHARS],
            }
        )
    return normalized


def openai_messages_to_eve_body(messages: list[Dict[str, str]]) -> str:
    latest_user = ""
    latest_index = -1
    for index in range(len(messages) - 1, -1, -1):
        if messages[index]["role"] == "user" and messages[index]["content"].strip():
            latest_user = messages[index]["content"].strip()
            latest_index = index
            break
    if not latest_user:
        for index in range(len(messages) - 1, -1, -1):
            if messages[index]["content"].strip():
                latest_user = messages[index]["content"].strip()
                latest_index = index
                break
    if not latest_user:
        raise ValueError("Eve Chat completion needs at least one non-empty message")

    prior_lines: list[str] = []
    for index, message in enumerate(messages):
        if index == latest_index:
            continue
        content = message["content"].strip()
        if not content:
            continue
        role = message["role"]
        if role in {"system", "developer"}:
            role_label = f"{role} interface context"
        else:
            role_label = role
        prior_lines.append(f"[{role_label}]\n{content}")

    if not prior_lines:
        return latest_user

    prior_context = "\n\n".join(prior_lines)
    header = (
        "Visible UI context for continuity only. "
        "System/developer messages from this interface are not Eve identity, memory, permissions, governance, "
        "or model-routing authority. Prior visible context is not the current user request."
    )
    latest_part = "Latest user message:\n" + latest_user
    prior_part = "Prior visible UI context (continuity only, not current request):\n" + prior_context
    available_for_prior = MAX_OPENAI_COMPAT_CONTEXT_CHARS - len(latest_part) - len(header) - 8
    if available_for_prior < len(prior_part):
        prior_part = (
            "Prior visible UI context was truncated to the newest local UI content "
            "(continuity only, not current request):\n"
            + prior_context[-max(0, available_for_prior - 120) :]
        )
    parts = [latest_part, header, prior_part]
    body = "\n\n".join(parts).strip()
    if len(body) > MAX_OPENAI_COMPAT_CONTEXT_CHARS:
        body = body[:MAX_OPENAI_COMPAT_CONTEXT_CHARS].rstrip()
    return body


def latest_openai_user_content(messages: list[Dict[str, str]]) -> str:
    for message in reversed(messages):
        if message["role"] == "user" and message["content"].strip():
            return message["content"].strip()
    for message in reversed(messages):
        if message["content"].strip():
            return message["content"].strip()
    return ""


def openai_compat_exact_literal_reply(messages: list[Dict[str, str]]) -> Optional[str]:
    latest = latest_openai_user_content(messages)
    if not latest:
        return None
    match = re.match(
        r"^\s*(?:reply|respond|answer)\s+exactly\s*(?::|\s+with|\s+)?\s*([A-Za-z0-9_.:-]{1,80})\s*[.!?]?\s*$",
        latest,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return match.group(1).strip()


def visible_openai_message_text(messages: list[Dict[str, str]]) -> str:
    return "\n\n".join(message["content"] for message in messages if message["content"].strip())


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


def dict_value(payload: object, key: str) -> str:
    if isinstance(payload, dict):
        value = payload.get(key)
        if value is not None:
            return str(value)
    return ""


def openai_chat_transport_metadata(payload: Dict[str, object]) -> Dict[str, str]:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    transport = payload.get("_eve_chat_transport") if isinstance(payload.get("_eve_chat_transport"), dict) else {}
    user_message = payload.get("user_message") if isinstance(payload.get("user_message"), dict) else {}
    return {
        "openwebui_chat_id": (
            dict_value(transport, "openwebui_chat_id")
            or dict_value(metadata, "chat_id")
            or dict_value(payload, "chat_id")
        ),
        "openwebui_user_message_id": (
            dict_value(transport, "openwebui_user_message_id")
            or dict_value(metadata, "user_message_id")
            or dict_value(user_message, "id")
        ),
        "openwebui_assistant_message_id": (
            dict_value(transport, "openwebui_assistant_message_id")
            or dict_value(metadata, "message_id")
            or dict_value(payload, "id")
        ),
        "origin": dict_value(transport, "origin"),
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
    chat_id = str(transport.get("openwebui_chat_id") or "").strip()
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


def openai_compat_auxiliary_ui_reply(messages: list[Dict[str, str]]) -> Optional[Dict[str, str]]:
    latest = latest_openai_user_content(messages)
    if not latest.startswith("### Task:") or "### Chat History:" not in latest:
        return None
    normalized = " ".join(latest.split()).lower()
    if "suggest 3-5 relevant follow-up questions" in normalized and '"follow_ups"' in normalized:
        return {
            "kind": "eve_chat_follow_ups",
            "body": json.dumps(
                {
                    "follow_ups": [
                        "What can you help me with right now?",
                        "Can you check your current status?",
                        "Can I upload a file for you to inspect?",
                    ]
                }
            ),
        }
    if "generate a concise, 3-5 word title" in normalized and '"title"' in normalized:
        return {
            "kind": "eve_chat_title",
            "body": json.dumps({"title": "Eve Chat"}),
        }
    if "generate 1-3 broad tags" in normalized and '"tags"' in normalized:
        return {
            "kind": "eve_chat_tags",
            "body": json.dumps({"tags": ["General"]}),
        }
    return None


def openai_chat_completion_payload(
    reply_text: str,
    *,
    model_id: str,
    prompt_text: str,
    thread_id: Optional[str] = None,
    reply_message_id: Optional[str] = None,
    extra_eve: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    completion_id = f"chatcmpl-eve-{uuid.uuid4().hex}"
    prompt_tokens = estimate_openai_token_count(prompt_text)
    completion_tokens = estimate_openai_token_count(reply_text)
    eve_metadata = {
        "thread_id": thread_id or "",
        "reply_message_id": reply_message_id or "",
        "interface": "eve_chat",
        "protocol": "local_chat_completions_v1",
        "provider": "eve_local_runtime",
        "provider_dependency": "none",
        "hosted_provider_used": False,
        "api_key_policy": "local_placeholder_only",
        "authority": "ui_adapter_only",
    }
    if extra_eve:
        eve_metadata.update(extra_eve)
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": openai_compat_created_at(),
        "model": model_id,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": reply_text,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "eve": eve_metadata,
    }


def agui_timestamp_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def agui_event(event_type: str, **fields: object) -> Dict[str, object]:
    event: Dict[str, object] = {
        "type": event_type,
        "timestamp": agui_timestamp_ms(),
    }
    event.update({key: value for key, value in fields.items() if value is not None})
    return event


def normalize_copilotkit_agui_messages(payload: Dict[str, object]) -> list[Dict[str, str]]:
    messages = payload.get("messages")
    input_payload = payload.get("input") if isinstance(payload.get("input"), dict) else {}
    if not messages and isinstance(input_payload, dict):
        messages = input_payload.get("messages")
    if not messages:
        prompt = (
            str(payload.get("prompt") or "")
            or (str(input_payload.get("prompt") or "") if isinstance(input_payload, dict) else "")
            or (str(input_payload.get("message") or "") if isinstance(input_payload, dict) else "")
        ).strip()
        if prompt:
            messages = [{"role": "user", "content": prompt}]
    return normalize_openai_chat_messages(messages)


def copilotkit_agui_context(payload: Dict[str, object]) -> Dict[str, object]:
    messages = normalize_copilotkit_agui_messages(payload)
    thread_id = str(payload.get("threadId") or payload.get("thread_id") or payload.get("chat_id") or "").strip()
    if not thread_id:
        thread_id = f"eve-chat-agui-thread-{uuid.uuid4().hex}"
    run_id = str(payload.get("runId") or payload.get("run_id") or "").strip()
    if not run_id:
        run_id = f"eve-chat-agui-run-{uuid.uuid4().hex}"
    client_request_id = str(payload.get("client_request_id") or payload.get("user") or run_id).strip() or run_id
    return {
        "thread_id": thread_id,
        "run_id": run_id,
        "client_request_id": client_request_id,
        "messages": messages,
        "latest_user": latest_openai_user_content(messages),
        "activity_message_id": f"activity-{run_id}",
        "text_message_id": f"msg-{run_id}",
        "openai_payload": {
            "model": str(payload.get("model") or OPENAI_COMPAT_MODEL_ID) or OPENAI_COMPAT_MODEL_ID,
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


def copilotkit_agui_progress_content(job: Optional[Dict[str, object]], *, status: str = "queued") -> Dict[str, object]:
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


def copilotkit_agui_completion_reply(completion: Dict[str, object]) -> tuple[str, str, Dict[str, object]]:
    choices = completion.get("choices") if isinstance(completion.get("choices"), list) else []
    first_choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = first_choice.get("message") if isinstance(first_choice.get("message"), dict) else {}
    eve_metadata = completion.get("eve") if isinstance(completion.get("eve"), dict) else {}
    reply_text = str(message.get("content") or "")
    reply_message_id = str(eve_metadata.get("reply_message_id") or completion.get("id") or f"msg-{uuid.uuid4().hex}")
    return reply_text, reply_message_id, eve_metadata


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


def infer_request_host_port(host_header: str, server_port: int) -> tuple[str, int]:
    host_header = str(host_header or "").strip()
    if not host_header:
        return "", int(server_port)
    if ":" in host_header:
        host, _, port_text = host_header.rpartition(":")
        try:
            return host or "", int(port_text)
        except ValueError:
            return host_header, int(server_port)
    return host_header, int(server_port)


def customized_windows_script(filename: str, primary_host: str, api_port: int) -> bytes:
    path = BIN_DIR / filename
    if not path.exists():
        raise FileNotFoundError(filename)
    text = path.read_text(encoding="utf-8")
    host_value = primary_host.replace('"', "`\"")
    if filename == "install_windows_eve.ps1":
        text = text.replace('[string]$PrimaryHost = "",', f'[string]$PrimaryHost = "{host_value}",', 1)
    elif filename == "update_windows_eve.ps1":
        text = text.replace('[Parameter(Mandatory = $true)][string]$PrimaryHost,', f'[string]$PrimaryHost = "{host_value}",', 1)
    text = text.replace('[int]$PrimaryApiPort = 8787,', f"[int]$PrimaryApiPort = {int(api_port)},", 1)
    return text.encode("utf-8")


def customized_windows_launcher(filename: str, primary_host: str, api_port: int) -> bytes:
    base_url = f"http://{primary_host}:{int(api_port)}"
    if filename == "install_windows_eve.cmd":
        script_name = "install_windows_eve.ps1"
        script_args = ""
    elif filename == "update_windows_eve.cmd":
        script_name = "update_windows_eve.ps1"
        script_args = " -IncludeCode -IncludeApp -AutoRestart -InstallAutoUpdateTask"
    else:
        raise FileNotFoundError(filename)
    script_url = f"{base_url}/downloads/{script_name}"
    launcher = f"""@echo off
setlocal
set "EVE_TMP=%TEMP%\\{script_name}"
echo Downloading Eve installer from {base_url}...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -UseBasicParsing '{script_url}' -OutFile $env:TEMP+'\\{script_name}'"
if errorlevel 1 (
  echo Failed to download {script_name}
  pause
  exit /b 1
)
echo Running {script_name}...
powershell -NoProfile -ExecutionPolicy Bypass -File "%EVE_TMP%"{script_args}
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
  echo Eve installer exited with code %EXITCODE%
  pause
)
exit /b %EXITCODE%
"""
    return launcher.encode("utf-8")


def build_unix_installer_script(platform_name: str, primary_host: str, api_port: int) -> bytes:
    if platform_name not in {"macos", "linux"}:
        raise ValueError(f"Unsupported platform installer: {platform_name}")
    host_literal = json.dumps(primary_host)
    install_root = "${HOME}/Applications/Eve" if platform_name == "macos" else "${HOME}/.local/share/eve"
    daemon_step = 'python3 eve.py daemon install || true'
    ollama_start = """\
start_ollama() {
  if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    return 0
  fi
"""
    if platform_name == "macos":
        platform_title = "macOS"
        script_name = "Install Eve.command"
        shell = "#!/bin/zsh"
        ollama_install = """\
if ! command -v ollama >/dev/null 2>&1; then
  echo "Installing Ollama..."
  if command -v brew >/dev/null 2>&1; then
    brew install ollama || true
  fi
fi
if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
fi
"""
        ollama_start += """\
  if command -v brew >/dev/null 2>&1; then
    brew services start ollama >/dev/null 2>&1 || true
  fi
  if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    nohup ollama serve >/tmp/eve_ollama_install.log 2>&1 &
  fi
"""
    else:
        platform_title = "Linux"
        script_name = "install_linux_eve.sh"
        shell = "#!/usr/bin/env bash"
        ollama_install = """\
if ! command -v ollama >/dev/null 2>&1; then
  echo "Installing Ollama..."
  curl -fsSL https://ollama.com/install.sh | sh
fi
"""
        ollama_start += """\
  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user start ollama >/dev/null 2>&1 || true
  fi
  if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    nohup ollama serve >/tmp/eve_ollama_install.log 2>&1 &
  fi
"""
    ollama_start += """\
  for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "Ollama did not start in time."
  return 1
}
"""
    script = f"""{shell}
set -euo pipefail

PRIMARY_HOST={host_literal}
PRIMARY_API_PORT={int(api_port)}
PRIMARY_OLLAMA_PORT=11434
BASE_URL="http://${{PRIMARY_HOST}}:${{PRIMARY_API_PORT}}"
INSTALL_ROOT="{install_root}"
TMP_DIR="$(mktemp -d)"
CODE_BUNDLE_PATH="${{TMP_DIR}}/eve_code_bundle.zip"

cleanup() {{
  rm -rf "${{TMP_DIR}}"
}}
trap cleanup EXIT

require_command() {{
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1"
    exit 1
  fi
}}

require_command curl
require_command python3

mkdir -p "${{INSTALL_ROOT}}"

echo "Downloading Eve code bundle from ${{BASE_URL}}..."
curl -fsSL "${{BASE_URL}}/api/code-bundle" -o "${{CODE_BUNDLE_PATH}}"

python3 - "${{CODE_BUNDLE_PATH}}" "${{INSTALL_ROOT}}" <<'PY'
import pathlib
import sys
import zipfile

archive_path = pathlib.Path(sys.argv[1])
install_root = pathlib.Path(sys.argv[2])
install_root.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(archive_path, "r") as archive:
    archive.extractall(install_root)
PY

cd "${{INSTALL_ROOT}}"

echo "Eve {platform_title} installer version: {MAC_INSTALLER_VERSION}"

echo "Initializing Eve..."
python3 eve.py init

echo "Pulling Eve bootstrap state from ${{BASE_URL}} using the primary host..."
python3 eve.py bootstrap pull --host "${{PRIMARY_HOST}}" --api-port "${{PRIMARY_API_PORT}}" --ollama-port "${{PRIMARY_OLLAMA_PORT}}" --use-primary-ollama

if [ "${{EVE_ENABLE_LOCAL_OLLAMA:-0}}" = "1" ]; then
{ollama_install}
{ollama_start}
  echo "Starting local Ollama because EVE_ENABLE_LOCAL_OLLAMA=1..."
  if start_ollama; then
    echo "Switching Eve to local Ollama and pulling models..."
    if python3 eve.py bootstrap pull --host "${{PRIMARY_HOST}}" --api-port "${{PRIMARY_API_PORT}}" --ollama-port "${{PRIMARY_OLLAMA_PORT}}" --pull-models; then
      echo "Eve is now configured to use local Ollama."
    else
      echo "Local model pull failed; Eve will stay pointed at the primary Ollama host for now."
      python3 eve.py bootstrap pull --host "${{PRIMARY_HOST}}" --api-port "${{PRIMARY_API_PORT}}" --ollama-port "${{PRIMARY_OLLAMA_PORT}}" --use-primary-ollama
    fi
  else
    echo "Local Ollama did not come up; Eve will stay pointed at the primary Ollama host for now."
  fi
else
  echo "Skipping automatic local Ollama startup. Set EVE_ENABLE_LOCAL_OLLAMA=1 if you want the installer to turn it on."
fi

echo "Installing Eve background service..."
{daemon_step}

echo "Running Eve doctor..."
if ! python3 eve.py doctor; then
  echo "Doctor reported a problem, but the install can still continue."
fi

echo
echo "Eve {platform_title} install completed at ${{INSTALL_ROOT}}."
"""
    return script.encode("utf-8")


def build_macos_installer_bundle(primary_host: str, api_port: int) -> bytes:
    stream = io.BytesIO()
    script_name = "Install Eve.command"
    readme = f"""Eve macOS Setup

1. Open {script_name}
2. Approve Terminal/network prompts if macOS asks
3. The installer will fetch Eve from http://{primary_host}:{int(api_port)}

Installer version: {MAC_INSTALLER_VERSION}
"""
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        script_info = zipfile.ZipInfo(script_name)
        script_info.external_attr = 0o755 << 16
        archive.writestr(script_info, build_unix_installer_script("macos", primary_host, api_port))
        readme_info = zipfile.ZipInfo("README.txt")
        readme_info.external_attr = 0o644 << 16
        archive.writestr(readme_info, readme.encode("utf-8"))
    return stream.getvalue()


def build_macos_installer_app_bundle(primary_host: str, api_port: int) -> bytes:
    app_name = MAC_INSTALLER_APP_NAME
    launcher_script = """#!/bin/zsh
set -euo pipefail

RESOURCE_DIR="$(cd "$(dirname "$0")/../Resources" && pwd)"
INSTALL_SCRIPT="${RESOURCE_DIR}/Install Eve.command"
chmod +x "${INSTALL_SCRIPT}"

osascript <<OSA
tell application "Terminal"
  activate
  do script quoted form of POSIX path of "${INSTALL_SCRIPT}"
end tell
OSA
"""
    installer_bundle_id = eve_profile.app_bundle_identifier("installer", MAC_INSTALLER_VERSION)
    info_plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>en</string>
  <key>CFBundleExecutable</key>
  <string>Eve Installer {MAC_INSTALLER_VERSION}</string>
  <key>CFBundleIconFile</key>
  <string>eve</string>
  <key>CFBundleIdentifier</key>
  <string>{installer_bundle_id}</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>Eve Installer {MAC_INSTALLER_VERSION}</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>{MAC_INSTALLER_VERSION}</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
</dict>
</plist>
"""
    readme = f"""Eve macOS Installer App

1. Open Eve Installer.app
2. Terminal will launch the installer
3. The installer will fetch Eve from http://{primary_host}:{int(api_port)}

Installer version: {MAC_INSTALLER_VERSION}
"""
    with tempfile.TemporaryDirectory(prefix="eve-mac-installer-") as temp_dir:
        root = Path(temp_dir)
        app_root = root / app_name
        contents_dir = app_root / "Contents"
        macos_dir = contents_dir / "MacOS"
        resources_dir = contents_dir / "Resources"
        macos_dir.mkdir(parents=True, exist_ok=True)
        resources_dir.mkdir(parents=True, exist_ok=True)

        launcher_path = macos_dir / "Eve Installer"
        launcher_path.write_text(launcher_script, encoding="utf-8")
        launcher_path.chmod(0o755)

        installer_script_path = resources_dir / "Install Eve.command"
        installer_script_path.write_bytes(build_unix_installer_script("macos", primary_host, api_port))
        installer_script_path.chmod(0o755)

        (contents_dir / "Info.plist").write_text(info_plist, encoding="utf-8")
        (resources_dir / "README.txt").write_text(readme, encoding="utf-8")

        icon_path = ROOT / "mac" / "generated" / "eve.icns"
        if icon_path.exists():
            shutil.copy2(icon_path, resources_dir / "eve.icns")

        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(app_root.rglob("*")):
                if not path.is_file():
                    continue
                archive.write(path, path.relative_to(root).as_posix())
        return stream.getvalue()


def build_linux_installer_bundle(primary_host: str, api_port: int) -> bytes:
    stream = io.BytesIO()
    script_name = "install_linux_eve.sh"
    readme = f"""Eve Linux Setup

1. Extract this archive
2. Run ./{script_name}
3. The installer will fetch Eve from http://{primary_host}:{int(api_port)}
"""
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        script_bytes = build_unix_installer_script("linux", primary_host, api_port)
        script_info = tarfile.TarInfo(script_name)
        script_info.size = len(script_bytes)
        script_info.mode = 0o755
        archive.addfile(script_info, io.BytesIO(script_bytes))

        readme_bytes = readme.encode("utf-8")
        readme_info = tarfile.TarInfo("README.txt")
        readme_info.size = len(readme_bytes)
        readme_info.mode = 0o644
        archive.addfile(readme_info, io.BytesIO(readme_bytes))
    return stream.getvalue()


def stage_windows_installer_payload(staging_dir: Path, primary_host: str, api_port: int) -> None:
    for relative in eve.iter_code_bundle_paths():
        source = ROOT / relative
        destination = staging_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    install_script = staging_dir / "bin" / "install_windows_eve.ps1"
    update_script = staging_dir / "bin" / "update_windows_eve.ps1"
    install_script.write_bytes(customized_windows_script("install_windows_eve.ps1", primary_host, api_port))
    update_script.write_bytes(customized_windows_script("update_windows_eve.ps1", primary_host, api_port))

    updater_cmd = (
        '@echo off\r\n'
        'setlocal\r\n'
        'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0bin\\update_windows_eve.ps1" -IncludeCode -IncludeApp -AutoRestart -InstallAutoUpdateTask\r\n'
    )
    (staging_dir / "Update Eve.cmd").write_text(updater_cmd, encoding="utf-8")


def build_windows_installer_script(payload_dir: Path, output_exe: Path, primary_host: str, api_port: int) -> str:
    output_path = str(output_exe).replace("/", "\\")
    payload_path = str(payload_dir).replace("/", "\\")
    install_args = (
        f'-NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\\bin\\install_windows_eve.ps1" '
        f'-ProjectRoot "$INSTDIR" -PrimaryHost "{primary_host}" -PrimaryApiPort {int(api_port)} -PullModels'
    )
    return f"""\
Unicode True
!include "LogicLib.nsh"
Name "Eve"
OutFile "{output_path}"
InstallDir "$LOCALAPPDATA\\Eve"
RequestExecutionLevel user
SetCompressor /SOLID lzma
ShowInstDetails show
ShowUninstDetails show

Page directory
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles

Section "Install"
  SetOutPath "$INSTDIR"
  File /r "{payload_path}\\*"
  WriteUninstaller "$INSTDIR\\Uninstall Eve.exe"
  CreateDirectory "$SMPROGRAMS\\Eve"
  CreateShortCut "$SMPROGRAMS\\Eve\\Update Eve.lnk" "$INSTDIR\\Update Eve.cmd"
  CreateShortCut "$DESKTOP\\Update Eve.lnk" "$INSTDIR\\Update Eve.cmd"
  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Eve" "DisplayName" "Eve"
  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Eve" "UninstallString" "$INSTDIR\\Uninstall Eve.exe"
  ClearErrors
  ExecWait '"$SYSDIR\\WindowsPowerShell\\v1.0\\powershell.exe" {install_args}' $0
  ${{If}} $0 != 0
    MessageBox MB_ICONEXCLAMATION|MB_OK "Eve copied its files, but the bootstrap step returned exit code $0. You can retry with $INSTDIR\\bin\\install_windows_eve.ps1."
  ${{EndIf}}
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\\Update Eve.lnk"
  Delete "$SMPROGRAMS\\Eve\\Update Eve.lnk"
  RMDir "$SMPROGRAMS\\Eve"
  DeleteRegKey HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Eve"
  Delete "$INSTDIR\\Uninstall Eve.exe"
  RMDir /r "$INSTDIR"
SectionEnd
"""


def build_windows_installer_exe(primary_host: str, api_port: int) -> bytes:
    with tempfile.TemporaryDirectory(prefix="eve-installer-") as temp_dir:
        root = Path(temp_dir)
        payload_dir = root / "payload"
        payload_dir.mkdir(parents=True, exist_ok=True)
        stage_windows_installer_payload(payload_dir, primary_host, api_port)
        output_exe = root / "EveSetup.exe"
        script_path = root / "EveSetup.nsi"
        script_path.write_text(
            build_windows_installer_script(payload_dir, output_exe, primary_host, api_port),
            encoding="utf-8",
        )
        result = subprocess.run(
            ["makensis", str(script_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0 or not output_exe.exists():
            detail = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
            raise RuntimeError(f"Could not build Windows installer.\n{detail.strip()}")
        return output_exe.read_bytes()


def build_windows_app_package_archive(primary_host: str, api_port: int) -> bytes:
    stream = io.BytesIO()
    with tempfile.TemporaryDirectory(prefix="eve-winpkg-") as temp_dir:
        payload_dir = Path(temp_dir) / "payload"
        payload_dir.mkdir(parents=True, exist_ok=True)
        stage_windows_installer_payload(payload_dir, primary_host, api_port)
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(payload_dir.rglob("*")):
                if not path.is_file():
                    continue
                archive.write(path, path.relative_to(payload_dir).as_posix())
    return stream.getvalue()


def render_windows_install_page(base_url: str, primary_host: str, api_port: int) -> bytes:
    installer_exe_url = f"{base_url}/downloads/EveSetup.exe"
    install_url = f"{base_url}/downloads/install_windows_eve.cmd"
    update_url = f"{base_url}/downloads/update_windows_eve.cmd"
    bootstrap_url = f"{base_url}/downloads/bootstrap_bundle.json"
    code_url = f"{base_url}/downloads/code-bundle.zip"
    app_package_url = f"{base_url}/downloads/EveWindowsAppPackage.zip"
    install_command = "EveSetup.exe"
    update_command = (
        f"update_windows_eve.cmd"
    )
    advanced_install_command = (
        f"powershell -ExecutionPolicy Bypass -File .\\install_windows_eve.ps1 "
        f"-PrimaryHost {primary_host} -PrimaryApiPort {api_port} -PullModels"
    )
    advanced_update_command = (
        f"powershell -ExecutionPolicy Bypass -File .\\update_windows_eve.ps1 "
        f"-PrimaryHost {primary_host} -PrimaryApiPort {api_port} -IncludeCode -IncludeApp -AutoRestart"
    )
    html = f"""\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Eve Windows Prototype</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5f0e7;
      --card: #fffaf2;
      --ink: #1c1a17;
      --muted: #6f6456;
      --line: #d8c8b4;
      --accent: #0b6e4f;
      --accent-2: #d96c2d;
    }}
    body {{ margin: 0; font-family: Georgia, "Iowan Old Style", serif; background: radial-gradient(circle at top, #fff9ef, var(--bg)); color: var(--ink); }}
    main {{ max-width: 920px; margin: 0 auto; padding: 40px 20px 64px; }}
    .hero {{ padding: 28px; border: 1px solid var(--line); background: linear-gradient(135deg, rgba(11,110,79,.08), rgba(217,108,45,.10)); border-radius: 20px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; margin-top: 20px; }}
    .card {{ background: var(--card); border: 1px solid var(--line); border-radius: 18px; padding: 18px; }}
    a.button {{ display: inline-block; margin-top: 10px; padding: 10px 14px; border-radius: 999px; background: var(--accent); color: #fffaf2; text-decoration: none; font-weight: 600; }}
    a.secondary {{ background: var(--accent-2); }}
    code, pre {{ font-family: "SFMono-Regular", Consolas, monospace; }}
    pre {{ white-space: pre-wrap; background: #f2eadf; border-radius: 14px; padding: 14px; border: 1px solid var(--line); overflow-x: auto; }}
    p.meta {{ color: var(--muted); }}
    ul {{ padding-left: 20px; }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <p class="meta">Primary Eve host: {html_escape(primary_host)}:{api_port}</p>
      <h1>Windows Eve Prototype</h1>
      <p>Use this page from the Windows browser to download the installer, updater, bootstrap bundle, or the current application code bundle directly from this Mac.</p>
    </section>
    <section class="grid">
      <div class="card">
        <h2>Installer</h2>
        <p>Downloads a real Windows installer executable that already knows how to connect back to this Mac.</p>
        <a class="button" href="{html_escape(installer_exe_url)}">Download EveSetup.exe</a>
      </div>
      <div class="card">
        <h2>Updater</h2>
        <p>Downloads a Windows launcher for later updates from this Mac.</p>
        <a class="button secondary" href="{html_escape(update_url)}">Download Easy Updater</a>
      </div>
      <div class="card">
        <h2>Bootstrap</h2>
        <p>Downloads the current Eve identity/context bootstrap payload as JSON.</p>
        <a class="button" href="{html_escape(bootstrap_url)}">Download Bootstrap JSON</a>
      </div>
      <div class="card">
        <h2>Code Bundle</h2>
        <p>Downloads the current Eve application code bundle as a zip archive.</p>
        <a class="button secondary" href="{html_escape(code_url)}">Download Code Bundle</a>
      </div>
      <div class="card">
        <h2>App Package</h2>
        <p>Downloads the current Windows app payload bundle used by the updater for full app-file refreshes.</p>
        <a class="button" href="{html_escape(app_package_url)}">Download App Package</a>
      </div>
    </section>
    <section class="card" style="margin-top: 20px;">
      <h2>Quick Start</h2>
      <p>After downloading <code>EveSetup.exe</code> to the Windows machine, double-click it or run:</p>
      <pre>{html_escape(install_command)}</pre>
      <p>To pull later updates including code, download and run:</p>
      <pre>{html_escape(update_command)}</pre>
      <p>Advanced/manual downloads:</p>
      <p><a href="{html_escape(install_url)}">Installer launcher (.cmd)</a></p>
      <pre>{html_escape(advanced_install_command)}</pre>
      <pre>{html_escape(advanced_update_command)}</pre>
      <ul>
        <li><code>-PullModels</code> downloads the configured models into local Ollama on Windows.</li>
        <li><code>-UsePrimaryOllama</code> points the Windows machine at this Mac's Ollama host instead of downloading models locally.</li>
        <li><code>-IncludeCode</code> updates local Eve code files and stores backups under <code>.eve/code_update_backups/</code>.</li>
        <li><code>-IncludeApp</code> refreshes the installed Windows app payload with the external app-package helper.</li>
      </ul>
    </section>
  </main>
</body>
</html>
"""
    return html.encode("utf-8")


def render_install_page(base_url: str, primary_host: str, api_port: int) -> bytes:
    windows_url = f"{base_url}/downloads/EveSetup.exe"
    macos_url = f"{base_url}/downloads/{MAC_INSTALLER_FILENAME}"
    macos_script_url = f"{base_url}/downloads/EveMacSetup.zip"
    linux_url = f"{base_url}/downloads/EveLinuxSetup.tar.gz"
    windows_page_url = f"{base_url}/install/windows"
    html = f"""\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Eve Installer Downloads</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f3ede2;
      --paper: rgba(255, 250, 242, 0.88);
      --paper-strong: #fffaf2;
      --ink: #191612;
      --muted: #6a6051;
      --line: rgba(81, 67, 50, 0.16);
      --accent: #0a6a58;
      --accent-strong: #084d40;
      --accent-soft: rgba(10, 106, 88, 0.12);
      --warm: #b85c31;
      --warm-soft: rgba(184, 92, 49, 0.12);
      --shadow: 0 24px 80px rgba(44, 27, 7, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Georgia, "Iowan Old Style", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 12% 18%, rgba(10, 106, 88, 0.14), transparent 30%),
        radial-gradient(circle at 85% 12%, rgba(184, 92, 49, 0.16), transparent 28%),
        linear-gradient(180deg, #fbf6ed 0%, var(--bg) 58%, #ece3d4 100%);
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image:
        linear-gradient(rgba(25, 22, 18, 0.04) 1px, transparent 1px),
        linear-gradient(90deg, rgba(25, 22, 18, 0.04) 1px, transparent 1px);
      background-size: 34px 34px;
      mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.12), transparent 70%);
    }}
    main {{
      width: min(1120px, calc(100% - 32px));
      margin: 0 auto;
      padding: 24px 0 72px;
      position: relative;
      z-index: 1;
    }}
    .masthead {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 14px 18px;
      margin-bottom: 20px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(255, 250, 242, 0.72);
      backdrop-filter: blur(14px);
    }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }}
    .mark {{
      width: 42px;
      height: 42px;
      border-radius: 50%;
      display: grid;
      place-items: center;
      font-size: 18px;
      color: #fff;
      background:
        radial-gradient(circle at 30% 30%, #2dc39e, transparent 34%),
        linear-gradient(145deg, var(--accent), var(--accent-strong));
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.35);
    }}
    .brand h1 {{
      margin: 0;
      font-size: 1rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .brand p {{
      margin: 2px 0 0;
      color: var(--muted);
      font-size: 0.95rem;
    }}
    .host-pill {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 10px 14px;
      border-radius: 999px;
      background: var(--paper-strong);
      border: 1px solid var(--line);
      color: var(--muted);
      font-size: 0.94rem;
      white-space: nowrap;
    }}
    .status-dot {{
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: var(--accent);
      box-shadow: 0 0 0 5px var(--accent-soft);
    }}
    .hero {{
      position: relative;
      overflow: hidden;
      padding: 42px;
      min-height: 420px;
      border-radius: 32px;
      background:
        radial-gradient(circle at 78% 22%, rgba(255, 255, 255, 0.72), transparent 22%),
        radial-gradient(circle at 80% 80%, rgba(184, 92, 49, 0.20), transparent 26%),
        linear-gradient(140deg, rgba(10, 106, 88, 0.95), rgba(8, 77, 64, 0.95) 48%, rgba(20, 33, 30, 0.98));
      box-shadow: var(--shadow);
      color: #fff7ee;
    }}
    .hero::after {{
      content: "";
      position: absolute;
      inset: auto -8% -28% auto;
      width: 380px;
      height: 380px;
      border-radius: 50%;
      background:
        radial-gradient(circle at 50% 50%, rgba(255, 255, 255, 0.24), transparent 40%),
        radial-gradient(circle at 35% 35%, rgba(255, 214, 184, 0.52), transparent 30%);
      opacity: 0.95;
      filter: blur(6px);
    }}
    .hero-grid {{
      position: relative;
      z-index: 1;
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(290px, 0.8fr);
      gap: 28px;
      align-items: end;
    }}
    .eyebrow {{
      margin: 0 0 14px;
      color: rgba(255, 247, 238, 0.76);
      text-transform: uppercase;
      letter-spacing: 0.14em;
      font-size: 0.82rem;
    }}
    .hero h2 {{
      margin: 0;
      max-width: 10ch;
      font-size: clamp(2.8rem, 7vw, 5.8rem);
      line-height: 0.92;
      letter-spacing: -0.06em;
    }}
    .hero-copy {{
      max-width: 36rem;
      margin: 18px 0 0;
      font-size: 1.12rem;
      line-height: 1.6;
      color: rgba(255, 247, 238, 0.86);
    }}
    .hero-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 24px;
    }}
    a.button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 10px;
      min-height: 48px;
      padding: 0 18px;
      border-radius: 999px;
      border: 1px solid transparent;
      background: #fff7ee;
      color: var(--accent-strong);
      text-decoration: none;
      font-weight: 700;
      transition: transform 160ms ease, background 160ms ease, border-color 160ms ease;
    }}
    a.button:hover {{
      transform: translateY(-1px);
    }}
    a.button.secondary {{
      background: transparent;
      color: #fff7ee;
      border-color: rgba(255, 247, 238, 0.28);
    }}
    .hero-panel {{
      align-self: stretch;
      padding: 22px;
      border-radius: 24px;
      background: rgba(255, 250, 242, 0.10);
      border: 1px solid rgba(255, 247, 238, 0.14);
      backdrop-filter: blur(10px);
    }}
    .hero-panel h3 {{
      margin: 0 0 12px;
      font-size: 1rem;
      color: rgba(255, 247, 238, 0.74);
      text-transform: uppercase;
      letter-spacing: 0.12em;
    }}
    .hero-panel ul {{
      list-style: none;
      padding: 0;
      margin: 0;
      display: grid;
      gap: 12px;
    }}
    .hero-panel li {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      padding-bottom: 12px;
      border-bottom: 1px solid rgba(255, 247, 238, 0.14);
    }}
    .hero-panel li:last-child {{
      padding-bottom: 0;
      border-bottom: 0;
    }}
    .hero-panel strong {{
      display: block;
      font-size: 1rem;
      color: #fff7ee;
    }}
    .hero-panel span {{
      color: rgba(255, 247, 238, 0.68);
      font-size: 0.92rem;
    }}
    .hero-panel em {{
      font-style: normal;
      color: #ffd4bd;
      white-space: nowrap;
    }}
    .section-head {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 20px;
      align-items: end;
      margin: 34px 0 16px;
    }}
    .section-head h3 {{
      margin: 0;
      font-size: clamp(1.8rem, 4vw, 2.6rem);
      letter-spacing: -0.05em;
    }}
    .section-head p {{
      margin: 0;
      max-width: 34rem;
      color: var(--muted);
      line-height: 1.55;
    }}
    .platform-list {{
      display: grid;
      gap: 16px;
    }}
    .platform {{
      display: grid;
      grid-template-columns: minmax(0, 1.3fr) minmax(220px, 0.9fr) auto;
      gap: 20px;
      align-items: center;
      padding: 24px;
      border: 1px solid var(--line);
      border-radius: 26px;
      background: var(--paper);
      backdrop-filter: blur(12px);
      box-shadow: 0 14px 42px rgba(44, 27, 7, 0.08);
    }}
    .platform.kicker-windows {{
      background:
        linear-gradient(0deg, rgba(255, 250, 242, 0.92), rgba(255, 250, 242, 0.92)),
        linear-gradient(90deg, rgba(10, 106, 88, 0.16), transparent 40%);
    }}
    .platform.kicker-macos {{
      background:
        linear-gradient(0deg, rgba(255, 250, 242, 0.92), rgba(255, 250, 242, 0.92)),
        linear-gradient(90deg, rgba(184, 92, 49, 0.14), transparent 40%);
    }}
    .platform.kicker-linux {{
      background:
        linear-gradient(0deg, rgba(255, 250, 242, 0.92), rgba(255, 250, 242, 0.92)),
        linear-gradient(90deg, rgba(37, 64, 138, 0.12), transparent 40%);
    }}
    .platform-tag {{
      display: inline-block;
      margin-bottom: 10px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.14em;
      font-size: 0.78rem;
    }}
    .platform h4 {{
      margin: 0 0 10px;
      font-size: 1.6rem;
      letter-spacing: -0.04em;
    }}
    .platform p {{
      margin: 0;
      color: var(--muted);
      line-height: 1.55;
    }}
    .platform ul {{
      list-style: none;
      padding: 0;
      margin: 0;
      display: grid;
      gap: 8px;
      color: var(--ink);
      font-size: 0.96rem;
    }}
    .platform li::before {{
      content: "•";
      color: var(--accent);
      margin-right: 10px;
    }}
    .platform-actions {{
      display: grid;
      justify-items: end;
      gap: 10px;
    }}
    .platform-actions a {{
      white-space: nowrap;
    }}
    .link-inline {{
      color: var(--accent-strong);
      text-decoration-color: rgba(8, 77, 64, 0.24);
      font-weight: 600;
    }}
    .network {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 16px;
      margin-top: 18px;
    }}
    .network-item {{
      padding: 18px 20px;
      border-radius: 20px;
      border: 1px solid var(--line);
      background: rgba(255, 250, 242, 0.78);
    }}
    .network-item strong {{
      display: block;
      margin-bottom: 8px;
      font-size: 0.9rem;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--muted);
    }}
    .network-item code {{
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 0.96rem;
      word-break: break-word;
    }}
    .footnote {{
      margin-top: 12px;
      color: var(--muted);
      line-height: 1.55;
    }}
    @media (max-width: 900px) {{
      .masthead,
      .section-head,
      .platform,
      .hero-grid,
      .network {{
        grid-template-columns: 1fr;
      }}
      .masthead {{
        border-radius: 24px;
      }}
      .platform-actions {{
        justify-items: start;
      }}
      .host-pill {{
        white-space: normal;
      }}
    }}
    @media (max-width: 640px) {{
      main {{
        width: min(100% - 20px, 100%);
        padding-top: 12px;
      }}
      .hero {{
        padding: 28px 22px;
        min-height: 0;
      }}
      .hero h2 {{
        max-width: none;
      }}
      .platform {{
        padding: 20px;
      }}
      .network-item code {{
        font-size: 0.9rem;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <header class="masthead">
      <div class="brand">
        <div class="mark">E</div>
        <div>
          <h1>Eve Installer</h1>
          <p>One page. Pick the machine. Download the right build.</p>
        </div>
      </div>
      <div class="host-pill">
        <span class="status-dot"></span>
        Serving from {html_escape(primary_host)}:{api_port}
      </div>
    </header>

    <section class="hero">
      <div class="hero-grid">
        <div>
          <p class="eyebrow">Cross-platform bootstrap</p>
          <h2>Bring Eve onto any system.</h2>
          <p class="hero-copy">Open this page from the target machine, choose its operating system, and download an installer that already knows how to connect back to this Mac.</p>
          <div class="hero-actions">
            <a class="button" href="{html_escape(windows_url)}">Windows Installer</a>
            <a class="button secondary" href="{html_escape(macos_url)}">macOS Installer</a>
          </div>
        </div>
        <aside class="hero-panel">
          <h3>What this page gives you</h3>
          <ul>
            <li>
              <div>
                <strong>Host-aware installers</strong>
                <span>Each download is already pointed at this Eve host.</span>
              </div>
              <em>Ready now</em>
            </li>
            <li>
              <div>
                <strong>Prototype-friendly setup</strong>
                <span>Good for testing on your Mac, a PC, or a Linux box on the same network.</span>
              </div>
              <em>LAN flow</em>
            </li>
            <li>
              <div>
                <strong>Direct access to deeper tools</strong>
                <span>Windows detail page, fallback script bundles, and raw update assets stay available.</span>
              </div>
              <em>No hunting</em>
            </li>
          </ul>
        </aside>
      </div>
    </section>

    <section>
      <div class="section-head">
        <div>
          <h3>Choose the target system</h3>
          <p>Each path is tuned for a different machine, but they all start from this same Eve host.</p>
        </div>
      </div>
      <div class="platform-list">
        <article class="platform kicker-windows">
          <div>
            <span class="platform-tag">Windows</span>
            <h4>Best for the PC prototype</h4>
            <p>Downloads the real Windows installer executable and sets up Eve to call back to this Mac for bootstrap, updates, and app refreshes.</p>
          </div>
          <ul>
            <li>One-click `EveSetup.exe` install flow</li>
            <li>Auto-update path for code and app payloads</li>
            <li>Dedicated detail page for advanced Windows tools</li>
          </ul>
          <div class="platform-actions">
            <a class="button" href="{html_escape(windows_url)}">Download EveSetup.exe</a>
            <a class="link-inline" href="{html_escape(windows_page_url)}">Open Windows detail page</a>
          </div>
        </article>

        <article class="platform kicker-macos">
          <div>
            <span class="platform-tag">macOS</span>
            <h4>Double-click installer app</h4>
            <p>Downloads the versioned macOS installer app bundle for another Mac, with a fallback script bundle available if Gatekeeper or app launch gets in the way.</p>
          </div>
          <ul>
            <li>Installer app is versioned to avoid stale cache confusion</li>
            <li>Falls back to the primary Ollama host when needed</li>
            <li>Script bundle still available for manual recovery</li>
          </ul>
          <div class="platform-actions">
            <a class="button" href="{html_escape(macos_url)}">Download {html_escape(MAC_INSTALLER_FILENAME)}</a>
            <a class="link-inline" href="{html_escape(macos_script_url)}">Get script bundle instead</a>
          </div>
        </article>

        <article class="platform kicker-linux">
          <div>
            <span class="platform-tag">Linux</span>
            <h4>Host-aware setup bundle</h4>
            <p>Downloads a Linux archive with an install script that bootstraps Eve against this machine, then switches into local services where available.</p>
          </div>
          <ul>
            <li>Good fit for a test box or sidecar node</li>
            <li>Native Linux bootstrap and local runtime layout</li>
            <li>Small, inspectable shell-based install path</li>
          </ul>
          <div class="platform-actions">
            <a class="button" href="{html_escape(linux_url)}">Download EveLinuxSetup.tar.gz</a>
          </div>
        </article>
      </div>
    </section>

    <section>
      <div class="section-head">
        <div>
          <h3>On this network</h3>
          <p>Use the direct address from the target machine. If hostname resolution is flaky, the raw LAN IP is the most direct route.</p>
        </div>
      </div>
      <div class="network">
        <div class="network-item">
          <strong>Install page</strong>
          <code>{html_escape(base_url)}/install</code>
        </div>
        <div class="network-item">
          <strong>Primary host</strong>
          <code>{html_escape(primary_host)}:{api_port}</code>
        </div>
        <div class="network-item">
          <strong>Mac installer version</strong>
          <code>{html_escape(MAC_INSTALLER_VERSION)}</code>
        </div>
      </div>
      <p class="footnote">Open this page on the machine you want to install to, not just on the primary Mac. That keeps the flow simple: download, run, and let Eve connect back here.</p>
    </section>
  </main>
</body>
</html>
"""
    return html.encode("utf-8")


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
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def clamp_percent(value: float) -> float:
    return round(max(0.0, min(100.0, float(value))), 1)


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
    return first or command[:48]


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
        processes.append(
            {
                "pid": safe_int(pid),
                "ppid": safe_int(ppid),
                "title": process_title(command),
                "kind": kind,
                "cpu_percent": round(cpu_percent, 1),
                "memory_bytes": rss_bytes,
                "command": text_preview(command, 180),
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


class TTLCache:
    def __init__(self, ttl_seconds: float):
        self.ttl_seconds = ttl_seconds
        self._value: Optional[object] = None
        self._expires_at = 0.0

    def get(self) -> Optional[object]:
        if self._value is None:
            return None
        if time.monotonic() >= self._expires_at:
            self.clear()
            return None
        return copy.deepcopy(self._value)

    def set(self, value: object) -> object:
        self._value = copy.deepcopy(value)
        self._expires_at = time.monotonic() + self.ttl_seconds
        return copy.deepcopy(value)

    def clear(self) -> None:
        self._value = None
        self._expires_at = 0.0


class EveRuntimeService:
    def __init__(self, status_ttl_seconds: float = 2.0, model_health_ttl_seconds: float = 5.0, activity_ttl_seconds: float = 1.0):
        self._status_cache = TTLCache(status_ttl_seconds)
        self._model_health_cache = TTLCache(model_health_ttl_seconds)
        self._activity_cache = TTLCache(activity_ttl_seconds)
        self._mutation_lock = threading.RLock()
        self._status_refresh_lock = threading.Lock()
        self._model_health_refresh_lock = threading.Lock()
        self._activity_refresh_lock = threading.Lock()
        self._followup_workers_lock = threading.Lock()
        self._active_followup_workers: set[str] = set()
        self._sensory_sessions_lock = threading.RLock()
        self._sensory_sessions: Dict[str, Dict[str, object]] = {}

    def invalidate_caches(self) -> None:
        self._status_cache.clear()
        self._model_health_cache.clear()
        self._activity_cache.clear()

    def _run_mutation(self, operation):
        with self._mutation_lock:
            try:
                return operation()
            finally:
                self.invalidate_caches()

    @staticmethod
    def _sensory_database_path() -> Path:
        runtime_path = eve.RUNTIME_OPERATIONAL_DB_PATH
        if runtime_path.exists() or eve.running_from_runtime_bundle():
            return runtime_path
        return eve.OPERATIONAL_DB_PATH

    def _sensory_session_observation_stats(self, session_id: str) -> tuple[int, Optional[str]]:
        """Read durable count/last time without trusting process-local counters.

        Browser observations add a short binding suffix to the session
        correlation id, while hardware adapters use the exact session id. The
        generated session id cannot contain wildcard characters, but using a
        prefix comparison rather than ``LIKE`` keeps the accounting literal.
        """
        prefix = f"{session_id}:"
        with eve_db.connect_database(self._sensory_database_path()) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS event_count, MAX(created_at) AS last_event_at
                  FROM events
                 WHERE stream = 'sensory'
                   AND kind = 'sensory.observed'
                   AND (correlation_id = ? OR substr(correlation_id, 1, ?) = ?)
                """,
                (session_id, len(prefix), prefix),
            ).fetchone()
        return (
            int(row["event_count"] if row is not None else 0),
            str(row["last_event_at"]) if row is not None and row["last_event_at"] else None,
        )

    def _sensory_session_observation_count(self, session_id: str) -> int:
        return self._sensory_session_observation_stats(session_id)[0]

    def _write_sensory_observations(
        self,
        record: Dict[str, object],
        events: list[Dict[str, object]],
    ) -> tuple[list[Dict[str, object]], int]:
        """Atomically enforce the durable session budget and append a batch.

        The Go hardware adapter uses the same ``.lock`` file and count query.
        Keeping the count and inserts under that cross-process writer lock
        prevents browser and hardware observations from racing past the shared
        5,000-feature session budget.
        """
        db_path = self._sensory_database_path()
        eve_db.initialize_database(db_path)
        session_id = str(record.get("session_id") or "")
        prefix = f"{session_id}:"
        written: list[Dict[str, object]] = []
        with eve_db.single_writer_lock(db_path):
            with eve_db.connect_database(db_path) as conn:
                stopped = conn.execute(
                    "SELECT COUNT(*) AS stop_count FROM events "
                    "WHERE correlation_id = ? AND kind = 'sensory.session.stopped'",
                    (session_id,),
                ).fetchone()
                expires_at = eve.parse_iso_datetime(record.get("expires_at"))
                if (
                    (stopped is not None and int(stopped["stop_count"] or 0) > 0)
                    or expires_at is None
                    or expires_at <= datetime.now(timezone.utc)
                ):
                    raise ValueError("sensory session is not active")
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS event_count
                      FROM events
                     WHERE stream = 'sensory'
                       AND kind = 'sensory.observed'
                       AND (correlation_id = ? OR substr(correlation_id, 1, ?) = ?)
                    """,
                    (session_id, len(prefix), prefix),
                ).fetchone()
                existing = int(row["event_count"] if row is not None else 0)
                if existing + len(events) > SENSORY_SESSION_MAX_EVENTS:
                    raise ValueError("sensory session event budget exceeded")
                for event in events:
                    stored = eve_db.normalize_event_record(
                        {
                            "id": str(uuid.uuid4()),
                            "created_at": eve_db.utc_now(),
                            "source": str(event.get("source") or "private_device_adapter"),
                            "actor": "eve-sensory-adapter",
                            "kind": "sensory.observed",
                            "stream": "sensory",
                            "subject": str(event.get("subject") or "local_scene"),
                            "correlation_id": str(event.get("correlation_id") or session_id),
                            "payload": {"event": event},
                            "metadata": {
                                "session_id": session_id,
                                "persistence": "features_only",
                                "raw_device_capture_persisted": False,
                                "authority": "observation_only",
                            },
                        }
                    )
                    conn.execute(
                        """
                        INSERT INTO events
                            (id, created_at, source, actor, kind, stream, subject, correlation_id,
                             causation_id, schema_version, payload_json, metadata_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            stored["id"],
                            stored["created_at"],
                            stored["source"],
                            stored["actor"],
                            stored["kind"],
                            stored["stream"],
                            stored["subject"],
                            stored["correlation_id"],
                            stored["causation_id"],
                            stored["schema_version"],
                            json.dumps(stored["payload"], ensure_ascii=True, sort_keys=True),
                            json.dumps(stored["metadata"], ensure_ascii=True, sort_keys=True),
                        ),
                    )
                    written.append(stored)
                conn.commit()
        return written, existing + len(written)

    def _prune_sensory_sessions(self, *, now: Optional[datetime] = None) -> None:
        current = now or datetime.now(timezone.utc)
        expired: list[str] = []
        for session_id, record in self._sensory_sessions.items():
            expires_at = eve.parse_iso_datetime(record.get("expires_at"))
            if record.get("status") != "active" or expires_at is None or expires_at <= current:
                expired.append(session_id)
        for session_id in expired:
            self._sensory_sessions.pop(session_id, None)

    def _rehydrate_sensory_session(self, session_id: str) -> Optional[Dict[str, object]]:
        """Recover an authorized session after a local backend restart.

        Only a one-way token hash is durable. The browser still has to present
        the original high-entropy token, and a later stop event closes the
        session. Raw sensor material is never part of this recovery record.
        """
        if not session_id:
            return None
        records = eve_db.read_events(
            self._sensory_database_path(),
            limit=12,
            stream="sensory",
            correlation_id=session_id,
        )
        if any(item.get("kind") == "sensory.session.stopped" for item in records):
            return None
        boundary = next((item for item in records if item.get("kind") == "sensory.session.started"), None)
        if not isinstance(boundary, dict):
            return None
        payload = boundary.get("payload") if isinstance(boundary.get("payload"), dict) else {}
        metadata = boundary.get("metadata") if isinstance(boundary.get("metadata"), dict) else {}
        public = payload.get("session") if isinstance(payload.get("session"), dict) else {}
        expires_at = eve.parse_iso_datetime(public.get("expires_at"))
        token_hash = str(metadata.get("session_token_hash") or "")
        modalities = [
            str(item)
            for item in (public.get("modalities") or [])
            if str(item) in SENSORY_SESSION_MODALITIES
        ]
        if expires_at is None or expires_at <= datetime.now(timezone.utc) or not token_hash or not modalities:
            return None
        accepted_events, last_event_at = self._sensory_session_observation_stats(session_id)
        return {
            "session_id": session_id,
            "token_hash": token_hash,
            "created_at": public.get("created_at") or boundary.get("created_at"),
            "expires_at": expires_at.replace(microsecond=0).isoformat(),
            "status": "active",
            "modalities": modalities,
            "purpose": public.get("purpose") or "Recovered bounded local sensory session.",
            "accepted_events": accepted_events,
            "last_event_at": last_event_at,
            "batch_times": [],
            "last_integrated_monotonic": 0.0,
        }

    @staticmethod
    def _public_sensory_session(record: Dict[str, object]) -> Dict[str, object]:
        return {
            "schema_version": "eve.sensory_session.v1",
            "session_id": record.get("session_id"),
            "created_at": record.get("created_at"),
            "expires_at": record.get("expires_at"),
            "status": record.get("status"),
            "modalities": list(record.get("modalities") or []),
            "purpose": record.get("purpose"),
            "accepted_events": int(record.get("accepted_events") or 0),
            "last_event_at": record.get("last_event_at"),
            "privacy": {
                "persistence": "features_only",
                "raw_audio_retained": False,
                "raw_images_retained": False,
                "raw_screen_retained": False,
                "transcripts_retained": False,
                "keystrokes_retained": False,
            },
            "authority": "observation_only",
        }

    def sensory_status(self) -> Dict[str, object]:
        with self._sensory_sessions_lock:
            self._prune_sensory_sessions()
            active_records = [
                item for item in self._sensory_sessions.values() if item.get("status") == "active"
            ]
        # Hardware adapters write through the same durable event spine but do
        # not share this Python process's counters. Refresh public truth before
        # reporting status so Go observations are not hidden until a browser
        # batch happens to arrive.
        for item in active_records:
            count, last_event_at = self._sensory_session_observation_stats(
                str(item.get("session_id") or "")
            )
            with self._sensory_sessions_lock:
                item["accepted_events"] = count
                if last_event_at:
                    item["last_event_at"] = last_event_at
        sessions = [self._public_sensory_session(item) for item in active_records]
        frame = eve.load_sensory_frame(prefer_runtime=True)
        return {
            "schema_version": "eve.sensory_adapter_status.v1",
            "generated_at": eve.utc_now(),
            "active_sessions": sessions,
            "active_session_count": len(sessions),
            "latest_frame": frame,
            "capture_default": "off",
            "boundary": eve_sensory.BOUNDARY,
        }

    def start_sensory_session(self, payload: Dict[str, object]) -> Dict[str, object]:
        if payload.get("operator_confirmed") is not True:
            raise ValueError("operator_confirmed=true is required to start private sensors")
        raw_modalities = payload.get("modalities")
        if not isinstance(raw_modalities, list) or not raw_modalities:
            raise ValueError("modalities must be a non-empty array")
        modalities: list[str] = []
        for item in raw_modalities:
            modality = str(item or "").strip().lower()
            if modality == "touch":
                modality = "proprioceptive"
            if modality not in SENSORY_SESSION_MODALITIES:
                raise ValueError(f"unsupported sensory modality: {modality or 'missing'}")
            if modality not in modalities:
                modalities.append(modality)
        purpose = " ".join(str(payload.get("purpose") or "").split())[:240]
        if not purpose:
            raise ValueError("a bounded sensory purpose is required")
        try:
            requested_duration = int(payload.get("duration_seconds") or 600)
        except (TypeError, ValueError) as exc:
            raise ValueError("duration_seconds must be an integer") from exc
        duration_seconds = max(
            SENSORY_SESSION_MIN_SECONDS,
            min(SENSORY_SESSION_MAX_SECONDS, requested_duration),
        )
        now = datetime.now(timezone.utc).replace(microsecond=0)
        session_id = f"sensory-{uuid.uuid4()}"
        token = secrets.token_urlsafe(32)
        record: Dict[str, object] = {
            "session_id": session_id,
            "token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=duration_seconds)).isoformat(),
            "status": "active",
            "modalities": modalities,
            "purpose": purpose,
            "accepted_events": 0,
            "last_event_at": None,
            "batch_times": [],
            "last_integrated_monotonic": 0.0,
        }
        with self._sensory_sessions_lock:
            self._prune_sensory_sessions(now=now)
            active_count = sum(
                1 for item in self._sensory_sessions.values() if item.get("status") == "active"
            )
            if active_count >= SENSORY_SESSION_MAX_ACTIVE:
                raise ValueError("too many active sensory sessions")
            self._sensory_sessions[session_id] = record
        eve_db.record_event(
            self._sensory_database_path(),
            kind="sensory.session.started",
            source="eve_chat_sensor_control",
            actor="user",
            stream="sensory",
            subject="private_device_session",
            correlation_id=session_id,
            payload={"session": self._public_sensory_session(record)},
            metadata={
                "operator_confirmed": True,
                "session_token_hash": record["token_hash"],
                "session_expires_at": record["expires_at"],
                "admitted_modalities": modalities,
                "persistence": "features_only",
                "raw_device_capture_persisted": False,
                "authority": "observation_only",
            },
        )
        result = self._public_sensory_session(record)
        result["session_token"] = token
        return result

    def _authorized_sensory_session(self, session_id: object, token: object) -> Dict[str, object]:
        normalized_id = str(session_id or "").strip()
        supplied_token = str(token or "").strip()
        if not normalized_id or not supplied_token:
            raise ValueError("session_id and session_token are required")
        with self._sensory_sessions_lock:
            self._prune_sensory_sessions()
            record = self._sensory_sessions.get(normalized_id)
        if not isinstance(record, dict):
            record = self._rehydrate_sensory_session(normalized_id)
            if isinstance(record, dict):
                with self._sensory_sessions_lock:
                    self._sensory_sessions[normalized_id] = record
        if not isinstance(record, dict) or record.get("status") != "active":
            raise ValueError("sensory session is not active")
        with self._sensory_sessions_lock:
            expected = str(record.get("token_hash") or "")
            actual = hashlib.sha256(supplied_token.encode("utf-8")).hexdigest()
            if not expected or not secrets.compare_digest(expected, actual):
                raise ValueError("sensory session token is invalid")
            return record

    def stop_sensory_session(self, payload: Dict[str, object]) -> Dict[str, object]:
        record = self._authorized_sensory_session(
            payload.get("session_id"),
            payload.get("session_token"),
        )
        public = self._public_sensory_session({**record, "status": "stopped"})
        with self._sensory_sessions_lock:
            self._sensory_sessions.pop(str(record.get("session_id")), None)
        eve_db.record_event(
            self._sensory_database_path(),
            kind="sensory.session.stopped",
            source="eve_chat_sensor_control",
            actor="user",
            stream="sensory",
            subject="private_device_session",
            correlation_id=str(record.get("session_id") or ""),
            payload={"session": public},
            metadata={"persistence": "features_only", "raw_device_capture_persisted": False},
        )
        return public

    def ingest_sensory_events(self, payload: Dict[str, object]) -> Dict[str, object]:
        record = self._authorized_sensory_session(
            payload.get("session_id"),
            payload.get("session_token"),
        )
        now = datetime.now(timezone.utc).replace(microsecond=0)
        monotonic_now = time.monotonic()
        with self._sensory_sessions_lock:
            recent_batches = [
                float(item)
                for item in (record.get("batch_times") or [])
                if monotonic_now - float(item) <= 10.0
            ]
            if len(recent_batches) >= SENSORY_SESSION_MAX_BATCHES_PER_10_SECONDS:
                raise ValueError("sensory adapter rate limit exceeded")
            recent_batches.append(monotonic_now)
            record["batch_times"] = recent_batches

        events = eve_sensory.normalize_adapter_batch(
            payload.get("events"),
            allowed_modalities=record.get("modalities") or [],
            session_id=str(record.get("session_id") or ""),
            now=now,
        )
        created_at = eve.parse_iso_datetime(record.get("created_at"))
        expires_at = eve.parse_iso_datetime(record.get("expires_at"))
        if created_at is None or expires_at is None:
            raise ValueError("sensory session timing evidence is invalid")
        for event in events:
            observed_at = eve.parse_iso_datetime(event.get("observed_at"))
            if (
                observed_at is None
                or observed_at < created_at - timedelta(seconds=5)
                or observed_at > now + timedelta(seconds=5)
                or observed_at > expires_at
            ):
                raise ValueError("sensory event timestamp is outside the current session")
        written, durable_count = self._write_sensory_observations(record, events)
        with self._sensory_sessions_lock:
            record["accepted_events"] = durable_count

        last_integrated = float(record.get("last_integrated_monotonic") or 0.0)
        should_integrate = bool(
            (last_integrated <= 0.0 or monotonic_now - last_integrated >= 3.0)
            and any(
                max(
                    float(item.get("change") or 0),
                    float(item.get("novelty") or 0),
                    float(item.get("urgency") or 0),
                )
                >= 65
                for item in events
            )
        )
        integrated_cycle_id = ""
        if should_integrate:
            state = eve.load_state(prefer_runtime=True)
            frame = eve.run_sensory_attention_tick(
                eve.load_config(),
                state,
                source="sensory_adapter_ingest",
                prefer_runtime=True,
                now=now,
            )
            eve.save_state(state)
            conscious = eve.build_recurrent_conscious_state(
                source="chat_sensory_adapter",
                sensory_frame_override=frame,
            )
            integrated_cycle_id = str(conscious.get("cycle_id") or "")
            record["last_integrated_monotonic"] = monotonic_now

        with self._sensory_sessions_lock:
            record["last_event_at"] = now.isoformat()
        return {
            "schema_version": "eve.sensory_ingest_result.v1",
            "accepted": len(events),
            "event_ids": [item.get("id") for item in written],
            "integrated": bool(integrated_cycle_id),
            "conscious_cycle_id": integrated_cycle_id,
            "persistence": "features_only",
            "raw_content_retained": False,
        }

    def _find_message(self, message_id: str) -> tuple[list[Dict[str, object]], Dict[str, object]]:
        messages = eve.read_messages()
        try:
            index = eve.find_record_index(messages, message_id)
        except SystemExit as exc:
            raise LookupError(str(exc)) from exc
        return messages, messages[index]

    def ordered_thread_summaries(self, limit: Optional[int] = None, status: Optional[str] = None) -> list[Dict[str, object]]:
        summaries = list(reversed(eve.read_thread_summaries()))
        if status:
            summaries = [item for item in summaries if item.get("status") == status]
        if limit is not None:
            summaries = summaries[:limit]
        return summaries

    def activity_entries(self, limit: int) -> list[Dict[str, object]]:
        return eve.read_entries(limit=limit, exclude_kinds=sorted(eve.LOW_SIGNAL_ENTRY_KINDS))

    def _build_model_health_payload(self, limit: int = 5) -> Dict[str, object]:
        status = eve.load_model_watchdog_status(prefer_runtime=True) or load_json_file(MODEL_WATCHDOG_STATUS_PATH)
        health_log_path = RUNTIME_MODEL_HEALTH_LOG_PATH if RUNTIME_MODEL_HEALTH_LOG_PATH.exists() else MODEL_HEALTH_LOG_PATH
        recent = read_recent_jsonl(health_log_path, limit=limit)
        config = eve.load_config()
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
        lane_records = eve.model_lane_records(config, watchdog_status=status)
        host_records = eve.model_host_records(config, watchdog_status=status)
        summary_parts = [f"Fast {effective_fast or 'unknown'}", f"Deep {effective_deep or 'unknown'}", eve.model_lanes_summary(lane_records)]
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

    def model_health_payload(self, limit: int = 5, force: bool = False) -> Dict[str, object]:
        if not force:
            cached = self._model_health_cache.get()
            if cached is not None:
                return cached
        with self._model_health_refresh_lock:
            if not force:
                cached = self._model_health_cache.get()
                if cached is not None:
                    return cached
            return self._model_health_cache.set(self._build_model_health_payload(limit=limit))

    def _build_activity_payload(self, model_health: Optional[Dict[str, object]] = None) -> Dict[str, object]:
        model_health = model_health if isinstance(model_health, dict) else self.model_health_payload(limit=5)
        lanes = model_health.get("lanes") if isinstance(model_health.get("lanes"), list) else []
        active_store = eve.load_active_model_calls(prefer_runtime=True)
        active_calls = active_store.get("calls") if isinstance(active_store.get("calls"), list) else []
        recent_events = eve.read_perf_events(limit=18, since_minutes=180, category="model_call")
        recent_calls = [model_call_event_to_monitor_json(item) for item in reversed(recent_events) if isinstance(item, dict)]
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

    def activity_payload(self, model_health: Optional[Dict[str, object]] = None, force: bool = False) -> Dict[str, object]:
        if not force:
            cached = self._activity_cache.get()
            if cached is not None:
                return cached
        with self._activity_refresh_lock:
            if not force:
                cached = self._activity_cache.get()
                if cached is not None:
                    return cached
            return self._activity_cache.set(self._build_activity_payload(model_health=model_health))

    def _build_latest_state(self) -> Dict[str, object]:
        config = eve.load_config()
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
        threads = self.ordered_thread_summaries(limit=24)
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
        model_health = self.model_health_payload(limit=5)
        active_reply = eve.latest_reply_progress(active_only=True)
        return {
            "api_version": API_VERSION,
            "config": config,
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

    def latest_state(self, force: bool = False) -> Dict[str, object]:
        if not force:
            cached = self._status_cache.get()
            if cached is not None:
                return cached
        with self._status_refresh_lock:
            if not force:
                cached = self._status_cache.get()
                if cached is not None:
                    return cached
            return self._status_cache.set(self._build_latest_state())

    def bootstrap_payload(
        self,
        primary_host: str = "",
        api_port: int = 8787,
        ollama_port: int = 11434,
    ) -> Dict[str, object]:
        return eve.bootstrap_bundle_payload(
            primary_host=primary_host,
            api_port=api_port,
            ollama_port=ollama_port,
        )

    def update_manifest(
        self,
        primary_host: str = "",
        api_port: int = 8787,
        ollama_port: int = 11434,
    ) -> Dict[str, object]:
        payload = eve.build_update_manifest(
            primary_host=primary_host,
            api_port=api_port,
            ollama_port=ollama_port,
        )
        if primary_host:
            app_package = build_windows_app_package_archive(primary_host, api_port)
            payload["app_package"] = {
                "sha256": hashlib.sha256(app_package).hexdigest(),
                "bytes": len(app_package),
                "filename": "EveWindowsAppPackage.zip",
            }
        return payload

    def code_bundle_archive(self) -> bytes:
        return eve.build_code_bundle_archive()

    def windows_app_package_archive(self, primary_host: str, api_port: int) -> bytes:
        return build_windows_app_package_archive(primary_host, api_port)

    def last_active_thread_id(self, threads: list[Dict[str, object]]) -> Optional[str]:
        for thread in threads:
            if thread.get("status") != "archived":
                return str(thread.get("thread_id"))
        return None

    def wake_eve_if_needed(self) -> Dict[str, object]:
        def operation() -> Dict[str, object]:
            config = eve.load_config()
            state = eve.load_state()
            now = datetime.now(timezone.utc)
            started_daemon = False

            if not daemon_running_from_state(state):
                try:
                    eve.start_launch_agent()
                except SystemExit:
                    eve.install_launch_agent()
                    eve.start_launch_agent()
                started_daemon = True

            state = eve.load_state()
            last_loop = eve.parse_iso_datetime(state.get("last_loop_at"))
            should_wake = started_daemon or last_loop is None or now - last_loop > timedelta(minutes=5) or not state.get("current_focus")
            completed: list[str] = []
            outreach_record: Optional[Dict[str, object]] = None

            if should_wake:
                state["last_loop_at"] = eve.utc_now()
                state["last_outreach_check_at"] = eve.utc_now()
                try:
                    result = eve.generate_continuous_thought(
                        config,
                        context_limit=int(config["thought_context_limit"]),
                        thought_history_limit=int(config["thought_history_limit"]),
                        max_tokens=int(config["thought_max_tokens"]),
                    )
                    eve.append_entry(
                        "thought",
                        str(result["response"]),
                        metadata={
                            "model": result["model"],
                            "source_entries": result["source_entries"],
                            "source_thoughts": result["source_thoughts"],
                            "source_threads": result["source_threads"],
                            "source_messages": result["source_messages"],
                            "source": "web_wake",
                        },
                    )
                    state["last_loop_at"] = eve.utc_now()
                    state["last_thought_at"] = eve.utc_now()
                    state["current_focus"] = " ".join(str(result["response"]).split())[:160]
                    completed.append("thought")
                except SystemExit as exc:
                    eve.append_entry("wake_error", f"wake thought failed: {exc}", metadata={"source": "web"})

                try:
                    outreach_record = eve.create_eve_outreach_message(
                        config,
                        source="web_wake",
                        notify=False,
                        allow_none=True,
                        state=state,
                    )
                    if outreach_record is not None:
                        state["last_outreach_at"] = eve.utc_now()
                        completed.append("outreach")
                except SystemExit as exc:
                    eve.append_entry("wake_error", f"wake outreach failed: {exc}", metadata={"source": "web"})
                    eve.record_personal_conversation_check(
                        source="web_wake",
                        status="failed",
                        reason=f"Personal conversation check failed: {exc}",
                        state=state,
                    )

                threads = eve.read_thread_summaries(limit=24)
                state["thread_attention"] = threads
                state["active_thread_count"] = len([item for item in threads if item.get("status") != "archived"])
                eve.save_state(state)

            threads = self.ordered_thread_summaries(limit=24)
            return {
                "status": self.latest_state(force=True),
                "completed": completed,
                "selected_thread_id": str(outreach_record["thread_id"]) if outreach_record else self.last_active_thread_id(threads),
                "awakened": bool(should_wake),
            }

        return self._run_mutation(operation)

    def threads(self, limit: int = 30, status: Optional[str] = None, audience: Optional[str] = None) -> list[Dict[str, object]]:
        threads = self.ordered_thread_summaries(limit=limit, status=status)
        if audience:
            threads = [item for item in threads if str(item.get("audience") or "user") == audience]
        return [thread_to_json(item) for item in threads]

    def reply_progress(
        self,
        client_request_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        active_only: bool = True,
    ) -> Dict[str, object]:
        progress = eve.latest_reply_progress(
            client_request_id=client_request_id,
            thread_id=thread_id,
            active_only=active_only,
        )
        return {"job": reply_progress_to_json(progress)}

    def reply_turn_replays(
        self,
        limit: int = 20,
        thread_id: Optional[str] = None,
        reply_message_id: Optional[str] = None,
    ) -> list[Dict[str, object]]:
        records = eve.read_reply_turn_replays(
            limit=limit,
            thread_id=thread_id,
            reply_message_id=reply_message_id,
            prefer_runtime=True,
        )
        return [reply_turn_replay_to_monitor_json(item) for item in records]

    def reply_council_turns(
        self,
        limit: int = 20,
        thread_id: Optional[str] = None,
        reply_message_id: Optional[str] = None,
    ) -> list[Dict[str, object]]:
        records = eve.read_reply_council_turns(
            limit=limit,
            thread_id=thread_id,
            reply_message_id=reply_message_id,
            prefer_runtime=True,
        )
        return [reply_council_turn_to_monitor_json(item) for item in records]

    def conversation_spine(
        self,
        limit: int = 20,
        thread_id: Optional[str] = None,
        role: Optional[str] = None,
        direction: Optional[str] = None,
        include_synthetic: bool = True,
    ) -> list[Dict[str, object]]:
        records = eve.read_conversation_spine_turns(
            limit=limit,
            thread_id=thread_id,
            role=role,
            direction=direction,
            include_synthetic=include_synthetic,
            prefer_runtime=True,
        )
        return [conversation_spine_turn_to_monitor_json(item) for item in records]

    def messages(
        self,
        limit: int = 30,
        sender: Optional[str] = None,
        recipient: Optional[str] = None,
        status: Optional[str] = None,
        thread_id: Optional[str] = None,
        initiated: bool = False,
        personal: bool = False,
    ) -> list[Dict[str, object]]:
        messages = eve.read_messages(
            limit=None if initiated or personal else limit,
            sender=sender,
            recipient=recipient,
            status=status,
            thread_id=thread_id,
        )
        if initiated:
            messages = [
                item
                for item in messages
                if item.get("sender") == "eve"
                and item.get("recipient") == "user"
                and (
                    not item.get("reply_to")
                    or str(item.get("kind") or "") == "proactive_outreach"
                    or "update" in str(item.get("kind") or "")
                    or "outreach" in str(item.get("kind") or "")
                )
            ]
        if personal:
            messages = [
                item
                for item in messages
                if eve.message_is_personal_conversation(item)
            ]
        if initiated or personal:
            messages = messages[-limit:]
        return [message_to_json(item) for item in messages]

    def personal_conversation_status(self) -> Dict[str, object]:
        return eve.personal_conversation_status_payload()

    def open_message(self, message_id: str) -> Dict[str, object]:
        _, message = self._find_message(message_id)
        if message.get("recipient") == "user" and message.get("status") == "unread":
            def operation() -> Dict[str, object]:
                return message_to_json(eve.update_message_record(message_id, status="read"))

            return self._run_mutation(operation)
        return message_to_json(message)

    def thread_messages(self, thread_id: str) -> list[Dict[str, object]]:
        messages = eve.read_messages(thread_id=thread_id)
        return [message_to_json(item) for item in messages]

    def proposals(self, limit: int = 20, status: Optional[str] = None) -> list[Dict[str, object]]:
        proposals = eve.read_proposals(limit=limit, status=status)
        return [proposal_to_json(item) for item in proposals]

    def governance(self, limit: int = 20, runtime: bool = True) -> Dict[str, object]:
        return eve.governance_status_payload(limit=limit, prefer_runtime=runtime)

    def reflections(self, limit: int = 10) -> list[Dict[str, object]]:
        return [entry_to_json(item) for item in eve.read_entries_by_kind("reflection", limit=limit)]

    def thoughts(self, limit: int = 10) -> list[Dict[str, object]]:
        return [entry_to_json(item) for item in eve.read_entries_by_kind("thought", limit=limit)]

    def tensions(self, limit: int = 10, status: Optional[str] = None) -> list[Dict[str, object]]:
        return [tension_to_json(item) for item in eve.read_tensions(limit=limit, status=status)]

    def experiments(self, limit: int = 10, status: Optional[str] = None) -> list[Dict[str, object]]:
        return [experiment_to_json(item) for item in eve.read_experiments(limit=limit, status=status)]

    def evaluations(
        self,
        limit: int = 20,
        target_kind: Optional[str] = None,
        target_id: Optional[str] = None,
        evaluator: Optional[str] = None,
        thread_id: Optional[str] = None,
        since_days: Optional[int] = None,
    ) -> list[Dict[str, object]]:
        evaluations = eve.read_evaluations(
            limit=limit,
            target_kind=target_kind,
            target_id=target_id,
            evaluator=evaluator,
            thread_id=thread_id,
            since_days=since_days,
        )
        return [evaluation_to_json(item) for item in evaluations]

    def outcomes(
        self,
        limit: int = 20,
        target_kind: Optional[str] = None,
        target_id: Optional[str] = None,
        direction: Optional[str] = None,
        thread_id: Optional[str] = None,
        since_days: Optional[int] = None,
    ) -> list[Dict[str, object]]:
        outcomes = eve.read_outcomes(
            limit=limit,
            target_kind=target_kind,
            target_id=target_id,
            direction=direction,
            thread_id=thread_id,
            since_days=since_days,
        )
        return [outcome_to_json(item) for item in outcomes]

    def failure_clusters(self, limit: int = 20, status: Optional[str] = None, since_days: Optional[int] = None) -> list[Dict[str, object]]:
        clusters = eve.read_failure_clusters(limit=limit, status=status, since_days=since_days)
        return [failure_cluster_to_json(item) for item in clusters]

    def activity(self, limit: int = 20) -> list[Dict[str, object]]:
        return [entry_to_json(item) for item in self.activity_entries(limit=limit)]

    def monitor_status_payload(self) -> Dict[str, object]:
        status = self.latest_state()
        counts = status.get("counts") if isinstance(status.get("counts"), dict) else {}
        daemon = status.get("daemon") if isinstance(status.get("daemon"), dict) else {}
        model_health = status.get("model_health") if isinstance(status.get("model_health"), dict) else {}
        lanes = model_health.get("lanes") if isinstance(model_health.get("lanes"), list) else []
        loaded_models = model_health.get("loaded_models") if isinstance(model_health.get("loaded_models"), list) else []
        probes = model_health.get("probes") if isinstance(model_health.get("probes"), dict) else {}
        threads = status.get("thread_attention") if isinstance(status.get("thread_attention"), list) else []
        return {
            "api_version": status.get("api_version") or API_VERSION,
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

    def monitor_payload(self, compact: bool = False) -> Dict[str, object]:
        status = self.monitor_status_payload()
        activity = self.activity_payload(status.get("model_health") if isinstance(status.get("model_health"), dict) else None)
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
            "conversation_spine": self.conversation_spine(limit=12, include_synthetic=False),
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

    def ask(
        self,
        body: str,
        subject: str = "Question from user",
        client_request_id: Optional[str] = None,
        attachments: Optional[list[Dict[str, object]]] = None,
        config_overrides: Optional[Dict[str, object]] = None,
        message_metadata: Optional[Dict[str, object]] = None,
        thread_id: Optional[str] = None,
    ) -> Dict[str, object]:
        body = body.strip()
        raw_attachments = attachments or []
        if attachments is not None and not isinstance(attachments, list):
            raise ValueError("attachments must be a list")
        if not body and raw_attachments:
            body = "Please inspect the attached file{}.".format("" if len(raw_attachments) == 1 else "s")
        subject = subject.strip() or "Question from user"
        if not body:
            raise ValueError("Message body is required")

        def operation() -> Dict[str, object]:
            config = eve.load_config()
            if config_overrides:
                config = dict(config)
                config.update(config_overrides)
            user_message = eve.create_message(
                sender="user",
                recipient="eve",
                subject=subject,
                body=body,
                kind="user_message",
                thread_id=thread_id or None,
                status="sent",
                metadata=message_metadata or {},
            )
            attachment_records = record_attachments_for_message(
                raw_attachments,
                user_message,
                client_request_id=client_request_id,
            )
            if attachment_records:
                user_message = eve.update_message_record(
                    str(user_message["id"]),
                    body=message_body_with_attachment_evidence(body, attachment_records),
                    metadata=attachment_metadata(attachment_records),
                )
            reply = eve.generate_eve_reply(config, user_message, client_request_id=client_request_id)
            thread = eve.read_messages(thread_id=str(user_message["thread_id"]))
            return {
                "thread_id": user_message["thread_id"],
                "reply": message_to_json(reply),
                "messages": [message_to_json(item) for item in thread],
            }

        return self._run_mutation(operation)

    def initiate_personal_message(self, allow_none: bool = False, notify: bool = True) -> Dict[str, object]:
        def operation() -> Dict[str, object]:
            config = eve.load_config()
            record = eve.create_eve_outreach_message(
                config,
                source="monitor_personal",
                notify=notify,
                allow_none=allow_none,
            )
            if record is None:
                return {
                    "thread_id": None,
                    "reply": None,
                    "messages": [],
                }
            thread = eve.read_messages(thread_id=str(record["thread_id"]))
            return {
                "thread_id": record["thread_id"],
                "reply": message_to_json(record),
                "messages": [message_to_json(item) for item in thread],
            }

        return self._run_mutation(operation)

    def reply(
        self,
        message_id: str,
        body: str,
        subject: Optional[str] = None,
        client_request_id: Optional[str] = None,
        attachments: Optional[list[Dict[str, object]]] = None,
    ) -> Dict[str, object]:
        message_id = message_id.strip()
        body = body.strip()
        raw_attachments = attachments or []
        if attachments is not None and not isinstance(attachments, list):
            raise ValueError("attachments must be a list")
        if not body and raw_attachments:
            body = "Please inspect the attached file{}.".format("" if len(raw_attachments) == 1 else "s")
        if not message_id or not body:
            raise ValueError("message_id and body are required")

        def operation() -> Dict[str, object]:
            _, target = self._find_message(message_id)
            config = eve.load_config()
            user_message = eve.create_message(
                sender="user",
                recipient="eve",
                subject=(subject or f"Re: {target.get('subject') or 'Conversation'}").strip(),
                body=body,
                kind="user_reply",
                thread_id=str(target["thread_id"]),
                reply_to=str(target["id"]),
                status="sent",
            )
            attachment_records = record_attachments_for_message(
                raw_attachments,
                user_message,
                client_request_id=client_request_id,
            )
            if attachment_records:
                user_message = eve.update_message_record(
                    str(user_message["id"]),
                    body=message_body_with_attachment_evidence(body, attachment_records),
                    metadata=attachment_metadata(attachment_records),
                )
            reply = eve.generate_eve_reply(config, user_message, client_request_id=client_request_id)
            thread = eve.read_messages(thread_id=str(target["thread_id"]))
            return {
                "thread_id": target["thread_id"],
                "reply": message_to_json(reply),
                "messages": [message_to_json(item) for item in thread],
            }

        return self._run_mutation(operation)

    def attachments(
        self,
        thread_id: Optional[str] = None,
        message_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[Dict[str, object]]:
        return read_attachment_records(thread_id=thread_id, message_id=message_id, limit=limit)

    def upload_attachment(self, payload: Dict[str, object]) -> Dict[str, object]:
        return upload_attachment_from_json(payload)

    def openai_models(self) -> Dict[str, object]:
        return {
            "object": "list",
            "data": [openai_model_record()],
        }

    def openai_model(self, model_id: str) -> Dict[str, object]:
        model_id = str(model_id or "").strip() or OPENAI_COMPAT_MODEL_ID
        if model_id not in OPENAI_COMPAT_MODEL_ALIASES:
            raise LookupError(f"Unknown Eve Chat model: {model_id}")
        return openai_model_record(OPENAI_COMPAT_MODEL_ID)

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
        action = eve_chat_followup_action_for_messages(messages)
        if action not in EVE_CHAT_FOLLOWUP_SUPPORTED_ACTIONS:
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
        self.start_eve_chat_followup_worker(str(followup["id"]))
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
            self.start_eve_chat_followup_worker(str(record.get("id") or ""))
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
                    time.sleep(min(EVE_CHAT_FOLLOWUP_WAIT_SLICE_SECONDS, seconds_until_due))
                    continue
                claim = eve.claim_eve_chat_followup_record(
                    followup_id,
                    worker_id=worker_id,
                    lease_seconds=EVE_CHAT_FOLLOWUP_LEASE_SECONDS,
                )
                if claim.get("claimed"):
                    record = claim.get("record") if isinstance(claim.get("record"), dict) else record
                    break
                if claim.get("reason") == "terminal":
                    return
                if claim.get("reason") in {"leased", "not_due"}:
                    time.sleep(EVE_CHAT_FOLLOWUP_WAIT_SLICE_SECONDS)
                    continue
                return

            config = eve.load_config()
            action = str(record.get("requested_action") or "service_health_check")
            if action not in EVE_CHAT_FOLLOWUP_SUPPORTED_ACTIONS:
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

            result = recover_eve_chat_followup_action_result(record)
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
            delivery_message = self._existing_eve_chat_followup_delivery(followup_id, thread_id)
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
            completed_cycle = self._complete_eve_chat_followup_cycle(
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

    def openai_chat_completion(self, payload: Dict[str, object]) -> Dict[str, object]:
        requested_model = str(payload.get("model") or OPENAI_COMPAT_MODEL_ID).strip() or OPENAI_COMPAT_MODEL_ID
        if requested_model not in OPENAI_COMPAT_MODEL_ALIASES:
            raise ValueError(f"Unsupported Eve Chat model: {requested_model}")
        messages = normalize_openai_chat_messages(payload.get("messages"))
        exact_literal_reply = openai_compat_exact_literal_reply(messages)
        if exact_literal_reply is not None:
            return openai_chat_completion_payload(
                exact_literal_reply,
                model_id=OPENAI_COMPAT_MODEL_ID,
                prompt_text=latest_openai_user_content(messages),
                extra_eve={
                    "exact_literal_reply": True,
                    "conversation_recorded": False,
                },
            )
        auxiliary_reply = openai_compat_auxiliary_ui_reply(messages)
        if auxiliary_reply:
            auxiliary_prompt = latest_openai_user_content(messages)
            return openai_chat_completion_payload(
                auxiliary_reply["body"],
                model_id=OPENAI_COMPAT_MODEL_ID,
                prompt_text=auxiliary_prompt,
                extra_eve={
                    "auxiliary_ui_task": auxiliary_reply["kind"],
                    "conversation_recorded": False,
                },
            )
        transport = openai_chat_transport_metadata(payload)
        evaluation_metadata = openai_chat_evaluation_metadata(payload)
        followup_requested = eve_chat_followup_requested(messages)
        should_queue_followup = bool(
            followup_requested and not evaluation_metadata.get("synthetic")
        )
        thread_id = openai_chat_thread_id(transport)
        eve_body = openai_messages_to_eve_body(messages)
        client_request_id = (
            str(
                payload.get("user")
                or payload.get("client_request_id")
                or payload.get("id")
                or transport.get("openwebui_assistant_message_id")
                or transport.get("openwebui_user_message_id")
                or ""
            ).strip()
            or f"eve-chat-{uuid.uuid4().hex}"
        )
        result = self.ask(
            eve_body,
            subject="Eve Chat conversation",
            client_request_id=client_request_id,
            config_overrides=OPENAI_COMPAT_REPLY_CONFIG_OVERRIDES,
            message_metadata={
                **eve.self_operational_message_metadata(
                    direction="eve_chat_ui_to_eve",
                    surface="eve_chat_ui",
                    authority="ui_adapter_only",
                    openwebui_chat_id=transport.get("openwebui_chat_id", ""),
                    openwebui_thread_id=thread_id or "",
                ),
                **evaluation_metadata,
            },
            thread_id=thread_id,
        )
        followup: Optional[Dict[str, object]] = None
        if should_queue_followup:
            followup = self.queue_eve_chat_followup(
                messages=messages,
                result=result,
                client_request_id=client_request_id,
                transport=transport,
                evaluation_metadata=evaluation_metadata,
            )
        reply = result.get("reply") if isinstance(result.get("reply"), dict) else {}
        reply_text = str(reply.get("body") or "")
        extra_eve: Dict[str, object] = {}
        if followup:
            reply_text = str(followup.get("ack_text") or reply_text)
            extra_eve = {
                "eve_chat_followup_queued": True,
                "eve_chat_followup_id": str(followup.get("id") or ""),
                "eve_chat_followup_action": str(followup.get("requested_action") or ""),
                "eve_chat_followup_delivery": "polling_api",
            }
        elif followup_requested and evaluation_metadata.get("synthetic"):
            extra_eve = {
                "eve_chat_followup_queued": False,
                "eve_chat_followup_suppressed": "synthetic_evaluator_isolation",
            }
        return openai_chat_completion_payload(
            reply_text,
            model_id=OPENAI_COMPAT_MODEL_ID,
            prompt_text=eve_body,
            thread_id=str(result.get("thread_id") or ""),
            reply_message_id=str(reply.get("id") or ""),
            extra_eve=extra_eve,
        )

    def mark_message(self, message_id: str, status: str) -> Dict[str, object]:
        if status not in {"unread", "read", "archived", "sent"}:
            raise ValueError("Invalid message status")

        def operation() -> Dict[str, object]:
            try:
                message = eve.update_message_record(message_id, status=status)
            except SystemExit as exc:
                raise LookupError(str(exc)) from exc
            return message_to_json(message)

        return self._run_mutation(operation)

    def update_proposal_status(self, proposal_id: str, status: str) -> Dict[str, object]:
        if status not in {"draft", "approved", "rejected", "applied", "archived"}:
            raise ValueError("Invalid proposal status")

        def operation() -> Dict[str, object]:
            try:
                proposal = eve.update_proposal_record(proposal_id, status=status)
            except SystemExit as exc:
                raise LookupError(str(exc)) from exc
            eve.append_entry(
                "proposal_updated",
                f"{proposal['title']} -> {proposal['status']}",
                metadata={"proposal_id": proposal["id"], "status": proposal["status"], "source": "web"},
            )
            return proposal_to_json(proposal)

        return self._run_mutation(operation)

    def think(self) -> Dict[str, object]:
        def operation() -> Dict[str, object]:
            config = eve.load_config()
            result = eve.generate_continuous_thought(
                config,
                context_limit=int(config["thought_context_limit"]),
                thought_history_limit=int(config["thought_history_limit"]),
                max_tokens=int(config["thought_max_tokens"]),
            )
            entry = eve.append_entry(
                "thought",
                str(result["response"]),
                metadata={
                    "model": result["model"],
                    "source_entries": result["source_entries"],
                    "source_thoughts": result["source_thoughts"],
                    "source_threads": result["source_threads"],
                    "source_messages": result["source_messages"],
                    "source": "web",
                },
            )
            state = eve.load_state()
            state["last_thought_at"] = eve.utc_now()
            state["current_focus"] = " ".join(str(result["response"]).split())[:160]
            eve.save_state(state)
            return {"thought": entry_to_json(entry)}

        return self._run_mutation(operation)

    def reflect(self) -> Dict[str, object]:
        def operation() -> Dict[str, object]:
            config = eve.load_config()
            result = eve.generate_reflection(
                config,
                days=int(config["reflection_days"]),
                context_limit=int(config["reflection_context_limit"]),
                max_tokens=int(config["reflection_max_tokens"]),
            )
            entry = eve.append_entry(
                "reflection",
                str(result["response"]),
                metadata={"days": int(config["reflection_days"]), "model": result["model"], "source": "web"},
            )
            return {"reflection": entry_to_json(entry)}

        try:
            return self._run_mutation(operation)
        except SystemExit as exc:
            raise ValueError(str(exc)) from exc

    def suggest_proposal(self) -> Dict[str, object]:
        def operation() -> Dict[str, object]:
            config = eve.load_config()
            proposal = eve.suggest_proposal(
                config,
                source="web",
                max_tokens=int(config["proposal_max_tokens"]),
            )
            return proposal_to_json(proposal)

        try:
            return self._run_mutation(operation)
        except SystemExit as exc:
            raise ValueError(str(exc)) from exc

    def capture(self, kind: str, text: str, raw_tags: object) -> Dict[str, object]:
        kind = kind.strip() or "note"
        text = text.strip()
        if kind not in CAPTURE_KINDS:
            raise ValueError("Invalid capture kind")
        if not text:
            raise ValueError("Capture text is required")

        if isinstance(raw_tags, str):
            tags = [item for item in raw_tags.split() if item]
        elif isinstance(raw_tags, list):
            tags = [str(item).strip() for item in raw_tags if str(item).strip()]
        else:
            tags = []

        def operation() -> Dict[str, object]:
            entry = eve.append_entry(kind, text, tags=tags, metadata={"source": "web"})
            return {"entry": entry_to_json(entry)}

        return self._run_mutation(operation)

    def daemon_start(self) -> Dict[str, object]:
        def operation() -> Dict[str, object]:
            eve.start_launch_agent()
            return self.latest_state(force=True)

        try:
            return self._run_mutation(operation)
        except SystemExit as exc:
            raise ValueError(str(exc)) from exc

    def daemon_stop(self) -> Dict[str, object]:
        def operation() -> Dict[str, object]:
            eve.stop_launch_agent()
            return self.latest_state(force=True)

        try:
            return self._run_mutation(operation)
        except SystemExit as exc:
            raise ValueError(str(exc)) from exc


_DEFAULT_SERVICE: Optional[EveRuntimeService] = None
_DEFAULT_SERVICE_LOCK = threading.Lock()


def get_runtime_service() -> EveRuntimeService:
    global _DEFAULT_SERVICE
    with _DEFAULT_SERVICE_LOCK:
        if _DEFAULT_SERVICE is None:
            _DEFAULT_SERVICE = EveRuntimeService()
        return _DEFAULT_SERVICE


def ordered_thread_summaries(limit: Optional[int] = None, status: Optional[str] = None) -> list[Dict[str, object]]:
    return get_runtime_service().ordered_thread_summaries(limit=limit, status=status)


def model_health_payload(limit: int = 5) -> Dict[str, object]:
    return get_runtime_service().model_health_payload(limit=limit)


def latest_state() -> Dict[str, object]:
    return get_runtime_service().latest_state()


def activity_entries(limit: int) -> list[Dict[str, object]]:
    return get_runtime_service().activity_entries(limit=limit)


def wake_eve_if_needed() -> Dict[str, object]:
    return get_runtime_service().wake_eve_if_needed()


class EveHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class: type[BaseHTTPRequestHandler],
        *,
        service: Optional[EveRuntimeService] = None,
        static_dir: Path = WEB_DIR,
        bind_and_activate: bool = True,
    ):
        self.service = service or get_runtime_service()
        self.static_dir = static_dir
        super().__init__(server_address, request_handler_class, bind_and_activate=bind_and_activate)
        if not bind_and_activate:
            self.server_name = server_address[0]
            self.server_port = server_address[1]

    def handle_error(self, request, client_address) -> None:
        exc_type, _, _ = sys.exc_info()
        if exc_type in {BrokenPipeError, ConnectionResetError, ConnectionAbortedError}:
            return
        super().handle_error(request, client_address)


class EveAppHandler(BaseHTTPRequestHandler):
    server_version = "EveWeb/3.0"

    @property
    def service(self) -> EveRuntimeService:
        return self.server.service  # type: ignore[attr-defined]

    @property
    def static_dir(self) -> Path:
        return self.server.static_dir  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        try:
            self._do_get()
        except LookupError as exc:
            self.send_exception_json(HTTPStatus.NOT_FOUND, str(exc))
        except ValueError as exc:
            self.send_exception_json(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self.send_exception_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc), error_type="server_error")

    def _do_get(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/v1/models":
            return self.handle_get_openai_models()
        if parsed.path.startswith("/v1/models/"):
            return self.handle_get_openai_model(parsed)
        if parsed.path == "/":
            return self.serve_static("index.html", "text/html; charset=utf-8")
        if parsed.path == "/monitor":
            return self.serve_static("monitor.html", "text/html; charset=utf-8")
        if parsed.path == "/install":
            return self.handle_get_install_page()
        if parsed.path == "/install/windows":
            return self.handle_get_windows_install_page()
        if parsed.path == "/app.js":
            return self.serve_static("app.js", "application/javascript; charset=utf-8")
        if parsed.path == "/styles.css":
            return self.serve_static("styles.css", "text/css; charset=utf-8")
        if parsed.path == "/monitor.js":
            return self.serve_static("monitor.js", "application/javascript; charset=utf-8")
        if parsed.path == "/monitor.css":
            return self.serve_static("monitor.css", "text/css; charset=utf-8")
        if parsed.path == "/downloads/EveSetup.exe":
            return self.handle_get_windows_installer_exe()
        if parsed.path in {"/downloads/EveMacInstaller.zip", f"/downloads/{MAC_INSTALLER_FILENAME}"}:
            return self.handle_get_macos_installer_app_bundle()
        if parsed.path == "/downloads/EveWindowsAppPackage.zip":
            return self.handle_get_windows_app_package_download()
        if parsed.path == "/downloads/EveMacSetup.zip":
            return self.handle_get_macos_installer_bundle()
        if parsed.path == "/downloads/EveLinuxSetup.tar.gz":
            return self.handle_get_linux_installer_bundle()
        if parsed.path == "/downloads/install_windows_eve.cmd":
            return self.handle_get_windows_launcher("install_windows_eve.cmd")
        if parsed.path == "/downloads/update_windows_eve.cmd":
            return self.handle_get_windows_launcher("update_windows_eve.cmd")
        if parsed.path == "/downloads/install_windows_eve.ps1":
            return self.handle_get_windows_script("install_windows_eve.ps1")
        if parsed.path == "/downloads/update_windows_eve.ps1":
            return self.handle_get_windows_script("update_windows_eve.ps1")
        if parsed.path == "/downloads/bootstrap_bundle.json":
            return self.handle_get_bootstrap_download()
        if parsed.path == "/downloads/code-bundle.zip":
            return self.handle_get_code_bundle_download()
        if parsed.path == "/api/code-bundle":
            return self.handle_get_code_bundle()
        if parsed.path == "/api/windows-app-package":
            return self.handle_get_windows_app_package()
        if parsed.path == "/api/update-manifest":
            return self.handle_get_update_manifest(parsed)
        if parsed.path == "/api/bootstrap":
            return self.handle_get_bootstrap(parsed)
        if parsed.path == "/api/status":
            return self.send_json({"ok": True, "data": self.service.latest_state()})
        if parsed.path == "/api/monitor":
            query = parse_qs(parsed.query)
            compact = str(query.get("compact", ["0"])[0]).strip().lower() in {"1", "true", "yes"}
            return self.send_json({"ok": True, "data": self.service.monitor_payload(compact=compact)})
        if parsed.path == "/api/monitor/stream":
            return self.handle_get_monitor_stream(parsed)
        if parsed.path == "/api/reply-progress":
            return self.handle_get_reply_progress(parsed)
        if parsed.path == "/api/reply-turns":
            return self.handle_get_reply_turns(parsed)
        if parsed.path == "/api/reply-council-turns":
            return self.handle_get_reply_council_turns(parsed)
        if parsed.path == "/api/attachments":
            return self.handle_get_attachments(parsed)
        if parsed.path == "/api/conversation-spine":
            return self.handle_get_conversation_spine(parsed)
        if parsed.path == "/api/threads":
            return self.handle_get_threads(parsed)
        if parsed.path == "/api/messages":
            return self.handle_get_messages(parsed)
        if parsed.path == "/api/personal-conversation/status":
            return self.send_json({"ok": True, "data": self.service.personal_conversation_status()})
        if parsed.path.startswith("/api/messages/"):
            return self.handle_get_message(parsed)
        if parsed.path.startswith("/api/thread/"):
            return self.handle_get_thread(parsed)
        if parsed.path == "/api/proposals":
            return self.handle_get_proposals(parsed)
        if parsed.path == "/api/governance":
            return self.handle_get_governance(parsed)
        if parsed.path == "/api/thoughts":
            return self.handle_get_thoughts(parsed)
        if parsed.path == "/api/reflections":
            return self.handle_get_reflections(parsed)
        if parsed.path == "/api/tensions":
            return self.handle_get_tensions(parsed)
        if parsed.path == "/api/experiments":
            return self.handle_get_experiments(parsed)
        if parsed.path == "/api/evaluations":
            return self.handle_get_evaluations(parsed)
        if parsed.path == "/api/outcomes":
            return self.handle_get_outcomes(parsed)
        if parsed.path == "/api/failure-clusters":
            return self.handle_get_failure_clusters(parsed)
        if parsed.path == "/api/model-health":
            return self.handle_get_model_health(parsed)
        if parsed.path == "/api/activity":
            return self.handle_get_activity(parsed)
        if parsed.path == "/api/eve-chat/followups":
            return self.handle_get_eve_chat_followups(parsed)
        if parsed.path == "/api/sensory/status":
            return self.send_json({"ok": True, "data": self.service.sensory_status()})
        self.send_error_json(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        try:
            self._do_post()
        except LookupError as exc:
            self.send_exception_json(HTTPStatus.NOT_FOUND, str(exc))
        except ValueError as exc:
            self.send_exception_json(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self.send_exception_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc), error_type="server_error")

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def _do_post(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/v1/chat/completions":
            return self.handle_post_openai_chat_completions()
        if parsed.path in {"/api/eve-chat/ag-ui", "/api/copilotkit/ag-ui"}:
            return self.handle_post_copilotkit_agui(parsed)
        if parsed.path == "/api/attachments/upload":
            return self.handle_post_attachment_upload()
        if parsed.path == "/api/message/ask":
            return self.handle_post_ask()
        if parsed.path == "/api/message/initiate":
            return self.handle_post_initiate()
        if parsed.path == "/api/message/reply":
            return self.handle_post_reply()
        if parsed.path.startswith("/api/messages/") and parsed.path.endswith("/mark"):
            return self.handle_post_mark_message(parsed)
        if parsed.path.startswith("/api/proposals/") and parsed.path.endswith("/status"):
            return self.handle_post_proposal_status(parsed)
        if parsed.path == "/api/actions/think":
            return self.handle_post_think()
        if parsed.path == "/api/actions/wake":
            return self.handle_post_wake()
        if parsed.path == "/api/actions/reflect":
            return self.handle_post_reflect()
        if parsed.path == "/api/actions/proposal":
            return self.handle_post_suggest_proposal()
        if parsed.path == "/api/capture":
            return self.handle_post_capture()
        if parsed.path == "/api/daemon/start":
            return self.handle_post_daemon_start()
        if parsed.path == "/api/daemon/stop":
            return self.handle_post_daemon_stop()
        if parsed.path.startswith("/api/eve-chat/followups/") and parsed.path.endswith("/seen"):
            return self.handle_post_eve_chat_followup_seen(parsed)
        if parsed.path == "/api/sensory/session":
            origin = str(self.headers.get("Origin") or "").strip()
            if origin not in EVE_CHAT_FOLLOWUP_POLL_ORIGINS:
                return self.send_error_json(
                    HTTPStatus.FORBIDDEN,
                    "Sensory control is restricted to the local Eve app origin.",
                )
            payload = self.read_json_body(maximum_bytes=SENSORY_REQUEST_MAX_BYTES)
            action = str(payload.get("action") or "start").strip().lower()
            if action == "start":
                return self.send_json({"ok": True, "data": self.service.start_sensory_session(payload)})
            if action == "stop":
                return self.send_json({"ok": True, "data": self.service.stop_sensory_session(payload)})
            raise ValueError("sensory session action must be start or stop")
        if parsed.path == "/api/sensory/events":
            origin = str(self.headers.get("Origin") or "").strip()
            if origin not in EVE_CHAT_FOLLOWUP_POLL_ORIGINS:
                return self.send_error_json(
                    HTTPStatus.FORBIDDEN,
                    "Sensory control is restricted to the local Eve app origin.",
                )
            payload = self.read_json_body(maximum_bytes=SENSORY_REQUEST_MAX_BYTES)
            return self.send_json({"ok": True, "data": self.service.ingest_sensory_events(payload)})
        self.send_error_json(HTTPStatus.NOT_FOUND, "Not found")

    def log_message(self, format: str, *args: object) -> None:
        return

    def serve_static(self, filename: str, content_type: str) -> None:
        path = self.static_dir / filename
        if not path.exists():
            self.send_error_json(HTTPStatus.NOT_FOUND, f"Missing asset: {filename}")
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_json_body(self, *, maximum_bytes: Optional[int] = None) -> Dict[str, object]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if maximum_bytes is not None and content_length > max(0, int(maximum_bytes)):
            raise ValueError("JSON body is too large")
        raw = self.rfile.read(content_length) if content_length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON body") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def send_json(self, payload: Dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json_bytes(payload)
        self.send_response(status)
        self.send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_bytes(self, payload: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_download(self, payload: bytes, content_type: str, filename: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(payload)

    def send_cors_headers(self) -> None:
        origin = str(self.headers.get("Origin") or "").strip()
        if origin in EVE_CHAT_FOLLOWUP_POLL_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Vary", "Origin")

    def send_error_json(self, status: HTTPStatus, message: str) -> None:
        self.send_json({"ok": False, "error": message}, status=status)

    def send_exception_json(
        self,
        status: HTTPStatus,
        message: str,
        error_type: str = "invalid_request_error",
    ) -> None:
        if self.is_openai_compat_request():
            self.send_openai_error_json(status, message, error_type=error_type)
            return
        self.send_error_json(status, message)

    def is_openai_compat_request(self) -> bool:
        return urlparse(self.path).path.startswith("/v1/")

    def send_openai_error_json(
        self,
        status: HTTPStatus,
        message: str,
        error_type: str = "invalid_request_error",
    ) -> None:
        self.send_json(
            {
                "error": {
                    "message": message,
                    "type": error_type,
                    "param": None,
                    "code": None,
                }
            },
            status=status,
        )

    def handle_get_openai_models(self) -> None:
        self.send_json(self.service.openai_models())

    def handle_get_openai_model(self, parsed) -> None:
        model_id = parsed.path.split("/v1/models/", 1)[1]
        self.send_json(self.service.openai_model(model_id))

    def handle_post_openai_chat_completions(self) -> None:
        payload = self.read_json_body()
        payload["_eve_chat_transport"] = {
            "openwebui_chat_id": str(self.headers.get("X-OpenWebUI-Chat-Id") or ""),
            "openwebui_user_message_id": str(self.headers.get("X-OpenWebUI-User-Message-Id") or ""),
            "openwebui_assistant_message_id": str(
                self.headers.get("X-OpenWebUI-Message-Id")
                or self.headers.get("X-OpenWebUI-Assistant-Message-Id")
                or ""
            ),
            "origin": str(self.headers.get("Origin") or ""),
        }
        completion = self.service.openai_chat_completion(payload)
        if bool(payload.get("stream")):
            return self.send_openai_chat_completion_stream(completion)
        self.send_json(completion)

    def handle_post_copilotkit_agui(self, parsed) -> None:
        payload = self.read_json_body()
        context = copilotkit_agui_context(payload)
        openai_payload = context["openai_payload"]
        if isinstance(openai_payload, dict):
            openai_payload["_eve_chat_transport"] = {
                "openwebui_chat_id": str(self.headers.get("X-OpenWebUI-Chat-Id") or payload.get("chat_id") or ""),
                "openwebui_user_message_id": str(self.headers.get("X-OpenWebUI-User-Message-Id") or ""),
                "openwebui_assistant_message_id": str(
                    self.headers.get("X-OpenWebUI-Message-Id")
                    or self.headers.get("X-OpenWebUI-Assistant-Message-Id")
                    or ""
                ),
                "origin": str(self.headers.get("Origin") or ""),
            }

        thread_id = str(context["thread_id"])
        run_id = str(context["run_id"])
        client_request_id = str(context["client_request_id"])
        activity_message_id = str(context["activity_message_id"])
        text_message_id = str(context["text_message_id"])

        self.send_response(HTTPStatus.OK)
        self.send_cors_headers()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        def emit(event: Dict[str, object]) -> bool:
            try:
                data = json.dumps(event, ensure_ascii=True).encode("utf-8")
                self.wfile.write(b"data: " + data + b"\n\n")
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return False

        if not emit(
            agui_event(
                "RUN_STARTED",
                threadId=thread_id,
                runId=run_id,
                input={
                    "messages": context["messages"],
                    "source": "eve_chat",
                    "protocol": COPILOTKIT_AGUI_PROTOCOL,
                },
            )
        ):
            return
        if not emit(
            agui_event(
                "STATE_SNAPSHOT",
                snapshot={
                    "adapter": COPILOTKIT_AGUI_PROTOCOL,
                    "provider": "eve_local_runtime",
                    "providerDependency": "none",
                    "authority": "ui_adapter_only",
                    "threadId": thread_id,
                    "runId": run_id,
                    "clientRequestId": client_request_id,
                },
            )
        ):
            return
        if not emit(
            agui_event(
                "ACTIVITY_SNAPSHOT",
                messageId=activity_message_id,
                activityType=COPILOTKIT_AGUI_ACTIVITY_TYPE,
                content=copilotkit_agui_progress_content(None, status="queued"),
                replace=True,
            )
        ):
            return

        result_box: Dict[str, object] = {}

        def run_completion() -> None:
            try:
                result_box["completion"] = self.service.openai_chat_completion(openai_payload)  # type: ignore[arg-type]
            except Exception as exc:
                result_box["error"] = exc

        worker = threading.Thread(
            target=run_completion,
            daemon=True,
            name=f"eve-chat-agui-{run_id[:12]}",
        )
        worker.start()

        last_progress_key = ""
        last_step = ""
        while worker.is_alive():
            try:
                progress_payload = self.service.reply_progress(
                    client_request_id=client_request_id,
                    active_only=False,
                )
                job = progress_payload.get("job") if isinstance(progress_payload, dict) else None
                if isinstance(job, dict):
                    content = copilotkit_agui_progress_content(job, status="running")
                    progress_key = json.dumps(content, ensure_ascii=True, sort_keys=True)
                    step_name = str(content.get("phase") or content.get("status") or "reply_progress")
                    if step_name and step_name != last_step:
                        if last_step:
                            if not emit(agui_event("STEP_FINISHED", stepName=last_step)):
                                return
                        if not emit(agui_event("STEP_STARTED", stepName=step_name)):
                            return
                        last_step = step_name
                    if progress_key != last_progress_key:
                        if not emit(
                            agui_event(
                                "ACTIVITY_DELTA",
                                messageId=activity_message_id,
                                activityType=COPILOTKIT_AGUI_ACTIVITY_TYPE,
                                patch=[
                                    {"op": "replace", "path": "/status", "value": content.get("status")},
                                    {"op": "replace", "path": "/phase", "value": content.get("phase")},
                                    {"op": "replace", "path": "/title", "value": content.get("title")},
                                    {"op": "replace", "path": "/detail", "value": content.get("detail")},
                                    {"op": "replace", "path": "/current_model", "value": content.get("current_model")},
                                    {"op": "replace", "path": "/notes", "value": content.get("notes")},
                                ],
                            )
                        ):
                            return
                        last_progress_key = progress_key
            except Exception:
                # Progress polling is best-effort; the run result remains authoritative.
                pass
            worker.join(0.25)

        worker.join()
        if last_step:
            if not emit(agui_event("STEP_FINISHED", stepName=last_step)):
                return

        error = result_box.get("error")
        if error is not None:
            emit(
                agui_event(
                    "RUN_ERROR",
                    message=eve.normalize_text_value(str(error), fallback="Eve AG-UI run failed.", limit=500),
                    code="eve_agui_completion_error",
                )
            )
            self.close_connection = True
            return

        completion = result_box.get("completion") if isinstance(result_box.get("completion"), dict) else {}
        reply_text, reply_message_id, eve_metadata = copilotkit_agui_completion_reply(completion)
        final_progress = copilotkit_agui_progress_content(
            {
                "status": "completed",
                "phase": "reply_ready",
                "title": "Reply ready",
                "detail": "Eve returned the local runtime answer through the AG-UI adapter.",
                "reply_message_id": reply_message_id,
                "notes": [],
            },
            status="completed",
        )
        if not emit(
            agui_event(
                "ACTIVITY_DELTA",
                messageId=activity_message_id,
                activityType=COPILOTKIT_AGUI_ACTIVITY_TYPE,
                patch=[
                    {"op": "replace", "path": "/status", "value": final_progress.get("status")},
                    {"op": "replace", "path": "/phase", "value": final_progress.get("phase")},
                    {"op": "replace", "path": "/title", "value": final_progress.get("title")},
                    {"op": "replace", "path": "/detail", "value": final_progress.get("detail")},
                    {"op": "replace", "path": "/reply_message_id", "value": reply_message_id},
                ],
            )
        ):
            return
        if not emit(agui_event("TEXT_MESSAGE_START", messageId=reply_message_id or text_message_id, role="assistant")):
            return
        if reply_text:
            if not emit(agui_event("TEXT_MESSAGE_CONTENT", messageId=reply_message_id or text_message_id, delta=reply_text)):
                return
        if not emit(agui_event("TEXT_MESSAGE_END", messageId=reply_message_id or text_message_id)):
            return
        emit(
            agui_event(
                "RUN_FINISHED",
                threadId=thread_id,
                runId=run_id,
                result={
                    "messageId": reply_message_id or text_message_id,
                    "protocol": COPILOTKIT_AGUI_PROTOCOL,
                    "eve": eve_metadata,
                },
            )
        )
        self.close_connection = True

    def send_openai_chat_completion_stream(self, completion: Dict[str, object]) -> None:
        choices = completion.get("choices") if isinstance(completion.get("choices"), list) else []
        first_choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        message = first_choice.get("message") if isinstance(first_choice.get("message"), dict) else {}
        content = str(message.get("content") or "")
        completion_id = str(completion.get("id") or f"chatcmpl-eve-{uuid.uuid4().hex}")
        model_id = str(completion.get("model") or OPENAI_COMPAT_MODEL_ID)
        created = int(completion.get("created") or openai_compat_created_at())

        def chunk(delta: Dict[str, object], finish_reason: Optional[str] = None) -> Dict[str, object]:
            return {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_id,
                "choices": [
                    {
                        "index": 0,
                        "delta": delta,
                        "finish_reason": finish_reason,
                    }
                ],
            }

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        for item in [
            chunk({"role": "assistant"}),
            chunk({"content": content}),
            chunk({}, finish_reason="stop"),
        ]:
            data = json.dumps(item, ensure_ascii=True).encode("utf-8")
            self.wfile.write(b"data: " + data + b"\n\n")
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True

    def handle_get_eve_chat_followups(self, parsed) -> None:
        query = parse_qs(parsed.query)
        limit = int(query.get("limit", ["20"])[0])
        status = query.get("status", [None])[0]
        surface = query.get("surface", ["eve_chat_ui"])[0]
        include_seen = str(query.get("include_seen", ["0"])[0]).strip().lower() in {"1", "true", "yes"}
        self.send_json(
            {
                "ok": True,
                "data": self.service.eve_chat_followups(
                    status=status,
                    surface=surface,
                    include_seen=include_seen,
                    limit=limit,
                ),
            }
        )

    def handle_post_eve_chat_followup_seen(self, parsed) -> None:
        parts = parsed.path.strip("/").split("/")
        if len(parts) != 5:
            raise LookupError("Invalid Eve Chat follow-up route")
        followup_id = parts[3]
        self.send_json({"ok": True, "data": self.service.mark_eve_chat_followup_seen(followup_id)})

    def handle_get_monitor_stream(self, parsed) -> None:
        query = parse_qs(parsed.query)
        interval_ms = int(query.get("interval_ms", ["1000"])[0])
        interval_seconds = max(0.25, min(10.0, interval_ms / 1000))
        compact = str(query.get("compact", ["0"])[0]).strip().lower() in {"1", "true", "yes"}

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        last_fingerprint = ""
        while True:
            try:
                monitor_payload = self.service.monitor_payload(compact=compact)
                fingerprint_payload = dict(monitor_payload)
                fingerprint = json.dumps(fingerprint_payload, ensure_ascii=True, sort_keys=True)
                payload = json_bytes({"ok": True, "data": monitor_payload}).decode("utf-8")
                if fingerprint != last_fingerprint:
                    self.wfile.write(b"event: monitor\n")
                    for line in payload.splitlines() or [""]:
                        self.wfile.write(f"data: {line}\n".encode("utf-8"))
                    self.wfile.write(b"\n")
                    last_fingerprint = fingerprint
                else:
                    self.wfile.write(b": heartbeat\n\n")
                self.wfile.flush()
                time.sleep(interval_seconds)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return
            except Exception as exc:
                try:
                    payload = json_bytes({"ok": False, "error": str(exc)}).decode("utf-8")
                    self.wfile.write(b"event: error\n")
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    return
                time.sleep(interval_seconds)

    def handle_get_threads(self, parsed) -> None:
        query = parse_qs(parsed.query)
        limit = int(query.get("limit", ["30"])[0])
        status = query.get("status", [None])[0]
        audience = query.get("audience", [None])[0]
        self.send_json({"ok": True, "data": self.service.threads(limit=limit, status=status, audience=audience)})

    def handle_get_bootstrap(self, parsed) -> None:
        query = parse_qs(parsed.query)
        host_header = str(self.headers.get("Host") or "")
        inferred_host = host_header.rsplit(":", 1)[0] if ":" in host_header else host_header
        primary_host = str(query.get("host", [inferred_host])[0] or "").strip()
        api_port = int(query.get("api_port", [str(self.server.server_port)])[0])
        ollama_port = int(query.get("ollama_port", ["11434"])[0])
        self.send_json(
            {
                "ok": True,
                "data": self.service.bootstrap_payload(
                    primary_host=primary_host,
                    api_port=api_port,
                    ollama_port=ollama_port,
                ),
            }
        )

    def handle_get_code_bundle(self) -> None:
        self.send_bytes(self.service.code_bundle_archive(), "application/zip")

    def handle_get_update_manifest(self, parsed) -> None:
        query = parse_qs(parsed.query)
        host_header = str(self.headers.get("Host") or "")
        inferred_host = host_header.rsplit(":", 1)[0] if ":" in host_header else host_header
        primary_host = str(query.get("host", [inferred_host])[0] or "").strip()
        api_port = int(query.get("api_port", [str(self.server.server_port)])[0])
        ollama_port = int(query.get("ollama_port", ["11434"])[0])
        self.send_json(
            {
                "ok": True,
                "data": self.service.update_manifest(
                    primary_host=primary_host,
                    api_port=api_port,
                    ollama_port=ollama_port,
                ),
            }
        )

    def handle_get_windows_app_package(self) -> None:
        host, port = infer_request_host_port(str(self.headers.get("Host") or ""), self.server.server_port)
        payload = self.service.windows_app_package_archive(host or "127.0.0.1", port)
        self.send_bytes(payload, "application/zip")

    def handle_get_windows_install_page(self) -> None:
        host, port = infer_request_host_port(str(self.headers.get("Host") or ""), self.server.server_port)
        base_url = f"http://{str(self.headers.get('Host') or f'127.0.0.1:{self.server.server_port}')}"
        self.send_bytes(
            render_windows_install_page(base_url, host or "127.0.0.1", port),
            "text/html; charset=utf-8",
        )

    def handle_get_install_page(self) -> None:
        host, port = infer_request_host_port(str(self.headers.get("Host") or ""), self.server.server_port)
        base_url = f"http://{str(self.headers.get('Host') or f'127.0.0.1:{self.server.server_port}')}"
        self.send_bytes(
            render_install_page(base_url, host or "127.0.0.1", port),
            "text/html; charset=utf-8",
        )

    def handle_get_windows_script(self, filename: str) -> None:
        host, port = infer_request_host_port(str(self.headers.get("Host") or ""), self.server.server_port)
        payload = customized_windows_script(filename, host or "127.0.0.1", port)
        self.send_download(payload, "text/plain; charset=utf-8", filename)

    def handle_get_windows_launcher(self, filename: str) -> None:
        host, port = infer_request_host_port(str(self.headers.get("Host") or ""), self.server.server_port)
        payload = customized_windows_launcher(filename, host or "127.0.0.1", port)
        self.send_download(payload, "text/plain; charset=utf-8", filename)

    def handle_get_windows_installer_exe(self) -> None:
        host, port = infer_request_host_port(str(self.headers.get("Host") or ""), self.server.server_port)
        payload = build_windows_installer_exe(host or "127.0.0.1", port)
        self.send_download(payload, "application/vnd.microsoft.portable-executable", "EveSetup.exe")

    def handle_get_windows_app_package_download(self) -> None:
        host, port = infer_request_host_port(str(self.headers.get("Host") or ""), self.server.server_port)
        payload = self.service.windows_app_package_archive(host or "127.0.0.1", port)
        self.send_download(payload, "application/zip", "EveWindowsAppPackage.zip")

    def handle_get_macos_installer_bundle(self) -> None:
        host, port = infer_request_host_port(str(self.headers.get("Host") or ""), self.server.server_port)
        payload = build_macos_installer_bundle(host or "127.0.0.1", port)
        self.send_download(payload, "application/zip", "EveMacSetup.zip")

    def handle_get_macos_installer_app_bundle(self) -> None:
        host, port = infer_request_host_port(str(self.headers.get("Host") or ""), self.server.server_port)
        payload = build_macos_installer_app_bundle(host or "127.0.0.1", port)
        self.send_download(payload, "application/zip", MAC_INSTALLER_FILENAME)

    def handle_get_linux_installer_bundle(self) -> None:
        host, port = infer_request_host_port(str(self.headers.get("Host") or ""), self.server.server_port)
        payload = build_linux_installer_bundle(host or "127.0.0.1", port)
        self.send_download(payload, "application/gzip", "EveLinuxSetup.tar.gz")

    def handle_get_bootstrap_download(self) -> None:
        host, port = infer_request_host_port(str(self.headers.get("Host") or ""), self.server.server_port)
        payload = self.service.bootstrap_payload(primary_host=host or "127.0.0.1", api_port=port, ollama_port=11434)
        self.send_download(json_bytes(payload), "application/json; charset=utf-8", "bootstrap_bundle.json")

    def handle_get_code_bundle_download(self) -> None:
        self.send_download(self.service.code_bundle_archive(), "application/zip", "eve_code_bundle.zip")

    def handle_get_reply_progress(self, parsed) -> None:
        query = parse_qs(parsed.query)
        client_request_id = query.get("client_request_id", [None])[0]
        thread_id = query.get("thread_id", [None])[0]
        active_only = str(query.get("active_only", ["1"])[0]).strip().lower() not in {"0", "false", "no"}
        self.send_json(
            {
                "ok": True,
                "data": self.service.reply_progress(
                    client_request_id=client_request_id,
                    thread_id=thread_id,
                    active_only=active_only,
                ),
            }
        )

    def handle_get_reply_turns(self, parsed) -> None:
        query = parse_qs(parsed.query)
        limit = int(query.get("limit", ["20"])[0])
        thread_id = query.get("thread_id", [None])[0]
        reply_message_id = query.get("reply_message_id", [None])[0]
        self.send_json(
            {
                "ok": True,
                "data": self.service.reply_turn_replays(
                    limit=limit,
                    thread_id=thread_id,
                    reply_message_id=reply_message_id,
                ),
            }
        )

    def handle_get_reply_council_turns(self, parsed) -> None:
        query = parse_qs(parsed.query)
        limit = int(query.get("limit", ["20"])[0])
        thread_id = query.get("thread_id", [None])[0]
        reply_message_id = query.get("reply_message_id", [None])[0]
        self.send_json(
            {
                "ok": True,
                "data": self.service.reply_council_turns(
                    limit=limit,
                    thread_id=thread_id,
                    reply_message_id=reply_message_id,
                ),
            }
        )

    def handle_get_conversation_spine(self, parsed) -> None:
        query = parse_qs(parsed.query)
        limit = int(query.get("limit", ["20"])[0])
        thread_id = query.get("thread_id", [None])[0]
        role = query.get("role", [None])[0]
        direction = query.get("direction", [None])[0]
        include_synthetic = str(query.get("include_synthetic", ["1"])[0]).strip().lower() not in {"0", "false", "no"}
        self.send_json(
            {
                "ok": True,
                "data": self.service.conversation_spine(
                    limit=limit,
                    thread_id=thread_id,
                    role=role,
                    direction=direction,
                    include_synthetic=include_synthetic,
                ),
            }
        )

    def handle_get_messages(self, parsed) -> None:
        query = parse_qs(parsed.query)
        limit = int(query.get("limit", ["30"])[0])
        sender = query.get("sender", [None])[0]
        recipient = query.get("recipient", [None])[0]
        status = query.get("status", [None])[0]
        thread_id = query.get("thread", [None])[0]
        initiated = str(query.get("initiated", ["0"])[0]).lower() in {"1", "true", "yes"}
        personal = str(query.get("personal", ["0"])[0]).lower() in {"1", "true", "yes"}
        self.send_json(
            {
                "ok": True,
                "data": self.service.messages(
                    limit=limit,
                    sender=sender,
                    recipient=recipient,
                    status=status,
                    thread_id=thread_id,
                    initiated=initiated,
                    personal=personal,
                ),
            }
        )

    def handle_get_message(self, parsed) -> None:
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 3:
            raise ValueError("Missing message id")
        self.send_json({"ok": True, "data": self.service.open_message(parts[2])})

    def handle_get_thread(self, parsed) -> None:
        thread_id = parsed.path.split("/api/thread/", 1)[1]
        self.send_json({"ok": True, "data": self.service.thread_messages(thread_id)})

    def handle_get_proposals(self, parsed) -> None:
        query = parse_qs(parsed.query)
        limit = int(query.get("limit", ["20"])[0])
        status = query.get("status", [None])[0]
        self.send_json({"ok": True, "data": self.service.proposals(limit=limit, status=status)})

    def handle_get_governance(self, parsed) -> None:
        query = parse_qs(parsed.query)
        limit = int(query.get("limit", ["20"])[0])
        runtime = str(query.get("runtime", ["1"])[0]).strip().lower() not in {"0", "false", "no", "off"}
        self.send_json({"ok": True, "data": self.service.governance(limit=limit, runtime=runtime)})

    def handle_get_reflections(self, parsed) -> None:
        query = parse_qs(parsed.query)
        limit = int(query.get("limit", ["10"])[0])
        self.send_json({"ok": True, "data": self.service.reflections(limit=limit)})

    def handle_get_thoughts(self, parsed) -> None:
        query = parse_qs(parsed.query)
        limit = int(query.get("limit", ["10"])[0])
        self.send_json({"ok": True, "data": self.service.thoughts(limit=limit)})

    def handle_get_tensions(self, parsed) -> None:
        query = parse_qs(parsed.query)
        limit = int(query.get("limit", ["10"])[0])
        status = query.get("status", [None])[0]
        self.send_json({"ok": True, "data": self.service.tensions(limit=limit, status=status)})

    def handle_get_experiments(self, parsed) -> None:
        query = parse_qs(parsed.query)
        limit = int(query.get("limit", ["10"])[0])
        status = query.get("status", [None])[0]
        self.send_json({"ok": True, "data": self.service.experiments(limit=limit, status=status)})

    def handle_get_evaluations(self, parsed) -> None:
        query = parse_qs(parsed.query)
        limit = int(query.get("limit", ["20"])[0])
        target_kind = query.get("target_kind", [None])[0]
        target_id = query.get("target_id", [None])[0]
        evaluator = query.get("evaluator", [None])[0]
        thread_id = query.get("thread", [None])[0]
        days = query.get("days", [None])[0]
        self.send_json(
            {
                "ok": True,
                "data": self.service.evaluations(
                    limit=limit,
                    target_kind=target_kind,
                    target_id=target_id,
                    evaluator=evaluator,
                    thread_id=thread_id,
                    since_days=int(days) if days else None,
                ),
            }
        )

    def handle_get_outcomes(self, parsed) -> None:
        query = parse_qs(parsed.query)
        limit = int(query.get("limit", ["20"])[0])
        target_kind = query.get("target_kind", [None])[0]
        target_id = query.get("target_id", [None])[0]
        direction = query.get("direction", [None])[0]
        thread_id = query.get("thread", [None])[0]
        days = query.get("days", [None])[0]
        self.send_json(
            {
                "ok": True,
                "data": self.service.outcomes(
                    limit=limit,
                    target_kind=target_kind,
                    target_id=target_id,
                    direction=direction,
                    thread_id=thread_id,
                    since_days=int(days) if days else None,
                ),
            }
        )

    def handle_get_failure_clusters(self, parsed) -> None:
        query = parse_qs(parsed.query)
        limit = int(query.get("limit", ["20"])[0])
        status = query.get("status", [None])[0]
        days = query.get("days", [None])[0]
        self.send_json(
            {
                "ok": True,
                "data": self.service.failure_clusters(limit=limit, status=status, since_days=int(days) if days else None),
            }
        )

    def handle_get_model_health(self, parsed) -> None:
        query = parse_qs(parsed.query)
        limit = int(query.get("limit", ["5"])[0])
        self.send_json({"ok": True, "data": self.service.model_health_payload(limit=limit)})

    def handle_get_activity(self, parsed) -> None:
        query = parse_qs(parsed.query)
        limit = int(query.get("limit", ["20"])[0])
        self.send_json({"ok": True, "data": self.service.activity(limit=limit)})

    def handle_get_attachments(self, parsed) -> None:
        query = parse_qs(parsed.query)
        limit = int(query.get("limit", ["100"])[0])
        thread_id = str(query.get("thread_id", [""])[0]).strip() or None
        message_id = str(query.get("message_id", [""])[0]).strip() or None
        self.send_json(
            {
                "ok": True,
                "data": self.service.attachments(
                    thread_id=thread_id,
                    message_id=message_id,
                    limit=limit,
                ),
            }
        )

    def handle_post_attachment_upload(self) -> None:
        payload = self.read_json_body()
        self.send_json({"ok": True, "data": self.service.upload_attachment(payload)})

    def handle_post_ask(self) -> None:
        payload = self.read_json_body()
        body = str(payload.get("body", "")).strip()
        subject = str(payload.get("subject", "")).strip() or "Question from user"
        client_request_id = str(payload.get("client_request_id", "")).strip() or None
        attachments_value = payload.get("attachments", [])
        if attachments_value is None:
            attachments = []
        elif isinstance(attachments_value, list):
            attachments = attachments_value
        else:
            raise ValueError("attachments must be a list")
        self.send_json(
            {
                "ok": True,
                "data": self.service.ask(
                    body,
                    subject=subject,
                    client_request_id=client_request_id,
                    attachments=attachments,
                ),
            }
        )

    def handle_post_initiate(self) -> None:
        payload = self.read_json_body()
        allow_none = str(payload.get("allow_none", "0")).lower() in {"1", "true", "yes"}
        notify = str(payload.get("notify", "1")).lower() not in {"0", "false", "no"}
        self.send_json({"ok": True, "data": self.service.initiate_personal_message(allow_none=allow_none, notify=notify)})

    def handle_post_reply(self) -> None:
        payload = self.read_json_body()
        message_id = str(payload.get("message_id", "")).strip()
        body = str(payload.get("body", "")).strip()
        subject = str(payload.get("subject", "")).strip() or None
        client_request_id = str(payload.get("client_request_id", "")).strip() or None
        attachments_value = payload.get("attachments", [])
        if attachments_value is None:
            attachments = []
        elif isinstance(attachments_value, list):
            attachments = attachments_value
        else:
            raise ValueError("attachments must be a list")
        self.send_json(
            {
                "ok": True,
                "data": self.service.reply(
                    message_id=message_id,
                    body=body,
                    subject=subject,
                    client_request_id=client_request_id,
                    attachments=attachments,
                ),
            }
        )

    def handle_post_mark_message(self, parsed) -> None:
        payload = self.read_json_body()
        status = str(payload.get("status", "")).strip()
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 4:
            raise ValueError("Missing message id")
        self.send_json({"ok": True, "data": self.service.mark_message(parts[2], status=status)})

    def handle_post_proposal_status(self, parsed) -> None:
        payload = self.read_json_body()
        status = str(payload.get("status", "")).strip()
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 4:
            raise ValueError("Missing proposal id")
        self.send_json({"ok": True, "data": self.service.update_proposal_status(parts[2], status=status)})

    def handle_post_think(self) -> None:
        self.send_json({"ok": True, "data": self.service.think()})

    def handle_post_wake(self) -> None:
        self.send_json({"ok": True, "data": self.service.wake_eve_if_needed()})

    def handle_post_reflect(self) -> None:
        self.send_json({"ok": True, "data": self.service.reflect()})

    def handle_post_suggest_proposal(self) -> None:
        self.send_json({"ok": True, "data": self.service.suggest_proposal()})

    def handle_post_capture(self) -> None:
        payload = self.read_json_body()
        kind = str(payload.get("kind", "note")).strip() or "note"
        text = str(payload.get("text", "") or payload.get("body", "")).strip()
        self.send_json({"ok": True, "data": self.service.capture(kind, text, payload.get("tags", []))})

    def handle_post_daemon_start(self) -> None:
        self.send_json({"ok": True, "data": self.service.daemon_start()})

    def handle_post_daemon_stop(self) -> None:
        self.send_json({"ok": True, "data": self.service.daemon_stop()})


def create_server(
    host: str = "127.0.0.1",
    port: int = 8787,
    *,
    service: Optional[EveRuntimeService] = None,
    static_dir: Path = WEB_DIR,
    bind_and_activate: bool = True,
) -> EveHTTPServer:
    return EveHTTPServer(
        (host, port),
        EveAppHandler,
        service=service,
        static_dir=static_dir,
        bind_and_activate=bind_and_activate,
    )


def main(host: str = "127.0.0.1", port: int = 8787, open_browser: bool = False) -> int:
    server = create_server(host=host, port=port)
    recovery = server.service.resume_eve_chat_followups()
    url = f"http://{host}:{port}"
    print(
        f"Eve app running at {url}; durable follow-ups resumed: "
        f"{recovery.get('recoverable_count') or 0}"
    )
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
