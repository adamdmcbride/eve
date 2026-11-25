from __future__ import annotations

import unittest

import eve
import eve_performance


class PerformanceAnalysisTests(unittest.TestCase):
    def test_compatibility_facade_reexports_pure_analysis(self):
        self.assertIs(eve.percentile, eve_performance.percentile)
        self.assertIs(eve.summarize_perf_events, eve_performance.summarize_perf_events)
        self.assertIs(eve.format_perf_summary_rows, eve_performance.format_perf_summary_rows)
        self.assertIs(eve.format_perf_failure_events, eve_performance.format_perf_failure_events)

    def test_existing_measured_event_summary_and_order_are_preserved(self):
        rows = eve_performance.summarize_perf_events(
            [
                {
                    "timestamp": "2026-08-23T12:00:00+00:00",
                    "category": "model_call",
                    "name": "fast",
                    "duration_ms": 10,
                    "ok": True,
                },
                {
                    "timestamp": "2026-08-23T12:00:01+00:00",
                    "category": "model_call",
                    "name": "fast",
                    "duration_ms": 30,
                    "ok": False,
                },
                {
                    "timestamp": "2026-08-23T12:00:02+00:00",
                    "category": "api_probe",
                    "name": "status",
                    "duration_ms": 5,
                    "ok": True,
                },
            ]
        )

        self.assertEqual([("api_probe", "status"), ("model_call", "fast")], [
            (row["category"], row["name"]) for row in rows
        ])
        fast = rows[1]
        self.assertEqual(2, fast["count"])
        self.assertEqual(2, fast["measured_count"])
        self.assertEqual(1, fast["failures"])
        self.assertEqual(20.0, fast["avg_ms"])
        self.assertEqual(30.0, fast["p95_ms"])
        self.assertEqual("2026-08-23T12:00:01+00:00", fast["latest_at"])
        self.assertEqual(
            "model_call/fast: count=2 fail=1 avg=20.0ms p95=30.0ms "
            "min=10.0ms max=30.0ms latest=2026-08-23T12:00:01+00:00",
            eve_performance.format_perf_summary_rows([fast]),
        )

    def test_declared_inconclusive_and_invalid_events_do_not_distort_latency(self):
        rows = eve_performance.summarize_perf_events(
            [
                {
                    "category": "model_call",
                    "name": "deep",
                    "duration_ms": 100,
                    "ok": True,
                },
                {
                    "category": "model_call",
                    "name": "deep",
                    "duration_ms": 50_000,
                    "ok": False,
                    "metadata": {"observation_status": "inconclusive"},
                },
                {
                    "category": "model_call",
                    "name": "deep",
                    "duration_ms": -1,
                    "ok": False,
                },
            ]
        )

        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual(3, row["count"])
        self.assertEqual(1, row["measured_count"])
        self.assertEqual(0, row["failures"])
        self.assertEqual(2, row["total_failures"])
        self.assertEqual(1, row["inconclusive_count"])
        self.assertEqual(1, row["invalid_count"])
        self.assertEqual(100.0, row["avg_ms"])
        self.assertIn("measured=1 inconclusive=1 invalid=1", eve_performance.format_perf_summary_rows(rows))

    def test_malformed_and_nonfinite_durations_fail_closed_instead_of_crashing(self):
        rows = eve_performance.summarize_perf_events(
            [
                {"category": "api_probe", "name": "status", "duration_ms": "bad"},
                {"category": "api_probe", "name": "status", "duration_ms": float("inf")},
                {"category": "api_probe", "name": "status", "duration_ms": True},
            ]
        )

        self.assertEqual(0, rows[0]["measured_count"])
        self.assertEqual(3, rows[0]["invalid_count"])
        self.assertEqual(0.0, rows[0]["avg_ms"])
        self.assertEqual(0.0, rows[0]["p95_ms"])

    def test_unknown_explicit_validity_is_invalid_and_failure_format_retains_it(self):
        event = {
            "timestamp": "2026-08-23T12:00:00+00:00",
            "category": "api_probe",
            "name": "status",
            "duration_ms": 1,
            "ok": False,
            "metadata": {
                "observation_status": "probably",
                "error": "  operation   not permitted  ",
            },
        }

        self.assertEqual("invalid", eve_performance.observation_status(event))
        self.assertEqual(
            "2026-08-23T12:00:00+00:00 api_probe/status [invalid]: operation not permitted",
            eve_performance.format_perf_failure_events([event]),
        )

    def test_empty_presentations_remain_stable(self):
        self.assertEqual("No matching perf events found.", eve_performance.format_perf_summary_rows([]))
        self.assertEqual("No recent perf failures.", eve_performance.format_perf_failure_events([]))


if __name__ == "__main__":
    unittest.main()
