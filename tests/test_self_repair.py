import io
import json
import unittest
from unittest.mock import patch

import eve


def sample_runtime_truth():
    return {
        "status": "ok",
        "daemon_runtime_running": True,
        "needs_runtime_sync": False,
        "needs_state_reconcile": False,
        "files": [
            {
                "label": "eve.py",
                "matches": True,
                "runtime_older_than_source": False,
                "source_path": "/repo/eve.py",
                "runtime_path": "/runtime/eve.py",
            }
        ],
        "state_authority": {"status": "ok"},
    }


class EveSelfRepairTests(unittest.TestCase):
    def test_self_repair_plan_builds_governed_code_patch(self):
        plan = eve.build_self_repair_plan(
            "Fix a bounded Eve repair regression.",
            runtime_truth=sample_runtime_truth(),
            safety_drills={"status": "passed"},
            safety_drills_path=".eve/safety_drills/latest.json",
            code_sessions=[],
            code_proposals=[],
        )

        self.assertEqual("eve_self_repair_plan.v1", plan["schema_version"])
        self.assertEqual("ready", plan["status"])
        self.assertFalse(plan["promotes_or_deploys_code"])
        self.assertFalse(plan["live_routing_changed"])

        reviewed = plan["reviewed_code_patch_proposal"]
        self.assertEqual("CodePatchProposal", reviewed["type"])
        self.assertEqual("accept", reviewed["review"]["decision"])
        self.assertEqual("needs_queue", plan["code_lifecycle"]["status"])

        payload = reviewed["payload"]
        self.assertIn("eve.py", payload["files_changed"])
        self.assertIn("python3 -m py_compile eve.py", payload["tests"])
        self.assertTrue(payload["rollback_plan"])
        metadata = payload["metadata"]
        self.assertTrue(metadata["requires_approval"])
        self.assertTrue(metadata["requires_canary"])
        self.assertFalse(metadata["deploys_code"])
        self.assertFalse(metadata["adds_chat_lane"])
        self.assertTrue(metadata["codex_is_separate_operator"])

    def test_self_repair_plan_tracks_runtime_cautions_as_operational_repair(self):
        runtime_truth = sample_runtime_truth()
        runtime_truth["status"] = "runtime_source_mismatch"
        runtime_truth["needs_runtime_sync"] = True

        plan = eve.build_self_repair_plan(
            "Investigate runtime drift before repair.",
            runtime_truth=runtime_truth,
            safety_drills={},
            code_sessions=[],
            code_proposals=[],
        )

        self.assertEqual("watch", plan["status"])
        self.assertEqual("operational", plan["repair_kind"])
        self.assertNotIn("reviewed_code_patch_proposal", plan)
        self.assertNotIn("code_patch_payload", plan)
        self.assertEqual("eve_operational_repair_plan.v1", plan["operational_repair_plan"]["schema_version"])
        cautions = plan["readiness"]["cautions"]
        self.assertIn("runtime_source_sync_needed_before_live_trust", cautions)
        self.assertIn("no_latest_safety_drills_artifact", cautions)
        self.assertEqual("watch", plan["operational_lifecycle"]["status"])
        commands = [item["command"] for item in plan["operational_repair_plan"]["commands"]]
        self.assertIn("python3 eve.py runtime sync", commands)
        self.assertEqual(2, commands.count("python3 eve.py runtime truth --json"))

    def test_self_repair_plan_tracks_eve_state_refresh_as_operational_repair(self):
        plan = eve.build_self_repair_plan(
            (
                "Operationally refresh Eve runtime state summaries: recompute "
                "cleanup_review_summary from the current system_snapshot and save state, "
                "without source code edits."
            ),
            files=[".eve/state.json", ".eve/system_snapshot.json"],
            tests=["python3 eve.py doctor"],
            diagnosis_only=True,
            runtime_truth=sample_runtime_truth(),
            safety_drills={"status": "passed"},
            safety_drills_path=".eve/safety_drills/latest.json",
            code_sessions=[],
            code_proposals=[],
        )

        self.assertEqual("operational", plan["repair_kind"])
        self.assertEqual("diagnosis_only", plan["mode"])
        self.assertNotIn("reviewed_code_patch_proposal", plan)
        self.assertNotIn("code_patch_payload", plan)
        self.assertEqual("eve_operational_repair_plan.v1", plan["operational_repair_plan"]["schema_version"])
        commands = [item["command"] for item in plan["operational_repair_plan"]["commands"]]
        self.assertEqual(["python3 eve.py doctor"], commands)

    def test_cli_self_repair_plan_json_no_save(self):
        output = io.StringIO()
        with patch.object(eve, "runtime_source_truth_check", return_value=sample_runtime_truth()), patch.object(
            eve,
            "read_whole_system_json_artifact",
            return_value=({"status": "passed"}, ".eve/safety_drills/latest.json"),
        ), patch.object(eve, "list_code_sessions", return_value=[]), patch.object(
            eve,
            "read_governance_proposals",
            return_value=[],
        ), patch("sys.stdout", output):
            code = eve.main(
                [
                    "self-repair",
                    "plan",
                    "Fix a small self-repair bug.",
                    "--no-save",
                    "--json",
                ]
            )

        self.assertEqual(0, code)
        rendered = json.loads(output.getvalue())
        self.assertEqual("eve_self_repair_plan.v1", rendered["schema_version"])
        self.assertEqual("CodePatchProposal", rendered["reviewed_code_patch_proposal"]["type"])
        self.assertFalse(rendered["promotes_or_deploys_code"])

    def test_queue_self_repair_proposal_stays_in_governance_lifecycle(self):
        plan = eve.build_self_repair_plan(
            "Queue a bounded self-repair proposal.",
            runtime_truth=sample_runtime_truth(),
            safety_drills={"status": "passed"},
            code_sessions=[],
            code_proposals=[],
        )
        reviewed = plan["reviewed_code_patch_proposal"]

        with patch.object(eve, "append_governance_proposal", return_value=reviewed), patch.object(
            eve,
            "mirror_store_file_to_runtime",
            lambda _path: None,
        ):
            result = eve.queue_self_repair_code_patch_proposal(plan)

        self.assertTrue(result["stored"])
        self.assertEqual(reviewed["id"], result["proposal_id"])
        self.assertEqual("needs_approval", plan["code_lifecycle"]["status"])
        self.assertFalse(plan["code_lifecycle"]["deploys_code"])

    def test_queue_operational_self_repair_is_rejected_as_code_patch(self):
        runtime_truth = sample_runtime_truth()
        runtime_truth["status"] = "runtime_source_mismatch"
        runtime_truth["needs_runtime_sync"] = True

        plan = eve.build_self_repair_plan(
            "Repair runtime/source mismatch after active claims release.",
            runtime_truth=runtime_truth,
            safety_drills={"status": "passed"},
            code_sessions=[],
            code_proposals=[],
        )

        with self.assertRaisesRegex(ValueError, "Operational self-repair plans are not queued"):
            eve.queue_self_repair_code_patch_proposal(plan)


if __name__ == "__main__":
    unittest.main()
