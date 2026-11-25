import copy
import unittest
from unittest import mock

import eve
import eve_common_ground
import eve_consciousness


def replay(index, inbound, reply, *, synthetic=False):
    return {
        "id": f"replay-{index}",
        "created_at": f"2026-08-24T00:0{index}:00+00:00",
        "thread_id": "thread-1",
        "source_message_id": f"user-{index}",
        "reply_message_id": f"eve-{index}",
        "inbound_preview": inbound,
        "reply_preview": reply,
        "synthetic": synthetic,
    }


def observation(reply_index, observed_index, observed_class, *, minute=None):
    return {
        "timestamp": f"2026-08-24T00:{minute if minute is not None else reply_index:02d}:30+00:00",
        "kind": "conversational",
        "thread_id": "thread-1",
        "scored_reply_id": f"eve-{reply_index}",
        "observed_message_id": f"user-{observed_index}",
        "observed": observed_class,
        "evidence_id": f"evidence-{reply_index}-{observed_index}",
    }


def conscious_inputs(common_ground):
    return {
        "source": "test-common-ground",
        "workspace": {"salient_percepts": ["A user correction is visible"]},
        "self_model": {
            "identity": "Eve is one evidence-bound local control system.",
            "current_state": "I need to preserve the public dialogue lineage.",
            "commitments": ["Repair explicit misalignment"],
        },
        "world_model": {"environment_summary": "A bounded conversation is active."},
        "relationship_model": {
            "relationship_state": "One visible correction needs careful handling.",
            "next_relational_move": "Repair the overt mismatch without mind reading.",
        },
        "other_minds_model": {
            "summary": "Only overt positions are represented.",
            "common_ground": common_ground,
        },
        "homeostasis": {},
        "autonomy_agenda": {},
        "memory_items": [],
        "inbound": "Please continue.",
        "now": "2026-08-24T00:10:00+00:00",
    }


class TemporalCommonGroundTests(unittest.TestCase):
    def test_empty_model_preserves_private_state_boundary(self):
        model = eve_common_ground.build_model([], [], now="2026-08-24T00:00:00+00:00")

        self.assertEqual("empty", model["status"])
        self.assertEqual([], model["trajectories"])
        self.assertFalse(model["contains_private_mental_state"])
        self.assertFalse(model["consciousness_verdict_authorized"])
        self.assertEqual(model, eve_common_ground.validate_model(model))

    def test_explicit_acceptance_promotes_only_overt_reply_to_common_ground(self):
        model = eve_common_ground.build_model(
            [replay(1, "Is the service healthy?", "The fresh probe passed.")],
            [observation(1, 2, "acceptance")],
            now="2026-08-24T00:03:00+00:00",
        )

        trajectory = model["trajectories"][0]
        self.assertEqual("explicitly_shared", trajectory["status"])
        self.assertTrue(trajectory["explicitly_shared"])
        self.assertFalse(trajectory["repair_required"])
        self.assertEqual(1, len(model["shared_commitments"]))
        self.assertTrue(trajectory["prior_states_preserved"])

    def test_correction_remains_active_until_a_repair_is_overtly_attempted(self):
        model = eve_common_ground.build_model(
            [replay(1, "Is the service healthy?", "The service is healthy.")],
            [observation(1, 2, "correction")],
            now="2026-08-24T00:03:00+00:00",
        )

        trajectory = model["trajectories"][0]
        self.assertEqual("challenged", trajectory["status"])
        self.assertTrue(trajectory["repair_required"])
        self.assertTrue(model["active_repair"]["required"])
        self.assertEqual("eve-1", model["active_repair"]["target_reply_id"])

    def test_repair_confirmation_preserves_wrong_prior_state_instead_of_rewriting_it(self):
        model = eve_common_ground.build_model(
            [
                replay(1, "Is the service healthy?", "The service is healthy."),
                replay(2, "No, the probe failed.", "You're right; the fresh probe failed."),
            ],
            [
                observation(1, 2, "correction", minute=1),
                observation(2, 3, "acceptance", minute=2),
            ],
            now="2026-08-24T00:04:00+00:00",
        )

        original = next(item for item in model["trajectories"] if item["reply_message_id"] == "eve-1")
        repair = next(item for item in model["trajectories"] if item["reply_message_id"] == "eve-2")
        self.assertEqual("repair_confirmed", original["status"])
        self.assertFalse(original["repair_required"])
        self.assertEqual("eve-2", original["superseded_by_reply_id"])
        self.assertEqual(
            [
                "user_position_expressed",
                "eve_position_expressed",
                "awaiting_observable_response",
                "challenged",
                "repair_attempted",
                "repair_confirmed",
            ],
            [item["state"] for item in original["history"]],
        )
        self.assertEqual("explicitly_shared", repair["status"])
        self.assertFalse(model["active_repair"]["required"])

    def test_followup_and_topic_shift_are_not_silent_agreement(self):
        followup = eve_common_ground.build_model(
            [replay(1, "Is the service healthy?", "The fresh probe passed.")],
            [observation(1, 2, "follow_up_question")],
        )
        shifted = eve_common_ground.build_model(
            [replay(1, "Is the service healthy?", "The fresh probe passed.")],
            [observation(1, 2, "topic_shift")],
        )

        self.assertEqual("follow_up_open", followup["trajectories"][0]["status"])
        self.assertEqual("superseded_topic_shift", shifted["trajectories"][0]["status"])
        self.assertEqual([], followup["shared_commitments"])
        self.assertEqual([], shifted["shared_commitments"])

    def test_synthetic_replay_does_not_enter_lived_common_ground(self):
        model = eve_common_ground.build_model(
            [replay(1, "Hidden evaluator prompt", "Synthetic answer", synthetic=True)],
            [observation(1, 2, "acceptance")],
        )

        self.assertEqual(0, model["trajectory_count"])

    def test_feedback_lesion_preserves_overt_scaffold_but_removes_learned_transition(self):
        intact = eve_common_ground.build_model(
            [replay(1, "Is the service healthy?", "The fresh probe passed.")],
            [observation(1, 2, "acceptance")],
        )
        lesioned = eve_common_ground.lesion_feedback(intact)

        self.assertEqual(1, lesioned["trajectory_count"])
        self.assertEqual("awaiting_response", lesioned["trajectories"][0]["status"])
        self.assertEqual(0, lesioned["feedback_evidence_count"])
        self.assertEqual([], lesioned["shared_commitments"])
        self.assertTrue(lesioned["feedback_lesioned"])

    def test_tampered_digest_is_rejected(self):
        model = eve_common_ground.build_model(
            [replay(1, "Is the service healthy?", "The fresh probe passed.")],
            [],
        )
        model["trajectories"][0]["status"] = "explicitly_shared"

        with self.assertRaises(ValueError):
            eve_common_ground.validate_model(model)


