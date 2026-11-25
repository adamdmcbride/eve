import copy
import unittest
from unittest import mock

import eve
import eve_autobiography
import eve_consciousness


def correction_episode(
    episode_id="episode-correction-1",
    *,
    created_at="2026-08-23T10:00:00+00:00",
    thread_id="thread-1",
    error="claimed success before checking",
    change="verify the current consequence before claiming success",
):
    return {
        "id": episode_id,
        "created_at": created_at,
        "source": "chat_user_correction",
        "thread_id": thread_id,
        "what_happened": "The user corrected Eve after an unsupported completion claim.",
        "what_user_cared_about": "current verified evidence and honest completion claims",
        "what_eve_got_wrong": error,
        "what_changed_afterward": change,
        "correction_ids": [f"correction-{episode_id}"],
        "metadata": {"user_correction_id": f"correction-{episode_id}"},
    }


def verified_presence_episode(
    episode_id="episode-presence-1",
    *,
    created_at="2026-08-23T12:00:00+00:00",
    thread_id="presence",
):
    return {
        "id": episode_id,
        "created_at": created_at,
        "source": "quiet_consolidation_presence_episode_extraction",
        "thread_id": thread_id,
        "what_happened": "Eve ran a bounded service-health action and verified its consequence.",
        "what_user_cared_about": "actions should leave current evidence",
        "what_eve_got_wrong": "",
        "what_changed_afterward": "bind a presence claim to the matched action and verification record",
        "evidence_ids": ["presence-cycle-1", "developmental-cycle-1"],
        "metadata": {
            "source_presence_cycle_id": "presence-cycle-1",
            "verification_ok": True,
            "action_matched_contract": True,
        },
    }


