#!/usr/bin/env python3
"""Usage census: for every function in Eve, is it reachable, does it run, is it hers?

Static half: parse every module, build a name-reference graph, and walk it from the real entry
points (the daemon cycle, the reply path, the workspace tick, the free run, the self-change cycle,
the HTTP service, the app server, the CLI commands, the bin scripts). Each function lands in one class:

  runtime     reachable from something that runs on its own (daemon, reply, HTTP, app)
  cli         reachable only from a CLI command or a bin script (used on request)
  tests_only  referenced only from tests
  orphan      referenced by nothing

Dynamic half: merge .eve/function_usage/*.json written by eve_usage_trace (stack samples from the
living processes) so each function also carries how often it was actually on a stack.

Output: docs/architecture/usage_census/census.json, census.csv and census.md. Read-only; never edits code.
"""
from __future__ import annotations

import ast
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "architecture" / "usage_census"
SKIP_DIRS = {"tests", "vendor", "EveBackups", "build", "__pycache__", ".pytest_cache", "dagster_lab", "experiments", "wiki", "openclaw", "data", "reviews", "design", "mac", "web", "go", "rust", "script", "launchd", "models", "memory", "coordination", "docs"}
RUNTIME_ROOTS = {
    "eve.py": ["run_daemon_cycle", "cmd_daemon_run", "_run_owned_daemon", "generate_eve_reply", "refresh_global_workspace", "run_autonomy_free_run_session", "run_self_change_cycle", "run_mind_tick", "generate_continuous_thought", "generate_eve_outreach", "suggest_proposal", "run_presence_cycle", "collect_runtime_sensory_events", "spawn_daemon_successor", "cmd_app", "run_eve_coder_agent", "execute_capability_tool", "run_operational_action_tree"],
    "eve_web.py": ["*"],
    "eve_consciousness.py": ["build_conscious_state", "complete_cycle"],
    "eve_sensory.py": ["build_frame", "normalize_event"],
}
CLI_ROOT_PATTERN = re.compile(r"^cmd_[a-z0-9_]+$")


def iter_modules() -> List[Path]:
    files = [p for p in ROOT.glob("*.py")]
    files += list((ROOT / "eve_commands").glob("*.py"))
    files += [p for p in (ROOT / "bin").glob("*.py")]
    return sorted(p for p in files if not any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts))


class Definition:
    __slots__ = ("module", "name", "qualname", "line", "end", "kind", "refs", "is_test_ref", "reachable", "samples")

    def __init__(self, module: str, name: str, qualname: str, line: int, end: int, kind: str):
        self.module, self.name, self.qualname, self.line, self.end, self.kind = module, name, qualname, line, end, kind
        self.refs: Set[str] = set()
        self.reachable = "orphan"
        self.samples = 0


