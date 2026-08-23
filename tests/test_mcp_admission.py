import unittest

import eve


class McpAdmissionChecklistTests(unittest.TestCase):
    def test_incomplete_candidate_is_blocked_with_missing_fields(self) -> None:
        report = eve.evaluate_mcp_admission_request(
            {
                "candidate_id": "calendar-mcp",
                "source": "local-test",
                "purpose": "Try a calendar MCP candidate.",
                "tools": ["calendar.read"],
            }
        )

        self.assertEqual("blocked", report["status"])
        missing_fields = {item["field"] for item in report["missing"]}
        self.assertIn("data_boundary", missing_fields)
        self.assertIn("filesystem_scope", missing_fields)
        self.assertIn("credential_scope", missing_fields)
        self.assertIn("tool_manifest", missing_fields)
        self.assertIn("verification_command", missing_fields)
        self.assertIn("rollback", missing_fields)
        self.assertFalse(report["enabled_for_eve"])
        self.assertFalse(report["adds_chat_lane"])

    def test_complete_read_only_candidate_is_ready_for_openclaw_admission_record(self) -> None:
        report = eve.evaluate_mcp_admission_request(
            {
                "candidate_id": "calendar-mcp",
                "name": "Calendar MCP",
                "source": "local calendar server",
                "purpose": "Read upcoming calendar context after existing local calendar checks are insufficient.",
                "permission_level": "pending_review",
                "data_boundary": "calendar metadata only",
                "filesystem_scope": "none",
                "network_scope": "loopback only",
                "credential_scope": "uses existing local account; no new secrets",
                "tools": ["calendar.read:read"],
                "logging_evidence": ".eve/mcp_admission_audit.jsonl",
                "verification_command": "python3 eve.py calendar read --json",
                "rollback": "Disable the calendar MCP server in the OpenClaw profile.",
                "noninteractive_policy": "fail",
                "owner_review": "codex_preflight",
            }
        )

        self.assertEqual("ready_for_admission_record", report["status"])
        self.assertTrue(report["ok"])
        self.assertFalse(report["enabled_for_eve"])
        self.assertFalse(report["adds_chat_lane"])
        self.assertEqual("openclaw_body_bus", report["body_bus_layer"])
        self.assertIn("openclaw admission create", report["candidate"]["admission_record"])

    def test_noninteractive_allow_blocks_candidate(self) -> None:
        report = eve.evaluate_mcp_admission_request(
            {
                "candidate_id": "calendar-mcp",
                "name": "Calendar MCP",
                "source": "local calendar server",
                "purpose": "Read upcoming calendar context.",
                "permission_level": "pending_review",
                "data_boundary": "calendar metadata only",
                "filesystem_scope": "none",
                "network_scope": "loopback only",
                "credential_scope": "no new secrets",
                "tools": ["calendar.read:read"],
                "logging_evidence": ".eve/mcp_admission_audit.jsonl",
                "verification_command": "python3 eve.py calendar read --json",
                "rollback": "Disable the MCP profile.",
                "noninteractive_policy": "allow",
                "owner_review": "codex_preflight",
            }
        )

        self.assertEqual("blocked", report["status"])
        self.assertIn("noninteractive_policy", {item["field"] for item in report["blockers"]})

    def test_destructive_tools_require_specific_approval_or_blocked(self) -> None:
        report = eve.evaluate_mcp_admission_request(
            {
                "candidate_id": "disk-mcp",
                "name": "Disk MCP",
                "source": "local disk server",
                "purpose": "Inspect disk operations.",
                "permission_level": "pending_review",
                "data_boundary": "local disk metadata and actions",
                "filesystem_scope": "/Users/example",
                "network_scope": "none",
                "credential_scope": "no new secrets",
                "tools": ["disk.erase:destructive"],
                "logging_evidence": ".eve/mcp_admission_audit.jsonl",
                "verification_command": "python3 eve.py mcp admission --help",
                "rollback": "Remove the disk MCP server from the profile.",
                "noninteractive_policy": "fail",
                "owner_review": "codex_preflight",
            }
        )

        self.assertEqual("blocked", report["status"])
        self.assertIn("permission_level", {item["field"] for item in report["blockers"]})


if __name__ == "__main__":
    unittest.main()