class AutobiographicalContinuityTests(unittest.TestCase):
    def test_temporal_projection_preserves_prior_change_lineage(self):
        first = correction_episode()
        second = correction_episode(
            "episode-correction-2",
            created_at="2026-08-23T11:00:00+00:00",
            error="repeated a stale answer after a correction",
            change="retrieve the prior correction before revising the next answer",
        )
        state = eve_autobiography.build_state(
            [second, first],
            query="How should you answer after a stale completion claim?",
            now="2026-08-23T12:00:00+00:00",
        )

        self.assertEqual(2, state["event_count"])
        self.assertEqual(2, state["change_count"])
        self.assertEqual("episode-correction-1", state["events"][0]["episode_id"])
        self.assertEqual("episode-correction-1", state["events"][1]["previous_episode_id"])
        self.assertEqual(state["changes"][0]["change_id"], state["changes"][1]["previous_change_id"])
        self.assertTrue(state["trajectories"][0]["prior_states_preserved"])
        self.assertFalse(state["changes"][1]["chronology_alone_treated_as_causation"])

    def test_only_source_grounded_events_and_changes_are_admitted(self):
        unverified = {
            "id": "episode-unverified",
            "created_at": "2026-08-23T09:00:00+00:00",
            "source": "manual",
            "what_happened": "Eve imagined that she had changed.",
            "what_changed_afterward": "invented change",
        }
        self_output = {
            **correction_episode("episode-self-output"),
            "source": "self_output_reflection",
            "metadata": {"self_output": True},
        }
        synthetic = {
            **correction_episode("episode-synthetic"),
            "source": "synthetic_evaluator",
            "synthetic": True,
        }
        exchange = {
            "id": "episode-exchange",
            "created_at": "2026-08-23T09:30:00+00:00",
            "source": "daemon_episode_extraction",
            "thread_id": "thread-2",
            "what_happened": "The user asked a substantive question and Eve answered.",
            "what_user_cared_about": "a substantive question",
            "what_changed_afterward": "",
            "evidence_ids": ["user-message-1", "eve-reply-1"],
            "metadata": {"source_message_id": "user-message-1", "reply_message_id": "eve-reply-1"},
        }

        state = eve_autobiography.build_state(
            [unverified, self_output, synthetic, exchange, correction_episode()],
            query="current verified evidence",
            now="2026-08-23T12:00:00+00:00",
        )

        self.assertEqual(
            {"episode-exchange", "episode-correction-1"},
            {item["episode_id"] for item in state["events"]},
        )
        self.assertEqual(1, state["change_count"])
        self.assertTrue(all(item["self_output_used_as_observation"] is False for item in state["events"]))
        self.assertTrue(all(item["private_mental_state_inferred"] is False for item in state["events"]))

    def test_verified_action_consequence_is_a_change_but_plain_exchange_is_not(self):
        exchange = {
            "id": "episode-exchange",
            "created_at": "2026-08-23T11:00:00+00:00",
            "source": "daemon_episode_extraction",
            "thread_id": "presence",
            "what_happened": "A real exchange occurred.",
            "what_changed_afterward": "a narrator says this mattered",
            "evidence_ids": ["message-1"],
            "metadata": {"source_message_id": "message-1"},
        }
        state = eve_autobiography.build_state(
            [exchange, verified_presence_episode()],
            query="How should presence claims use matched action evidence?",
            now="2026-08-23T13:00:00+00:00",
        )

        self.assertEqual(2, state["event_count"])
        self.assertEqual(1, state["change_count"])
        self.assertEqual("verified_action_learning", state["changes"][0]["change_kind"])
        self.assertEqual("verified", state["changes"][0]["change_strength"])
        self.assertEqual("verified", state["changes"][0]["change_status"])

    def test_relevance_selects_a_prior_change_and_abstains_when_unrelated(self):
        episodes = [correction_episode(), verified_presence_episode()]
        relevant = eve_autobiography.build_state(
            episodes,
            query="Before claiming success, should you verify current evidence?",
            now="2026-08-23T13:00:00+00:00",
        )
        unrelated = eve_autobiography.build_state(
            episodes,
            query="What color is the ocean?",
            now="2026-08-23T13:00:00+00:00",
        )

        self.assertTrue(relevant["selected_precedent"]["selected"])
        self.assertEqual("episode-correction-1", relevant["selected_precedent"]["episode_id"])
        self.assertTrue(relevant["selected_precedent"]["requires_revision"])
        self.assertEqual("revision_required", relevant["selected_precedent"]["change_status"])
        self.assertEqual({}, unrelated["selected_precedent"])

    def test_change_lesion_preserves_event_sequence_but_removes_policy_change(self):
        intact = eve_autobiography.build_state(
            [correction_episode(), verified_presence_episode()],
            query="verify current evidence before claiming success",
            now="2026-08-23T13:00:00+00:00",
        )
        lesioned = eve_autobiography.lesion_change(intact)

        self.assertEqual(intact["event_count"], lesioned["event_count"])
        self.assertEqual(intact["trajectory_count"], lesioned["trajectory_count"])
        self.assertEqual(0, lesioned["change_count"])
        self.assertEqual({}, lesioned["selected_precedent"])
        self.assertTrue(lesioned["change_lesioned"])
        self.assertTrue(all(not item["change_eligible"] for item in lesioned["events"]))

    def test_full_lesion_removes_projection(self):
        intact = eve_autobiography.build_state(
            [correction_episode()],
            query="verify current evidence",
            now="2026-08-23T13:00:00+00:00",
        )
        lesioned = eve_autobiography.lesion_all(intact)
        self.assertEqual(0, lesioned["event_count"])
        self.assertEqual(0, lesioned["trajectory_count"])
        self.assertTrue(lesioned["autobiography_lesioned"])

    def test_transient_memory_item_references_source_without_writing_duplicate_episode(self):
        state = eve_autobiography.build_state(
            [correction_episode()],
            query="verify current evidence before claiming success",
            now="2026-08-23T13:00:00+00:00",
        )
        item = eve_autobiography.transient_memory_item(state)

        self.assertEqual("autobiographical_continuity", item["source"])
        self.assertEqual("episode-correction-1", item["episode_id"])
        self.assertTrue(item["transient_projection"])
        self.assertFalse(item["contains_private_mental_state"])

    def test_digest_validation_rejects_tampering(self):
        state = eve_autobiography.build_state(
            [correction_episode()],
            query="verify current evidence",
            now="2026-08-23T13:00:00+00:00",
        )
        eve_autobiography.validate_state(state)
        tampered = copy.deepcopy(state)
        tampered["changes"][0]["change_directive"] = "invented replacement"
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            eve_autobiography.validate_state(tampered)


