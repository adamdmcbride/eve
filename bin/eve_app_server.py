#!/usr/bin/env python3
"""Serve Eve's local living timeline and proxy only its admitted routes."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


MAX_REQUEST_BYTES = 256 * 1024
MAX_CHAT_MESSAGES = 32
MAX_MESSAGE_CHARS = 16_000
STREAM_CHUNK_BYTES = 64 * 1024
PRESENCE_CACHE_SECONDS = 8.0
SENSORY_APP_ORIGINS = {
    "http://127.0.0.1:3000",
    "http://localhost:3000",
}


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


class EveAppHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    static_root: Path
    backend_base: str
    presence_cache: dict[str, Any] | None = None
    presence_cache_at: float = 0.0


class EveAppHandler(BaseHTTPRequestHandler):
    server: EveAppHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format_string: str, *args: object) -> None:
        # Never log request bodies, query values, or conversation text.
        path = urllib.parse.urlsplit(self.path).path
        sys.stderr.write(
            f"eve-app {self.client_address[0]} {self.command} {path} "
            + (format_string % args)
            + "\n"
        )

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/health":
            self._send_json(
                {
                    "ok": True,
                    "surface": "eve-app",
                    "backend_ok": self._backend_available(),
                }
            )
            return
        if parsed.path == "/api/status":
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
        if parsed.path == "/api/presence":
            self._handle_presence()
            return
        if parsed.path == "/v1/models":
            self._proxy("GET", parsed.path)
            return
        if parsed.path == "/api/eve-chat/followups":
            suffix = parsed.path
            if parsed.query:
                suffix += f"?{parsed.query}"
            self._proxy("GET", suffix)
            return
        live_read_routes = {
            "/api/messages",
            "/api/thoughts",
            "/api/activity",
            "/api/reflections",
            "/api/personal-conversation/status",
            "/api/reply-progress",
            "/api/sensory/status",
        }
        message_parts = parsed.path.strip("/").split("/")
        is_message_read = (
            len(message_parts) == 3
            and message_parts[0] == "api"
            and message_parts[1] == "messages"
            and bool(message_parts[2])
        )
        if parsed.path in live_read_routes or parsed.path.startswith("/api/thread/") or is_message_read:
            suffix = parsed.path
            if parsed.query:
                suffix += f"?{parsed.query}"
            self._proxy("GET", suffix)
            return
        if parsed.path.startswith("/api/") or parsed.path.startswith("/v1/"):
            self._send_json({"ok": False, "error": "Not found"}, status=HTTPStatus.NOT_FOUND)
            return
        self._serve_static(parsed.path)

    def do_HEAD(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path.startswith("/api/") or parsed.path.startswith("/v1/") or parsed.path == "/health":
            self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._serve_static(parsed.path, head_only=True)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/api/chat":
            self._handle_chat()
            return
        if parsed.path == "/api/message/reply":
            self._handle_personal_reply()
            return
        if parsed.path.startswith("/api/messages/") and parsed.path.endswith("/mark"):
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "messages" and parts[3] == "mark":
                try:
                    self._discard_request_body()
                except ValueError as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self._proxy(
                    "POST",
                    parsed.path,
                    body=b'{"status":"read"}',
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                )
                return
        if parsed.path.startswith("/api/eve-chat/followups/") and parsed.path.endswith("/seen"):
            try:
                self._discard_request_body()
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._proxy("POST", parsed.path, body=b"{}")
            return
        if parsed.path in {"/api/sensory/session", "/api/sensory/events"}:
            origin = str(self.headers.get("Origin") or "").strip()
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
                parsed.path,
                body=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Origin": origin,
                },
            )
            return
        self._send_json({"ok": False, "error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def _handle_chat(self) -> None:
        try:
            payload = self._read_json_body()
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        chat_id = str(payload.get("chat_id") or "").strip()
        try:
            messages = normalize_chat_messages(payload.get("messages"))
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if not chat_id or len(chat_id) > 160:
            self._send_json(
                {"ok": False, "error": "chat_id is required"},
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        upstream_payload = {
            "model": "eve",
            "messages": messages,
            "stream": bool(payload.get("stream", True)),
        }
        body = json.dumps(upstream_payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json",
            "X-OpenWebUI-Chat-Id": chat_id,
        }
        user_message_id = str(payload.get("user_message_id") or "").strip()
        if user_message_id:
            headers["X-OpenWebUI-User-Message-Id"] = user_message_id[:160]
        self._proxy("POST", "/v1/chat/completions", body=body, headers=headers, stream=True)

    def _handle_personal_reply(self) -> None:
        try:
            payload = self._read_json_body()
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        message_id = str(payload.get("message_id") or "").strip()
        body_text = str(payload.get("body") or "").strip()
        if not message_id or not body_text:
            self._send_json(
                {"ok": False, "error": "message_id and body are required"},
                status=HTTPStatus.BAD_REQUEST,
            )
            return
        upstream_payload = {
            "message_id": message_id[:160],
            "body": body_text[:8000],
            "client_request_id": str(payload.get("client_request_id") or "")[:160],
        }
        self._proxy(
            "POST",
            "/api/message/reply",
            body=json.dumps(upstream_payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=300,
        )

    def _read_json_body(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Invalid Content-Length") from exc
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise ValueError("Request body is empty or too large")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Request body must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return payload

    def _discard_request_body(self) -> None:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Invalid Content-Length") from exc
        if length < 0 or length > MAX_REQUEST_BYTES:
            raise ValueError("Request body is too large")
        if length:
            self.rfile.read(length)

    def _backend_available(self) -> bool:
        request = urllib.request.Request(
            f"{self.server.backend_base}/v1/models",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=1.5) as response:
                return 200 <= response.status < 300
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

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
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(
                {"ok": False, "error": "Eve's current presence is temporarily unavailable."},
                status=HTTPStatus.BAD_GATEWAY,
            )
            return

        monitor = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(monitor, dict):
            self._send_json(
                {"ok": False, "error": "Eve's current presence could not be read."},
                status=HTTPStatus.BAD_GATEWAY,
            )
            return

        presence = build_presence_snapshot(monitor)
        self.server.presence_cache = presence
        self.server.presence_cache_at = now
        self._send_json({"ok": True, "data": presence})

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
            error_body = exc.read()
            self._send_bytes(
                error_body or b'{"ok":false,"error":"Eve backend rejected the request"}',
                status=exc.code,
                content_type=exc.headers.get_content_type() if exc.headers else "application/json",
            )
            return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            self._send_json(
                {"ok": False, "error": f"Eve's local runtime is unavailable: {reason}"},
                status=HTTPStatus.BAD_GATEWAY,
            )
            return

        with response:
            content_type = response.headers.get("Content-Type", "application/octet-stream")
            self.send_response(response.status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if stream:
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

            response_body = response.read()
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
        # The app is installed and upgraded in place; stale WebKit assets would
        # leave the user looking at an older Eve after a successful rebuild.
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Permissions-Policy", "camera=(self), geolocation=(), microphone=(self)")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; connect-src 'self'; img-src 'self' data: blob:; "
            "style-src 'self'; script-src 'self'; media-src 'self' blob:; frame-src 'none'; "
            "frame-ancestors 'none'; form-action 'self'; base-uri 'none'",
        )
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
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
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
