import unittest

import eve_active_sensing_adapters as adapters


class ActiveSensingAdapterTests(unittest.TestCase):
    def action_result(self, **overrides):
        result = {
            "action": "service_health_check",
            "execution_id": "execution-health-1",
            "executed": True,
            "execution_tree_status": "SUCCESS",
            "execution_verification_ok": True,
            # This is intentionally true in every outcome test. It proves only
            # that the action ran, not that Eve is healthy.
            "ok": True,
            "execution_summary": "Service-health probe executed.",
        }
        result.update(overrides)
        return result

    def snapshot(self, **overrides):
        snapshot = {
            "timestamp": "2026-08-23T12:00:02+00:00",
            "eve_services": {
                "daemon": {"loaded": True, "state": "active"},
                "model_watchdog": {"loaded": True, "state": "active"},
                # A missing legacy Ollama warmer is not a required indicator.
                "model_warm": {"loaded": False, "state": "missing"},
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

    def verified_episode(self):
        opened = adapters.open_service_health_episode(
            now="2026-08-23T12:00:00+00:00"
        )
        return adapters.attach_service_health_execution(
            opened,
            self.action_result(),
            now="2026-08-23T12:00:01+00:00",
        )

    def test_execution_receipt_does_not_itself_claim_health(self):
        attached = self.verified_episode()
        self.assertEqual("action_verified", attached["status"])
        self.assertFalse(attached["consequence_qualified"])
        self.assertEqual({}, attached["beliefs_after"])

    def test_new_operational_snapshot_reduces_uncertainty(self):
        closed = adapters.close_service_health_episode(
            self.verified_episode(), self.snapshot()
        )
        self.assertEqual("operational_receipt", closed["observation"]["outcome"])
        self.assertEqual("closed_uncertainty_reduced", closed["status"])
        self.assertEqual("operational", closed["leading_hypothesis_after"])
        self.assertTrue(closed["consequence_qualified"])

    def test_successful_tool_call_can_observe_degraded_world_state(self):
        snapshot = self.snapshot()
        snapshot["model_status"]["probes"]["eve-deep"]["ok"] = False
        closed = adapters.close_service_health_episode(
            self.verified_episode(), snapshot
        )
        self.assertEqual("degraded_receipt", closed["observation"]["outcome"])
        self.assertEqual("degraded", closed["leading_hypothesis_after"])
        self.assertTrue(closed["consequence_qualified"])

    def test_missing_structured_state_is_inconclusive_and_not_rewarded(self):
        classified = adapters.classify_service_health_snapshot(
            {"timestamp": "2026-08-23T12:00:02+00:00"}
        )
        self.assertEqual("inconclusive", classified["outcome"])
        closed = adapters.close_service_health_episode(
            self.verified_episode(),
            {"timestamp": "2026-08-23T12:00:02+00:00"},
        )
        self.assertEqual("closed_no_material_change", closed["status"])
        self.assertFalse(closed["consequence_qualified"])
        self.assertEqual(0.0, closed["information_gain"])

    def test_failed_execution_cannot_be_rescued_by_a_healthy_snapshot(self):
        opened = adapters.open_service_health_episode(
            now="2026-08-23T12:00:00+00:00"
        )
        failed = adapters.attach_service_health_execution(
            opened,
            self.action_result(
                executed=False,
                execution_tree_status="FAILURE",
                execution_verification_ok=False,
            ),
            now="2026-08-23T12:00:01+00:00",
        )
        closed = adapters.close_service_health_episode(failed, self.snapshot())
        self.assertEqual("observation_unqualified", closed["status"])
        self.assertFalse(closed["consequence_qualified"])

    def test_stale_snapshot_cannot_close_the_episode(self):
        closed = adapters.close_service_health_episode(
            self.verified_episode(),
            self.snapshot(timestamp="2026-08-23T11:59:59+00:00"),
        )
        self.assertEqual("observation_unqualified", closed["status"])
        self.assertFalse(closed["consequence_qualified"])

    def test_adapter_output_is_feature_only(self):
        snapshot = self.snapshot(
            top_processes=[{"command": "/private/path/secret", "cpu_percent": 90}],
            workspace={"focus_files": ["/private/secret.txt"]},
        )
        classified = adapters.classify_service_health_snapshot(snapshot)
        rendered = str(classified)
        self.assertTrue(classified["feature_only"])
        self.assertNotIn("private", rendered)
        self.assertNotIn("secret", rendered)


if __name__ == "__main__":
    unittest.main()
