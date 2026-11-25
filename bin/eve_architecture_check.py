#!/usr/bin/env python3
"""Executable boundaries for the new independent core, not a legacy waiver."""
import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PURE_STDLIB = {"dataclasses", "json", "typing"}
CORE_DEPENDENCIES = {
    "eve_core": set(),
    "eve_core.changes": set(),
    "eve_core.ports": set(),
    "eve_core.self_change": {"eve_core.changes", "eve_core.ports"},
    "eve_core.replies": set(),
    "eve_core.reply_ports": {"eve_core.replies"},
    "eve_core.conversation": {"eve_core.replies", "eve_core.reply_ports"},
    "eve_core.turns": set(),
    "eve_core.memory_context": set(),
    "eve_core.preflight_ports": set(),
    "eve_core.preflight": {"eve_core.turns", "eve_core.preflight_ports"},
}


def check_core(root: Path) -> list:
    issues, edges = [], {}
    package = root / "eve_core"
    if not (package / "__init__.py").is_file():
        return ["eve_core package is missing"]
    for path in sorted(package.rglob("*.py")):
        name = ".".join(path.relative_to(root).with_suffix("").parts)
        if name.endswith(".__init__"):
            name = name[:-9]
        edges[name] = set()
        if name not in CORE_DEPENDENCIES:
            issues.append(name + ": declare the new module's layer before admission")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            issues.append(f"{name}:{exc.lineno}: syntax error")
            continue
        for node in ast.walk(tree):
            imports = []
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    parent = name if path.name == "__init__.py" else name.rsplit(".", 1)[0]
                    parts = parent.split(".")
                    base = ".".join(parts[:len(parts) - node.level + 1])
                    imports = [base + "." + node.module] if node.module else [base + "." + alias.name for alias in node.names]
                else:
                    imports = [node.module or ""]
            for target in imports:
                if target.startswith("eve_core"):
                    edges[name].add(target)
                    if target not in CORE_DEPENDENCIES.get(name, set()):
                        issues.append(f"{name}:{node.lineno}: forbidden layer dependency {target}")
                elif target not in PURE_STDLIB:
                    issues.append(f"{name}:{node.lineno}: forbidden core import {target}")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"open", "__import__", "eval", "exec"}:
                issues.append(f"{name}:{node.lineno}: forbidden core effect/dynamic escape {node.func.id}")
    visited, active = set(), set()

    def visit(name):
        if name in active:
            issues.append("core import cycle through " + name)
            return
        if name in visited:
            return
        active.add(name)
        for target in sorted(edges.get(name, ())):
            visit(target)
        active.remove(name)
        visited.add(name)

    for name in sorted(edges):
        visit(name)
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    issues = check_core(ROOT)
    if args.json:
        print(json.dumps({"ok": not issues, "scope": "independent eve_core only", "issues": issues}))
    else:
        print("Independent core boundaries: " + ("PASS" if not issues else "FAIL"))
        for issue in issues:
            print(issue)
    return bool(issues)


if __name__ == "__main__":
    raise SystemExit(main())