def collect(paths: List[Path]) -> Tuple[Dict[str, Definition], Dict[str, Set[str]], Set[str]]:
    """Return definitions keyed by module::qualname, the reference graph, and names referenced by tests."""
    defs: Dict[str, Definition] = {}
    by_name: Dict[str, List[str]] = defaultdict(list)
    module_trees: Dict[str, ast.Module] = {}
    for path in paths:
        module = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        module_trees[module] = tree
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                key = f"{module}::{node.name}"
                defs[key] = Definition(module, node.name, node.name, node.lineno, getattr(node, "end_lineno", node.lineno), "function")
                by_name[node.name].append(key)
            elif isinstance(node, ast.ClassDef):
                key = f"{module}::{node.name}"
                defs[key] = Definition(module, node.name, node.name, node.lineno, getattr(node, "end_lineno", node.lineno), "class")
                by_name[node.name].append(key)
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        skey = f"{module}::{node.name}.{sub.name}"
                        defs[skey] = Definition(module, sub.name, f"{node.name}.{sub.name}", sub.lineno, getattr(sub, "end_lineno", sub.lineno), "method")
                        by_name[sub.name].append(skey)
    graph: Dict[str, Set[str]] = defaultdict(set)

    def resolve(module: str, name: str, attr_base: str = "") -> List[str]:
        candidates = by_name.get(name, [])
        if not candidates:
            return []
        if attr_base:
            base_module = attr_base + ".py" if not attr_base.endswith(".py") else attr_base
            scoped = [c for c in candidates if c.startswith(base_module + "::")]
            if scoped:
                return scoped
        same = [c for c in candidates if c.startswith(module + "::")]
        if same:
            return same
        # Cross-module by bare name only when the name is unique in the codebase (or lives in eve.py,
        # the facade every module imports); otherwise a bare `main` in a bin script would look reachable.
        if len(candidates) == 1:
            return candidates
        facade = [c for c in candidates if c.startswith("eve.py::")]
        return facade

    for module, tree in module_trees.items():
        # module-level references (dispatch tables, decorators, constants) count as reachable from the module itself
        for node in tree.body:
            owner = f"{module}::<module>"
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                owner = f"{module}::{node.name}"
            for sub in ast.walk(node):
                if isinstance(sub, ast.ImportFrom) and sub.module:
                    for alias in sub.names:
                        for target in resolve(module, alias.name, attr_base=sub.module.split(".")[-1]):
                            graph[owner].add(target)
                if isinstance(sub, ast.Name):
                    for target in resolve(module, sub.id):
                        if target != owner:
                            graph[owner].add(target)
                elif isinstance(sub, ast.Attribute):
                    base = sub.value.id if isinstance(sub.value, ast.Name) else ""
                    for target in resolve(module, sub.attr, attr_base=base):
                        if target != owner:
                            graph[owner].add(target)
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        mkey = f"{module}::{node.name}.{sub.name}"
                        graph[f"{module}::{node.name}"].add(mkey)
                        for inner in ast.walk(sub):
                            if isinstance(inner, ast.Name):
                                for target in resolve(module, inner.id):
                                    graph[mkey].add(target)
                            elif isinstance(inner, ast.Attribute):
                                base = inner.value.id if isinstance(inner.value, ast.Name) else ""
                                for target in resolve(module, inner.attr, attr_base=base):
                                    graph[mkey].add(target)
    lab = Path.home() / "Documents" / "eve-fly"
    for path in lab.glob("*.py") if lab.exists() else []:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        owner = f"lab/{path.name}::<module>"
        for sub in ast.walk(tree):
            if isinstance(sub, ast.ImportFrom) and sub.module:
                for alias in sub.names:
                    for target in resolve("lab", alias.name, attr_base=sub.module.split(".")[-1]):
                        graph[owner].add(target)
            elif isinstance(sub, ast.Attribute):
                base = sub.value.id if isinstance(sub.value, ast.Name) else ""
                if base.startswith("eve_"):
                    for target in resolve("lab", sub.attr, attr_base=base):
                        graph[owner].add(target)
    test_refs: Set[str] = set()
    for path in (ROOT / "tests").glob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for sub in ast.walk(tree):
            if isinstance(sub, ast.Attribute):
                base = sub.value.id if isinstance(sub.value, ast.Name) else ""
                test_refs.update(resolve("tests", sub.attr, attr_base=base))
            elif isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub.value in by_name:
                test_refs.update(by_name[sub.value])  # patch.object(eve, "name")
    return defs, graph, test_refs


def walk(graph: Dict[str, Set[str]], roots: List[str]) -> Set[str]:
    seen: Set[str] = set()
    stack = list(roots)
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(graph.get(node, ()))
    return seen


def load_dynamic() -> Dict[Tuple[str, str, int], int]:
    counts: Dict[Tuple[str, str, int], int] = defaultdict(int)
    for path in (ROOT / ".eve" / "function_usage").glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for row in payload.get("functions") or []:
            counts[(str(row.get("file")), str(row.get("function")), int(row.get("line") or 0))] += int(row.get("samples") or row.get("calls") or 0)
    return counts


