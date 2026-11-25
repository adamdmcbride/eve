import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("eve_bootstrap", ROOT / "bin" / "eve_bootstrap.py")
eve_bootstrap = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(eve_bootstrap)


class EveBootstrapTests(unittest.TestCase):
    def test_optional_model_artifacts_are_not_required_for_source_bootstrap(self):
        self.assertNotIn("eve_epistemic_model_v1.json", eve_bootstrap.REQUIRED_SOURCE_FILES)
        self.assertNotIn("eve_epistemic_event_v1.json", eve_bootstrap.REQUIRED_SOURCE_FILES)

    def make_checkout(self, root: Path) -> None:
        for relative in eve_bootstrap.REQUIRED_SOURCE_FILES:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("placeholder\n", encoding="utf-8")

    @staticmethod
    def tools(name: str):
        return {
            "uv": "/usr/local/bin/uv",
            "git": "/usr/bin/git",
            "llama-server": "/usr/local/bin/llama-server",
            "xcodebuild": "/usr/bin/xcodebuild",
        }.get(name)

    def test_preflight_passes_for_complete_supported_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_checkout(root)
            report = eve_bootstrap.preflight_report(
                root,
                which=self.tools,
                version=(3, 12, 9),
                system="Darwin",
            )

        self.assertTrue(report["ok"])
        self.assertEqual(eve_bootstrap.BOOTSTRAP_REPORT_SCHEMA_VERSION, report["schema_version"])
        self.assertEqual(0, report["failure_count"])
        self.assertEqual(0, report["warning_count"])

    def test_preflight_blocks_missing_source_and_uv_but_uv_can_provision_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = eve_bootstrap.preflight_report(
                Path(tmp),
                which=lambda _name: None,
                version=(3, 11, 0),
                system="Linux",
            )

        failures = {item["id"] for item in report["checks"] if item["status"] == "fail"}
        warnings = {item["id"] for item in report["checks"] if item["status"] == "warning"}
        self.assertFalse(report["ok"])
        self.assertEqual({"source_checkout", "uv"}, failures)
        self.assertIn("bootstrap_python", warnings)

    def test_install_plan_is_locked_adds_source_command_and_does_not_install_a_daemon(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            plan = eve_bootstrap.install_plan(
                root,
                uv_path="/usr/local/bin/uv",
                extras=["dev", "dev", "infra"],
                system="Darwin",
            )

        self.assertEqual(
            [
                "/usr/local/bin/uv",
                "sync",
                "--python",
                "3.12",
                "--frozen",
                "--extra",
                "dev",
                "--extra",
                "infra",
            ],
            plan[0],
        )
        self.assertEqual(
            [
                str(root / ".venv/bin/python"),
                str(root / "bin/eve_bootstrap.py"),
                "--root",
                str(root),
                "install-cli",
            ],
            plan[1],
        )
        self.assertEqual([str(root / ".venv/bin/python"), str(root / "eve.py"), "runtime", "sync"], plan[2])
        self.assertEqual(
            [str(root / ".venv/bin/python"), str(root / "eve.py"), "runtime", "truth", "--json"],
            plan[3],
        )
        self.assertFalse(any("daemon" in part for command in plan for part in command))

    def test_source_command_is_relocation_safe_and_forwards_arguments(self):
        if os.name == "nt":
            self.skipTest("Unix launcher execution contract")
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            root = parent / "checkout-before"
            (root / ".venv/bin").mkdir(parents=True)
            (root / "eve.py").write_text(
                "import json, sys\nprint(json.dumps(sys.argv[1:]))\n",
                encoding="utf-8",
            )
            os.symlink(sys.executable, root / ".venv/bin/python")

            launcher = eve_bootstrap.install_source_cli(root, system="Darwin")
            source = launcher.read_text(encoding="utf-8")
            self.assertNotIn(str(root), source)
            self.assertTrue(launcher.stat().st_mode & 0o111)

            moved = parent / "checkout after"
            shutil.move(str(root), moved)
            completed = subprocess.run(
                [str(moved / ".venv/bin/eve"), "doctor", "--quick"],
                text=True,
                capture_output=True,
                check=True,
            )

        self.assertEqual(["doctor", "--quick"], json.loads(completed.stdout))

    def test_windows_source_command_uses_relative_venv_and_source_paths(self):
        content = eve_bootstrap.source_cli_content(system="Windows")

        self.assertIn('"%SCRIPT_DIR%python.exe"', content)
        self.assertIn('"%ROOT_DIR%\\eve.py" %*', content)
        self.assertNotIn(str(ROOT), content)

    def test_source_command_install_fails_before_locked_environment_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "eve.py").write_text("pass\n", encoding="utf-8")

            with self.assertRaisesRegex(FileNotFoundError, "uv sync --frozen"):
                eve_bootstrap.install_source_cli(root, system="Darwin")

    def test_install_cli_json_failure_keeps_the_schema_contract(self):
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(stdout):
            returncode = eve_bootstrap.main(["--root", tmp, "--json", "install-cli"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(1, returncode)
        self.assertFalse(payload["ok"])
        self.assertEqual(eve_bootstrap.BOOTSTRAP_REPORT_SCHEMA_VERSION, payload["schema_version"])
        self.assertIn("uv sync --frozen", payload["error"])

    def test_install_execution_uses_checkout_and_stops_on_failure(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return None

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            eve_bootstrap.execute_install(root, [["uv", "sync", "--frozen"]], env={}, runner=runner)

        self.assertEqual([["uv", "sync", "--frozen"]], [item[0] for item in calls])
        self.assertEqual(str(root), calls[0][1]["cwd"])
        self.assertTrue(calls[0][1]["check"])
        self.assertEqual(
            str(Path(tempfile.gettempdir()) / "eve_bootstrap_pycache"),
            calls[0][1]["env"]["PYTHONPYCACHEPREFIX"],
        )

    def test_isolated_install_failure_stops_later_steps_and_keeps_only_a_bounded_tail(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            if command[0] == "second":
                kwargs["stdout"].write(b"old output\n" + (b"x" * 9000) + b"\nuseful failure\n")
                raise subprocess.CalledProcessError(7, command)
            return subprocess.CompletedProcess(command, 0)

        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(
            eve_bootstrap.InstallCommandError
        ) as raised:
            eve_bootstrap.execute_install(
                Path(tmp),
                [["first"], ["second"], ["never"]],
                env={},
                runner=runner,
                isolate_output=True,
            )

        failure = raised.exception
        self.assertEqual([["first"], ["second"]], [item[0] for item in calls])
        self.assertEqual(1, failure.command_index)
        self.assertEqual(("second",), failure.command)
        self.assertEqual(7, failure.returncode)
        self.assertTrue(failure.output_tail.startswith("…\n"))
        self.assertIn("useful failure", failure.output_tail)
        self.assertNotIn("old output", failure.output_tail)
        self.assertLessEqual(len(failure.output_tail.encode("utf-8")), eve_bootstrap.INSTALL_OUTPUT_TAIL_BYTES + 4)
        self.assertIs(calls[1][1]["stderr"], subprocess.STDOUT)

    def test_json_install_failure_is_one_truthful_document_without_traceback(self):
        report = {
            "schema_version": 1,
            "root": "/source",
            "platform": "Darwin",
            "ok": True,
            "failure_count": 0,
            "warning_count": 0,
            "checks": [{"id": "uv", "status": "pass", "detail": "/usr/bin/uv"}],
        }
        failure = eve_bootstrap.InstallCommandError(
            command_index=1,
            command=["eve", "runtime", "sync"],
            returncode=9,
            output_tail="bounded failure",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.object(eve_bootstrap, "preflight_report", return_value=report), patch.object(
            eve_bootstrap,
            "install_plan",
            return_value=[["uv", "sync"], ["eve", "runtime", "sync"], ["never"]],
        ), patch.object(eve_bootstrap, "execute_install", side_effect=failure) as execute, contextlib.redirect_stdout(
            stdout
        ), contextlib.redirect_stderr(stderr):
            returncode = eve_bootstrap.main(["--root", "/source", "--json", "install"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(1, returncode)
        self.assertEqual("failed", payload["install_status"])
        self.assertFalse(payload["ok"])
        self.assertEqual(1, payload["completed_command_count"])
        self.assertEqual(["eve", "runtime", "sync"], payload["failed_command"])
        self.assertEqual("bounded failure", payload["output_tail"])
        self.assertFalse(payload["rollback_performed"])
        self.assertEqual("", stderr.getvalue())
        self.assertTrue(execute.call_args.kwargs["isolate_output"])

    def test_json_install_success_is_emitted_after_all_steps_complete(self):
        report = {
            "schema_version": 1,
            "root": "/source",
            "platform": "Darwin",
            "ok": True,
            "failure_count": 0,
            "warning_count": 0,
            "checks": [{"id": "uv", "status": "pass", "detail": "/usr/bin/uv"}],
        }
        commands = [["uv", "sync"], ["eve", "install-cli"]]
        receipts = [
            {"command_index": index, "command": command, "returncode": 0}
            for index, command in enumerate(commands)
        ]
        stdout = io.StringIO()
        with patch.object(eve_bootstrap, "preflight_report", return_value=report), patch.object(
            eve_bootstrap, "install_plan", return_value=commands
        ), patch.object(eve_bootstrap, "execute_install", return_value=receipts), contextlib.redirect_stdout(stdout):
            returncode = eve_bootstrap.main(["--root", "/source", "--json", "install"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(0, returncode)
        self.assertTrue(payload["ok"])
        self.assertEqual("completed", payload["install_status"])
        self.assertEqual(2, payload["completed_command_count"])

    def test_skipped_runtime_sync_is_not_reported_as_completed(self):
        message = "\n".join(eve_bootstrap.completion_lines(runtime_synced=False))
        self.assertIn("intentionally not created", message)
        self.assertNotIn("runtime mirror are ready", message)
        self.assertIn(".venv/bin/eve doctor", message)

    def test_public_bootstrap_source_contains_no_owner_specific_path(self):
        text = (ROOT / "bin" / "eve_bootstrap.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"/Users/(?!example(?:/|$)|test(?:/|$)|user(?:/|$))[^/]+/", text))
        self.assertNotIn("Eden", text)
        self.assertNotIn('"/tmp/eve_bootstrap_pycache"', text)


if __name__ == "__main__":
    unittest.main()
