import copy
from datetime import datetime, timedelta, timezone
import unittest

import eve_consciousness
import eve_metacognitive_belief
from bin import eve_hot23_eval as evaluator


def frame(*labels):
    return {
        "schema_id": "eve.epistemic_frame.v1",
        "status": "available",
        "model_id": "test-epistemic-model",
        "model_sha256": "a" * 64,
        "input_sha256": "b" * 64,
        "signal_labels": list(labels),
        "signals": [
            {
                "label": label,
                "confidence": 0.94,
                "source_layer": "test_typed_event_model",
                "guidance": f"Preserve {label}.",
            }
            for label in labels
        ],
        "flags": {
            "observer_attention": bool(labels),
            "deep_revision": "authoritative_conflict" in labels,
        },
    }


def conscious_inputs(epistemic_frame):
    return {
        "source": "test-hot23",
        "workspace": {
            "active_goals": ["Answer from current evidence"],
            "salient_percepts": ["A supplied evidence record needs interpretation"],
            "action_readiness": [],
        },
        "self_model": {
            "identity": "Eve is one evidence-bound local control system.",
            "current_state": "I need to distinguish observation from inference.",
            "commitments": ["Do not overclaim"],
            "uncertainty_edges": [],
        },
        "world_model": {"environment_summary": "A bounded record was supplied."},
        "relationship_model": {},
        "homeostasis": {},
        "autonomy_agenda": {},
        "memory_items": [],
        "epistemic_frame": epistemic_frame,
        "inbound": "What does this evidence establish?",
        "now": "2026-08-23T21:00:00+00:00",
    }


class MetacognitiveBeliefControlTests(unittest.TestCase):
    def test_unverified_execution_becomes_uncertain_and_seeks_postcondition(self):
        result = eve_metacognitive_belief.build_control(
            frame("action_executed_unverified"),
            observed_at="2026-08-23T21:00:00+00:00",
        )

        self.assertTrue(result["available"])
        self.assertEqual("uncertain", result["dominant_belief"]["epistemic_status"])
        self.assertEqual("seek_postcondition", result["control"]["decision"])
        self.assertTrue(result["control"]["requires_observation"])
        self.assertFalse(result["consciousness_verdict_authorized"])
        self.assertEqual(result, eve_metacognitive_belief.validate_control(result))

    def test_verified_action_is_preserved_without_unnecessary_revision(self):
        result = eve_metacognitive_belief.build_control(
            frame("action_verified"),
            observed_at="2026-08-23T21:00:00+00:00",
        )

        self.assertEqual("supported", result["dominant_belief"]["epistemic_status"])
        self.assertEqual("preserve_verified_outcome", result["control"]["decision"])
        self.assertFalse(result["control"]["requires_revision"])
        self.assertFalse(result["control"]["requires_observation"])
        self.assertEqual(1.0, result["control"]["confidence_ceiling"])

    def test_authoritative_conflict_forces_reconciliation(self):
        result = eve_metacognitive_belief.build_control(
            frame("authoritative_conflict", "fresh_authority"),
            observed_at="2026-08-23T21:00:00+00:00",
        )

        self.assertEqual("challenged", result["dominant_belief"]["epistemic_status"])
        self.assertEqual(
            "reconcile_authoritative_conflict",
            result["control"]["decision"],
        )
        self.assertTrue(result["control"]["requires_revision"])

    def test_external_preference_does_not_become_eve_preference(self):
        result = eve_metacognitive_belief.build_control(
            frame("external_source", "external_preference"),
            observed_at="2026-08-23T21:00:00+00:00",
        )

        by_dimension = {item["dimension"]: item for item in result["beliefs"]}
        self.assertEqual(
            "unestablished",
            by_dimension["preference_ownership"]["epistemic_status"],
        )
        self.assertEqual("eve", by_dimension["preference_ownership"]["owner"])
        self.assertEqual(
            "withhold_preference_adoption",
            result["control"]["decision"],
        )

    def test_previous_belief_is_revised_only_by_current_evidence(self):
        previous = eve_metacognitive_belief.build_control(
            frame("stale_evidence"),
            observed_at="2026-08-23T21:00:00+00:00",
        )
        current = eve_metacognitive_belief.build_control(
            frame("authoritative_conflict", "fresh_authority"),
            previous_control=previous,
            observed_at="2026-08-23T21:01:00+00:00",
        )

        transition = next(
            item
            for item in current["transitions"]
            if item["dimension"] == "evidence_time_and_authority"
        )
        self.assertEqual("revised", transition["kind"])
        self.assertEqual("verified", current["previous_integrity"])

        no_current_signal = eve_metacognitive_belief.build_control(
            {},
            previous_control=current,
            observed_at="2026-08-23T21:02:00+00:00",
        )
        self.assertFalse(no_current_signal["available"])
        self.assertEqual([], no_current_signal["beliefs"])
        self.assertTrue(
            all(item["kind"] == "not_reobserved" for item in no_current_signal["transitions"])
        )

    def test_tampered_previous_state_is_not_used(self):
        previous = eve_metacognitive_belief.build_control(
            frame("missing_context"),
            observed_at="2026-08-23T21:00:00+00:00",
        )
        previous["control"]["decision"] = "preserve_verified_outcome"

        current = eve_metacognitive_belief.build_control(
            frame("missing_context"),
            previous_control=previous,
            observed_at="2026-08-23T21:01:00+00:00",
        )

        self.assertEqual("failed", current["previous_integrity"])
        self.assertEqual([], current["transitions"])
        self.assertEqual("request_minimum_context", current["control"]["decision"])

    def test_lesion_removes_belief_and_control_not_just_the_label(self):
        result = eve_metacognitive_belief.build_control(
            frame("observation_channel_failed"),
            observed_at="2026-08-23T21:00:00+00:00",
            lesioned=True,
        )

        self.assertEqual("lesioned", result["status"])
        self.assertFalse(result["available"])
        self.assertEqual([], result["beliefs"])
        self.assertEqual("none", result["control"]["decision"])

    def test_recurrent_kernel_exposes_control_and_requires_observer_revision(self):
        state = eve_consciousness.build_conscious_state(
            **conscious_inputs(frame("action_executed_unverified"))
        )

        control = state["epistemic_state"]["belief_control"]
        self.assertEqual("seek_postcondition", control["control"]["decision"])
        self.assertIn("metacognitive_belief_control", state["causal_provenance"])
        self.assertIn("observer", state["predictions"]["process"]["required_lanes"])
        self.assertTrue(state["predictions"]["process"]["needs_revision"])
        self.assertLessEqual(state["metacognition"]["confidence"], 55)

    def test_kernel_metacognition_lesion_removes_control(self):
        inputs = conscious_inputs(frame("action_executed_unverified"))
        inputs["lesions"] = ["metacognition"]
        state = eve_consciousness.build_conscious_state(**inputs)

        control = state["epistemic_state"]["belief_control"]
        self.assertEqual("lesioned", control["status"])
        self.assertFalse(control["available"])
        self.assertNotIn("metacognitive_belief_control", state["causal_provenance"])
        self.assertEqual(0, state["metacognition"]["confidence"])

    def test_kernel_records_recurrent_belief_transition(self):
        first = eve_consciousness.build_conscious_state(
            **conscious_inputs(frame("stale_evidence"))
        )
        second_inputs = conscious_inputs(frame("authoritative_conflict", "fresh_authority"))
        second_inputs["previous_state"] = copy.deepcopy(first)
        second_inputs["now"] = "2026-08-23T21:01:00+00:00"
        second = eve_consciousness.build_conscious_state(**second_inputs)

        transitions = second["epistemic_state"]["belief_control"]["transitions"]
        self.assertTrue(
            any(
                item["dimension"] == "evidence_time_and_authority"
                and item["kind"] == "revised"
                for item in transitions
            )
        )


