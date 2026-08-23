import subprocess
import unittest
from unittest.mock import patch

import eve_openclaw


class OpenClawConfigHealthTests(unittest.TestCase):
    def test_invalid_profile_preserves_structured_plugin_issue(self) -> None:
        fields = eve_openclaw.openclaw_config_validation_fields(
            {
                "valid": False,
                "path": "/tmp/openclaw.json",
                "issues": [
                    {
                        "path": "plugins.allow",
                        "message": "plugin llama-cpp: runtime extension entry not found",
                    }
                ],
            }
        )

        self.assertFalse(fields["config_valid"])
        self.assertEqual("/tmp/openclaw.json", fields["config_validation_path"])
        self.assertEqual("plugins.allow", fields["config_validation_issues"][0]["path"])
        self.assertIn("llama-cpp", fields["config_validation_summary"])

    def test_valid_profile_reports_current_validation_evidence(self) -> None:
        fields = eve_openclaw.openclaw_config_validation_fields(
            {"valid": True, "path": "/tmp/openclaw.json", "issues": []},
            returncode=0,
        )

        self.assertTrue(fields["config_valid"])
        self.assertEqual([], fields["config_validation_issues"])
        self.assertIn("passed", fields["config_validation_summary"])

    def test_invalid_profile_takes_priority_over_reachable_gateway_summary(self) -> None:
        status = dict(eve_openclaw.DEFAULT_OPENCLAW_STATUS)
        status.update(
            {
                "enabled": True,
                "command_available": True,
                "installed": True,
                "gateway_reachable": True,
                "config_valid": False,
                "config_validation_summary": "plugins.allow: missing runtime extension",
                "last_sync_ok": True,
                "last_sync_summary": "sync completed",
            }
        )

        summary = eve_openclaw.build_openclaw_summary(status)

        self.assertIn("profile is invalid", summary)
        self.assertIn("plugins.allow", summary)
        self.assertNotIn("recovered cleanly", summary)

    def test_probe_uses_active_profile_and_parses_noisy_json(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                "permission hardening warning\n"
                '{"valid":false,"path":"/tmp/openclaw.json","issues":'
                '[{"path":"plugins.allow","message":"missing extension"}]}\n'
            ),
            stderr="",
        )
        with patch.object(eve_openclaw, "openclaw_command", return_value="/opt/homebrew/bin/openclaw"), patch.object(
            eve_openclaw, "run", return_value=completed
        ) as run_probe:
            fields = eve_openclaw.probe_openclaw_config_validation(
                {"openclaw_profile": "eve-repair"}
            )

        self.assertFalse(fields["config_valid"])
        self.assertEqual(
            [
                "/opt/homebrew/bin/openclaw",
                "--profile",
                "eve-repair",
                "config",
                "validate",
                "--json",
            ],
            run_probe.call_args.args[0],
        )


if __name__ == "__main__":
    unittest.main()
