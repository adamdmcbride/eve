"""Tests for bin/eve_test_receipt.sh and its writer bin/eve_test_receipt.py.

The full pytest stage (scratch worktree + .venv pytest) is never exercised
here: it is long and touches a worktree. These tests check the shell syntax,
the DRY_RUN plan, the log parsers on fixture output, and one short real run
with the pytest stage skipped.
"""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "eve_test_receipt.sh"
WRITER = ROOT / "bin" / "eve_test_receipt.py"
FIXTURES = ROOT / "tests" / "fixtures" / "test_receipt"
PY39 = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable
SEVEN_SUITES = [
    "tests.test_eve_core_contract",
    "tests.test_self_authority",
    "tests.test_cognition_budget",
    "tests.test_daemon_runtime",
    "tests.test_mind_tick",
    "tests.test_llama_transport",
    "tests.test_cli_parser",
]

SPEC = importlib.util.spec_from_file_location("eve_test_receipt", WRITER)
receipt_mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(receipt_mod)


def _worktrees():
    result = subprocess.run(
        ["git", "-C", str(ROOT), "worktree", "list", "--porcelain"], capture_output=True, text=True
    )
    return result.stdout


def _run_script(args, env_extra, cwd=None):
    env = dict(os.environ)
    env.update(env_extra)
    return subprocess.run(
        ["bash", str(SCRIPT)] + list(args), capture_output=True, text=True, cwd=str(cwd or ROOT), env=env
    )


