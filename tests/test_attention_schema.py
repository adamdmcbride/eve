import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import eve_sensory


ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-08-23T18:00:00+00:00"


def event(event_id: str, **overrides):
    value = {
        "id": event_id,
        "observed_at": NOW,
        "modality": "world",
        "source": "attention_schema_test",
        "subject": event_id,
        "summary": event_id,
        "intensity": 20,
        "novelty": 20,
        "change": 10,
        "urgency": 20,
        "goal_relevance": 20,
        "self_relevance": 20,
        "social_relevance": 0,
        "precision": 80,
    }
    value.update(overrides)
    return value


def overload_events():
    return [
        event(
            "goal-target",
            goal_relevance=100,
            self_relevance=90,
            precision=95,
        ),
        event(
            "vivid-low-urgency-distractor",
            intensity=100,
            novelty=100,
            change=100,
            urgency=20,
            goal_relevance=0,
            self_relevance=0,
            precision=50,
        ),
        event("noise-1", intensity=60, novelty=80),
        event("noise-2", intensity=55, novelty=70),
        event("noise-3", intensity=50, novelty=60),
    ]


class AttentionSchemaTests(unittest.TestCase):
    def test_predictive_control_changes_capture_under_overload(self):
        intact = eve_sensory.build_frame(
            overload_events(),
            now=NOW,
            capacity=4,
            attention_schema_enabled=True,
        )
        lesioned = eve_sensory.build_frame(
            overload_events(),
            now=NOW,
            capacity=4,
            attention_schema_enabled=False,
        )

        self.assertEqual("goal-target", intact["winner"]["id"])
        self.assertEqual("vivid-low-urgency-distractor", lesioned["winner"]["id"])
        self.assertTrue(intact["attention_schema"]["control"]["changed_winner"])
        self.assertTrue(lesioned["attention_schema"]["control"]["lesioned"])
        self.assertGreater(
            intact["winner"]["selection_score"],
            intact["winner"]["attention_score"],
        )

    def test_direct_human_safety_and_high_urgency_capture_are_protected(self):
        cases = [
            event("human", direct_human=True),
            event("safety", safety_critical=True),
            event("urgent", urgency=91, intensity=80, novelty=80, change=80),
        ]
        for protected in cases:
            with self.subTest(protected=protected["id"]):
                frame = eve_sensory.build_frame(
                    [
                        event(
                            "goal-target",
                            goal_relevance=100,
                            self_relevance=90,
                            precision=95,
                        ),
                        protected,
                        event("noise-1"),
                        event("noise-2"),
                        event("noise-3"),
                    ],
                    now=NOW,
                    capacity=4,
                    attention_schema_enabled=True,
                )
                self.assertEqual(protected["id"], frame["winner"]["id"])

    def test_schema_does_not_reorder_a_non_overloaded_priority_map(self):
        events = [
            event(
                "salient",
                intensity=100,
                novelty=100,
                change=100,
                urgency=40,
            ),
            event("goal", goal_relevance=100, self_relevance=90, precision=95),
        ]
        intact = eve_sensory.build_frame(events, now=NOW, capacity=4)
        lesioned = eve_sensory.build_frame(
            events,
            now=NOW,
            capacity=4,
            attention_schema_enabled=False,
        )

        self.assertFalse(intact["attention_schema"]["control"]["applied"])
        self.assertEqual(lesioned["winner"]["id"], intact["winner"]["id"])

        urgency_guard = eve_sensory.build_frame(
            [
                event(
                    "goal",
                    goal_relevance=100,
                    self_relevance=90,
                    precision=95,
                ),
                event(
                    "nominally-urgent-but-otherwise-empty",
                    intensity=0,
                    novelty=0,
                    change=0,
                    urgency=75,
                    goal_relevance=0,
                    self_relevance=0,
                    precision=0,
                ),
            ],
            now=NOW,
            capacity=4,
        )
        self.assertEqual("goal", urgency_guard["winner"]["id"])
        self.assertFalse(urgency_guard["attention_schema"]["control"]["changed_winner"])

    def test_next_state_forecast_is_scored_only_on_comparable_later_input(self):
        events = [event("a", goal_relevance=80), event("b", novelty=45)]
        first = eve_sensory.build_frame(events, now=NOW)
        second = eve_sensory.build_frame(
            events,
            prior_frame=first,
            now="2026-08-23T18:00:15+00:00",
        )
        changed = eve_sensory.build_frame(
            [*events, event("new", novelty=100, change=100)],
            prior_frame=second,
            now="2026-08-23T18:00:30+00:00",
        )

        calibration = second["attention_schema"]["calibration"]
        self.assertEqual(1, calibration["comparable_predictions"])
        self.assertEqual("scored", calibration["latest"]["status"])
        self.assertIsNotNone(calibration["mean_brier"])
        self.assertEqual(
            "not_scored_due_to_input_change",
            changed["attention_schema"]["calibration"]["latest"]["status"],
        )

    def test_public_frame_keeps_schema_but_no_new_action_authority(self):
        public = eve_sensory.public_frame(
            eve_sensory.build_frame(overload_events(), now=NOW, capacity=4)
        )

        schema = public["attention_schema"]
        self.assertEqual(eve_sensory.ATTENTION_SCHEMA_SCHEMA, schema["schema_version"])
        self.assertEqual("selection_policy_only", schema["control"]["authority"])
        self.assertIn("not subjective", schema["boundary"])
        self.assertEqual([], eve_sensory.forbidden_ingest_paths(public))

    def test_repeatable_cli_evaluation_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "attention-schema.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "bin" / "eve_attention_schema_eval.py"),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("passed", payload["status"])
            self.assertEqual(100.0, payload["intact_accuracy_percent"])
            self.assertGreaterEqual(payload["directional_effect"], 20.0)


if __name__ == "__main__":
    unittest.main()
