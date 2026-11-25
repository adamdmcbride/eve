import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "public-release-audit.yml"
SBOM_WORKFLOW = ROOT / ".github" / "workflows" / "dependency-sbom-audit.yml"
CODEQL_WORKFLOW = ROOT / ".github" / "workflows" / "codeql.yml"
RELEASE_CONFIG = ROOT / "public_release.json"


class PublicWorkflowContractTests(unittest.TestCase):
    def test_security_workflows_are_required_release_controls(self):
        release_config = json.loads(RELEASE_CONFIG.read_text(encoding="utf-8"))
        required = set(release_config.get("required_files") or [])

        self.assertTrue(
            {
                ".github/dependabot.yml",
                ".github/workflows/codeql.yml",
                ".github/workflows/dependency-sbom-audit.yml",
                ".github/workflows/public-release-audit.yml",
            }
            <= required
        )

    def test_actions_are_immutable_and_workflow_permissions_are_read_only(self):
        for path in (WORKFLOW, SBOM_WORKFLOW):
            source = path.read_text(encoding="utf-8")
            uses = re.findall(r"uses:\s+([^\s]+)", source)

            self.assertTrue(uses, path)
            for action in uses:
                self.assertRegex(
                    action,
                    r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$",
                )
            self.assertIn("permissions:\n  contents: read", source)
            self.assertIn("cancel-in-progress: true", source)
            checkout_count = len(re.findall(r"uses:\s+actions/checkout@", source))
            self.assertGreater(checkout_count, 0)
            self.assertEqual(checkout_count, source.count("persist-credentials: false"))
            self.assertNotIn("pull_request_target:", source)
            self.assertNotIn("workflow_run:", source)
        self.assertIn(
            "tests.test_public_workflow_contract",
            WORKFLOW.read_text(encoding="utf-8"),
        )

    def test_linux_ci_covers_new_foundation_and_interface_seams(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        for module in (
            "tests.test_agui",
            "tests.test_chat_protocol",
            "tests.test_chat_followups",
            "tests.test_store",
            "tests.test_repository",
            "tests.test_database_lifecycle",
            "tests.test_tracing_contracts",
            "tests.test_performance",
            "tests.test_attachments",
            "tests.test_install_artifacts",
            "tests.test_monitor_projection",
            "tests.test_runtime_projection",
            "tests.test_sensory_sessions",
            "tests.test_http_headers",
            "tests.test_http_json",
            "tests.test_http_path",
            "tests.test_http_security",
            "tests.test_openai_compat",
            "tests.test_runtime_api",
        ):
            self.assertIn(module, source)

    def test_release_ci_round_trips_export_through_exact_manifest_verification(self):
        source = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("--write-manifest", source)
        self.assertIn("--export", source)
        self.assertIn("--verify-manifest", source)
        self.assertIn("--exact-tree", source)
        self.assertIn('${RUNNER_TEMP}/eve-public-manifest.json', source)
        self.assertIn('${RUNNER_TEMP}/eve-public-export', source)

    def test_macos_ci_uses_current_sdk_runner_and_native_contracts(self):
        source = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("macos-native-contracts:", source)
        self.assertIn("runs-on: macos-26", source)
        self.assertIn('"pytest==9.0.3"', source)
        self.assertIn("tests/test_eve_app_server.py", source)
        self.assertIn("tests/test_canonical_eve_app.py", source)
        self.assertIn("tests/test_macos_native_capabilities.py", source)

    def test_sbom_gate_is_read_only_default_branch_revalidation(self):
        source = SBOM_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("schedule:", source)
        self.assertIn("workflow_dispatch:", source)
        self.assertNotIn("pull_request:", source)
        self.assertNotIn("\n  push:", source)
        self.assertIn(
            "if: github.ref_name == github.event.repository.default_branch",
            source,
        )
        self.assertIn("/dependency-graph/sbom", source)
        self.assertIn("X-GitHub-Api-Version: 2026-03-10", source)
        self.assertIn("--max-filesize 26214400", source)
        self.assertIn("persist-credentials: false", source)
        self.assertIn("bin/eve_dependency_license_audit.py", source)
        self.assertIn('--source-revision "${GITHUB_SHA}"', source)

    def test_codeql_uses_one_minimal_sarif_upload_boundary(self):
        source = CODEQL_WORKFLOW.read_text(encoding="utf-8")
        uses = re.findall(r"uses:\s+([^\s]+)", source)

        self.assertEqual(len(uses), 3)
        for action in uses:
            self.assertRegex(
                action,
                r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?@[0-9a-f]{40}$",
            )
        self.assertEqual(source.count("persist-credentials: false"), 1)
        self.assertIn("push:", source)
        self.assertIn("pull_request:", source)
        self.assertIn("schedule:", source)
        self.assertIn("workflow_dispatch:", source)
        self.assertNotIn("pull_request_target:", source)
        self.assertNotIn("workflow_run:", source)
        self.assertIn("cancel-in-progress: true", source)
        self.assertIn("timeout-minutes: 20", source)
        self.assertIn("languages: python", source)
        self.assertIn("build-mode: none", source)

        write_permissions = re.findall(
            r"^\s+([a-z-]+): write\s*$",
            source,
            flags=re.MULTILINE,
        )
        self.assertEqual(write_permissions, ["security-events"])
        self.assertIn("contents: read", source)
        self.assertNotIn("actions: write", source)
        self.assertNotIn("checks: write", source)
        self.assertNotIn("id-token: write", source)
        self.assertNotIn("packages: write", source)
        self.assertNotIn("pull-requests: write", source)
        self.assertNotIn("\n        run:", source)

        codeql_actions = [
            action for action in uses if action.startswith("github/codeql-action/")
        ]
        self.assertEqual(len(codeql_actions), 2)
        self.assertTrue(codeql_actions[0].startswith("github/codeql-action/init@"))
        self.assertTrue(codeql_actions[1].startswith("github/codeql-action/analyze@"))
        self.assertEqual(
            codeql_actions[0].rsplit("@", 1)[1],
            codeql_actions[1].rsplit("@", 1)[1],
        )


if __name__ == "__main__":
    unittest.main()
