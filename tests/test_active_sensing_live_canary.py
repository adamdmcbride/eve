import json
import unittest

from bin import eve_active_sensing_live_canary as canary


class ActiveSensingLiveCanaryTests(unittest.TestCase):
    def clock(self, *values):
        remaining = iter(values)
        return lambda: next(remaining)

    def action_result(self, **overrides):
        result = {
            "action": "service_health_check",
            "execution_id": "exec-1",
            "status": "completed",
            "executed": True,
            "execution_tree_status": "SUCCESS",
            "execution_verification_ok": True,
            "execution_summary": "Read-only service-health action completed.",
        }
        result.update(overrides)
        return result

    def snapshot(self, **overrides):
        snapshot = {
            "timestamp": "2026-08-23T12:00:02+00:00",
            "eve_services": {
                "daemon": {"state": "active", "loaded": True},
                "model_watchdog": {"state": "active", "loaded": True},
            },
            "model_status": {
                "preferred_fast_model": "eve-fast",
                "preferred_deep_model": "eve-deep",
                "residency": {"both_preferred_loaded": True},
                "probes": {
                    "eve-fast": {"ok": True},
                    "eve-deep": {"ok": True},
                },
            },
        }
        snapshot.update(overrides)
        return snapshot

    def execute_canary(self, *, action=None, snapshot=None):
        return canary.run_canary(
            action_runner=lambda: action or self.action_result(),
            snapshot_collector=lambda: snapshot or self.snapshot(),
            now=self.clock(
                "2026-08-23T12:00:00+00:00",
                "2026-08-23T12:00:01+00:00",
            ),
        )

    def test_verified_action_and_later_snapshot_close_episode(self):
        report = self.execute_canary()
        rendered = json.dumps(report, sort_keys=True)

        self.assertEqual("closed_uncertainty_reduced", report["status"])
        self.assertTrue(report["verification_ok"])
        self.assertTrue(report["observation_collected"])
        self.assertTrue(report["observer_evidence_refreshed"])
        self.assertTrue(report["observation_after_verified_action"])
        self.assertEqual("operational_receipt", report["observation_outcome"])
        self.assertGreater(report["information_gain"], 0)
        self.assertTrue(report["consequence_qualified"])
        self.assertEqual(64, len(report["execution_id_sha256"]))
        self.assertEqual(64, len(report["observation_id_sha256"]))
        self.assertNotIn("exec-1", rendered)
        self.assertNotIn("execution_summary", report)
        self.assertNotIn("raw_action", report)
        self.assertNotIn("snapshot", report)
        self.assertFalse(report["content_persisted"])
        self.assertFalse(report["service_state_mutated"])
        self.assertFalse(report["action_authority"])
        self.assertFalse(report["consciousness_proven"])

    def test_unverified_action_does_not_collect_an_observation(self):
        collected = []
        report = canary.run_canary(
            action_runner=lambda: self.action_result(
                execution_tree_status="FAILURE",
                execution_verification_ok=False,
            ),
            snapshot_collector=lambda: collected.append(True) or self.snapshot(),
            now=self.clock(
                "2026-08-23T12:00:00+00:00",
                "2026-08-23T12:00:01+00:00",
            ),
        )

        self.assertEqual("action_unverified", report["status"])
        self.assertFalse(report["observation_collected"])
        self.assertFalse(report["observer_evidence_refreshed"])
        self.assertFalse(report["consequence_qualified"])
        self.assertEqual([], collected)

    def test_incomplete_snapshot_cannot_manufacture_information_gain(self):
        report = self.execute_canary(
            snapshot={"timestamp": "2026-08-23T12:00:02+00:00"}
        )

        self.assertEqual("closed_no_material_change", report["status"])
        self.assertEqual("inconclusive", report["observation_outcome"])
        self.assertEqual(0.0, report["information_gain"])
        self.assertFalse(report["consequence_qualified"])

    def test_snapshot_before_verified_action_is_rejected(self):
        report = self.execute_canary(
            snapshot=self.snapshot(timestamp="2026-08-23T11:59:59+00:00")
        )

        self.assertEqual("observation_unqualified", report["status"])
        self.assertFalse(report["consequence_qualified"])
        self.assertFalse(report["observation_after_verified_action"])


if __name__ == "__main__":
    unittest.main()
