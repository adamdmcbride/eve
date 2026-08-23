import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import eve_openclaw


SANDBOX_OUTPUT = """
[state/db] skipped permission hardening for /private/tmp/eve-test-user/.openclaw-eve-repair/state: Error: EPERM: operation not permitted, chmod '/private/tmp/eve-test-user/.openclaw-eve-repair/state'
{
  "valid": false,
  "path": "/private/tmp/eve-test-user/.openclaw-eve-repair/openclaw.json",
  "issues": [
    {
      "path": "plugins.allow",
      "message": "plugin llama-cpp: runtime extension entry not found: ./dist/index.js"
    }
  ]
}
"""

SANDBOX_MEMORY_OUTPUT = """
[state/db] skipped permission hardening for /private/tmp/eve-test-user/.openclaw-eve-repair/state: Error: EPERM: operation not permitted, chmod '/private/tmp/eve-test-user/.openclaw-eve-repair/state'
OpenClaw does not know the command "memory".
Try: openclaw --profile eve-repair --help
"""

SANDBOX_GATEWAY_OUTPUT = """
Runtime: running (pid 54154, state active)
Listening: 127.0.0.1:19011, [::1]:19011
Connectivity probe: failed connect EPERM 127.0.0.1:19011
"""


class OpenClawValidationEnvironmentTests(unittest.TestCase):
    def test_restricted_runtime_extension_false_negative_is_inconclusive(self) -> None:
        fields = eve_openclaw.openclaw_config_validation_fields(
            {
                "valid": False,
                "path": "/tmp/openclaw.json",
                "issues": [
                    {
                        "path": "plugins.allow",
                        "message": "plugin llama-cpp: runtime extension entry not found: ./dist/index.js",
                    }
                ],
            },
            returncode=1,
            output=SANDBOX_OUTPUT,
        )

        self.assertIsNone(fields["config_valid"])
        self.assertFalse(fields["config_validation_authoritative"])
        self.assertTrue(fields["config_validation_environment_limited"])
        self.assertIn("inconclusive", fields["config_validation_summary"])

    def test_same_plugin_issue_without_permission_signature_is_a_real_failure(self) -> None:
        fields = eve_openclaw.openclaw_config_validation_fields(
            {
                "valid": False,
                "issues": [
                    {
                        "path": "plugins.allow",
                        "message": "plugin llama-cpp: runtime extension entry not found: ./dist/index.js",
                    }
                ],
            },
            returncode=1,
            output="plugin validation failed",
        )

        self.assertFalse(fields["config_valid"])
        self.assertTrue(fields["config_validation_authoritative"])
        self.assertFalse(fields["config_validation_environment_limited"])

    def test_restricted_probe_does_not_hide_an_unrelated_config_issue(self) -> None:
        fields = eve_openclaw.openclaw_config_validation_fields(
            {
                "valid": False,
                "issues": [
                    {
                        "path": "plugins.allow",
                        "message": "plugin llama-cpp: runtime extension entry not found: ./dist/index.js",
                    },
                    {"path": "gateway.bind", "message": "invalid bind mode"},
                ],
            },
            returncode=1,
            output=SANDBOX_OUTPUT,
        )

        self.assertFalse(fields["config_valid"])
        self.assertTrue(fields["config_validation_authoritative"])
        self.assertFalse(fields["config_validation_environment_limited"])

    def test_inconclusive_probe_preserves_last_authoritative_result(self) -> None:
        prior = dict(eve_openclaw.DEFAULT_OPENCLAW_STATUS)
        prior.update(
            {
                "config_valid": True,
                "config_validation_authoritative": True,
                "config_validation_checked_at": "2026-08-23T16:57:00+00:00",
                "config_validation_last_authoritative_valid": True,
                "config_validation_last_authoritative_checked_at": "2026-08-23T16:57:00+00:00",
            }
        )
        inconclusive = eve_openclaw.openclaw_config_validation_fields(
            {
                "valid": False,
                "issues": [
                    {
                        "path": "plugins.allow",
                        "message": "plugin llama-cpp: runtime extension entry not found: ./dist/index.js",
                    }
                ],
            },
            returncode=1,
            output=SANDBOX_OUTPUT,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            profile_path = workspace / "openclaw.json"
            profile_path.write_text("{}", encoding="utf-8")
            with patch.object(eve_openclaw, "load_openclaw_status", return_value=prior), patch.object(
                eve_openclaw, "load_openclaw_sync_history", return_value=[]
            ), patch.object(eve_openclaw, "openclaw_command", return_value="/opt/homebrew/bin/openclaw"), patch.object(
                eve_openclaw, "openclaw_command_available", return_value=True
            ), patch.object(eve_openclaw, "openclaw_workspace", return_value=workspace), patch.object(
                eve_openclaw, "openclaw_profile_config_path", return_value=profile_path
            ), patch.object(eve_openclaw, "gateway_reachable", return_value=True), patch.object(
                eve_openclaw, "probe_openclaw_config_validation", return_value=inconclusive
            ):
                status = eve_openclaw.collect_openclaw_status(
                    {"openclaw_enabled": True},
                    include_config_probe=True,
                )

        self.assertTrue(status["config_valid"])
        self.assertFalse(status["config_validation_authoritative"])
        self.assertTrue(status["config_validation_environment_limited"])
        self.assertTrue(status["config_validation_last_authoritative_valid"])
        self.assertEqual(
            "2026-08-23T16:57:00+00:00",
            status["config_validation_last_authoritative_checked_at"],
        )
        self.assertNotIn("profile is invalid", status["summary"])

    def test_without_prior_truth_summary_says_inconclusive_not_invalid(self) -> None:
        status = dict(eve_openclaw.DEFAULT_OPENCLAW_STATUS)
        status.update(
            {
                "enabled": True,
                "command_available": True,
                "installed": True,
                "config_valid": None,
                "config_validation_environment_limited": True,
                "config_validation_summary": "restricted probe could not resolve an extension",
            }
        )

        summary = eve_openclaw.build_openclaw_summary(status)

        self.assertIn("inconclusive, not failed", summary)
        self.assertNotIn("profile is invalid", summary)

    def test_hidden_memory_command_under_restriction_is_inconclusive(self) -> None:
        fields = eve_openclaw.openclaw_memory_status_fields(
            None,
            returncode=1,
            output=SANDBOX_MEMORY_OUTPUT,
        )

        self.assertIsNone(fields["memory_status_ok"])
        self.assertIsNone(fields["memory_capability_available"])
        self.assertEqual("inconclusive", fields["memory_status_severity"])
        self.assertFalse(fields["memory_probe_authoritative"])
        self.assertTrue(fields["memory_probe_environment_limited"])

    def test_restricted_gateway_and_memory_probes_preserve_host_truth(self) -> None:
        prior = dict(eve_openclaw.DEFAULT_OPENCLAW_STATUS)
        prior.update(
            {
                "updated_at": "2026-08-23T17:08:00+00:00",
                "gateway_reachable": True,
                "gateway_status_ok": True,
                "gateway_probe_authoritative": True,
                "gateway_last_authoritative_reachable": True,
                "gateway_last_authoritative_checked_at": "2026-08-23T17:08:00+00:00",
                "last_memory_probe_at": "2026-08-23T17:08:02+00:00",
                "memory_status_ok": True,
                "memory_status_severity": "ready",
                "memory_capability_available": True,
                "memory_status_summary": "Memory search ready via qmd; 120 indexed file(s), 120 chunk(s).",
                "memory_provider": "qmd",
                "memory_model": "qmd",
                "memory_files": 120,
                "memory_chunks": 120,
                "memory_probe_authoritative": True,
                "memory_last_authoritative_status_ok": True,
                "memory_last_authoritative_probe_at": "2026-08-23T17:08:02+00:00",
            }
        )
        restricted_memory = eve_openclaw.openclaw_memory_status_fields(
            None,
            returncode=1,
            output=SANDBOX_MEMORY_OUTPUT,
        )
        restricted_gateway = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout=SANDBOX_GATEWAY_OUTPUT,
            stderr="",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            profile_path = workspace / "openclaw.json"
            profile_path.write_text("{}", encoding="utf-8")
            with patch.object(eve_openclaw, "load_openclaw_status", return_value=prior), patch.object(
                eve_openclaw, "load_openclaw_sync_history", return_value=[]
            ), patch.object(eve_openclaw, "openclaw_command", return_value="/opt/homebrew/bin/openclaw"), patch.object(
                eve_openclaw, "openclaw_command_available", return_value=True
            ), patch.object(eve_openclaw, "openclaw_workspace", return_value=workspace), patch.object(
                eve_openclaw, "openclaw_profile_config_path", return_value=profile_path
            ), patch.object(eve_openclaw, "gateway_reachable", return_value=False), patch.object(
                eve_openclaw, "run", return_value=restricted_gateway
            ), patch.object(
                eve_openclaw, "probe_openclaw_memory_status", return_value=restricted_memory
            ):
                status = eve_openclaw.collect_openclaw_status(
                    {"openclaw_enabled": True},
                    include_gateway_probe=True,
                    include_config_probe=False,
                    include_memory_probe=True,
                )

        self.assertTrue(status["gateway_reachable"])
        self.assertTrue(status["gateway_status_ok"])
        self.assertFalse(status["gateway_probe_authoritative"])
        self.assertTrue(status["gateway_probe_environment_limited"])
        self.assertTrue(status["memory_status_ok"])
        self.assertTrue(status["memory_capability_available"])
        self.assertEqual("qmd", status["memory_provider"])
        self.assertEqual(120, status["memory_files"])
        self.assertFalse(status["memory_probe_authoritative"])
        self.assertTrue(status["memory_probe_environment_limited"])
        self.assertNotIn("degraded", status["summary"])


if __name__ == "__main__":
    unittest.main()
