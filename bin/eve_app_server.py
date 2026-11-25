#!/usr/bin/env python3
"""Serve Eve's local living timeline and proxy only its admitted routes."""

from __future__ import annotations

import argparse
import http.client
import json
import mimetypes
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path
from typing import Any


RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

import eve_http_body
import eve_http_headers
import eve_http_json
import eve_http_path
import eve_http_query
import eve_http_security
import eve_http_server
from eve_spotlight_projection import build_spotlight_projection


MAX_REQUEST_BYTES = 256 * 1024
MAX_CHAT_MESSAGES = 32
MAX_MESSAGE_CHARS = 16_000
MAX_PERSONAL_MESSAGE_ID_CHARS = 160
MAX_PERSONAL_MESSAGE_BODY_CHARS = 8_000
MAX_CLIENT_REQUEST_ID_CHARS = 160
STREAM_CHUNK_BYTES = 64 * 1024
MAX_PROXY_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_PROXY_ERROR_BYTES = 64 * 1024
MAX_PRESENCE_RESPONSE_BYTES = 2 * 1024 * 1024
PRESENCE_CACHE_SECONDS = 8.0
BACKEND_HEALTH_POSITIVE_CACHE_SECONDS = 12.0
BACKEND_HEALTH_NEGATIVE_CACHE_SECONDS = 1.0
MAX_PROJECTION_STATE_BYTES = 256 * 1024
SENSORY_APP_ORIGINS = {
    "http://127.0.0.1:3000",
    "http://localhost:3000",
}


class UpstreamResponseError(ValueError):
    """The local backend response cannot safely cross the Eve.app boundary."""


class UpstreamResponseTooLarge(UpstreamResponseError):
    """The local backend response exceeded its admitted byte budget."""


def _compact_text(value: object, limit: int = 320) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    return text if len(text) <= limit else f"{text[: limit - 1].rstrip()}…"


def _parse_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _action_scope(action: str) -> str:
    normalized = action.lower()
    if any(
        marker in normalized
        for marker in (
            "external_send",
            "channel_send",
            "email_send",
            "message_send",
            "notification_send",
            "device_control",
        )
    ):
        return "outside"
    if any(marker in normalized for marker in ("browser_", "web_", "web_search")):
        return "web"
    return "local"


def normalize_chat_messages(messages: object) -> list[dict[str, str]]:
    """Accept only the small user/assistant conversation contract Eve.app owns."""
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty array")
    normalized: list[dict[str, str]] = []
    for message in messages[-MAX_CHAT_MESSAGES:]:
        if not isinstance(message, dict):
            raise ValueError("each message must be an object")
        role = str(message.get("role") or "").strip()
        content = message.get("content")
        if role not in {"user", "assistant"}:
            raise ValueError("message roles must be user or assistant")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("message content must be non-empty text")
        if len(content) > MAX_MESSAGE_CHARS:
            raise ValueError("message content is too long")
        normalized.append({"role": role, "content": content.strip()})
    if normalized[-1]["role"] != "user":
        raise ValueError("the final message must be from the user")
    return normalized


def read_bounded_response(response: Any, *, max_bytes: int, label: str) -> bytes:
    """Read one non-stream upstream response without trusting its size header."""

    raw_length = response.headers.get("Content-Length") if response.headers else None
    declared_length: int | None = None
    if raw_length not in (None, ""):
        try:
            declared_length = int(raw_length)
        except (TypeError, ValueError) as exc:
            raise UpstreamResponseError(f"{label} returned an invalid Content-Length") from exc
        if declared_length < 0 or declared_length > max_bytes:
            raise UpstreamResponseTooLarge(
                f"{label} exceeded the {max_bytes}-byte response limit"
            )
    data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise UpstreamResponseTooLarge(
            f"{label} exceeded the {max_bytes}-byte response limit"
        )
    if declared_length is not None and len(data) != declared_length:
        raise UpstreamResponseError(f"{label} ended before its declared Content-Length")
    return data


