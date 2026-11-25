import unittest
from unittest.mock import patch

import eve


class PatternLineageTests(unittest.TestCase):
    """Procedural memory points at the evidence that earned it, so a contradiction can find it."""

    def setUp(self):
        self.entries = []
        patcher = patch.object(eve, "append_entry", side_effect=lambda kind, text, **kw: self.entries.append((kind, kw.get("metadata") or {})) or {"id": "e"})
        patcher.start(); self.addCleanup(patcher.stop)

    def _experiment(self, **over):
        base = {"id": "x1", "name": "Route daemon ticks to the observer lane", "hypothesis": "the observer answers in budget", "action": "set operation_model_overrides", "success_criteria": "80 percent parse", "status": "passed", "outcome": "82 percent parsed", "closure_evidence": "2 positive outcome(s)"}
        base.update(over); return base

    def test_a_passed_experiment_writes_a_pattern_carrying_its_id(self):
        with patch.object(eve, "upsert_success_pattern", return_value=({"id": "pat1"}, True, True)) as upsert:
            record = eve.record_pattern_from_experiment(self._experiment())
        self.assertEqual({"id": "pat1"}, record)
        payload = upsert.call_args.args[0]
        self.assertEqual(["experiment"], payload["source_kinds"]); self.assertEqual(["x1"], payload["source_ids"])
        self.assertEqual("x1", payload["metadata"]["experiment_id"])
        self.assertIn("80 percent parse", str(payload["metadata"]["success_criteria"]))
        self.assertEqual([("success_pattern_logged", "x1")], [(k, m["experiment_id"]) for k, m in self.entries])

    def test_a_failed_experiment_decays_the_pattern_it_taught(self):
        dedupe = eve.success_pattern_dedupe_key("Route daemon ticks to the observer lane", "the observer answers in budget")
        with patch.object(eve, "read_success_patterns", return_value=[{"id": "pat1", "dedupe_key": dedupe}]), patch.object(eve, "update_success_pattern_decay", return_value={"id": "pat1", "status": "superseded"}) as decay, patch.object(eve, "upsert_success_pattern") as upsert:
            record = eve.record_pattern_from_experiment(self._experiment(status="failed", outcome="regressed on day two"))
        self.assertEqual("superseded", record["status"]); self.assertEqual(0, upsert.call_count)
        self.assertEqual(("experiment", "x1"), (decay.call_args.kwargs["source_kind"], decay.call_args.kwargs["source_id"]))
        self.assertLess(decay.call_args.kwargs["delta"], 0)

    def test_unclosed_experiments_teach_nothing(self):
        for status in ("proposed", "active", "expired_unverified"):
            with patch.object(eve, "upsert_success_pattern") as upsert:
                self.assertIsNone(eve.record_pattern_from_experiment(self._experiment(status=status)), status)
                self.assertEqual(0, upsert.call_count)

    def test_an_improved_consequence_writes_a_pattern_with_the_session(self):
        followup = {"session_id": "s1", "proposal_id": "p1", "proposal_title": "Block the failing check", "metric_spec": {"kind": "action_failures", "action": "openclaw_log_check"}, "detail": "9 -> 0 failed run(s)"}
        with patch.object(eve, "upsert_success_pattern", return_value=({"id": "pat2"}, True, True)) as upsert:
            eve.record_pattern_from_consequence(followup, "improved")
        payload = upsert.call_args.args[0]
        self.assertEqual(["self_change"], payload["source_kinds"]); self.assertIn("s1", payload["source_ids"])
        self.assertIn("openclaw_log_check", payload["situation"]); self.assertIn("9 -> 0", payload["summary"])

    def test_a_regressed_consequence_decays_and_an_unmeasured_one_does_nothing(self):
        followup = {"session_id": "s1", "proposal_title": "Block the failing check", "metric_spec": {"kind": "action_failures"}, "detail": "1 -> 30"}
        dedupe = eve.success_pattern_dedupe_key("Block the failing check", "action_failures")
        with patch.object(eve, "read_success_patterns", return_value=[{"id": "pat2", "dedupe_key": dedupe}]), patch.object(eve, "update_success_pattern_decay", return_value={"id": "pat2"}) as decay:
            eve.record_pattern_from_consequence(followup, "regressed")
        self.assertEqual(1, decay.call_count)
        with patch.object(eve, "upsert_success_pattern") as upsert, patch.object(eve, "update_success_pattern_decay") as decay2:
            self.assertIsNone(eve.record_pattern_from_consequence(followup, "unmeasured"))
            self.assertEqual((0, 0), (upsert.call_count, decay2.call_count))


if __name__ == "__main__":
    unittest.main()
