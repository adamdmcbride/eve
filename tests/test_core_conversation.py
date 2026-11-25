"""Model/store-free acceptance tests for request-scoped reply finalization."""
from dataclasses import replace
import unittest

from eve_core.conversation import NonactingReplyFinalizer
from eve_core.replies import ReplyAssessment, ReplyScope, critic_receipt


class FakeBoundary:
    def __init__(self):
        self.assessments = {}
        self.groundings = []
        self.fallbacks = 0

    def trim(self, text):
        return text.removesuffix(" Shall we continue?")

    def prepare(self, text):
        return self.trim(text)

    def assess(self, text):
        return self.assessments.get(text, ReplyAssessment((), ()))

    def ground(self, text, source):
        self.groundings.append((text, source))
        return text

    def fallback(self):
        self.fallbacks += 1
        return "grounded fallback"


class FakeAuthor:
    model = "explicit-author"

    def __init__(self):
        self.drafts = []
        self.calls = []
        self.error = None

    def rewrite(self, text, issues):
        self.calls.append((text, issues))
        if self.error:
            raise self.error
        return self.drafts.pop(0) if self.drafts else ""


class FakeCritic:
    def __init__(self):
        self.verdicts = []
        self.corrections = []
        self.calls = []
        self.correction_calls = []
        self.error = None
        self.correction_error = None

    def review(self, text):
        self.calls.append(text)
        if self.error:
            raise self.error
        return self.verdicts.pop(0) if self.verdicts else {"evaluated": True, "ok": True, "model": "explicit-critic"}

    def correct(self, text, verdict, max_tokens):
        self.correction_calls.append((text, verdict, max_tokens))
        if self.correction_error:
            raise self.correction_error
        return self.corrections.pop(0) if self.corrections else {"attempted": True, "response": ""}


def rejection():
    return {"evaluated": True, "ok": False, "unsupported_claims": ["causal mismatch"], "model": "explicit-critic"}


