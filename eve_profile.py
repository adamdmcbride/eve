#!/usr/bin/env python3
"""Portable local-user and service-namespace configuration for Eve.

Source code should describe a product, not the machine or person on which it
was first developed. Local names are discovered or configured at runtime and
never become canonical identity or authority.
"""

from __future__ import annotations

import argparse
import getpass
import os
import plistlib
import re
from pathlib import Path
from typing import Optional

import eve_platform


DEFAULT_USER_DISPLAY_NAME = "User"
DEFAULT_SERVICE_NAMESPACE = "local.eve"
_NAMESPACE_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?$")
_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


def _clean_display_name(value: object) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text or any(character in text for character in "\r\n\t"):
        return ""
    return text[:120]


def user_display_name() -> str:
    """Return a local display name without encoding one in source.

    ``EVE_USER_NAME`` is authoritative. Otherwise the account name is used as
    a convenience only; callers that do not need a name should say "the user"
    or "you" instead.
    """

    configured = _clean_display_name(os.environ.get("EVE_USER_NAME"))
    if configured:
        return configured
    try:
        account = _clean_display_name(getpass.getuser())
    except (OSError, KeyError):
        account = ""
    return account or DEFAULT_USER_DISPLAY_NAME


def user_slug() -> str:
    slug = _SLUG_PATTERN.sub("-", user_display_name().lower()).strip("-")
    return slug or "user"


def _valid_namespace(value: object) -> str:
    text = str(value or "").strip()
    if not text or not _NAMESPACE_PATTERN.fullmatch(text):
        return ""
    return text


def _installed_daemon_namespace(service_dir: Optional[Path] = None) -> str:
    """Discover an existing launchd daemon label for in-place migrations.

    Fresh installations receive the generic namespace. Existing installations
    keep working until their generated service definitions are explicitly
    migrated. Only a plist whose command invokes Eve's daemon is considered.
    """

    if not eve_platform.is_macos():
        return ""
    directory = service_dir or eve_platform.service_definition_dir()
    try:
        candidates = sorted(directory.glob("*.plist"))
    except OSError:
        return ""
    for candidate in candidates:
        try:
            with candidate.open("rb") as handle:
                payload = plistlib.load(handle)
        except (OSError, plistlib.InvalidFileException, ValueError):
            continue
        label = _valid_namespace(payload.get("Label")) if isinstance(payload, dict) else ""
        arguments = payload.get("ProgramArguments") if isinstance(payload, dict) else None
        if not label or not isinstance(arguments, list):
            continue
        rendered = " ".join(str(item) for item in arguments).lower()
        if "eve.py" not in rendered or "daemon" not in rendered:
            continue
        return label
    return ""


def service_namespace(*, service_dir: Optional[Path] = None, discover_installed: bool = True) -> str:
    configured = _valid_namespace(os.environ.get("EVE_SERVICE_NAMESPACE"))
    if configured:
        return configured
    if discover_installed:
        installed = _installed_daemon_namespace(service_dir)
        if installed:
            return installed
    return DEFAULT_SERVICE_NAMESPACE


def service_label(suffix: str = "", *, namespace: Optional[str] = None) -> str:
    base = _valid_namespace(namespace) if namespace is not None else service_namespace()
    base = base or DEFAULT_SERVICE_NAMESPACE
    suffix = str(suffix or "").strip()
    if suffix and not suffix.startswith(("-", ".")):
        suffix = "-" + suffix
    candidate = base + suffix
    if not _NAMESPACE_PATTERN.fullmatch(candidate):
        raise ValueError("invalid Eve service label")
    return candidate


def app_bundle_identifier(component: str, version: str = "") -> str:
    component_slug = _SLUG_PATTERN.sub("-", str(component or "app").lower()).strip("-") or "app"
    version_slug = _SLUG_PATTERN.sub("-", str(version or "").lower()).strip("-")
    suffix = "." + component_slug
    if version_slug:
        suffix += "." + version_slug
    return service_label(suffix, namespace=DEFAULT_SERVICE_NAMESPACE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    namespace_parser = subparsers.add_parser("namespace", help="Print the local service namespace.")
    namespace_parser.add_argument("--fresh", action="store_true", help="Ignore installed service definitions.")
    label_parser = subparsers.add_parser("label", help="Print a service label.")
    label_parser.add_argument("suffix", nargs="?", default="")
    subparsers.add_parser("user-name", help="Print the configured local display name.")
    args = parser.parse_args()
    if args.command == "namespace":
        print(service_namespace(discover_installed=not args.fresh))
    elif args.command == "label":
        print(service_label(args.suffix))
    else:
        print(user_display_name())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