def build_presence_snapshot(monitor: dict[str, Any]) -> dict[str, Any]:
    """Reduce monitor evidence to the small, truthful state Eve.app can show."""
    status = monitor.get("status") if isinstance(monitor.get("status"), dict) else {}
    daemon = status.get("daemon") if isinstance(status.get("daemon"), dict) else {}
    workspace = monitor.get("workspace") if isinstance(monitor.get("workspace"), dict) else {}
    workspace_state = (
        workspace.get("workspace_state") if isinstance(workspace.get("workspace_state"), dict) else {}
    )
    autonomy = monitor.get("autonomy") if isinstance(monitor.get("autonomy"), dict) else {}
    agenda = autonomy.get("agenda") if isinstance(autonomy.get("agenda"), dict) else {}
    homeostasis = monitor.get("homeostasis") if isinstance(monitor.get("homeostasis"), dict) else {}
    activity = monitor.get("activity") if isinstance(monitor.get("activity"), dict) else {}
    model_activity = activity.get("models") if isinstance(activity.get("models"), dict) else {}
    operations = monitor.get("operations") if isinstance(monitor.get("operations"), dict) else {}

    goals = workspace.get("active_goals") if isinstance(workspace.get("active_goals"), list) else []
    focus_candidates = [
        goals[0] if goals else "",
        workspace_state.get("focus"),
        agenda.get("current_focus"),
    ]
    focus = next((_compact_text(item, 260) for item in focus_candidates if _compact_text(item, 260)), "")

    next_step = _compact_text(homeostasis.get("next_regulation_step"), 320)
    if next_step.casefold() == focus.casefold():
        next_step = ""

    actions = operations.get("actions") if isinstance(operations.get("actions"), list) else []
    action_records = [item for item in actions if isinstance(item, dict)]
    action_records.sort(
        key=lambda item: _parse_timestamp(item.get("updated_at") or item.get("created_at"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    latest_action = action_records[0] if action_records else {}
    action_name = _compact_text(latest_action.get("action"), 120)
    action_at = _compact_text(latest_action.get("updated_at") or latest_action.get("created_at"), 80)
    tree_status = str(latest_action.get("tree_status") or "").strip().upper()
    verified = bool(action_name) and (
        tree_status == "SUCCESS"
        and latest_action.get("verification_ok") is True
        and latest_action.get("result_ok") is True
        and latest_action.get("typed_contract_ok") is not False
    )
    failed = bool(action_name) and (
        tree_status in {"FAILURE", "ERROR", "FAILED"}
        or latest_action.get("verification_ok") is False
        or latest_action.get("result_ok") is False
    )
    last_action: dict[str, Any] | None = None
    if action_name:
        last_action = {
            "kind": action_name,
            "at": action_at,
            "outcome": "verified" if verified else "failed" if failed else "unverified",
            "scope": _action_scope(action_name),
        }

    running = bool(daemon.get("running"))
    awake = bool(daemon.get("awake"))
    active_reply = status.get("active_reply") if isinstance(status.get("active_reply"), dict) else {}
    active_calls = (
        model_activity.get("active_calls") if isinstance(model_activity.get("active_calls"), list) else []
    )
    action_time = _parse_timestamp(action_at)
    action_age_seconds = (
        (datetime.now(timezone.utc) - action_time).total_seconds() if action_time else None
    )
    action_is_recent = bool(
        action_age_seconds is not None and 0 <= action_age_seconds <= 50
    )
    if not running:
        state = "reconnecting"
    elif active_reply:
        state = "responding"
    elif action_is_recent:
        state = "acting"
    elif active_calls:
        state = "thinking"
    else:
        state = "here" if awake else "quiet"

    return {
        "schema": "eve_app_presence.v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_updated_at": _compact_text(
            workspace.get("updated_at") or monitor.get("generated_at"), 80
        ),
        "place": "inside this Mac",
        "running": running,
        "awake": awake,
        "state": state,
        "focus": focus,
        "focus_is_goal_not_action": bool(focus),
        "next_step": next_step,
        "last_action": last_action,
    }


def _read_projection_json(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > MAX_PROJECTION_STATE_BYTES:
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_projection_action_tail(path: Path, *, limit: int = 24) -> list[dict[str, Any]]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            start = max(0, size - MAX_PROJECTION_STATE_BYTES)
            handle.seek(start)
            data = handle.read(MAX_PROJECTION_STATE_BYTES)
    except OSError:
        return []
    if start:
        first_newline = data.find(b"\n")
        data = data[first_newline + 1 :] if first_newline >= 0 else b""
    records: list[dict[str, Any]] = []
    for raw_line in data.splitlines()[-max(1, limit) :]:
        try:
            item = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def build_spotlight_monitor_from_runtime_state(state_dir: Path) -> dict[str, Any]:
    """Read only the bounded canonical state needed for the derived index."""

    return {
        "workspace": _read_projection_json(state_dir / "global_workspace.json"),
        "homeostasis": _read_projection_json(state_dir / "homeostasis.json"),
        "autonomy": {"agenda": _read_projection_json(state_dir / "autonomy_agenda.json")},
        "operations": {
            "actions": _read_projection_action_tail(state_dir / "action_executions.jsonl")
        },
    }


def detach_from_launcher() -> None:
    """Keep the loopback UI alive after its short-lived launcher exits."""
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
    try:
        os.setsid()
    except OSError:
        # Being a process-group leader already is harmless; ignoring SIGHUP is
        # the important part for app launches.
        pass


class EveAppHTTPServer(eve_http_server.EveBoundedThreadingHTTPServer):
    internal_error_surface = "eve-app"
    static_root: Path
    backend_base: str
    config_path: Path = RUNTIME_ROOT / ".eve" / "config.json"
    runtime_state_dir: Path = RUNTIME_ROOT / ".eve"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.presence_cache: dict[str, Any] | None = None
        self.presence_cache_at = 0.0
        self._backend_health_cache: bool | None = None
        self._backend_health_cache_at = 0.0
        self._backend_health_lock = threading.Lock()

    def record_backend_health(self, available: bool, *, now: float | None = None) -> None:
        observed_at = time.monotonic() if now is None else float(now)
        with self._backend_health_lock:
            self._backend_health_cache = bool(available)
            self._backend_health_cache_at = observed_at

    def cached_backend_health(self, *, now: float | None = None) -> bool | None:
        observed_at = time.monotonic() if now is None else float(now)
        with self._backend_health_lock:
            available = self._backend_health_cache
            observed_health_at = self._backend_health_cache_at
        if available is None:
            return None
        ttl = (
            BACKEND_HEALTH_POSITIVE_CACHE_SECONDS
            if available
            else BACKEND_HEALTH_NEGATIVE_CACHE_SECONDS
        )
        age = max(0.0, observed_at - observed_health_at)
        return available if age <= ttl else None


class EveAppHandler(eve_http_server.EveBoundedHTTPRequestHandler):
    server: EveAppHTTPServer
    server_version = "EveApp/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, format_string: str, *args: object) -> None:
        # Never log request lines, query values, bodies, or conversation text.
        # JSON string encoding escapes terminal controls without inventing a
        # second logging dependency for this small local surface.
        def field(value: object, limit: int = 512) -> str:
            raw = str(value or "")
            if len(raw) > limit:
                raw = raw[:limit] + "..."
            return json.dumps(raw, ensure_ascii=True)

        raw_target = str(getattr(self, "path", ""))
        raw_path = raw_target.split("?", 1)[0].split("#", 1)[0]
        try:
            path = eve_http_path.require_request_path(raw_path)
        except ValueError:
            path = "<invalid>"
        status = str(args[1]) if len(args) >= 2 and str(args[1]).isdigit() else "-"
        client_host = self.client_address[0] if self.client_address else ""
        sys.stderr.write(
            "eve-app request"
            f" client={field(client_host, 128)}"
            f" method={field(getattr(self, 'command', ''), 24)}"
            f" path={field(path)}"
            f" status={field(status, 8)}\n"
        )

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        target = self._admit_target(self.path)
        if target is None:
            return
        if not self._admit_query(target.query):
            return
        path = target.path
        try:
            message_id = eve_http_path.match_route_segment(
                path,
                prefix="/api/messages/",
                label="Message id",
            )
            thread_id = eve_http_path.match_route_segment(
                path,
                prefix="/api/thread/",
                label="Thread id",
            )
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if path == "/health":
            backend_ok = self._backend_available()
            self._send_json(
                {
                    "ok": backend_ok,
                    "surface": "eve-app",
                    "backend_ok": backend_ok,
                },
                status=HTTPStatus.OK if backend_ok else HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        if path == "/api/status":
            backend_ok = self._backend_available()
            self._send_json(
                {
                    "ok": backend_ok,
                    "surface": "eve-app",
                    "backend": "ready" if backend_ok else "offline",
                    "provider_boundary": "local_eve_runtime",
                },
                status=HTTPStatus.OK if backend_ok else HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        if path == "/api/presence":
            self._handle_presence()
            return
        if path == "/api/eve-chat/spotlight-projection":
            self._handle_spotlight_projection()
            return
        if path == "/v1/models":
            self._proxy("GET", path)
            return
        if path == "/api/eve-chat/followups":
            suffix = path
            if target.query:
                suffix += f"?{target.query}"
            self._proxy("GET", suffix)
            return
        live_read_routes = {
            "/api/eve-app/snapshot",
            "/api/messages",
            "/api/thoughts",
            "/api/activity",
            "/api/reflections",
            "/api/personal-conversation/status",
            "/api/reply-progress",
            "/api/sensory/status",
        }
        dynamic_path = None
        if message_id is not None:
            dynamic_path = eve_http_path.build_route_path(
                prefix="/api/messages/",
                segment=message_id,
                label="Message id",
            )
        elif thread_id is not None:
            dynamic_path = eve_http_path.build_route_path(
                prefix="/api/thread/",
                segment=thread_id,
                label="Thread id",
            )
        if path in live_read_routes or dynamic_path is not None:
            suffix = dynamic_path or path
            if target.query:
                suffix += f"?{target.query}"
            self._proxy("GET", suffix)
            return
        if path.startswith("/api/") or path.startswith("/v1/"):
            self._send_json({"ok": False, "error": "Not found"}, status=HTTPStatus.NOT_FOUND)
            return
        self._serve_static(path)

    def do_HEAD(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        target = self._admit_target(self.path, head_only=True)
        if target is None:
            return
        if target.path.startswith("/api/") or target.path.startswith("/v1/") or target.path == "/health":
            self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
            self.send_header("Content-Length", "0")
            self.send_eve_private_response_headers()
            self.end_headers()
            return
        self._serve_static(target.path, head_only=True)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        target = self._admit_target(self.path, close_on_rejection=True)
        if target is None:
            return
        if not self._admit_query(target.query, close_on_rejection=True):
            return
        path = target.path
        try:
            message_id = eve_http_path.match_route_segment(
                path,
                prefix="/api/messages/",
                suffix="/mark",
                label="Message id",
            )
            followup_id = eve_http_path.match_route_segment(
                path,
                prefix="/api/eve-chat/followups/",
                suffix="/seen",
                label="Follow-up id",
            )
        except ValueError as exc:
            self.close_connection = True
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if not self._enforce_json_mutation_request():
            return
        if path == "/api/chat":
            self._handle_chat()
            return
        if path == "/api/message/reply":
            self._handle_personal_reply()
            return
        if message_id is not None:
            try:
                self._discard_request_body()
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._proxy(
                "POST",
                eve_http_path.build_route_path(
                    prefix="/api/messages/",
                    segment=message_id,
                    suffix="/mark",
                    label="Message id",
                ),
                body=b'{"status":"read"}',
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            return
        if followup_id is not None:
            try:
                self._discard_request_body()
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._proxy(
                "POST",
                eve_http_path.build_route_path(
                    prefix="/api/eve-chat/followups/",
                    segment=followup_id,
                    suffix="/seen",
                    label="Follow-up id",
                ),
                body=b"{}",
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            return
        if path in {"/api/sensory/session", "/api/sensory/events"}:
            origin = str(getattr(self, "_validated_mutation_origin", ""))
            if origin not in SENSORY_APP_ORIGINS:
                try:
                    self._discard_request_body()
                except ValueError:
                    pass
                self._send_json(
                    {"ok": False, "error": "Sensory control is restricted to the local Eve app origin."},
                    status=HTTPStatus.FORBIDDEN,
                )
                return
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._proxy(
                "POST",
                path,
                body=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Origin": origin,
                },
            )
            return
        self.close_connection = True
        self._send_json({"ok": False, "error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def _admit_target(
        self,
        target: str,
        *,
        close_on_rejection: bool = False,
        head_only: bool = False,
    ) -> eve_http_path.HTTPRequestTarget | None:
        try:
            parsed = eve_http_path.parse_request_target(target)
        except ValueError as exc:
            if close_on_rejection:
                self.close_connection = True
            if head_only:
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Length", "0")
                self.send_eve_private_response_headers()
                self.end_headers()
            else:
                self._send_json(
                    {"ok": False, "error": str(exc)},
                    status=HTTPStatus.BAD_REQUEST,
                )
            return None
        return parsed

    def _admit_query(self, query_string: str, *, close_on_rejection: bool = False) -> bool:
        try:
            eve_http_query.BoundedQuery.parse(query_string)
        except ValueError as exc:
            if close_on_rejection:
                self.close_connection = True
            self._send_json(
                {"ok": False, "error": str(exc)},
                status=HTTPStatus.BAD_REQUEST,
            )
            return False
        return True

    def _record_internal_error(self, error: BaseException, *, operation: str) -> str:
        return eve_http_server.record_http_internal_error(
            error,
            surface="eve-app",
            operation=operation,
        )

    def _enforce_json_mutation_request(self) -> bool:
        try:
            origin = eve_http_headers.optional_ascii_header(
                self.headers,
                "Origin",
                maximum_characters=512,
            )
            sec_fetch_site = eve_http_headers.optional_ascii_header(
                self.headers,
                "Sec-Fetch-Site",
                maximum_characters=32,
            )
            content_type = eve_http_headers.optional_ascii_header(
                self.headers,
                "Content-Type",
                maximum_characters=256,
            )
        except eve_http_headers.RequestHeaderError as exc:
            self.close_connection = True
            self._send_json(
                {"ok": False, "error": str(exc)},
                status=HTTPStatus.BAD_REQUEST,
            )
            return False
        decision = eve_http_security.evaluate_json_mutation_request(
            origin=origin,
            sec_fetch_site=sec_fetch_site,
            content_type=content_type,
            server_port=int(self.server.server_address[1]),
            extra_origins=SENSORY_APP_ORIGINS,
        )
        if decision.allowed:
            self._validated_mutation_origin = origin
            return True
        # The body is untrusted and may be arbitrarily large. Close rather than
        # draining it into the next keep-alive request boundary.
        self.close_connection = True
        self._send_json(
            {"ok": False, "error": decision.message},
            status=decision.status,
        )
        return False

    def _handle_chat(self) -> None:
        try:
            payload = self._read_json_body()
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            chat_id = eve_http_headers.require_ascii_field_value(
                payload.get("chat_id"),
                label="chat_id",
                maximum_characters=160,
                allow_empty=False,
            )
            messages = normalize_chat_messages(payload.get("messages"))
            user_message_id = eve_http_headers.require_ascii_field_value(
                payload.get("user_message_id"),
                label="user_message_id",
                maximum_characters=160,
            )
            stream = eve_http_json.boolean_field(payload, "stream", default=True)
        except (ValueError, eve_http_headers.RequestHeaderError) as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        upstream_payload = {
            "model": "eve",
            "messages": messages,
            "stream": stream,
        }
        body = json.dumps(upstream_payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json",
            "X-OpenWebUI-Chat-Id": chat_id,
        }
        if user_message_id:
            headers["X-OpenWebUI-User-Message-Id"] = user_message_id
        self._proxy("POST", "/v1/chat/completions", body=body, headers=headers, stream=stream)

    def _handle_personal_reply(self) -> None:
        try:
            payload = self._read_json_body()
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        try:
            message_id = eve_http_json.text_field(
                payload,
                "message_id",
                maximum_characters=MAX_PERSONAL_MESSAGE_ID_CHARS,
                required=True,
            )
            body_text = eve_http_json.text_field(
                payload,
                "body",
                label="Message body",
                maximum_characters=MAX_PERSONAL_MESSAGE_BODY_CHARS,
                required=True,
                multiline=True,
            )
            client_request_id = eve_http_json.text_field(
                payload,
                "client_request_id",
                maximum_characters=MAX_CLIENT_REQUEST_ID_CHARS,
            )
        except ValueError as exc:
            self._send_json(
                {"ok": False, "error": str(exc)},
                status=HTTPStatus.BAD_REQUEST,
            )
            return
        upstream_payload = {
            "message_id": message_id,
            "body": body_text,
            "client_request_id": client_request_id,
        }
        self._proxy(
            "POST",
            "/api/message/reply",
            body=json.dumps(upstream_payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=300,
        )

    def _read_json_body(self) -> dict[str, Any]:
        try:
            raw = eve_http_body.read_bounded_request_body(
                self.rfile,
                self.headers,
                maximum_bytes=MAX_REQUEST_BYTES,
            )
        except eve_http_body.RequestBodyFramingError:
            self.close_connection = True
            raise
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise ValueError("Request body must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return payload

    def _discard_request_body(self) -> None:
        try:
            eve_http_body.read_bounded_request_body(
                self.rfile,
                self.headers,
                maximum_bytes=MAX_REQUEST_BYTES,
                allow_empty=True,
            )
        except eve_http_body.RequestBodyFramingError:
            self.close_connection = True
            raise

    def _backend_available(self) -> bool:
        cached = self.server.cached_backend_health()
        if cached is not None:
            return cached
        request = urllib.request.Request(
            f"{self.server.backend_base}/v1/models",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=1.5) as response:
                available = 200 <= response.status < 300
        except (urllib.error.URLError, TimeoutError, OSError):
            available = False
        self.server.record_backend_health(available)
        return available

    def _handle_presence(self) -> None:
        now = time.monotonic()
        cached = self.server.presence_cache
        if cached is not None and now - self.server.presence_cache_at <= PRESENCE_CACHE_SECONDS:
            self._send_json({"ok": True, "data": cached})
            return

        request = urllib.request.Request(
            f"{self.server.backend_base}/api/monitor?compact=1",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=6) as response:
                payload = json.loads(
                    read_bounded_response(
                        response,
                        max_bytes=MAX_PRESENCE_RESPONSE_BYTES,
                        label="Eve's compact monitor",
                    ).decode("utf-8")
                )
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            UpstreamResponseError,
            http.client.HTTPException,
        ):
            self.server.record_backend_health(False)
            self._send_json(
                {"ok": False, "error": "Eve's current presence is temporarily unavailable."},
                status=HTTPStatus.BAD_GATEWAY,
            )
            return

        monitor = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(monitor, dict):
            self.server.record_backend_health(False)
            self._send_json(
                {"ok": False, "error": "Eve's current presence could not be read."},
                status=HTTPStatus.BAD_GATEWAY,
            )
            return

        presence = build_presence_snapshot(monitor)
        self.server.record_backend_health(True)
        self.server.presence_cache = presence
        self.server.presence_cache_at = now
        self._send_json({"ok": True, "data": presence})

    def _handle_spotlight_projection(self) -> None:
        try:
            config = json.loads(self.server.config_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            config = {}
        approval_source = str(config.get("spotlight_projection_approval_source") or "").strip()
        if config.get("spotlight_projection_enabled") is not True or not approval_source:
            self._send_json(
                {
                    "ok": False,
                    "error": "The derived Spotlight projection is not approved in Eve's runtime config.",
                },
                status=HTTPStatus.FORBIDDEN,
            )
            return

        monitor = build_spotlight_monitor_from_runtime_state(self.server.runtime_state_dir)
        projection = build_spotlight_projection(
            monitor,
            approved=True,
            approval_source=approval_source,
        )
        self._send_json(projection)

    def _proxy(
        self,
        method: str,
        suffix: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        stream: bool = False,
        timeout: float | None = None,
    ) -> None:
        target = f"{self.server.backend_base}{suffix}"
        request = urllib.request.Request(target, data=body, headers=headers or {}, method=method)
        try:
            response = urllib.request.urlopen(
                request,
                timeout=timeout if timeout is not None else (180 if stream else 15),
            )
        except urllib.error.HTTPError as exc:
            self.server.record_backend_health(exc.code < 500)
            try:
                error_body = read_bounded_response(
                    exc,
                    max_bytes=MAX_PROXY_ERROR_BYTES,
                    label="Eve's local runtime error",
                )
            except UpstreamResponseTooLarge:
                error_body = b'{"ok":false,"error":"Eve backend returned an oversized error"}'
            except (UpstreamResponseError, OSError, http.client.HTTPException):
                error_body = b'{"ok":false,"error":"Eve backend returned an unreadable error"}'
            finally:
                exc.close()
            if exc.code >= 500:
                error_id = self._record_internal_error(
                    exc,
                    operation="backend_http",
                )
                self._send_json(
                    {
                        "ok": False,
                        "error": "Eve's local runtime could not complete the request.",
                        "error_id": error_id,
                    },
                    status=HTTPStatus.BAD_GATEWAY,
                )
                return
            self._send_bytes(
                error_body or b'{"ok":false,"error":"Eve backend rejected the request"}',
                status=exc.code,
                content_type=exc.headers.get_content_type() if exc.headers else "application/json",
            )
            return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.server.record_backend_health(False)
            error_id = self._record_internal_error(
                exc,
                operation="backend_transport",
            )
            self._send_json(
                {
                    "ok": False,
                    "error": "Eve's local runtime is temporarily unavailable.",
                    "error_id": error_id,
                },
                status=HTTPStatus.BAD_GATEWAY,
            )
            return

        with response:
            content_type = response.headers.get("Content-Type", "application/octet-stream")
            if stream:
                self.server.record_backend_health(True)
                self.send_response(response.status)
                self.send_header("Content-Type", content_type)
                self.send_eve_private_response_headers()
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    while True:
                        chunk = response.read(STREAM_CHUNK_BYTES)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    # Stopping a reply closes the WebView connection by design.
                    pass
                self.close_connection = True
                return

            try:
                response_body = read_bounded_response(
                    response,
                    max_bytes=MAX_PROXY_RESPONSE_BYTES,
                    label="Eve's local runtime",
                )
            except UpstreamResponseTooLarge:
                self.server.record_backend_health(True)
                self._send_json(
                    {
                        "ok": False,
                        "error": "Eve's local runtime returned more data than this app route admits.",
                    },
                    status=HTTPStatus.BAD_GATEWAY,
                )
                return
            except (UpstreamResponseError, OSError, http.client.HTTPException) as exc:
                self.server.record_backend_health(False)
                error_id = self._record_internal_error(
                    exc,
                    operation="backend_response",
                )
                self._send_json(
                    {
                        "ok": False,
                        "error": "Eve's local runtime returned an incomplete response.",
                        "error_id": error_id,
                    },
                    status=HTTPStatus.BAD_GATEWAY,
                )
                return
            self.server.record_backend_health(True)
            self.send_response(response.status)
            self.send_header("Content-Type", content_type)
            self.send_eve_private_response_headers()
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)

    def _serve_static(self, request_path: str, *, head_only: bool = False) -> None:
        relative = urllib.parse.unquote(request_path).lstrip("/") or "index.html"
        root = self.server.static_root.resolve()
        candidate = (root / relative).resolve()
        if root != candidate and root not in candidate.parents:
            self._send_json({"ok": False, "error": "Not found"}, status=HTTPStatus.NOT_FOUND)
            return
        if candidate.is_dir():
            candidate = candidate / "index.html"
        if not candidate.is_file():
            # Never return HTML for a missing script or stylesheet: WebKit would
            # report an opaque module/asset load failure instead of a truthful 404.
            if Path(relative).suffix:
                self._send_json({"ok": False, "error": "Asset not found"}, status=HTTPStatus.NOT_FOUND)
                return
            # The tiny client has no server-side routes; navigation paths return its shell.
            candidate = root / "index.html"
        if not candidate.is_file():
            self._send_json({"ok": False, "error": "UI assets missing"}, status=HTTPStatus.NOT_FOUND)
            return

        content_type, _ = mimetypes.guess_type(candidate.name)
        data = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        # Stale WebKit assets would leave the user looking at an older Eve
        # after a successful rebuild, so the shared policy remains no-store.
        self.send_eve_document_security_headers(allow_sensory=True)
        self.end_headers()
        if not head_only:
            self.wfile.write(data)

    def _send_json(self, payload: object, *, status: int = HTTPStatus.OK) -> None:
        self._send_bytes(
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            status=status,
            content_type="application/json; charset=utf-8",
        )

    def _send_bytes(self, data: bytes, *, status: int, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_eve_private_response_headers()
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve Eve's local living timeline.")
    parser.add_argument("--host", default=os.environ.get("EVE_APP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("EVE_APP_PORT", "3000")))
    parser.add_argument("--backend", default=os.environ.get("EVE_APP_BACKEND", "http://127.0.0.1:8797"))
    parser.add_argument("--static-root", required=True)
    args = parser.parse_args()

    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("Eve's app server is loopback-only")
    static_root = Path(args.static_root).expanduser().resolve()
    if not (static_root / "index.html").is_file():
        parser.error(f"missing Eve app assets under {static_root}")

    detach_from_launcher()
    server = EveAppHTTPServer((args.host, args.port), EveAppHandler)
    server.static_root = static_root
    server.backend_base = str(args.backend).rstrip("/")
    print(
        f"Eve app listening on http://{args.host}:{args.port} "
        f"with local backend {server.backend_base}",
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
