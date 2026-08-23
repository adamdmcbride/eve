import importlib.util
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "bin" / "eve_copilotkit_probe.py"
SPEC = importlib.util.spec_from_file_location("eve_copilotkit_probe", SCRIPT_PATH)
copilotkit_probe = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(copilotkit_probe)


class CopilotKitProbeTests(unittest.TestCase):
    def test_package_metadata_requires_mit_packages(self) -> None:
        def fake_npm_field(package: str, field: str, timeout: int = 45) -> dict:
            return {
                "status": "ok",
                "package": package,
                "field": field,
                "value": "1.57.1" if field == "version" else "MIT",
                "returncode": 0,
                "stderr_tail": "",
            }

        with patch.object(copilotkit_probe, "npm_field", side_effect=fake_npm_field):
            metadata = copilotkit_probe.package_metadata()

        self.assertEqual("ready", metadata["status"])
        self.assertTrue(metadata["all_mit"])
        self.assertEqual(
            {"@copilotkit/runtime", "@copilotkit/react-core", "@copilotkit/react-ui"},
            {item["package"] for item in metadata["packages"]},
        )

    def test_node_import_probe_reads_installed_package_metadata_without_repo_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lab_root = Path(tmp)
            package_dir = lab_root / "node_modules" / "@copilotkit" / "runtime"
            package_dir.mkdir(parents=True)
            (package_dir / "package.json").write_text(
                json.dumps({"version": "1.57.1", "license": "MIT"}) + "\n",
                encoding="utf-8",
            )

            def fake_command(command, *, cwd=None, timeout=60, env=None):
                return {
                    "status": "ok",
                    "command": command,
                    "returncode": 0,
                    "stdout_tail": json.dumps(
                        {
                            "@copilotkit/runtime": {
                                "version": "1.57.1",
                                "license": "MIT",
                                "import_ok": True,
                                "export_sample": ["CopilotRuntime"],
                            },
                            "__adapter_probe": {
                                "status": "ready",
                                "openai_adapter_constructed": True,
                                "copilot_runtime_constructed": True,
                            },
                        }
                    ),
                    "stderr_tail": "",
                }

            with patch.object(copilotkit_probe, "command_result", side_effect=fake_command):
                report = copilotkit_probe.node_import_probe(lab_root)

        self.assertEqual("ready", report["status"])
        self.assertTrue(report["packages"]["@copilotkit/runtime"]["import_ok"])
        self.assertEqual("ready", report["adapter_probe"]["status"])

    def test_build_report_keeps_copilotkit_lab_only_and_adapter_gated(self) -> None:
        args = Namespace(
            lab_root="/tmp/eve-copilotkit-test",
            mirror_path="/tmp/eve-copilotkit-test.git",
            mirror=False,
            install_npm_lab=False,
            import_probe=False,
            probe_eve_backend=False,
            eve_base_url="http://127.0.0.1:8797/v1",
            npm_timeout=1,
            mirror_timeout=1,
            eve_timeout=1,
        )
        with patch.object(copilotkit_probe, "package_metadata", return_value={"status": "ready"}), patch.object(
            copilotkit_probe, "mirror_status", return_value={"status": "missing"}
        ):
            report = copilotkit_probe.build_report(args)

        self.assertEqual("ready", report["status"])
        self.assertTrue(report["boundary"]["lab_only"])
        self.assertFalse(report["boundary"]["changes_live_chat_ui"])
        self.assertTrue(report["fit_for_eve"]["requires_adapter_before_live_chat"])


if __name__ == "__main__":
    unittest.main()
