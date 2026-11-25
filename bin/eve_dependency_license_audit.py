#!/usr/bin/env python3
"""Verify Eve's declared dependency/license inventory without network access."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote

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
SPDX_TOKEN = re.compile(r"LicenseRef-[A-Za-z0-9.-]+|[A-Za-z0-9][A-Za-z0-9.+-]*")
SPDX_OPERATORS = {"AND", "OR", "WITH"}
IMMUTABLE_REVISION = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


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


def package_purl(package: dict[str, Any]) -> str:
    for reference in package.get("externalRefs") or []:
        if not isinstance(reference, dict):
            continue
        if reference.get("referenceType") == "purl":
            return str(reference.get("referenceLocator") or "").strip()
    return ""


def python_purl_identity(purl: str) -> tuple[str, str] | None:
    prefix = "pkg:pypi/"
    if not purl.startswith(prefix):
        return None
    body = purl[len(prefix) :].split("#", 1)[0].split("?", 1)[0]
    if "@" not in body:
        return None
    name, version = body.rsplit("@", 1)
    name = normalize_name(unquote(name))
    version = unquote(version).strip()
    if not name or not version or "/" in name:
        return None
    return name, version


def locked_python_package_identities(
    lock: dict[str, Any],
    project: dict[str, Any],
) -> set[tuple[str, str]]:
    identities: set[tuple[str, str]] = set()
    for package in lock.get("package") or []:
        if not isinstance(package, dict):
            continue
        source = package.get("source")
        if not isinstance(source, dict) or "registry" not in source:
            continue
        name = normalize_name(str(package.get("name") or ""))
        version = str(package.get("version") or "").strip()
        if name and version:
            identities.add((name, version))

    project_name = normalize_name(str(project.get("name") or ""))
    project_version = str(project.get("version") or "").strip()
    if project_name and project_version:
        identities.add((project_name, project_version))
    return identities


def _python_identity_purl(identity: tuple[str, str]) -> str:
    return f"pkg:pypi/{identity[0]}@{identity[1]}"


def python_package_inventory_findings(
    payload: dict[str, Any],
    lock: dict[str, Any],
    project: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Bind an SPDX Python package inventory to this checkout's exact lock inventory."""

    sbom = payload.get("sbom") if isinstance(payload.get("sbom"), dict) else payload
    packages = sbom.get("packages") if isinstance(sbom, dict) else None
    if not isinstance(packages, list):
        return [], {}

    expected = locked_python_package_identities(lock, project)
    observed: set[tuple[str, str]] = set()
    malformed: list[str] = []
    for package in packages:
        if not isinstance(package, dict):
            continue
        purl = package_purl(package)
        if not purl.startswith("pkg:pypi/"):
            continue
        identity = python_purl_identity(purl)
        if identity is None:
            malformed.append(purl)
        else:
            observed.add(identity)

    missing = sorted(expected - observed)
    extra = sorted(observed - expected)
    summary = {
        "expected_python_package_count": len(expected),
        "observed_python_package_count": len(observed),
        "python_inventory_missing_count": len(missing),
        "python_inventory_extra_count": len(extra),
        "python_inventory_malformed_purl_count": len(malformed),
    }
    if not missing and not extra and not malformed:
        return [], summary

    return [
        finding(
            "dependency.sbom_lock_inventory_mismatch",
            "SPDX Python packages do not exactly match uv.lock and the project identity.",
            expected_python_package_count=len(expected),
            observed_python_package_count=len(observed),
            missing_count=len(missing),
            extra_count=len(extra),
            malformed_purl_count=len(malformed),
            missing_python_packages=[_python_identity_purl(item) for item in missing[:12]],
            extra_python_packages=[_python_identity_purl(item) for item in extra[:12]],
            malformed_python_purls=sorted(malformed)[:12],
        )
    ], summary


def spdx_license_ids(expression: str) -> set[str]:
    return {
        token
        for token in SPDX_TOKEN.findall(str(expression or ""))
        if token.upper() not in SPDX_OPERATORS
    }


