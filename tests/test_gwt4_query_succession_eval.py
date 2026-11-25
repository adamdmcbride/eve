from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "bin" / "eve_gwt4_query_succession_eval.py"
SPEC = importlib.util.spec_from_file_location(
    "eve_gwt4_query_succession_eval", MODULE_PATH
)
assert SPEC and SPEC.loader
gwt4 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gwt4)


REGISTERED_AT = datetime(2026, 8, 23, 12, tzinfo=timezone.utc)


def registration():
    return gwt4.preregister(
        registered_at=REGISTERED_AT.isoformat(),
        evaluator_id="independent-protocol-operator",
    )


class GWT4QuerySuccessionEvalTests(unittest.TestCase):
    def test_registration_is_gwt4_specific_and_implementation_bound(self):
        record = registration()
        trial = record["trials"][0]

        self.assertEqual("GWT-4", trial["indicator_id"])
        self.assertEqual("global_workspace", trial["theory"])
        self.assertEqual("synthetic", trial["evidence_class"])
        self.assertIn(gwt4.implementation_digest(), record["objective"])
        self.assertFalse(record["consciousness_verdict_authorized"])
        self.assertEqual(
            record["registration_digest"],
            gwt4.validate_registration(record)["registration_digest"],
        )

    def test_matched_query_lesion_supports_only_functional_gwt4_edge(self):
        record = registration()
        result = gwt4.evaluate(
            record,
            evidence_started_at=(REGISTERED_AT + timedelta(minutes=1)).isoformat(),
            scored_by="held-out-gwt4-scorer",
        )
        trial = result["protocol_report"]["results"][0]

        self.assertEqual("supported", trial["status"])
        self.assertEqual(100.0, trial["intact_mean"])
        self.assertEqual(0.0, trial["lesion_mean"])
        self.assertEqual(100.0, trial["directional_effect"])
        self.assertEqual(6, result["case_count"])
        self.assertTrue(result["kernel_suite_passed"])
        self.assertTrue(all(item["causal_result_valid"] for item in result["cases"]))
        self.assertFalse(result["resident_autonomous_querying_established"])
        self.assertFalse(result["minimal_implementation_problem_resolved"])
        self.assertFalse(result["consciousness_proven"])
        self.assertEqual(
            "not_a_consciousness_verdict", result["protocol_report"]["verdict"]
        )

    def test_registration_tamper_and_pre_registration_evidence_fail_closed(self):
        record = registration()
        record["trials"][0]["minimum_effect"] = 1.0
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            gwt4.validate_registration(record)

        with self.assertRaisesRegex(ValueError, "after preregistration"):
            gwt4.evaluate(
                registration(),
                evidence_started_at=REGISTERED_AT.isoformat(),
                scored_by="held-out-gwt4-scorer",
            )

    def test_evaluator_rejects_incomplete_kernel_suite(self):
        record = registration()
        with mock.patch.object(
            gwt4.eve_consciousness,
            "run_state_dependent_query_succession_suite",
            return_value={"cases": [{}] * 5, "passed": False},
        ):
            with self.assertRaisesRegex(ValueError, "six matched"):
                gwt4.evaluate(
                    record,
                    evidence_started_at=(REGISTERED_AT + timedelta(minutes=1)).isoformat(),
                    scored_by="held-out-gwt4-scorer",
                )


if __name__ == "__main__":
    unittest.main()
