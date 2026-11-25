"""Compatibility wiring and request detachment with explicit fake effects."""
from contextlib import ExitStack
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

import eve
from eve_adapters.preflight import prepare_chat_preflight, prepare_reply_preflight


class PreflightAdapterTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.message = {"id": "current", "thread_id": "thread", "body": "question", "sender": "user"}
        self.operator = self.mock("resolve_external_operator_result_context", None)
        self.observe = self.mock("observe_inbound_reply_consequence", {"scored_reply_id": "exact", "consequence_observed": True})
        self.social = self.mock("build_reply_other_minds_preflight_state", {"lineage": "exact"})
        self.reference = self.mock("epistemic_reference_resolution_request", False)
        self.thread = self.mock("read_messages", [{"id": "prior"}])
        self.frame = self.mock("build_epistemic_perception_frame", {"signals": []})
        self.cycle = self.mock("build_recurrent_conscious_state", {"cycle_id": "cycle"})
        self.correction = self.mock("record_user_correction", {"id": "correction"})
        self.journal = self.mock("append_entry", None)

    def mock(self, name, result):
        return self.stack.enter_context(patch.object(eve, name, return_value=result))

    def prepare(self, **message_changes):
        return prepare_reply_preflight({}, {**self.message, **message_changes}, "question", thread_limit=8)

    def test_legacy_mailbox_arguments_and_lineage_are_preserved(self):
        self.prepare()
        self.operator.assert_called_once_with(self.message, prefer_runtime=True)
        self.observe.assert_called_once_with(self.message)
        self.assertEqual("exact", self.correction.call_args.kwargs["target_message_id"])
        self.assertTrue(self.correction.call_args.kwargs["metadata"]["prior_reply_consequence_observed"])
        kwargs = self.cycle.call_args.kwargs
        self.assertEqual("reply_preflight", kwargs["source"])
        self.assertTrue(kwargs["persist"])
        self.assertEqual(self.social.return_value, kwargs["other_minds_model"])
        self.assertEqual(self.frame.return_value, kwargs["epistemic_frame_override"])

    def test_synthetic_metadata_suppresses_feedback_correction_and_cycle_writes(self):
        self.prepare(metadata={"synthetic": True, "conversation_class": "synthetic_eval"})
        self.observe.assert_not_called()
        self.social.assert_not_called()
        self.correction.assert_not_called()
        self.journal.assert_not_called()
        self.assertFalse(self.frame.call_args.kwargs["allow_semantic"])
        self.assertFalse(self.cycle.call_args.kwargs["persist"])

    def test_operator_metadata_not_report_words_owns_feedback(self):
        self.operator.return_value = {"operator": "codex"}
        self.prepare(sender="codex", body="user health routing failure")
        self.observe.assert_not_called()
        self.correction.assert_not_called()
        self.assertFalse(self.frame.call_args.kwargs["allow_semantic"])

    def test_reference_receipt_is_bound_to_current_message_and_thread_limit(self):
        self.reference.return_value = True
        self.prepare()
        self.thread.assert_called_once_with(thread_id="thread", limit=8)
        self.assertEqual("current", self.frame.call_args.kwargs["current_message_id"])
        self.assertEqual(self.thread.return_value, self.frame.call_args.kwargs["thread_messages"])

    def test_cli_preserves_private_and_lesion_arguments(self):
        prepare_chat_preflight({}, "question", session_id="session", private_audit=True, lesion=True, lesion_event=True)
        self.operator.assert_not_called()
        self.observe.assert_not_called()
        kwargs = self.frame.call_args.kwargs
        self.assertTrue(kwargs["lesion"])
        self.assertTrue(kwargs["lesion_event"])
        self.assertTrue(kwargs["allow_candidate_event"])
        self.assertEqual([], kwargs["thread_messages"])
        self.assertFalse(self.cycle.call_args.kwargs["learned_epistemic_enabled"])
        self.assertFalse(self.cycle.call_args.kwargs["persist"])

    def test_cli_perception_failure_retains_lesioned_sparse_frame(self):
        self.frame.side_effect = SystemExit("offline")
        result = prepare_chat_preflight({}, "question", session_id="session", private_audit=True, lesion=True)
        self.assertEqual(eve.eve_epistemic.lesioned_frame(), result.epistemic_frame)
        self.journal.assert_not_called()

    def test_request_and_config_are_detached_from_port_mutation(self):
        config = {"nested": {"value": "original"}}
        message = {**self.message, "metadata": {"origin": "original"}}
        original_config, original_message = deepcopy(config), deepcopy(message)
        def operator(owned, **kwargs):
            owned["metadata"]["origin"] = "changed"
        def frame(owned, body, **kwargs):
            owned["nested"]["value"] = "changed"
            return {"nested": {"evidence": "original"}}
        def cycle(**kwargs):
            kwargs["epistemic_frame_override"]["nested"]["evidence"] = "changed"
            return {"cycle_id": "cycle"}
        self.operator.side_effect, self.frame.side_effect, self.cycle.side_effect = operator, frame, cycle
        result = prepare_reply_preflight(config, message, "question", thread_limit=8)
        self.assertEqual(original_config, config)
        self.assertEqual(original_message, message)
        self.assertEqual("original", result.epistemic_frame["nested"]["evidence"])

    def test_concurrent_requests_preserve_body_and_frame_lineage(self):
        self.frame.side_effect = lambda config, body, **kwargs: {"body": body}
        self.cycle.side_effect = lambda **kwargs: {"cycle_id": kwargs["inbound"], "frame": kwargs["epistemic_frame_override"]}
        def run(body):
            return prepare_chat_preflight({}, body, session_id=body, private_audit=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, ["first", "second"]))
        self.assertEqual(["first", "second"], [r.conscious_state["frame"]["body"] for r in results])

    def test_journal_does_not_receive_exception_payload(self):
        self.observe.side_effect = RuntimeError("fake credential=not-for-logs")
        result = self.prepare()
        self.assertEqual("RuntimeError", self.journal.call_args.kwargs["metadata"]["reason"])
        self.assertNotIn("not-for-logs", str(result.errors) + str(self.journal.call_args))
