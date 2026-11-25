#!/usr/bin/env python3
"""Generate the facade pin fixture for the strangler harness (program task 0.3).

The fixture ``tests/fixtures/eve_facade_pins.txt`` lists, one per line and
sorted, every name the rest of the repository expects to find on the ``eve``
module. Four sources feed it, all read statically (this script never imports
``eve``):

1. ``patch.object(eve, "<name>")`` / ``patch("eve.<name>")`` /
   ``patch.multiple(eve, <name>=...)`` targets in ``tests/``;
2. every distinct ``eve.<name>`` attribute reference in ``tests/``;
3. ``HANDLER_NAMES`` and ``SETTING_NAMES`` in ``eve_commands/parser.py``;
4. every ``globals().get("<name>")`` lookup in ``eve.py``.

``tests/test_facade_pins.py`` asserts ``hasattr(eve, name)`` for each line and
that the fixture is up to date, so any extraction that drops a name from the
facade fails loudly before it can reach the daemon.

Usage::

    python3 bin/eve_facade_pins.py            # write the fixture, print counts
    python3 bin/eve_facade_pins.py --check    # exit 1 with a diff when stale
    python3 bin/eve_facade_pins.py --stats    # counts per source as JSON

Python 3.9 compatible (the daemon interpreter); stdlib only.
"""
import argparse
import ast
import difflib
import json
import os
import re
import sys
from typing import Dict, Iterable, List, Optional, Set

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_RELPATH = os.path.join("tests", "fixtures", "eve_facade_pins.txt")
PARSER_RELPATH = os.path.join("eve_commands", "parser.py")
PARSER_LIST_NAMES = ("HANDLER_NAMES", "SETTING_NAMES")
FACADE_MODULE = "eve"

SOURCE_KEYS = (
    "patch_targets",
    "attribute_references",
    "handler_names",
    "setting_names",
    "globals_lookups",
)

_EVE_DOTTED = re.compile(r"^eve\.([A-Za-z_][A-Za-z0-9_]*)")


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _parse(path: str) -> ast.AST:
    return ast.parse(_read(path), filename=path)


def iter_python_files(directory: str) -> Iterable[str]:
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for filename in sorted(filenames):
            if filename.endswith(".py"):
                yield os.path.join(dirpath, filename)


def _is_patch_callable(func: ast.AST) -> bool:
    """True for ``patch`` and ``mock.patch`` (any dotted prefix)."""
    if isinstance(func, ast.Name):
        return func.id == "patch"
    if isinstance(func, ast.Attribute):
        return func.attr == "patch"
    return False


def _patch_method(func: ast.AST) -> Optional[str]:
    """Return "object"/"multiple"/"dict" for ``patch.<method>`` calls."""
    if isinstance(func, ast.Attribute) and func.attr in ("object", "multiple", "dict"):
        if _is_patch_callable(func.value):
            return func.attr
    return None


