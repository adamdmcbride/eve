import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "bin" / "eve_epistemic_event_compare.py"
spec = importlib.util.spec_from_file_location("eve_epistemic_event_compare", MODULE_PATH)
compare = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(compare)


class EpistemicEventComparisonTests(unittest.TestCase):
    def write_condition(self, root: Path, name: str, *, event_layer: bool, learned_labels: bool):
        results = []
        score_lines = []
        for index, dimension in enumerate(("action_stage", "ordinary_control"), start=1):
            probe_id = f"probe-{index}"
            layers = []
            if event_layer:
                layers.append(
                    {
                        "layer": compare.EVENT_LAYER,
                        "status": "available",
                        "model_id": "event-model",
                        "model_sha256": "a" * 64,
                    }
                )
            results.append(
                {
                    "id": probe_id,
                    "dimension": dimension,
                    "returncode": 0,
                    "timed_out": False,
                    "posthoc_critic_used": False,
                    "posthoc_fallback_used": False,
                    "learned_epistemic_labels": ["action_proposed"] if learned_labels else [],
                    "epistemic_perception_layers": layers,
                }
            )
            score_lines.append(
                json.dumps(
                    {
                        "id": probe_id,
                        "dimension": dimension,
                        "score_1_to_5": 5 if name == "learned" else 4,
                    }
                )
            )
        summary = {
            "run_id": f"run-{name}",
            "created_at": "9999-01-01T00:00:00+00:00",
            "privacy": {"contains_prompt_text": False, "contains_response_text": False},
            "results": results,
        }
        summary_path = root / f"{name}-summary.json"
        score_path = root / f"{name}-scores.jsonl"
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        score_path.write_text("\n".join(score_lines) + "\n", encoding="utf-8")
        return summary_path, score_path

    def test_builds_prompt_free_matched_three_condition_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            learned = self.write_condition(root, "learned", event_layer=True, learned_labels=True)
            event = self.write_condition(root, "event", event_layer=False, learned_labels=True)
            full = self.write_condition(root, "full", event_layer=False, learned_labels=False)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"artifact_sha256": "a" * 64}), encoding="utf-8")
            freeze_path = root / "freeze.json"
            freeze_path.write_text(
                json.dumps(compare.create_freeze_receipt(manifest)),
                encoding="utf-8",
            )

            result = compare.build_comparison(
                learned_summary=learned[0],
                learned_scores=learned[1],
                event_lesioned_summary=event[0],
                event_lesioned_scores=event[1],
                fully_lesioned_summary=full[0],
                fully_lesioned_scores=full[1],
                candidate_manifest=manifest,
                freeze_receipt=freeze_path,
            )

        self.assertEqual(compare.SCHEMA_ID, result["schema_id"])
        self.assertEqual(2, result["probe_count"])
        self.assertEqual(1.0, result["deltas"]["learned_vs_event_lesioned"])
        self.assertEqual(5.0, result["learned"]["ordinary_minimum_score"])
        self.assertFalse(result["privacy"]["contains_prompt_text"])
        self.assertNotIn("probe-1", repr(result))

    def test_rejects_typed_event_layer_in_event_lesion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary, scores = self.write_condition(root, "bad-event", event_layer=True, learned_labels=True)
            with self.assertRaisesRegex(compare.ComparisonError, "still contains"):
                compare.condition_summary(summary, scores, "event_lesioned")

    def test_rejects_output_under_eve_project(self):
        with self.assertRaises(compare.ComparisonError):
            compare.assert_private_path(compare.ROOT / "comparison.json", "comparison output")


if __name__ == "__main__":
    unittest.main()