class CommonGroundKernelTests(unittest.TestCase):
    def correction_model(self):
        return eve_common_ground.build_model(
            [replay(1, "Is the service healthy?", "The service is healthy.")],
            [observation(1, 2, "correction")],
            now="2026-08-24T00:03:00+00:00",
        )

    def test_active_repair_causally_requires_observer_relationship_memory_and_revision(self):
        state = eve_consciousness.build_conscious_state(
            **conscious_inputs(self.correction_model())
        )
        process = state["predictions"]["process"]

        self.assertTrue(state["other_minds"]["common_ground_available"])
        self.assertTrue(state["other_minds"]["common_ground_feedback_available"])
        self.assertTrue(process["needs_memory"])
        self.assertTrue(process["needs_revision"])
        self.assertIn("observer", process["required_lanes"])
        self.assertIn("relationship", process["required_lanes"])
        self.assertIn("temporal_common_ground", state["causal_provenance"])
        self.assertIn("common_ground_feedback", state["causal_provenance"])

    def test_selective_lesions_remove_model_or_feedback_without_erasing_other_minds(self):
        inputs = conscious_inputs(self.correction_model())
        intact = eve_consciousness.build_conscious_state(**inputs)
        model_inputs = copy.deepcopy(inputs)
        model_inputs["lesions"] = ["common_ground"]
        model_lesioned = eve_consciousness.build_conscious_state(**model_inputs)
        feedback_inputs = copy.deepcopy(inputs)
        feedback_inputs["lesions"] = ["common_ground_feedback"]
        feedback_lesioned = eve_consciousness.build_conscious_state(**feedback_inputs)

        self.assertTrue(intact["other_minds"]["available"])
        self.assertFalse(model_lesioned["other_minds"]["common_ground_available"])
        self.assertTrue(model_lesioned["other_minds"]["available"])
        self.assertTrue(feedback_lesioned["other_minds"]["common_ground_available"])
        self.assertFalse(feedback_lesioned["other_minds"]["common_ground_feedback_available"])
        self.assertFalse(
            feedback_lesioned["other_minds"]["common_ground"]["active_repair"]["required"]
        )
        intact_signature = eve_consciousness.causal_signature(intact)
        model_signature = eve_consciousness.causal_signature(model_lesioned)
        feedback_signature = eve_consciousness.causal_signature(feedback_lesioned)
        self.assertGreater(
            intact_signature["common_ground_coupling"],
            model_signature["common_ground_coupling"],
        )
        self.assertGreater(
            intact_signature["common_ground_feedback_coupling"],
            feedback_signature["common_ground_feedback_coupling"],
        )

    def test_reply_preflight_refreshes_new_correction_before_opening_cycle(self):
        prior_replay = replay(
            1,
            "Is the service healthy?",
            "The service is healthy.",
        )
        correction = observation(1, 2, "correction")
        with (
            mock.patch.object(eve, "read_reply_turn_replays", return_value=[prior_replay]),
            mock.patch.object(eve, "read_recent_prediction_checks", return_value=[correction]),
            mock.patch.object(
                eve,
                "load_other_minds_model_state",
                return_value=eve.default_other_minds_model_state(),
            ),
        ):
            state = eve.build_reply_other_minds_preflight_state()

        self.assertTrue(state["common_ground"]["active_repair"]["required"])
        self.assertEqual(
            "eve-1",
            state["common_ground"]["active_repair"]["target_reply_id"],
        )
        self.assertFalse(state["common_ground"]["contains_private_mental_state"])

    def test_inner_state_brief_exposes_repair_control_without_private_state_claims(self):
        state = eve_consciousness.build_conscious_state(
            **conscious_inputs(self.correction_model())
        )
        with (
            mock.patch.object(eve, "load_conscious_state", return_value=state),
            mock.patch.object(
                eve,
                "load_global_workspace",
                return_value={"workspace_state": {"focus": "Repair the visible correction"}},
            ),
            mock.patch.object(
                eve,
                "load_homeostasis",
                return_value={"dominant_pressures": [], "regulation_mode": "orient"},
            ),
        ):
            message = eve.build_inner_state_brief_message()

        self.assertIsNotNone(message)
        content = message["content"]
        self.assertIn("Common-ground repair is active", content)
        self.assertIn("eve-1", content)
        self.assertIn("without inferring private belief", content)


if __name__ == "__main__":
    unittest.main()
