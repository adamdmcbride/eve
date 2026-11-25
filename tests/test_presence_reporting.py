"""Presence projection must not confuse native data authority with liveness."""
from contextlib import ExitStack
from pathlib import Path
import unittest
from unittest.mock import patch

import eve


class PresenceReportingTests(unittest.TestCase):
    def report(self, *, native, liveness, blocked=False):
        values = {
            "presence_state_authority_side": "source",
            "build_organ_assimilation_report": {"organs": [], "readiness": {"blocking_organs": ["model"] if blocked else [], "working_now": True}},
            "latest_consciousness_test_record": ({"passed": True, "scorecard": {key: 5 for key in ["fallback_independence", "integrated_present", "temporal_continuity", "attention_control"]}}, Path("unused")),
            "load_global_workspace": {}, "load_homeostasis": {},
            "load_active_mind": {"current_focus": "Verify the current deployment"},
            "load_conscious_state": {}, "load_state": {}, "daemon_runtime_running": native,
            "presence_runtime_liveness": liveness, "observe_core_runner": {},
            "organ_embodiment_score": 5, "build_presence_action_contract": {"bounded_action": "service_health_check"},
        }
        with ExitStack() as patches:
            for key, value in values.items():
                patches.enter_context(patch.object(eve, key, return_value=value))
            return eve.build_presence_report({}, prefer_runtime=False)

    def test_live_source_core_is_not_dormant_and_does_not_change_data_authority(self):
        result = self.report(native=False, liveness={"status": "active", "live": True, "daemon_running": True})
        self.assertEqual("present", result["status"])
        self.assertFalse(result["state_authority"]["daemon_runtime_running"])
        self.assertEqual("source", result["state_authority"]["side"])
        self.assertNotIn("Start Eve", result["next_step"])

    def test_live_source_core_with_blocked_organ_stays_blocked_not_dormant(self):
        result = self.report(native=False, liveness={"status": "active", "live": True, "daemon_running": True}, blocked=True)
        self.assertEqual("blocked", result["status"])
        self.assertIn("Resolve blocked organs", result["next_step"])

    def test_stale_process_is_not_promoted_to_live(self):
        result = self.report(native=False, liveness={"status": "stale", "live": False, "daemon_running": True})
        self.assertEqual("blocked", result["status"])
        self.assertIn("stalled daemon", result["next_step"])

    def test_native_service_cannot_override_explicit_dead_owner(self):
        result = self.report(native=True, liveness={"status": "dormant", "live": False, "daemon_running": False})
        self.assertEqual("dormant", result["status"])
        self.assertIn("Start Eve", result["next_step"])


if __name__ == "__main__":
    unittest.main()
