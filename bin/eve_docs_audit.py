#!/usr/bin/env python3
"""Audit Eve's documentation shelves and authority metadata.

This is intentionally non-destructive. It helps future agents distinguish
canonical doctrine from active roadmaps, evidence logs, historical research, and
archive candidates without deleting historical evidence.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REQUIRED_STATUS_KEYS = (
    "Status",
    "Last reviewed",
    "Current authority",
    "Supersedes",
    "Superseded by",
)

VALID_STATUSES = {
    "canonical",
    "active",
    "evidence-log",
    "historical",
    "archive-candidate",
}

SHELF_HEADINGS = {
    "canonical doctrine: current source of truth": "canonical",
    "operating manuals and domain doctrine": "operating-manual",
    "current architecture and recovery notes": "current-architecture",
    "active roadmaps and staged tracks": "active-roadmap",
    "operating baselines and evidence logs": "evidence-log",
    "historical research and idea capture": "historical-research",
    "historical audits": "historical-audit",
}

ARCHIVE_PARTS = {"archive", "archived"}

ROOT_OPERATOR_MARKDOWN = {
    "AGENTS.md",
    "CLAUDE.md",
    "CLAUDE_EVE_BRIDGE.md",
    "COORDINATION.md",
    "PROJECT_MEMORY.md",
    "README.md",
}

OPENCLAW_SIDECAR_ROOT_MARKDOWN = {
    "openclaw/AGENTS.md",
    "openclaw/BOOTSTRAP.md",
    "openclaw/DREAMS.md",
    "openclaw/HEARTBEAT.md",
    "openclaw/IDENTITY.md",
    "openclaw/MEMORY.md",
    "openclaw/SOUL.md",
    "openclaw/TOOLS.md",
    "openclaw/USER.md",
}

REPO_NOISE_RULES = (
    (
        ".eve/hermes_runs/",
        "generated-hermes-profile-copies",
        "Hermes smoke/profile sandboxes that copy skill/reference docs; keep out of human doc navigation.",
    ),
    (
        ".eve/runtime_tools/",
        "runtime-tool-source-copies",
        "Downloaded/forked runtime tool source trees; read only when working on that tool.",
    ),
    (
        ".eve/oss_integration/",
        "oss-lab-venv-package-docs",
        "Local OSS lab virtualenv/site-package docs; not Eve project documentation.",
    ),
    (
        ".eve/",
        "runtime-state-artifacts",
        "Eve runtime state, ledgers, test artifacts, and generated files; prefer Eve commands over browsing.",
    ),
    (
        "openclaw/memory/",
        "openclaw-runtime-memory",
        "OpenClaw memory/day logs; useful as evidence, but noisy as prose documentation.",
    ),
    (
        "openclaw/context/",
        "openclaw-generated-context",
        "OpenClaw current-context snapshots; read through status/sync commands when possible.",
    ),
    (
        "openclaw/dreams/",
        "openclaw-dream-artifacts",
        "OpenClaw dream artifacts; historical/lab evidence, not canonical Eve doctrine.",
    ),
    (
        "openclaw/wiki/",
        "openclaw-memory-wiki",
        "OpenClaw support wiki generated from Eve sources; secondary to canonical docs.",
    ),
    (
        "openclaw/skills/",
        "openclaw-skills",
        "OpenClaw skill docs; relevant only when changing body/action capabilities.",
    ),
    (
        ".venv",
        "local-virtualenv-docs",
        "Local Python virtualenv package docs; ignore for Eve documentation work.",
    ),
    (
        ".venv-techlab/",
        "local-virtualenv-docs",
        "Local lab virtualenv package docs; ignore for Eve documentation work.",
    ),
    (
        "EveBackups/",
        "local-backup-docs",
        "Local backup snapshots; consult only for recovery, not current policy.",
    ),
    (
        "vendor/",
        "vendor-docs",
        "Third-party vendored docs; secondary to Eve source/docs.",
    ),
    (
        "memory/",
        "imported-memory-evidence",
        "Imported conversation/memory evidence; search only when reconstructing history.",
    ),
    (
        "docs/",
        "curated-docs",
        "Curated Eve documentation shelf audited by status metadata.",
    ),
    (
        "prompts/",
        "prompt-assets",
        "Prompt assets; behavior-affecting source, not narrative documentation.",
    ),
)

COMPONENT_README_PREFIXES = ("design/", "experiments/", "go/", "rust/")

TRACKED_NON_DOC_GUIDANCE = {
    "root-operator-surfaces": "Root Markdown is operational context or history; start at docs/README.md instead of reading all of it.",
    "prompt-assets": "Prompt Markdown is behavior-affecting source, not narrative documentation.",
    "openclaw-sidecar-docs": "OpenClaw sidecar docs are body/action subsystem boot/support files. Start at openclaw/AGENTS.md; do not treat SOUL/IDENTITY/USER templates, hooks, or DREAMS diary text as canonical Eve doctrine.",
    "openclaw-memory-wiki": "OpenClaw wiki pages are secondary support memory; canonical Eve doctrine lives under docs/.",
    "openclaw-skills": "OpenClaw skill docs matter only for body/action capability work.",
    "imported-memory-evidence": "Imported memory files are evidence trails, not current policy.",
    "component-readmes": "Component/language README files are local subsystem notes, not the project reading path.",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()



def repo_root_from(start: Optional[Path] = None) -> Path:
    path = (start or Path.cwd()).resolve()
    for candidate in (path, *path.parents):
        if (candidate / "eve.py").exists() and (candidate / "docs").is_dir():
            return candidate
    return path


def git_tracked_paths(root: Path) -> set[str]:
    try:
        output = subprocess.check_output(["git", "ls-files"], cwd=root, text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return set()
    return {line.strip() for line in output.splitlines() if line.strip()}


def classify_repo_markdown(rel_path: str) -> Dict[str, str]:
    if rel_path in ROOT_OPERATOR_MARKDOWN:
        return {
            "category": "root-operator-surfaces",
            "recommendation": "Large root operator/history surfaces; use docs/README.md as the reading path first.",
        }
    if rel_path in OPENCLAW_SIDECAR_ROOT_MARKDOWN:
        return {
            "category": "openclaw-sidecar-docs",
            "recommendation": "OpenClaw sidecar root doc; read openclaw/AGENTS.md first and treat identity/template/dream files as scoped sidecar context, not canonical Eve doctrine.",
        }
    if rel_path.startswith(COMPONENT_README_PREFIXES):
        return {
            "category": "component-readmes",
            "recommendation": "Subsystem README; relevant only when working in that component.",
        }
    for prefix, category, recommendation in REPO_NOISE_RULES:
        if rel_path.startswith(prefix):
            return {"category": category, "recommendation": recommendation}
    if rel_path.startswith("openclaw/"):
        return {
            "category": "openclaw-sidecar-docs",
            "recommendation": "OpenClaw sidecar/support doc; read only when changing OpenClaw body/action integration, not as Eve canonical doctrine.",
        }
    return {
        "category": "project-root-or-misc-docs",
        "recommendation": "Small set of root/misc docs; inspect directly if they appear in navigation.",
    }


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def markdown_files(docs_dir: Path) -> List[Path]:
    return sorted(path for path in docs_dir.rglob("*.md") if path.is_file())


def repo_markdown_files(root: Path) -> List[Path]:
    return sorted(path for path in root.rglob("*.md") if path.is_file() and ".git" not in path.parts)


def relative_doc_path(path: Path, docs_dir: Path) -> str:
    return path.relative_to(docs_dir).as_posix()


def first_h1(text: str) -> str:
    match = re.search(r"^#\s+(.+?)\s*$", text, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def parse_status_block(text: str) -> Dict[str, str]:
    """Parse the simple top-of-file docs status block.

    The block is expected shortly after the H1. We only inspect early non-empty
    lines so accidental later mentions of "Status:" do not count.
    """

    lines = [line.rstrip() for line in text.splitlines()[:16]]
    status: Dict[str, str] = {}
    for line in lines:
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key in REQUIRED_STATUS_KEYS and key not in status:
            status[key] = value.strip()
    return status


def duplicate_status_keys(text: str, *, line_limit: int = 30) -> List[Dict[str, int | str]]:
    seen: Dict[str, int] = {}
    duplicates: List[Dict[str, int | str]] = []
    for index, line in enumerate(text.splitlines()[:line_limit], start=1):
        if ":" not in line:
            continue
        key = line.split(":", 1)[0].strip()
        if key not in REQUIRED_STATUS_KEYS:
            continue
        if key in seen:
            duplicates.append({"key": key, "first_line": seen[key], "line": index})
        else:
            seen[key] = index
    return duplicates


def normalize_doc_ref(ref: str) -> str:
    ref = ref.strip().strip("`")
    if "/docs/" in ref:
        ref = ref.split("/docs/", 1)[1]
    ref = ref.replace("docs/", "") if ref.startswith("docs/") else ref
    return ref.lstrip("/")


def parse_front_door_shelves(front_door_text: str) -> Dict[str, str]:
    shelves: Dict[str, str] = {}
    current_shelf = ""
    for raw_line in front_door_text.splitlines():
        line = raw_line.strip()
        heading = re.match(r"^###\s+(.+?)\s*$", line)
        if heading:
            current_shelf = SHELF_HEADINGS.get(heading.group(1).strip().lower(), "")
            continue
        if not current_shelf or not line.startswith("- "):
            continue
        code_match = re.search(r"`([^`]+\.md)`", line)
        if not code_match:
            continue
        ref = normalize_doc_ref(code_match.group(1))
        shelves[ref] = current_shelf
    return shelves


def front_door_shelf_item_counts(front_door_text: str) -> Dict[str, int]:
    counts: Counter[str] = Counter()
    current_shelf = ""
    for raw_line in front_door_text.splitlines():
        line = raw_line.strip()
        heading = re.match(r"^###\s+(.+?)\s*$", line)
        if heading:
            current_shelf = SHELF_HEADINGS.get(heading.group(1).strip().lower(), "")
            continue
        if not current_shelf or not line.startswith("- "):
            continue
        if re.search(r"`([^`]+\.md)`", line):
            counts[current_shelf] += 1
    return dict(sorted(counts.items()))


def umbrella_shelf(rel_path: str, shelves: Dict[str, str]) -> str:
    if rel_path == "README.md":
        return "canonical"
    parts = set(Path(rel_path).parts)
    if parts & ARCHIVE_PARTS:
        return "archive"
    if rel_path in shelves:
        return shelves[rel_path]
    if rel_path.startswith("model_lanes/") and "model_lanes/README.md" in shelves:
        return shelves["model_lanes/README.md"]
    if rel_path.startswith("routing/") and "routing/README.md" in shelves:
        return shelves["routing/README.md"]
    if rel_path.startswith("roadmaps/") and "roadmaps/README.md" in shelves:
        return shelves["roadmaps/README.md"]
    if rel_path.startswith("evidence/") and "evidence/README.md" in shelves:
        return shelves["evidence/README.md"]
    if rel_path.startswith("operating/") and "operating/README.md" in shelves:
        return shelves["operating/README.md"]
    if rel_path.startswith("evals/") and "evals/README.md" in shelves:
        return shelves["evals/README.md"]
    return "unshelved"


def status_missing_keys(status: Dict[str, str]) -> List[str]:
    return [key for key in REQUIRED_STATUS_KEYS if not status.get(key)]


def analyze_doc(path: Path, docs_dir: Path, shelves: Dict[str, str]) -> Dict[str, Any]:
    rel = relative_doc_path(path, docs_dir)
    text = read_text(path)
    status = parse_status_block(text)
    duplicate_keys = duplicate_status_keys(text)
    missing = status_missing_keys(status)
    raw_status_value = status.get("Status", "").strip().lower()
    # Legacy docs sometimes had a prose "Status:" line without the full authority
    # block. Treat those as missing metadata, not invalid new metadata.
    status_value = "missing" if missing else raw_status_value
    return {
        "path": rel,
        "title": first_h1(text),
        "status": status_value,
        "valid_status": bool(status_value == "missing" or status_value in VALID_STATUSES),
        "missing_status_keys": missing,
        "duplicate_status_keys": duplicate_keys,
        "shelf": umbrella_shelf(rel, shelves),
        "word_count": len(re.findall(r"\w+", text)),
    }


def build_findings(
    records: List[Dict[str, Any]],
    *,
    front_door_exists: bool,
    front_door_shelf_counts: Optional[Dict[str, int]] = None,
) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    if not front_door_exists:
        findings.append(
            {
                "id": "docs.front_door_missing",
                "severity": "error",
                "summary": "docs/README.md is missing, so agents have no canonical documentation map.",
                "paths": ["README.md"],
                "recommendation": "Restore docs/README.md before adding more roadmap or research docs.",
            }
        )


    duplicate_key_records = [record for record in records if record.get("duplicate_status_keys")]
    if duplicate_key_records:
        findings.append(
            {
                "id": "docs.duplicate_status_keys",
                "severity": "warning",
                "summary": f"{len(duplicate_key_records)} docs repeat authority metadata keys near the top of the file.",
                "paths": [record["path"] for record in duplicate_key_records[:30]],
                "recommendation": "Keep exactly one status block near the top; delete stale repeated Status/Last reviewed/Supersedes lines.",
            }
        )

    root_docs = [record for record in records if "/" not in record["path"] and record["path"] != "README.md"]
    if len(root_docs) > 8:
        findings.append(
            {
                "id": "docs.root_crowding",
                "severity": "warning",
                "summary": f"{len(root_docs)} non-README Markdown docs still live at docs/ root, so directory browsing can feel flat/noisy.",
                "paths": [record["path"] for record in root_docs[:30]],
                "recommendation": "Prefer docs/README.md as the front door; move more files only with a path-rewrite/reference-check pass.",
            }
        )

    front_door_shelf_counts = front_door_shelf_counts or {}
    wide_shelves = {shelf: count for shelf, count in front_door_shelf_counts.items() if count > 12}
    if wide_shelves:
        findings.append(
            {
                "id": "docs.wide_front_door_shelf",
                "severity": "warning",
                "summary": "One or more docs/README.md shelves are wide enough to feel like an unsorted list: "
                + ", ".join(f"{shelf}={count}" for shelf, count in sorted(wide_shelves.items())),
                "paths": ["README.md"],
                "recommendation": "Split over-wide shelves into start-here vs domain/evidence subsections before adding more top-level docs.",
            }
        )

    invalid_status = [record for record in records if record["status"] != "missing" and not record["valid_status"]]
    if invalid_status:
        findings.append(
            {
                "id": "docs.invalid_status",
                "severity": "error",
                "summary": f"{len(invalid_status)} docs use a status outside the allowed vocabulary.",
                "paths": [record["path"] for record in invalid_status[:20]],
                "recommendation": "Use one of: canonical, active, evidence-log, historical, archive-candidate.",
            }
        )

    missing_status = [record for record in records if record["missing_status_keys"]]
    if missing_status:
        findings.append(
            {
                "id": "docs.missing_status_block",
                "severity": "warning",
                "summary": f"{len(missing_status)} docs do not yet declare full authority metadata.",
                "paths": [record["path"] for record in missing_status[:30]],
                "recommendation": "Add the five-line status block from docs/README.md, starting with the largest/current docs.",
            }
        )

    unshelved = [record for record in records if record["shelf"] == "unshelved"]
    if unshelved:
        findings.append(
            {
                "id": "docs.unshelved",
                "severity": "warning",
                "summary": f"{len(unshelved)} docs are not listed or covered by docs/README.md shelves.",
                "paths": [record["path"] for record in unshelved[:30]],
                "recommendation": "Add each current doc to a shelf, or mark it archive-candidate before moving it.",
            }
        )

    return findings


def audit_docs(docs_dir: Path) -> Dict[str, Any]:
    front_door = docs_dir / "README.md"
    front_door_text = read_text(front_door) if front_door.exists() else ""
    shelves = parse_front_door_shelves(front_door_text) if front_door.exists() else {}
    shelf_item_counts = front_door_shelf_item_counts(front_door_text) if front_door.exists() else {}
    records = [analyze_doc(path, docs_dir, shelves) for path in markdown_files(docs_dir)]
    status_counts = Counter(record["status"] for record in records)
    shelf_counts = Counter(record["shelf"] for record in records)
    findings = build_findings(records, front_door_exists=front_door.exists(), front_door_shelf_counts=shelf_item_counts)
    error_count = sum(1 for finding in findings if finding["severity"] == "error")
    warning_count = sum(1 for finding in findings if finding["severity"] == "warning")
    return {
        "generated_at": utc_now(),
        "docs_dir": str(docs_dir),
        "total_markdown": len(records),
        "status_counts": dict(sorted(status_counts.items())),
        "shelf_counts": dict(sorted(shelf_counts.items())),
        "front_door_shelf_item_counts": shelf_item_counts,
        "error_count": error_count,
        "warning_count": warning_count,
        "findings": findings,
        "records": records,
        "ok": error_count == 0,
    }


def audit_repo_noise(root: Path, *, largest_limit: int = 20) -> Dict[str, Any]:
    tracked = git_tracked_paths(root)
    records: List[Dict[str, Any]] = []
    category_counts: Counter[str] = Counter()
    category_untracked_counts: Counter[str] = Counter()
    category_tracked_counts: Counter[str] = Counter()
    category_bytes: Counter[str] = Counter()

    for path in repo_markdown_files(root):
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            rel = path.as_posix()
        classification = classify_repo_markdown(rel)
        category = classification["category"]
        size = path.stat().st_size
        is_tracked = rel in tracked
        record = {
            "path": rel,
            "category": category,
            "tracked": is_tracked,
            "size_bytes": size,
            "recommendation": classification["recommendation"],
        }
        records.append(record)
        category_counts[category] += 1
        category_bytes[category] += size
        if is_tracked:
            category_tracked_counts[category] += 1
        else:
            category_untracked_counts[category] += 1

    largest_noise = [
        record
        for record in sorted(records, key=lambda item: item["size_bytes"], reverse=True)
        if record["category"] != "curated-docs"
    ][:largest_limit]
    tracked_non_doc = [
        record
        for record in records
        if record["tracked"] and record["category"] != "curated-docs"
    ]
    tracked_non_doc_counts = Counter(record["category"] for record in tracked_non_doc)
    tracked_non_doc_largest = sorted(tracked_non_doc, key=lambda item: item["size_bytes"], reverse=True)[:largest_limit]
    tracked_guidance = [
        {"category": category, "guidance": TRACKED_NON_DOC_GUIDANCE.get(category, recommendation_for_category(records, category))}
        for category in sorted(tracked_non_doc_counts)
    ]
    generated_categories = {
        "generated-hermes-profile-copies",
        "runtime-tool-source-copies",
        "oss-lab-venv-package-docs",
        "runtime-state-artifacts",
        "openclaw-runtime-memory",
        "openclaw-generated-context",
        "openclaw-dream-artifacts",
        "local-virtualenv-docs",
        "local-backup-docs",
    }
    generated_count = sum(count for category, count in category_counts.items() if category in generated_categories)
    return {
        "repo_root": str(root),
        "total_markdown": len(records),
        "tracked_markdown": sum(1 for record in records if record["tracked"]),
        "untracked_or_ignored_markdown": sum(1 for record in records if not record["tracked"]),
        "generated_or_runtime_markdown": generated_count,
        "category_counts": dict(sorted(category_counts.items())),
        "category_tracked_counts": dict(sorted(category_tracked_counts.items())),
        "category_untracked_counts": dict(sorted(category_untracked_counts.items())),
        "category_bytes": dict(sorted(category_bytes.items())),
        "largest_noise": largest_noise,
        "tracked_non_doc_markdown": len(tracked_non_doc),
        "tracked_non_doc_counts": dict(sorted(tracked_non_doc_counts.items())),
        "tracked_non_doc_largest": tracked_non_doc_largest,
        "tracked_non_doc_guidance": tracked_guidance,
        "recommendation": (
            "Treat docs/ as the curated shelf. Do not manually browse .eve/ or OpenClaw runtime logs "
            "as documentation; use Eve/OpenClaw status commands or targeted evidence paths."
        ),
    }


def recommendation_for_category(records: List[Dict[str, Any]], category: str) -> str:
    for record in records:
        if record["category"] == category:
            return str(record.get("recommendation") or "")
    return ""


def build_docs_triage(
    root: Path,
    docs_report: Optional[Dict[str, Any]] = None,
    repo_noise: Optional[Dict[str, Any]] = None,
    *,
    largest_limit: int = 12,
) -> Dict[str, Any]:
    """Build a concise, human-facing map of what is real docs vs noise.

    The full audit is useful for agents, but too much when the user is just asking
    "why does this repo feel like gibberish?"  This report keeps the answer
    non-destructive: it names the current front door, explains the noisy
    buckets, and points to safe cleanup commands without deleting evidence.
    """

    docs_dir = root / "docs"
    docs_report = docs_report or audit_docs(docs_dir)
    repo_noise = repo_noise or audit_repo_noise(root, largest_limit=largest_limit)
    category_counts = repo_noise.get("category_counts", {})
    tracked_counts = repo_noise.get("tracked_non_doc_counts", {})
    noise_reasons = [
        {
            "path": "docs/",
            "role": "curated documentation shelf",
            "count": docs_report.get("total_markdown", 0),
            "guidance": "Start at docs/README.md; do not read every file as equal authority.",
        },
        {
            "path": ".eve/**",
            "role": "runtime ledgers, generated profiles, capability-test artifacts",
            "count": sum(category_counts.get(key, 0) for key in ("runtime-state-artifacts", "generated-hermes-profile-copies", "oss-lab-venv-package-docs", "runtime-tool-source-copies")),
            "guidance": "Use Eve commands instead of browsing these files as prose documentation.",
        },
        {
            "path": "openclaw/memory/** and openclaw/context/**",
            "role": "OpenClaw runtime memory/context snapshots",
            "count": category_counts.get("openclaw-runtime-memory", 0) + category_counts.get("openclaw-generated-context", 0),
            "guidance": "Evidence only; read through OpenClaw/Eve status commands or targeted paths.",
        },
        {
            "path": ".venv*/**, vendor/**, EveBackups/**",
            "role": "dependency/reference/backup material",
            "count": category_counts.get("local-virtualenv-docs", 0) + category_counts.get("vendor-docs", 0) + category_counts.get("local-backup-docs", 0),
            "guidance": "Not authored Eve docs; consult only for dependency, upstream, or recovery work.",
        },
        {
            "path": "prompts/*.md",
            "role": "behavior-affecting prompt source",
            "count": category_counts.get("prompt-assets", 0),
            "guidance": "Important source assets, but not explanatory documentation.",
        },
        {
            "path": "openclaw/*.md, openclaw/wiki/**, openclaw/skills/**",
            "role": "OpenClaw sidecar/support docs",
            "count": category_counts.get("openclaw-sidecar-docs", 0) + category_counts.get("openclaw-memory-wiki", 0) + category_counts.get("openclaw-skills", 0),
            "guidance": "Read only when changing the body/action nervous system; canonical Eve doctrine is under docs/.",
        },
    ]
    start_here = [
        "docs/README.md",
        "docs/MASTER_ROADMAP.md",
        "docs/ROADMAP_INDEX.md",
        "docs/EVE_CORE.md",
        "docs/EXECUTIVE_SCHEDULER.md",
        "docs/SPECIALIST_SUBSTRATES.md",
    ]
    safe_commands = [
        "python3 bin/eve_docs_audit.py --triage",
        "python3 bin/eve_docs_audit.py --full --include-repo-noise",
        "python3 bin/eve_docs_retention.py --archive-hermes-profile-skills",
        "python3 eve.py eval roadmap --full",
    ]
    return {
        "generated_at": utc_now(),
        "repo_root": str(root),
        "curated_docs": docs_report.get("total_markdown", 0),
        "docs_errors": docs_report.get("error_count", 0),
        "docs_warnings": docs_report.get("warning_count", 0),
        "repo_markdown_total": repo_noise.get("total_markdown", 0),
        "tracked_markdown": repo_noise.get("tracked_markdown", 0),
        "untracked_or_ignored_markdown": repo_noise.get("untracked_or_ignored_markdown", 0),
        "generated_or_runtime_markdown": repo_noise.get("generated_or_runtime_markdown", 0),
        "tracked_non_doc_markdown": repo_noise.get("tracked_non_doc_markdown", 0),
        "tracked_non_doc_counts": dict(sorted(tracked_counts.items())),
        "start_here": start_here,
        "noise_reasons": noise_reasons,
        "largest_noise": repo_noise.get("largest_noise", [])[:largest_limit],
        "safe_cleanup_commands": safe_commands,
        "do_not_do": [
            "Do not delete historical evidence just because it reads badly.",
            "Do not promote OpenClaw memory/wiki/template files into Eve canonical doctrine.",
            "Do not treat generated runtime Markdown as roadmap, identity, or capability truth.",
        ],
    }


def format_triage_report(triage: Dict[str, Any]) -> str:
    lines = [
        "Eve docs triage",
        f"generated_at: {triage['generated_at']}",
        f"repo_root: {triage['repo_root']}",
        (
            "curated_docs: "
            f"{triage['curated_docs']} markdown file(s), "
            f"errors={triage['docs_errors']}, warnings={triage['docs_warnings']}"
        ),
        (
            "repo_markdown: "
            f"{triage['repo_markdown_total']} total, "
            f"{triage['generated_or_runtime_markdown']} generated/runtime, "
            f"{triage['tracked_non_doc_markdown']} tracked non-doc"
        ),
        "",
        "Start here:",
    ]
    for path in triage["start_here"]:
        lines.append(f"- {path}")
    lines.extend(["", "Why it feels like gibberish:"])
    for item in triage["noise_reasons"]:
        count = item.get("count", 0)
        suffix = f" ({count} markdown file(s))" if count else ""
        lines.append(f"- {item['path']}: {item['role']}{suffix}")
        lines.append(f"  guidance: {item['guidance']}")
    lines.extend(["", "Largest non-doc/noise files right now:"])
    for record in triage["largest_noise"]:
        kib = record["size_bytes"] / 1024
        tracked = "tracked" if record.get("tracked") else "untracked"
        lines.append(f"- {kib:.1f} KiB {tracked} {record['category']}: {record['path']}")
    lines.extend(["", "Safe commands:"])
    for command in triage["safe_cleanup_commands"]:
        lines.append(f"- `{command}`")
    lines.extend(["", "Do not:"])
    for warning in triage["do_not_do"]:
        lines.append(f"- {warning}")
    return "\n".join(lines)


def format_report(report: Dict[str, Any], *, full: bool = False) -> str:
    lines = [
        "Eve docs audit",
        f"generated_at: {report['generated_at']}",
        f"docs_dir: {report['docs_dir']}",
        f"total_markdown: {report['total_markdown']}",
        f"status_counts: {json.dumps(report['status_counts'], sort_keys=True)}",
        f"shelf_counts: {json.dumps(report['shelf_counts'], sort_keys=True)}",
        f"front_door_shelf_item_counts: {json.dumps(report.get('front_door_shelf_item_counts', {}), sort_keys=True)}",
        f"errors: {report['error_count']} warnings: {report['warning_count']}",
    ]
    for finding in report["findings"]:
        lines.append(f"- {finding['severity']} {finding['id']}: {finding['summary']}")
        lines.append(f"  recommendation: {finding['recommendation']}")
        if full:
            for path in finding.get("paths", []):
                lines.append(f"  path: {path}")
    repo_noise = report.get("repo_noise")
    if repo_noise:
        lines.extend(
            [
                "",
                "Repo-wide markdown noise",
                f"repo_root: {repo_noise['repo_root']}",
                f"repo_markdown_total: {repo_noise['total_markdown']}",
                f"tracked_markdown: {repo_noise['tracked_markdown']}",
                f"untracked_or_ignored_markdown: {repo_noise['untracked_or_ignored_markdown']}",
                f"generated_or_runtime_markdown: {repo_noise['generated_or_runtime_markdown']}",
                f"tracked_non_doc_markdown: {repo_noise['tracked_non_doc_markdown']}",
                f"tracked_non_doc_counts: {json.dumps(repo_noise['tracked_non_doc_counts'], sort_keys=True)}",
                f"category_counts: {json.dumps(repo_noise['category_counts'], sort_keys=True)}",
                f"recommendation: {repo_noise['recommendation']}",
            ]
        )
        if full:
            lines.append("tracked_non_doc_guidance:")
            for record in repo_noise["tracked_non_doc_guidance"]:
                lines.append(f"  {record['category']}: {record['guidance']}")
            lines.append("largest_tracked_non_doc:")
            for record in repo_noise["tracked_non_doc_largest"]:
                kib = record["size_bytes"] / 1024
                lines.append(f"  {kib:.1f} KiB {record['category']}: {record['path']}")
            lines.append("largest_noise:")
            for record in repo_noise["largest_noise"]:
                kib = record["size_bytes"] / 1024
                tracked = "tracked" if record["tracked"] else "untracked"
                lines.append(f"  {kib:.1f} KiB {tracked} {record['category']}: {record['path']}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit Eve docs authority metadata and front-door shelves.")
    parser.add_argument("--docs-dir", type=Path, default=None, help="Docs directory to audit. Defaults to ./docs from repo root.")
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    parser.add_argument("--full", action="store_true", help="Print finding paths in text mode.")
    parser.add_argument("--fail-on-warning", action="store_true", help="Exit nonzero on warnings as well as errors.")
    parser.add_argument("--include-repo-noise", action="store_true", help="Also classify repo-wide Markdown noise outside docs/.")
    parser.add_argument("--triage", action="store_true", help="Print a concise human map of curated docs vs generated/runtime noise.")
    parser.add_argument("--largest-noise", type=int, default=20, help="How many large non-doc Markdown files to show in repo-noise/triage reports.")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    root = repo_root_from()
    docs_dir = (args.docs_dir or (root / "docs")).resolve()
    report = audit_docs(docs_dir)
    if args.triage:
        repo_noise = audit_repo_noise(root, largest_limit=args.largest_noise)
        triage = build_docs_triage(root, report, repo_noise, largest_limit=args.largest_noise)
        if args.json:
            print(json.dumps(triage, indent=2, sort_keys=True))
        else:
            print(format_triage_report(triage))
    else:
        if args.include_repo_noise:
            report["repo_noise"] = audit_repo_noise(root, largest_limit=args.largest_noise)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(format_report(report, full=args.full))
    if report["error_count"]:
        return 1
    if args.fail_on_warning and report["warning_count"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
