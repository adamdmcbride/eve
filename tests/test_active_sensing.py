import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import eve_active_sensing


class ActiveSensingTests(unittest.TestCase):
    def observation_model(self):
        return {
            "open_features": {"open": 0.85, "closed": 0.05},
            "closed_features": {"open": 0.05, "closed": 0.85},
            "ambiguous": {"open": 0.10, "closed": 0.10},
        }

    def orientation(self):
        return {
            "target_id": "visual-1",
            "target_fingerprint": "door-state-v1",
            "subject": "front-door",
            "summary": "The door state is ambiguous.",
            "recommended_action": "look_for_more_evidence",
            "requested_modalities": ["visual"],
            "authority": "proposal_only",
        }

    def opened(self):
        return eve_active_sensing.open_episode(
            self.orientation(),
            question="Is the front door open or closed?",
            expected_observation="A later visual feature should distinguish open from closed.",
            beliefs_before={"open": 0.5, "closed": 0.5},
            observation_model=self.observation_model(),
            observation_model_source="camera_feature_sample.edge_contract.v1",
            executable_action="camera_feature_sample",
            now="2026-08-23T12:00:00+00:00",
        )

    def verified(self):
        return eve_active_sensing.attach_action_result(
            self.opened(),
            {
                "action": "camera_feature_sample",
                "execution_id": "execution-1",
                "status": "completed",
                "executed": True,
                "execution_verification_ok": True,
                "summary": "Feature-only camera sample completed.",
            },
            now="2026-08-23T12:00:01+00:00",
        )

    def observation(self):
        return {
            "id": "observation-1",
            "observed_at": "2026-08-23T12:00:02+00:00",
            "source": "camera_feature_sample",
            "caused_by_execution_id": "execution-1",
            "summary": "Door-edge features support the closed hypothesis.",
            "outcome": "closed_features",
            "target_fingerprint": "door-state-v1",
        }

    def closed(self):
        return eve_active_sensing.close_with_observation(
            self.verified(),
            self.observation(),
        )

    def test_entropy_is_normalized_functional_uncertainty(self):
        self.assertEqual(100.0, eve_active_sensing.normalized_entropy({"a": 1, "b": 1}))
        self.assertLess(eve_active_sensing.normalized_entropy({"a": 99, "b": 1}), 10.0)

    def test_open_episode_is_proposal_only_and_feature_only(self):
        episode = self.opened()
        self.assertEqual("proposed", episode["status"])
        self.assertEqual("proposal_only", episode["orientation"]["authority"])
        self.assertEqual(100.0, episode["prior_uncertainty"])
        self.assertFalse(episode["consequence_qualified"])
        with self.assertRaises(ValueError):
            eve_active_sensing.open_episode(
                {**self.orientation(), "raw_image": b"private"},
                question="What is visible?",
                expected_observation="A feature arrives.",
                beliefs_before={"a": 0.5, "b": 0.5},
                observation_model={
                    "a_seen": {"a": 0.9, "b": 0.1},
                    "b_seen": {"a": 0.1, "b": 0.9},
                },
                observation_model_source="test-model-v1",
            )

    def test_execution_alone_is_not_information_gain(self):
        episode = self.verified()
        self.assertEqual("action_verified", episode["status"])
        self.assertFalse(episode["consequence_qualified"])
        self.assertIsNone(episode["information_gain"])

    def test_exact_action_and_verification_are_required(self):
        wrong_action = eve_active_sensing.attach_action_result(
            self.opened(),
            {
                "action": "different_action",
                "execution_id": "execution-1",
                "status": "completed",
                "executed": True,
                "execution_verification_ok": True,
            },
            now="2026-08-23T12:00:01+00:00",
        )
        self.assertEqual("action_unverified", wrong_action["status"])
        self.assertFalse(wrong_action["consequence_qualified"])

    def test_permission_gated_orientation_requires_permission_evidence(self):
        opened = eve_active_sensing.open_episode(
            {**self.orientation(), "requires_permission": True},
            question="Is the front door open or closed?",
            expected_observation="A permitted feature sample resolves the state.",
            beliefs_before={"open": 0.5, "closed": 0.5},
            observation_model=self.observation_model(),
            observation_model_source="camera_feature_sample.edge_contract.v1",
            executable_action="camera_feature_sample",
            now="2026-08-23T12:00:00+00:00",
        )
        missing_permission = eve_active_sensing.attach_action_result(
            opened,
            {
                "action": "camera_feature_sample",
                "execution_id": "execution-1",
                "status": "completed",
                "executed": True,
                "execution_verification_ok": True,
            },
            now="2026-08-23T12:00:01+00:00",
        )
        permitted = eve_active_sensing.attach_action_result(
            opened,
            {
                "action": "camera_feature_sample",
                "execution_id": "execution-1",
                "status": "completed",
                "executed": True,
                "execution_verification_ok": True,
                "permission_granted": True,
                "permission_evidence_id": "permission-1",
            },
            now="2026-08-23T12:00:01+00:00",
        )
        self.assertEqual("action_unverified", missing_permission["status"])
        self.assertEqual("action_verified", permitted["status"])

    def test_later_causally_linked_observation_can_reduce_uncertainty(self):
        closed = self.closed()
        self.assertEqual("closed_uncertainty_reduced", closed["status"])
        self.assertTrue(closed["consequence_qualified"])
        self.assertGreater(closed["information_gain"], 60)

    def test_belief_revision_is_allowed_when_evidence_reduces_uncertainty(self):
        opened = eve_active_sensing.open_episode(
            self.orientation(),
            question="Is the front door open or closed?",
            expected_observation="A feature resolves the state.",
            beliefs_before={"open": 0.8, "closed": 0.2},
            observation_model=self.observation_model(),
            observation_model_source="camera_feature_sample.edge_contract.v1",
            executable_action="camera_feature_sample",
            now="2026-08-23T12:00:00+00:00",
        )
        verified = eve_active_sensing.attach_action_result(
            opened,
            {
                "action": "camera_feature_sample",
                "execution_id": "execution-1",
                "status": "completed",
                "executed": True,
                "execution_verification_ok": True,
            },
            now="2026-08-23T12:00:01+00:00",
        )
        closed = eve_active_sensing.close_with_observation(
            verified,
            self.observation(),
        )
        self.assertTrue(closed["belief_revision"])
        self.assertTrue(closed["consequence_qualified"])

    def test_stale_or_mismatched_observations_cannot_close(self):
        stale = eve_active_sensing.close_with_observation(
            self.verified(),
            {**self.observation(), "observed_at": "2026-08-23T11:59:59+00:00"},
        )
        mismatched = eve_active_sensing.close_with_observation(
            self.verified(),
            {**self.observation(), "caused_by_execution_id": "another-execution"},
        )
        self.assertEqual("observation_unqualified", stale["status"])
        self.assertEqual("observation_unqualified", mismatched["status"])
        self.assertFalse(stale["consequence_qualified"])
        self.assertFalse(mismatched["consequence_qualified"])

    def test_observation_without_information_gain_is_not_rewarded(self):
        closed = eve_active_sensing.close_with_observation(
            self.verified(),
            {**self.observation(), "outcome": "ambiguous"},
        )
        self.assertEqual("closed_no_material_change", closed["status"])
        self.assertFalse(closed["consequence_qualified"])
        self.assertEqual(0.0, closed["information_gain"])

    def test_unmodeled_outcome_cannot_create_a_posterior(self):
        closed = eve_active_sensing.close_with_observation(
            self.verified(),
            {**self.observation(), "outcome": "caller_invented_certainty"},
        )
        self.assertEqual("observation_unqualified", closed["status"])
        self.assertFalse(closed["consequence_qualified"])

    def test_raw_observation_cannot_cross_feature_boundary(self):
        closed = eve_active_sensing.close_with_observation(
            self.verified(),
            {**self.observation(), "raw_image": b"private"},
        )
        self.assertEqual("observation_unqualified", closed["status"])
        self.assertFalse(closed["consequence_qualified"])

    def test_observation_model_must_be_precommitted_and_normalized(self):
        with self.assertRaises(ValueError):
            eve_active_sensing.open_episode(
                self.orientation(),
                question="Is the door open?",
                expected_observation="A feature resolves the state.",
                beliefs_before={"open": 0.5, "closed": 0.5},
                observation_model={
                    "closed_features": {"open": 0.1, "closed": 0.9},
                    "ambiguous": {"open": 0.1, "closed": 0.1},
                },
                observation_model_source="camera-feature-model-v1",
            )

    def test_later_independent_truth_scores_false_certainty(self):
        correct = eve_active_sensing.score_independent_outcome(
            self.closed(),
            ground_truth_hypothesis="closed",
            ground_truth_source="door_contact_sensor",
            ground_truth_evidence_id="contact-1",
            observed_at="2026-08-23T12:00:03+00:00",
        )
        wrong = eve_active_sensing.score_independent_outcome(
            self.closed(),
            ground_truth_hypothesis="open",
            ground_truth_source="door_contact_sensor",
            ground_truth_evidence_id="contact-2",
            observed_at="2026-08-23T12:00:03+00:00",
        )
        self.assertLess(correct["posterior_brier"], correct["prior_brier"])
        self.assertTrue(correct["top_hypothesis_correct"])
        self.assertGreater(wrong["posterior_brier"], wrong["prior_brier"])
        self.assertFalse(wrong["top_hypothesis_correct"])

    def test_ground_truth_must_be_later_and_independent(self):
        with self.assertRaises(ValueError):
            eve_active_sensing.score_independent_outcome(
                self.closed(),
                ground_truth_hypothesis="closed",
                ground_truth_source="camera_feature_sample",
                ground_truth_evidence_id="observation-1",
                observed_at="2026-08-23T12:00:03+00:00",
            )
        with self.assertRaises(ValueError):
            eve_active_sensing.score_independent_outcome(
                self.closed(),
                ground_truth_hypothesis="closed",
                ground_truth_source="door_contact_sensor",
                ground_truth_evidence_id="contact-before",
                observed_at="2026-08-23T11:59:59+00:00",
            )

    def test_calibration_report_requires_distinct_resolved_episodes(self):
        records = []
        for index in range(5):
            episode = copy.deepcopy(self.closed())
            episode["id"] = f"episode-{index}"
            records.append(
                eve_active_sensing.score_independent_outcome(
                    episode,
                    ground_truth_hypothesis="closed",
                    ground_truth_source="door_contact_sensor",
                    ground_truth_evidence_id=f"contact-{index}",
                    observed_at="2026-08-23T12:00:03+00:00",
                )
            )
        insufficient = eve_active_sensing.calibration_report(records[:4])
        measured = eve_active_sensing.calibration_report([*records, records[0]])
        self.assertEqual("insufficient_independent_outcomes", insufficient["status"])
        self.assertEqual("measured_better_than_prior", measured["status"])
        self.assertEqual(5, measured["resolved_episode_count"])
        self.assertFalse(measured["calibration_proven"])

    def test_matched_causal_evaluation_passes_all_negative_controls(self):
        report = eve_active_sensing.matched_causal_evaluation()
        self.assertEqual("passed", report["status"])
        self.assertTrue(all(report["checks"].values()))
        self.assertTrue(report["intact"]["consequence_qualified"])
        self.assertFalse(
            report["negative_controls"]["no_information_gain"]["consequence_qualified"]
        )

    def test_cli_writes_repeatable_report_without_runtime_state(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "active-sensing.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parents[1] / "bin" / "eve_active_sensing_eval.py"),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("passed", payload["status"])
            self.assertEqual(eve_active_sensing.EVALUATION_SCHEMA_VERSION, payload["schema_version"])


if __name__ == "__main__":
    unittest.main()
