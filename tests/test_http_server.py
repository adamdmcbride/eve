from __future__ import annotations

import io
import json
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import eve_http_server


class NoopHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        return


class FakeConnection:
    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def settimeout(self, timeout: float) -> None:
        self.timeouts.append(timeout)


class BoundedHTTPServerTests(unittest.TestCase):
    def create_server(self, maximum: int = 1):
        return eve_http_server.EveBoundedThreadingHTTPServer(
            ("127.0.0.1", 0),
            NoopHandler,
            bind_and_activate=False,
            max_active_requests=maximum,
        )

    def test_server_declares_finite_queue_and_daemon_worker_policy(self):
        server = self.create_server(maximum=3)
        try:
            self.assertEqual(3, server.max_active_requests)
            self.assertEqual(0, server.active_request_count)
            self.assertEqual(0, server.rejected_request_count)
            self.assertEqual(32, server.request_queue_size)
            self.assertTrue(server.daemon_threads)
        finally:
            server.server_close()

    def test_internal_error_log_is_correlatable_but_content_free(self):
        stream = io.StringIO()

        error_id = eve_http_server.record_http_internal_error(
            RuntimeError("private path and conversation must not be logged"),
            surface="eve runtime\nunsafe",
            operation="GET /api/private?query=secret",
            stream=stream,
        )
        event = json.loads(stream.getvalue())

        self.assertEqual(error_id, event["error_id"])
        self.assertRegex(error_id, r"^[0-9a-f]{16}$")
        self.assertEqual("eve_http_internal_error", event["event"])
        self.assertEqual("RuntimeError", event["exception_type"])
        self.assertNotIn("private path", stream.getvalue())
        self.assertNotIn("conversation", stream.getvalue())
        self.assertNotIn("query=secret", stream.getvalue())
        self.assertNotIn("\nunsafe", stream.getvalue())

    def test_unhandled_request_error_replaces_stdlib_traceback_with_safe_record(self):
        server = self.create_server()
        stream = io.StringIO()
        secret = "private traceback payload and local machine path"
        try:
            with patch.object(eve_http_server.sys, "stderr", stream):
                try:
                    raise RuntimeError(secret)
                except RuntimeError:
                    server.handle_error(object(), ("127.0.0.1", 12345))

            event = json.loads(stream.getvalue())
            self.assertEqual("unhandled_request", event["operation"])
            self.assertEqual("eve-local-server", event["surface"])
            self.assertEqual("RuntimeError", event["exception_type"])
            self.assertNotIn(secret, stream.getvalue())
            self.assertNotIn("Traceback", stream.getvalue())
            self.assertNotIn("127.0.0.1", stream.getvalue())
        finally:
            server.server_close()

    def test_request_admission_closes_excess_without_starting_a_thread(self):
        server = self.create_server()
        closed: list[object] = []
        server.shutdown_request = lambda request: closed.append(request)  # type: ignore[method-assign]
        first = object()
        excess = object()
        address = ("127.0.0.1", 12345)
        try:
            with patch.object(
                ThreadingHTTPServer,
                "process_request",
                return_value=None,
            ) as parent_process:
                server.process_request(first, address)
                server.process_request(excess, address)

            self.assertEqual(1, parent_process.call_count)
            self.assertEqual([excess], closed)
            self.assertEqual(1, server.active_request_count)
            self.assertEqual(1, server.rejected_request_count)

            with patch.object(
                ThreadingHTTPServer,
                "process_request_thread",
                return_value=None,
            ):
                server.process_request_thread(first, address)

            self.assertEqual(0, server.active_request_count)
        finally:
            server.server_close()

    def test_failed_thread_start_releases_its_admission_slot(self):
        server = self.create_server()
        try:
            with patch.object(
                ThreadingHTTPServer,
                "process_request",
                side_effect=RuntimeError("thread start failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "thread start failed"):
                    server.process_request(object(), ("127.0.0.1", 12345))

            self.assertEqual(0, server.active_request_count)
            self.assertEqual(0, server.rejected_request_count)
        finally:
            server.server_close()

    def test_worker_limit_must_be_positive(self):
        for value in (0, -1, "invalid"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "positive integer"):
                    self.create_server(maximum=value)  # type: ignore[arg-type]

    def test_handler_applies_finite_client_io_idle_timeout(self):
        handler = object.__new__(eve_http_server.EveBoundedHTTPRequestHandler)
        connection = FakeConnection()
        handler.connection = connection  # type: ignore[assignment]

        with patch.object(BaseHTTPRequestHandler, "setup", autospec=True) as parent_setup:
            handler.setup()

        parent_setup.assert_called_once_with(handler)
        self.assertEqual(
            [eve_http_server.DEFAULT_REQUEST_IDLE_TIMEOUT_SECONDS],
            connection.timeouts,
        )

    def test_private_and_document_headers_are_centralized(self):
        handler = object.__new__(eve_http_server.EveBoundedHTTPRequestHandler)
        sent: list[tuple[str, str]] = []
        handler.send_header = lambda name, value: sent.append((name, value))  # type: ignore[method-assign]

        handler.send_eve_private_response_headers()
        self.assertEqual(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            },
            dict(sent),
        )

        sent.clear()
        handler.send_eve_document_security_headers(allow_sensory=False)
        headers = dict(sent)
        self.assertEqual("same-origin", headers["Cross-Origin-Resource-Policy"])
        self.assertEqual("DENY", headers["X-Frame-Options"])
        self.assertEqual(
            "camera=(), geolocation=(), microphone=()",
            headers["Permissions-Policy"],
        )
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertIn("base-uri 'none'", headers["Content-Security-Policy"])

        sent.clear()
        handler.send_eve_document_security_headers(allow_sensory=True)
        self.assertEqual(
            "camera=(self), geolocation=(), microphone=(self)",
            dict(sent)["Permissions-Policy"],
        )

    def test_server_header_does_not_disclose_python_version(self):
        handler = object.__new__(eve_http_server.EveBoundedHTTPRequestHandler)

        self.assertEqual("EveLocal", handler.version_string())
        self.assertNotIn("Python", handler.version_string())


if __name__ == "__main__":
    unittest.main()
