#!/usr/bin/env python3
"""Retain Eve documentation evidence while reducing generated Markdown noise.

Default mode is dry-run. The first supported cleanup targets generated Hermes run
profiles: each run used to copy the full Hermes skill/reference tree, producing
thousands of duplicate Markdown files under .eve/hermes_runs/profiles/. Applying
this tool archives copied skills trees and replaces them with a symlink to the
canonical Hermes Eve profile skills directory.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import tarfile
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Set


ROOT_MARKERS = ("eve.py", "AGENTS.md")
DEFAULT_KEEP_LATEST = 3


@dataclass
class HermesSkillArchiveCandidate:
    profile: str
    profile_dir: str
    skills_dir: str
    archive_path: str
    manifest_path: str
    markdown_count: int
    file_count: int
    size_bytes: int
    reason: str
    protected: bool = False
    action: str = "archive_skills_and_symlink"


def repo_root_from(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for path in [current, *current.parents]:
        if all((path / marker).exists() for marker in ROOT_MARKERS):
            return path
    return current


def count_tree(path: Path) -> Dict[str, int]:
    files = 0
    markdown = 0
    bytes_total = 0
    for item in path.rglob("*"):
        if not item.is_file():
            continue
        files += 1
        if item.suffix.lower() in {".md", ".markdown"}:
            markdown += 1
        try:
            bytes_total += item.stat().st_size
        except OSError:
            pass
    return {"file_count": files, "markdown_count": markdown, "size_bytes": bytes_total}


def latest_json_profile_names(root: Path) -> Set[str]:
    latest = root / ".eve" / "hermes_runs" / "latest.json"
    protected: Set[str] = set()
    if not latest.exists():
        return protected
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return protected
    for key in ("temp_profile_home", "profile_home"):
        value = payload.get(key)
        if value:
            protected.add(Path(str(value)).name)
    return protected


def newest_profile_names(profiles_dir: Path, keep_latest: int) -> Set[str]:
    if keep_latest <= 0 or not profiles_dir.exists():
        return set()
    rows = []
    for profile in profiles_dir.iterdir():
        if not profile.is_dir():
            continue
        skills = profile / "skills"
        if skills.is_symlink() or not skills.is_dir():
            continue
        try:
            mtime = profile.stat().st_mtime
        except OSError:
            mtime = 0
        rows.append((mtime, profile.name))
    return {name for _, name in sorted(rows, reverse=True)[:keep_latest]}


def build_hermes_skill_archive_plan(
    root: Path,
    *,
    keep_latest: int = DEFAULT_KEEP_LATEST,
    canonical_skills_dir: Path | None = None,
    protect_latest_profile: bool = True,
) -> Dict[str, Any]:
    profiles_dir = root / ".eve" / "hermes_runs" / "profiles"
    archive_dir = root / ".eve" / "docs_noise_archives" / "hermes_profile_skills"
    canonical_skills_dir = canonical_skills_dir or (Path.home() / ".hermes" / "profiles" / "evelearning" / "skills")
    protected_names = newest_profile_names(profiles_dir, keep_latest)
    if protect_latest_profile:
        protected_names |= latest_json_profile_names(root)
    candidates: List[HermesSkillArchiveCandidate] = []
    protected: List[HermesSkillArchiveCandidate] = []
    skipped: List[Dict[str, str]] = []
    if not profiles_dir.exists():
        return {
            "status": "no_profiles_dir",
            "profiles_dir": str(profiles_dir),
            "canonical_skills_dir": str(canonical_skills_dir),
            "keep_latest": keep_latest,
            "protect_latest_profile": protect_latest_profile,
            "candidates": [],
            "protected": [],
            "skipped": [],
            "totals": {"candidate_profiles": 0, "markdown_count": 0, "file_count": 0, "size_bytes": 0},
        }
    for profile in sorted((p for p in profiles_dir.iterdir() if p.is_dir()), key=lambda p: p.name):
        skills = profile / "skills"
        if skills.is_symlink():
            skipped.append({"profile": profile.name, "reason": "skills_already_symlink"})
            continue
        if not skills.exists():
            skipped.append({"profile": profile.name, "reason": "skills_missing"})
            continue
        if not skills.is_dir():
            skipped.append({"profile": profile.name, "reason": "skills_not_directory"})
            continue
        counts = count_tree(skills)
        item = HermesSkillArchiveCandidate(
            profile=profile.name,
            profile_dir=str(profile),
            skills_dir=str(skills),
            archive_path=str(archive_dir / f"{profile.name}.skills.tar.gz"),
            manifest_path=str(archive_dir / f"{profile.name}.skills.manifest.json"),
            markdown_count=counts["markdown_count"],
            file_count=counts["file_count"],
            size_bytes=counts["size_bytes"],
            reason="copied_static_hermes_skills_tree",
            protected=profile.name in protected_names,
        )
        if item.protected:
            protected.append(item)
        else:
            candidates.append(item)
    totals = {
        "candidate_profiles": len(candidates),
        "markdown_count": sum(item.markdown_count for item in candidates),
        "file_count": sum(item.file_count for item in candidates),
        "size_bytes": sum(item.size_bytes for item in candidates),
    }
    return {
        "status": "ok",
        "profiles_dir": str(profiles_dir),
        "archive_dir": str(archive_dir),
        "canonical_skills_dir": str(canonical_skills_dir),
        "keep_latest": keep_latest,
        "protect_latest_profile": protect_latest_profile,
        "candidates": [asdict(item) for item in candidates],
        "protected": [asdict(item) for item in protected],
        "skipped": skipped,
        "totals": totals,
    }


def archive_and_symlink_candidate(candidate: Dict[str, Any], *, canonical_skills_dir: Path) -> Dict[str, Any]:
    skills_dir = Path(candidate["skills_dir"])
    archive_path = Path(candidate["archive_path"])
    manifest_path = Path(candidate["manifest_path"])
    if not skills_dir.exists() or skills_dir.is_symlink():
        return {"profile": candidate["profile"], "changed": False, "reason": "skills_missing_or_already_symlink"}
    if not canonical_skills_dir.exists():
        return {"profile": candidate["profile"], "changed": False, "reason": "canonical_skills_missing", "canonical_skills_dir": str(canonical_skills_dir)}
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if archive_path.exists():
        return {"profile": candidate["profile"], "changed": False, "reason": "archive_already_exists", "archive_path": str(archive_path)}
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(skills_dir, arcname="skills", recursive=True)
    manifest = {
        **candidate,
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "archive_path": str(archive_path),
        "canonical_skills_dir": str(canonical_skills_dir),
        "restore_hint": f"tar -xzf {archive_path} -C {Path(candidate['profile_dir'])}",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    shutil.rmtree(skills_dir)
    skills_dir.symlink_to(canonical_skills_dir, target_is_directory=True)
    return {
        "profile": candidate["profile"],
        "changed": True,
        "archive_path": str(archive_path),
        "manifest_path": str(manifest_path),
        "skills_symlink": str(skills_dir),
        "canonical_skills_dir": str(canonical_skills_dir),
    }


def apply_hermes_skill_archive_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    canonical_skills_dir = Path(str(plan["canonical_skills_dir"]))
    results = [archive_and_symlink_candidate(item, canonical_skills_dir=canonical_skills_dir) for item in plan.get("candidates", [])]
    return {
        "status": "applied",
        "changed": sum(1 for item in results if item.get("changed")),
        "unchanged": sum(1 for item in results if not item.get("changed")),
        "results": results,
    }


def format_bytes(num: int) -> str:
    value = float(num)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GiB"


def format_report(plan: Dict[str, Any], apply_result: Dict[str, Any] | None = None) -> str:
    totals = plan.get("totals", {})
    lines = [
        "Eve docs retention plan",
        f"status: {plan.get('status')}",
        f"profiles_dir: {plan.get('profiles_dir')}",
        f"canonical_skills_dir: {plan.get('canonical_skills_dir')}",
        f"keep_latest: {plan.get('keep_latest')}",
        f"protect_latest_profile: {plan.get('protect_latest_profile')}",
        f"candidates: {totals.get('candidate_profiles', 0)} profile(s), {totals.get('markdown_count', 0)} markdown file(s), {format_bytes(int(totals.get('size_bytes', 0)))}",
        f"protected: {len(plan.get('protected', []))} profile(s)",
        f"skipped: {len(plan.get('skipped', []))} profile(s)",
    ]
    for item in plan.get("candidates", [])[:20]:
        lines.append(
            f"- archive {item['profile']}: {item['markdown_count']} md, {format_bytes(int(item['size_bytes']))} -> {item['archive_path']}"
        )
    if len(plan.get("candidates", [])) > 20:
        lines.append(f"... {len(plan['candidates']) - 20} more candidate(s)")
    if apply_result is not None:
        lines.extend([
            "",
            "Apply result",
            f"changed: {apply_result.get('changed', 0)}",
            f"unchanged: {apply_result.get('unchanged', 0)}",
        ])
    else:
        lines.extend([
            "",
            "dry_run: true",
            "To apply: python3 bin/eve_docs_retention.py --archive-hermes-profile-skills --apply --yes",
        ])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Archive generated documentation noise without deleting evidence.")
    parser.add_argument("--json", action="store_true", help="Print JSON.")
    parser.add_argument("--archive-hermes-profile-skills", action="store_true", help="Plan/archive copied Hermes run profile skills trees.")
    parser.add_argument("--keep-latest", type=int, default=DEFAULT_KEEP_LATEST, help="Protect this many newest Hermes temp profiles.")
    parser.add_argument(
        "--archive-latest-profile-skills",
        action="store_true",
        help=(
            "Do not protect the profile referenced by .eve/hermes_runs/latest.json. "
            "Use for stale smoke-run profile copies; the profile remains usable through the canonical skills symlink."
        ),
    )
    parser.add_argument("--canonical-skills-dir", type=Path, default=None, help="Canonical Hermes skills directory to symlink to.")
    parser.add_argument("--apply", action="store_true", help="Apply the retention plan.")
    parser.add_argument("--yes", action="store_true", help="Required with --apply.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.archive_hermes_profile_skills:
        args.archive_hermes_profile_skills = True
    root = repo_root_from()
    plan = build_hermes_skill_archive_plan(
        root,
        keep_latest=args.keep_latest,
        canonical_skills_dir=args.canonical_skills_dir,
        protect_latest_profile=not args.archive_latest_profile_skills,
    )
    apply_result = None
    if args.apply:
        if not args.yes:
            if args.json:
                print(json.dumps({"plan": plan, "error": "--apply requires --yes"}, indent=2, sort_keys=True))
            else:
                print(format_report(plan))
                print("error: --apply requires --yes")
            return 2
        apply_result = apply_hermes_skill_archive_plan(plan)
    if args.json:
        payload = {"plan": plan}
        if apply_result is not None:
            payload["apply_result"] = apply_result
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(format_report(plan, apply_result=apply_result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
