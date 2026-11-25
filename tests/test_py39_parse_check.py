"""Tests for bin/eve_py39_parse_check.py (Rearchitecture Program task 0.4a).

The daemon runs on Apple /usr/bin/python3 (3.9.6). The parse gate must pass
on the real tree under that interpreter, and it must fail loudly, with a
``file:line`` pointer, for a file that only parses under 3.10+.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "eve_py39_parse_check.py"
PY39 = "/usr/bin/python3"

SPEC = importlib.util.spec_from_file_location("eve_py39_parse_check", SCRIPT)
parse_check = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(parse_check)


def _interpreter() -> str:
    # Prefer the daemon interpreter; fall back to the running one elsewhere.
    return PY39 if os.path.exists(PY39) else sys.executable


def _run(*args, **kwargs):
    return subprocess.run(
        [_interpreter(), str(SCRIPT)] + list(args),
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        **kwargs
    )


def _make_tree(root: Path) -> None:
    (root / "eve.py").write_text("x = 1\n", encoding="utf-8")
    (root / "eve_thing.py").write_text("def f():\n    return 2\n", encoding="utf-8")
    (root / "eve_commands").mkdir()
    (root / "eve_commands" / "__init__.py").write_text("", encoding="utf-8")
    (root / "eve_commands" / "parser.py").write_text("NAMES = []\n", encoding="utf-8")
    (root / "bin").mkdir()
    (root / "bin" / "tool.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_a.py").write_text("import unittest\n", encoding="utf-8")
    (root / "tests" / "fixtures").mkdir()
    (root / "tests" / "fixtures" / "broken_fixture.py").write_text("this is not python\n", encoding="utf-8")
    for skipped in ("vendor", ".venv", ".venv-old", "EveBackups", "build", ".build"):
        (root / skipped).mkdir()
        (root / skipped / "eve_skipped.py").write_text("match x:\n    case 1:\n        pass\n", encoding="utf-8")
    (root / "bin" / "__pycache__").mkdir()
    (root / "bin" / "__pycache__" / "junk.py").write_text("def (:\n", encoding="utf-8")


class ParseCheckTreeTests(unittest.TestCase):
    def test_real_tree_parses_under_python39(self):
        result = _run()
        self.assertEqual(
            result.returncode,
            0,
            "parse gate failed under %s:\n%s\n%s" % (_interpreter(), result.stdout, result.stderr),
        )
        self.assertIn("py39-parse-check OK", result.stdout)

    def test_real_tree_json_summary_reports_every_first_party_group(self):
        result = _run("--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["errors"], [])
        self.assertGreater(payload["files_checked"], 100)
        if _interpreter() == PY39:
            self.assertTrue(payload["python_version"].startswith("3.9."), payload["python_version"])
        files = parse_check.collect_first_party_files(ROOT)
        names = {str(path.relative_to(ROOT)) for path in files}
        self.assertIn("eve.py", names)
        self.assertIn("eve_platform.py", names)
        self.assertIn("eve_commands/parser.py", names)
        self.assertIn("bin/eve_py39_parse_check.py", names)
        self.assertIn("tests/test_py39_parse_check.py", names)
        self.assertEqual(len(files), payload["files_checked"])
        self.assertFalse(any(".venv" in name or "vendor/" in name or "EveBackups" in name for name in names))


class ParseCheckBehaviourTests(unittest.TestCase):
    def test_collects_first_party_files_and_skips_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_tree(root)
            files = parse_check.collect_first_party_files(root)
            rel = [str(path.relative_to(root.resolve())) for path in files]
            self.assertEqual(
                rel,
                [
                    "eve.py",
                    "eve_thing.py",
                    "eve_commands/__init__.py",
                    "eve_commands/parser.py",
                    "bin/tool.py",
                    "tests/test_a.py",
                ],
            )

    def test_clean_tree_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_tree(Path(tmp))
            result = _run("--root", tmp)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("6 files parsed", result.stdout)

    def test_python310_syntax_fails_with_file_and_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_tree(root)
            bad = root / "eve_modern.py"
            bad.write_text("import sys\n\n\nmatch sys.argv:\n    case [_]:\n        pass\n", encoding="utf-8")
            result = _run("--root", tmp)
            if _interpreter() != PY39:
                self.skipTest("match statements only fail to parse under Python < 3.10")
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("eve_modern.py:4: SyntaxError", result.stdout)
            self.assertIn("py39-parse-check FAIL", result.stdout)

    def test_plain_syntax_error_reported_in_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_tree(root)
            (root / "bin" / "broken.py").write_text("def f(:\n    pass\n", encoding="utf-8")
            result = _run("--root", tmp, "--json")
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertEqual(len(payload["errors"]), 1)
            self.assertEqual(payload["errors"][0]["line"], 1)
            self.assertTrue(payload["errors"][0]["display"].startswith("bin/broken.py:1: SyntaxError"))

    def test_parse_one_returns_none_for_valid_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "good.py"
            good.write_text("value = {'a': 1}\n", encoding="utf-8")
            self.assertIsNone(parse_check.parse_one(good))
            bad = Path(tmp) / "bad.py"
            bad.write_text("x = (\n", encoding="utf-8")
            record = parse_check.parse_one(bad)
            self.assertIsNotNone(record)
            self.assertIn("SyntaxError", record["message"])


if __name__ == "__main__":
    unittest.main()
