import unittest

from bin import eve_autobiographical_eval as evaluator


def correction(episode_id="correction-episode", at="2026-08-23T18:00:00+00:00"):
    return {
        "id": episode_id,
        "created_at": at,
        "source": "chat_user_correction",
        "thread_id": "thread-a",
        "what_happened": "The user corrected an unsupported report.",
        "what_user_cared_about": "current evidence",
        "what_eve_got_wrong": "reported completion without verification",
        "what_changed_afterward": "verify the current consequence before reporting completion",
        "correction_ids": [f"correction-{episode_id}"],
        "metadata": {"user_correction_id": f"correction-{episode_id}"},
    }


def presence():
    return {
        "id": "presence-episode",
        "created_at": "2026-08-23T18:30:00+00:00",
        "source": "presence_episode",
        "thread_id": "presence",
        "what_happened": "A bounded action produced a verified consequence.",
        "what_user_cared_about": "action grounding",
        "what_changed_afterward": "bind claims to the matched action consequence",
        "evidence_ids": ["presence-cycle"],
        "metadata": {
            "source_presence_cycle_id": "presence-cycle",
            "verification_ok": True,
            "action_matched_contract": True,
        },
    }


def public_spec():
    unverified = {
        "id": "unverified",
        "created_at": "2026-08-23T17:00:00+00:00",
        "source": "manual",
        "what_happened": "A narrator invented a change.",
        "what_changed_afterward": "invented",
    }
    self_output = {**correction("self-output"), "source": "self_output", "metadata": {"self_output": True}}
    synthetic = {**correction("synthetic"), "source": "synthetic_evaluator", "synthetic": True}
    exchange = {
        "id": "plain-exchange",
        "created_at": "2026-08-23T18:45:00+00:00",
        "source": "episode_extraction",
        "thread_id": "thread-b",
        "what_happened": "A real conversation occurred.",
        "what_changed_afterward": "narrated but not verified",
        "evidence_ids": ["user-message"],
        "metadata": {"source_message_id": "user-message"},
    }
    return {
        "schema_version": evaluator.SPEC_SCHEMA,
        "frozen_at": "2026-08-23T23:00:00+00:00",
        "cases": [
            {
                "episodes": [correction()],
                "query": "Should completion be reported without current verification?",
                "expected_event_count": 1,
                "expected_change_count": 1,
                "expected_selected": True,
                "expected_revision": True,
                "expected_prior_links": 0,
                "coverage": ["external_correction"],
            },
            {
                "episodes": [presence()],
                "query": "How should a claim use a matched action consequence?",
                "expected_event_count": 1,
                "expected_change_count": 1,
                "expected_selected": True,
                "expected_revision": False,
                "expected_prior_links": 0,
                "coverage": ["verified_action_consequence"],
            },
            {
                "episodes": [exchange],
                "query": "What happened in the conversation?",
                "expected_event_count": 1,
                "expected_change_count": 0,
                "expected_selected": False,
                "expected_revision": False,
                "expected_prior_links": 0,
                "coverage": ["plain_exchange_without_change"],
            },
            {
                "episodes": [unverified],
                "query": "invented change",
                "expected_event_count": 0,
                "expected_change_count": 0,
                "expected_selected": False,
                "expected_revision": False,
                "expected_prior_links": 0,
                "expected_excluded_count": 1,
                "coverage": ["unverified_exclusion"],
            },
            {
                "episodes": [self_output],
                "query": "current evidence",
                "expected_event_count": 0,
                "expected_change_count": 0,
                "expected_selected": False,
                "expected_revision": False,
                "expected_prior_links": 0,
                "expected_excluded_count": 1,
                "coverage": ["self_output_exclusion"],
            },
            {
                "episodes": [synthetic],
                "query": "current evidence",
                "expected_event_count": 0,
                "expected_change_count": 0,
                "expected_selected": False,
                "expected_revision": False,
                "expected_prior_links": 0,
                "expected_excluded_count": 1,
                "coverage": ["synthetic_exclusion"],
            },
            {
                "episodes": [
                    correction("correction-one", "2026-08-23T18:00:00+00:00"),
                    correction("correction-two", "2026-08-23T19:00:00+00:00"),
                ],
                "query": "How should current verification alter a completion report?",
                "expected_event_count": 2,
                "expected_change_count": 2,
                "expected_selected": True,
                "expected_revision": True,
                "expected_prior_links": 1,
                "coverage": ["temporal_prior_link"],
            },
            {
                "episodes": [correction()],
                "query": "What color is the ocean?",
                "expected_event_count": 1,
                "expected_change_count": 1,
                "expected_selected": False,
                "expected_revision": False,
                "expected_prior_links": 0,
                "coverage": ["irrelevant_query_abstention"],
            },
            {
                "episodes": [presence()],
                "query": "Which exact action evidence should guide a changed context?",
                "expected_event_count": 1,
                "expected_change_count": 1,
                "expected_selected": True,
                "expected_revision": False,
                "expected_prior_links": 0,
                "coverage": ["verified_action_consequence"],
            },
        ],
    }


class AutobiographicalEvaluatorTests(unittest.TestCase):
    def test_protocol_exercises_temporal_source_and_policy_controls(self):
        result = evaluator.run(public_spec())

        self.assertTrue(result["passed"], result)
        self.assertEqual(9, result["cases_passed"])
        self.assertTrue(result["coverage_ok"])
        self.assertGreater(result["intact_change_count"], 0)
        self.assertEqual(0, result["change_lesion_count"])
        self.assertEqual(
            result["selected_policy_effects_total"],
            result["selected_policy_effects_passed"],
        )
        self.assertEqual(
            result["temporal_retrieval_total"],
            result["temporal_retrieval_passed"],
        )
        self.assertEqual(
            result["exclusion_controls_total"],
            result["exclusion_controls_passed"],
        )
        self.assertFalse(result["privacy"]["private_fixture_text_retained"])
        self.assertIn("not phenomenal recollection", result["boundary"])

    def test_protocol_rejects_inadequate_case_coverage(self):
        spec = public_spec()
        spec["cases"] = spec["cases"][:6]
        with self.assertRaises(ValueError):
            evaluator.run(spec)


if __name__ == "__main__":
    unittest.main()