def main() -> int:
    paths = iter_modules()
    defs, graph, test_refs = collect(paths)
    runtime_roots: List[str] = []
    for module, names in RUNTIME_ROOTS.items():
        for name in names:
            if name == "*":
                runtime_roots.extend(k for k in defs if k.startswith(module + "::"))
            elif f"{module}::{name}" in defs:
                runtime_roots.append(f"{module}::{name}")
    runtime_roots += [f"{m}::<module>" for m in {d.module for d in defs.values()} if m in ("eve.py", "eve_web.py", "bin/eve_app_server.py", "eve_commands/parser.py")]
    runtime_roots += [k for k in graph if k.startswith("lab/")]
    cli_roots = [k for k, d in defs.items() if d.module == "eve.py" and CLI_ROOT_PATTERN.match(d.name)]
    cli_roots += [f"{m}::<module>" for m in {d.module for d in defs.values()} if m.startswith("bin/") or m.startswith("eve_commands/")]
    runtime = walk(graph, runtime_roots)
    cli = walk(graph, cli_roots)
    dynamic = load_dynamic()
    for key, d in defs.items():
        if key in runtime:
            d.reachable = "runtime"
        elif key in cli:
            d.reachable = "cli"
        elif key in test_refs:
            d.reachable = "tests_only"
        else:
            d.reachable = "orphan"
        d.samples = dynamic.get((d.module, d.name, d.line), 0)
        if not d.samples:
            # Edits move line numbers under a long-running sampler; match by name and take the nearest line.
            near = [(abs(ln - d.line), c) for (f, fn, ln), c in dynamic.items() if f == d.module and fn == d.name]
            if near:
                d.samples = sum(c for dist, c in near if dist <= 400) or min(near)[1]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = [{"module": d.module, "qualname": d.qualname, "kind": d.kind, "line": d.line, "lines": d.end - d.line + 1, "reachable": d.reachable, "samples": d.samples, "test_referenced": key in test_refs} for key, d in sorted(defs.items(), key=lambda kv: (kv[1].module, kv[1].line))]
    (OUT_DIR / "census.json").write_text(json.dumps({"generated_from": str(ROOT), "definitions": rows, "dynamic_files": len(list((ROOT / '.eve' / 'function_usage').glob('*.json')))}, indent=1), encoding="utf-8")
    with (OUT_DIR / "census.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader(); writer.writerows(rows)
    per_module: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        m = per_module[r["module"]]
        m["definitions"] += 1; m["lines"] += r["lines"]; m[r["reachable"]] += 1
        if r["samples"]:
            m["observed"] += 1
        if r["reachable"] in ("orphan", "tests_only"):
            m["dead_lines"] += r["lines"]
    total = len(rows); obs = sum(1 for r in rows if r["samples"])
    lines = ["# Usage census", "", f"Definitions: {total}. Reachable from runtime: {sum(1 for r in rows if r['reachable']=='runtime')}. CLI or bin only: {sum(1 for r in rows if r['reachable']=='cli')}. Tests only: {sum(1 for r in rows if r['reachable']=='tests_only')}. Orphans: {sum(1 for r in rows if r['reachable']=='orphan')}. Observed on a live stack so far: {obs}.", "", "Static reachability is by name reference, so dynamic dispatch through dicts and strings is counted as a reference when the name appears; a function can be 'runtime' and still never run. The `samples` column is the living evidence.", "", "| Module | Defs | Lines | Runtime | CLI-only | Tests-only | Orphan | Observed | Dead lines |", "|---|---|---|---|---|---|---|---|---|"]
    for module, m in sorted(per_module.items(), key=lambda kv: -kv[1]["lines"]):
        lines.append(f"| {module} | {m['definitions']} | {m['lines']} | {m['runtime']} | {m['cli']} | {m['tests_only']} | {m['orphan']} | {m['observed']} | {m['dead_lines']} |")
    lines += ["", "## Largest orphans and tests-only definitions", "", "| Module | Definition | Lines | Class |", "|---|---|---|---|"]
    for r in sorted((r for r in rows if r["reachable"] in ("orphan", "tests_only")), key=lambda r: -r["lines"])[:80]:
        lines.append(f"| {r['module']} | {r['qualname']} | {r['lines']} | {r['reachable']} |")
    (OUT_DIR / "census.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(lines[2])
    print(f"wrote {OUT_DIR}/census.json, census.csv, census.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