class AutobiographicalKernelIntegrationTests(unittest.TestCase):
    def state_and_memory(self):
        state = eve_autobiography.build_state(
            [correction_episode()],
            query="Before claiming success, should current evidence be verified?",
            now="2026-08-23T13:00:00+00:00",
        )
        return state, [eve_autobiography.transient_memory_item(state)]

    def kernel_inputs(self):
        autobiography, memory_items = self.state_and_memory()
        return {
            "source": "test-autobiographical-continuity",
            "workspace": {"salient_percepts": ["A completion report is being prepared."]},
            "self_model": {
                "identity": "Eve is one evidence-bound local control system.",
                "current_state": "A prior correction may be relevant.",
            },
            "world_model": {"environment_summary": "A bounded conversation is active."},
            "relationship_model": {"relationship_state": "No private state is inferred."},
            "other_minds_model": {},
            "homeostasis": {},
            "autonomy_agenda": {},
            "autobiography": autobiography,
            "memory_items": memory_items,
            "inbound": "Before claiming success, should current evidence be verified?",
            "now": "2026-08-23T13:01:00+00:00",
        }

    def test_relevant_prior_change_causally_controls_memory_and_revision(self):
        intact = eve_consciousness.build_conscious_state(**self.kernel_inputs())
        process = intact["predictions"]["process"]

        self.assertEqual(1, intact["autobiography"]["change_count"])
        self.assertTrue(intact["autobiography"]["selected_precedent"]["selected"])
        self.assertTrue(process["needs_memory"])
        self.assertTrue(process["needs_revision"])
        self.assertIn("observer", process["required_lanes"])
        self.assertIn("relationship", process["required_lanes"])
        self.assertIn("autobiographical_continuity", intact["causal_provenance"])
        self.assertIn("autobiographical_change_directive", intact["causal_provenance"])
        self.assertEqual(
            "autobiographical_continuity",
            intact["memory"]["retrieved"][0]["source"],
        )

    def test_change_lesion_preserves_event_history_but_removes_control(self):
        inputs = self.kernel_inputs()
        intact = eve_consciousness.build_conscious_state(**inputs)
        lesioned_inputs = copy.deepcopy(inputs)
        lesioned_inputs["lesions"] = ["autobiographical_change"]
        lesioned = eve_consciousness.build_conscious_state(**lesioned_inputs)

        self.assertEqual(
            intact["autobiography"]["event_count"],
            lesioned["autobiography"]["event_count"],
        )
        self.assertEqual(0, lesioned["autobiography"]["change_count"])
        self.assertEqual({}, lesioned["autobiography"]["selected_precedent"])
        self.assertFalse(
            any(
                item.get("source") == "autobiographical_continuity"
                for item in lesioned["memory"]["retrieved"]
                if isinstance(item, dict)
            )
        )
        intact_signature = eve_consciousness.causal_signature(intact)
        lesioned_signature = eve_consciousness.causal_signature(lesioned)
        self.assertGreater(
            intact_signature["autobiographical_change_control"],
            lesioned_signature["autobiographical_change_control"],
        )

    def test_full_lesion_removes_autobiographical_continuity_only(self):
        inputs = self.kernel_inputs()
        intact = eve_consciousness.build_conscious_state(**inputs)
        lesioned_inputs = copy.deepcopy(inputs)
        lesioned_inputs["lesions"] = ["autobiography"]
        lesioned = eve_consciousness.build_conscious_state(**lesioned_inputs)

        self.assertGreater(intact["autobiography"]["event_count"], 0)
        self.assertEqual(0, lesioned["autobiography"]["event_count"])
        self.assertTrue(lesioned["self_model"]["available"])
        self.assertGreater(
            eve_consciousness.causal_signature(intact)["autobiographical_continuity_coupling"],
            eve_consciousness.causal_signature(lesioned)["autobiographical_continuity_coupling"],
        )

    def test_runtime_builder_projects_canonical_episodes_without_new_store(self):
        with (
            mock.patch.object(eve, "read_relationship_episodes", return_value=[correction_episode()]),
            mock.patch.object(eve, "select_conscious_memory_items", return_value=[]),
            mock.patch.object(eve, "load_conscious_state", return_value=eve.default_conscious_state()),
            mock.patch.object(eve, "load_autonomy_agenda", return_value={}),
            mock.patch.object(eve, "load_human_context", return_value=eve.normalize_human_context({})),
            mock.patch.object(eve, "load_state", return_value={}),
        ):
            state = eve.build_recurrent_conscious_state(
                source="reply-autobiography-test",
                workspace={"salient_percepts": ["A completion claim needs review."]},
                self_model={"identity": "Eve", "current_state": "Reviewing evidence."},
                world_model={"environment_summary": "Conversation active."},
                relationship_model={"relationship_state": "A prior correction exists."},
                other_minds_model={},
                homeostasis={},
                plan_model={},
                inbound="Before claiming success, should current evidence be verified?",
                persist=False,
            )

        self.assertEqual(1, state["autobiography"]["change_count"])
        self.assertTrue(state["autobiography"]["selected_precedent"]["selected"])
        self.assertEqual(
            "autobiographical_continuity",
            state["memory"]["retrieved"][0]["source"],
        )
        self.assertFalse(state["autobiography"]["self_output_used_as_observation"])


if __name__ == "__main__":
    unittest.main()