def _is_eve_name(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == FACADE_MODULE


def _string_value(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def collect_patch_targets(tree: ast.AST) -> Set[str]:
    names = set()  # type: Set[str]
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        method = _patch_method(node.func)
        if method == "object":
            if len(node.args) >= 2 and _is_eve_name(node.args[0]):
                value = _string_value(node.args[1])
                if value:
                    names.add(value)
        elif method == "multiple":
            if node.args and _is_eve_name(node.args[0]):
                for keyword in node.keywords:
                    if keyword.arg:
                        names.add(keyword.arg)
        elif method == "dict" or _is_patch_callable(node.func):
            if node.args:
                value = _string_value(node.args[0])
                if value:
                    match = _EVE_DOTTED.match(value)
                    if match:
                        names.add(match.group(1))
    return names


def collect_attribute_references(tree: ast.AST) -> Set[str]:
    names = set()  # type: Set[str]
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and _is_eve_name(node.value):
            names.add(node.attr)
    return names


def collect_parser_lists(parser_path: str) -> Dict[str, List[str]]:
    tree = _parse(parser_path)
    found = {}  # type: Dict[str, List[str]]
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in PARSER_LIST_NAMES:
            continue
        if not isinstance(node.value, (ast.Tuple, ast.List)):
            raise ValueError("%s: %s is not a literal sequence" % (parser_path, target.id))
        values = []
        for element in node.value.elts:
            value = _string_value(element)
            if value is None:
                raise ValueError("%s: %s holds a non-string element" % (parser_path, target.id))
            values.append(value)
        found[target.id] = values
    missing = [name for name in PARSER_LIST_NAMES if name not in found]
    if missing:
        raise ValueError("%s: missing %s" % (parser_path, ", ".join(missing)))
    return found


def collect_globals_lookups(tree: ast.AST) -> Set[str]:
    names = set()  # type: Set[str]
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "get"):
            continue
        receiver = func.value
        if not (
            isinstance(receiver, ast.Call)
            and isinstance(receiver.func, ast.Name)
            and receiver.func.id == "globals"
            and not receiver.args
        ):
            continue
        if node.args:
            value = _string_value(node.args[0])
            if value:
                names.add(value)
    return names


def collect_sources(root: str = ROOT) -> Dict[str, Set[str]]:
    """Return the pinned names grouped by source key."""
    sources = {key: set() for key in SOURCE_KEYS}  # type: Dict[str, Set[str]]
    tests_dir = os.path.join(root, "tests")
    for path in iter_python_files(tests_dir):
        tree = _parse(path)
        sources["patch_targets"].update(collect_patch_targets(tree))
        sources["attribute_references"].update(collect_attribute_references(tree))
    lists = collect_parser_lists(os.path.join(root, PARSER_RELPATH))
    sources["handler_names"].update(lists["HANDLER_NAMES"])
    sources["setting_names"].update(lists["SETTING_NAMES"])
    sources["globals_lookups"].update(collect_globals_lookups(_parse(os.path.join(root, "eve.py"))))
    return sources


def pinned_names(root: str = ROOT, sources: Optional[Dict[str, Set[str]]] = None) -> List[str]:
    if sources is None:
        sources = collect_sources(root)
    union = set()  # type: Set[str]
    for names in sources.values():
        union.update(names)
    return sorted(union)


def render(names: Iterable[str]) -> str:
    return "".join(name + "\n" for name in sorted(set(names)))


def parse_fixture(text: str) -> List[str]:
    """Names from fixture text; blank lines and ``#`` comments are ignored."""
    names = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.append(line)
    return names


def read_fixture(root: str = ROOT, path: Optional[str] = None) -> List[str]:
    if path is None:
        path = os.path.join(root, FIXTURE_RELPATH)
    return parse_fixture(_read(path))


def fixture_diff(current: Iterable[str], expected: Iterable[str]) -> str:
    return "".join(
        difflib.unified_diff(
            [n + "\n" for n in current],
            [n + "\n" for n in expected],
            fromfile="fixture (on disk)",
            tofile="fixture (regenerated)",
        )
    )


def stats(sources: Dict[str, Set[str]]) -> Dict[str, int]:
    counts = {key: len(sources[key]) for key in SOURCE_KEYS}
    counts["pinned"] = len(pinned_names(sources=sources))
    return counts


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=ROOT, help="repository root (default: this checkout)")
    parser.add_argument("--output", default=None, help="fixture path (default: tests/fixtures/eve_facade_pins.txt)")
    parser.add_argument("--check", action="store_true", help="do not write; exit 1 with a diff when the fixture is stale")
    parser.add_argument("--stats", action="store_true", help="print per-source counts as JSON and exit")
    args = parser.parse_args(argv)

    root = os.path.abspath(args.root)
    output = args.output or os.path.join(root, FIXTURE_RELPATH)
    sources = collect_sources(root)
    names = pinned_names(root, sources)
    counts = stats(sources)

    if args.stats:
        print(json.dumps(counts, indent=2, sort_keys=True))
        return 0

    if args.check:
        if not os.path.exists(output):
            print("facade pins: fixture missing at %s" % output)
            return 1
        current = read_fixture(path=output)
        if current == names:
            print("facade pins: fixture up to date (%d names)" % len(names))
            return 0
        sys.stdout.write(fixture_diff(current, names))
        print("facade pins: fixture stale (%d on disk, %d regenerated)" % (len(current), len(names)))
        return 1

    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w", encoding="utf-8") as handle:
        handle.write(render(names))
    print("facade pins: wrote %d names to %s" % (len(names), os.path.relpath(output, root)))
    for key in SOURCE_KEYS:
        print("  %-22s %5d" % (key, counts[key]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
