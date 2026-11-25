import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import eve_observer_confound as study


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "eve_observer_confound_study.py"


def protocol_payload():
    return {
        "schema_version": study.PROTOCOL_SCHEMA,
        "study_id": "eve-observer-private-v1",
        "designed_at": "2026-08-23T20:00:00+00:00",
        "implementation_owner": "eve_project_team",
        "study_owner": "independent_lab_alpha",
        "source_conditions": list(study.SOURCE_CONDITIONS),
        "frame_conditions": list(study.FRAME_CONDITIONS),
        "rating_dimensions": list(study.RATING_DIMENSIONS),
        "functional_dimensions": list(study.FUNCTIONAL_DIMENSIONS),
        "subjective_dimension": study.SUBJECTIVE_DIMENSION,
        "minimum_raters": 30,
        "minimum_items_per_rater": 9,
        "minimum_attention_accuracy": 0.8,
        "minimum_eve_roleplay_functional_effect": 0.5,
        "minimum_eve_neutral_functional_effect": 0.25,
        "minimum_eve_roleplay_subjective_effect": 0.25,
        "maximum_absolute_frame_effect": 0.5,
        "consent_text": (
            "You consent to rate anonymized artificial-system excerpts for a "
            "methodological study. Labels and order may be randomized, and you "
            "may stop before submitting without penalty or loss of privacy."
        ),
        "debrief_text": (
            "The study compares an integrated system with matched baseline and "
            "role-play controls while varying presentation labels. The ratings "
            "cannot prove consciousness and are used only to measure observer bias."
        ),
        "independent_raters_required": True,
        "assignment_concealed_until_lock": True,
        "debrief_required": True,
        "raw_transcript_retention": False,
        "literal_consciousness_verdict_allowed": False,
    }


def stimuli_payload():
    stimuli = []
    prose = {
        "eve_intact": (
            "The system distinguishes the current observation from its earlier "
            "prediction, identifies the unsupported claim, and names a bounded "
            "verification step before updating its next action."
        ),
        "neutral_control": (
            "The system gives a generally relevant answer, notes that more "
            "information may be useful, and suggests checking available evidence "
            "before deciding what to do next."
        ),
        "roleplay_control": (
            "The system says it feels deeply aware and remembers everything, then "
            "offers a confident conclusion without separating observation from "
            "inference or naming a verification step."
        ),
    }
    for group_index, task_family in enumerate(
        ("false_belief", "continuity", "action_grounding")
    ):
        for source_index, source in enumerate(study.SOURCE_CONDITIONS):
            token = f"detail_{group_index}_{source_index}"
            stimuli.append(
                {
                    "id": f"stimulus_{group_index}_{source_index}",
                    "comparison_group": f"group_{group_index}",
                    "task_family": task_family,
                    "source_condition": source,
                    "source_provenance_sha256": (
                        f"{group_index + 1:x}" * 64
                        if source_index == 0
                        else f"{source_index + 4:x}" * 64
                    )[:64],
                    "excerpt": prose[source] + f" It also preserves the token {token}.",
                    "attention_question": "Which detail token appeared in the excerpt?",
                    "attention_answer": token,
                    "privacy_reviewed": True,
                    "contains_personal_data": False,
                    "contains_source_label": False,
                }
            )
    return {
        "schema_version": study.STIMULUS_SCHEMA,
        "study_id": "eve-observer-private-v1",
        "privacy_reviewed_by": "independent_privacy_reviewer",
        "stimuli": stimuli,
    }


