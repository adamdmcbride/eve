#!/usr/bin/env python3
"""Receipt writer for ``bin/eve_test_receipt.sh``.

The shell driver runs the three stages (Python 3.9 parse gate, the seven
3.9 unittest suites, the full pytest run in a scratch worktree) and hands
their logs and exit codes to this module, which parses them into one JSON
receipt plus an optional Markdown summary.

It is also importable so the parsers can be unit-tested on fixture logs::

    parse_unittest_log(text) -> dict
    parse_pytest_log(text)   -> dict

Runs under Apple /usr/bin/python3 (3.9): no 3.10+ syntax here.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

RECEIPT_SCHEMA = "eve_test_receipt/1"

_UNITTEST_RESULT_RE = re.compile(r"^(FAIL|ERROR): (\S+) \(([^)]+)\)(.*)$")
_UNITTEST_RAN_RE = re.compile(r"^Ran (\d+) tests? in ([0-9.]+)s")
_UNITTEST_STATUS_RE = re.compile(r"^(OK|FAILED)(?: \((.*)\))?\s*$")
_PYTEST_FAILED_RE = re.compile(r"^(FAILED|ERROR) (\S+)(?: - (.*))?$")
_PYTEST_SUMMARY_TOKEN_RE = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?)\b")
_PYTEST_SUMMARY_LINE_RE = re.compile(r"^=*\s*(?:(?:\d+ \w+(?:, )?)+) in [0-9.]+s(?: \([^)]*\))?\s*=*$")
_PYTEST_NO_TESTS_RE = re.compile(r"^(?:=+ )?no tests ran in [0-9.]+s")


def utc_stamp(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y%m%dT%H%M%SZ")


def utc_iso(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _unittest_test_id(name: str, qualifier: str) -> str:
    # Python 3.9 prints "test_x (pkg.mod.Class)"; 3.11+ prints
    # "test_x (pkg.mod.Class.test_x)". Normalise to pkg.mod.Class.test_x.
    if qualifier.endswith("." + name):
        return qualifier
    return "%s.%s" % (qualifier, name)


def parse_unittest_log(text: str) -> Dict[str, object]:
    """Parse ``python -m unittest`` output (stdout+stderr combined)."""
    failing: List[Dict[str, str]] = []
    seen = set()
    ran = 0
    duration = 0.0
    status = None  # type: Optional[str]
    counts = {"failures": 0, "errors": 0, "skipped": 0, "expected_failures": 0, "unexpected_successes": 0}
    key_map = {
        "failures": "failures",
        "errors": "errors",
        "skipped": "skipped",
        "expected failures": "expected_failures",
        "unexpected successes": "unexpected_successes",
    }
    for raw in text.splitlines():
        line = raw.rstrip()
        match = _UNITTEST_RESULT_RE.match(line)
        if match:
            kind, name, qualifier, extra = match.groups()
            test_id = _unittest_test_id(name, qualifier)
            label = test_id + (extra.strip() and " " + extra.strip() or "")
            if label not in seen:
                seen.add(label)
                failing.append({"id": test_id, "kind": kind, "detail": extra.strip()})
            continue
        match = _UNITTEST_RAN_RE.match(line)
        if match:
            ran += int(match.group(1))
            duration += float(match.group(2))
            continue
        match = _UNITTEST_STATUS_RE.match(line)
        if match:
            status = match.group(1)
            details = match.group(2) or ""
            for part in details.split(","):
                part = part.strip()
                if "=" not in part:
                    continue
                key, _, value = part.partition("=")
                key = key.strip()
                if key in key_map and value.strip().isdigit():
                    counts[key_map[key]] += int(value.strip())
    passed = max(ran - counts["failures"] - counts["errors"] - counts["skipped"], 0)
    return {
        "status_line": status,
        "ran": ran,
        "passed": passed,
        "failures": counts["failures"],
        "errors": counts["errors"],
        "skipped": counts["skipped"],
        "expected_failures": counts["expected_failures"],
        "unexpected_successes": counts["unexpected_successes"],
        "duration_seconds": round(duration, 3),
        "failing": failing,
        "failing_ids": [item["id"] for item in failing],
    }


def parse_pytest_log(text: str) -> Dict[str, object]:
    """Parse ``pytest -q -rfE`` output."""
    failing: List[Dict[str, str]] = []
    seen = set()
    counts = {
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "xfailed": 0,
        "xpassed": 0,
        "deselected": 0,
        "warnings": 0,
    }
    summary_line = None  # type: Optional[str]
    for raw in text.splitlines():
        line = raw.strip()
        match = _PYTEST_FAILED_RE.match(line)
        if match:
            kind, node_id, detail = match.groups()
            if node_id not in seen:
                seen.add(node_id)
                failing.append({"id": node_id, "kind": kind, "detail": (detail or "").strip()})
            continue
        if _PYTEST_NO_TESTS_RE.match(line):
            summary_line = line.strip("= ").strip()
            continue
        if _PYTEST_SUMMARY_LINE_RE.match(line):
            summary_line = line.strip("= ").strip()
            for value, key in _PYTEST_SUMMARY_TOKEN_RE.findall(line):
                if key in ("error", "errors"):
                    key = "errors"
                elif key in ("warning", "warnings"):
                    key = "warnings"
                counts[key] = int(value)
    total = counts["passed"] + counts["failed"] + counts["errors"] + counts["skipped"] + counts["xfailed"] + counts["xpassed"]
    return {
        "summary_line": summary_line,
        "total": total,
        "passed": counts["passed"],
        "failed": counts["failed"],
        "errors": counts["errors"],
        "skipped": counts["skipped"],
        "xfailed": counts["xfailed"],
        "xpassed": counts["xpassed"],
        "deselected": counts["deselected"],
        "warnings": counts["warnings"],
        "failing": failing,
        "failing_ids": [item["id"] for item in failing],
    }


def _read_text(path: Optional[str]) -> str:
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _tail(text: str, lines: int = 40) -> List[str]:
    return text.splitlines()[-lines:]


def build_receipt(args: argparse.Namespace) -> Dict[str, object]:
    now = datetime.now(timezone.utc)
    stamp = args.stamp or utc_stamp(now)

    parse_text = _read_text(args.parse_json)
    parse_payload = {}  # type: Dict[str, object]
    try:
        parse_payload = json.loads(parse_text) if parse_text.strip() else {}
    except ValueError:
        parse_payload = {}
    parse_ok = args.parse_exit == 0 and bool(parse_payload.get("ok", args.parse_exit == 0))
    parse_gate = {
        "ok": parse_ok,
        "exit_code": args.parse_exit,
        "interpreter": parse_payload.get("interpreter", args.interpreter),
        "python_version": parse_payload.get("python_version"),
        "files_checked": parse_payload.get("files_checked"),
        "errors": [str(item.get("display") or item) for item in parse_payload.get("errors", [])],
        "log": args.parse_json,
    }

    unittest_text = _read_text(args.unittest_log)
    unittest_parsed = parse_unittest_log(unittest_text)
    unittest_stage = dict(unittest_parsed)
    unittest_stage.update(
        {
            "ok": args.unittest_exit == 0 and unittest_parsed["failures"] == 0 and unittest_parsed["errors"] == 0,
            "exit_code": args.unittest_exit,
            "interpreter": args.interpreter,
            "suites": list(args.suites or []),
            "log": args.unittest_log,
            "log_tail": _tail(unittest_text),
        }
    )

    if args.pytest_skipped is not None:
        pytest_stage = {
            "status": "skipped",
            "ok": None,
            "reason": args.pytest_skipped,
            "total": None,
            "passed": None,
            "failed": None,
            "errors": None,
            "failing_ids": [],
        }  # type: Dict[str, object]
    else:
        pytest_text = _read_text(args.pytest_log)
        pytest_parsed = parse_pytest_log(pytest_text)
        pytest_stage = dict(pytest_parsed)
        pytest_stage.update(
            {
                "status": "ran",
                "ok": args.pytest_exit == 0,
                "exit_code": args.pytest_exit,
                "interpreter": args.pytest_python,
                "worktree": args.pytest_worktree,
                "worktree_head": args.pytest_head,
                "runtime_dir": args.pytest_runtime_dir,
                "log": args.pytest_log,
                "log_tail": _tail(pytest_text),
            }
        )

    stages_ok = [parse_gate["ok"], unittest_stage["ok"]]
    if pytest_stage["status"] == "ran":
        stages_ok.append(bool(pytest_stage["ok"]))
    overall_ok = all(stages_ok)

    return {
        "schema": RECEIPT_SCHEMA,
        "stamp": stamp,
        "generated_at_utc": utc_iso(now),
        "started_at_utc": args.started_at,
        "root": args.root,
        "git": {"head": args.git_head, "branch": args.git_branch, "dirty": bool(args.dirty)},
        "overall_ok": overall_ok,
        "parse_gate": parse_gate,
        "unittest_py39": unittest_stage,
        "pytest_full": pytest_stage,
    }


def render_markdown(receipt: Dict[str, object]) -> str:
    git = receipt["git"]  # type: ignore[index]
    parse_gate = receipt["parse_gate"]  # type: ignore[index]
    unit = receipt["unittest_py39"]  # type: ignore[index]
    pyt = receipt["pytest_full"]  # type: ignore[index]

    def flag(value: object) -> str:
        if value is None:
            return "skipped"
        return "pass" if value else "FAIL"

    lines = []  # type: List[str]
    lines.append("# Eve test receipt %s" % receipt["stamp"])
    lines.append("")
    lines.append("- Generated: %s (UTC)" % receipt["generated_at_utc"])
    lines.append("- Git: `%s` on `%s`%s" % (git["head"], git["branch"], " (dirty)" if git["dirty"] else ""))  # type: ignore[index]
    lines.append("- Overall: **%s**" % ("PASS" if receipt["overall_ok"] else "FAIL"))
    lines.append("")
    lines.append("| Stage | Result | Detail |")
    lines.append("|---|---|---|")
    lines.append(
        "| Python 3.9 parse gate | %s | %s files parsed with %s, %d error(s) |"
        % (flag(parse_gate["ok"]), parse_gate.get("files_checked"), parse_gate.get("python_version") or parse_gate.get("interpreter"), len(parse_gate["errors"]))  # type: ignore[index]
    )
    lines.append(
        "| unittest (3.9, %d suites) | %s | ran %s, failures %s, errors %s, skipped %s |"
        % (len(unit["suites"]), flag(unit["ok"]), unit["ran"], unit["failures"], unit["errors"], unit["skipped"])  # type: ignore[index]
    )
    if pyt["status"] == "ran":  # type: ignore[index]
        lines.append(
            "| pytest (full, worktree) | %s | %s |" % (flag(pyt["ok"]), pyt.get("summary_line") or "no summary line found")  # type: ignore[index]
        )
    else:
        lines.append("| pytest (full, worktree) | skipped | %s |" % pyt.get("reason"))  # type: ignore[index]
    lines.append("")
    if parse_gate["errors"]:  # type: ignore[index]
        lines.append("## Parse errors")
        lines.append("")
        for item in parse_gate["errors"]:  # type: ignore[index]
            lines.append("- `%s`" % item)
        lines.append("")
    if unit["failing_ids"]:  # type: ignore[index]
        lines.append("## unittest failures")
        lines.append("")
        for item in unit["failing"]:  # type: ignore[index]
            lines.append("- %s `%s`" % (item["kind"], item["id"]))
        lines.append("")
    if pyt["status"] == "ran" and pyt["failing_ids"]:  # type: ignore[index]
        lines.append("## pytest failures")
        lines.append("")
        for item in pyt["failing"]:  # type: ignore[index]
            detail = item.get("detail") or ""
            lines.append("- %s `%s`%s" % (item["kind"], item["id"], (" - " + detail) if detail else ""))
        lines.append("")
    if pyt["status"] == "ran":  # type: ignore[index]
        lines.append("Worktree: `%s` at `%s`, `EVE_RUNTIME_DIR=%s`" % (pyt.get("worktree"), pyt.get("worktree_head"), pyt.get("runtime_dir")))  # type: ignore[index]
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="write the JSON receipt for eve_test_receipt.sh")
    parser.add_argument("--receipt-dir", required=True)
    parser.add_argument("--md", default=None, help="optional Markdown summary path")
    parser.add_argument("--stamp", default=None, help="UTC stamp used for the receipt file name")
    parser.add_argument("--started-at", default=None)
    parser.add_argument("--root", default=None)
    parser.add_argument("--git-head", default=None)
    parser.add_argument("--git-branch", default=None)
    parser.add_argument("--dirty", type=int, default=0)
    parser.add_argument("--interpreter", default="/usr/bin/python3")
    parser.add_argument("--parse-json", default=None)
    parser.add_argument("--parse-exit", type=int, default=1)
    parser.add_argument("--unittest-log", default=None)
    parser.add_argument("--unittest-exit", type=int, default=1)
    parser.add_argument("--suites", nargs="*", default=[])
    parser.add_argument("--pytest-skipped", default=None, help="reason the full pytest stage did not run")
    parser.add_argument("--pytest-log", default=None)
    parser.add_argument("--pytest-exit", type=int, default=1)
    parser.add_argument("--pytest-python", default=None)
    parser.add_argument("--pytest-worktree", default=None)
    parser.add_argument("--pytest-head", default=None)
    parser.add_argument("--pytest-runtime-dir", default=None)
    args = parser.parse_args(argv)

    receipt = build_receipt(args)
    receipt_dir = Path(args.receipt_dir)
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / ("%s.json" % receipt["stamp"])
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("receipt: %s" % receipt_path)
    if args.md:
        md_path = Path(args.md)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(render_markdown(receipt), encoding="utf-8")
        print("markdown: %s" % md_path)
    print("overall: %s" % ("PASS" if receipt["overall_ok"] else "FAIL"))
    return 0 if receipt["overall_ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
