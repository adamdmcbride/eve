#!/usr/bin/env python3
"""AST lint for the strangler harness (program task 0.3).

Checks every first-party module outside ``eve.py`` (``eve_*.py`` at the root,
``eve_commands/``, and ``eve_core/`` once it exists) for two things that break
the facade contract enforced by ``tests/test_facade_pins.py``:

``import-eve``
    A module-level ``import eve`` / ``from eve import ...`` (including ones
    nested in module-level ``try``/``if`` blocks; ``if TYPE_CHECKING:`` blocks
    are ignored). ``eve.py`` imports these modules, so this is circular, and a
    ``from eve import name`` freezes a binding that ``patch.object(eve, name)``
    can never reach. Extracted code goes through ``eve_late.core`` instead.
    Allowed only for the modules in ``IMPORT_EVE_ALLOWLIST`` (the ones that do
    it today; the list must only shrink).

``shadow``
    A module-level binding of a *pinned* name (a line of
    ``tests/fixtures/eve_facade_pins.txt``) by ``def``/``class``/assignment, or
    by ``from <first-party module> import name``. Such a binding is a second
    implementation of a facade name that the test-suite's patches on ``eve``
    do not see. Plain ``import`` statements never count (they bind the same
    module object ``eve`` sees), and neither does the module ``eve.py`` sources
    the name from (``from M import name`` or ``name = M.name`` in ``eve.py``).
    Today's pre-existing duplicates are pinned in ``SHADOW_BASELINE`` so the
    lint passes on the unmodified tree; regenerate it with ``--emit-baseline``
    only when a duplicate is deliberately retired, never to admit a new one.

Exit status 1 when any finding is reported. Never imports ``eve``.

Usage::

    python3 bin/eve_facade_lint.py                 # lint the checkout
    python3 bin/eve_facade_lint.py --json          # findings as JSON
    python3 bin/eve_facade_lint.py --emit-baseline # print SHADOW_BASELINE for today's tree
    python3 bin/eve_facade_lint.py path/a.py ...   # lint only these files

Python 3.9 compatible; stdlib only.
"""
import argparse
import ast
import glob
import importlib.util
import json
import os
import sys
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FACADE_MODULE = "eve"
FACADE_FILE = "eve.py"
FIXTURE_RELPATH = os.path.join("tests", "fixtures", "eve_facade_pins.txt")
FIRST_PARTY_PREFIXES = ("eve_",)
FIRST_PARTY_PACKAGES = ("eve_commands", "eve_core")

# Modules that ``import eve`` at module level on the unmodified 2026-09-17 tree.
# Phase 4 moves each of them onto ``eve_late.core``; this set only shrinks.
IMPORT_EVE_ALLOWLIST = frozenset(
    (
        "eve_chat_followups.py",
        "eve_chat_protocol.py",
        "eve_install_artifacts.py",
        "eve_monitor_projection.py",
        "eve_runtime_projection.py",
        "eve_sensory_sessions.py",
        "eve_web.py",
    )
)

