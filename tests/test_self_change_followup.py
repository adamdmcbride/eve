import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import eve


class MetricSpecTests(unittest.TestCase):
    def test_the_lever_names_its_own_metric(self):
        block = eve.self_change_metric_spec(['block_action:{"action": "openclaw_log_check", "hours": 24}'], [])
        self.assertEqual(("action_failures", "openclaw_log_check", "lower_is_better"), (block["kind"], block["action"], block["direction"]))
        route = eve.self_change_metric_spec(['set_config:{"key": "operation_model_overrides", "value": {"proposal": "observer"}}'], [])
        self.assertEqual(("operation_ok_rate", "proposal", "higher_is_better"), (route["kind"], route["operation"], route["direction"]))
        cadence = eve.self_change_metric_spec(['set_config:{"key": "proposal_interval_minutes", "value": 120}'], [])
        self.assertEqual(("config_change", "proposal_interval_minutes"), (cadence["kind"], cadence["config_key"]))
        code = eve.self_change_metric_spec([], ["eve_sensory.py"])
        self.assertEqual("code_change", code["kind"])
        self.assertEqual("manual", eve.self_change_metric_spec([], [])["kind"])

    def test_verdicts_follow_the_declared_direction(self):
        lower = {"direction": "lower_is_better", "kind": "action_failures"}
        self.assertEqual("improved", eve.self_change_followup_verdict(lower, {"value": 9.0, "detail": "9"}, {"value": 1.0, "detail": "1"})[0])
        self.assertEqual("regressed", eve.self_change_followup_verdict(lower, {"value": 1.0, "detail": "1"}, {"value": 6.0, "detail": "6"})[0])
        self.assertEqual("unchanged", eve.self_change_followup_verdict(lower, {"value": 2.0, "detail": "2"}, {"value": 2.0, "detail": "2"})[0])
        higher = {"direction": "higher_is_better", "kind": "operation_ok_rate"}
        self.assertEqual("improved", eve.self_change_followup_verdict(higher, {"value": 0.4, "detail": "a"}, {"value": 0.9, "detail": "b"})[0])
        self.assertEqual("unmeasured", eve.self_change_followup_verdict(higher, {"value": None, "detail": "none"}, {"value": 0.9, "detail": "b"})[0])