class CoreConversationTests(unittest.TestCase):
    def setUp(self):
        self.boundary, self.author, self.critic = FakeBoundary(), FakeAuthor(), FakeCritic()
        self.scope = ReplyScope("Use this record only.", "practical", True, False, True, False)
        self.service = NonactingReplyFinalizer(self.boundary, self.author, self.critic)

    def finalize(self, draft="record answer", **scope_changes):
        return self.service.finalize(replace(self.scope, **scope_changes), draft, max_tokens=220)

    def block(self, text, *issues):
        self.boundary.assessments[text] = ReplyAssessment(tuple(issues), tuple(issues))

    def test_grounded_primary_is_preserved_without_rewrite(self):
        result = self.finalize()
        self.assertEqual("record answer", result["response"])
        self.assertEqual([], self.author.calls)
        self.assertEqual(["record answer"], self.critic.calls)
        self.assertFalse(result["fallback_applied"])

    def test_inactive_boundary_skips_critic(self):
        result = self.finalize(epistemic_boundary=False)
        self.assertEqual("epistemic_boundary_inactive", result["epistemic_critic"]["skipped_reason"])
        self.assertEqual([], self.critic.calls)

    def test_defined_taxonomy_is_not_reinterpreted_by_provenance_critic(self):
        result = self.finalize(taxonomy_classification=True)
        self.assertEqual("defined_taxonomy_classification", result["epistemic_critic"]["skipped_reason"])
        self.assertEqual([], self.critic.calls)

    def test_closed_record_style_does_not_regenerate_answer(self):
        self.boundary.assessments["record answer"] = ReplyAssessment(("long style",), ())
        self.assertEqual(0, self.finalize()["rewrite_attempts"])
        self.assertEqual([], self.author.calls)

    def test_trailing_invitation_is_removed_before_critic(self):
        self.finalize("record answer Shall we continue?")
        self.assertEqual(["record answer"], self.critic.calls)

    def test_hard_guard_can_be_repaired_before_critic(self):
        self.block("bad", "wrong source")
        self.author.drafts = ["record answer"]
        result = self.finalize("bad")
        self.assertEqual("record answer", result["response"])
        self.assertEqual(1, result["rewrite_attempts"])
        self.assertEqual("explicit-author", result["rewrite_model"])

    def test_worse_rewrite_is_not_accepted(self):
        self.block("bad", "wrong source")
        self.block("worse", "wrong source", "wrong authorization")
        self.author.drafts = ["worse"]
        result = self.finalize("bad")
        self.assertEqual("bad", result["precritic_response"])
        self.assertEqual("grounded fallback", result["response"])
        self.assertEqual([], self.critic.calls)

    def test_equal_blockers_with_fewer_soft_issues_is_an_improvement(self):
        self.boundary.assessments["bad"] = ReplyAssessment(("source", "style"), ("source",))
        self.block("less bad", "source")
        self.author.drafts = ["less bad", "record answer"]
        self.assertEqual("record answer", self.finalize("bad")["response"])

    def test_rewrite_limit_is_two(self):
        self.block("three", "a", "b", "c")
        self.block("two", "a", "b")
        self.block("one", "a")
        self.author.drafts = ["two", "one", "record answer"]
        result = self.finalize("three")
        self.assertEqual(2, result["rewrite_attempts"])
        self.assertTrue(result["fallback_applied"])
        self.assertEqual(["record answer"], self.author.drafts)

    def test_rewrite_exception_is_unavailable_not_a_process_exit(self):
        for error in (OSError("transport"), SystemExit("timeout")):
            with self.subTest(error=type(error).__name__):
                self.setUp()
                self.block("bad", "source")
                self.author.error = error
                result = self.finalize("bad")
                self.assertTrue(result["fallback_applied"])
                self.assertTrue(result["finalization_errors"])

    def test_nonstring_rewrite_is_not_a_draft(self):
        self.block("bad", "source")
        self.author.drafts = [{"response": "record answer"}]
        self.assertTrue(self.finalize("bad")["fallback_applied"])

    def test_critic_transport_outage_retains_grounded_record(self):
        self.critic.verdicts = [{"evaluated": True, "ok": False, "error": "transport failure"}]
        result = self.finalize()
        self.assertEqual("record answer", result["response"])
        self.assertTrue(result["critic_unavailable_retained"])
        self.assertFalse(result["fallback_applied"])

    def test_raised_critic_outage_does_not_erase_primary(self):
        for error in (OSError("transport"), RuntimeError("decode"), SystemExit("timeout")):
            with self.subTest(error=type(error).__name__):
                self.setUp()
                self.critic.error = error
                result = self.finalize()
                self.assertEqual("record answer", result["response"])
                self.assertTrue(result["critic_unavailable_retained"])
                self.assertFalse(result["fallback_applied"])

    def test_malformed_critic_is_unavailable_not_semantic_failure(self):
        for verdict in (None, [], "bad", {}, {"evaluated": "true", "ok": True}, {"evaluated": True, "ok": "false"}, {"evaluated": True, "ok": True, "unsupported_claims": "bad"}, {"evaluated": True, "ok": True, "error": []}):
            with self.subTest(verdict=verdict):
                self.setUp()
                self.critic.verdicts = [verdict]
                result = self.finalize()
                self.assertTrue(result["critic_unavailable_retained"])
                self.assertEqual([], self.critic.correction_calls)

    def test_real_critic_rejection_gets_a_bounded_correction(self):
        self.critic.verdicts = [rejection()]
        self.critic.corrections = [{"attempted": True, "response": "corrected record"}]
        result = self.finalize()
        self.assertEqual("corrected record", result["response"])
        self.assertTrue(result["epistemic_revision"]["accepted"])
        self.assertEqual(220, self.critic.correction_calls[0][2])

    def test_second_correction_can_reconcile_critic_disagreement(self):
        self.critic.verdicts = [rejection(), rejection()]
        self.critic.corrections = [{"response": "wrong correction"}, {"response": "reconciled correction"}]
        result = self.finalize()
        self.assertEqual("reconciled correction", result["response"])
        self.assertEqual(2, result["epistemic_revision"]["attempt_count"])
        self.assertEqual("wrong correction", self.critic.correction_calls[1][0])

    def test_corrections_stop_after_two_rejections(self):
        self.critic.verdicts = [rejection(), rejection(), rejection()]
        self.critic.corrections = [{"response": "first"}, {"response": "second"}, {"response": "third"}]
        result = self.finalize()
        self.assertTrue(result["fallback_applied"])
        self.assertEqual(2, len(self.critic.correction_calls))
        self.assertEqual([{"response": "third"}], self.critic.corrections)

    def test_confirmation_outage_retains_safe_correction(self):
        self.critic.verdicts = [rejection(), {"evaluated": True, "ok": False, "error": "unavailable"}]
        self.critic.corrections = [{"response": "corrected record"}]
        result = self.finalize()
        self.assertEqual("corrected record", result["response"])
        self.assertTrue(result["epistemic_revision"]["accepted_with_critic_unavailable"])
        self.assertTrue(result["critic_unavailable_retained"])
        self.assertTrue(result["epistemic_revision"]["attempts"][-1]["accepted"])

    def test_blocked_correction_never_reaches_confirmation_critic(self):
        self.critic.verdicts = [rejection()]
        self.critic.corrections = [{"response": "wrong source"}]
        self.block("wrong source", "invented current telemetry")
        result = self.finalize()
        self.assertTrue(result["fallback_applied"])
        self.assertEqual(["record answer"], self.critic.calls)

    def test_model_cannot_claim_that_an_unverified_correction_was_accepted(self):
        self.critic.verdicts = [rejection()]
        self.critic.corrections = [{"response": "wrong source", "accepted": True, "accepted_with_critic_unavailable": True}]
        self.block("wrong source", "wrong source")
        result = self.finalize()
        self.assertTrue(result["fallback_applied"])
        self.assertFalse(result["epistemic_revision"]["accepted"])
        self.assertNotIn("accepted_with_critic_unavailable", result["epistemic_revision"])

    def test_malformed_correction_is_not_stringified_into_an_answer(self):
        for correction in (None, [], {"response": {"text": "answer"}}, {"response": 42}):
            with self.subTest(correction=correction):
                self.setUp()
                self.critic.verdicts = [rejection()]
                self.critic.corrections = [correction]
                result = self.finalize()
                self.assertTrue(result["fallback_applied"])
                self.assertIn("invalid correction", result["epistemic_revision"]["error"])

    def test_correction_exception_cannot_exit_finalizer(self):
        self.critic.verdicts = [rejection()]
        self.critic.correction_error = SystemExit("timeout")
        result = self.finalize()
        self.assertTrue(result["fallback_applied"])
        self.assertIn("correction unavailable", result["epistemic_revision"]["error"])

    def test_ordinary_nonrecord_rejection_does_not_run_record_correction(self):
        self.critic.verdicts = [rejection()]
        result = self.finalize(closed_world=False)
        self.assertTrue(result["fallback_applied"])
        self.assertEqual([], self.critic.correction_calls)

    def test_current_state_requires_critic_grounding(self):
        result = self.finalize(current_inner_state=True, closed_world=False)
        self.assertTrue(result["current_inner_state_primary_grounded"])
        self.assertEqual([], self.boundary.groundings)

    def test_current_state_outage_cannot_be_claimed_as_grounded(self):
        self.critic.error = OSError("transport")
        result = self.finalize(current_inner_state=True, closed_world=False)
        self.assertTrue(result["current_inner_state_fallback_applied"])
        self.assertFalse(result["current_inner_state_primary_grounded"])
        self.assertFalse(result["critic_unavailable_retained"])

    def test_current_state_hard_guard_inhibits_before_critic(self):
        self.block("unsupported subjective claim", "subjective experience unknown")
        result = self.finalize("unsupported subjective claim", current_inner_state=True, closed_world=False)
        self.assertTrue(result["current_inner_state_fallback_applied"])
        self.assertEqual("current_inner_state_fallback", result["epistemic_critic"]["skipped_reason"])
        self.assertEqual([], self.critic.calls)

    def test_rewritten_current_state_is_not_credited_to_primary(self):
        self.block("bad", "source")
        self.author.drafts = ["grounded current state"]
        result = self.finalize("bad", current_inner_state=True, closed_world=False)
        self.assertFalse(result["current_inner_state_primary_grounded"])
        self.assertTrue(result["current_inner_state_model_path_grounded"])

    def test_no_shared_critic_receipt_mutation(self):
        verdict = rejection()
        correction = {"response": "corrected record"}
        self.critic.verdicts = [verdict]
        self.critic.corrections = [correction]
        self.finalize()
        self.assertNotIn("attempt_index", correction)
        self.assertEqual(["causal mismatch"], verdict["unsupported_claims"])

    def test_multiple_requests_do_not_share_revisions_or_result_buffers(self):
        first = self.finalize()
        first["epistemic_revision"]["accepted"] = True
        first["finalization_errors"].append("caller mutation")
        second = self.finalize("second record answer")
        self.assertFalse(second["epistemic_revision"]["accepted"])
        self.assertEqual([], second["finalization_errors"])

    def test_guarded_telemetry_cannot_displace_the_requested_record(self):
        self.block("gateway healthy", "unrequested organ status")
        self.author.drafts = ["record answer"]
        result = self.finalize("gateway healthy")
        self.assertEqual("record answer", result["response"])
        self.assertEqual(["record answer"], self.critic.calls)

    def test_receipt_validation_preserves_explicit_skipped_evidence(self):
        result = critic_receipt({"evaluated": False, "ok": True, "skipped_reason": "not applicable"})
        self.assertFalse(result["evaluated"])
        self.assertEqual("not applicable", result["skipped_reason"])


if __name__ == "__main__":
    unittest.main()
