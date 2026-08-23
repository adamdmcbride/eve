#!/usr/bin/env python3
"""Verify Eve's declared dependency/license inventory without network access."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError as exc:  # pragma: no cover - Eve requires Python 3.12+
    raise SystemExit("Python 3.12 or newer is required for the dependency audit") from exc


DIRECT_DEPENDENCY = re.compile(r"^\s*([A-Za-z0-9_.-]+)")
NOTICE_ROW = re.compile(
    r"^\|\s*(?P<name>[^|]+?)\s*\|\s*(?P<version>[^|]+?)\s*\|"
    r"\s*(?P<group>[^|]+?)\s*\|\s*(?P<license>[^|]+?)\s*\|\s*$"
)
NON_PERMISSIVE_MARKERS = ("gpl", "agpl", "sspl", "elastic license", "unknown")


def normalize_name(value: str) -> str:
    return re.sub(r"[-_.\s]+", "-", value.strip().lower())


def dependency_name(specifier: str) -> str:
    match = DIRECT_DEPENDENCY.match(specifier)
    if not match:
        raise ValueError(f"cannot parse dependency specifier: {specifier!r}")
    return normalize_name(match.group(1))


def declared_dependencies(project: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for specifier in project.get("dependencies") or []:
        result[dependency_name(str(specifier))] = "core"
    for group, entries in (project.get("optional-dependencies") or {}).items():
        for specifier in entries or []:
            name = dependency_name(str(specifier))
            if name in result and result[name] != group:
                result[name] = ", ".join(sorted({result[name], str(group)}))
            else:
                result[name] = str(group)
    return result


def locked_versions(lock: dict[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for package in lock.get("package") or []:
        name = normalize_name(str(package.get("name") or ""))
        version = str(package.get("version") or "").strip()
        if name and version:
            result.setdefault(name, set()).add(version)
    return result


def notice_inventory(text: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    in_direct_table = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line == "## Declared direct dependencies":
            in_direct_table = True
            continue
        if in_direct_table and line.startswith("## "):
            break
        if not in_direct_table or not line.startswith("|") or line.startswith("| ---"):
            continue
        match = NOTICE_ROW.match(line)
        if not match or match.group("name").strip() == "Dependency":
            continue
        row = {key: value.strip() for key, value in match.groupdict().items()}
        result[normalize_name(row["name"])] = row
    return result


def finding(finding_id: str, message: str, *, severity: str = "error", **detail: Any) -> dict[str, Any]:
    return {"id": finding_id, "severity": severity, "message": message, **detail}


def audit(root: Path) -> dict[str, Any]:
    root = root.expanduser().resolve()
    pyproject_path = root / "pyproject.toml"
    lock_path = root / "uv.lock"
    notices_path = root / "THIRD_PARTY_NOTICES.md"
    release_path = root / "public_release.json"
    findings: list[dict[str, Any]] = []

    required = (pyproject_path, lock_path, notices_path, release_path)
    for path in required:
        if not path.is_file():
            findings.append(
                finding(
                    "dependency.required_file_missing",
                    f"Required dependency-policy file is missing: {path.name}",
                    path=path.name,
                )
            )
    if findings:
        return _result(root, {}, findings)

    project_payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))["project"]
    lock_payload = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    release_payload = json.loads(release_path.read_text(encoding="utf-8"))
    declared = declared_dependencies(project_payload)
    versions = locked_versions(lock_payload)
    notices = notice_inventory(notices_path.read_text(encoding="utf-8"))

    forbidden = {
        normalize_name(str(name))
        for name in release_payload.get("forbidden_declared_dependencies") or []
    }
    for name in sorted(declared):
        if name in forbidden:
            findings.append(
                finding(
                    "dependency.forbidden_declared",
                    f"{name} is outside Eve's permissive public install policy.",
                    dependency=name,
                )
            )
        if name not in versions:
            findings.append(
                finding(
                    "dependency.not_locked",
                    f"Declared dependency {name} is missing from uv.lock.",
                    dependency=name,
                )
            )
        notice = notices.get(name)
        if notice is None:
            findings.append(
                finding(
                    "dependency.notice_missing",
                    f"Declared dependency {name} is missing from THIRD_PARTY_NOTICES.md.",
                    dependency=name,
                )
            )
            continue
        if notice["version"] not in versions.get(name, set()):
            findings.append(
                finding(
                    "dependency.notice_version_mismatch",
                    f"The reviewed {name} version is not present in uv.lock.",
                    dependency=name,
                    reviewed_version=notice["version"],
                    locked_versions=sorted(versions.get(name, set())),
                )
            )
        declared_groups = {item.strip() for item in declared[name].split(",")}
        if not all(group in notice["group"] for group in declared_groups):
            findings.append(
                finding(
                    "dependency.notice_group_mismatch",
                    f"The notice does not identify every install group for {name}.",
                    dependency=name,
                    declared_group=declared[name],
                    notice_group=notice["group"],
                )
            )
        license_text = notice["license"].lower()
        if any(marker in license_text for marker in NON_PERMISSIVE_MARKERS):
            findings.append(
                finding(
                    "dependency.non_permissive_direct_license",
                    f"Direct dependency {name} has an unapproved reviewed license: {notice['license']}",
                    dependency=name,
                    license=notice["license"],
                )
            )

    for name in sorted(set(notices) - set(declared)):
        findings.append(
            finding(
                "dependency.stale_notice",
                f"THIRD_PARTY_NOTICES.md lists undeclared direct dependency {name}.",
                severity="warning",
                dependency=name,
            )
        )
    return _result(root, declared, findings)


def _result(root: Path, declared: dict[str, str], findings: list[dict[str, Any]]) -> dict[str, Any]:
    errors = [item for item in findings if item["severity"] == "error"]
    warnings = [item for item in findings if item["severity"] == "warning"]
    return {
        "schema_version": 1,
        "root": str(root),
        "ok": not errors,
        "direct_dependency_count": len(declared),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "findings": findings,
        "boundary": "Direct declared dependencies only; this is not a transitive SBOM or legal advice.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = audit(args.root)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        status = "pass" if result["ok"] else "blocked"
        print(f"dependency license audit: {status}")
        print(f"direct dependencies: {result['direct_dependency_count']}")
        for item in result["findings"]:
            print(f"[{item['severity']}] {item['id']}: {item['message']}")
        print(result["boundary"])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