# Pre-existing module-level duplicates of pinned names, keyed by repo-relative
# path, as of the unmodified 2026-09-17 tree (``--emit-baseline``). A name is
# admitted here only because it already existed before the harness; new
# duplicates are findings.
SHADOW_BASELINE = {
    "eve_capability_adoption.py": ("utc_now",),
    "eve_capability_intelligence.py": ("utc_now",),
    "eve_commands/parser.py": ("build_parser",),
    "eve_commitments.py": ("utc_now",),
    "eve_db.py": ("utc_now",),
    "eve_economy.py": ("build_parser", "main", "utc_now"),
    "eve_evidence.py": ("parse_iso_datetime", "utc_now"),
    "eve_experience.py": ("read_experience_events", "utc_now"),
    "eve_governance.py": ("utc_now",),
    "eve_install_artifacts.py": ("BIN_DIR", "ROOT"),
    "eve_model_governor.py": ("parse_iso_datetime", "utc_now"),
    "eve_model_inventory.py": ("build_parser", "main", "utc_now"),
    "eve_model_topology.py": ("MODEL_LANE_TOPOLOGY_MODES", "build_parser", "load_config", "main"),
    "eve_monitor_projection.py": ("ROOT",),
    "eve_observer_confound.py": ("file_sha256",),
    "eve_openclaw.py": (
        "ACTIVE_MIND_PATH",
        "APP_DIR",
        "ROOT",
        "RUNTIME_APP_DIR",
        "RUNTIME_DIR",
        "STATE_PATH",
        "parse_iso_datetime",
        "utc_now",
    ),
    "eve_openclaw_body.py": ("APP_DIR", "ROOT", "RUNTIME_APP_DIR", "RUNTIME_DIR", "utc_now"),
    "eve_oss_validation.py": ("file_sha256", "utc_now"),
    "eve_otel_genai.py": ("build_parser", "main"),
    "eve_profile.py": ("main",),
    "eve_records.py": ("utc_now",),
    "eve_self_authority.py": ("ROOT",),
    "eve_self_repair_container.py": ("utc_now",),
    "eve_store.py": (
        "append_jsonl_record",
        "read_jsonl_records",
        "read_jsonl_tail_records",
        "read_text_tail",
        "write_jsonl_records",
    ),
    "eve_tracing.py": ("utc_now",),
    "eve_usage_trace.py": ("ROOT",),
    "eve_web.py": ("BIN_DIR", "ROOT", "main"),
}  # type: Dict[str, Tuple[str, ...]]


class Finding(object):
    __slots__ = ("path", "lineno", "code", "name", "message")

    def __init__(self, path, lineno, code, name, message):
        # type: (str, int, str, str, str) -> None
        self.path = path
        self.lineno = lineno
        self.code = code
        self.name = name
        self.message = message

    def as_dict(self):
        # type: () -> Dict[str, object]
        return {
            "path": self.path,
            "lineno": self.lineno,
            "code": self.code,
            "name": self.name,
            "message": self.message,
        }

    def __str__(self):
        # type: () -> str
        return "%s:%d: [%s] %s" % (self.path, self.lineno, self.code, self.message)

    def __repr__(self):
        # type: () -> str
        return "Finding(%r)" % (str(self),)


def _read(path):
    # type: (str) -> str
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _parse(path):
    # type: (str) -> ast.Module
    return ast.parse(_read(path), filename=path)


def is_first_party_module(module, level=0):
    # type: (Optional[str], int) -> bool
    if level:
        return True
    if not module:
        return False
    head = module.split(".")[0]
    if head == FACADE_MODULE:
        return True
    if head in FIRST_PARTY_PACKAGES:
        return True
    return any(head.startswith(prefix) for prefix in FIRST_PARTY_PREFIXES)


def _is_type_checking_test(test):
    # type: (ast.AST) -> bool
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def iter_module_level(body):
    # type: (Sequence[ast.stmt]) -> Iterator[ast.stmt]
    """Yield statements executed at module scope, descending into try/if/with."""
    for node in body:
        if isinstance(node, ast.If):
            if _is_type_checking_test(node.test):
                for sub in iter_module_level(node.orelse):
                    yield sub
                continue
            for sub in iter_module_level(node.body):
                yield sub
            for sub in iter_module_level(node.orelse):
                yield sub
        elif isinstance(node, ast.Try):
            for sub in iter_module_level(node.body):
                yield sub
            for handler in node.handlers:
                for sub in iter_module_level(handler.body):
                    yield sub
            for sub in iter_module_level(node.orelse):
                yield sub
            for sub in iter_module_level(node.finalbody):
                yield sub
        elif isinstance(node, (ast.With, ast.For, ast.While)):
            for sub in iter_module_level(node.body):
                yield sub
            for sub in iter_module_level(getattr(node, "orelse", [])):
                yield sub
        else:
            yield node


def _assignment_targets(node):
    # type: (ast.stmt) -> List[str]
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        targets = [node.target]
    else:
        return []
    names = []
    for target in targets:
        for sub in ast.walk(target):
            if isinstance(sub, ast.Name):
                names.append(sub.id)
    return names


