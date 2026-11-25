#!/usr/bin/env python3
"""Python 3.9 parse gate for Eve's first-party sources.

Runs ``ast.parse`` over every first-party Python file using the interpreter
this script is executed with. The daemon runs on Apple ``/usr/bin/python3``
(3.9.6), so the gate is meant to be invoked as::

    /usr/bin/python3 bin/eve_py39_parse_check.py

A file that only parses under 3.10+ (``match`` statements, ``X | Y`` in
annotations evaluated at import, parenthesised context managers, ...) is
reported as ``path:line: SyntaxError: message`` and the script exits 1.

Coverage (relative to the checkout root):

* ``eve.py``
* ``eve_*.py``
* ``eve_commands/**/*.py``
* ``bin/*.py``
* ``tests/*.py``

``vendor/``, ``.venv*``, ``EveBackups/``, ``build/``, ``.build/`` and any
``__pycache__`` directory are never scanned. Read-only: nothing is written.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

SKIP_DIR_NAMES = ("vendor", "EveBackups", "build", ".build", "__pycache__")
SKIP_DIR_PREFIXES = (".venv",)


def default_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _skipped(path: Path, root: Path) -> bool:
    try:
        rel_parts = path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        rel_parts = path.parts
    for part in rel_parts[:-1]:
        if part in SKIP_DIR_NAMES:
            return True
        if any(part.startswith(prefix) for prefix in SKIP_DIR_PREFIXES):
            return True
    return False


def collect_first_party_files(root: Optional[Path] = None) -> List[Path]:
    """Return the first-party Python files under ``root`` in a stable order."""
    root = (root or default_root()).resolve()
    candidates: List[Path] = []
    eve_py = root / "eve.py"
    if eve_py.is_file():
        candidates.append(eve_py)
    candidates.extend(sorted(root.glob("eve_*.py")))
    commands_dir = root / "eve_commands"
    if commands_dir.is_dir():
        candidates.extend(sorted(commands_dir.rglob("*.py")))
    bin_dir = root / "bin"
    if bin_dir.is_dir():
        candidates.extend(sorted(bin_dir.glob("*.py")))
    tests_dir = root / "tests"
    if tests_dir.is_dir():
        candidates.extend(sorted(tests_dir.glob("*.py")))
    seen = set()
    files: List[Path] = []
    for path in candidates:
        if not path.is_file() or _skipped(path, root):
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        files.append(path)
    return files


def parse_one(path: Path, feature_version: Optional[Sequence[int]] = None) -> Optional[Dict[str, object]]:
    """Parse ``path``; return ``None`` on success or an error record."""
    try:
        source = path.read_bytes()
    except OSError as exc:
        return {"file": str(path), "line": 0, "column": 0, "message": "unreadable: %s" % exc}
    try:
        if feature_version is not None:
            ast.parse(source, filename=str(path), feature_version=tuple(feature_version))
        else:
            ast.parse(source, filename=str(path))
    except SyntaxError as exc:  # covers IndentationError and TabError too
        return {
            "file": str(path),
            "line": int(exc.lineno or 0),
            "column": int(exc.offset or 0),
            "message": "%s: %s" % (type(exc).__name__, exc.msg),
        }
    except ValueError as exc:  # e.g. null bytes in source
        return {"file": str(path), "line": 0, "column": 0, "message": "ValueError: %s" % exc}
    return None


def check_files(files: Iterable[Path], feature_version: Optional[Sequence[int]] = None) -> List[Dict[str, object]]:
    errors: List[Dict[str, object]] = []
    for path in files:
        record = parse_one(path, feature_version)
        if record is not None:
            errors.append(record)
    return errors


def format_error(record: Dict[str, object], root: Optional[Path] = None) -> str:
    file_text = str(record["file"])
    if root is not None:
        try:
            file_text = str(Path(file_text).resolve().relative_to(root.resolve()))
        except ValueError:
            pass
    return "%s:%s: %s" % (file_text, record["line"], record["message"])


def _parse_feature_version(text: str) -> Sequence[int]:
    parts = text.strip().split(".")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise argparse.ArgumentTypeError("feature version must look like 3.9")
    return (int(parts[0]), int(parts[1]))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=None, help="checkout root (default: parent of bin/)")
    parser.add_argument(
        "--feature-version",
        type=_parse_feature_version,
        default=None,
        help="best-effort grammar pin passed to ast.parse (e.g. 3.9); default: the running interpreter",
    )
    parser.add_argument("--json", action="store_true", help="emit a JSON summary instead of text")
    parser.add_argument("--quiet", action="store_true", help="only print errors")
    args = parser.parse_args(argv)

    root = (args.root or default_root()).resolve()
    files = collect_first_party_files(root)
    errors = check_files(files, args.feature_version)
    version = "%d.%d.%d" % sys.version_info[:3]

    if args.json:
        payload = {
            "interpreter": sys.executable,
            "python_version": version,
            "feature_version": list(args.feature_version) if args.feature_version else None,
            "root": str(root),
            "files_checked": len(files),
            "ok": not errors,
            "errors": [dict(record, display=format_error(record, root)) for record in errors],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for record in errors:
            print(format_error(record, root))
        if not args.quiet or errors:
            status = "OK" if not errors else "FAIL"
            print(
                "py39-parse-check %s: %d files parsed under Python %s (%s), %d error(s)"
                % (status, len(files), version, sys.executable, len(errors))
            )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
