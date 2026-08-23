import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import eve_economy


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class EconomicSelfSustainabilityTests(unittest.TestCase):
    def test_eve_py_economy_bridge_uses_proposal_only_engine(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                sys.executable,
                str(root / "eve.py"),
                "economy",
                "resources",
                "--no-save",
                "--json",
            ],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "proposal_only")
        self.assertFalse(payload["summary"]["spending_allowed"])
        self.assertFalse(payload["summary"]["payment_allowed"])
        self.assertFalse(payload["summary"]["external_action_allowed"])

    def test_resource_plan_is_proposal_only_and_blocks_financial_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_dir = root / ".eve"
            write_json(
                app_dir / "model_suitability" / "latest.json",
                {"status": "watch", "summary": "fast lane needs runtime headroom", "recommendations": ["tune context"]},
            )
            write_json(
                app_dir / "whole_system_evals" / "latest.json",
                {"status": "degraded", "average_score": 4.2, "failing_check_count": 2},
            )
            write_json(app_dir / "safety_drills" / "latest.json", {"status": "passed", "average_score": 5.0})
            write_json(app_dir / "capability_matrix.json", {"summary": {"verified": 3, "callable": 5, "open_gaps": 1}})

            plan = eve_economy.build_resource_plan(root, runtime_app_dir=app_dir)

            self.assertEqual(plan["status"], "proposal_only")
            self.assertFalse(plan["summary"]["external_action_allowed"])
            self.assertFalse(plan["summary"]["spending_allowed"])
            self.assertFalse(plan["summary"]["payment_allowed"])
            self.assertIn("spend_money", plan["boundary"]["blocked_actions"])
            self.assertIn("access_bank_or_brokerage", plan["boundary"]["blocked_actions"])
            self.assertGreaterEqual(len(plan["resource_needs"]), 4)
            self.assertTrue(all(item["approval_required"] for item in plan["resource_needs"]))

    def test_value_map_counts_only_verified_capabilities_as_sellable_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_dir = root / ".eve"
            write_json(
                app_dir / "capability_matrix.json",
                {
                    "capabilities": [
                        {
                            "id": "coder.git_status",
                            "name": "Git status",
                            "category": "coder_mode",
                            "verified": True,
                            "callable": True,
                            "safe_for_autonomy": True,
                        },
                        {
                            "id": "action.agent_capability_scout",
                            "name": "Capability scout",
                            "category": "agent_integration",
                            "verified": True,
                            "callable": True,
                        },
                        {
                            "id": "coder.apply_patch",
                            "name": "Apply patch",
                            "category": "coder_mode",
                            "verified": False,
                            "callable": True,
                        },
                    ]
                },
            )

            value_map = eve_economy.build_value_map(root, runtime_app_dir=app_dir)

            self.assertEqual(value_map["status"], "proposal_only")
            self.assertEqual(value_map["summary"]["verified_capability_count"], 2)
            self.assertEqual(value_map["summary"]["unverified_callable_count"], 1)
            self.assertFalse(value_map["summary"]["external_action_allowed"])
            self.assertIn("coder.apply_patch", {item["id"] for item in value_map["not_sellable_yet"]})
            self.assertTrue(
                all("Draft/sample only" in str(offer["permission_boundary"]) for offer in value_map["offers"])
            )

    def test_outreach_draft_never_sends_without_exact_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_dir = root / ".eve"
            write_json(app_dir / "capability_matrix.json", {"capabilities": []})

            draft = eve_economy.build_outreach_draft(
                "agent capability safety audit",
                "email",
                root,
                runtime_app_dir=app_dir,
            )

            self.assertEqual(draft["status"], "draft_only")
            self.assertFalse(draft["send_allowed"])
            self.assertTrue(draft["exact_user_approval_required"])
            self.assertIn("send_unapproved_outreach", draft["boundary"]["blocked_actions"])
            self.assertIn("No implied contract", " ".join(draft["claims_checklist"]))

    def test_save_record_writes_economy_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            path = eve_economy.save_record(root, "resource_plan.json", {"id": "x"})

            self.assertEqual(path.resolve(), (root / ".eve" / "economy" / "resource_plan.json").resolve())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["id"], "x")


if __name__ == "__main__":
    unittest.main()
