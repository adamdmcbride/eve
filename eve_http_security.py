"""Pure request-origin policy for Eve's local JSON mutation surfaces.

Loopback binding is not a CSRF defense: a browser on the same Mac can submit a
cross-site form or a CORS-safelisted ``text/plain`` request to a local port.
This module keeps the small browser boundary shared by the runtime API and the
canonical Eve.app proxy without importing either server.

The policy is intentionally not authentication.  Native clients and local CLI
tools may omit browser-only Origin and Fetch Metadata headers, so no-Origin
JSON requests remain compatible.  A hostile local process therefore remains a
host-security concern rather than something this browser-focused gate claims
to solve.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Iterable, FrozenSet
from urllib.parse import urlsplit

import eve_http_headers


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_DNS_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")


@dataclass(frozen=True)
class MutationRequestDecision:
    allowed: bool
    status: int
    reason: str
    message: str


def canonical_advertised_host(value: object) -> str:
    """Return a shell-safe DNS name or canonical IPv4 address.

    Installer and update artifacts interpolate this value into URLs and local
    scripts.  Keep that contract narrower than the full URI host grammar:
    Unicode/IDNA and IPv6 require explicit serialization support in every
    generated platform script and are rejected until that support exists.
    """

    if not isinstance(value, str) or not value or value != value.strip():
        return ""
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        return ""
    if len(value) > 253:
        return ""

    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        address = None
    if address is not None:
        if not isinstance(address, ipaddress.IPv4Address) or address.is_unspecified:
            return ""
        return str(address)

    # Do not let dotted numeric lookalikes fall through as DNS labels. Some
    # clients interpret legacy numeric spellings as IP addresses differently.
    if all(character.isdigit() or character == "." for character in value):
        return ""
    labels = value.split(".")
    if not labels or any(not _DNS_LABEL.fullmatch(label) for label in labels):
        return ""
    return value.lower()


def require_advertised_host(value: object, *, label: str = "host") -> str:
    """Validate one endpoint host before it enters generated artifacts."""

    canonical = canonical_advertised_host(value)
    if not canonical:
        raise ValueError(
            f"{label} must be an ASCII DNS name or IPv4 address, not a wildcard or IPv6 literal"
        )
    return canonical


def require_network_port(value: object, *, label: str = "port") -> int:
    """Return one strict decimal TCP port without permissive ``int`` coercion."""

    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer from 1 through 65535")
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, str):
        text = value
    else:
        raise ValueError(f"{label} must be an integer from 1 through 65535")
    if not text or len(text) > 5 or any(character < "0" or character > "9" for character in text):
        raise ValueError(f"{label} must be an integer from 1 through 65535")
    port = int(text)
    if not 1 <= port <= 65_535:
        raise ValueError(f"{label} must be an integer from 1 through 65535")
    return port


def advertised_host_for_bind(bound_host: object, explicit_host: object = None) -> str:
    """Resolve the server-owned endpoint host without reading a request header."""

    if explicit_host is not None:
        return require_advertised_host(explicit_host, label="advertised_host")
    return canonical_advertised_host(bound_host) or "localhost"


def http_authority(host: object, port: object) -> str:
    """Serialize the deliberately DNS/IPv4-only advertised endpoint."""

    return (
        f"{require_advertised_host(host, label='host')}:"
        f"{require_network_port(port, label='port')}"
    )


def _serialized_http_origin(host: str, port: int) -> str:
    authority = f"[{host}]" if ":" in host else host
    return f"http://{authority}" if port == 80 else f"http://{authority}:{port}"


def canonical_loopback_origin(value: object) -> str:
    """Return one canonical HTTP loopback origin, or an empty string."""

    try:
        raw = eve_http_headers.require_ascii_field_value(
            value,
            label="Origin",
            maximum_characters=512,
        )
    except eve_http_headers.RequestHeaderError:
        return ""
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
        port = parsed.port or 80
    except ValueError:
        return ""
    host = str(parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() != "http"
        or host not in LOOPBACK_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("",)
        or parsed.query
        or parsed.fragment
        or not (1 <= port <= 65_535)
    ):
        return ""
    return _serialized_http_origin(host, port)


def loopback_origins_for_port(port: int) -> FrozenSet[str]:
    try:
        normalized_port = int(port)
    except (TypeError, ValueError):
        return frozenset()
    if not (1 <= normalized_port <= 65_535):
        return frozenset()
    return frozenset(
        _serialized_http_origin(host, normalized_port)
        for host in sorted(LOOPBACK_HOSTS)
    )


def trusted_mutation_origins(
    server_port: int,
    extra_origins: Iterable[str] = (),
) -> FrozenSet[str]:
    origins = set(loopback_origins_for_port(server_port))
    for value in extra_origins:
        canonical = canonical_loopback_origin(value)
        if not canonical:
            raise ValueError("trusted mutation origins must be canonical HTTP loopback origins")
        origins.add(canonical)
    return frozenset(origins)


def is_json_media_type(value: object) -> bool:
    media_type = str(value or "").split(";", 1)[0].strip().lower()
    return media_type == "application/json" or (
        media_type.startswith("application/") and media_type.endswith("+json")
    )


def evaluate_json_mutation_request(
    *,
    origin: object,
    sec_fetch_site: object,
    content_type: object,
    server_port: int,
    extra_origins: Iterable[str] = (),
) -> MutationRequestDecision:
    """Evaluate the browser-CSRF boundary for one state-changing JSON POST."""

    try:
        normalized_origin = eve_http_headers.require_ascii_field_value(
            origin,
            label="Origin",
            maximum_characters=512,
        )
        fetch_site = eve_http_headers.require_ascii_field_value(
            sec_fetch_site,
            label="Sec-Fetch-Site",
            maximum_characters=32,
        ).lower()
        normalized_content_type = eve_http_headers.require_ascii_field_value(
            content_type,
            label="Content-Type",
            maximum_characters=256,
        )
    except eve_http_headers.RequestHeaderError:
        return MutationRequestDecision(
            allowed=False,
            status=400,
            reason="invalid_request_header",
            message="A consumed request header is invalid.",
        )

    if fetch_site == "cross-site":
        return MutationRequestDecision(
            allowed=False,
            status=403,
            reason="cross_site_fetch",
            message="Cross-site browser requests cannot change Eve's local state.",
        )

    if normalized_origin:
        canonical = canonical_loopback_origin(normalized_origin)
        if not canonical or canonical not in trusted_mutation_origins(server_port, extra_origins):
            return MutationRequestDecision(
                allowed=False,
                status=403,
                reason="untrusted_origin",
                message=(
                    "This browser origin is not a trusted local Eve app origin and "
                    "cannot change Eve's local state."
                ),
            )

    if not is_json_media_type(normalized_content_type):
        return MutationRequestDecision(
            allowed=False,
            status=415,
            reason="json_content_type_required",
            message="Eve's local mutation API requires Content-Type: application/json.",
        )

    return MutationRequestDecision(
        allowed=True,
        status=200,
        reason="allowed",
        message="",
    )
