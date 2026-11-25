"""Bounded stdlib HTTP server primitives for Eve's loopback interfaces.

Python's ``ThreadingHTTPServer`` creates a new thread for every accepted
connection.  That behavior is convenient for browsers that pre-open sockets,
but it is not a resource budget.  Eve's local runtime API and app proxy share
this bounded admission layer so a stalled or buggy local client cannot create
an unlimited number of request threads.

This remains a small loopback transport, not a claim that ``http.server`` is a
general production web stack or an authentication boundary.
"""

from __future__ import annotations

import json
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, TextIO


DEFAULT_MAX_ACTIVE_REQUESTS = 32
DEFAULT_REQUEST_QUEUE_SIZE = 32
DEFAULT_REQUEST_IDLE_TIMEOUT_SECONDS = 30.0
EVE_DOCUMENT_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; connect-src 'self'; img-src 'self' data: blob:; "
    "style-src 'self'; script-src 'self'; media-src 'self' blob:; "
    "frame-src 'none'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
)


def _safe_log_token(value: object, *, fallback: str) -> str:
    token = str(value or "")
    if not 1 <= len(token) <= 64 or any(
        not character.isascii() or not (character.isalnum() or character in "._-")
        for character in token
    ):
        return fallback
    return token


def record_http_internal_error(
    error: BaseException,
    *,
    surface: object,
    operation: object,
    stream: TextIO | None = None,
) -> str:
    """Write content-free correlation metadata and return its opaque ID."""

    error_id = secrets.token_hex(8)
    event = {
        "event": "eve_http_internal_error",
        "error_id": error_id,
        "surface": _safe_log_token(surface, fallback="eve-local"),
        "operation": _safe_log_token(operation, fallback="request"),
        "exception_type": _safe_log_token(type(error).__name__, fallback="Exception"),
    }
    destination = stream if stream is not None else sys.stderr
    destination.write(json.dumps(event, ensure_ascii=True, sort_keys=True) + "\n")
    destination.flush()
    return error_id


class EveBoundedThreadingHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer with explicit concurrent-request admission."""

    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = DEFAULT_REQUEST_QUEUE_SIZE
    internal_error_surface = "eve-local-server"

    def __init__(
        self,
        *args: Any,
        max_active_requests: int = DEFAULT_MAX_ACTIVE_REQUESTS,
        **kwargs: Any,
    ) -> None:
        try:
            normalized_limit = int(max_active_requests)
        except (TypeError, ValueError) as exc:
            raise ValueError("max_active_requests must be a positive integer") from exc
        if normalized_limit <= 0:
            raise ValueError("max_active_requests must be a positive integer")

        self._max_active_requests = normalized_limit
        self._request_slots = threading.BoundedSemaphore(normalized_limit)
        self._request_count_lock = threading.Lock()
        self._active_request_count = 0
        self._rejected_request_count = 0
        super().__init__(*args, **kwargs)

    @property
    def max_active_requests(self) -> int:
        return self._max_active_requests

    @property
    def active_request_count(self) -> int:
        with self._request_count_lock:
            return self._active_request_count

    @property
    def rejected_request_count(self) -> int:
        with self._request_count_lock:
            return self._rejected_request_count

    def _acquire_request_slot(self) -> bool:
        admitted = self._request_slots.acquire(blocking=False)
        with self._request_count_lock:
            if admitted:
                self._active_request_count += 1
            else:
                self._rejected_request_count += 1
        return admitted

    def _release_request_slot(self) -> None:
        with self._request_count_lock:
            self._active_request_count -= 1
            if self._active_request_count < 0:
                self._active_request_count = 0
                raise RuntimeError("request admission accounting underflow")
        self._request_slots.release()

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._acquire_request_slot():
            # The request has not been parsed, so there is no safe HTTP response
            # to construct. Close it immediately instead of allocating a thread.
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._release_request_slot()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._release_request_slot()

    def handle_error(self, request: Any, client_address: Any) -> None:
        """Do not print tracebacks, request data, or machine paths to service logs."""

        error = sys.exc_info()[1]
        if isinstance(error, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return
        record_http_internal_error(
            error if isinstance(error, BaseException) else RuntimeError("unknown server error"),
            surface=self.internal_error_surface,
            operation="unhandled_request",
        )


class EveBoundedHTTPRequestHandler(BaseHTTPRequestHandler):
    """Base handler with a finite idle timeout for client socket I/O."""

    server_version = "EveLocal"
    sys_version = ""
    request_idle_timeout_seconds = DEFAULT_REQUEST_IDLE_TIMEOUT_SECONDS

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(float(self.request_idle_timeout_seconds))

    def version_string(self) -> str:
        """Do not disclose the host Python version in every HTTP response."""

        return self.server_version

    def send_eve_private_response_headers(self) -> None:
        """Mark local state/content as non-cacheable and non-sniffable."""

        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")

    def send_eve_document_security_headers(self, *, allow_sensory: bool) -> None:
        """Apply the shared security policy for Eve-owned static documents."""

        self.send_eve_private_response_headers()
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Permissions-Policy",
            (
                "camera=(self), geolocation=(), microphone=(self)"
                if allow_sensory
                else "camera=(), geolocation=(), microphone=()"
            ),
        )
        self.send_header(
            "Content-Security-Policy",
            EVE_DOCUMENT_CONTENT_SECURITY_POLICY,
        )