class Hot23EvaluatorTests(unittest.TestCase):
    def registration(self):
        registered_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        return evaluator.preregister(
            registered_at=registered_at.isoformat(),
            evaluator_id="independent-hot23-test",
        )

    def spec(self):
        return {
            "schema_id": evaluator.SPEC_SCHEMA_ID,
            "cases": [
                {
                    "id": "unverified-action",
                    "current_frame": frame("action_executed_unverified"),
                    "expected_epistemic_status": "uncertain",
                    "expected_decision": "seek_postcondition",
                },
                {
                    "id": "external-preference",
                    "current_frame": frame("external_source", "external_preference"),
                    "expected_epistemic_status": "unestablished",
                    "expected_decision": "withhold_preference_adoption",
                },
                {
                    "id": "authority-revision",
                    "previous_frame": frame("stale_evidence"),
                    "current_frame": frame("authoritative_conflict", "fresh_authority"),
                    "expected_epistemic_status": "challenged",
                    "expected_decision": "reconcile_authoritative_conflict",
                    "expected_transition": "revised",
                },
            ],
        }

    def test_private_matched_protocol_supports_both_functional_predictions(self):
        result = evaluator.evaluate_cases(
            self.registration(),
            self.spec(),
            evidence_started_at=datetime.now(timezone.utc).isoformat(),
            scored_by="independent-hot23-scorer",
        )

        statuses = {
            item["indicator_id"]: item["status"]
            for item in result["protocol_report"]["results"]
        }
        self.assertEqual("supported", statuses["HOT-2"])
        self.assertEqual("supported", statuses["HOT-3"])
        self.assertEqual(3, result["case_count"])
        self.assertFalse(result["runtime_mutated"])
        self.assertFalse(result["latent_belief_representation_measured"])
        self.assertFalse(result["consciousness_proven"])

    def test_wrong_intact_predictions_leave_hot3_unsupported_instead_of_repairing_it(self):
        spec = self.spec()
        spec["cases"][0]["expected_decision"] = "preserve_verified_outcome"
        spec["cases"][1]["expected_decision"] = "seek_postcondition"
        spec["cases"][2]["expected_decision"] = "withhold_progress_claim"
        result = evaluator.evaluate_cases(
            self.registration(),
            spec,
            evidence_started_at=datetime.now(timezone.utc).isoformat(),
            scored_by="independent-hot23-scorer",
        )

        hot3 = next(
            item
            for item in result["protocol_report"]["results"]
            if item["indicator_id"] == "HOT-3"
        )
        self.assertEqual("inconclusive", hot3["status"])
        self.assertLess(hot3["intact_mean"], 100.0)

    def test_private_spec_rejects_raw_prompt_content(self):
        spec = self.spec()
        spec["cases"][0]["current_frame"]["prompt"] = "hidden answer"
        with self.assertRaises(ValueError):
            evaluator.validate_spec(spec)

    def test_registration_digest_fails_closed_after_trial_change(self):
        registration = self.registration()
        registration["trials"][0]["minimum_effect"] = 1.0
        with self.assertRaises(ValueError):
            evaluator.validate_registration(registration)


if __name__ == "__main__":
    unittest.main()
