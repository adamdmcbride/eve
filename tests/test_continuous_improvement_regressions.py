import unittest
from unittest.mock import patch

import eve


class ContinuousImprovementRegressionTests(unittest.TestCase):
    def test_no_risk_summary_does_not_become_a_developmental_failure(self) -> None:
        state = {
            "success_pattern_repair_summary": "No at-risk success-pattern repairs queued."
        }
        with patch.object(
            eve, "daemon_health_diagnostics", return_value={"degraded": False}
        ), patch.object(
            eve, "read_failure_clusters", return_value=[]
        ), patch.object(
            eve, "read_action_executions", return_value=[]
        ), patch.object(
            eve, "at_risk_success_patterns", return_value=[]
        ):
            modes = eve.build_developmental_failure_modes({}, state)

        self.assertNotIn(
            "success-pattern repair thread still needs upstream attention", modes
        )

    def test_real_at_risk_pattern_remains_a_developmental_failure(self) -> None:
        with patch.object(
            eve, "daemon_health_diagnostics", return_value={"degraded": False}
        ), patch.object(
            eve, "read_failure_clusters", return_value=[]
        ), patch.object(
            eve, "read_action_executions", return_value=[]
        ), patch.object(
            eve, "at_risk_success_patterns", return_value=[{"id": "pattern-1"}]
        ):
            modes = eve.build_developmental_failure_modes({}, {})

        self.assertIn(
            "success-pattern repair thread still needs upstream attention", modes
        )

    def test_no_risk_summary_does_not_trigger_openclaw_repair(self) -> None:
        state = {
            "success_pattern_repair_summary": "No at-risk success-pattern repairs queued."
        }
        with patch.object(
            eve, "daemon_health_diagnostics", return_value={"degraded": False}
        ), patch.object(
            eve, "read_failure_clusters", return_value=[]
        ), patch.object(
            eve, "read_system_tasks", return_value=[]
        ), patch.object(
            eve, "read_maintenance_actions", return_value=[]
        ), patch.object(
            eve, "read_entries", return_value=[]
        ), patch.object(
            eve, "at_risk_success_patterns", return_value=[]
        ):
            signals = eve.openclaw_repair_signals({}, state)

        self.assertNotIn(
            "at-risk success patterns still need upstream repair", signals
        )

    def test_real_at_risk_pattern_still_triggers_openclaw_repair(self) -> None:
        with patch.object(
            eve, "daemon_health_diagnostics", return_value={"degraded": False}
        ), patch.object(
            eve, "read_failure_clusters", return_value=[]
        ), patch.object(
            eve, "read_system_tasks", return_value=[]
        ), patch.object(
            eve, "read_maintenance_actions", return_value=[]
        ), patch.object(
            eve, "read_entries", return_value=[]
        ), patch.object(
            eve, "at_risk_success_patterns", return_value=[{"id": "pattern-1"}]
        ):
            signals = eve.openclaw_repair_signals({}, {})

        self.assertIn(
            "at-risk success patterns still need upstream repair", signals
        )


if __name__ == "__main__":
    unittest.main()
