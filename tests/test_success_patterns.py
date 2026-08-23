import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import eve


class SuccessPatternLifecycleTests(unittest.TestCase):
    def test_status_for_counts_preserves_superseded_patterns(self) -> None:
        self.assertEqual(
            "superseded",
            eve.success_pattern_status_for_counts(
                confidence=0.95,
                reinforcement_count=5,
                contradiction_count=0,
                current_status="superseded",
            ),
        )

    def test_merge_does_not_reactivate_superseded_pattern(self) -> None:
        existing = eve.normalize_success_pattern(
            {
                "id": "pattern-1",
                "status": "superseded",
                "title": "Stale pattern",
                "situation": "When old evidence applies.",
                "good_move": "Do the old move.",
                "why_it_worked": "Superseded after contradictory evidence.",
                "source_ids": ["old"],
                "confidence": 0.2,
                "contradiction_count": 3,
            }
        )
        incoming = eve.normalize_success_pattern(
            {
                "status": "active",
                "title": "Stale pattern",
                "situation": "When old evidence applies.",
                "good_move": "Do the old move.",
                "why_it_worked": "A refresh found the old evidence again.",
                "source_ids": ["old", "new"],
                "confidence": 0.95,
                "contradiction_count": 3,
            }
        )

        merged = eve.merge_success_patterns(existing, incoming)

        self.assertEqual("superseded", merged["status"])
        self.assertIn("new", merged["source_ids"])

    def test_at_risk_success_patterns_ignores_superseded_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "success_patterns.jsonl"
            records = [
                {
                    "id": "active-risk",
                    "status": "active",
                    "title": "Active risk",
                    "situation": "When live.",
                    "good_move": "Repair.",
                    "contradiction_count": 1,
                    "updated_at": "2026-04-27T00:00:00+00:00",
                },
                {
                    "id": "retired-risk",
                    "status": "superseded",
                    "title": "Retired risk",
                    "situation": "When stale.",
                    "good_move": "Do not repair.",
                    "contradiction_count": 4,
                    "updated_at": "2026-04-27T00:00:00+00:00",
                },
            ]
            path.write_text("\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8")

            with patch.object(eve, "SUCCESS_PATTERNS_PATH", path):
                at_risk = eve.at_risk_success_patterns()

        self.assertEqual(["active-risk"], [item["id"] for item in at_risk])


if __name__ == "__main__":
    unittest.main()