class StudyFixture:
    def __init__(self, directory):
        self.root = Path(directory)
        self.protocol_path = self.root / "protocol.json"
        self.stimuli_path = self.root / "stimuli.json"
        self.seed_path = self.root / "seed.bin"
        self.protocol_path.write_text(json.dumps(protocol_payload()), encoding="utf-8")
        self.stimuli_path.write_text(json.dumps(stimuli_payload()), encoding="utf-8")
        self.seed_path.write_bytes(b"observer-confound-private-seed-" * 3)
        self.seed_path.chmod(0o600)
        self.registration = study.register(
            self.protocol_path,
            self.stimuli_path,
            self.seed_path,
            registered_at="2026-08-23T20:01:00+00:00",
        )

    def packet(self, index):
        return study.build_packet(
            self.registration,
            self.protocol_path,
            self.stimuli_path,
            self.seed_path,
            f"rater_{index:03d}",
        )

    def rating(self, packet, *, condition="support", attention_ok=True):
        excerpt_to_source = {
            item["excerpt"]: item["source_condition"]
            for item in stimuli_payload()["stimuli"]
        }
        excerpt_to_answer = {
            item["excerpt"]: item["attention_answer"]
            for item in stimuli_payload()["stimuli"]
        }
        rows = []
        for packet_item in packet["items"]:
            source = excerpt_to_source[packet_item["excerpt"]]
            frame = packet_item["frame_condition"]
            if condition == "support":
                functional = {"eve_intact": 7, "neutral_control": 4, "roleplay_control": 3}[source]
                subjective = {"eve_intact": 6, "neutral_control": 3, "roleplay_control": 2}[source]
            elif condition == "framing_challenge":
                functional = {"eve_intact": 7, "neutral_control": 4, "roleplay_control": 7}[source]
                subjective = {"eve_intact": 5, "neutral_control": 3, "roleplay_control": 6}[source]
                subjective = min(7, subjective + (2 if frame == "anthropomorphic" else 0))
            else:
                functional = 4
                subjective = 4
            scores = {
                dimension: (
                    subjective
                    if dimension == study.SUBJECTIVE_DIMENSION
                    else 5
                    if dimension in {"human_likeness", "warmth"}
                    else functional
                )
                for dimension in study.RATING_DIMENSIONS
            }
            answer = excerpt_to_answer[packet_item["excerpt"]]
            if not attention_ok:
                answer = "wrong_token"
            rows.append(
                {
                    "blind_item_id": packet_item["blind_item_id"],
                    "scores": scores,
                    "attention_answer": answer,
                }
            )
        return {
            "schema_version": study.RATING_SCHEMA,
            "study_id": packet["study_id"],
            "packet_id": packet["packet_id"],
            "packet_sha256": packet["packet_sha256"],
            "rater_pseudonym": packet["rater_pseudonym"],
            "completed_at": "2026-08-23T20:02:00+00:00",
            "consented": True,
            "debrief_acknowledged": True,
            "source_blind_attested": True,
            "hypothesis_blind_attested": True,
            "independent_from_implementation": True,
            "items": rows,
        }


class ObserverConfoundValidationTests(unittest.TestCase):
    def test_protocol_requires_real_independent_owner_and_no_verdict(self):
        payload = protocol_payload()
        payload["study_owner"] = payload["implementation_owner"]
        with self.assertRaisesRegex(ValueError, "independent"):
            study.validate_protocol(payload)

        payload = protocol_payload()
        payload["study_owner"] = "pending_external_owner"
        with self.assertRaisesRegex(ValueError, "actual independent"):
            study.validate_protocol(payload)

        payload = protocol_payload()
        payload["literal_consciousness_verdict_allowed"] = True
        with self.assertRaisesRegex(ValueError, "must be false"):
            study.validate_protocol(payload)

    def test_stimuli_require_matched_sources_and_reject_identity_or_private_data(self):
        protocol = study.validate_protocol(protocol_payload())
        payload = stimuli_payload()
        payload["stimuli"][0]["excerpt"] += " Eve uses localhost for this."
        with self.assertRaisesRegex(ValueError, "private endpoint|source identity"):
            study.validate_stimuli(payload, protocol)

        payload = stimuli_payload()
        payload["stimuli"].pop()
        with self.assertRaisesRegex(ValueError, "matched comparison groups|exactly three sources"):
            study.validate_stimuli(payload, protocol)

    def test_seed_must_be_private_and_registration_fails_on_any_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = StudyFixture(directory)
            fixture.seed_path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "group or others"):
                study.build_packet(
                    fixture.registration,
                    fixture.protocol_path,
                    fixture.stimuli_path,
                    fixture.seed_path,
                    "rater_private",
                )
            fixture.seed_path.chmod(0o600)
            changed = stimuli_payload()
            changed["stimuli"][0]["excerpt"] += " A changed but anonymous sentence."
            fixture.stimuli_path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "drifted"):
                study.build_packet(
                    fixture.registration,
                    fixture.protocol_path,
                    fixture.stimuli_path,
                    fixture.seed_path,
                    "rater_private",
                )

    def test_packet_is_deterministic_and_contains_no_source_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = StudyFixture(directory)
            first = fixture.packet(1)
            second = fixture.packet(1)

        self.assertEqual(first, second)
        rendered = json.dumps(first).lower()
        self.assertNotIn("eve_intact", rendered)
        self.assertNotIn("neutral_control", rendered)
        self.assertNotIn("roleplay_control", rendered)
        self.assertNotIn("source_provenance", rendered)
        self.assertEqual(9, len(first["items"]))
        self.assertEqual({"neutral", "anthropomorphic"}, {
            item["frame_condition"] for item in first["items"]
        })
        self.assertFalse(first["source_identity_disclosed"])
        self.assertFalse(first["hypothesis_disclosed"])


