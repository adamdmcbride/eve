"""Bounded HTTP request-body framing shared by Eve's loopback servers.

``BaseHTTPRequestHandler`` does not decode chunked request bodies and leaves
body framing to each handler.  Reading an asserted ``Content-Length`` once is
also insufficient for arbitrary binary streams: a short read can otherwise be
mistaken for a complete request.  This module owns the small transport rule so
the runtime API and Eve.app proxy cannot drift.

The helper deliberately does not parse JSON or authenticate a caller.  It only
validates one unambiguous, bounded Content-Length body and returns the exact
declared bytes.
"""

from __future__ import annotations

from typing import Any, BinaryIO

import eve_http_headers


class RequestBodyError(ValueError):
    """A request body cannot be accepted by Eve's local HTTP contract."""


class RequestBodyFramingError(RequestBodyError):
    """The request body boundary is ambiguous or incomplete."""


class RequestBodyTooLarge(RequestBodyFramingError):
    """The declared request body exceeds the endpoint's byte budget."""


class IncompleteRequestBody(RequestBodyFramingError):
    """The stream ended before the declared request body was complete."""


def declared_request_length(
    headers: Any,
    *,
    maximum_bytes: int,
    allow_empty: bool = False,
) -> int:
    """Validate request framing and return one bounded Content-Length."""

    try:
        limit = int(maximum_bytes)
    except (TypeError, ValueError) as exc:
        raise ValueError("maximum_bytes must be a non-negative integer") from exc
    if limit < 0:
        raise ValueError("maximum_bytes must be a non-negative integer")

    if eve_http_headers.header_values(headers, "Transfer-Encoding"):
        raise RequestBodyFramingError(
            "Transfer-Encoding request bodies are not supported"
        )

    lengths = eve_http_headers.header_values(headers, "Content-Length")
    if not lengths:
        raise RequestBodyFramingError("Content-Length is required")
    if len(lengths) != 1:
        raise RequestBodyFramingError("Multiple Content-Length headers are not allowed")

    raw_length = lengths[0].strip()
    if not raw_length or not raw_length.isascii() or not raw_length.isdigit():
        raise RequestBodyFramingError("Invalid Content-Length")
    # Avoid feeding an attacker-controlled, arbitrarily long decimal string to
    # int(), whose conversion limits vary across supported Python versions.
    if len(raw_length) > 20:
        raise RequestBodyTooLarge(
            f"Request body is too large (limit: {limit} bytes)"
        )
    length = int(raw_length)
    if length > limit:
        raise RequestBodyTooLarge(
            f"Request body is too large (limit: {limit} bytes)"
        )
    if length == 0 and not allow_empty:
        raise RequestBodyError("Request body is empty")
    return length


def read_bounded_request_body(
    stream: BinaryIO,
    headers: Any,
    *,
    maximum_bytes: int,
    allow_empty: bool = False,
) -> bytes:
    """Read exactly one validated Content-Length body within ``maximum_bytes``."""

    length = declared_request_length(
        headers,
        maximum_bytes=maximum_bytes,
        allow_empty=allow_empty,
    )
    if length == 0:
        return b""

    try:
        first = stream.read(length)
    except OSError as exc:
        raise IncompleteRequestBody("Request body could not be read completely") from exc
    if not isinstance(first, (bytes, bytearray, memoryview)):
        raise RequestBodyFramingError("Request body stream returned non-bytes data")
    first_bytes = bytes(first)
    if len(first_bytes) > length:
        raise RequestBodyFramingError("Request body stream exceeded Content-Length")
    if len(first_bytes) == length:
        return first_bytes

    chunks = [first_bytes]
    received = len(first_bytes)
    while received < length:
        try:
            chunk = stream.read(length - received)
        except OSError as exc:
            raise IncompleteRequestBody("Request body could not be read completely") from exc
        if not isinstance(chunk, (bytes, bytearray, memoryview)):
            raise RequestBodyFramingError("Request body stream returned non-bytes data")
        chunk_bytes = bytes(chunk)
        if not chunk_bytes:
            raise IncompleteRequestBody(
                f"Request body ended after {received} of {length} declared bytes"
            )
        if len(chunk_bytes) > length - received:
            raise RequestBodyFramingError("Request body stream exceeded Content-Length")
        chunks.append(chunk_bytes)
        received += len(chunk_bytes)
    return b"".join(chunks)
