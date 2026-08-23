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
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


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
        results.append(
            finding(
                "public.file_too_large",
                "error",
                "File is %d bytes; public source limit is %d bytes." % (size, config["max_file_bytes"]),
                path=path,
            )
        )
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
    if full_path.is_symlink():
        results.append(
            finding(
                "public.symlink_not_allowed",
                "error",
                "Public exports do not follow symlinks; replace this with an owned file.",
                path=path,
            )
        )
        return results
    try:
        data = full_path.read_bytes()
    except OSError as exc:
        results.append(finding("public.file_unreadable", "error", str(exc), path=path))
        return results
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


def git_posture_findings(root: Path, config: Dict[str, Any]) -> List[Dict[str, Any]]:
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
        findings.extend(git_posture_findings(root, config))

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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_for(root: Path, paths: Sequence[str]) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "files": [
            {
                "path": path,
                "bytes": (root / path).stat().st_size,
                "sha256": sha256_file(root / path),
            }
            for path in paths
        ],
    }


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def export_tree(root: Path, destination: Path, paths: Sequence[str]) -> None:
    root = root.resolve()
    destination = destination.resolve()
    try:
        destination.relative_to(root)
    except ValueError:
        pass
    else:
        raise ValueError("export destination must be outside the private source tree: %s" % destination)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("export destination must not exist or must be empty: %s" % destination)
    destination.mkdir(parents=True, exist_ok=True)
    for path in paths:
        source = root / path
        target = destination / path
        if source.is_symlink():
            raise ValueError("refusing to export symlink: %s" % path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


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
    parser.add_argument("--write-manifest", type=Path, help="Write candidate paths, sizes, and SHA-256 hashes")
    parser.add_argument("--export", type=Path, help="Copy a passing candidate into a new or empty directory")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    config_path = (args.config or (root / "public_release.json")).resolve()
    try:
        config = load_config(config_path)
        candidate_only = args.candidate_only or bool(args.export)
        report = audit_repository(
            root,
            config,
            include_untracked=args.include_untracked,
            enforce_tracked_private=not candidate_only,
        )
        if args.write_manifest:
            write_json(args.write_manifest.resolve(), manifest_for(root, report["candidate_paths"]))
        if args.export:
            if not report["ok"]:
                raise ValueError("release audit has blocking findings; export refused")
            export_tree(root, args.export, report["candidate_paths"])
            exported_paths = filesystem_paths(args.export.resolve())
            exported_report = audit_repository(
                args.export.resolve(),
                config,
                known_paths=exported_paths,
                include_git_posture=False,
                enforce_tracked_private=True,
            )
            if not exported_report["ok"]:
                raise ValueError("post-copy export audit failed")
    except ValueError as exc:
        print("eve-public-release-audit: %s" % exc, file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else render_human(report, full=args.full))
    if not report["ok"] or (args.fail_on_warning and report["warning_count"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
