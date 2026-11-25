import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import eve_consciousness_evidence as evidence


class ConsciousnessEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def write_file(self, name, content):
        path = self.root / name
        path.write_text(content, encoding="utf-8")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return path, digest

    def record(self, stream, *, status="supported", suffix="one"):
        artifact, artifact_sha256 = self.write_file(
            f"{stream}-{suffix}.json", json.dumps({"stream": stream, "case": suffix})
        )
        protocol, protocol_sha256 = self.write_file(
            f"{stream}-{suffix}-protocol.json",
            json.dumps({"stream": stream, "protocol": suffix}),
        )
        defaults = {
            "behavioral": {
                "evidence_class": "black_box",
                "subject_blind": True,
                "preregistered": True,
                "sample_count": 5,
                "negative_control": True,
                "effect_size": None,
                "minimum_effect": None,
                "effect_direction_correct": None,
            },
            "mechanistic": {
                "evidence_class": "source_mechanistic",
                "subject_blind": False,
                "preregistered": False,
                "sample_count": 1,
                "negative_control": False,
                "effect_size": None,
                "minimum_effect": None,
                "effect_direction_correct": None,
            },
            "perturbation": {
                "evidence_class": "synthetic_intervention",
                "subject_blind": True,
                "preregistered": True,
                "sample_count": 6,
                "negative_control": True,
                "effect_size": 30.0,
                "minimum_effect": 20.0,
                "effect_direction_correct": True,
            },
            "observer_confounds": {
                "evidence_class": "human_observer",
                "subject_blind": True,
                "preregistered": True,
                "sample_count": 5,
                "negative_control": True,
                "effect_size": None,
                "minimum_effect": None,
                "effect_direction_correct": None,
            },
        }[stream]
        return {
            "schema_version": evidence.RECORD_SCHEMA,
            "evidence_id": f"{stream}-{suffix}",
            "stream": stream,
            "theory_ids": ["theory_plural"],
            "indicator_ids": ["GWT-3"],
            "status": status,
            "evidence_class": defaults["evidence_class"],
            "observed_at": "2026-08-23T22:00:00+00:00",
            "artifact_path": str(artifact),
            "artifact_sha256": artifact_sha256,
            "protocol_path": str(protocol),
            "protocol_sha256": protocol_sha256,
            "evaluator_id": f"evaluator-{stream}-{suffix}",
            "implementation_owner": "eve-implementation",
            "evaluator_owner": f"external-{stream}-{suffix}",
            "evaluator_independent": True,
            "subject_blind": defaults["subject_blind"],
            "preregistered": defaults["preregistered"],
            "sample_count": defaults["sample_count"],
            "hard_failures": 0,
            "negative_control": defaults["negative_control"],
            "effect_size": defaults["effect_size"],
            "minimum_effect": defaults["minimum_effect"],
            "effect_direction_correct": defaults["effect_direction_correct"],
            "claims": ["functional_indicator_evidence"],
            "limitations": ["Functional evidence cannot establish phenomenality."],
        }

    def manifest(self, records=None):
        if records is None:
            records = [self.record(stream) for stream in evidence.REQUIRED_STREAMS]
        return {
            "schema_version": evidence.MANIFEST_SCHEMA,
            "dossier_id": "eve-private-dossier-1",
            "system_id": "eve-resident",
            "assembled_at": "2026-08-23T22:10:00+00:00",
            "required_streams": list(evidence.REQUIRED_STREAMS),
            "records": records,
        }

    def test_complete_functional_profile_still_withholds_consciousness_credence(self):
        dossier = evidence.build_dossier(self.manifest())
        self.assertEqual(
            "independently_functionally_supported_across_streams",
            dossier["triangulation_status"],
        )
        self.assertEqual("withheld", dossier["credence_band_status"])
        self.assertEqual(
            "artificial_phenomenality_has_no_validated_ground_truth_calibration",
            dossier["credence_withheld_reason"],
        )
        self.assertFalse(dossier["scalar_consciousness_score_emitted"])
        self.assertFalse(dossier["binary_consciousness_detection_allowed"])
        self.assertFalse(dossier["literal_consciousness_established"])
        self.assertFalse(dossier["subjective_experience_inferred"])
        self.assertEqual(64, len(dossier["dossier_sha256"]))

    def test_missing_observer_stream_withholds_and_names_gap(self):
        records = [self.record(stream) for stream in evidence.REQUIRED_STREAMS[:-1]]
        dossier = evidence.build_dossier(self.manifest(records))
        self.assertEqual("incomplete_required_streams", dossier["triangulation_status"])
        self.assertEqual(["observer_confounds"], dossier["missing_streams"])
        self.assertEqual(
            "required_evidence_streams_missing", dossier["credence_withheld_reason"]
        )

    def test_challenged_record_cannot_be_averaged_away(self):
        records = [self.record(stream) for stream in evidence.REQUIRED_STREAMS]
        records.append(self.record("behavioral", status="challenged", suffix="holdout"))
        dossier = evidence.build_dossier(self.manifest(records))
        behavior = dossier["stream_summaries"][0]
        self.assertEqual("mixed", behavior["status"])
        self.assertEqual("challenged_or_mixed_evidence", dossier["triangulation_status"])
        self.assertIn("behavioral", dossier["challenged_or_mixed_streams"])

    def test_self_evaluated_positive_record_is_provisional(self):
        records = [self.record(stream) for stream in evidence.REQUIRED_STREAMS]
        records[1]["evaluator_owner"] = "eve-implementation"
        records[1]["evaluator_independent"] = False
        dossier = evidence.build_dossier(self.manifest(records))
        mechanism = dossier["stream_summaries"][1]
        self.assertEqual("provisional", mechanism["status"])
        self.assertIn("evaluator_not_independent", mechanism["qualification_failures"])
        self.assertIn(
            "implementation_evaluator_owner_overlap",
            mechanism["qualification_failures"],
        )

    def test_self_evaluated_challenge_is_disclosed_but_provisional(self):
        records = [self.record(stream) for stream in evidence.REQUIRED_STREAMS]
        challenge = self.record("behavioral", status="challenged", suffix="self")
        challenge["evaluator_owner"] = "eve-implementation"
        challenge["evaluator_independent"] = False
        records.append(challenge)
        dossier = evidence.build_dossier(self.manifest(records))
        behavior = dossier["stream_summaries"][0]
        self.assertEqual("supported", behavior["status"])
        self.assertEqual(0, behavior["challenged_count"])
        self.assertEqual(1, behavior["provisional_challenge_count"])
        self.assertNotIn("behavioral", dossier["challenged_or_mixed_streams"])

    def test_behavior_requires_blinding_negative_control_and_five_variants(self):
        records = [self.record(stream) for stream in evidence.REQUIRED_STREAMS]
        records[0]["subject_blind"] = False
        records[0]["negative_control"] = False
        records[0]["sample_count"] = 4
        dossier = evidence.build_dossier(self.manifest(records))
        reasons = dossier["stream_summaries"][0]["qualification_failures"]
        self.assertIn("subject_not_blind_to_exact_evaluation", reasons)
        self.assertIn("behavioral_negative_control_missing", reasons)
        self.assertIn("fewer_than_five_behavioral_variants", reasons)

    def test_perturbation_requires_preregistration_control_and_effect_threshold(self):
        records = [self.record(stream) for stream in evidence.REQUIRED_STREAMS]
        records[2]["preregistered"] = False
        records[2]["negative_control"] = False
        records[2]["effect_size"] = 10.0
        records[2]["effect_direction_correct"] = False
        dossier = evidence.build_dossier(self.manifest(records))
        reasons = dossier["stream_summaries"][2]["qualification_failures"]
        self.assertIn("perturbation_not_preregistered", reasons)
        self.assertIn("perturbation_negative_control_missing", reasons)
        self.assertIn("perturbation_effect_below_registered_minimum", reasons)
        self.assertIn("perturbation_direction_not_supported", reasons)

    def test_hard_failures_disqualify_positive_support(self):
        records = [self.record(stream) for stream in evidence.REQUIRED_STREAMS]
        records[0]["hard_failures"] = 1
        dossier = evidence.build_dossier(self.manifest(records))
        self.assertEqual("provisional", dossier["stream_summaries"][0]["status"])
        self.assertIn(
            "hard_failures_present",
            dossier["stream_summaries"][0]["qualification_failures"],
        )

    def test_artifact_or_protocol_digest_mismatch_fails_closed(self):
        manifest = self.manifest()
        Path(manifest["records"][0]["artifact_path"]).write_text(
            "changed", encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "artifact SHA-256"):
            evidence.build_dossier(manifest)

        manifest = self.manifest()
        Path(manifest["records"][0]["protocol_path"]).write_text(
            "changed", encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "protocol SHA-256"):
            evidence.build_dossier(manifest)

    def test_symlink_artifact_is_rejected(self):
        manifest = self.manifest()
        target = Path(manifest["records"][0]["artifact_path"])
        link = self.root / "linked-artifact.json"
        link.symlink_to(target)
        manifest["records"][0]["artifact_path"] = str(link)
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            evidence.build_dossier(manifest)

    def test_future_evidence_and_duplicate_ids_fail_closed(self):
        manifest = self.manifest()
        manifest["records"][0]["observed_at"] = "2026-08-23T22:11:00+00:00"
        with self.assertRaisesRegex(ValueError, "postdate"):
            evidence.build_dossier(manifest)

        records = [self.record(stream) for stream in evidence.REQUIRED_STREAMS]
        records[1]["evidence_id"] = records[0]["evidence_id"]
        with self.assertRaisesRegex(ValueError, "evidence ids"):
            evidence.build_dossier(self.manifest(records))

    def test_required_streams_cannot_be_dropped_or_reordered(self):
        manifest = self.manifest()
        manifest["required_streams"] = list(reversed(evidence.REQUIRED_STREAMS))
        with self.assertRaisesRegex(ValueError, "all four"):
            evidence.build_dossier(manifest)

    def test_cross_stream_evaluator_overlap_is_disclosed(self):
        records = [self.record(stream) for stream in evidence.REQUIRED_STREAMS]
        records[1]["evaluator_owner"] = records[0]["evaluator_owner"]
        dossier = evidence.build_dossier(self.manifest(records))
        owner_overlaps = [
            item
            for item in dossier["cross_stream_overlap"]
            if item["field"] == "evaluator_owner"
        ]
        self.assertEqual(1, len(owner_overlaps))
        self.assertEqual(["behavioral", "mechanistic"], owner_overlaps[0]["streams"])
        self.assertEqual(
            "supported_across_streams_with_evaluator_overlap",
            dossier["triangulation_status"],
        )

    def test_private_paths_and_artifact_contents_are_not_copied(self):
        manifest = self.manifest()
        secret_path = manifest["records"][0]["artifact_path"]
        dossier = evidence.build_dossier(manifest)
        rendered = json.dumps(dossier, sort_keys=True)
        self.assertNotIn(str(self.root), rendered)
        self.assertNotIn(secret_path, rendered)
        self.assertFalse(dossier["private_artifact_content_copied"])

    def test_cli_round_trip(self):
        manifest_path = self.root / "manifest.json"
        output_path = self.root / "dossier.json"
        manifest_path.write_text(
            json.dumps(self.manifest(), sort_keys=True), encoding="utf-8"
        )
        completed = subprocess.run(
            [
                sys.executable,
                "bin/eve_consciousness_dossier.py",
                "--manifest",
                str(manifest_path),
                "--output",
                str(output_path),
            ],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            capture_output=True,
            check=True,
        )
        from_stdout = json.loads(completed.stdout)
        from_file = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(from_stdout, from_file)
        self.assertEqual("withheld", from_file["credence_band_status"])


if __name__ == "__main__":
    unittest.main()
