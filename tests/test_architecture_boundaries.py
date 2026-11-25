import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("eve_architecture_check", ROOT / "bin/eve_architecture_check.py")
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_current_core_obeys_declared_dependency_direction(self):
        self.assertEqual([], checker.check_core(ROOT))

    def fixture(self, source, other=""):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        package = root / "eve_core"
        package.mkdir()
        (package / "__init__.py").write_text("")
        (package / "changes.py").write_text(source)
        (package / "self_change.py").write_text(other)
        return checker.check_core(root)

    def test_proxy_and_infrastructure_imports_are_rejected(self):
        for source in ("import eve", "from eve_late import core", "import eve_store", "from eve_adapters.self_change import LegacyCoder", "import pathlib", "from pathlib import Path", "import importlib"):
            with self.subTest(source=source):
                self.assertTrue(self.fixture(source))

    def test_dynamic_escape_and_core_io_are_rejected(self):
        for source in ("open('state')", "__import__('eve')", "exec('import eve')", "eval('1')"):
            with self.subTest(source=source):
                self.assertTrue(self.fixture(source))

    def test_back_edge_and_cycles_are_rejected(self):
        issues = self.fixture("from .self_change import SelfChangeService", "from .changes import ChangeEvidence")
        self.assertTrue(any("forbidden layer" in issue for issue in issues))
        self.assertTrue(any("import cycle" in issue for issue in issues))

    def test_unreviewed_layer_and_syntax_are_rejected(self):
        self.assertTrue(any("syntax error" in issue for issue in self.fixture("def x(:")))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "eve_core").mkdir()
            (root / "eve_core/__init__.py").write_text("")
            (root / "eve_core/extra.py").write_text("pass")
            self.assertTrue(any("declare" in issue for issue in checker.check_core(root)))

    def test_core_imports_and_tests_work_with_legacy_facade_blocked(self):
        code = '''
import importlib.abc, sys, unittest
class BlockLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"eve", "eve_late", "eve_store"} or fullname.startswith("eve_adapters"):
            raise ImportError("legacy dependency is unavailable: " + fullname)
sys.meta_path.insert(0, BlockLegacy())
suite = unittest.defaultTestLoader.loadTestsFromNames(["tests.test_core_self_change", "tests.test_core_conversation", "tests.test_core_preflight", "tests.test_core_memory_context"])
result = unittest.TextTestRunner().run(suite)
assert not any(name in sys.modules for name in ("eve", "eve_late", "eve_store", "eve_adapters"))
raise SystemExit(not result.wasSuccessful())
'''
        result = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
