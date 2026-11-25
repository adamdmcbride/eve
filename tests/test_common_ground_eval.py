import unittest

from bin import eve_common_ground_eval as evaluator


def private_spec():
    return {
        "schema_version": evaluator.SPEC_SCHEMA,
        "frozen_at": "2026-08-23T23:30:00+00:00",
        "cases": [
            {
                "id": "explicit-acceptance",
                "turns": [
                    {
                        "inbound": "Did the fresh check pass?",
                        "reply": "The fresh check passed.",
                        "observed_class": "acceptance",
                    }
                ],
                "expected_statuses": ["explicitly_shared"],
                "expected_history_states": [["eve_position_expressed", "explicitly_shared"]],
                "expected_active_repair": False,
                "expected_shared_count": 1,
            },
            {
                "id": "visible-correction",
                "turns": [
                    {
                        "inbound": "Did the fresh check pass?",
                        "reply": "The fresh check passed.",
                        "observed_class": "correction",
                    }
                ],
                "expected_statuses": ["challenged"],
                "expected_history_states": [["eve_position_expressed", "challenged"]],
                "expected_active_repair": True,
                "expected_shared_count": 0,
            },
            {
                "id": "repair-confirmed",
                "turns": [
                    {
                        "inbound": "Did the fresh check pass?",
                        "reply": "The fresh check passed.",
                        "observed_class": "correction",
                    },
                    {
                        "inbound": "No, it failed.",
                        "reply": "You're right; the fresh check failed.",
                        "observed_class": "acceptance",
                    },
                ],
                "expected_statuses": ["repair_confirmed", "explicitly_shared"],
                "expected_history_states": [
                    ["challenged", "repair_attempted", "repair_confirmed"],
                    ["eve_position_expressed", "explicitly_shared"],
                ],
                "expected_active_repair": False,
                "expected_shared_count": 1,
            },
            {
                "id": "follow-up-not-agreement",
                "turns": [
                    {
                        "inbound": "Did the fresh check pass?",
                        "reply": "The fresh check passed.",
                        "observed_class": "follow_up_question",
                    }
                ],
                "expected_statuses": ["follow_up_open"],
                "expected_history_states": [["follow_up_open"]],
                "expected_active_repair": False,
                "expected_shared_count": 0,
            },
            {
                "id": "topic-shift-not-agreement",
                "turns": [
                    {
                        "inbound": "Did the fresh check pass?",
                        "reply": "The fresh check passed.",
                        "observed_class": "topic_shift",
                    }
                ],
                "expected_statuses": ["superseded_topic_shift"],
                "expected_history_states": [["superseded_topic_shift"]],
                "expected_active_repair": False,
                "expected_shared_count": 0,
            },
            {
                "id": "answer-not-agreement",
                "turns": [
                    {
                        "inbound": "Which check should I run?",
                        "reply": "Run the bounded health check. Did it pass?",
                        "observed_class": "answer",
                    }
                ],
                "expected_statuses": ["counterpart_answered"],
                "expected_history_states": [["counterpart_answered"]],
                "expected_active_repair": False,
                "expected_shared_count": 0,
            },
        ],
    }


class CommonGroundEvaluatorTests(unittest.TestCase):
    def test_private_matched_protocol_exercises_trajectory_retrieval_and_feedback_lesion(self):
        result = evaluator.run(private_spec())

        self.assertTrue(result["passed"], result)
        self.assertEqual(6, result["cases_passed"])
        self.assertEqual(6, result["cases_total"])
        self.assertTrue(result["coverage_ok"])
        self.assertGreater(result["intact_feedback_evidence_count"], 0)
        self.assertEqual(0, result["feedback_lesion_evidence_count"])
        self.assertEqual(
            result["temporal_retrieval_total"],
            result["temporal_retrieval_passed"],
        )
        self.assertFalse(result["privacy"]["private_fixture_text_retained"])
        self.assertIn("not access to private beliefs", result["boundary"])

    def test_protocol_rejects_inadequate_case_coverage(self):
        spec = private_spec()
        spec["cases"] = spec["cases"][:5]

        with self.assertRaises(ValueError):
            evaluator.run(spec)


if __name__ == "__main__":
    unittest.main()
