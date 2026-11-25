import unittest

import eve_social_prediction as social


class ObservableSocialPredictionTests(unittest.TestCase):
    def prediction(self, reply_text="Here is the answer.", inbound_text="What happened?"):
        return social.build_prediction(
            reply_text=reply_text,
            inbound_text=inbound_text,
            thread_id="thread-1",
            source_message_id="user-1",
            reply_message_id="reply-1",
            made_at="2026-08-23T20:00:00+00:00",
        )

    def test_prediction_is_probability_distribution_with_explicit_boundary(self):
        prediction = self.prediction()

        self.assertEqual(social.SCHEMA_VERSION, prediction["schema_version"])
        self.assertAlmostEqual(1.0, sum(prediction["distribution"].values()), places=6)
        self.assertEqual(set(social.RESPONSE_CLASSES), set(prediction["distribution"]))
        self.assertEqual("observation_and_calibration_only", prediction["authority"])
        self.assertNotIn("emotion", prediction)
        self.assertNotIn("belief", prediction)
        self.assertFalse(prediction["lesioned"])

    def test_reply_question_predicts_observable_answer(self):
        prediction = self.prediction("What concrete outcome did you observe?")

        self.assertEqual("answer", prediction["predicted_class"])
        self.assertTrue(prediction["features"]["reply_asked_question"])

    def test_sparse_history_cannot_overwrite_current_reply_evidence(self):
        history = {
            "evidence_count": 200,
            "scored_count": 200,
            "response_prior": {"topic_shift": 1.0},
        }
        prediction = social.build_prediction(
            reply_text="What did you see?",
            inbound_text="Help me diagnose this.",
            thread_id="t",
            source_message_id="u",
            reply_message_id="r",
            made_at="2026-08-23T20:00:00+00:00",
            history=history,
        )

        self.assertLessEqual(prediction["history_weight"], 0.35)
        self.assertEqual("answer", prediction["predicted_class"])

    def test_classification_uses_visible_form_not_private_state(self):
        prediction = self.prediction("What changed?")

        self.assertEqual(
            "correction",
            social.classify_observed_response(
                "No, that is not what I asked.", prediction=prediction, correction=True
            ),
        )
        self.assertEqual(
            "acceptance",
            social.classify_observed_response(
                "Great, thanks.", prediction=prediction, explicit_acceptance=True
            ),
        )
        self.assertEqual(
            "answer",
            social.classify_observed_response("The service restarted.", prediction=prediction),
        )
        self.assertEqual(
            "topic_shift",
            social.classify_observed_response(
                "New question: what model is live?", prediction=prediction
            ),
        )

    def test_incidental_wrong_word_is_not_a_reply_correction(self):
        self.assertFalse(social.explicitly_corrects_prior_reply("What is wrong with the server?"))
        self.assertTrue(social.explicitly_corrects_prior_reply("No, your answer is wrong."))

    def test_no_to_a_question_is_an_answer_not_automatic_correction(self):
        prediction = self.prediction("Did the service recover?")

        self.assertFalse(
            social.explicitly_corrects_prior_reply("No, it stayed down.", prediction=prediction)
        )
        self.assertEqual(
            "answer",
            social.classify_observed_response("No, it stayed down.", prediction=prediction),
        )

    def test_yes_to_a_question_is_not_automatic_positive_reward(self):
        prediction = self.prediction("Should I run the bounded canary?")

        self.assertFalse(
            social.explicitly_accepts_prior_reply(
                "Yes, do it.", coarse_acceptance=True, prediction=prediction
            )
        )
        self.assertTrue(
            social.explicitly_accepts_prior_reply(
                "Yes, that's correct. Thanks.",
                coarse_acceptance=True,
                prediction=prediction,
            )
        )
        self.assertFalse(
            social.explicitly_accepts_prior_reply(
                "Great, but that still needs work.",
                coarse_acceptance=True,
                prediction=prediction,
            )
        )

    def test_proper_score_rewards_probability_on_observed_class(self):
        good = self.prediction("What changed?")
        bad = dict(good)
        bad["distribution"] = {
            "acceptance": 0.02,
            "correction": 0.02,
            "answer": 0.02,
            "follow_up_question": 0.02,
            "continuation": 0.02,
            "topic_shift": 0.90,
        }

        good_score = social.score_prediction(good, "answer", observed_message_id="u2")
        bad_score = social.score_prediction(bad, "answer", observed_message_id="u2")

        self.assertTrue(good_score["scored"])
        self.assertLess(good_score["normalized_brier"], bad_score["normalized_brier"])
        self.assertTrue(good_score["top1_correct"])
        self.assertFalse(bad_score["top1_correct"])

    def test_lineage_rejects_wrong_thread_reply_source_or_time(self):
        prediction = self.prediction()

        self.assertTrue(
            social.observation_matches_prediction(
                prediction,
                thread_id="thread-1",
                reply_message_id="reply-1",
                observed_message_id="user-2",
                observed_at="2026-08-23T20:00:01+00:00",
            )
        )
        self.assertFalse(
            social.observation_matches_prediction(
                prediction,
                thread_id="thread-2",
                reply_message_id="reply-1",
                observed_message_id="user-2",
            )
        )
        self.assertFalse(
            social.observation_matches_prediction(
                prediction,
                thread_id="thread-1",
                reply_message_id="reply-1",
                observed_message_id="user-1",
            )
        )
        self.assertFalse(
            social.observation_matches_prediction(
                prediction,
                thread_id="thread-1",
                reply_message_id="reply-1",
                observed_message_id="user-2",
                observed_at="2026-08-23T19:59:59+00:00",
            )
        )

    def test_summary_tracks_dynamic_observations_without_text(self):
        records = []
        for index, label in enumerate(
            ["continuation"] * 8 + ["follow_up_question"] * 8
        ):
            prediction = social.build_prediction(
                reply_text="Here is one bounded result.",
                thread_id="t",
                source_message_id=f"u{index}",
                reply_message_id=f"r{index}",
                made_at=f"2026-08-23T20:{index:02d}:00+00:00",
            )
            outcome = social.score_prediction(
                prediction, label, observed_message_id=f"u{index + 1}"
            )
            records.append(
                {
                    "kind": "conversational",
                    "evidence_id": f"e{index}",
                    "observed_text": "private user words",
                    "social_outcome": outcome,
                }
            )

        summary = social.summarize_records(records)

        self.assertEqual(16, summary["scored_count"])
        self.assertIsNotNone(summary["distribution_shift"])
        self.assertGreater(summary["distribution_shift"], 0.0)
        self.assertFalse(summary["contains_user_text"])
        self.assertFalse(summary["contains_private_mental_state"])
        self.assertNotIn("private user words", str(summary))

    def test_feedback_lesion_preserves_schema_but_removes_learning(self):
        prediction = self.prediction()
        outcome = social.score_prediction(prediction, "continuation", observed_message_id="u2")
        record = {
            "kind": "conversational",
            "evidence_id": "e1",
            "social_outcome": outcome,
        }

        intact = social.summarize_records([record])
        lesioned = social.summarize_records([record], feedback_lesioned=True)

        self.assertEqual(1, intact["scored_count"])
        self.assertEqual(0, lesioned["scored_count"])
        self.assertTrue(lesioned["feedback_lesioned"])

    def test_ledger_sanitizer_hashes_instead_of_persisting_user_text(self):
        sanitized = social.sanitize_ledger_record(
            {"kind": "conversational", "observed_text": "counterpart private message"}
        )

        self.assertNotIn("observed_text", sanitized)
        self.assertEqual(64, len(sanitized["observed_text_sha256"]))
        self.assertFalse(sanitized["contains_user_text"])


if __name__ == "__main__":
    unittest.main()
