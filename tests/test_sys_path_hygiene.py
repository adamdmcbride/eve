"""No test may prepend bin/ (or another script dir) to sys.path for the whole session.

The repo has same-named modules at the root and under bin/ (for example
eve_sensory_eval.py is a library at the root and an argparse CLI wrapper in bin/).
A test that inserts bin/ at sys.path[0] at import time makes every later plain
``import eve_sensory_eval`` resolve to the wrapper, which broke three sensory tests
in receipt 20260917T053245Z. Load scripts by path with importlib instead.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = ROOT / "tests"
BIN_DIR = ROOT / "bin"

_MUTATION = re.compile(r"sys\.path\.(insert|append|extend)\s*\((?P<arg>[^\n]*)")
# The only sys.path mutation a test may make is putting the repo root first.
_ALLOWED_ARGS = {"0,str(ROOT))", "0,ROOT)", "str(ROOT))", "ROOT)"}


class SysPathHygieneTests(unittest.TestCase):
    def test_root_and_bin_share_module_names(self):
        # The hazard only exists while these pairs exist; if they disappear this
        # guard can go too.
        shared = sorted(
            path.name for path in BIN_DIR.glob("*.py") if (ROOT / path.name).is_file()
        )
        self.assertIn("eve_sensory_eval.py", shared)

    def test_no_test_module_puts_a_script_dir_on_sys_path(self):
        offenders = []
        for path in sorted(TESTS_DIR.glob("*.py")):
            if path.name == Path(__file__).name:
                continue
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                match = _MUTATION.search(line)
                if not match:
                    continue
                arg = re.sub(r"\s", "", match.group("arg"))
                if arg not in _ALLOWED_ARGS:
                    offenders.append("%s:%d: %s" % (path.name, lineno, line.strip()))
        self.assertEqual([], offenders)