class FollowupReviewTests(unittest.TestCase):
    def _isolate(self, tmp, rows):
        base = Path(tmp)
        path = base / "self_change_followups.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.entries, self.ledger, self.outcomes = [], [], []
        for item in (
            patch.object(eve, "SELF_CHANGE_FOLLOWUPS_PATH", path),
            patch.object(eve, "append_entry", side_effect=lambda kind, text, **kw: self.entries.append((kind, kw.get("metadata") or {})) or {"id": "e"}),
            patch.object(eve, "append_self_change_ledger", side_effect=lambda row: self.ledger.append(row)),
            patch.object(eve, "create_outcome", side_effect=lambda **kw: self.outcomes.append(kw)),
            # the review now teaches a pattern; without this the fixture merges a row into her real
            # procedural memory (it did, on 2026-09-19)
            patch.object(eve, "SUCCESS_PATTERNS_PATH", base / "success_patterns.jsonl"),
            patch.object(eve, "upsert_success_pattern", return_value=({"id": "pat"}, True, True)),
            patch.object(eve, "read_success_patterns", return_value=[]),
        ):
            item.start(); self.addCleanup(item.stop)
        return path

    def _due(self, **over):
        row = {"id": "f1", "session_id": "s1", "proposal_id": "p1", "proposal_title": "Block the failing check",
               "scheduled_at": (eve.utc_now_datetime() - timedelta(hours=25)).isoformat(timespec="seconds"),
               "due_at": (eve.utc_now_datetime() - timedelta(hours=1)).isoformat(timespec="seconds"),
               "metric_spec": {"kind": "action_failures", "action": "openclaw_log_check", "direction": "lower_is_better", "window_hours": 24},
               "baseline": {"value": 9.0, "detail": "9 failed run(s)"}, "status": "pending"}
        row.update(over); return row

    def test_an_improvement_is_recorded_and_nothing_is_undone(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._isolate(tmp, [self._due()])
            with patch.object(eve, "measure_self_change_metric", return_value={"value": 0.0, "detail": "0 failed run(s)"}), patch.object(eve, "revert_self_change") as revert:
                result = eve.review_self_change_followups(dict(eve.DEFAULT_CONFIG))
            self.assertEqual(["improved"], [r["verdict"] for r in result["reviewed"]])
            self.assertEqual(0, revert.call_count)
            self.assertEqual("positive", self.outcomes[0]["direction"])
            self.assertEqual(["consequence"], [r["outcome"] for r in self.ledger])
            self.assertEqual("reviewed", json.loads(path.read_text().splitlines()[0])["status"])

    def test_a_regression_reverses_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._isolate(tmp, [self._due()])
            with patch.object(eve, "measure_self_change_metric", return_value={"value": 30.0, "detail": "30 failed run(s)"}), patch.object(eve, "revert_self_change", return_value={"ok": True}) as revert:
                result = eve.review_self_change_followups(dict(eve.DEFAULT_CONFIG))
            self.assertEqual(["regressed"], [r["verdict"] for r in result["reviewed"]])
            self.assertEqual("s1", revert.call_args.args[0])
            self.assertEqual("negative", self.outcomes[0]["direction"])
            self.assertIn("self_change_undone", [k for k, _ in self.entries])

    def test_the_undo_can_be_turned_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._isolate(tmp, [self._due()])
            with patch.object(eve, "measure_self_change_metric", return_value={"value": 30.0, "detail": "30"}), patch.object(eve, "revert_self_change") as revert:
                eve.review_self_change_followups(dict(eve.DEFAULT_CONFIG, self_change_undo_on_regression=False))
            self.assertEqual(0, revert.call_count)
            self.assertEqual("negative", self.outcomes[0]["direction"], "the regression is still recorded")

    def test_a_row_that_is_not_due_is_left_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._isolate(tmp, [self._due(due_at=(eve.utc_now_datetime() + timedelta(hours=5)).isoformat(timespec="seconds"))])
            result = eve.review_self_change_followups(dict(eve.DEFAULT_CONFIG))
            self.assertEqual([], result["reviewed"]); self.assertEqual(1, result["pending"])
            self.assertEqual("pending", json.loads(path.read_text().splitlines()[0])["status"])

    def test_an_unmeasurable_change_is_closed_honestly_without_an_undo(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._isolate(tmp, [self._due(metric_spec={"kind": "code_change", "paths": ["eve.py"], "direction": "manual", "window_hours": 24}, baseline={"value": None, "detail": "no automatic metric"})])
            with patch.object(eve, "revert_self_change") as revert:
                result = eve.review_self_change_followups(dict(eve.DEFAULT_CONFIG))
            self.assertEqual(["unmeasured"], [r["verdict"] for r in result["reviewed"]])
            self.assertEqual(0, revert.call_count); self.assertEqual("neutral", self.outcomes[0]["direction"])


class SchedulingTests(unittest.TestCase):
    def test_an_applied_change_schedules_its_own_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.jsonl"
            with patch.object(eve, "SELF_CHANGE_FOLLOWUPS_PATH", path), patch.object(eve, "measure_self_change_metric", return_value={"value": 9.0, "detail": "9"}):
                row = eve.schedule_self_change_followup({"session_id": "s1", "proposal_id": "p1", "proposal_title": "t", "changes": ['block_action:{"action": "openclaw_log_check"}'], "patched_paths": []}, dict(eve.DEFAULT_CONFIG))
            self.assertEqual("pending", row["status"]); self.assertEqual(9.0, row["baseline"]["value"])
            self.assertTrue(row["due_at"] > row["scheduled_at"])
            self.assertEqual(1, len(path.read_text().splitlines()))


if __name__ == "__main__":
    unittest.main()