class ShellScriptTests(unittest.TestCase):
    def test_bash_syntax(self):
        result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_dry_run_prints_plan_and_writes_nothing(self):
        before = _worktrees()
        with tempfile.TemporaryDirectory() as tmp:
            receipt_dir = Path(tmp) / "receipts"
            md = Path(tmp) / "summary.md"
            # The plan only includes the pytest stage when a venv interpreter with
            # pytest exists. Stand one in here so the test does not depend on the
            # checkout's .venv (absent in a scratch worktree); DRY_RUN runs nothing.
            fake_venv_py = Path(tmp) / "venv" / "bin" / "python"
            fake_venv_py.parent.mkdir(parents=True)
            fake_venv_py.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_venv_py.chmod(0o755)
            result = _run_script(
                ["--md", str(md)],
                {
                    "DRY_RUN": "1",
                    "EVE_TEST_RECEIPT_DIR": str(receipt_dir),
                    "EVE_TEST_VENV_PYTHON": str(fake_venv_py),
                },
                cwd=tmp,  # the script must not depend on the caller's cwd
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            out = result.stdout
            self.assertIn("DRY_RUN=1", out)
            self.assertIn("bin/eve_py39_parse_check.py --json", out)
            self.assertIn("-m unittest " + " ".join(SEVEN_SUITES), out)
            self.assertIn("git worktree add --detach", out)
            self.assertIn("EVE_RUNTIME_DIR=", out)
            self.assertIn("-m pytest tests -q -p no:cacheprovider", out)
            self.assertIn("receipt:      %s/" % receipt_dir, out)
            self.assertIn("markdown:     %s" % md, out)
            self.assertIn("worktree removed on exit", out)
            self.assertFalse(receipt_dir.exists(), "dry run must not create the receipt dir")
            self.assertFalse(md.exists(), "dry run must not write the markdown summary")
        self.assertEqual(before, _worktrees(), "dry run must not add a worktree")

    def test_dry_run_flag_and_skip_pytest_are_reflected_in_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_script(
                ["--dry-run", "--skip-pytest", "--suites", "tests.test_cli_parser"],
                {"EVE_TEST_RECEIPT_DIR": tmp},
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("SKIPPED (--skip-pytest requested)", result.stdout)
            self.assertIn("-m unittest tests.test_cli_parser\n", result.stdout)
            self.assertIn("markdown:     (none)", result.stdout)
            self.assertEqual(os.listdir(tmp), [])

    def test_unknown_argument_is_rejected(self):
        result = _run_script(["--bogus"], {"DRY_RUN": "1"})
        self.assertEqual(result.returncode, 64)
        self.assertIn("unknown argument", result.stderr)

    def test_option_missing_its_value_is_rejected_not_looped(self):
        # `shift 2` with one arg left does not shift in bash; without a guard the
        # parser would spin forever on a trailing --md / --receipt-dir / --suites.
        for opt in ("--md", "--receipt-dir", "--suites"):
            env = dict(os.environ)
            env.update({"DRY_RUN": "1", "EVE_TEST_RECEIPT_DIR": "/nonexistent/receipts"})
            result = subprocess.run(
                ["bash", str(SCRIPT), "--skip-pytest", opt],
                capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=20,
            )
            self.assertEqual(result.returncode, 64, opt + ": " + result.stdout + result.stderr)
            self.assertIn("%s requires a value" % opt, result.stderr)

    def test_help_prints_header_without_shell_code(self):
        result = _run_script(["--help"], {"DRY_RUN": "1"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Usage: bin/eve_test_receipt.sh", result.stdout)
        self.assertNotIn("set -u", result.stdout)

    def test_default_receipt_dir_is_eve_test_receipts(self):
        env = {k: v for k, v in os.environ.items() if k != "EVE_TEST_RECEIPT_DIR"}
        env["DRY_RUN"] = "1"
        result = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, cwd=str(ROOT), env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("receipt:      %s/.eve/test_receipts/" % ROOT, result.stdout)

    def test_real_run_with_pytest_skipped_writes_receipt(self):
        # Parse gate + one fast suite, pytest stage skipped: no worktree, no .eve writes.
        before = _worktrees()
        with tempfile.TemporaryDirectory() as tmp:
            receipt_dir = Path(tmp) / "receipts"
            md = Path(tmp) / "TEST_BASELINE.md"
            result = _run_script(
                ["--md", str(md), "--skip-pytest", "--suites", "tests.test_cli_parser"],
                {"EVE_TEST_RECEIPT_DIR": str(receipt_dir)},
                cwd=tmp,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            receipts = sorted(receipt_dir.glob("*.json"))
            self.assertEqual(len(receipts), 1, list(receipt_dir.iterdir()))
            receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
            self.assertEqual(receipt["schema"], receipt_mod.RECEIPT_SCHEMA)
            self.assertTrue(receipt["overall_ok"], json.dumps(receipt, indent=2)[:4000])
            self.assertTrue(receipt["parse_gate"]["ok"])
            self.assertGreater(receipt["parse_gate"]["files_checked"], 100)
            self.assertEqual(receipt["unittest_py39"]["suites"], ["tests.test_cli_parser"])
            self.assertGreater(receipt["unittest_py39"]["ran"], 0)
            self.assertEqual(receipt["unittest_py39"]["failing_ids"], [])
            self.assertEqual(receipt["pytest_full"]["status"], "skipped")
            self.assertIn("--skip-pytest", receipt["pytest_full"]["reason"])
            self.assertEqual(receipt["git"]["head"], subprocess.check_output(
                ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip())
            logs_dir = receipt_dir / (receipt["stamp"] + ".logs")
            self.assertTrue((logs_dir / "unittest_py39.log").exists())
            self.assertTrue((logs_dir / "parse_gate.json").exists())
            text = md.read_text(encoding="utf-8")
            self.assertIn("# Eve test receipt", text)
            self.assertIn("| Python 3.9 parse gate | pass |", text)
            self.assertIn("| pytest (full, worktree) | skipped |", text)
        self.assertEqual(before, _worktrees())


class ReceiptParserTests(unittest.TestCase):
    def test_parse_unittest_log_counts_and_failing_ids(self):
        parsed = receipt_mod.parse_unittest_log((FIXTURES / "unittest_sample.log").read_text(encoding="utf-8"))
        self.assertEqual(parsed["ran"], 10)
        self.assertEqual(parsed["failures"], 2)
        self.assertEqual(parsed["errors"], 1)
        self.assertEqual(parsed["skipped"], 1)
        self.assertEqual(parsed["passed"], 6)
        self.assertEqual(parsed["status_line"], "FAILED")
        self.assertEqual(
            parsed["failing_ids"],
            [
                "tests.test_llama_transport.LlamaTransportTests.test_transport_retries",
                "tests.test_cognition_budget.CognitionBudgetTests.test_budget_default",
                "tests.test_mind_tick.MindTickTests.test_subtest_case",
            ],
        )
        self.assertEqual(parsed["failing"][0]["kind"], "ERROR")
        self.assertEqual(parsed["failing"][2]["detail"], "[lane=fast]")

    def test_parse_unittest_log_ok(self):
        parsed = receipt_mod.parse_unittest_log((FIXTURES / "unittest_ok_sample.log").read_text(encoding="utf-8"))
        self.assertEqual(parsed["ran"], 5)
        self.assertEqual(parsed["passed"], 5)
        self.assertEqual(parsed["failing_ids"], [])
        self.assertEqual(parsed["status_line"], "OK")

    def test_parse_unittest_log_handles_python311_id_format(self):
        text = "FAIL: test_x (tests.test_mod.Cls.test_x)\nRan 1 test in 0.001s\n\nFAILED (failures=1)\n"
        parsed = receipt_mod.parse_unittest_log(text)
        self.assertEqual(parsed["failing_ids"], ["tests.test_mod.Cls.test_x"])

    def test_parse_pytest_log_counts_and_failing_ids(self):
        parsed = receipt_mod.parse_pytest_log((FIXTURES / "pytest_sample.log").read_text(encoding="utf-8"))
        self.assertEqual(parsed["passed"], 21)
        self.assertEqual(parsed["failed"], 2)
        self.assertEqual(parsed["errors"], 1)
        self.assertEqual(parsed["skipped"], 1)
        self.assertEqual(parsed["xfailed"], 1)
        self.assertEqual(parsed["total"], 26)
        self.assertEqual(
            parsed["failing_ids"],
            [
                "tests/test_copilotkit_probe.py::CopilotKitTests::test_agui_adapter_canary",
                "tests/test_copilotkit_probe.py::CopilotKitTests::test_probe_reports_protocol",
                "tests/test_http_server.py::HttpServerTests::test_bind",
            ],
        )
        self.assertEqual(parsed["failing"][2]["kind"], "ERROR")
        self.assertTrue(parsed["summary_line"].startswith("2 failed, 21 passed"))

    def test_parse_pytest_log_decorated_summary(self):
        text = "===== 3 passed, 1 warning in 0.10s =====\n"
        parsed = receipt_mod.parse_pytest_log(text)
        self.assertEqual(parsed["passed"], 3)
        self.assertEqual(parsed["warnings"], 1)
        self.assertEqual(parsed["failing_ids"], [])


class ReceiptWriterTests(unittest.TestCase):
    def _common(self, receipt_dir, md):
        return [
            "--receipt-dir", str(receipt_dir), "--md", str(md), "--stamp", "20260917T000000Z",
            "--started-at", "2026-09-17T00:00:00Z", "--root", str(ROOT),
            "--git-head", "abc123", "--git-branch", "main", "--dirty", "0", "--interpreter", PY39,
            "--parse-json", str(FIXTURES / "parse_gate_sample.json"), "--parse-exit", "0",
        ]

    def test_writer_records_failures_and_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt_dir = Path(tmp) / "r"
            md = Path(tmp) / "summary.md"
            argv = self._common(receipt_dir, md) + [
                "--unittest-log", str(FIXTURES / "unittest_sample.log"), "--unittest-exit", "1",
                "--suites"] + SEVEN_SUITES + [
                "--pytest-log", str(FIXTURES / "pytest_sample.log"), "--pytest-exit", "1",
                "--pytest-python", "/x/.venv/bin/python", "--pytest-worktree", "/tmp/wt/tree",
                "--pytest-head", "abc123", "--pytest-runtime-dir", "/tmp/wt/runtime",
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                code = receipt_mod.main(argv)
            self.assertEqual(code, 2)
            receipt = json.loads((receipt_dir / "20260917T000000Z.json").read_text(encoding="utf-8"))
            self.assertFalse(receipt["overall_ok"])
            self.assertTrue(receipt["parse_gate"]["ok"])
            self.assertEqual(receipt["parse_gate"]["files_checked"], 320)
            self.assertFalse(receipt["unittest_py39"]["ok"])
            self.assertEqual(receipt["unittest_py39"]["ran"], 10)
            self.assertEqual(len(receipt["unittest_py39"]["failing_ids"]), 3)
            self.assertEqual(receipt["unittest_py39"]["suites"], SEVEN_SUITES)
            self.assertEqual(receipt["pytest_full"]["status"], "ran")
            self.assertFalse(receipt["pytest_full"]["ok"])
            self.assertEqual(receipt["pytest_full"]["passed"], 21)
            self.assertEqual(receipt["pytest_full"]["failed"], 2)
            self.assertEqual(receipt["pytest_full"]["errors"], 1)
            self.assertEqual(len(receipt["pytest_full"]["failing_ids"]), 3)
            self.assertEqual(receipt["pytest_full"]["runtime_dir"], "/tmp/wt/runtime")
            text = md.read_text(encoding="utf-8")
            self.assertIn("Overall: **FAIL**", text)
            self.assertIn("## unittest failures", text)
            self.assertIn("## pytest failures", text)
            self.assertIn("tests/test_copilotkit_probe.py::CopilotKitTests::test_agui_adapter_canary", text)

    def test_writer_all_green_with_pytest_skipped_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt_dir = Path(tmp) / "r"
            md = Path(tmp) / "summary.md"
            argv = self._common(receipt_dir, md) + [
                "--unittest-log", str(FIXTURES / "unittest_ok_sample.log"), "--unittest-exit", "0",
                "--suites", "tests.test_cli_parser",
                "--pytest-skipped", "no venv interpreter",
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                code = receipt_mod.main(argv)
            self.assertEqual(code, 0)
            receipt = json.loads((receipt_dir / "20260917T000000Z.json").read_text(encoding="utf-8"))
            self.assertTrue(receipt["overall_ok"])
            self.assertEqual(receipt["pytest_full"]["status"], "skipped")
            self.assertEqual(receipt["pytest_full"]["reason"], "no venv interpreter")
            self.assertIn("| pytest (full, worktree) | skipped | no venv interpreter |", md.read_text(encoding="utf-8"))

    def test_writer_runs_under_python39_interpreter(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt_dir = Path(tmp) / "r"
            argv = [PY39, str(WRITER)] + self._common(receipt_dir, Path(tmp) / "s.md") + [
                "--unittest-log", str(FIXTURES / "unittest_ok_sample.log"), "--unittest-exit", "0",
                "--pytest-skipped", "test",
            ]
            result = subprocess.run(argv, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("overall: PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
