#!/usr/bin/env python3
"""Audit and export a deterministic public Eve source tree.

The live Eve checkout contains runtime state, personal continuity material, and
operational evidence that must never be made public by accident.  This tool is
read-only unless ``--write-manifest`` or ``--export`` is explicitly supplied.
It never rewrites or sanitizes source: a release must pass as written.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple


SECRET_RULES: Tuple[Tuple[str, re.Pattern[bytes]], ...] = (
    ("private_key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("github_token", re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("openai_key", re.compile(rb"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b")),
    ("anthropic_key", re.compile(rb"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("aws_access_key", re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("google_api_key", re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("slack_token", re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("huggingface_token", re.compile(rb"\bhf_[A-Za-z0-9]{30,}\b")),
    ("credential_url", re.compile(rb"https?://[^\s/:@]{2,}:[^\s/@]{2,}@")),
)

GENERIC_LITERAL_CREDENTIAL = re.compile(
    rb"(?ix)\b(?:api[_-]?key|client[_-]?secret|password|access[_-]?token|auth[_-]?token)"
    rb"\b\s*[:=]\s*[\"'][^\"'\n${}<]{8,}[\"']"
)
ABSOLUTE_MAC_HOME = re.compile(rb"/Users/([A-Za-z0-9._-]+)/")
EMAIL_ADDRESS = re.compile(
    rb"\b(?!git@(?:github\.com|gitlab\.com|bitbucket\.org)\b)"
    rb"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)
PRIVATE_CONVERSATION_LINK = re.compile(rb"https://claude\.ai/share/", re.IGNORECASE)
MANIFEST_SCHEMA_VERSION = 2
MANIFEST_MAX_BYTES = 16 * 1024 * 1024
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def _is_dataless(info: os.stat_result) -> bool:
    # macOS SF_DATALESS is absent from some supported Python stat modules.
    return bool(getattr(info, "st_flags", 0) & 0x40000000)


def _require_local(info: os.stat_result, path: str) -> None:
    if _is_dataless(info):
        raise ValueError("source not local (dataless placeholder): " + path)


def normalize_rel_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    return normalized


def matches_pattern(path: str, pattern: str) -> bool:
    path = normalize_rel_path(path)
    pattern = normalize_rel_path(pattern)
    if pattern.endswith("/**"):
        prefix = pattern[:-3].rstrip("/")
        return path == prefix or path.startswith(prefix + "/")
    return fnmatch.fnmatchcase(path, pattern)


def matches_any(path: str, patterns: Sequence[str]) -> bool:
    return any(matches_pattern(path, pattern) for pattern in patterns)


def load_config(path: Path) -> Dict[str, Any]:
    try:
        _require_local(path.stat(), path.name)
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("unable to read public release config %s: %s" % (path, exc)) from exc
    if config.get("schema_version") != 1:
        raise ValueError("public release config schema_version must be 1")
    for key in (
        "required_files",
        "include",
        "force_include",
        "exclude",
        "tracked_private_patterns",
        "portable_source_patterns",
        "behavior_patterns",
        "behavior_owner_names",
        "owner_sensitive_patterns",
        "owner_identity_allowed_patterns",
        "owner_identifiers",
        "supported_installers",
        "forbidden_declared_dependencies",
    ):
        if not isinstance(config.get(key), list) or not all(isinstance(item, str) for item in config[key]):
            raise ValueError("public release config %s must be a list of strings" % key)
    exemptions = config.get("owner_identifier_exemptions")
    if not isinstance(exemptions, dict):
        raise ValueError("public release config owner_identifier_exemptions must be an object")
    for relative_path, patterns in exemptions.items():
        if not isinstance(relative_path, str) or not isinstance(patterns, list) or not all(
            isinstance(item, str) for item in patterns
        ):
            raise ValueError(
                "public release config owner_identifier_exemptions must map paths to lists of regex strings"
            )
        for pattern in patterns:
            try:
                re.compile(pattern.encode("utf-8"), re.IGNORECASE)
            except re.error as exc:
                raise ValueError(
                    "invalid owner identifier exemption for %s: %s" % (relative_path, exc)
                ) from exc
    max_bytes = config.get("max_file_bytes")
    if not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("public release config max_file_bytes must be a positive integer")
    for key in ("github_owner", "github_repository", "publisher_kind"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError("public release config %s must be a non-empty string" % key)
    if config["publisher_kind"] != "personal":
        raise ValueError("Eve's public release publisher_kind must remain personal")
    return config


def _git_paths(root: Path, args: Sequence[str]) -> Optional[Set[str]]:
    try:
        output = subprocess.check_output(
            ["git", *args, "-z"],
            cwd=root,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return {
        normalize_rel_path(item.decode("utf-8", "surrogateescape"))
        for item in output.split(b"\0")
        if item
    }


def git_tracked_paths(root: Path) -> Optional[Set[str]]:
    return _git_paths(root, ("ls-files",))


def git_untracked_paths(root: Path) -> Set[str]:
    return _git_paths(root, ("ls-files", "--others", "--exclude-standard")) or set()


def filesystem_paths(root: Path) -> Set[str]:
    paths: Set[str] = set()
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name != ".git"]
        current_path = Path(current)
        for filename in filenames:
            paths.add((current_path / filename).relative_to(root).as_posix())
    return paths


def candidate_paths(
    root: Path,
    config: Dict[str, Any],
    include_untracked: bool = False,
    known_paths: Optional[Iterable[str]] = None,
) -> Tuple[List[str], Set[str]]:
    tracked = git_tracked_paths(root) if known_paths is None else {normalize_rel_path(path) for path in known_paths}
    if tracked is None:
        tracked = filesystem_paths(root)
    universe = set(tracked)
    if include_untracked and known_paths is None:
        universe.update(git_untracked_paths(root))
    include = config["include"]
    force_include = config["force_include"]
    exclude = config["exclude"]
    selected = []
    for path in sorted(universe):
        forced = matches_any(path, force_include)
        if not forced and not matches_any(path, include):
            continue
        if not forced and matches_any(path, exclude):
            continue
        selected.append(path)
    return selected, set(tracked)


def finding(
    finding_id: str,
    severity: str,
    message: str,
    path: Optional[str] = None,
    line: Optional[int] = None,
    count: Optional[int] = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "id": finding_id,
        "severity": severity,
        "message": message,
    }
    if path is not None:
        result["path"] = path
    if line is not None:
        result["line"] = line
    if count is not None:
        result["count"] = count
    return result


def first_line(data: bytes, offset: int) -> int:
    return data.count(b"\n", 0, offset) + 1


def _rule_finding(
    rule_id: str,
    severity: str,
    message: str,
    path: str,
    data: bytes,
    regex: re.Pattern[bytes],
) -> Optional[Dict[str, Any]]:
    matches = list(regex.finditer(data))
    if not matches:
        return None
    return finding(
        rule_id,
        severity,
        message,
        path=path,
        line=first_line(data, matches[0].start()),
        count=len(matches),
    )


def _file_too_large_finding(path: str, size: int, maximum: int) -> Dict[str, Any]:
    return finding(
        "public.file_too_large",
        "error",
        "File is %d bytes; public source limit is %d bytes." % (size, maximum),
        path=path,
    )


def mask_owner_identifier_exemptions(path: str, data: bytes, config: Dict[str, Any]) -> bytes:
    """Mask narrowly declared technical terms before owner-identity scanning.

    Some standard optimizer names can contain an owner's name as a substring.
    Exemptions are path-specific regular expressions so a
    file containing both a technical term and owner-specific prose still fails.
    Replacing matched bytes with spaces preserves line offsets in findings.
    """

    masked = data
    patterns = config.get("owner_identifier_exemptions", {}).get(path, [])
    for pattern in patterns:
        regex = re.compile(pattern.encode("utf-8"), re.IGNORECASE)
        masked = regex.sub(lambda match: b" " * len(match.group(0)), masked)
    return masked


def scan_candidate_data(path: str, data: bytes, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    size = len(data)
    if size > config["max_file_bytes"]:
        results.append(_file_too_large_finding(path, size, config["max_file_bytes"]))
    if b"\0" in data[:8192]:
        return results

    for rule_name, regex in SECRET_RULES:
        item = _rule_finding(
            "secret.%s" % rule_name,
            "error",
            "A high-confidence credential signature is present. The value is intentionally not printed.",
            path,
            data,
            regex,
        )
        if item:
            results.append(item)

    generic_item = _rule_finding(
        "secret.literal_credential_review",
        "warning",
        "A literal credential-like assignment needs manual review; the value is intentionally not printed.",
        path,
        data,
        GENERIC_LITERAL_CREDENTIAL,
    )
    if generic_item:
        results.append(generic_item)

    home_matches = list(ABSOLUTE_MAC_HOME.finditer(data))
    if path.startswith("tests/"):
        generic_test_users = {b"example", b"test", b"user", b"runner"}
        home_matches = [match for match in home_matches if match.group(1).lower() not in generic_test_users]
    if home_matches:
        severity = "error" if matches_any(path, config["portable_source_patterns"]) else "warning"
        results.append(
            finding(
                "privacy.absolute_user_home",
                severity,
                "A user-specific macOS home path must become configuration, a template variable, or a portable example.",
                path=path,
                line=first_line(data, home_matches[0].start()),
                count=len(home_matches),
            )
        )

    email_item = _rule_finding(
        "privacy.email_address",
        "error",
        "A personal email address is present in the release candidate.",
        path,
        data,
        EMAIL_ADDRESS,
    )
    if email_item:
        results.append(email_item)

    conversation_item = _rule_finding(
        "privacy.private_conversation_link",
        "error",
        "A private/shared conversation link is present in the release candidate.",
        path,
        data,
        PRIVATE_CONVERSATION_LINK,
    )
    if conversation_item:
        results.append(conversation_item)

    if matches_any(path, config["behavior_patterns"]):
        for owner_name in config["behavior_owner_names"]:
            owner_regex = re.compile(rb"\b" + re.escape(owner_name.encode("utf-8")) + rb"\b", re.IGNORECASE)
            owner_item = _rule_finding(
                "privacy.owner_specific_behavior",
                "error",
                "Default behavior is hard-coded to the repository owner's identity; move this into local user configuration.",
                path,
                data,
                owner_regex,
            )
            if owner_item:
                results.append(owner_item)
    elif matches_any(path, config["owner_sensitive_patterns"]) and not matches_any(
        path, config["owner_identity_allowed_patterns"]
    ):
        owner_scan_data = mask_owner_identifier_exemptions(path, data, config)
        identifiers = [item.encode("utf-8") for item in config["owner_identifiers"] if item]
        if identifiers:
            owner_regex = re.compile(rb"(?:" + rb"|".join(re.escape(item) for item in identifiers) + rb")", re.IGNORECASE)
            owner_item = _rule_finding(
                "privacy.owner_specific_source",
                "error",
                "Product source or tests still encode the repository owner's identity or service namespace.",
                path,
                owner_scan_data,
                owner_regex,
            )
            if owner_item:
                results.append(owner_item)
    return results


def scan_candidate(root: Path, path: str, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    full_path = root / path
    results: List[Dict[str, Any]] = []
    try:
        initial_stat = full_path.lstat()
    except OSError as exc:
        results.append(
            finding(
                "public.file_unreadable",
                "error",
                "Unable to inspect candidate safely: %s" % (exc.strerror or type(exc).__name__),
                path=path,
            )
        )
        return results
    def unavailable():
        return [finding("public.source_not_local", "error", "Candidate is a dataless placeholder.", path=path)]

    if _is_dataless(initial_stat):
        return unavailable()
    if stat.S_ISLNK(initial_stat.st_mode):
        results.append(
            finding(
                "public.symlink_not_allowed",
                "error",
                "Public exports do not follow symlinks; replace this with an owned file.",
                path=path,
            )
        )
        return results
    if not stat.S_ISREG(initial_stat.st_mode):
        results.append(
            finding(
                "public.non_regular_file",
                "error",
                "Public exports accept regular owned files only.",
                path=path,
            )
        )
        return results

    maximum = config["max_file_bytes"]
    if initial_stat.st_size > maximum:
        return [_file_too_large_finding(path, initial_stat.st_size, maximum)]

    flags = os.O_RDONLY
    for flag_name in ("O_BINARY", "O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"):
        flags |= getattr(os, flag_name, 0)
    descriptor: Optional[int] = None
    try:
        descriptor = os.open(full_path, flags)
        opened_stat = os.fstat(descriptor)
        if _is_dataless(opened_stat):
            return unavailable()
        if not stat.S_ISREG(opened_stat.st_mode):
            return [
                finding(
                    "public.non_regular_file",
                    "error",
                    "Public exports accept regular owned files only.",
                    path=path,
                )
            ]
        if opened_stat.st_size > maximum:
            return [_file_too_large_finding(path, opened_stat.st_size, maximum)]

        chunks: List[bytes] = []
        remaining = maximum + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
    except OSError as exc:
        results.append(
            finding(
                "public.file_unreadable",
                "error",
                "Unable to read candidate safely: %s" % (exc.strerror or type(exc).__name__),
                path=path,
            )
        )
        return results
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(data) > maximum:
        return [_file_too_large_finding(path, len(data), maximum)]
    return results + scan_candidate_data(path, data, config)


def pyproject_findings(
    root: Path,
    config: Dict[str, Any],
    selected_paths: Sequence[str],
) -> List[Dict[str, Any]]:
    path = root / "pyproject.toml"
    if not path.exists():
        return []
    try:
        if _is_dataless(path.stat()):
            return [finding("packaging.metadata_not_local", "error", "Packaging metadata is not local.", path="pyproject.toml")]
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    project_match = re.search(r"(?ms)^\[project\]\s*(.*?)(?=^\[|\Z)", text)
    section = project_match.group(1) if project_match else ""
    results = []
    for field in ("license", "readme", "authors"):
        if not re.search(r"(?m)^%s\s*=" % re.escape(field), section):
            results.append(
                finding(
                    "packaging.missing_%s" % field,
                    "warning",
                    "The [project] table should declare %s metadata for a public release." % field,
                    path="pyproject.toml",
                )
            )
    if re.search(r"(?ms)^\[tool\.uv\]\s*.*?^package\s*=\s*false\b", text):
        selected = set(selected_paths)
        supported = [
            relative
            for relative in config.get("supported_installers", [])
            if relative in selected and (root / relative).is_file()
        ]
        if not supported:
            results.append(
                finding(
                    "packaging.not_installable",
                    "warning",
                    "The project is explicitly non-packageable; public onboarding needs a supported install path.",
                    path="pyproject.toml",
                )
            )
    for dependency in config.get("forbidden_declared_dependencies", []):
        declared = re.search(
            r"(?i)[\"']\s*%s(?:\[[^\]]+\])?(?:\s*[<>=!~;]|[\"'])"
            % re.escape(dependency),
            text,
        )
        if declared:
            results.append(
                finding(
                    "license.forbidden_declared_dependency",
                    "error",
                    "This dependency is outside Eve's permissive public install policy; keep the integration optional and user-managed.",
                    path="pyproject.toml",
                    line=first_line(text.encode("utf-8"), len(text[: declared.start()].encode("utf-8"))),
                )
            )
    return results


def github_remote_coordinates(remote_url: str) -> Optional[Tuple[str, str]]:
    value = str(remote_url or "").strip()
    patterns = (
        r"^git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$",
        r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$",
        r"^ssh://git@github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$",
    )
    for pattern in patterns:
        match = re.match(pattern, value, flags=re.IGNORECASE)
        if match:
            return match.group(1), match.group(2)
    return None


def git_posture_findings(root: Path, config: Dict[str, Any], *, check_worktree: bool = True) -> List[Dict[str, Any]]:
    if not (root / ".git").exists():
        return []
    results = []
    try:
        remotes = subprocess.check_output(["git", "remote"], cwd=root, text=True, stderr=subprocess.DEVNULL).split()
    except (OSError, subprocess.CalledProcessError):
        remotes = []
    if not remotes:
        results.append(
            finding(
                "git.no_remote",
                "warning",
                "No Git remote is configured. Add only the new clean public repository, never this private working history.",
            )
        )
    elif "origin" in remotes:
        try:
            origin = subprocess.check_output(
                ["git", "remote", "get-url", "origin"],
                cwd=root,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            origin = ""
        coordinates = github_remote_coordinates(origin)
        expected = (
            str(config.get("github_owner") or "").lower(),
            str(config.get("github_repository") or "").lower(),
        )
        if coordinates is None or tuple(item.lower() for item in coordinates) != expected:
            results.append(
                finding(
                    "git.personal_remote_mismatch",
                    "error",
                    "Origin must be the configured personal GitHub repository; organization or unrelated remotes are blocked.",
                )
            )
    if not check_worktree:
        results.append(finding("git.worktree_unchecked", "warning",
                               "Worktree status not checked while candidate files are unavailable."))
        return results
    try:
        status = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        status = ""
    if status.strip():
        results.append(
            finding(
                "git.dirty_worktree",
                "warning",
                "The working tree is dirty; public export must be generated from a reviewed immutable source revision.",
            )
        )
    return results


def audit_repository(
    root: Path,
    config: Dict[str, Any],
    include_untracked: bool = False,
    known_paths: Optional[Iterable[str]] = None,
    include_git_posture: bool = True,
    enforce_tracked_private: bool = True,
) -> Dict[str, Any]:
    root = root.resolve()
    selected, tracked = candidate_paths(root, config, include_untracked=include_untracked, known_paths=known_paths)
    findings: List[Dict[str, Any]] = []

    for required in config["required_files"]:
        if not (root / required).is_file():
            findings.append(
                finding(
                    "public.required_file_missing",
                    "error",
                    "Required public project file is missing.",
                    path=required,
                )
            )
        elif required not in selected:
            findings.append(
                finding(
                    "public.required_file_not_selected",
                    "error",
                    "Required public project file exists but is not tracked or selected for export.",
                    path=required,
                )
            )

    private_tracked = [
        path for path in sorted(tracked) if matches_any(path, config["tracked_private_patterns"])
    ]
    if enforce_tracked_private:
        for path in private_tracked:
            findings.append(
                finding(
                    "public.private_path_tracked",
                    "error",
                    "Private, generated, or operator-only material is tracked. Publish a clean export, not this Git history.",
                    path=path,
                )
            )
    elif private_tracked:
        findings.append(
            finding(
                "public.private_paths_excluded",
                "warning",
                "%d private, generated, or operator-only tracked paths are excluded from the clean candidate."
                % len(private_tracked),
                count=len(private_tracked),
            )
        )

    for path in selected:
        findings.extend(scan_candidate(root, path, config))
    findings.extend(pyproject_findings(root, config, selected))
    if include_git_posture:
        local = not any(item["id"] == "public.source_not_local" for item in findings)
        findings.extend(git_posture_findings(root, config, check_worktree=local))

    findings.sort(key=lambda item: (item["severity"] != "error", item["id"], item.get("path", "")))
    error_count = sum(item["severity"] == "error" for item in findings)
    warning_count = sum(item["severity"] == "warning" for item in findings)
    return {
        "schema_version": 1,
        "project": config.get("project_name", "Eve"),
        "release_strategy": config.get("release_strategy", "clean_export"),
        "audit_scope": "source_repository" if enforce_tracked_private else "clean_candidate",
        "root": str(root),
        "candidate_file_count": len(selected),
        "tracked_file_count": len(tracked),
        "source_private_tracked_count": len(private_tracked),
        "candidate_paths": selected,
        "error_count": error_count,
        "warning_count": warning_count,
        "ok": error_count == 0,
        "findings": findings,
    }


def _canonical_manifest_path(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("release manifest paths must be non-empty strings")
    if value.startswith("/") or "\\" in value:
        raise ValueError("release manifest paths must be relative POSIX paths: %r" % value)
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("release manifest path escapes or is not canonical: %r" % value)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("release manifest paths may not contain control characters")
    if normalize_rel_path(value) != value:
        raise ValueError("release manifest path is not canonical: %r" % value)
    return value


def _file_state(stat_result: os.stat_result) -> Tuple[int, int, int, int]:
    return (
        stat_result.st_dev,
        stat_result.st_ino,
        stat_result.st_size,
        getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000)),
    )


def _regular_file_digest(root: Path, relative_path: str) -> Tuple[int, str]:
    relative_path = _canonical_manifest_path(relative_path)
    full_path = root / relative_path
    try:
        initial_stat = full_path.lstat()
    except OSError as exc:
        raise ValueError(
            "unable to inspect manifest path %s: %s"
            % (relative_path, exc.strerror or type(exc).__name__)
        ) from exc
    _require_local(initial_stat, relative_path)
    if not stat.S_ISREG(initial_stat.st_mode):
        raise ValueError("manifest path is not a regular file: %s" % relative_path)

    flags = os.O_RDONLY
    for flag_name in ("O_BINARY", "O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"):
        flags |= getattr(os, flag_name, 0)
    descriptor: Optional[int] = None
    try:
        descriptor = os.open(full_path, flags)
        opened_stat = os.fstat(descriptor)
        _require_local(opened_stat, relative_path)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise ValueError("manifest path is not a regular file: %s" % relative_path)
        if (opened_stat.st_dev, opened_stat.st_ino) != (initial_stat.st_dev, initial_stat.st_ino):
            raise ValueError("manifest path changed while it was opened: %s" % relative_path)

        digest = hashlib.sha256()
        byte_count = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            byte_count += len(chunk)
            digest.update(chunk)
        final_stat = os.fstat(descriptor)
        if _file_state(opened_stat) != _file_state(final_stat) or byte_count != final_stat.st_size:
            raise ValueError("manifest path changed while it was hashed: %s" % relative_path)
        return byte_count, digest.hexdigest()
    except OSError as exc:
        raise ValueError(
            "unable to hash manifest path %s: %s"
            % (relative_path, exc.strerror or type(exc).__name__)
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def sha256_file(path: Path) -> str:
    """Compatibility helper for callers that need one regular-file digest."""

    return _regular_file_digest(path.parent.resolve(), path.name)[1]


def _manifest_tree_sha256(files: Sequence[Dict[str, Any]]) -> str:
    canonical = json.dumps(
        list(files),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def manifest_for(root: Path, paths: Sequence[str]) -> Dict[str, Any]:
    root = root.resolve()
    canonical_paths = [_canonical_manifest_path(path) for path in paths]
    if len(canonical_paths) != len(set(canonical_paths)):
        raise ValueError("release manifest paths must be unique")
    canonical_paths.sort()
    files = []
    for path in canonical_paths:
        byte_count, digest = _regular_file_digest(root, path)
        files.append({"path": path, "bytes": byte_count, "sha256": digest})
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "algorithm": "sha256",
        "file_count": len(files),
        "total_bytes": sum(item["bytes"] for item in files),
        "tree_sha256": _manifest_tree_sha256(files),
        "files": files,
    }


def validate_manifest(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("release manifest must be a JSON object")
    schema_version = payload.get("schema_version")
    if schema_version not in (1, MANIFEST_SCHEMA_VERSION):
        raise ValueError("unsupported release manifest schema_version: %r" % schema_version)
    files = payload.get("files")
    if not isinstance(files, list):
        raise ValueError("release manifest files must be a list")

    validated_files: List[Dict[str, Any]] = []
    previous_path: Optional[str] = None
    for index, entry in enumerate(files):
        if not isinstance(entry, dict):
            raise ValueError("release manifest file entry %d must be an object" % index)
        path = _canonical_manifest_path(entry.get("path"))
        byte_count = entry.get("bytes")
        digest = entry.get("sha256")
        if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 0:
            raise ValueError("release manifest bytes must be a non-negative integer for %s" % path)
        if not isinstance(digest, str) or not SHA256_HEX.fullmatch(digest):
            raise ValueError("release manifest sha256 must be lowercase hexadecimal for %s" % path)
        if previous_path is not None and path <= previous_path:
            raise ValueError("release manifest file paths must be unique and sorted")
        previous_path = path
        validated_files.append({"path": path, "bytes": byte_count, "sha256": digest})

    result: Dict[str, Any] = {
        "schema_version": schema_version,
        "files": validated_files,
    }
    if schema_version == MANIFEST_SCHEMA_VERSION:
        if payload.get("algorithm") != "sha256":
            raise ValueError("release manifest algorithm must be sha256")
        expected_count = len(validated_files)
        expected_bytes = sum(item["bytes"] for item in validated_files)
        expected_tree = _manifest_tree_sha256(validated_files)
        if payload.get("file_count") != expected_count:
            raise ValueError("release manifest file_count does not match its file entries")
        if payload.get("total_bytes") != expected_bytes:
            raise ValueError("release manifest total_bytes does not match its file entries")
        if payload.get("tree_sha256") != expected_tree:
            raise ValueError("release manifest tree_sha256 does not match its file entries")
        result.update(
            {
                "algorithm": "sha256",
                "file_count": expected_count,
                "total_bytes": expected_bytes,
                "tree_sha256": expected_tree,
            }
        )
    return result


def load_manifest(path: Path) -> Dict[str, Any]:
    try:
        file_stat = path.lstat()
        _require_local(file_stat, path.name)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError("release manifest must be a regular file")
        if file_stat.st_size > MANIFEST_MAX_BYTES:
            raise ValueError("release manifest exceeds the %d-byte limit" % MANIFEST_MAX_BYTES)
        raw = path.read_bytes()
        if len(raw) > MANIFEST_MAX_BYTES:
            raise ValueError("release manifest exceeds the %d-byte limit" % MANIFEST_MAX_BYTES)
        payload = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            "unable to read release manifest: %s"
            % (getattr(exc, "strerror", None) or type(exc).__name__)
        ) from exc
    return validate_manifest(payload)


def _exact_tree_paths(root: Path) -> Set[str]:
    paths: Set[str] = set()
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        descend = []
        for dirname in dirnames:
            full_path = current_path / dirname
            relative = full_path.relative_to(root).as_posix()
            if relative == ".git" or relative.startswith(".git/"):
                continue
            if full_path.is_symlink():
                paths.add(relative)
            else:
                descend.append(dirname)
        dirnames[:] = descend
        for filename in filenames:
            relative = (current_path / filename).relative_to(root).as_posix()
            if relative != ".git" and not relative.startswith(".git/"):
                paths.add(relative)
    return paths


def verify_manifest(
    root: Path,
    manifest: Dict[str, Any],
    expected_paths: Optional[Sequence[str]] = None,
    exact_tree: bool = False,
) -> Dict[str, Any]:
    root = root.resolve()
    manifest = validate_manifest(manifest)
    entries = {entry["path"]: entry for entry in manifest["files"]}
    manifest_paths = set(entries)
    findings: List[Dict[str, Any]] = []

    if expected_paths is not None:
        expected = {_canonical_manifest_path(path) for path in expected_paths}
        for path in sorted(expected - manifest_paths):
            findings.append(
                finding(
                    "manifest.candidate_path_missing",
                    "error",
                    "The audited candidate path is absent from the release manifest.",
                    path=path,
                )
            )
        for path in sorted(manifest_paths - expected):
            findings.append(
                finding(
                    "manifest.unexpected_path",
                    "error",
                    "The release manifest contains a path outside the audited candidate.",
                    path=path,
                )
            )

    if exact_tree:
        actual_tree_paths = _exact_tree_paths(root)
        for path in sorted(actual_tree_paths - manifest_paths):
            findings.append(
                finding(
                    "manifest.exact_tree_extra_path",
                    "error",
                    "The release tree contains a path absent from the manifest.",
                    path=path,
                )
            )

    verified_count = 0
    verified_bytes = 0
    for path, entry in entries.items():
        full_path = root / path
        try:
            current_stat = full_path.lstat()
        except OSError:
            findings.append(
                finding(
                    "manifest.file_missing",
                    "error",
                    "The release manifest path is missing from the verified tree.",
                    path=path,
                )
            )
            continue
        if not stat.S_ISREG(current_stat.st_mode):
            findings.append(
                finding(
                    "manifest.non_regular_file",
                    "error",
                    "The release manifest path is not a regular file.",
                    path=path,
                )
            )
            continue
        if current_stat.st_size != entry["bytes"]:
            findings.append(
                finding(
                    "manifest.size_mismatch",
                    "error",
                    "The release file size does not match the reviewed manifest.",
                    path=path,
                )
            )
            continue
        try:
            byte_count, digest = _regular_file_digest(root, path)
        except ValueError as exc:
            findings.append(
                finding(
                    "manifest.file_unreadable",
                    "error",
                    str(exc),
                    path=path,
                )
            )
            continue
        if byte_count != entry["bytes"]:
            findings.append(
                finding(
                    "manifest.size_mismatch",
                    "error",
                    "The release file size changed while it was verified.",
                    path=path,
                )
            )
            continue
        if digest != entry["sha256"]:
            findings.append(
                finding(
                    "manifest.sha256_mismatch",
                    "error",
                    "The release file digest does not match the reviewed manifest.",
                    path=path,
                )
            )
            continue
        verified_count += 1
        verified_bytes += byte_count

    findings.sort(key=lambda item: (item["id"], item.get("path", "")))
    return {
        "schema_version": 1,
        "manifest_schema_version": manifest["schema_version"],
        "root": str(root),
        "exact_tree": exact_tree,
        "manifest_file_count": len(entries),
        "verified_file_count": verified_count,
        "verified_bytes": verified_bytes,
        "error_count": len(findings),
        "ok": not findings,
        "findings": findings,
    }


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _copy_regular_file(source: Path, target: Path, relative_path: str) -> None:
    try:
        initial_stat = source.lstat()
    except OSError as exc:
        raise ValueError(
            "unable to inspect export source %s: %s"
            % (relative_path, exc.strerror or type(exc).__name__)
        ) from exc
    _require_local(initial_stat, relative_path)
    if not stat.S_ISREG(initial_stat.st_mode):
        raise ValueError("refusing to export non-regular file: %s" % relative_path)

    flags = os.O_RDONLY
    for flag_name in ("O_BINARY", "O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"):
        flags |= getattr(os, flag_name, 0)
    descriptor: Optional[int] = None
    copied = 0
    try:
        descriptor = os.open(source, flags)
        opened_stat = os.fstat(descriptor)
        _require_local(opened_stat, relative_path)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise ValueError("refusing to export non-regular file: %s" % relative_path)
        if (opened_stat.st_dev, opened_stat.st_ino) != (initial_stat.st_dev, initial_stat.st_ino):
            raise ValueError("export source changed while it was opened: %s" % relative_path)
        with target.open("xb") as output:
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                copied += len(chunk)
        final_stat = os.fstat(descriptor)
        if _file_state(opened_stat) != _file_state(final_stat) or copied != final_stat.st_size:
            raise ValueError("export source changed while it was copied: %s" % relative_path)
        os.chmod(target, stat.S_IMODE(opened_stat.st_mode))
        os.utime(target, ns=(opened_stat.st_atime_ns, opened_stat.st_mtime_ns))
    except OSError as exc:
        raise ValueError(
            "unable to copy export source %s: %s"
            % (relative_path, exc.strerror or type(exc).__name__)
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def export_tree(
    root: Path,
    destination: Path,
    paths: Sequence[str],
    validator: Optional[Callable[[Path], None]] = None,
) -> None:
    root = root.resolve()
    destination = destination.resolve()
    try:
        destination.relative_to(root)
    except ValueError:
        pass
    else:
        raise ValueError("export destination must be outside the private source tree: %s" % destination)
    if destination.exists():
        if not destination.is_dir() or any(destination.iterdir()):
            raise ValueError("export destination must not exist or must be empty: %s" % destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=".%s.eve-export-" % destination.name,
            dir=destination.parent,
        )
    )
    try:
        for path in sorted(_canonical_manifest_path(path) for path in paths):
            source = root / path
            target = staging / path
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy_regular_file(source, target, path)
        if validator is not None:
            validator(staging)
        if destination.exists():
            destination.rmdir()
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def render_human(report: Dict[str, Any], full: bool = False) -> str:
    lines = [
        "%s public release audit" % report["project"],
        "strategy: %s" % report["release_strategy"],
        "scope: %s" % report["audit_scope"],
        "candidate_files: %d" % report["candidate_file_count"],
        "tracked_files: %d" % report["tracked_file_count"],
        "errors: %d warnings: %d" % (report["error_count"], report["warning_count"]),
    ]
    limit = None if full else 80
    visible = report["findings"] if limit is None else report["findings"][:limit]
    for item in visible:
        location = item.get("path", "repository")
        if item.get("line"):
            location += ":%s" % item["line"]
        count = " (%s matches)" % item["count"] if item.get("count", 1) > 1 else ""
        lines.append("[%s] %s %s%s: %s" % (item["severity"].upper(), item["id"], location, count, item["message"]))
    hidden = len(report["findings"]) - len(visible)
    if hidden:
        lines.append("... %d more finding(s); rerun with --full or --json." % hidden)
    if report["ok"]:
        lines.append("result: release candidate passed blocking checks")
    else:
        lines.append("result: blocked; do not create or push the public repository yet")
    return "\n".join(lines)


def _attach_manifest_verification(
    report: Dict[str, Any],
    verification: Dict[str, Any],
) -> None:
    report["manifest_verification"] = verification
    report["findings"].extend(verification["findings"])
    report["findings"].sort(
        key=lambda item: (item["severity"] != "error", item["id"], item.get("path", ""))
    )
    report["error_count"] += verification["error_count"]
    report["ok"] = report["error_count"] == 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Eve source root")
    parser.add_argument("--config", type=Path, help="Release policy JSON (default: <root>/public_release.json)")
    parser.add_argument("--include-untracked", action="store_true", help="Audit matching untracked files too")
    parser.add_argument(
        "--candidate-only",
        action="store_true",
        help="Audit the filtered clean candidate instead of treating excluded private tracked paths as direct-publication errors",
    )
    parser.add_argument("--json", action="store_true", help="Print structured JSON")
    parser.add_argument("--full", action="store_true", help="Print every finding")
    parser.add_argument("--fail-on-warning", action="store_true", help="Return nonzero for warnings as well as errors")
    parser.add_argument(
        "--write-manifest",
        type=Path,
        help="Write a passing candidate manifest outside the audited source tree",
    )
    parser.add_argument(
        "--verify-manifest",
        type=Path,
        help="Verify candidate paths, sizes, and SHA-256 hashes against a reviewed manifest",
    )
    parser.add_argument(
        "--exact-tree",
        action="store_true",
        help="With --verify-manifest, reject every non-.git file absent from the manifest",
    )
    parser.add_argument(
        "--export",
        type=Path,
        help="Transactionally copy and verify a passing candidate in a new or empty directory",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    config_path = (args.config or (root / "public_release.json")).resolve()
    try:
        if args.exact_tree and not args.verify_manifest:
            raise ValueError("--exact-tree requires --verify-manifest")
        config = load_config(config_path)
        candidate_only = args.candidate_only or bool(args.export)
        report = audit_repository(
            root,
            config,
            include_untracked=args.include_untracked,
            enforce_tracked_private=not candidate_only,
        )
        if args.verify_manifest:
            verification = verify_manifest(
                root,
                load_manifest(args.verify_manifest.resolve()),
                expected_paths=report["candidate_paths"],
                exact_tree=args.exact_tree,
            )
            _attach_manifest_verification(report, verification)

        if (args.write_manifest or args.export) and not report["ok"]:
            noun = "export" if args.export else "manifest creation"
            raise ValueError("release audit has blocking findings; %s refused" % noun)

        source_manifest: Optional[Dict[str, Any]] = None
        if args.write_manifest or args.export:
            source_manifest = manifest_for(root, report["candidate_paths"])

        if args.write_manifest:
            manifest_path = args.write_manifest.resolve()
            try:
                manifest_path.relative_to(root)
            except ValueError:
                pass
            else:
                raise ValueError("release manifest output must be outside the audited source tree")

        if args.export:
            destination = args.export.resolve()
            if args.write_manifest:
                try:
                    args.write_manifest.resolve().relative_to(destination)
                except ValueError:
                    pass
                else:
                    raise ValueError("release manifest output must be outside the exported tree")
            assert source_manifest is not None

            def validate_export(staging: Path) -> None:
                exported_paths = _exact_tree_paths(staging)
                exported_report = audit_repository(
                    staging,
                    config,
                    known_paths=exported_paths,
                    include_git_posture=False,
                    enforce_tracked_private=True,
                )
                if not exported_report["ok"]:
                    raise ValueError("post-copy export audit failed")
                export_verification = verify_manifest(
                    staging,
                    source_manifest,
                    expected_paths=report["candidate_paths"],
                    exact_tree=True,
                )
                if not export_verification["ok"]:
                    raise ValueError("post-copy export manifest verification failed")

            export_tree(
                root,
                destination,
                report["candidate_paths"],
                validator=validate_export,
            )

        if args.write_manifest:
            assert source_manifest is not None
            write_json(args.write_manifest.resolve(), source_manifest)
    except ValueError as exc:
        print("eve-public-release-audit: %s" % exc, file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else render_human(report, full=args.full))
    if not report["ok"] or (args.fail_on_warning and report["warning_count"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
