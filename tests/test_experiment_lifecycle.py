import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import eve


class ExperimentClosureTests(unittest.TestCase):
    """An experiment closes on evidence or expires unverified; a model never sets its status."""

    def _store(self, tmp, rows):
        base = Path(tmp); path = base / "experiments.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.entries = []
        self.patterns = []
        for item in (
            patch.object(eve, "EXPERIMENTS_PATH", path),
            patch.object(eve, "SUCCESS_PATTERNS_PATH", base / "success_patterns.jsonl"),
            # the closure now teaches a pattern; without this the fixture writes into her real
            # procedural memory (it did, on 2026-09-19, and two fixture rows had to be removed)
            patch.object(eve, "upsert_success_pattern", side_effect=lambda payload: (self.patterns.append(payload) or {"id": "pat"}, True, True)),
            patch.object(eve, "read_success_patterns", return_value=[]),
            patch.object(eve, "append_entry", side_effect=lambda kind, text, **kw: self.entries.append((kind, kw.get("metadata") or {})) or {"id": "e"}),
        ):
            item.start(); self.addCleanup(item.stop)
        return path

    def _rows(self, path):
        return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]

    def _experiment(self, **over):
        base = {"id": "x1", "created_at": (eve.utc_now_datetime() - timedelta(days=8)).isoformat(timespec="seconds"), "updated_at": "", "name": "Route ticks to observer", "hypothesis": "h", "action": "a", "success_criteria": "80 percent parse", "duration_days": 7, "status": "proposed", "outcome": "", "notes": ""}
        base.update(over); return base

    def test_due_with_a_positive_outcome_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._store(tmp, [self._experiment(status="active")])
            with patch.object(eve, "read_outcomes", return_value=[{"target_id": "x1", "direction": "positive", "summary": "82 percent of ticks parsed", "created_at": eve.utc_now()}]), patch.object(eve, "read_entries", return_value=[]):
                result = eve.review_due_experiments(dict(eve.DEFAULT_CONFIG))
            row = self._rows(path)[0]
            self.assertEqual("passed", row["status"]); self.assertEqual("evidence", row["closed_by"])
            self.assertIn("82 percent", row["outcome"])
            experiment_rows = [(k, m["status"]) for k, m in self.entries if k.startswith("experiment_")]
            self.assertEqual([("experiment_updated", "passed")], experiment_rows)
            self.assertIn("success_pattern_logged", [k for k, _ in self.entries], "a passed experiment teaches a pattern")

    def test_a_negative_outcome_fails_it_even_with_a_positive_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._store(tmp, [self._experiment(status="active")])
            with patch.object(eve, "read_outcomes", return_value=[{"target_id": "x1", "direction": "positive", "summary": "up", "created_at": eve.utc_now()}, {"target_id": "x1", "direction": "negative", "summary": "regressed on the second day", "created_at": eve.utc_now()}]), patch.object(eve, "read_entries", return_value=[]):
                eve.review_due_experiments(dict(eve.DEFAULT_CONFIG))
            row = self._rows(path)[0]
            self.assertEqual("failed", row["status"]); self.assertIn("regressed", row["outcome"])

    def test_due_without_evidence_expires_unverified(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._store(tmp, [self._experiment(status="active")])
            with patch.object(eve, "read_outcomes", return_value=[]), patch.object(eve, "read_entries", return_value=[]):
                eve.review_due_experiments(dict(eve.DEFAULT_CONFIG))
            row = self._rows(path)[0]
            self.assertEqual("expired_unverified", row["status"]); self.assertEqual("", row["outcome"])
            self.assertEqual([("experiment_expired", "expired_unverified")], [(k, m["status"]) for k, m in self.entries if k.startswith("experiment_")])
            self.assertNotIn("success_pattern_logged", [k for k, _ in self.entries], "an unverified experiment teaches nothing")

    def test_proposed_becomes_active_only_when_something_acted_on_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            fresh = self._experiment(created_at=eve.utc_now(), status="proposed")
            path = self._store(tmp, [fresh])
            with patch.object(eve, "read_proposals", return_value=[]), patch.object(eve, "read_self_change_ledger", return_value=[]), patch.object(eve, "read_outcomes", return_value=[]), patch.object(eve, "read_entries", return_value=[]):
                eve.review_due_experiments(dict(eve.DEFAULT_CONFIG))
            self.assertEqual("proposed", self._rows(path)[0]["status"], "nothing acted on it yet")
            with patch.object(eve, "read_proposals", return_value=[{"id": "p1", "metadata": {"experiment_ids": ["x1"]}, "body": ""}]), patch.object(eve, "read_self_change_ledger", return_value=[]), patch.object(eve, "read_outcomes", return_value=[]), patch.object(eve, "read_entries", return_value=[]):
                eve.review_due_experiments(dict(eve.DEFAULT_CONFIG))
            self.assertEqual("active", self._rows(path)[0]["status"])

    def test_a_journal_row_carrying_the_id_is_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._store(tmp, [self._experiment(status="active")])
            with patch.object(eve, "read_outcomes", return_value=[]), patch.object(eve, "read_entries", return_value=[{"kind": "body_standing_intent_completed", "text": "hunger fell 1.00 -> 0.10", "timestamp": eve.utc_now(), "metadata": {"experiment_id": "x1", "direction": "positive"}}]):
                eve.review_due_experiments(dict(eve.DEFAULT_CONFIG))
            self.assertEqual("passed", self._rows(path)[0]["status"])

    def test_closed_experiments_are_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._store(tmp, [self._experiment(status="passed", outcome="done")])
            with patch.object(eve, "read_outcomes", return_value=[]), patch.object(eve, "read_entries", return_value=[]):
                result = eve.review_due_experiments(dict(eve.DEFAULT_CONFIG))
            self.assertEqual([], result["changed"]); self.assertEqual("passed", self._rows(path)[0]["status"])


if __name__ == "__main__":
    unittest.main()
