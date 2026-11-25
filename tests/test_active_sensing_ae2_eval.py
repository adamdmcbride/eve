from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "bin" / "eve_active_sensing_ae2_eval.py"
SPEC = importlib.util.spec_from_file_location("eve_active_sensing_ae2_eval", MODULE_PATH)
assert SPEC and SPEC.loader
ae2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ae2)


REGISTERED_AT = datetime(2026, 8, 23, 12, tzinfo=timezone.utc)


def registration():
    return ae2.preregister(
        registered_at=REGISTERED_AT.isoformat(),
        evaluator_id="independent-protocol-operator",
    )


class ActiveSensingAE2EvalTests(unittest.TestCase):
    def test_registration_is_ae2_specific_and_implementation_bound(self):
        record = registration()
        trial = record["trials"][0]

        self.assertEqual("AE-2", trial["indicator_id"])
        self.assertEqual("agency_embodiment", trial["theory"])
        self.assertEqual("synthetic", trial["evidence_class"])
        self.assertIn(ae2.evaluator_digest(), record["objective"])
        self.assertFalse(record["consciousness_verdict_authorized"])
        self.assertEqual(
            record["registration_digest"],
            ae2.validate_ae2_registration(record)["registration_digest"],
        )

    def test_matched_linkage_lesion_supports_only_functional_ae2(self):
        record = registration()
        start = REGISTERED_AT + timedelta(minutes=1)
        result = ae2.evaluate_scenarios(
            record,
            ae2.default_scenarios(start),
            evidence_started_at=start.isoformat(),
            scored_by="held-out-ae2-scorer",
        )
        trial = result["protocol_report"]["results"][0]

        self.assertEqual("supported", trial["status"])
        self.assertEqual(100.0, trial["intact_mean"])
        self.assertEqual(0.0, trial["lesion_mean"])
        self.assertEqual(100.0, trial["directional_effect"])
        self.assertEqual(3, result["scenario_count"])
        self.assertTrue(
            all(item["matched_snapshot"] for item in result["scenarios"])
        )
        self.assertTrue(
            all(item["intact_consequence_qualified"] for item in result["scenarios"])
        )
        self.assertFalse(
            any(item["lesion_consequence_qualified"] for item in result["scenarios"])
        )
        self.assertFalse(result["lived_agency_established"])
        self.assertFalse(result["consciousness_proven"])
        self.assertFalse(result["subjective_experience_inferred"])
        self.assertEqual("not_a_consciousness_verdict", result["protocol_report"]["verdict"])

    def test_uninformative_intact_arm_is_inconclusive_not_repaired(self):
        record = registration()
        start = REGISTERED_AT + timedelta(minutes=1)
        result = ae2.evaluate_scenarios(
            record,
            [{}, {}, {}],
            evidence_started_at=start.isoformat(),
            scored_by="held-out-ae2-scorer",
        )
        trial = result["protocol_report"]["results"][0]

        self.assertEqual("inconclusive", trial["status"])
        self.assertEqual(0.0, trial["directional_effect"])

    def test_evidence_must_follow_registration_and_meet_sample_count(self):
        record = registration()
        scenarios = ae2.default_scenarios(REGISTERED_AT)
        with self.assertRaisesRegex(ValueError, "after preregistration"):
            ae2.evaluate_scenarios(
                record,
                scenarios,
                evidence_started_at=REGISTERED_AT.isoformat(),
                scored_by="held-out-ae2-scorer",
            )
        with self.assertRaisesRegex(ValueError, "at least three"):
            ae2.evaluate_scenarios(
                record,
                scenarios[:2],
                evidence_started_at=(REGISTERED_AT + timedelta(minutes=1)).isoformat(),
                scored_by="held-out-ae2-scorer",
            )

    def test_registration_tamper_and_extra_snapshot_payload_fail_closed(self):
        record = registration()
        record["trials"][0]["minimum_effect"] = 1.0
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            ae2.validate_ae2_registration(record)

        clean = registration()
        start = REGISTERED_AT + timedelta(minutes=1)
        scenarios = ae2.default_scenarios(start)
        scenarios[0]["prompt"] = "private content"
        with self.assertRaisesRegex(ValueError, "typed service-health"):
            ae2.evaluate_scenarios(
                clean,
                scenarios,
                evidence_started_at=start.isoformat(),
                scored_by="held-out-ae2-scorer",
            )


if __name__ == "__main__":
    unittest.main()
