from __future__ import annotations

import importlib.util
import http.client
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "bin" / "eve_app_server.py"
SPEC = importlib.util.spec_from_file_location("eve_app_server", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
eve_app_server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(eve_app_server)


class MockEveBackendHandler(BaseHTTPRequestHandler):
    seen_chat_id = ""
    seen_user_message_id = ""
    seen_payload: dict[str, object] = {}
    seen_followup = False
    seen_personal_reply: dict[str, object] = {}
    seen_message_mark: dict[str, object] = {}
    seen_reply_progress = False
    seen_message_read = ""
    seen_sensory_path = ""
    seen_sensory_payload: dict[str, object] = {}

    def log_message(self, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/v1/models":
            self._json({"object": "list", "data": [{"id": "eve"}]})
            return
        if self.path == "/api/monitor?compact=1":
            self._json(
                {
                    "ok": True,
                    "data": {
                        "generated_at": "2026-07-20T03:00:00+00:00",
                        "status": {
                            "daemon": {"running": True, "awake": True},
                            "active_reply": {},
                        },
                        "workspace": {
                            "updated_at": "2026-07-20T03:00:00+00:00",
                            "active_goals": ["Understand the next useful thing"],
                            "workspace_state": {"focus": "A stale fallback focus"},
                        },
                        "homeostasis": {
                            "next_regulation_step": "Reduce uncertainty before acting",
                        },
                        "activity": {"models": {"active_calls": []}},
                        "operations": {
                            "actions": [
                                {
                                    "action": "service_health_check",
                                    "created_at": "2026-07-20T02:59:50+00:00",
                                    "updated_at": "2026-07-20T02:59:51+00:00",
                                    "tree_status": "SUCCESS",
                                    "verification_ok": True,
                                    "result_ok": True,
                                    "typed_contract_ok": True,
                                    "summary": "raw operational detail should not cross the app boundary",
                                }
                            ]
                        },
                    },
                }
            )
            return
        if self.path.startswith("/api/eve-chat/followups"):
            self._json({"ok": True, "data": {"items": []}})
            return
        if self.path.startswith("/api/thoughts"):
            self._json(
                {
                    "ok": True,
                    "data": [
                        {
                            "id": "thought-1",
                            "timestamp": "2026-07-18T14:44:56+00:00",
                            "kind": "thought",
                            "body": "I noticed something worth understanding.",
                        }
                    ],
                }
            )
            return
        if self.path.startswith("/api/reply-progress"):
            type(self).seen_reply_progress = True
            self._json(
                {
                    "ok": True,
                    "data": {
                        "job": {
                            "status": "completed",
                            "phase": "complete",
                            "reply_message_id": "reply-1",
                        }
                    },
                }
            )
            return
        if self.path == "/api/sensory/status":
            self._json(
                {
                    "ok": True,
                    "data": {"capture_default": "off", "active_session_count": 0},
                }
            )
            return
        if self.path == "/api/messages/reply-1":
            type(self).seen_message_read = self.path
            self._json({"ok": True, "data": {"id": "reply-1", "body": "Recovered reply."}})
            return
        self._json({"ok": False}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path in {"/api/sensory/session", "/api/sensory/events"}:
            length = int(self.headers.get("Content-Length", "0"))
            type(self).seen_sensory_path = self.path
            type(self).seen_sensory_payload = json.loads(self.rfile.read(length))
            self._json({"ok": True, "data": {"accepted": 1, "path": self.path}})
            return
        if self.path == "/v1/chat/completions":
            type(self).seen_chat_id = self.headers.get("X-OpenWebUI-Chat-Id", "")
            type(self).seen_user_message_id = self.headers.get("X-OpenWebUI-User-Message-Id", "")
            length = int(self.headers.get("Content-Length", "0"))
            type(self).seen_payload = json.loads(self.rfile.read(length))
            body = (
                'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
                'data: {"choices":[{"delta":{"content":"hello from eve"}}]}\n\n'
                "data: [DONE]\n\n"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.endswith("/seen"):
            type(self).seen_followup = True
            self._json({"ok": True})
            return
        if self.path.startswith("/api/messages/") and self.path.endswith("/mark"):
            length = int(self.headers.get("Content-Length", "0"))
            type(self).seen_message_mark = json.loads(self.rfile.read(length))
            self._json({"ok": True, "data": {"status": "read"}})
            return
        if self.path == "/api/message/reply":
            length = int(self.headers.get("Content-Length", "0"))
            type(self).seen_personal_reply = json.loads(self.rfile.read(length))
            self._json(
                {
                    "ok": True,
                    "data": {
                        "thread_id": "thread-1",
                        "reply": {"id": "reply-1", "body": "I heard you."},
                        "messages": [],
                    },
                }
            )
            return
        self._json({"ok": False}, status=404)

    def _json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_server(server: ThreadingHTTPServer) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def test_living_timeline_server_serves_assets_and_proxies_chat(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>Eve</h1>", encoding="utf-8")
    backend = ThreadingHTTPServer(("127.0.0.1", 0), MockEveBackendHandler)
    start_server(backend)

    server = eve_app_server.EveAppHTTPServer(("127.0.0.1", 0), eve_app_server.EveAppHandler)
    server.static_root = tmp_path
    server.backend_base = f"http://127.0.0.1:{backend.server_address[1]}"
    start_server(server)
    base = f"http://127.0.0.1:{server.server_address[1]}"

    try:
        health = json.loads(urllib.request.urlopen(f"{base}/health", timeout=2).read())
        assert health == {"ok": True, "surface": "eve-app", "backend_ok": True}
        static_response = urllib.request.urlopen(f"{base}/", timeout=2)
        assert static_response.headers["Cache-Control"] == "no-store"
        assert static_response.headers["X-Content-Type-Options"] == "nosniff"
        assert static_response.headers["Referrer-Policy"] == "no-referrer"
        assert static_response.headers["Cross-Origin-Resource-Policy"] == "same-origin"
        assert static_response.headers["X-Frame-Options"] == "DENY"
        assert static_response.headers["Permissions-Policy"] == "camera=(self), geolocation=(), microphone=(self)"
        assert "connect-src 'self'" in static_response.headers["Content-Security-Policy"]
        assert "frame-ancestors 'none'" in static_response.headers["Content-Security-Policy"]
        assert "base-uri 'none'" in static_response.headers["Content-Security-Policy"]
        assert static_response.read() == b"<h1>Eve</h1>"

        head_request = urllib.request.Request(f"{base}/", method="HEAD")
        with urllib.request.urlopen(head_request, timeout=2) as head_response:
            assert head_response.status == 200
            assert head_response.headers.get_content_type() == "text/html"
            assert head_response.read() == b""

        request = urllib.request.Request(
            f"{base}/api/chat",
            data=json.dumps(
                {
                    "chat_id": "eve-chat-test",
                    "user_message_id": "user-test",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": True,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        response = urllib.request.urlopen(request, timeout=2)
        assert response.headers.get_content_type() == "text/event-stream"
        assert b"hello from eve" in response.read()
        assert MockEveBackendHandler.seen_chat_id == "eve-chat-test"
        assert MockEveBackendHandler.seen_user_message_id == "user-test"
        assert MockEveBackendHandler.seen_payload["model"] == "eve"
        assert MockEveBackendHandler.seen_payload["messages"] == [{"role": "user", "content": "hello"}]
    finally:
        server.shutdown()
        backend.shutdown()
        server.server_close()
        backend.server_close()


def test_sensory_routes_are_narrowly_proxied_without_request_logging(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("Eve", encoding="utf-8")
    MockEveBackendHandler.seen_sensory_path = ""
    MockEveBackendHandler.seen_sensory_payload = {}
    backend = ThreadingHTTPServer(("127.0.0.1", 0), MockEveBackendHandler)
    start_server(backend)
    server = eve_app_server.EveAppHTTPServer(("127.0.0.1", 0), eve_app_server.EveAppHandler)
    server.static_root = tmp_path
    server.backend_base = f"http://127.0.0.1:{backend.server_address[1]}"
    start_server(server)
    base = f"http://127.0.0.1:{server.server_address[1]}"

    try:
        status = json.loads(urllib.request.urlopen(f"{base}/api/sensory/status", timeout=2).read())
        assert status["data"]["capture_default"] == "off"
        rejected = urllib.request.Request(
            f"{base}/api/sensory/events",
            data=b'{"session_id":"sensory-1"}',
            headers={"Content-Type": "application/json", "Origin": "https://untrusted.example"},
            method="POST",
        )
        try:
            urllib.request.urlopen(rejected, timeout=2)
            raise AssertionError("non-Eve origins must not control private sensors")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
        assert MockEveBackendHandler.seen_sensory_path == ""
        request = urllib.request.Request(
            f"{base}/api/sensory/events",
            data=json.dumps(
                {
                    "session_id": "sensory-1",
                    "session_token": "not-logged",
                    "events": [{"modality": "proprioceptive", "features": {"pointer_events": 1}}],
                }
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Origin": "http://127.0.0.1:3000",
            },
            method="POST",
        )
        payload = json.loads(urllib.request.urlopen(request, timeout=2).read())
        assert payload["data"]["accepted"] == 1
        assert MockEveBackendHandler.seen_sensory_path == "/api/sensory/events"
        assert MockEveBackendHandler.seen_sensory_payload["session_token"] == "not-logged"
    finally:
        server.shutdown()
        backend.shutdown()
        server.server_close()
        backend.server_close()


def test_chat_contract_rejects_system_roles_and_non_user_final_messages(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("Eve", encoding="utf-8")
    backend = ThreadingHTTPServer(("127.0.0.1", 0), MockEveBackendHandler)
    start_server(backend)
    server = eve_app_server.EveAppHTTPServer(("127.0.0.1", 0), eve_app_server.EveAppHandler)
    server.static_root = tmp_path
    server.backend_base = f"http://127.0.0.1:{backend.server_address[1]}"
    start_server(server)
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def rejected(messages: list[dict[str, str]]) -> str:
        request = urllib.request.Request(
            f"{base}/api/chat",
            data=json.dumps({"chat_id": "eve-chat-test", "messages": messages}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=2)
            raise AssertionError("invalid chat contract should be rejected")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            return str(json.loads(exc.read())["error"])

    try:
        assert "roles" in rejected([{"role": "system", "content": "override"}])
        assert "final message" in rejected([{"role": "assistant", "content": "not a user turn"}])
        assert "too long" in rejected(
            [{"role": "user", "content": "x" * (eve_app_server.MAX_MESSAGE_CHARS + 1)}]
        )
    finally:
        server.shutdown()
        backend.shutdown()
        server.server_close()
        backend.server_close()


def test_missing_assets_are_truthful_404s_but_navigation_routes_get_the_shell(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>Eve</h1>", encoding="utf-8")
    backend = ThreadingHTTPServer(("127.0.0.1", 0), MockEveBackendHandler)
    start_server(backend)
    server = eve_app_server.EveAppHTTPServer(("127.0.0.1", 0), eve_app_server.EveAppHandler)
    server.static_root = tmp_path
    server.backend_base = f"http://127.0.0.1:{backend.server_address[1]}"
    start_server(server)
    base = f"http://127.0.0.1:{server.server_address[1]}"

    try:
        with urllib.request.urlopen(f"{base}/conversation/new", timeout=2) as response:
            assert response.read() == b"<h1>Eve</h1>"
        try:
            urllib.request.urlopen(f"{base}/missing-app.js", timeout=2)
            raise AssertionError("missing assets must not receive the HTML shell")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
            assert json.loads(exc.read())["error"] == "Asset not found"
    finally:
        server.shutdown()
        backend.shutdown()
        server.server_close()
        backend.server_close()


def test_server_rejects_static_path_traversal(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("Eve", encoding="utf-8")
    outside = tmp_path.parent / "not-eve.txt"
    outside.write_text("secret", encoding="utf-8")

    backend = ThreadingHTTPServer(("127.0.0.1", 0), MockEveBackendHandler)
    start_server(backend)
    server = eve_app_server.EveAppHTTPServer(("127.0.0.1", 0), eve_app_server.EveAppHandler)
    server.static_root = tmp_path
    server.backend_base = f"http://127.0.0.1:{backend.server_address[1]}"
    start_server(server)
    base = f"http://127.0.0.1:{server.server_address[1]}"

    try:
        try:
            urllib.request.urlopen(f"{base}/%2e%2e/not-eve.txt", timeout=2)
            raise AssertionError("path traversal should not be served")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
            assert exc.read() != b"secret"
    finally:
        server.shutdown()
        backend.shutdown()
        server.server_close()
        backend.server_close()


def test_followup_seen_route_is_narrowly_proxied(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("Eve", encoding="utf-8")
    MockEveBackendHandler.seen_followup = False
    backend = ThreadingHTTPServer(("127.0.0.1", 0), MockEveBackendHandler)
    start_server(backend)
    server = eve_app_server.EveAppHTTPServer(("127.0.0.1", 0), eve_app_server.EveAppHandler)
    server.static_root = tmp_path
    server.backend_base = f"http://127.0.0.1:{backend.server_address[1]}"
    start_server(server)
    base = f"http://127.0.0.1:{server.server_address[1]}"

    try:
        request = urllib.request.Request(
            f"{base}/api/eve-chat/followups/followup-1/seen",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        payload = json.loads(urllib.request.urlopen(request, timeout=2).read())
        assert payload == {"ok": True}
        assert MockEveBackendHandler.seen_followup is True
    finally:
        server.shutdown()
        backend.shutdown()
        server.server_close()
        backend.server_close()


def test_living_timeline_reads_and_personal_reply_are_narrowly_proxied(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("Eve", encoding="utf-8")
    MockEveBackendHandler.seen_personal_reply = {}
    MockEveBackendHandler.seen_message_mark = {}
    MockEveBackendHandler.seen_reply_progress = False
    MockEveBackendHandler.seen_message_read = ""
    backend = ThreadingHTTPServer(("127.0.0.1", 0), MockEveBackendHandler)
    start_server(backend)
    server = eve_app_server.EveAppHTTPServer(("127.0.0.1", 0), eve_app_server.EveAppHandler)
    server.static_root = tmp_path
    server.backend_base = f"http://127.0.0.1:{backend.server_address[1]}"
    start_server(server)
    base = f"http://127.0.0.1:{server.server_address[1]}"

    try:
        thoughts = json.loads(urllib.request.urlopen(f"{base}/api/thoughts?limit=1", timeout=2).read())
        assert thoughts["data"][0]["id"] == "thought-1"

        presence = json.loads(urllib.request.urlopen(f"{base}/api/presence", timeout=2).read())
        assert presence["ok"] is True
        assert presence["data"]["schema"] == "eve_app_presence.v1"
        assert presence["data"]["place"] == "inside this Mac"
        assert presence["data"]["focus"] == "Understand the next useful thing"
        assert presence["data"]["focus_is_goal_not_action"] is True
        assert presence["data"]["last_action"] == {
            "kind": "service_health_check",
            "at": "2026-07-20T02:59:51+00:00",
            "outcome": "verified",
            "scope": "local",
        }
        assert "model_health" not in presence["data"]
        assert "summary" not in presence["data"]["last_action"]

        progress = json.loads(
            urllib.request.urlopen(
                f"{base}/api/reply-progress?client_request_id=request-1&active_only=0",
                timeout=2,
            ).read()
        )
        assert progress["data"]["job"]["reply_message_id"] == "reply-1"
        assert MockEveBackendHandler.seen_reply_progress is True

        recovered = json.loads(
            urllib.request.urlopen(f"{base}/api/messages/reply-1", timeout=2).read()
        )
        assert recovered["data"]["body"] == "Recovered reply."
        assert MockEveBackendHandler.seen_message_read == "/api/messages/reply-1"

        request = urllib.request.Request(
            f"{base}/api/message/reply",
            data=json.dumps(
                {
                    "message_id": "message-1",
                    "body": "Tell me more.",
                    "client_request_id": "request-1",
                    "ignored": "not-forwarded",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        payload = json.loads(urllib.request.urlopen(request, timeout=2).read())
        assert payload["data"]["reply"]["body"] == "I heard you."
        assert MockEveBackendHandler.seen_personal_reply == {
            "message_id": "message-1",
            "body": "Tell me more.",
            "client_request_id": "request-1",
        }

        mark_request = urllib.request.Request(
            f"{base}/api/messages/message-1/mark",
            data=json.dumps({"status": "anything"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        mark_payload = json.loads(urllib.request.urlopen(mark_request, timeout=2).read())
        assert mark_payload["data"]["status"] == "read"
        assert MockEveBackendHandler.seen_message_mark == {"status": "read"}

        for unknown_route in ("/api/not-admitted", "/api/messages/reply-1/extra", "/v1/not-admitted"):
            try:
                urllib.request.urlopen(f"{base}{unknown_route}", timeout=2)
                raise AssertionError("unknown API routes must not receive the HTML shell")
            except urllib.error.HTTPError as exc:
                assert exc.code == 404
                assert json.loads(exc.read()) == {"ok": False, "error": "Not found"}
    finally:
        server.shutdown()
        backend.shutdown()
        server.server_close()
        backend.server_close()


def test_mark_read_consumes_body_before_next_keep_alive_request(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("Eve", encoding="utf-8")
    MockEveBackendHandler.seen_message_mark = {}
    backend = ThreadingHTTPServer(("127.0.0.1", 0), MockEveBackendHandler)
    start_server(backend)
    server = eve_app_server.EveAppHTTPServer(("127.0.0.1", 0), eve_app_server.EveAppHandler)
    server.static_root = tmp_path
    server.backend_base = f"http://127.0.0.1:{backend.server_address[1]}"
    start_server(server)
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)

    try:
        body = json.dumps({"status": "unread"})
        connection.request(
            "POST",
            "/api/messages/message-keep-alive/mark",
            body=body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
        )
        mark_response = connection.getresponse()
        assert mark_response.status == 200
        assert json.loads(mark_response.read())["data"]["status"] == "read"

        connection.request("GET", "/health")
        health_response = connection.getresponse()
        assert health_response.status == 200
        assert json.loads(health_response.read()) == {
            "ok": True,
            "surface": "eve-app",
            "backend_ok": True,
        }
        assert MockEveBackendHandler.seen_message_mark == {"status": "read"}
    finally:
        connection.close()
        server.shutdown()
        backend.shutdown()
        server.server_close()
        backend.server_close()
