"""Facade lint (program task 0.3): passes on today's tree and catches both regressions.

``bin/eve_facade_lint.py`` reports module-level ``import eve`` outside its
allowlist and module-level bindings that shadow a pinned facade name outside
its baseline. This test runs it over the checkout and, on synthetic modules in
a temp dir, shows both finding codes fire.
"""
import contextlib
import importlib.util
import io
import os
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
LINT = ROOT / "bin" / "eve_facade_lint.py"

_spec = importlib.util.spec_from_file_location("eve_facade_lint", str(LINT))
lint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lint)


class FacadeLintOnCheckoutTests(unittest.TestCase):
    def test_checkout_is_clean(self):
        findings = lint.lint(root=str(ROOT))
        self.assertEqual(
            findings,
            [],
            "facade lint findings:\n%s" % "\n".join(str(f) for f in findings),
        )

    def test_default_paths_cover_first_party_modules_but_not_eve_py(self):
        paths = [os.path.relpath(p, str(ROOT)) for p in lint.default_paths(str(ROOT))]
        self.assertIn("eve_late.py", paths)
        self.assertIn("eve_web.py", paths)
        self.assertIn(os.path.join("eve_commands", "parser.py"), paths)
        self.assertNotIn("eve.py", paths)
        self.assertGreater(len(paths), 60)

    def test_allowlist_and_baseline_only_name_files_that_exist(self):
        for relpath in lint.IMPORT_EVE_ALLOWLIST:
            self.assertTrue((ROOT / relpath).exists(), "stale allowlist entry %s" % relpath)
        for relpath in lint.SHADOW_BASELINE:
            self.assertTrue((ROOT / relpath).exists(), "stale baseline entry %s" % relpath)

    def test_allowlist_is_still_needed_by_each_member(self):
        # Every allowlisted module really does import eve at module level today;
        # when Phase 4 moves one onto eve_late.core its entry must be removed.
        for relpath in sorted(lint.IMPORT_EVE_ALLOWLIST):
            tree = lint._parse(str(ROOT / relpath))
            self.assertTrue(
                lint.module_level_eve_imports(tree),
                "%s no longer imports eve at module level; drop it from IMPORT_EVE_ALLOWLIST" % relpath,
            )

    def test_baseline_is_exact_for_today(self):
        # No baseline entry is dead weight: each name is still a live duplicate.
        computed = lint.emit_baseline(str(ROOT))
        self.assertEqual(
            computed,
            lint.SHADOW_BASELINE,
            "SHADOW_BASELINE drifted; regenerate with: python3 bin/eve_facade_lint.py --emit-baseline",
        )

    def test_eve_late_never_imports_eve_at_module_level(self):
        tree = lint._parse(str(ROOT / "eve_late.py"))
        self.assertEqual(lint.module_level_eve_imports(tree), [])


class FacadeLintSyntheticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.pinned = {"utc_now", "ROOT", "cmd_thing", "helper"}
        self.sourced = {"eve_owner": {"helper"}}

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, relpath, source):
        path = os.path.join(self.root, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(source)
        return path

    def _lint(self, relpaths, **kwargs):
        paths = [os.path.join(self.root, r) for r in relpaths]
        kwargs.setdefault("import_allowlist", frozenset())
        kwargs.setdefault("shadow_baseline", {})
        return lint.lint(root=self.root, paths=paths, pinned=self.pinned, sourced=self.sourced, **kwargs)

    def test_import_eve_is_reported_including_nested_and_from_forms(self):
        self._write(
            "eve_bad.py",
            "import os\n"
            "try:\n"
            "    import eve\n"
            "except ImportError:\n"
            "    eve = None\n"
            "if os.environ.get('X'):\n"
            "    from eve import utc_now as now\n"
            "def f():\n"
            "    import eve  # inside a function: allowed\n",
        )
        findings = self._lint(["eve_bad.py"])
        codes = [(f.code, f.lineno) for f in findings]
        self.assertEqual(codes, [("import-eve", 3), ("import-eve", 7)])

    def test_type_checking_imports_are_ignored(self):
        self._write(
            "eve_typed.py",
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    import eve\n",
        )
        self.assertEqual(self._lint(["eve_typed.py"]), [])

    def test_allowlisted_module_may_import_eve(self):
        self._write("eve_ok.py", "import eve\n")
        self.assertEqual(self._lint(["eve_ok.py"], import_allowlist=frozenset({"eve_ok.py"})), [])
        self.assertEqual(len(self._lint(["eve_ok.py"])), 1)

    def test_shadow_bindings_are_reported_by_kind(self):
        self._write(
            "eve_dup.py",
            "import os\n"
            "from pathlib import Path\n"
            "from eve_records import utc_now\n"
            "ROOT = Path('.')\n"
            "def cmd_thing(): pass\n"
            "unrelated = 1\n"
            "def other(): pass\n"
            "class helper: pass\n",
        )
        findings = self._lint(["eve_dup.py"])
        self.assertEqual(
            [(f.code, f.name, f.lineno) for f in findings],
            [("shadow", "utc_now", 3), ("shadow", "ROOT", 4), ("shadow", "cmd_thing", 5), ("shadow", "helper", 8)],
        )

    def test_plain_imports_and_external_from_imports_never_shadow(self):
        self._write(
            "eve_imports.py",
            "import ROOT\n"
            "from os.path import join as utc_now\n"
            "import eve_store as helper\n",
        )
        self.assertEqual(self._lint(["eve_imports.py"]), [])

    def test_sourcing_module_may_define_the_name(self):
        self._write("eve_owner.py", "def helper(): pass\ndef utc_now(): pass\n")
        findings = self._lint(["eve_owner.py"])
        self.assertEqual([(f.code, f.name) for f in findings], [("shadow", "utc_now")])

    def test_baseline_admits_only_listed_names(self):
        self._write("eve_base.py", "def utc_now(): pass\ndef cmd_thing(): pass\n")
        findings = self._lint(["eve_base.py"], shadow_baseline={"eve_base.py": ("utc_now",)})
        self.assertEqual([(f.code, f.name) for f in findings], [("shadow", "cmd_thing")])

    def test_late_core_usage_is_clean(self):
        self._write(
            "eve_core/extracted.py",
            "from eve_late import core\n"
            "def compute():\n"
            "    return core.utc_now(), core.ROOT\n",
        )
        self.assertEqual(self._lint(["eve_core/extracted.py"]), [])

    def test_sourced_names_reads_both_forms(self):
        facade = self._write(
            "eve.py",
            "import eve_a\n"
            "from eve_b import one, two as alias\n"
            "three = eve_c.three\n"
            "four = set(eve_c.four)\n",
        )
        self.assertEqual(lint.sourced_names(facade), {"eve_b": {"one"}, "eve_c": {"three"}})

    def test_cli_exit_status(self):
        self._write("eve_cli.py", "import eve\n")
        self._write("eve.py", "")
        fixture = self._write("tests/fixtures/eve_facade_pins.txt", "utc_now\n")
        self.assertTrue(os.path.exists(fixture))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = lint.main(["--root", self.root, os.path.join(self.root, "eve_cli.py")])
        self.assertEqual(rc, 1)
        self.assertIn("[import-eve]", out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            rc = lint.main(["--root", self.root, os.path.join(self.root, "eve.py")])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
