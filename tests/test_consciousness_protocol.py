import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import eve_consciousness_protocol as protocol


REGISTERED_AT = "2026-08-23T12:00:00+00:00"


class ConsciousnessProtocolTests(unittest.TestCase):
    def draft(self):
        return {
            "protocol_id": "quality-space-lesion-v1",
            "registered_at": REGISTERED_AT,
            "subject_system_id": "eve",
            "evaluator_id": "codex-independent-evaluator",
            "objective": "Test whether smooth perceptual geometry causally controls change detection.",
            "trials": [
                {
                    "id": "hot4-quality-space",
                    "theory": "higher_order",
                    "indicator_id": "HOT-4",
                    "intervention": "Lesion graded feature distance while preserving the same inputs and coarse fingerprint.",
                    "intact_arm": "quality space enabled",
                    "lesion_arm": "quality space disabled",
                    "measure_id": "correct_boundary_change_classification",
                    "unit": "accuracy_percent",
                    "expected_direction": "lesion_lower",
                    "minimum_effect": 20,
                    "minimum_samples_per_arm": 3,
                    "evidence_class": "synthetic",
                    "falsifier": "The lesion does not lower classification accuracy by at least 20 points.",
                }
            ],
        }

    def registration(self):
        return protocol.preregister(self.draft())

    def evidence(self, intact=(100, 100, 100), lesion=(60, 60, 60)):
        records = []
        for arm, values in (("intact", intact), ("lesion", lesion)):
            for index, value in enumerate(values):
                records.append(
                    {
                        "evidence_id": f"{arm}-{index}",
                        "trial_id": "hot4-quality-space",
                        "arm": arm,
                        "value": value,
                        "observed_at": f"2026-08-23T12:00:{index + 1:02d}+00:00",
                        "source": "external-matched-lesion-runner",
                        "evidence_class": "synthetic",
                    }
                )
        return records

    def score(self, evidence=None):
        return protocol.score_protocol(
            self.registration(),
            evidence if evidence is not None else self.evidence(),
            scored_by="codex-independent-evaluator",
            scored_at="2026-08-23T12:01:00+00:00",
        )

    def test_preregistered_directional_lesion_can_support_one_indicator(self):
        report = self.score()
        self.assertEqual("supported", report["results"][0]["status"])
        self.assertEqual(40.0, report["results"][0]["directional_effect"])
        self.assertEqual(1, report["counts"]["supported"])
        self.assertEqual(1, report["indicator_coverage"]["observed"])

    def test_opposite_direction_challenges_instead_of_being_reframed(self):
        report = self.score(self.evidence(intact=(40, 40, 40), lesion=(80, 80, 80)))
        self.assertEqual("challenged", report["results"][0]["status"])
        self.assertEqual(-40.0, report["results"][0]["directional_effect"])

    def test_missing_arm_samples_are_inconclusive(self):
        report = self.score(self.evidence()[:4])
        self.assertEqual("inconclusive", report["results"][0]["status"])
        self.assertIn("insufficient", report["results"][0]["reason"])

    def test_tampering_after_registration_is_rejected(self):
        registration = self.registration()
        registration["trials"][0]["minimum_effect"] = 1
        with self.assertRaises(ValueError):
            protocol.score_protocol(
                registration,
                self.evidence(),
                scored_by="external",
                scored_at="2026-08-23T12:01:00+00:00",
            )

    def test_postdated_or_duplicate_evidence_is_rejected(self):
        before = self.evidence()
        before[0]["observed_at"] = "2026-08-23T11:59:59+00:00"
        with self.assertRaises(ValueError):
            self.score(before)
        duplicates = self.evidence()
        duplicates[1]["evidence_id"] = duplicates[0]["evidence_id"]
        with self.assertRaises(ValueError):
            self.score(duplicates)

    def test_self_report_measure_and_self_evaluation_are_rejected(self):
        draft = self.draft()
        draft["trials"][0]["measure_id"] = "self_report_feels_conscious"
        with self.assertRaises(ValueError):
            protocol.preregister(draft)
        draft = self.draft()
        draft["evaluator_id"] = "eve"
        with self.assertRaises(ValueError):
            protocol.preregister(draft)

    def test_synthetic_evidence_cannot_satisfy_a_lived_trial(self):
        draft = self.draft()
        draft["trials"][0]["evidence_class"] = "lived"
        report = protocol.score_protocol(
            protocol.preregister(draft),
            self.evidence(),
            scored_by="external",
            scored_at="2026-08-23T12:01:00+00:00",
        )
        self.assertEqual("inconclusive", report["results"][0]["status"])
        self.assertEqual(6, report["results"][0]["wrong_evidence_class_count"])

    def test_report_is_structurally_unable_to_prove_consciousness(self):
        report = self.score()
        self.assertFalse(report["consciousness_proven"])
        self.assertFalse(report["subjective_experience_inferred"])
        self.assertFalse(report["phenomenality_calibrated"])
        self.assertEqual("not_a_consciousness_verdict", report["verdict"])
        self.assertEqual(14, report["indicator_coverage"]["total_framework_indicators"])

    def test_raw_evidence_is_rejected(self):
        evidence = self.evidence()
        evidence[0]["raw_payload"] = {"transcript": "private"}
        with self.assertRaises(ValueError):
            self.score(evidence)

    def test_cli_registers_and_scores_same_digest(self):
        script = Path(__file__).resolve().parents[1] / "bin" / "eve_consciousness_protocol_eval.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            draft_path = root / "draft.json"
            registration_path = root / "registration.json"
            evidence_path = root / "evidence.json"
            report_path = root / "report.json"
            draft_path.write_text(json.dumps(self.draft()), encoding="utf-8")
            evidence_path.write_text(json.dumps(self.evidence()), encoding="utf-8")
            registered = subprocess.run(
                [sys.executable, str(script), "--register", str(draft_path), "--output", str(registration_path)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, registered.returncode, registered.stderr)
            scored = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--score",
                    str(registration_path),
                    "--evidence",
                    str(evidence_path),
                    "--scored-by",
                    "codex-independent-evaluator",
                    "--scored-at",
                    "2026-08-23T12:01:00+00:00",
                    "--output",
                    str(report_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, scored.returncode, scored.stderr)
            registration = json.loads(registration_path.read_text(encoding="utf-8"))
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(registration["registration_digest"], report["registration_digest"])


if __name__ == "__main__":
    unittest.main()

