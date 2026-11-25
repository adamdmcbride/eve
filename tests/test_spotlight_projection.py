from __future__ import annotations

import json
import unittest

import eve_spotlight_projection as projection


class SpotlightProjectionTests(unittest.TestCase):
    def monitor(self) -> dict:
        return {
            "workspace": {
                "active_goals": ["Finish the bounded upgrade and verify its effects."],
                "workspace_state": {"focus": "fallback focus"},
            },
            "autonomy": {"agenda": {"current_focus": "agenda focus"}},
            "homeostasis": {"next_regulation_step": "Run the focused verification suite."},
            "operations": {
                "actions": [
                    {
                        "action": "native_capability_canary",
                        "tree_status": "SUCCESS",
                        "verification_ok": True,
                        "result_ok": True,
                        "typed_contract_ok": True,
                        "updated_at": "2026-08-23T18:00:00+00:00",
                    }
                ]
            },
        }

    def test_projection_requires_backend_approval(self) -> None:
        result = projection.build_spotlight_projection(self.monitor(), approved=False)
        self.assertFalse(result["approved"])
        self.assertEqual([], result["records"])

    def test_projection_is_bounded_derived_and_content_minimized(self) -> None:
        result = projection.build_spotlight_projection(
            self.monitor(),
            approved=True,
            approval_source="operator_request_2026-08-23",
        )
        self.assertEqual("eve_local_backend", result["source_authority"])
        self.assertFalse(result["canonical"])
        self.assertLessEqual(result["record_count"], 3)
        self.assertEqual(
            {"current_focus", "commitment_summary", "evidence_summary"},
            {item["source_kind"] for item in result["records"]},
        )
        for record in result["records"]:
            self.assertEqual("spotlight_approved", record["approval"])
            self.assertEqual(64, len(record["opaque_id"]))
            self.assertEqual(64, len(record["source_revision"]))
        serialized = json.dumps(result).lower()
        self.assertNotIn("transcript", serialized.replace("raw_transcripts_included", ""))
        self.assertFalse(result["raw_transcripts_included"])
        self.assertFalse(result["canonical_identifiers_included"])

    def test_sensitive_or_path_bearing_summary_is_omitted(self) -> None:
        monitor = self.monitor()
        monitor["workspace"]["active_goals"] = ["Inspect /Users/example/.eve/private.json"]
        monitor["workspace"]["workspace_state"]["focus"] = "api_key=secret"
        monitor["autonomy"]["agenda"]["current_focus"] = "authorization: bearer token"
        result = projection.build_spotlight_projection(monitor, approved=True)
        kinds = {item["source_kind"] for item in result["records"]}
        self.assertNotIn("current_focus", kinds)
        self.assertNotIn("/users/", json.dumps(result).lower())
        self.assertNotIn("api_key", json.dumps(result).lower())

    def test_unverified_action_is_not_indexed(self) -> None:
        monitor = self.monitor()
        monitor["operations"]["actions"][0]["verification_ok"] = False
        result = projection.build_spotlight_projection(monitor, approved=True)
        self.assertNotIn(
            "evidence_summary",
            {item["source_kind"] for item in result["records"]},
        )


if __name__ == "__main__":
    unittest.main()
