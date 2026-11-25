import hashlib
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import eve_lived_feature_stream as lived


ROOT = Path(__file__).resolve().parents[1]
EVAL_PATH = ROOT / "bin" / "eve_lived_predictive_transfer.py"
SPEC = importlib.util.spec_from_file_location("eve_lived_predictive_transfer", EVAL_PATH)
assert SPEC and SPEC.loader
evaluator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluator)


def contract(feature_id="system.load_1m_per_core_percent"):
    material = {
        "schema_version": lived.CONTRACT_SCHEMA,
        "sample_count": 9,
        "interval_seconds": 0,
        "minimum_history": 5,
        "read_only": True,
        "induced_perturbation": False,
        "features": [{"id": feature_id, "limit": 100, "precision": 100}],
        "metric": "100_minus_normalized_absolute_one_step_error",
        "intact": "multi_hypothesis_dynamics",
        "lesion": "velocity_only_numeric",
        "minimum_comparisons_per_arm": 4,
    }
    digest = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {**material, "contract_digest": digest}


class LivedFeatureStreamTests(unittest.TestCase):
    def test_extracts_only_fixed_numeric_privacy_minimized_features(self):
        snapshot = lived.extract_feature_snapshot(
            {
                "timestamp": "2026-08-23T19:59:00+00:00",
                "battery": {"percent": 77, "estimate": "private prose"},
                "top_processes": [{"command": "secret-process"}],
                "model_status": {
                    "probes": {
                        "eve-fast": {"wall_ms": 1200, "content": "secret model output"}
                    }
                },
            },
            {
                "updated_at": "2026-08-23T19:59:30+00:00",
                "pressures": [
                    {"id": "coherence", "level": 52, "reason": "private reason"},
                    {"id": "invented_private_key", "level": 99},
                ]
            },
            load_average=(8, 4, 2),
            cpu_count=16,
            disk_used_percent=84,
            aggregate_cpu_percent=55,
            aggregate_memory_percent=63,
            observed_at="2026-08-23T20:00:00+00:00",
        )

        self.assertEqual(50.0, snapshot["features"]["system.load_1m_per_core_percent"]["value"])
        self.assertEqual(1200.0, snapshot["features"]["model.eve_fast_latency_ms"]["value"])
        self.assertEqual(52.0, snapshot["features"]["homeostasis.coherence"]["value"])
        self.assertEqual(
            "2026-08-23T19:59:30+00:00",
            snapshot["features"]["homeostasis.coherence"]["source_observed_at"],
        )
        rendered = json.dumps(snapshot, sort_keys=True)
        self.assertNotIn("secret", rendered)
        self.assertNotIn("invented_private_key", rendered)
        self.assertFalse(snapshot["action_authority"])

    def test_contract_digest_is_fail_closed(self):
        payload = contract()
        self.assertEqual(payload["contract_digest"], lived.validate_contract(payload)["contract_digest"])
        payload["sample_count"] = 10
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            lived.validate_contract(payload)

    def test_paired_lived_evaluation_uses_temporal_history_without_authority(self):
        feature_id = "system.load_1m_per_core_percent"
        values = [20, 60, 20, 60, 20, 60, 20, 60, 20]
        start = datetime(2026, 8, 23, 20, 0, tzinfo=timezone.utc)
        samples = []
        for index, value in enumerate(values):
            samples.append(
                {
                    "schema_version": lived.SCHEMA,
                    "observed_at": (start + timedelta(seconds=index * 2)).isoformat(),
                    "features": {
                        feature_id: {
                            "value": value,
                            "limit": 100.0,
                            "source_precision": 100.0,
                            "source": "fixture",
                            "source_observed_at": (start + timedelta(seconds=index * 2)).isoformat(),
                        }
                    },
                    "read_only": True,
                    "raw_media_retained": False,
                    "user_content_retained": False,
                    "process_identity_retained": False,
                    "action_authority": False,
                }
            )
        report = evaluator.evaluate_samples(
            contract(feature_id),
            samples,
            evaluated_at="2026-08-23T20:01:00+00:00",
        )

        self.assertEqual("evidence_ready", report["status"])
        self.assertEqual(4, report["paired_comparison_count"])
        self.assertGreater(report["intact_mean_accuracy_percent"], report["lesion_mean_accuracy_percent"])
        self.assertFalse(report["runtime_mutated"])
        self.assertFalse(report["consciousness_proven"])


if __name__ == "__main__":
    unittest.main()
