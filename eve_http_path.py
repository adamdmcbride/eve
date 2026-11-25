"""Bounded, exact path routing primitives for Eve's local HTTP surfaces.

Dynamic resource identifiers are opaque data, not route syntax.  The runtime
API and Eve.app proxy use this module to agree on one path budget, one strict
percent-decoding rule, and exact one-segment route templates.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from urllib.parse import quote, unquote_to_bytes, urlsplit


DEFAULT_MAX_PATH_CHARACTERS = 4096
DEFAULT_MAX_ROUTE_SEGMENT_CHARACTERS = 512
DEFAULT_MAX_REQUEST_TARGET_CHARACTERS = 12_289
_HEX_DIGITS = frozenset(string.hexdigits)


@dataclass(frozen=True)
class HTTPRequestTarget:
    path: str
    query: str


def _strict_percent_decoded_text(value: str, *, label: str) -> str:
    index = 0
    while index < len(value):
        if value[index] != "%":
            index += 1
            continue
        if (
            index + 2 >= len(value)
            or value[index + 1] not in _HEX_DIGITS
            or value[index + 2] not in _HEX_DIGITS
        ):
            raise ValueError(f"{label} contains invalid percent encoding")
        index += 3
    try:
        return unquote_to_bytes(value).decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} must use valid UTF-8") from exc


def require_request_path(
    path: object,
    *,
    maximum_characters: int = DEFAULT_MAX_PATH_CHARACTERS,
) -> str:
    """Return one bounded ASCII request path or raise a client-safe error."""

    if isinstance(maximum_characters, bool) or not isinstance(maximum_characters, int):
        raise TypeError("maximum_characters must be an integer")
    if maximum_characters <= 0:
        raise ValueError("maximum_characters must be positive")
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("Request path must begin with /")
    if len(path) > maximum_characters:
        raise ValueError("Request path is too long")
    if not path.isascii() or any(ord(character) < 0x21 or ord(character) > 0x7E for character in path):
        raise ValueError("Request path must use printable ASCII or percent encoding")

    decoded = _strict_percent_decoded_text(path, label="Request path")
    if any(not character.isprintable() for character in decoded):
        raise ValueError("Request path contains a control character")
    return path


def parse_request_target(
    target: object,
    *,
    maximum_characters: int = DEFAULT_MAX_REQUEST_TARGET_CHARACTERS,
) -> HTTPRequestTarget:
    """Parse one bounded HTTP origin-form target without accepting proxy form."""

    if isinstance(maximum_characters, bool) or not isinstance(maximum_characters, int):
        raise TypeError("maximum_characters must be an integer")
    if maximum_characters <= 0:
        raise ValueError("maximum_characters must be positive")
    if not isinstance(target, str) or not target:
        raise ValueError("Request target is required")
    if len(target) > maximum_characters:
        raise ValueError("Request target is too long")
    if not target.isascii() or any(
        ord(character) < 0x21 or ord(character) > 0x7E for character in target
    ):
        raise ValueError("Request target must use printable ASCII or percent encoding")
    try:
        parsed = urlsplit(target)
    except ValueError as exc:
        raise ValueError("Request target is invalid") from exc
    if parsed.scheme or parsed.netloc or parsed.fragment:
        raise ValueError("Request target must use origin form")
    path = require_request_path(parsed.path)
    return HTTPRequestTarget(path=path, query=parsed.query)


def require_route_segment(
    value: object,
    *,
    label: str = "Resource id",
    maximum_characters: int = DEFAULT_MAX_ROUTE_SEGMENT_CHARACTERS,
) -> str:
    """Validate one decoded opaque route identifier without changing it."""

    if isinstance(maximum_characters, bool) or not isinstance(maximum_characters, int):
        raise TypeError("maximum_characters must be an integer")
    if maximum_characters <= 0:
        raise ValueError("maximum_characters must be positive")
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} is required")
    if len(value) > maximum_characters:
        raise ValueError(f"{label} is too long")
    if value != value.strip() or any(not character.isprintable() for character in value):
        raise ValueError(f"{label} must be printable without surrounding whitespace")
    if value in {".", ".."}:
        raise ValueError(f"{label} cannot be a dot segment")
    return value


def encode_route_segment(
    value: object,
    *,
    label: str = "Resource id",
    maximum_characters: int = DEFAULT_MAX_ROUTE_SEGMENT_CHARACTERS,
) -> str:
    """Encode one validated opaque identifier as a canonical URL segment."""

    normalized = require_route_segment(
        value,
        label=label,
        maximum_characters=maximum_characters,
    )
    return quote(normalized, safe="-._~", encoding="utf-8", errors="strict")


def match_route_segment(
    path: object,
    *,
    prefix: str,
    suffix: str = "",
    label: str = "Resource id",
    maximum_characters: int = DEFAULT_MAX_ROUTE_SEGMENT_CHARACTERS,
) -> str | None:
    """Decode an exact one-segment route, or return ``None`` if it is another route.

    Extra raw slash-delimited segments are structural mismatches rather than a
    partial match. A percent-encoded slash remains part of the opaque decoded
    identifier and therefore never changes dispatch structure.
    """

    normalized_path = require_request_path(path)
    if not prefix.startswith("/") or not prefix.endswith("/"):
        raise ValueError("Route prefix must begin and end with /")
    if suffix and not suffix.startswith("/"):
        raise ValueError("Route suffix must begin with /")
    if not normalized_path.startswith(prefix):
        return None

    encoded = normalized_path[len(prefix) :]
    if suffix:
        if not encoded.endswith(suffix):
            return None
        encoded = encoded[: -len(suffix)]
    if not encoded or "/" in encoded:
        return None

    decoded = _strict_percent_decoded_text(encoded, label=label)
    return require_route_segment(
        decoded,
        label=label,
        maximum_characters=maximum_characters,
    )


def build_route_path(
    *,
    prefix: str,
    segment: object,
    suffix: str = "",
    label: str = "Resource id",
    maximum_characters: int = DEFAULT_MAX_ROUTE_SEGMENT_CHARACTERS,
) -> str:
    """Build and revalidate the canonical representation of a dynamic route."""

    if not prefix.startswith("/") or not prefix.endswith("/"):
        raise ValueError("Route prefix must begin and end with /")
    if suffix and not suffix.startswith("/"):
        raise ValueError("Route suffix must begin with /")
    encoded = encode_route_segment(
        segment,
        label=label,
        maximum_characters=maximum_characters,
    )
    return require_request_path(f"{prefix}{encoded}{suffix}")
