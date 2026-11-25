from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "bin" / "eve_predictive_cross_session.py"
SPEC = importlib.util.spec_from_file_location("eve_predictive_cross_session", MODULE_PATH)
assert SPEC and SPEC.loader
cross = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cross)


def contract():
    material = {
        "schema_version": "eve.lived_feature_transfer_contract.v1",
        "version": "cross-session-fixture-v1",
        "features": [
            {
                "id": "system.aggregate_cpu_per_core_percent",
                "limit": 100,
                "precision": 85,
            }
        ],
        "sample_count": 4,
        "interval_seconds": 0,
        "minimum_history": 1,
        "minimum_comparisons_per_arm": 3,
        "metric": "100_minus_normalized_absolute_one_step_error",
        "intact": "multi_hypothesis_dynamics",
        "lesion": "velocity_only_numeric",
        "read_only": True,
        "induced_perturbation": False,
        "exclude_cached_snapshot_replays": True,
        "require_strictly_increasing_source_timestamps": True,
    }
    digest = hashlib.sha256(
        json.dumps(
            material, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    return {**material, "contract_digest": digest}


def registration(**overrides):
    values = {
        "protocol_id": "pp1-cross-session-fixture",
        "registered_at": "2026-08-23T00:00:00+00:00",
        "protocol_author_id": "Codex-protocol-author",
        "scorer_id": "external-black-box-scorer",
        "minimum_session_gap_seconds": 3600,
        "minimum_distinct_utc_days": 3,
    }
    values.update(overrides)
    return cross.create_registration(contract(), **values)


def window_report(start, *, context="lower_activity", offset=0):
    if context == "lower_activity":
        values = [5.0, 15.0, 5.0, 15.0]
    elif context == "higher_activity":
        values = [50.0, 70.0, 50.0, 70.0]
    else:
        values = [25.0, 30.0, 25.0, 30.0]
    feature_id = "system.aggregate_cpu_per_core_percent"
    samples = []
    for index, value in enumerate(values):
        observed = start + timedelta(seconds=index)
        samples.append(
            {
                "schema_version": "eve.lived_feature_snapshot.v1",
                "observed_at": observed.isoformat(),
                "features": {
                    feature_id: {
                        "value": value,
                        "limit": 100.0,
                        "source_precision": 85.0,
                        "source": "fixture",
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
    for sample_index in range(1, len(values)):
        actual = values[sample_index]
        intact.append(
            {
                "feature_id": feature_id,
                "sample_index": sample_index,
                "observed_at": samples[sample_index]["observed_at"],
                "selected_expert": "period_2",
                "forecast_precision": 85.0,
                "prediction": actual,
                "actual": actual,
                "raw_error_percent": 0.0,
                "accuracy_percent": 100.0,
                "action_authority": False,
            }
        )
        lesion_prediction = actual - 10.0
        lesion.append(
            {
                "feature_id": feature_id,
                "sample_index": sample_index,
                "observed_at": samples[sample_index]["observed_at"],
                "selected_expert": "velocity",
                "forecast_precision": 85.0,
                "prediction": lesion_prediction,
                "actual": actual,
                "raw_error_percent": 10.0,
                "accuracy_percent": 90.0,
                "action_authority": False,
            }
        )
    return {
        "schema_version": "eve.lived_predictive_transfer_evaluation.v1",
        "evaluated_at": (start + timedelta(seconds=5)).isoformat(),
        "status": "evidence_ready",
        "contract_digest": contract()["contract_digest"],
        "protocol_trial_id": f"fixture-{start.isoformat()}-{offset}",
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


def session_bundle(record, start, *, context="lower_activity", collector="host-runner"):
    reports = [
        window_report(start + timedelta(minutes=index), context=context, offset=index)
        for index in range(6)
    ]
    return cross.build_session_bundle(
        record,
        reports,
        created_at=(start + timedelta(minutes=6)).isoformat(),
        collected_by=collector,
        host_boot_fingerprint_sha256="a" * 64,
    )


class PredictiveCrossSessionTests(unittest.TestCase):
    def test_registration_freezes_protocol_and_implementations(self):
        record = registration()

        self.assertEqual("preregistered", record["status"])
        self.assertEqual(5, len(record["implementation_digests"]))
        self.assertFalse(record["independent_replication_authorized"])
        self.assertFalse(record["consciousness_verdict_authorized"])
        record["minimum_median_effect_vs_adaptive_ema_pp"] = 0.01
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            cross.validate_registration(record)

    def test_adaptive_baseline_uses_only_available_history(self):
        forecast, alpha = cross.adaptive_ema_forecast([5.0, 15.0, 5.0])

        self.assertIn(alpha, cross.BASELINE_ALPHAS)
        self.assertGreaterEqual(forecast, 5.0)
        self.assertLessEqual(forecast, 15.0)
        with self.assertRaisesRegex(ValueError, "requires history"):
            cross.adaptive_ema_forecast([])

    def test_session_bundle_recomputes_stronger_baseline_and_seals_sources(self):
        record = registration()
        bundle = session_bundle(
            record,
            datetime(2026, 8, 24, 1, tzinfo=timezone.utc),
            context="lower_activity",
        )

        self.assertEqual("short_horizon_supported", bundle["within_session_status"])
        self.assertEqual("lower_activity", bundle["context_label"])
        self.assertGreater(bundle["effect_vs_adaptive_ema_pp"], 0)
        self.assertEqual(6, len(bundle["source_report_digests"]))
        self.assertEqual(64, len(bundle["session_digest"]))
        self.assertFalse(bundle["runtime_mutated"])
        self.assertFalse(bundle["consciousness_proven"])
        self.assertEqual(bundle, cross.validate_session_bundle(bundle, record))

    def test_six_separated_counterbalanced_sessions_support_only_same_host_claim(self):
        record = registration()
        base = datetime(2026, 8, 24, 1, tzinfo=timezone.utc)
        sessions = [
            session_bundle(
                record,
                base + timedelta(hours=12 * index),
                context="lower_activity" if index % 2 == 0 else "higher_activity",
            )
            for index in range(6)
        ]
        report = cross.score_sessions(
            record,
            sessions,
            scored_at="2026-08-27T12:00:00+00:00",
            scored_by="held-out-report-scorer",
        )

        self.assertEqual("cross_session_supported", report["status"])
        self.assertTrue(all(report["gates"].values()))
        self.assertEqual(6, report["valid_session_count"])
        self.assertGreaterEqual(len(report["distinct_utc_days"]), 3)
        self.assertEqual(
            ["higher_activity", "lower_activity"],
            report["observed_context_strata"],
        )
        self.assertFalse(report["serial_independence_established"])
        self.assertFalse(report["external_authorship_established"])
        self.assertFalse(report["independent_replication_established"])
        self.assertFalse(report["consciousness_proven"])

    def test_insufficient_or_too_close_sessions_do_not_pass(self):
        record = registration()
        base = datetime(2026, 8, 24, 1, tzinfo=timezone.utc)
        first = session_bundle(record, base, context="lower_activity")
        collecting = cross.score_sessions(
            record,
            [first],
            scored_at="2026-08-24T08:00:00+00:00",
            scored_by="held-out-report-scorer",
        )
        self.assertEqual("collecting", collecting["status"])
        self.assertFalse(collecting["gates"]["minimum_valid_sessions_met"])

        close_sessions = [
            session_bundle(
                record,
                base + timedelta(minutes=10 * index),
                context="lower_activity" if index % 2 == 0 else "higher_activity",
            )
            for index in range(6)
        ]
        report = cross.score_sessions(
            record,
            close_sessions,
            scored_at="2026-08-25T12:00:00+00:00",
            scored_by="held-out-report-scorer",
        )
        self.assertEqual("inconclusive", report["status"])
        self.assertFalse(report["gates"]["minimum_session_separation_met"])

    def test_duplicate_overlap_tamper_and_privacy_fail_closed(self):
        record = registration()
        base = datetime(2026, 8, 24, 1, tzinfo=timezone.utc)
        first = session_bundle(record, base, context="lower_activity")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            cross.score_sessions(
                record,
                [first] * 6,
                scored_at="2026-08-25T12:00:00+00:00",
                scored_by="held-out-report-scorer",
            )

        tampered = dict(first)
        tampered["context_label"] = "higher_activity"
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            cross.validate_session_bundle(tampered, record)

        reports = list(first["source_reports"])
        reports[0] = dict(reports[0])
        reports[0]["samples"] = list(reports[0]["samples"])
        reports[0]["samples"][0] = dict(reports[0]["samples"][0])
        reports[0]["samples"][0]["user_content_retained"] = True
        with self.assertRaisesRegex(ValueError, "privacy"):
            cross.build_session_bundle(
                record,
                reports,
                created_at=(base + timedelta(minutes=6)).isoformat(),
                collected_by="host-runner",
            )

        raw = [window_report(base + timedelta(minutes=index), offset=index) for index in range(6)]
        raw[0]["prompt"] = "private prompt"
        with self.assertRaisesRegex(ValueError, "forbidden raw or user payload"):
            cross.build_session_bundle(
                record,
                raw,
                created_at=(base + timedelta(minutes=6)).isoformat(),
                collected_by="host-runner",
            )

        false_score = [
            window_report(base + timedelta(minutes=index), offset=index)
            for index in range(6)
        ]
        false_score[0]["arms"]["intact"][0]["prediction"] = 0.0
        with self.assertRaisesRegex(ValueError, "reported accuracy"):
            cross.build_session_bundle(
                record,
                false_score,
                created_at=(base + timedelta(minutes=6)).isoformat(),
                collected_by="host-runner",
            )


if __name__ == "__main__":
    unittest.main()