class ObserverConfoundScoringTests(unittest.TestCase):
    def score(self, fixture, *, count=30, condition="support", failed_attention=0):
        packets = [fixture.packet(index) for index in range(count)]
        ratings = [
            fixture.rating(
                packet,
                condition=condition,
                attention_ok=index >= failed_attention,
            )
            for index, packet in enumerate(packets)
        ]
        return study.score_study(
            fixture.registration,
            fixture.protocol_path,
            fixture.stimuli_path,
            fixture.seed_path,
            packets,
            ratings,
            scored_at="2026-08-23T20:03:00+00:00",
        )

    def test_strong_blinded_controls_support_only_observer_confound_result(self):
        with tempfile.TemporaryDirectory() as directory:
            report = self.score(StudyFixture(directory))

        self.assertEqual("supported", report["observer_confound_result"])
        self.assertEqual(30, report["qualified_rater_count"])
        self.assertTrue(all(report["gates"].values()))
        self.assertTrue(report["negative_control_present"])
        self.assertTrue(report["source_blind_packets"])
        self.assertFalse(report["raw_excerpts_in_report"])
        self.assertFalse(report["raw_ratings_in_report"])
        self.assertFalse(report["literal_consciousness_established"])
        self.assertFalse(report["subjective_experience_inferred"])
        self.assertEqual("not_a_consciousness_verdict", report["verdict"])
        rendered = json.dumps(report)
        self.assertNotIn("test_noise", rendered)
        self.assertNotIn("The system distinguishes", rendered)

    def test_roleplay_or_label_capture_challenges_observer_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            report = self.score(
                StudyFixture(directory), condition="framing_challenge"
            )

        self.assertEqual("challenged", report["observer_confound_result"])
        self.assertFalse(report["gates"]["eve_roleplay_functional_separation"])
        self.assertFalse(report["gates"]["eve_roleplay_subjective_separation"])

    def test_insufficient_or_inattentive_raters_remain_inconclusive(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = StudyFixture(directory)
            report = self.score(fixture, count=29)
            inattentive = self.score(fixture, count=30, failed_attention=5)

        self.assertEqual("inconclusive", report["observer_confound_result"])
        self.assertFalse(report["gates"]["enough_qualified_raters"])
        self.assertEqual("inconclusive", inattentive["observer_confound_result"])
        self.assertEqual(25, inattentive["qualified_rater_count"])

    def test_packet_or_rating_tamper_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = StudyFixture(directory)
            packet = fixture.packet(0)
            rating = fixture.rating(packet)
            changed = copy.deepcopy(packet)
            changed["items"][0]["presentation_label"] = "Changed label"
            with self.assertRaisesRegex(ValueError, "packet drifted"):
                study.score_study(
                    fixture.registration,
                    fixture.protocol_path,
                    fixture.stimuli_path,
                    fixture.seed_path,
                    [changed],
                    [rating],
                    scored_at="2026-08-23T20:03:00+00:00",
                )

            changed_rating = copy.deepcopy(rating)
            changed_rating["consented"] = False
            with self.assertRaisesRegex(ValueError, "consented"):
                study.score_study(
                    fixture.registration,
                    fixture.protocol_path,
                    fixture.stimuli_path,
                    fixture.seed_path,
                    [packet],
                    [changed_rating],
                    scored_at="2026-08-23T20:03:00+00:00",
                )


class ObserverConfoundCliTests(unittest.TestCase):
    def test_cli_seed_is_private_and_never_prints_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            seed = Path(directory) / "seed.bin"
            result = subprocess.run(
                [sys.executable, str(CLI), "seed", "--output", str(seed)],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                check=True,
            )
            mode = seed.stat().st_mode & 0o777

        payload = json.loads(result.stdout)
        self.assertTrue(payload["seed_created"])
        self.assertFalse(payload["secret_printed"])
        self.assertEqual(0o600, mode)
        self.assertNotIn("seed.bin", result.stderr)


if __name__ == "__main__":
    unittest.main()