def module_level_bindings(tree):
    # type: (ast.Module) -> List[Tuple[str, int, str]]
    """Return (name, lineno, kind) for every module-scope binding.

    ``kind`` is one of ``def``, ``class``, ``assign``, ``import``,
    ``from-first-party`` or ``from-external``.
    """
    bindings = []  # type: List[Tuple[str, int, str]]
    for node in iter_module_level(tree.body):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bindings.append((node.name, node.lineno, "def"))
        elif isinstance(node, ast.ClassDef):
            bindings.append((node.name, node.lineno, "class"))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bindings.append(((alias.asname or alias.name).split(".")[0], node.lineno, "import"))
        elif isinstance(node, ast.ImportFrom):
            kind = "from-first-party" if is_first_party_module(node.module, node.level) else "from-external"
            for alias in node.names:
                bindings.append((alias.asname or alias.name, node.lineno, kind))
        else:
            for name in _assignment_targets(node):
                bindings.append((name, node.lineno, "assign"))
    return bindings


def module_level_eve_imports(tree):
    # type: (ast.Module) -> List[Tuple[int, str]]
    """Return (lineno, statement) for module-scope imports of the facade."""
    found = []  # type: List[Tuple[int, str]]
    for node in iter_module_level(tree.body):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == FACADE_MODULE or alias.name.startswith(FACADE_MODULE + "."):
                    found.append((node.lineno, "import %s" % alias.name))
        elif isinstance(node, ast.ImportFrom) and not node.level:
            module = node.module or ""
            if module == FACADE_MODULE or module.startswith(FACADE_MODULE + "."):
                found.append((node.lineno, "from %s import ..." % module))
    return found


def sourced_names(facade_path):
    # type: (str) -> Dict[str, Set[str]]
    """Names ``eve.py`` takes verbatim from a module: ``from M import n`` / ``n = M.n``.

    Keyed by dotted module name (``eve_performance``, ``eve_commands.x``).
    """
    tree = _parse(facade_path)
    sourced = {}  # type: Dict[str, Set[str]]
    for node in iter_module_level(tree.body):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                if alias.asname is None and alias.name != "*":
                    sourced.setdefault(node.module, set()).add(alias.name)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            value = node.value
            if (
                isinstance(target, ast.Name)
                and isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.attr == target.id
            ):
                sourced.setdefault(value.value.id, set()).add(value.attr)
    return sourced


def dotted_module_name(relpath):
    # type: (str) -> str
    name = relpath[:-3] if relpath.endswith(".py") else relpath
    name = name.replace(os.sep, ".").replace("/", ".")
    if name.endswith(".__init__"):
        name = name[: -len(".__init__")]
    return name


def default_paths(root=ROOT):
    # type: (str) -> List[str]
    paths = sorted(glob.glob(os.path.join(root, "eve_*.py")))
    for package in FIRST_PARTY_PACKAGES:
        paths.extend(sorted(glob.glob(os.path.join(root, package, "**", "*.py"), recursive=True)))
    return [p for p in paths if os.path.basename(p) != FACADE_FILE and "__pycache__" not in p]


