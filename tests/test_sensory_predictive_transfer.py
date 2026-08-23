import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "bin" / "eve_predictive_perception_transfer_eval.py"
SPEC = importlib.util.spec_from_file_location("eve_predictive_perception_transfer_eval", MODULE_PATH)
assert SPEC and SPEC.loader
transfer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(transfer)


def frozen_manifest():
    scenarios = [
        {
            "id": "linear-up",
            "kind": "numeric",
            "values": [10, 20, 30],
            "precision": 100,
            "expected_surprise": False,
        },
        {
            "id": "omitted-motion",
            "kind": "numeric",
            "values": [10, 20, 20],
            "precision": 100,
            "expected_surprise": True,
        },
    ]
    material = {
        "schema_version": transfer.MANIFEST_SCHEMA,
        "seed": 230823,
        "frozen_before_evidence": True,
        "scenarios": scenarios,
    }
    digest = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {**material, "manifest_digest": digest}


class PredictivePerceptionTransferTests(unittest.TestCase):
    def test_manifest_digest_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            payload = frozen_manifest()
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(payload["manifest_digest"], transfer.load_manifest(path)["manifest_digest"])

            payload["scenarios"][0]["values"][2] = 99
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                transfer.load_manifest(path)

    def test_transfer_evaluation_preserves_protocol_and_safety_boundaries(self):
        report = transfer.run_evaluation(
            frozen_manifest(),
            evaluated_at="2026-08-23T19:00:00+00:00",
        )

        self.assertEqual(2, report["scenario_count_per_arm"])
        self.assertEqual(4, len(report["protocol_evidence"]))
        self.assertTrue(report["checks"]["protected_paths_preserved"])
        self.assertTrue(report["checks"]["lesion_removed_prediction_comparison"])
        self.assertFalse(report["consciousness_proven"])
        self.assertFalse(report["subjective_experience_inferred"])

    def test_cli_writes_repeatable_aggregate_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            output = root / "report.json"
            evidence = root / "evidence.json"
            manifest.write_text(json.dumps(frozen_manifest()), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "--manifest",
                    str(manifest),
                    "--output",
                    str(output),
                    "--evidence-output",
                    str(evidence),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual(4, len(json.loads(evidence.read_text(encoding="utf-8"))))
            self.assertIn(
                json.loads(output.read_text(encoding="utf-8"))["status"],
                {"passed_full_transfer", "partial_transfer"},
            )


if __name__ == "__main__":
    unittest.main()