def transitive_license_findings(
    payload: dict[str, Any],
    release_policy: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    sbom = payload.get("sbom") if isinstance(payload.get("sbom"), dict) else payload
    packages = sbom.get("packages") if isinstance(sbom, dict) else None
    if not isinstance(packages, list):
        return [finding("dependency.sbom_invalid", "SPDX SBOM has no packages list.")], {}

    allowed = {
        str(item) for item in release_policy.get("permissive_transitive_license_ids") or []
    }
    allowed.update(
        str(item) for item in release_policy.get("permissive_transitive_license_refs") or []
    )
    overrides = release_policy.get("transitive_license_overrides") or {}
    if not isinstance(overrides, dict):
        return [finding("dependency.sbom_policy_invalid", "transitive_license_overrides must be an object.")], {}

    findings: list[dict[str, Any]] = []
    observed_purls: set[str] = set()
    reviewed = 0
    overridden = 0
    for package in packages:
        if not isinstance(package, dict):
            continue
        purl = package_purl(package)
        if purl:
            observed_purls.add(purl)
        expression = str(
            package.get("licenseConcluded")
            or package.get("licenseDeclared")
            or "NOASSERTION"
        ).strip()
        override = overrides.get(purl) if purl else None
        if override is not None:
            effective_license = str(
                override.get("effective_license") if isinstance(override, dict) else ""
            ).strip()
            evidence_url = str(
                override.get("evidence_url") if isinstance(override, dict) else ""
            ).strip()
            evidence_sha256 = str(
                override.get("evidence_sha256") if isinstance(override, dict) else ""
            ).strip()
            if (
                not effective_license
                or not evidence_url.startswith("https://")
                or not SHA256.fullmatch(evidence_sha256)
            ):
                findings.append(
                    finding(
                        "dependency.sbom_override_invalid",
                        f"License override for {purl} lacks immutable HTTPS and SHA-256 evidence metadata.",
                        package=str(package.get("name") or "unknown"),
                        purl=purl,
                    )
                )
                continue
            expression = effective_license
            overridden += 1

        identifiers = spdx_license_ids(expression)
        package_detail = {
            "package": str(package.get("name") or "unknown"),
            "version": str(package.get("versionInfo") or ""),
            "purl": purl,
            "license": expression,
        }
        if not identifiers or "NOASSERTION" in identifiers or "NONE" in identifiers:
            findings.append(
                finding(
                    "dependency.sbom_license_unresolved",
                    f"Transitive package {package_detail['package']} has no reviewed license conclusion.",
                    **package_detail,
                )
            )
            continue
        unapproved = sorted(identifiers - allowed)
        if unapproved:
            findings.append(
                finding(
                    "dependency.sbom_license_not_permissive",
                    f"Transitive package {package_detail['package']} includes unapproved license identifiers.",
                    unapproved_license_ids=unapproved,
                    **package_detail,
                )
            )
            continue
        reviewed += 1

    for purl in sorted(set(overrides) - observed_purls):
        findings.append(
            finding(
                "dependency.sbom_override_stale",
                f"Reviewed license override is not present in this SBOM: {purl}",
                severity="warning",
                purl=purl,
            )
        )
    return findings, {
        "package_count": len(packages),
        "reviewed_package_count": reviewed,
        "overridden_package_count": overridden,
    }


def finding(finding_id: str, message: str, *, severity: str = "error", **detail: Any) -> dict[str, Any]:
    return {"id": finding_id, "severity": severity, "message": message, **detail}


def audit(
    root: Path,
    *,
    sbom_path: Path | None = None,
    source_revision: str = "",
) -> dict[str, Any]:
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
    sbom_summary: dict[str, Any] = {}
    if sbom_path is not None:
        if not IMMUTABLE_REVISION.fullmatch(source_revision):
            findings.append(
                finding(
                    "dependency.sbom_revision_invalid",
                    "An exact 40- or 64-character lowercase hexadecimal source revision is required with --sbom.",
                    source_revision=source_revision,
                )
            )
        try:
            sbom_bytes = sbom_path.expanduser().read_bytes()
            sbom_payload = json.loads(sbom_bytes)
        except (OSError, json.JSONDecodeError) as exc:
            findings.append(
                finding(
                    "dependency.sbom_unreadable",
                    f"Unable to read SPDX SBOM: {exc}",
                    path=str(sbom_path),
                )
            )
        else:
            sbom_findings, sbom_summary = transitive_license_findings(
                sbom_payload,
                release_payload,
            )
            inventory_findings, inventory_summary = python_package_inventory_findings(
                sbom_payload,
                lock_payload,
                project_payload,
            )
            sbom_summary.update(inventory_summary)
            sbom = (
                sbom_payload.get("sbom")
                if isinstance(sbom_payload.get("sbom"), dict)
                else sbom_payload
            )
            creation_info = sbom.get("creationInfo") if isinstance(sbom, dict) else {}
            sbom_summary.update(
                {
                    "sha256": hashlib.sha256(sbom_bytes).hexdigest(),
                    "spdx_version": str(sbom.get("spdxVersion") or "")
                    if isinstance(sbom, dict)
                    else "",
                    "name": str(sbom.get("name") or "")
                    if isinstance(sbom, dict)
                    else "",
                    "created": str(creation_info.get("created") or "")
                    if isinstance(creation_info, dict)
                    else "",
                    "uv_lock_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
                }
            )
            findings.extend(sbom_findings)
            findings.extend(inventory_findings)
    return _result(
        root,
        declared,
        findings,
        sbom_summary=sbom_summary,
        source_revision=source_revision,
    )


def _result(
    root: Path,
    declared: dict[str, str],
    findings: list[dict[str, Any]],
    *,
    sbom_summary: dict[str, Any] | None = None,
    source_revision: str = "",
) -> dict[str, Any]:
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
        "sbom": dict(sbom_summary or {}),
        "source_revision": source_revision,
        "boundary": (
            "Direct dependency inventory plus an optional conservative SPDX transitive-license gate; "
            "this is release evidence, not legal advice."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--sbom", type=Path, help="GitHub/SPDX SBOM JSON for the exact release revision")
    parser.add_argument("--source-revision", default="", help="Immutable source revision associated with --sbom")
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = audit(args.root, sbom_path=args.sbom, source_revision=args.source_revision)
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
