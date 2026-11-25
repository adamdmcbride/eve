import subprocess
import tempfile
import unittest
from pathlib import Path

import eve_capability_intelligence as intelligence


class HermesAutomationRunner:
    def __init__(self, *, cron_text: str, hooks_text: str, returncode: int = 0):
        self.cron_text = cron_text
        self.hooks_text = hooks_text
        self.returncode = returncode
        self.environments = []

    def __call__(self, command, timeout, env=None):
        del timeout
        args = [str(value) for value in command]
        self.environments.append(dict(env or {}))
        if args[-1] == "--version":
            return subprocess.CompletedProcess(args, 0, "Hermes Agent v0.20.5\n", "")
        if args[-3:] == ["cron", "list", "--all"]:
            return subprocess.CompletedProcess(args, self.returncode, self.cron_text, "failed" if self.returncode else "")
        if args[-2:] == ["hooks", "list"]:
            return subprocess.CompletedProcess(args, self.returncode, self.hooks_text, "failed" if self.returncode else "")
        raise AssertionError(f"unexpected command: {args}")


class HermesRuntimeReceiptTests(unittest.TestCase):
    def _snapshot(self, runner):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = root / "profile"
            source = root / "source"
            profile.mkdir()
            source.mkdir()
            (profile / "config.yaml").write_text("model:\n  default: eve-deep\n", encoding="utf-8")
            snapshot = intelligence.collect_hermes_snapshot(
                profile_home=profile,
                source_root=source,
                inventory={
                    "hermes_status": {"status": "available", "source_head": "abc"},
                    "serious_learning_route": "local_64k_lab_constrained_json",
                    "capability_families": [
                        {
                            "id": "cron_hooks",
                            "status": "configured",
                            "eve_role": "Do not let Hermes schedule Eve directly.",
                            "evidence": ["stale parser output"],
                        }
                    ],
                },
                feature_policy={"status": "watch", "features": []},
                command="hermes",
                runner=runner,
            )
            expected_home = str(profile)
        return snapshot, expected_home

    def test_empty_live_receipts_override_stale_configured_family(self):
        runner = HermesAutomationRunner(
            cron_text="No scheduled jobs.\nCreate one with 'hermes cron create ...'.\n",
            hooks_text=(
                "No shell hooks or outbound webhooks configured in ~/.hermes/config.yaml.\n"
                "See the documentation for examples.\n"
            ),
        )
        snapshot, expected_home = self._snapshot(runner)

        self.assertTrue(snapshot["automation_receipts"]["all_observed"])
        self.assertFalse(snapshot["automation_receipts"]["any_configured"])
        self.assertEqual("empty", snapshot["automation_receipts"]["cron"]["status"])
        self.assertEqual("empty", snapshot["automation_receipts"]["hooks"]["status"])
        scoped_environments = [env for env in runner.environments if env.get("HERMES_HOME")]
        self.assertEqual(2, len(scoped_environments))
        self.assertTrue(all(env.get("HERMES_HOME") == expected_home for env in scoped_environments))
        self.assertNotIn("No scheduled jobs", repr(snapshot))
        self.assertNotIn("outbound webhooks", repr(snapshot))

        reviews = intelligence.build_subsystem_feature_family_reviews({"hermes": snapshot})
        cron_review = next(item for item in reviews if item["id"] == "hermes:cron_hooks")
        self.assertEqual("defer", cron_review["decision"])
        self.assertEqual("not_configured_live_receipt", cron_review["current_state"])
        self.assertEqual(
            ["live_cron_status=empty", "live_hooks_status=empty", "receipt_content=hash_only"],
            cron_review["evidence"],
        )

        attestations = intelligence.build_effective_configuration_attestations({"hermes": snapshot})
        receipt = next(item for item in attestations if item["id"] == "hermes:automation_absence")
        self.assertEqual("effective", receipt["status"])
        self.assertTrue(receipt["consequence"]["direct_automation_absent"])

    def test_nonempty_receipts_fail_closed_without_retaining_content(self):
        runner = HermesAutomationRunner(
            cron_text="daily-secret-job with private payload\n",
            hooks_text="pre_tool hook /private/path/do-not-retain.sh\n",
        )
        snapshot, _ = self._snapshot(runner)

        self.assertTrue(snapshot["automation_receipts"]["any_configured"])
        self.assertNotIn("daily-secret-job", repr(snapshot))
        self.assertNotIn("do-not-retain", repr(snapshot))
        attestations = intelligence.build_effective_configuration_attestations({"hermes": snapshot})
        receipt = next(item for item in attestations if item["id"] == "hermes:automation_absence")
        self.assertEqual("degraded", receipt["status"])
        self.assertFalse(receipt["consequence"]["direct_automation_absent"])

    def test_failed_commands_remain_unverified(self):
        runner = HermesAutomationRunner(cron_text="", hooks_text="", returncode=2)
        snapshot, _ = self._snapshot(runner)

        self.assertFalse(snapshot["automation_receipts"]["all_observed"])
        self.assertFalse(snapshot["automation_receipts"]["any_configured"])
        attestations = intelligence.build_effective_configuration_attestations({"hermes": snapshot})
        receipt = next(item for item in attestations if item["id"] == "hermes:automation_absence")
        self.assertEqual("configured_unverified", receipt["status"])


if __name__ == "__main__":
    unittest.main()
