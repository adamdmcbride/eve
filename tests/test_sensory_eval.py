import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import eve_sensory
import eve_sensory_eval


ROOT = Path(__file__).resolve().parents[1]


class SensoryEvaluationTests(unittest.TestCase):
    def test_sliding_window_coalesces_repeated_semantic_state_before_admission(self):
        start = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
        events = [
            {
                "id": f"sample-{index}",
                "observed_at": (start + timedelta(seconds=30 * index)).isoformat(),
                "modality": "system",
                "source": "test",
                "subject": "runtime",
                "summary": "Steady state.",
                "fingerprint": "same-state",
            }
            for index in range(6)
        ]
        frame = eve_sensory.build_frame(events, now=start + timedelta(seconds=150), capacity=4)

        self.assertEqual(1, frame["admitted_count"])
        self.assertEqual(5, frame["coalesced_duplicate_count"])
        self.assertEqual(6, frame["winner"]["coalesced_observation_count"])
        self.assertTrue(
            all(item["reason"] == "duplicate_current_state" for item in frame["ignored"])
        )
        self.assertEqual("passed", eve_sensory_eval.evaluate_frame_contract(frame)["status"])

    def test_binding_uses_one_representative_per_modality_and_coalesces_episodes(self):
        start = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
        events = []
        for sample in range(3):
            correlation = f"session:scene:{sample}"
            for modality in ("auditory", "visual"):
                events.append(
                    {
                        "id": f"{modality}-{sample}",
                        "observed_at": (start + timedelta(seconds=sample)).isoformat(),
                        "modality": modality,
                        "source": "test",
                        "subject": "local_scene",
                        "correlation_id": correlation,
                        "summary": f"Stable {modality} state.",
                        "fingerprint": f"stable-{modality}",
                        "permission_granted": True,
                    }
                )
        frame = eve_sensory.build_frame(events, now=start + timedelta(seconds=3))

        self.assertEqual(1, frame["bound_episode_count"])
        self.assertEqual(3, frame["bound_episode_observed_count"])
        self.assertEqual(2, frame["coalesced_duplicate_count"])
        episode = frame["winner"]
        self.assertEqual(["auditory", "visual"], episode["modalities"])
        self.assertEqual(2, len(episode["member_ids"]))
        self.assertEqual(2, len(episode["member_fingerprints"]))

    def test_entity_tracks_do_not_recount_replayed_sliding_window_events(self):
        start = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
        first_events = [
            {
                "id": f"observation-{index}",
                "observed_at": (start + timedelta(seconds=index)).isoformat(),
                "modality": "visual",
                "source": "test",
                "subject": "tracked_scene",
                "summary": "Tracked scene state.",
                "fingerprint": "tracked-scene-state",
                "permission_granted": True,
            }
            for index in range(3)
        ]
        first = eve_sensory.build_frame(first_events, now=start + timedelta(seconds=2))
        replay = eve_sensory.build_frame(
            first_events,
            prior_frame=first,
            now=start + timedelta(seconds=30),
        )
        extended = eve_sensory.build_frame(
            [
                *first_events,
                {
                    **first_events[-1],
                    "id": "observation-3",
                    "observed_at": (start + timedelta(seconds=31)).isoformat(),
                },
            ],
            prior_frame=replay,
            now=start + timedelta(seconds=31),
        )

        self.assertEqual(3, first["entity_tracks"][0]["observation_count"])
        self.assertEqual(3, replay["entity_tracks"][0]["observation_count"])
        self.assertEqual(4, extended["entity_tracks"][0]["observation_count"])
        self.assertEqual(4, len(extended["entity_tracks"][0]["recent_observation_keys"]))

    def test_accelerated_multi_hour_overload_and_lesion_suite_passes_honestly(self):
        report = eve_sensory_eval.run_evaluation(duration_hours=4)

        self.assertEqual("passed", report["status"])
        self.assertEqual("passed", report["overload_novelty"]["status"])
        self.assertEqual("passed", report["intact_vs_lesioned"]["status"])
        self.assertEqual("not_exercised", report["active_sampling_consequence"]["status"])
        self.assertIn("wall-clock", " ".join(report["not_established"]))

    def test_cli_writes_repeatable_json_without_touching_runtime_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "sensory-eval.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "bin" / "eve_sensory_eval.py"),
                    "--hours",
                    "0.1",
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
            self.assertEqual(eve_sensory_eval.EVAL_SCHEMA, payload["schema_version"])
            self.assertEqual("passed", payload["status"])


if __name__ == "__main__":
    unittest.main()
