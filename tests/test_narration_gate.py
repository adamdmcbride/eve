import unittest
from datetime import timedelta
from unittest.mock import patch

import eve


class ReflectionLivedEvidenceGateTests(unittest.TestCase):
    def test_a_reflection_waits_until_something_lived_happened(self):
        state = {"last_reflection_at": "2026-09-18T00:00:00+00:00"}
        stale = [{"kind": "thought", "timestamp": "2026-09-17T23:00:00+00:00"}] * 9
        with patch.object(eve, "read_lived_entries", return_value=(stale, {})):
            self.assertIn("nothing new to reflect on", eve.reflection_lived_evidence_gate(state))
        fresh = stale + [{"kind": "message_sent", "timestamp": "2026-09-18T05:00:00+00:00"} for _ in range(3)]
        with patch.object(eve, "read_lived_entries", return_value=(fresh, {})):
            self.assertEqual("", eve.reflection_lived_evidence_gate(state))

    def test_a_reader_error_never_blocks_a_reflection(self):
        with patch.object(eve, "read_lived_entries", side_effect=OSError("store gone")):
            self.assertEqual("", eve.reflection_lived_evidence_gate({}))

    def test_first_ever_reflection_is_allowed_when_rows_exist(self):
        rows = [{"kind": "thought", "timestamp": "2026-09-18T05:00:00+00:00"}] * 4
        with patch.object(eve, "read_lived_entries", return_value=(rows, {})):
            self.assertEqual("", eve.reflection_lived_evidence_gate({}))


class RecentHumanTurnGateTests(unittest.TestCase):
    def _row(self, hours_ago, **metadata):
        return {"id": "m", "sender": "user", "created_at": (eve.utc_now_datetime() - timedelta(hours=hours_ago)).isoformat(timespec="seconds"), "metadata": metadata}

    def test_a_real_recent_turn_opens_the_gate(self):
        with patch.object(eve, "read_messages", return_value=[self._row(5)]):
            self.assertEqual("", eve.recent_human_turn_gate(dict(eve.DEFAULT_CONFIG)))

    def test_claude_and_evaluator_turns_are_not_human_turns(self):
        for metadata in ({"actual_sender": "claude"}, {"synthetic": True}, {"provenance": "evaluator_grant"}):
            with patch.object(eve, "read_messages", return_value=[self._row(2, **metadata)]):
                self.assertIn("no genuine human turn", eve.recent_human_turn_gate(dict(eve.DEFAULT_CONFIG)), metadata)

    def test_an_old_turn_closes_the_gate(self):
        with patch.object(eve, "read_messages", return_value=[self._row(24 * 9)]):
            self.assertIn("last 3 day(s)", eve.recent_human_turn_gate(dict(eve.DEFAULT_CONFIG)))

    def test_zero_days_disables_the_gate(self):
        with patch.object(eve, "read_messages", return_value=[]):
            self.assertEqual("", eve.recent_human_turn_gate(dict(eve.DEFAULT_CONFIG, outreach_requires_recent_human_days=0)))


class ProposalLineageTests(unittest.TestCase):
    BODY = """# Proposal
## Why Now
The deep lane times out.
## Exact Change
Route proposal drafting to the observer lane.
## Grounded In
- 11111111-1111-1111-1111-111111111111
- 22222222-2222-2222-2222-222222222222
- 33333333-3333-3333-3333-333333333333
## Rollback
set_config operation_model_overrides {} to restore deep-lane drafting.
"""

    def test_lineage_and_rollback_are_read_and_matched(self):
        with patch.object(eve, "read_tensions", return_value=[{"id": "11111111-1111-1111-1111-111111111111"}]), patch.object(eve, "read_experiments", return_value=[{"id": "22222222-2222-2222-2222-222222222222"}]):
            lineage = eve.parse_proposal_lineage(self.BODY)
        self.assertEqual(["11111111-1111-1111-1111-111111111111"], lineage["tension_ids"])
        self.assertEqual(["22222222-2222-2222-2222-222222222222"], lineage["experiment_ids"])
        self.assertEqual(["33333333-3333-3333-3333-333333333333"], lineage["unmatched_lineage_ids"])
        self.assertIn("operation_model_overrides", lineage["rollback"])

    def test_the_lineage_requirement_is_off_by_default_and_binding_when_on(self):
        body = "## Why Now The deep lane times out. ## Exact Change Route drafting to observer. ## Rollback set_config operation_model_overrides {}."
        grounded = {"title": "Proposal ## Title Route drafting", "source": "daemon", "body": body, "metadata": {"tension_ids": ["t1"], "rollback": "set it back"}}
        bare = {"title": "Proposal ## Title Route drafting", "source": "daemon", "body": body, "metadata": {}}
        self.assertTrue(eve.proposal_is_actionable(bare, dict(eve.DEFAULT_CONFIG)))
        strict = dict(eve.DEFAULT_CONFIG, self_change_require_lineage=True)
        self.assertTrue(eve.proposal_is_actionable(grounded, strict))
        self.assertFalse(eve.proposal_is_actionable(bare, strict))
        no_rollback = {**grounded, "metadata": {"tension_ids": ["t1"]}}
        self.assertFalse(eve.proposal_is_actionable(no_rollback, strict), "lineage without a rollback is not enough")


if __name__ == "__main__":
    unittest.main()
