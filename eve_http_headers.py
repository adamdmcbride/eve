"""Duplicate-aware, bounded header primitives for Eve's local HTTP surfaces.

``BaseHTTPRequestHandler`` limits the total parser shape, but consumers still
need one explicit contract for the individual fields that influence routing,
browser policy, or durable correlation metadata.  This module rejects
ambiguous duplicates, oversized values, non-ASCII bytes, and control
characters before those values cross into Eve's application state.
"""

from __future__ import annotations

import re
from typing import Any


DEFAULT_MAX_HEADER_CHARACTERS = 1024
_HEADER_NAME = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+\Z")


class RequestHeaderError(ValueError):
    """A consumed request header is ambiguous or outside Eve's budget."""


def _require_positive_limit(maximum_characters: object) -> int:
    if isinstance(maximum_characters, bool) or not isinstance(maximum_characters, int):
        raise TypeError("maximum_characters must be an integer")
    if maximum_characters <= 0:
        raise ValueError("maximum_characters must be positive")
    return maximum_characters


def _require_header_name(name: object) -> str:
    if not isinstance(name, str) or not _HEADER_NAME.fullmatch(name):
        raise ValueError("header name must be one ASCII HTTP token")
    return name


def header_values(headers: Any, name: str) -> list[str]:
    """Return every value for one header without collapsing duplicates."""

    normalized_name = _require_header_name(name)
    get_all = getattr(headers, "get_all", None)
    if callable(get_all):
        values = get_all(normalized_name) or []
        return [str(value) for value in values]

    items = getattr(headers, "items", None)
    if callable(items):
        target = normalized_name.casefold()
        return [
            str(value)
            for key, value in items()
            if str(key).casefold() == target
        ]

    get = getattr(headers, "get", None)
    if callable(get):
        value = get(normalized_name)
        return [] if value is None else [str(value)]
    return []


def require_ascii_field_value(
    value: object,
    *,
    label: str,
    maximum_characters: int = DEFAULT_MAX_HEADER_CHARACTERS,
    allow_empty: bool = True,
) -> str:
    """Normalize one bounded ASCII field value after optional HTTP whitespace."""

    limit = _require_positive_limit(maximum_characters)
    if not isinstance(label, str) or not label:
        raise ValueError("label is required")
    if value is None:
        raw = ""
    elif isinstance(value, str):
        raw = value
    else:
        raise RequestHeaderError(f"{label} must be text")
    if len(raw) > limit:
        raise RequestHeaderError(f"{label} is too long")
    normalized = raw.strip(" \t")
    if not normalized:
        if allow_empty:
            return ""
        raise RequestHeaderError(f"{label} is required")
    if not normalized.isascii() or any(
        ord(character) < 0x20 or ord(character) > 0x7E
        for character in normalized
    ):
        raise RequestHeaderError(f"{label} must use printable ASCII")
    return normalized


def optional_ascii_header(
    headers: Any,
    name: str,
    *,
    maximum_characters: int = DEFAULT_MAX_HEADER_CHARACTERS,
    allow_empty: bool = True,
) -> str:
    """Read at most one bounded ASCII request-header value."""

    _require_positive_limit(maximum_characters)
    values = header_values(headers, name)
    if len(values) > 1:
        raise RequestHeaderError(f"Multiple {name} headers are not allowed")
    if not values:
        return ""
    return require_ascii_field_value(
        values[0],
        label=name,
        maximum_characters=maximum_characters,
        allow_empty=allow_empty,
    )
