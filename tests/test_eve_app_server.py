from __future__ import annotations

import importlib.util
import http.client
import io
import json
import threading
import urllib.error
import urllib.request
from email.message import Message
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch


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
    seen_monitor = 0

    def log_message(self, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/v1/models":
            self._json({"object": "list", "data": [{"id": "eve"}]})
            return
        if self.path == "/api/monitor?compact=1":
            type(self).seen_monitor += 1
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


def test_post_policy_runs_before_app_mutation_dispatch() -> None:
    handler = object.__new__(eve_app_server.EveAppHandler)
    handler.server = type("Server", (), {"server_address": ("127.0.0.1", 3000)})()
    handler.path = "/api/chat"
    handler.close_connection = False
    sent: list[tuple[object, int]] = []
    dispatched: list[bool] = []
    handler._send_json = lambda payload, status=HTTPStatus.OK: sent.append((payload, status))
    handler._handle_chat = lambda: dispatched.append(True)

    handler.headers = {"Content-Type": "text/plain"}
    handler.do_POST()
    assert dispatched == []
    assert sent[-1][1] == HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    assert handler.close_connection is True

    handler.close_connection = False
    handler.headers = {
        "Content-Type": "application/json",
        "Origin": "http://127.0.0.1:3000",
        "Sec-Fetch-Site": "same-origin",
    }
    handler.do_POST()
    assert dispatched == [True]
    assert handler.close_connection is False


def test_app_rejects_duplicate_consumed_header_before_mutation_dispatch() -> None:
    handler = object.__new__(eve_app_server.EveAppHandler)
    handler.server = type("Server", (), {"server_address": ("127.0.0.1", 3000)})()
    handler.path = "/api/chat"
    handler.close_connection = False
    sent: list[tuple[object, int]] = []
    dispatched: list[bool] = []
    handler._send_json = lambda payload, status=HTTPStatus.OK: sent.append((payload, status))
    handler._handle_chat = lambda: dispatched.append(True)
    headers = Message()
    headers.add_header("Content-Type", "application/json")
    headers.add_header("Origin", "http://127.0.0.1:3000")
    headers.add_header("Origin", "http://127.0.0.1:3000")
    handler.headers = headers

    handler.do_POST()

    assert dispatched == []
    assert sent[-1][1] == HTTPStatus.BAD_REQUEST
    assert "Multiple Origin" in sent[-1][0]["error"]
    assert handler.close_connection is True


def test_app_chat_transport_ids_must_fit_safe_forward_headers() -> None:
    cases = (
        {"chat_id": "x" * 161},
        {"chat_id": "chat\nid"},
        {"chat_id": "éve-chat"},
        {"chat_id": "chat-1", "user_message_id": "x" * 161},
    )
    for metadata in cases:
        payload = {
            **metadata,
            "messages": [{"role": "user", "content": "hello"}],
        }
        raw = json.dumps(payload).encode("utf-8")
        handler = object.__new__(eve_app_server.EveAppHandler)
        handler.headers = {
            "Content-Length": str(len(raw)),
            "Content-Type": "application/json",
        }
        handler.rfile = io.BytesIO(raw)
        sent: list[tuple[object, int]] = []
        proxied: list[tuple[object, ...]] = []
        handler._send_json = lambda body, status=HTTPStatus.OK: sent.append((body, status))
        handler._proxy = lambda *args, **kwargs: proxied.append((args, kwargs))

        handler._handle_chat()

        assert sent[-1][1] == HTTPStatus.BAD_REQUEST
        assert proxied == []


def test_app_chat_stream_is_a_strict_json_boolean() -> None:
    for stream in ("false", 0, None):
        payload = {
            "chat_id": "chat-1",
            "stream": stream,
            "messages": [{"role": "user", "content": "hello"}],
        }
        raw = json.dumps(payload).encode("utf-8")
        handler = object.__new__(eve_app_server.EveAppHandler)
        handler.headers = {
            "Content-Length": str(len(raw)),
            "Content-Type": "application/json",
        }
        handler.rfile = io.BytesIO(raw)
        sent: list[tuple[object, int]] = []
        proxied: list[tuple[object, ...]] = []
        handler._send_json = lambda body, status=HTTPStatus.OK: sent.append((body, status))
        handler._proxy = lambda *args, **kwargs: proxied.append((args, kwargs))

        handler._handle_chat()

        assert sent[-1][1] == HTTPStatus.BAD_REQUEST
        assert "JSON Boolean" in sent[-1][0]["error"]
        assert proxied == []


def test_app_chat_forwards_a_valid_false_stream_without_coercion() -> None:
    payload = {
        "chat_id": "chat-1",
        "stream": False,
        "messages": [{"role": "user", "content": "hello"}],
    }
    raw = json.dumps(payload).encode("utf-8")
    handler = object.__new__(eve_app_server.EveAppHandler)
    handler.headers = {
        "Content-Length": str(len(raw)),
        "Content-Type": "application/json",
    }
    handler.rfile = io.BytesIO(raw)
    proxied: list[tuple[tuple[object, ...], dict[str, object]]] = []
    handler._send_json = lambda *_args, **_kwargs: None
    handler._proxy = lambda *args, **kwargs: proxied.append((args, kwargs))

    handler._handle_chat()

    assert len(proxied) == 1
    upstream_payload = json.loads(proxied[0][1]["body"])
    assert upstream_payload["stream"] is False
    assert proxied[0][1]["stream"] is False


def test_app_personal_reply_rejects_oversized_fields_instead_of_truncating() -> None:
    cases = (
        {"message_id": "x" * 161, "body": "hello"},
        {"message_id": "message-1", "body": "x" * 8001},
        {"message_id": "message-1", "body": "hello", "client_request_id": "x" * 161},
        {"message_id": 17, "body": "hello"},
    )
    for payload in cases:
        raw = json.dumps(payload).encode("utf-8")
        handler = object.__new__(eve_app_server.EveAppHandler)
        handler.headers = {
            "Content-Length": str(len(raw)),
            "Content-Type": "application/json",
        }
        handler.rfile = io.BytesIO(raw)
        sent: list[tuple[object, int]] = []
        proxied: list[tuple[object, ...]] = []
        handler._send_json = lambda body, status=HTTPStatus.OK: sent.append((body, status))
        handler._proxy = lambda *args, **kwargs: proxied.append((args, kwargs))

        handler._handle_personal_reply()

        assert sent[-1][1] == HTTPStatus.BAD_REQUEST
        assert proxied == []


def test_app_personal_reply_forwards_exact_valid_fields() -> None:
    payload = {
        "message_id": "message-1",
        "body": "first\nsecond",
        "client_request_id": "request-1",
    }
    raw = json.dumps(payload).encode("utf-8")
    handler = object.__new__(eve_app_server.EveAppHandler)
    handler.headers = {
        "Content-Length": str(len(raw)),
        "Content-Type": "application/json",
    }
    handler.rfile = io.BytesIO(raw)
    proxied: list[tuple[tuple[object, ...], dict[str, object]]] = []
    handler._send_json = lambda *_args, **_kwargs: None
    handler._proxy = lambda *args, **kwargs: proxied.append((args, kwargs))

    handler._handle_personal_reply()

    assert len(proxied) == 1
    assert json.loads(proxied[0][1]["body"]) == payload


def test_app_query_budget_runs_before_proxy_or_mutation_dispatch() -> None:
    handler = object.__new__(eve_app_server.EveAppHandler)
    sent: list[tuple[object, int]] = []
    proxied: list[tuple[object, ...]] = []
    dispatched: list[bool] = []
    handler._send_json = lambda payload, status=HTTPStatus.OK: sent.append((payload, status))
    handler._proxy = lambda *args, **kwargs: proxied.append((args, kwargs))
    handler._handle_chat = lambda: dispatched.append(True)
    handler.headers = {"Content-Type": "application/json"}
    handler.close_connection = False

    handler.path = "/api/thoughts?value=" + (
        "a" * (eve_app_server.eve_http_query.DEFAULT_MAX_QUERY_CHARACTERS + 1)
    )
    handler.do_GET()

    assert sent[-1][1] == HTTPStatus.BAD_REQUEST
    assert proxied == []
    assert handler.close_connection is False

    handler.path = "/api/chat?broken-field"
    handler.do_POST()

    assert sent[-1][1] == HTTPStatus.BAD_REQUEST
    assert dispatched == []
    assert handler.close_connection is True


def test_app_dynamic_routes_are_exact_and_canonically_forwarded() -> None:
    handler = object.__new__(eve_app_server.EveAppHandler)
    handler.server = type("Server", (), {"server_address": ("127.0.0.1", 3000)})()
    sent: list[tuple[object, int]] = []
    proxied: list[tuple[tuple[object, ...], dict[str, object]]] = []
    discarded: list[bool] = []
    handler._send_json = lambda payload, status=HTTPStatus.OK: sent.append((payload, status))
    handler._proxy = lambda *args, **kwargs: proxied.append((args, kwargs))
    handler._discard_request_body = lambda: discarded.append(True)
    handler.headers = {"Content-Type": "application/json"}
    handler.close_connection = False

    handler.path = "/api/thread/thread%2fwith%20space"
    handler.do_GET()
    assert proxied[-1][0] == ("GET", "/api/thread/thread%2Fwith%20space")

    handler.path = "/api/messages/message%2fone/mark"
    handler.do_POST()
    assert discarded == [True]
    assert proxied[-1][0] == ("POST", "/api/messages/message%2Fone/mark")
    assert handler.close_connection is False

    prior_proxy_count = len(proxied)
    handler.path = "/api/messages/message-one/extra/mark"
    handler.do_POST()
    assert sent[-1][1] == HTTPStatus.NOT_FOUND
    assert len(proxied) == prior_proxy_count
    assert handler.close_connection is True


def test_app_rejects_invalid_or_oversized_paths_before_proxy_dispatch() -> None:
    handler = object.__new__(eve_app_server.EveAppHandler)
    handler.server = type("Server", (), {"server_address": ("127.0.0.1", 3000)})()
    sent: list[tuple[object, int]] = []
    proxied: list[tuple[object, ...]] = []
    handler._send_json = lambda payload, status=HTTPStatus.OK: sent.append((payload, status))
    handler._proxy = lambda *args, **kwargs: proxied.append((args, kwargs))
    handler.headers = {"Content-Type": "application/json"}
    handler.close_connection = False

    handler.path = "/api/thread/%00"
    handler.do_GET()
    assert sent[-1][1] == HTTPStatus.BAD_REQUEST
    assert proxied == []
    assert handler.close_connection is False

    handler.path = "/api/messages/" + ("a" * 513) + "/mark"
    handler.do_POST()
    assert sent[-1][1] == HTTPStatus.BAD_REQUEST
    assert proxied == []
    assert handler.close_connection is True

    handler.close_connection = False
    handler.path = "http://foreign.example/api/chat"
    handler.do_POST()
    assert sent[-1][1] == HTTPStatus.BAD_REQUEST
    assert proxied == []
    assert handler.close_connection is True


def test_app_request_log_is_bounded_query_free_and_control_safe() -> None:
    handler = object.__new__(eve_app_server.EveAppHandler)
    handler.path = "/api/chat?secret=PRIVATE\nINJECT"
    handler.command = "POST\nBAD"
    handler.client_address = ("127.0.0.1\nBAD", 12345)
    output = io.StringIO()

    with patch.object(eve_app_server.sys, "stderr", output):
        handler.log_message('"%s" %s %s', "SECRET REQUEST LINE", "200", "42")

    line = output.getvalue()
    assert line.count("\n") == 1
    assert "PRIVATE" not in line
    assert "SECRET REQUEST LINE" not in line
    assert "INJECT" not in line
    assert "\\nBAD" in line
    assert 'path="/api/chat"' in line
    assert 'status="200"' in line
    assert handler.version_string() == "EveApp/1.0"
    assert "Python" not in handler.version_string()


def test_app_json_reader_rejects_incomplete_framing_and_closes_connection() -> None:
    handler = object.__new__(eve_app_server.EveAppHandler)
    handler.headers = {"Content-Length": "3"}
    handler.rfile = io.BytesIO(b"{}")
    handler.close_connection = False

    try:
        handler._read_json_body()
        raise AssertionError("an incomplete declared body must be rejected")
    except eve_app_server.eve_http_body.IncompleteRequestBody as exc:
        assert "2 of 3 declared bytes" in str(exc)

    assert handler.close_connection is True


def test_app_json_reader_reports_invalid_utf8_as_a_client_error() -> None:
    handler = object.__new__(eve_app_server.EveAppHandler)
    handler.headers = {"Content-Length": "1"}
    handler.rfile = io.BytesIO(b"\xff")
    handler.close_connection = False

    try:
        handler._read_json_body()
        raise AssertionError("invalid UTF-8 must not reach JSON dispatch")
    except ValueError as exc:
        assert "valid JSON" in str(exc)

    assert handler.close_connection is False


def test_eve_app_snapshot_is_an_explicit_read_only_proxy_route() -> None:
    handler = object.__new__(eve_app_server.EveAppHandler)
    handler.path = "/api/eve-app/snapshot"
    proxied: list[tuple[str, str]] = []
    handler._proxy = lambda method, suffix: proxied.append((method, suffix))

    handler.do_GET()

    assert proxied == [("GET", "/api/eve-app/snapshot")]


def test_health_is_unavailable_until_eves_backend_is_ready() -> None:
    handler = object.__new__(eve_app_server.EveAppHandler)
    handler.path = "/health"
    sent: list[tuple[object, int]] = []
    handler._backend_available = lambda: False
    handler._send_json = lambda payload, status=HTTPStatus.OK: sent.append((payload, status))

    handler.do_GET()

    payload, status = sent[-1]
    assert status == HTTPStatus.SERVICE_UNAVAILABLE
    assert payload == {"ok": False, "surface": "eve-app", "backend_ok": False}


def test_backend_health_cache_has_short_asymmetric_expiry() -> None:
    server = object.__new__(eve_app_server.EveAppHTTPServer)
    server._backend_health_cache = None
    server._backend_health_cache_at = 0.0
    server._backend_health_lock = eve_app_server.threading.Lock()

    server.record_backend_health(True, now=100.0)
    assert server.cached_backend_health(now=112.0) is True
    assert server.cached_backend_health(now=112.001) is None

    server.record_backend_health(False, now=200.0)
    assert server.cached_backend_health(now=201.0) is False
    assert server.cached_backend_health(now=201.001) is None


def test_backend_health_cache_is_instance_scoped() -> None:
    first = eve_app_server.EveAppHTTPServer(
        ("127.0.0.1", 0),
        eve_app_server.EveAppHandler,
        bind_and_activate=False,
    )
    second = eve_app_server.EveAppHTTPServer(
        ("127.0.0.1", 0),
        eve_app_server.EveAppHandler,
        bind_and_activate=False,
    )
    try:
        assert first.max_active_requests == 32
        assert issubclass(
            eve_app_server.EveAppHandler,
            eve_app_server.eve_http_server.EveBoundedHTTPRequestHandler,
        )
        first.record_backend_health(True, now=100.0)
        assert first.cached_backend_health(now=100.0) is True
        assert second.cached_backend_health(now=100.0) is None
    finally:
        first.server_close()
        second.server_close()


def test_backend_health_uses_recent_real_traffic_without_a_probe() -> None:
    handler = object.__new__(eve_app_server.EveAppHandler)
    handler.server = type(
        "Server",
        (),
        {"cached_backend_health": lambda _self: True},
    )()

    with patch.object(
        eve_app_server.urllib.request,
        "urlopen",
        side_effect=AssertionError("a recent app success should avoid a redundant probe"),
    ):
        assert handler._backend_available() is True


def test_backend_health_probe_refreshes_an_expired_cache() -> None:
    recorded: list[bool] = []
    handler = object.__new__(eve_app_server.EveAppHandler)
    handler.server = type(
        "Server",
        (),
        {
            "backend_base": "http://127.0.0.1:8797",
            "cached_backend_health": lambda _self: None,
            "record_backend_health": lambda _self, value: recorded.append(value),
        },
    )()

    response = type(
        "Response",
        (),
        {
            "status": 200,
            "__enter__": lambda self: self,
            "__exit__": lambda self, *_args: None,
        },
    )()
    with patch.object(eve_app_server.urllib.request, "urlopen", return_value=response) as urlopen:
        assert handler._backend_available() is True

    urlopen.assert_called_once()
    assert recorded == [True]


def test_successful_proxy_response_refreshes_backend_health() -> None:
    recorded: list[bool] = []
    handler = object.__new__(eve_app_server.EveAppHandler)
    handler.server = type(
        "Server",
        (),
        {
            "backend_base": "http://127.0.0.1:8797",
            "record_backend_health": lambda _self, value: recorded.append(value),
        },
    )()
    handler.send_response = lambda _status: None
    handler.send_header = lambda _name, _value: None
    handler.end_headers = lambda: None
    handler.wfile = io.BytesIO()
    response = type(
        "Response",
        (),
        {
            "status": 200,
            "headers": {"Content-Type": "application/json"},
            "read": lambda _self, _size=-1: b'{"ok":true}',
            "__enter__": lambda self: self,
            "__exit__": lambda self, *_args: None,
        },
    )()

    with patch.object(eve_app_server.urllib.request, "urlopen", return_value=response):
        handler._proxy("GET", "/api/eve-app/snapshot")

    assert recorded == [True]
    assert handler.wfile.getvalue() == b'{"ok":true}'


def test_bounded_upstream_reader_checks_declared_and_actual_size() -> None:
    class Response(io.BytesIO):
        def __init__(self, body: bytes, headers: dict[str, str]) -> None:
            super().__init__(body)
            self.headers = headers

    assert eve_app_server.read_bounded_response(
        Response(b"1234", {"Content-Length": "4"}),
        max_bytes=4,
        label="test backend",
    ) == b"1234"

    try:
        eve_app_server.read_bounded_response(
            Response(b"12345", {"Content-Length": "5"}),
            max_bytes=4,
            label="test backend",
        )
        raise AssertionError("an oversized declared response must be rejected")
    except ValueError as exc:
        assert "4-byte response limit" in str(exc)

    try:
        eve_app_server.read_bounded_response(
            Response(b"12345", {}),
            max_bytes=4,
            label="test backend",
        )
        raise AssertionError("an oversized undeclared response must be rejected")
    except ValueError as exc:
        assert "4-byte response limit" in str(exc)

    try:
        eve_app_server.read_bounded_response(
            Response(b"1234", {"Content-Length": "5"}),
            max_bytes=5,
            label="test backend",
        )
        raise AssertionError("a truncated declared response must be rejected")
    except eve_app_server.UpstreamResponseError as exc:
        assert "ended before" in str(exc)


def test_oversized_non_stream_proxy_response_is_rejected_before_headers_are_sent() -> None:
    recorded: list[bool] = []
    sent: list[tuple[object, int]] = []
    response = type(
        "Response",
        (),
        {
            "status": 200,
            "headers": {"Content-Type": "application/json"},
            "read": lambda _self, size=-1: b"x" * size,
            "__enter__": lambda self: self,
            "__exit__": lambda self, *_args: None,
        },
    )()
    handler = object.__new__(eve_app_server.EveAppHandler)
    handler.server = type(
        "Server",
        (),
        {
            "backend_base": "http://127.0.0.1:8797",
            "record_backend_health": lambda _self, value: recorded.append(value),
        },
    )()
    handler._send_json = lambda payload, status=HTTPStatus.OK: sent.append((payload, status))
    handler.send_response = lambda _status: (_ for _ in ()).throw(
        AssertionError("response headers must wait until the body passes its bound")
    )

    with patch.object(eve_app_server, "MAX_PROXY_RESPONSE_BYTES", 16), patch.object(
        eve_app_server.urllib.request,
        "urlopen",
        return_value=response,
    ):
        handler._proxy("GET", "/api/eve-app/snapshot")

    assert recorded == [True]
    assert sent[-1][1] == HTTPStatus.BAD_GATEWAY
    assert "more data" in str(sent[-1][0])


def test_incomplete_non_stream_proxy_response_invalidates_backend_health() -> None:
    recorded: list[bool] = []
    sent: list[tuple[object, int]] = []
    response = type(
        "Response",
        (),
        {
            "status": 200,
            "headers": {"Content-Type": "application/json", "Content-Length": "5"},
            "read": lambda _self, _size=-1: b"1234",
            "__enter__": lambda self: self,
            "__exit__": lambda self, *_args: None,
        },
    )()
    handler = object.__new__(eve_app_server.EveAppHandler)
    handler.server = type(
        "Server",
        (),
        {
            "backend_base": "http://127.0.0.1:8797",
            "record_backend_health": lambda _self, value: recorded.append(value),
        },
    )()
    handler._send_json = lambda payload, status=HTTPStatus.OK: sent.append((payload, status))

    with patch.object(eve_app_server.urllib.request, "urlopen", return_value=response):
        handler._proxy("GET", "/api/eve-app/snapshot")

    assert recorded == [False]
    assert sent[-1][1] == HTTPStatus.BAD_GATEWAY
    assert "incomplete response" in str(sent[-1][0])


def test_proxy_transport_failure_records_short_negative_health() -> None:
    recorded: list[bool] = []
    sent: list[tuple[object, int]] = []
    handler = object.__new__(eve_app_server.EveAppHandler)
    handler.server = type(
        "Server",
        (),
        {
            "backend_base": "http://127.0.0.1:8797",
            "record_backend_health": lambda _self, value: recorded.append(value),
        },
    )()
    handler._send_json = lambda payload, status=HTTPStatus.OK: sent.append((payload, status))
    secret = "private backend address and machine path"
    log = io.StringIO()

    with patch.object(
        eve_app_server.urllib.request,
        "urlopen",
        side_effect=urllib.error.URLError(secret),
    ), patch.object(eve_app_server.eve_http_server.sys, "stderr", log):
        handler._proxy("GET", "/api/eve-app/snapshot")

    assert recorded == [False]
    assert sent[-1][1] == HTTPStatus.BAD_GATEWAY
    payload = sent[-1][0]
    assert payload["error"] == "Eve's local runtime is temporarily unavailable."
    assert len(payload["error_id"]) == 16
    assert secret not in str(payload)
    assert secret not in log.getvalue()
    assert payload["error_id"] in log.getvalue()


def test_proxy_does_not_relay_upstream_internal_error_content() -> None:
    recorded: list[bool] = []
    sent: list[tuple[object, int]] = []
    headers = http.client.HTTPMessage()
    headers.add_header("Content-Type", "application/json")
    secret = "private upstream traceback and machine path"
    upstream_error = urllib.error.HTTPError(
        "http://127.0.0.1:8797/api/eve-app/snapshot",
        500,
        "Internal Server Error",
        headers,
        io.BytesIO(json.dumps({"ok": False, "error": secret}).encode("utf-8")),
    )
    handler = object.__new__(eve_app_server.EveAppHandler)
    handler.server = type(
        "Server",
        (),
        {
            "backend_base": "http://127.0.0.1:8797",
            "record_backend_health": lambda _self, value: recorded.append(value),
        },
    )()
    handler._send_json = lambda payload, status=HTTPStatus.OK: sent.append((payload, status))
    log = io.StringIO()

    with patch.object(
        eve_app_server.urllib.request,
        "urlopen",
        side_effect=upstream_error,
    ), patch.object(eve_app_server.eve_http_server.sys, "stderr", log):
        handler._proxy("GET", "/api/eve-app/snapshot")

    assert recorded == [False]
    assert sent[-1][1] == HTTPStatus.BAD_GATEWAY
    payload = sent[-1][0]
    assert payload["error"] == "Eve's local runtime could not complete the request."
    assert len(payload["error_id"]) == 16
    assert secret not in str(payload)
    assert secret not in log.getvalue()


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


def test_spotlight_projection_requires_backend_config_approval_and_is_derived(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("Eve", encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    (tmp_path / "global_workspace.json").write_text(
        json.dumps(
            {
                "active_goals": ["Understand the next useful thing"],
                "workspace_state": {"focus": "A stale fallback focus"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "homeostasis.json").write_text(
        json.dumps({"next_regulation_step": "Reduce uncertainty before acting"}),
        encoding="utf-8",
    )
    (tmp_path / "autonomy_agenda.json").write_text("{}", encoding="utf-8")
    (tmp_path / "action_executions.jsonl").write_text(
        json.dumps(
            {
                "action": "service_health_check",
                "tree_status": "SUCCESS",
                "verification_ok": True,
                "result_ok": True,
                "typed_contract_ok": True,
                "updated_at": "2026-07-20T02:59:51+00:00",
                "summary": "raw operational detail should not cross the app boundary",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    MockEveBackendHandler.seen_monitor = 0
    backend = ThreadingHTTPServer(("127.0.0.1", 0), MockEveBackendHandler)
    start_server(backend)
    server = eve_app_server.EveAppHTTPServer(("127.0.0.1", 0), eve_app_server.EveAppHandler)
    server.static_root = tmp_path
    server.config_path = config_path
    server.runtime_state_dir = tmp_path
    server.backend_base = f"http://127.0.0.1:{backend.server_address[1]}"
    start_server(server)
    base = f"http://127.0.0.1:{server.server_address[1]}"

    try:
        try:
            urllib.request.urlopen(f"{base}/api/eve-chat/spotlight-projection", timeout=2)
            raise AssertionError("an unapproved projection must not be exposed")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
            assert "not approved" in str(json.loads(exc.read())["error"])

        config_path.write_text(
            json.dumps(
                {
                    "spotlight_projection_enabled": True,
                    "spotlight_projection_approval_source": "operator_explicit_upgrade_goal_2026-08-23",
                }
            ),
            encoding="utf-8",
        )
        projection = json.loads(
            urllib.request.urlopen(f"{base}/api/eve-chat/spotlight-projection", timeout=2).read()
        )
        assert projection["schema_id"] == "eve_spotlight_projection.v1"
        assert projection["source_authority"] == "eve_local_backend"
        assert projection["canonical"] is False
        assert projection["approved"] is True
        assert projection["record_count"] == 3
        assert projection["raw_transcripts_included"] is False
        assert projection["canonical_identifiers_included"] is False
        assert all(record["approval"] == "spotlight_approved" for record in projection["records"])
        serialized = json.dumps(projection).lower()
        assert "raw operational detail" not in serialized
        assert MockEveBackendHandler.seen_monitor == 0
    finally:
        server.shutdown()
        backend.shutdown()
        server.server_close()
        backend.server_close()


def test_app_server_blocks_cross_site_and_simple_content_mutations(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("Eve", encoding="utf-8")
    MockEveBackendHandler.seen_payload = {}
    backend = ThreadingHTTPServer(("127.0.0.1", 0), MockEveBackendHandler)
    start_server(backend)
    server = eve_app_server.EveAppHTTPServer(("127.0.0.1", 0), eve_app_server.EveAppHandler)
    server.static_root = tmp_path
    server.backend_base = f"http://127.0.0.1:{backend.server_address[1]}"
    start_server(server)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    body = json.dumps(
        {
            "chat_id": "eve-chat-security",
            "messages": [{"role": "user", "content": "hello"}],
        }
    ).encode("utf-8")

    def rejected(headers: dict[str, str]) -> tuple[int, dict[str, object]]:
        request = urllib.request.Request(
            f"{base}/api/chat",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=2)
            raise AssertionError("unsafe browser mutation should be rejected")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    try:
        status, payload = rejected({"Content-Type": "text/plain"})
        assert status == HTTPStatus.UNSUPPORTED_MEDIA_TYPE
        assert "application/json" in str(payload["error"])

        status, payload = rejected(
            {
                "Content-Type": "application/json",
                "Origin": "https://untrusted.example",
            }
        )
        assert status == HTTPStatus.FORBIDDEN
        assert "local Eve app origin" in str(payload["error"])

        status, _ = rejected(
            {
                "Content-Type": "application/json",
                "Sec-Fetch-Site": "cross-site",
            }
        )
        assert status == HTTPStatus.FORBIDDEN
        assert MockEveBackendHandler.seen_payload == {}

        allowed = urllib.request.Request(
            f"{base}/api/chat",
            data=body,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Origin": base,
                "Sec-Fetch-Site": "same-origin",
            },
            method="POST",
        )
        with urllib.request.urlopen(allowed, timeout=2) as response:
            assert response.status == HTTPStatus.OK
            assert b"hello from eve" in response.read()
        assert MockEveBackendHandler.seen_payload["messages"] == [
            {"role": "user", "content": "hello"}
        ]
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



import unittest


class BoundedQueryEmptyStringTests(unittest.TestCase):
    def test_bounded_query_accepts_an_empty_query_string(self):
        import eve_http_query
        query = eve_http_query.BoundedQuery.parse("")
        self.assertEqual({}, dict(query.values))
        self.assertIsNone(query.value("anything"))
        with self.assertRaises(ValueError):
            eve_http_query.BoundedQuery.parse("a=1&=&b")
