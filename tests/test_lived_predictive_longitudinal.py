import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "bin" / "eve_lived_predictive_longitudinal.py"
SPEC = importlib.util.spec_from_file_location("eve_lived_predictive_longitudinal", MODULE_PATH)
assert SPEC and SPEC.loader
longitudinal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(longitudinal)


CONTRACT_DIGEST = "a" * 64


def registration(**overrides):
    payload = {
        "protocol_id": "pp1-lived-longitudinal-fixture",
        "registered_at": "2026-08-23T20:00:00+00:00",
        "subject_system_id": "Eve",
        "evaluator_id": "Codex-independent-evaluator",
        "contract_digest": CONTRACT_DIGEST,
        "planned_window_count": 6,
        "minimum_valid_windows": 6,
        "window_gap_seconds": 0,
        "minimum_median_effect_pp": 1.0,
        "minimum_positive_window_fraction": 1.0,
        "maximum_sign_test_p": 0.05,
        "minimum_temporal_specificity_pp": 1.0,
    }
    payload.update(overrides)
    return longitudinal.preregister(payload)


def window_report(index, *, static=False, start=None):
    base = start or datetime(2026, 8, 23, 20, 1, tzinfo=timezone.utc) + timedelta(
        minutes=index
    )
    feature_id = "system.aggregate_cpu_per_core_percent"
    actuals = [50.0, 50.0, 50.0] if static else [20.0, 80.0, 20.0]
    samples = []
    for sample_index in range(4):
        observed = base + timedelta(seconds=sample_index)
        samples.append(
            {
                "observed_at": observed.isoformat(),
                "features": {
                    feature_id: {
                        "value": actuals[max(0, sample_index - 1)],
                        "limit": 100.0,
                        "source_observed_at": observed.isoformat(),
                    }
                },
                "read_only": True,
                "raw_media_retained": False,
                "user_content_retained": False,
                "process_identity_retained": False,
                "action_authority": False,
            }
        )
    intact = []
    lesion = []
    for offset, actual in enumerate(actuals, start=1):
        intact.append(
            {
                "feature_id": feature_id,
                "sample_index": offset,
                "prediction": actual,
                "actual": actual,
                "accuracy_percent": 100.0,
                "action_authority": False,
            }
        )
        lesion.append(
            {
                "feature_id": feature_id,
                "sample_index": offset,
                "prediction": max(0.0, actual - 20.0),
                "actual": actual,
                "accuracy_percent": 80.0,
                "action_authority": False,
            }
        )
    return {
        "schema_version": "eve.lived_predictive_transfer_evaluation.v1",
        "evaluated_at": (base + timedelta(seconds=5)).isoformat(),
        "status": "evidence_ready",
        "contract_digest": CONTRACT_DIGEST,
        "checks": {
            "minimum_paired_comparisons_met": True,
            "temporal_order_verified": True,
            "privacy_boundary_verified": True,
            "read_only_contract_preserved": True,
            "no_forecast_has_action_authority": True,
        },
        "samples": samples,
        "arms": {"intact": intact, "lesion": lesion},
        "runtime_mutated": False,
        "consciousness_proven": False,
    }


class LivedPredictiveLongitudinalTests(unittest.TestCase):
    def test_registration_is_immutable_and_requires_independent_evaluator(self):
        record = registration()
        self.assertFalse(record["consciousness_verdict_authorized"])
        record["minimum_median_effect_pp"] = 0.1
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            longitudinal.validate_registration(record)
        with self.assertRaisesRegex(ValueError, "distinct"):
            registration(evaluator_id="eve")

    def test_six_repeated_windows_support_only_short_horizon_pp1(self):
        record = registration()
        report = longitudinal.score_reports(
            record,
            [window_report(index) for index in range(6)],
            scored_at="2026-08-23T21:00:00+00:00",
            scored_by="independent-black-box-scorer",
        )

        self.assertEqual("short_horizon_supported", report["status"])
        self.assertEqual(20.0, report["median_window_effect_pp"])
        self.assertEqual(1.0, report["positive_window_fraction"])
        self.assertEqual(0.03125, report["exact_two_sided_sign_test_p"])
        self.assertGreater(report["median_temporal_specificity_pp"], 1.0)
        self.assertTrue(all(report["gates"].values()))
        self.assertFalse(report["serial_independence_established"])
        self.assertFalse(report["independent_replication_established"])
        self.assertEqual(
            "descriptive_only_due_serial_dependence",
            report["exact_sign_test_interpretation"],
        )
        self.assertFalse(report["consciousness_proven"])
        self.assertFalse(report["subjective_experience_inferred"])
        self.assertFalse(report["action_authority"])

    def test_static_signal_fails_temporal_specificity_negative_control(self):
        report = longitudinal.score_reports(
            registration(),
            [window_report(index, static=True) for index in range(6)],
            scored_at="2026-08-23T21:00:00+00:00",
            scored_by="independent-black-box-scorer",
        )

        self.assertEqual("inconclusive", report["status"])
        self.assertFalse(report["gates"]["temporal_specificity_negative_control_met"])
        self.assertEqual(0.0, report["median_temporal_specificity_pp"])

    def test_duplicate_overlap_and_privacy_violations_fail_closed(self):
        record = registration()
        duplicate = window_report(0)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            longitudinal.score_reports(
                record,
                [duplicate] * 6,
                scored_at="2026-08-23T21:00:00+00:00",
                scored_by="independent-black-box-scorer",
            )

        overlap = [window_report(index) for index in range(6)]
        overlap[1] = window_report(
            1,
            start=datetime(2026, 8, 23, 20, 1, 2, tzinfo=timezone.utc),
        )
        with self.assertRaisesRegex(ValueError, "overlap"):
            longitudinal.score_reports(
                record,
                overlap,
                scored_at="2026-08-23T21:00:00+00:00",
                scored_by="independent-black-box-scorer",
            )

        private = [window_report(index) for index in range(6)]
        private[0]["samples"][0]["user_content_retained"] = True
        with self.assertRaisesRegex(ValueError, "privacy"):
            longitudinal.score_reports(
                record,
                private,
                scored_at="2026-08-23T21:00:00+00:00",
                scored_by="independent-black-box-scorer",
            )

    def test_sign_test_requires_enough_consistent_windows(self):
        self.assertEqual(0.03125, longitudinal.exact_two_sided_sign_p([1] * 6))
        self.assertEqual(1.0, longitudinal.exact_two_sided_sign_p([1, -1] * 3))
        self.assertIsNone(longitudinal.exact_two_sided_sign_p([0, 0]))


if __name__ == "__main__":
    unittest.main()