def load_pinned_names(root=ROOT, fixture=None):
    # type: (str, Optional[str]) -> Set[str]
    """Pinned names from the fixture, or regenerated live when it is absent."""
    if fixture is None:
        fixture = os.path.join(root, FIXTURE_RELPATH)
    if os.path.exists(fixture):
        names = set()
        for line in _read(fixture).splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                names.add(line)
        return names
    spec = importlib.util.spec_from_file_location(
        "eve_facade_pins", os.path.join(root, "bin", "eve_facade_pins.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return set(module.pinned_names(root))


def lint_file(
    path,  # type: str
    pinned,  # type: Set[str]
    sourced,  # type: Dict[str, Set[str]]
    root=ROOT,  # type: str
    import_allowlist=IMPORT_EVE_ALLOWLIST,  # type: Iterable[str]
    shadow_baseline=SHADOW_BASELINE,  # type: Dict[str, Tuple[str, ...]]
):
    # type: (...) -> List[Finding]
    relpath = os.path.relpath(path, root).replace(os.sep, "/")
    tree = _parse(path)
    findings = []  # type: List[Finding]

    if relpath not in set(import_allowlist):
        for lineno, statement in module_level_eve_imports(tree):
            findings.append(
                Finding(
                    relpath,
                    lineno,
                    "import-eve",
                    FACADE_MODULE,
                    "module-level '%s' (use 'from eve_late import core' and core.<name> at call time)" % statement,
                )
            )

    module_name = dotted_module_name(relpath)
    owned = sourced.get(module_name, set())
    baseline = set(shadow_baseline.get(relpath, ()))
    for name, lineno, kind in module_level_bindings(tree):
        if name not in pinned or kind in ("import", "from-external"):
            continue
        if name in owned or name in baseline:
            continue
        findings.append(
            Finding(
                relpath,
                lineno,
                "shadow",
                name,
                "module-level %s binds pinned facade name '%s' (tests patch eve.%s; bind it through eve_late.core instead)"
                % (kind, name, name),
            )
        )
    return findings


def lint(
    root=ROOT,  # type: str
    paths=None,  # type: Optional[Sequence[str]]
    pinned=None,  # type: Optional[Set[str]]
    sourced=None,  # type: Optional[Dict[str, Set[str]]]
    import_allowlist=IMPORT_EVE_ALLOWLIST,  # type: Iterable[str]
    shadow_baseline=SHADOW_BASELINE,  # type: Dict[str, Tuple[str, ...]]
):
    # type: (...) -> List[Finding]
    if paths is None:
        paths = default_paths(root)
    if pinned is None:
        pinned = load_pinned_names(root)
    if sourced is None:
        facade = os.path.join(root, FACADE_FILE)
        sourced = sourced_names(facade) if os.path.exists(facade) else {}
    findings = []  # type: List[Finding]
    for path in paths:
        findings.extend(
            lint_file(
                os.path.abspath(path),
                pinned,
                sourced,
                root=root,
                import_allowlist=import_allowlist,
                shadow_baseline=shadow_baseline,
            )
        )
    findings.sort(key=lambda f: (f.path, f.lineno, f.code, f.name))
    return findings


def emit_baseline(root=ROOT):
    # type: (str) -> Dict[str, Tuple[str, ...]]
    """Compute SHADOW_BASELINE for the current tree (shadow findings with no baseline)."""
    findings = lint(root=root, shadow_baseline={})
    grouped = {}  # type: Dict[str, Set[str]]
    for finding in findings:
        if finding.code == "shadow":
            grouped.setdefault(finding.path, set()).add(finding.name)
    return {path: tuple(sorted(names)) for path, names in sorted(grouped.items())}


def main(argv=None):
    # type: (Optional[List[str]]) -> int
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", help="files to lint (default: eve_*.py, eve_commands/, eve_core/)")
    parser.add_argument("--root", default=ROOT, help="repository root (default: this checkout)")
    parser.add_argument("--json", action="store_true", help="print findings as JSON")
    parser.add_argument("--emit-baseline", action="store_true", help="print a SHADOW_BASELINE literal for the current tree")
    args = parser.parse_args(argv)
    root = os.path.abspath(args.root)

    if args.emit_baseline:
        baseline = emit_baseline(root)
        print("SHADOW_BASELINE = {")
        for path, names in baseline.items():
            print("    %r: %r," % (path, names))
        print("}")
        return 0

    findings = lint(root=root, paths=args.paths or None)
    if args.json:
        print(json.dumps([f.as_dict() for f in findings], indent=2))
    else:
        for finding in findings:
            print(finding)
        checked = len(args.paths) if args.paths else len(default_paths(root))
        print(
            "facade lint: %d finding(s) in %d file(s); %d import-eve allowlisted, %d baseline shadow module(s)"
            % (len(findings), checked, len(IMPORT_EVE_ALLOWLIST), len(SHADOW_BASELINE))
        )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
