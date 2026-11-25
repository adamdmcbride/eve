"""Ordered preflight controls without importing Eve or running infrastructure."""
from dataclasses import replace
import unittest

from eve_core.preflight import ConversationPreflight
from eve_core.turns import ConversationTurn


class FakePreflightPorts:
    def __init__(self):
        self.events, self.failures = [], {}
        self.operator, self.reference = None, False
        self.messages = [{"id": "previous"}]
        self.previous = {"scored_reply_id": "exact-reply", "consequence_observed": True, "conscious_consequence_joined": True}
        self.social, self.frame, self.state = {"lineage": "exact"}, {"signals": []}, {"cycle_id": "new-cycle"}

    def event(self, name, payload=None):
        self.events.append((name, payload))
        if name in self.failures:
            raise self.failures[name]

    def resolve_operator(self):
        self.event("operator")
        return self.operator

    def needs_thread(self, body):
        self.event("reference", body)
        return self.reference

    def read_thread(self):
        self.event("thread")
        return self.messages

    def perceive(self, body, **kwargs):
        self.event("perception", {"body": body, **kwargs})
        return self.frame

    def sparse(self, body):
        self.event("sparse", body)
        return {"sparse": True}

    def observe_previous(self):
        self.event("consequence")
        return self.previous

    def refresh_social(self):
        self.event("social")
        return self.social

    def open_cycle(self, body, **kwargs):
        self.event("cycle", {"body": body, **kwargs})
        return self.state

    def record_correction(self, body, **kwargs):
        self.event("correction", {"body": body, **kwargs})
        return {"id": "correction"}

    def warning(self, kind, summary, metadata):
        self.event("warning", {"kind": kind, "summary": summary, "metadata": metadata})


