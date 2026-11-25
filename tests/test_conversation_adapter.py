"""Compatibility and actual deterministic guard tests; no model or live writes."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from copy import deepcopy
import unittest
from unittest.mock import patch

import eve
from eve_adapters.conversation import LegacyReplyBoundary
from eve_core.replies import ReplyScope


class ConversationAdapterTests(unittest.TestCase):
    def isolate_models(self, stack):
        stack.enter_context(patch.object(eve, "active_reply_repair_flags", return_value=set()))
        stack.enter_context(patch.object(eve, "resolve_reply_council_lane_model", return_value="fixture-deep"))
        stack.enter_context(patch.object(eve, "evaluate_reply_epistemic_grounding", return_value={"evaluated": True, "ok": True, "model": "fixture-critic", "unsupported_claims": []}))
        stack.enter_context(patch.object(eve, "ground_generated_action_claims", side_effect=lambda text, **kwargs: text))
        return stack.enter_context(patch.object(eve, "rewrite_reply_for_clarity", return_value=""))

    def test_public_entrypoint_preserves_original_signature_and_late_patch_seams(self):
        contract = {"reply_posture": "practical", "epistemic_boundary": True, "closed_world_evidence": True}
        with ExitStack() as stack:
            self.isolate_models(stack)
            stack.enter_context(patch.object(eve, "reply_quality_issues", return_value=[]))
            critic = stack.enter_context(patch.object(eve, "evaluate_reply_epistemic_grounding", return_value={"evaluated": True, "ok": True, "model": "patched-critic", "unsupported_claims": []}))
            result = eve.finalize_grounded_nonacting_reply({"deep_model": "fixture-deep"}, "Use only this record.", "The supplied record is inconclusive.", contract, max_tokens=190)
        self.assertEqual("The supplied record is inconclusive.", result["response"])
        self.assertEqual("patched-critic", result["epistemic_critic"]["model"])
        self.assertEqual(190, result["max_tokens"])
        self.assertEqual(set(), critic.call_args.kwargs["current_turn_actions"])

    def test_actual_guard_rejects_openclaw_status_for_an_existential_question(self):
        scope = ReplyScope("What is the purpose of life?", "relational", False, False, True, False)
        assessment = LegacyReplyBoundary(scope, {}).assess("I checked the OpenClaw sync. Gateway: reachable.")
        self.assertTrue(assessment.blocking)
        self.assertTrue(any("did not ask for" in issue for issue in assessment.issues))

    def test_actual_guard_rejects_multi_organ_telemetry_in_personal_conversation(self):
        scope = ReplyScope("What do you think would make Eve feel more human to talk to?", "relational", False, False, True, False)
        assessment = LegacyReplyBoundary(scope, {}).assess("OpenClaw status is healthy, Hermes status is clear, and the event ledger is current.")
        self.assertTrue(any("organ/runtime status" in issue for issue in assessment.issues))
        self.assertTrue(assessment.blocking)

    def test_telemetry_guard_fails_before_critic_when_rewrite_does_not_fix_it(self):
        contract = {"reply_posture": "relational", "epistemic_boundary": True}
        with ExitStack() as stack:
            self.isolate_models(stack)
            critic = stack.enter_context(patch.object(eve, "evaluate_reply_epistemic_grounding"))
            stack.enter_context(patch.object(eve, "build_epistemic_boundary_fallback_reply", return_value="A grounded answer to your question."))
            result = eve.finalize_grounded_nonacting_reply({}, "What is the purpose of life?", "I checked the OpenClaw sync. Gateway: reachable.", contract, max_tokens=220)
        critic.assert_not_called()
        self.assertTrue(result["fallback_applied"])
        self.assertNotIn("Gateway", result["response"])

    def test_record_finalization_loads_no_live_context_and_performs_no_actions(self):
        forbidden = ("load_human_context", "load_active_mind", "read_entries", "read_tensions", "read_proposals", "read_thread_summaries", "execute_supported_reply_commitment", "run_operational_action_tree", "read_messages")
        with ExitStack() as stack:
            self.isolate_models(stack)
            stack.enter_context(patch.object(eve, "reply_quality_issues", return_value=[]))
            mocks = [stack.enter_context(patch.object(eve, name, side_effect=AssertionError("unrelated context/action loaded: " + name))) for name in forbidden]
            grounded = stack.enter_context(patch.object(eve, "ground_generated_action_claims", side_effect=lambda text, **kwargs: text))
            result = eve.finalize_grounded_nonacting_reply({}, "Use only this record, not live state.", "The record does not establish a cause.", {"closed_world_evidence": True, "epistemic_boundary": True}, max_tokens=220)
        self.assertFalse(result["fallback_applied"])
        for mock in mocks:
            mock.assert_not_called()
        self.assertIs(False, grounded.call_args.kwargs["record"])
        self.assertEqual(set(), grounded.call_args.kwargs["completed_actions"])

    def test_record_quality_uses_no_runtime_policy_discovery(self):
        with ExitStack() as stack:
            self.isolate_models(stack)
            flags = stack.enter_context(patch.object(eve, "active_reply_repair_flags", side_effect=AssertionError("live policy read")))
            stores = stack.enter_context(patch.object(eve, "ensure_store", side_effect=AssertionError("store initialization")))
            result = eve.finalize_grounded_nonacting_reply({}, "Use only this record.", "The record does not establish a cause.", {"closed_world_evidence": True, "epistemic_boundary": True}, max_tokens=220)
        flags.assert_not_called()
        stores.assert_not_called()
        self.assertFalse(result["fallback_applied"])

    def test_ordinary_policy_is_snapshotted_once_not_read_for_each_assessment(self):
        with ExitStack() as stack:
            self.isolate_models(stack)
            flags = stack.enter_context(patch.object(eve, "active_reply_repair_flags", return_value={"fixture-flag"}))
            quality = stack.enter_context(patch.object(eve, "reply_quality_issues", return_value=[]))
            eve.finalize_grounded_nonacting_reply({}, "Give a grounded explanation.", "A grounded explanation.", {"epistemic_boundary": True}, max_tokens=220)
        self.assertEqual(1, flags.call_count)
        self.assertTrue(all(call.kwargs["repair_flags_override"] == frozenset({"fixture-flag"}) for call in quality.call_args_list))

    def test_real_guard_keeps_current_state_separate_from_unknown_subjective_experience(self):
        scope = ReplyScope("What is on your mind?", "relational", False, True, True, False)
        boundary = LegacyReplyBoundary(scope, {})
        self.assertTrue(boundary.assess("I am consciously feeling joy right now.").blocking)
        self.assertTrue(boundary.assess("I don't have subjective experience.").blocking)

    def test_snapshot_is_detached_even_if_an_adapter_mutates_its_copy(self):
        config = {"deep_model": "fixture", "nested": {"key": "original"}}
        contract = {"reply_posture": "practical", "epistemic_boundary": True, "closed_world_evidence": True, "record": {"id": "original"}}
        before_config, before_contract = deepcopy(config), deepcopy(contract)
        def review(cfg, body, draft, owned_contract, **kwargs):
            cfg["nested"]["key"] = "mutated"
            owned_contract["record"]["id"] = "mutated"
            return {"evaluated": True, "ok": True, "unsupported_claims": []}
        with ExitStack() as stack:
            self.isolate_models(stack)
            stack.enter_context(patch.object(eve, "reply_quality_issues", return_value=[]))
            stack.enter_context(patch.object(eve, "evaluate_reply_epistemic_grounding", side_effect=review))
            eve.finalize_grounded_nonacting_reply(config, "Use only this record.", "A grounded supplied record.", contract, max_tokens=180)
        self.assertEqual(before_config, config)
        self.assertEqual(before_contract, contract)

    def test_concurrent_requests_keep_body_record_and_correction_distinct(self):
        def review(cfg, body, draft, contract, **kwargs):
            self.assertEqual(body, contract["record_id"])
            self.assertEqual(body, draft)
            return {"evaluated": True, "ok": True, "model": body, "unsupported_claims": []}
        def finalize(body):
            return eve.finalize_grounded_nonacting_reply({}, body, body, {"reply_posture": "practical", "epistemic_boundary": True, "closed_world_evidence": True, "record_id": body}, max_tokens=200)
        with ExitStack() as stack:
            self.isolate_models(stack)
            stack.enter_context(patch.object(eve, "reply_quality_issues", return_value=[]))
            stack.enter_context(patch.object(eve, "evaluate_reply_epistemic_grounding", side_effect=review))
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(finalize, ["first", "second"]))
        self.assertEqual(["first", "second"], [item["response"] for item in results])
        self.assertEqual(["first", "second"], [item["epistemic_critic"]["model"] for item in results])

    def test_current_state_fallback_receives_the_bound_target_not_a_new_live_selection(self):
        target = {"selected_goal": "bound target"}
        contract = {"route_contract_kind": "current_inner_state", "current_self_report_target": target}
        with ExitStack() as stack:
            self.isolate_models(stack)
            stack.enter_context(patch.object(eve, "reply_erases_persistent_functional_inner_state", return_value=True))
            fallback = stack.enter_context(patch.object(eve, "build_current_inner_state_fallback_reply", return_value="Bound fallback."))
            eve.finalize_grounded_nonacting_reply({}, "What is on your mind?", "I have nothing inside.", contract, max_tokens=200)
        self.assertEqual(target, fallback.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
