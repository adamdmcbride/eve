import importlib.util
import re
import tempfile
import unittest
from pathlib import Path


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

    def test_install_plan_is_locked_and_does_not_install_a_daemon(self):
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
        self.assertEqual([str(root / ".venv/bin/python"), str(root / "eve.py"), "runtime", "sync"], plan[1])
        self.assertEqual(
            [str(root / ".venv/bin/python"), str(root / "eve.py"), "runtime", "truth", "--json"],
            plan[2],
        )
        self.assertFalse(any("daemon" in part for command in plan for part in command))

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

    def test_skipped_runtime_sync_is_not_reported_as_completed(self):
        message = "\n".join(eve_bootstrap.completion_lines(runtime_synced=False))
        self.assertIn("intentionally not created", message)
        self.assertNotIn("runtime mirror are ready", message)

    def test_public_bootstrap_source_contains_no_owner_specific_path(self):
        text = (ROOT / "bin" / "eve_bootstrap.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"/Users/(?!example(?:/|$)|test(?:/|$)|user(?:/|$))[^/]+/", text))
        self.assertNotIn("Eden", text)


if __name__ == "__main__":
    unittest.main()