class CorePreflightTests(unittest.TestCase):
    def setUp(self):
        self.ports = FakePreflightPorts()
        self.service = ConversationPreflight(self.ports, self.ports, self.ports, self.ports)
        self.turn = ConversationTurn("current question", "reply", message_id="current", thread_id="thread")

    def prepare(self, **changes):
        return self.service.prepare(replace(self.turn, **changes))

    def payload(self, name):
        return next(payload for event, payload in self.ports.events if event == name)

    def test_user_feedback_precedes_social_perception_cycle_and_correction(self):
        result = self.prepare()
        self.assertEqual(["operator", "consequence", "social", "reference", "perception", "cycle", "correction"],
                         [name for name, _ in self.ports.events])
        self.assertEqual("exact-reply", self.payload("correction")["target_message_id"])
        self.assertTrue(self.payload("correction")["consequence_joined"])
        self.assertEqual(result.epistemic_frame, self.payload("cycle")["frame"])
        self.assertEqual(result.other_minds_model, self.payload("cycle")["social"])
        self.assertTrue(self.payload("cycle")["persist"])
        self.assertEqual((), result.errors)

    def test_synthetic_mailbox_turn_never_observes_learns_or_journals(self):
        self.ports.failures["cycle"] = RuntimeError("sensitive model input")
        result = self.prepare(synthetic=True)
        names = [name for name, _ in self.ports.events]
        self.assertFalse(set(names) & {"consequence", "social", "correction", "warning"})
        self.assertFalse(self.payload("perception")["allow_semantic"])
        self.assertFalse(self.payload("cycle")["persist"])
        self.assertEqual("reply_synthetic_preflight", self.payload("cycle")["source"])
        self.assertEqual(("conscious_cycle_preflight_failed: RuntimeError",), result.errors)

    def test_other_agent_report_is_not_human_feedback(self):
        self.ports.operator = {"operator": "codex", "report": "health routing failure"}
        result = self.prepare(source_owner="other_agent")
        self.assertFalse(set(name for name, _ in self.ports.events) & {"consequence", "social", "correction"})
        self.assertFalse(self.payload("perception")["allow_semantic"])
        self.assertEqual("reply_external_operator_result_preflight", self.payload("cycle")["source"])
        self.assertEqual(self.ports.operator, result.external_operator_context)

    def test_empty_operator_context_is_still_an_external_envelope(self):
        self.ports.operator = {}
        self.prepare(source_owner="other_agent")
        self.assertFalse(self.payload("perception")["allow_semantic"])

    def test_no_reference_does_not_read_thread(self):
        self.assertIsNone(self.prepare().thread_messages)
        self.assertNotIn("thread", [name for name, _ in self.ports.events])

    def test_reference_is_loaded_once_and_shared_with_perception(self):
        self.ports.reference = True
        result = self.prepare()
        self.assertEqual(self.ports.messages, result.thread_messages)
        self.assertEqual(result.thread_messages, self.payload("perception")["thread_messages"])
        self.assertEqual(1, [name for name, _ in self.ports.events].count("thread"))

    def test_thread_failure_retains_empty_reference_receipt(self):
        self.ports.reference = True
        self.ports.failures["thread"] = OSError("unavailable")
        result = self.prepare()
        self.assertEqual([], result.thread_messages)
        self.assertEqual([], self.payload("perception")["thread_messages"])
        self.assertIn("reply_reference_preflight_failed: OSError", result.errors)

    def test_bad_thread_receipt_is_not_given_to_perception(self):
        self.ports.reference, self.ports.messages = True, ["not a message"]
        self.assertEqual([], self.prepare().thread_messages)

    def test_perception_failure_uses_sparse_frame_in_same_cycle(self):
        self.ports.failures["perception"] = SystemExit("model offline")
        result = self.prepare()
        self.assertEqual({"sparse": True}, result.epistemic_frame)
        self.assertEqual(result.epistemic_frame, self.payload("cycle")["frame"])
        self.assertIn("epistemic_perception_preflight_failed: SystemExit", result.errors)

    def test_bad_perception_receipt_uses_sparse_fallback(self):
        self.ports.frame = None
        self.assertEqual({"sparse": True}, self.prepare().epistemic_frame)

    def test_consequence_failure_does_not_invent_reply_credit(self):
        self.ports.failures["consequence"] = ValueError("broken join")
        result = self.prepare()
        self.assertIsNone(result.prior_reply_consequence)
        correction = self.payload("correction")
        self.assertEqual("", correction["target_message_id"])
        self.assertFalse(correction["consequence_observed"])
        self.assertFalse(correction["consequence_joined"])

    def test_social_failure_does_not_substitute_unrelated_state(self):
        self.ports.failures["social"] = RuntimeError("broken state")
        self.assertIsNone(self.prepare().other_minds_model)
        self.assertIsNone(self.payload("cycle")["social"])

    def test_truthy_strings_are_not_verified_consequence_receipts(self):
        self.ports.previous = {"scored_reply_id": "exact", "consequence_observed": "false",
                               "conscious_consequence_joined": "true"}
        self.prepare()
        self.assertFalse(self.payload("correction")["consequence_observed"])
        self.assertFalse(self.payload("correction")["consequence_joined"])

    def test_operator_failure_is_explicit_without_exit(self):
        self.ports.failures["operator"] = SystemExit("unavailable")
        result = self.prepare()
        self.assertIsNone(result.external_operator_context)
        self.assertEqual("external_operator_result_resolution_failed: SystemExit", result.errors[0])

    def test_invalid_optional_receipts_are_not_silent_success(self):
        self.ports.operator, self.ports.previous, self.ports.social = True, [], "bad state"
        result = self.prepare()
        self.assertIsNone(result.external_operator_context)
        self.assertIsNone(result.prior_reply_consequence)
        self.assertIsNone(result.other_minds_model)
        self.assertEqual(3, len(result.errors))

    def test_failed_or_invalid_cycle_returns_no_cycle_claim(self):
        for value in (None, True, "success"):
            with self.subTest(value=value):
                self.ports.state = value
                self.assertEqual({}, self.prepare().conscious_state)

    def test_correction_failure_preserves_answer_preflight(self):
        self.ports.failures["correction"] = OSError("locked")
        result = self.prepare()
        self.assertEqual("new-cycle", result.conscious_state["cycle_id"])
        self.assertIsNone(result.user_correction)
        self.assertIn("reply_correction_preflight_failed: OSError", result.errors)

    def test_journal_failure_is_receipted_not_a_second_crash(self):
        self.ports.failures.update(operator=RuntimeError("secret"), warning=OSError("secret"))
        result = self.prepare()
        self.assertIn("preflight_journal_failed: OSError", result.errors)
        self.assertNotIn("secret", str(result.errors) + str(self.payload("warning")))

    def test_cli_has_no_mailbox_feedback_or_reference_effects(self):
        result = self.prepare(surface="chat", session_id="session")
        self.assertEqual(["perception", "cycle"], [name for name, _ in self.ports.events])
        self.assertEqual([], result.thread_messages)
        self.assertTrue(self.payload("perception")["allow_semantic"])
        self.assertEqual("chat_preflight", self.payload("cycle")["source"])

    def test_cli_private_cycle_does_not_persist_or_journal(self):
        self.ports.failures["cycle"] = OSError("private probe")
        self.prepare(surface="chat", synthetic=True)
        self.assertFalse(self.payload("cycle")["persist"])
        self.assertEqual("chat_private_preflight", self.payload("cycle")["source"])
        self.assertNotIn("warning", [name for name, _ in self.ports.events])

    def test_independent_requests_do_not_accumulate_error_buffers(self):
        self.ports.failures["social"] = OSError("first")
        first = self.prepare()
        self.ports.failures.clear()
        second = self.prepare(message_id="second")
        self.assertEqual(1, len(first.errors))
        self.assertEqual((), second.errors)

    def test_unknown_surface_and_truthy_policy_flags_are_rejected(self):
        with self.assertRaises(ValueError):
            self.prepare(surface="other")
        with self.assertRaises(ValueError):
            self.prepare(synthetic="false")
