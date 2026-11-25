"""Independent application tests: no Eve facade, model servers or live stores."""
from copy import deepcopy
import unittest

from eve_core.changes import collect_change_evidence
from eve_core.ports import CodingSession, Verification
from eve_core.self_change import SelfChangeService


class FakeClock:
    def utc(self):
        return "2026-10-01T10:00:00+00:00"

    def monotonic(self):
        return 42.0


class FakeProposals:
    def __init__(self):
        self.items = [{"id": "p1", "title": "Improve a check", "metadata": {}}]
        self.updated = []
        self.error = None
        self.candidates_error = None

    def archive_stale(self, config):
        pass

    def candidates(self, config):
        if self.candidates_error:
            raise self.candidates_error
        return self.items

    def update(self, proposal_id, status, metadata):
        if self.error:
            raise self.error
        self.updated.append((proposal_id, status, metadata))


class FakeCoder:
    authority_tools = ("set_config", "request_restart", "record_change")

    def __init__(self):
        self.agent = {"response": "changed", "tool_calls": []}
        self.error = None
        self.verify_error = None
        self.rollback_error = None
        self.rollback_paths = ["eve_core/changes.py"]
        self.preparation_error = None
        self.sessions = []
        self.verifications = []
        self.restored = []
        self.verdict = True
        self.reason = ""

    def prepare(self, config, now, proposal, timeout):
        if self.preparation_error:
            raise self.preparation_error
        session = CodingSession("session-" + str(len(self.sessions)), "backup", dict(config))
        session.config["code_timeout_seconds"] = timeout
        self.sessions.append(session)
        return session

    def execute(self, session, proposal):
        if self.reason:
            session.context["restart_requested"] = self.reason
        if self.error:
            raise self.error
        return self.agent

    def verify(self, session, tests_ok):
        self.verifications.append(tests_ok)
        if self.verify_error:
            raise self.verify_error
        return Verification(self.verdict and tests_ok is not False, "passed" if self.verdict and tests_ok is not False else "tests failed")

    def rollback(self, session):
        if self.rollback_error:
            raise self.rollback_error
        self.restored.append(session.session_id)
        return self.rollback_paths


class FakeRuntime:
    def __init__(self):
        self.receipt = {"verified": True}
        self.sync_error = None
        self.restart_error = None
        self.ack = True
        self.syncs = 0
        self.restarts = []

    def synchronize(self):
        self.syncs += 1
        if self.sync_error:
            raise self.sync_error
        return self.receipt

    def restart(self, session, reason, code_changed):
        self.restarts.append((session.session_id, reason, code_changed))
        if self.restart_error:
            raise self.restart_error
        return self.ack


class FakeJournal:
    def __init__(self):
        self.rows, self.entries, self.followups, self.messages = [], [], [], []
        self.error = None
        self.followup_error = None
        self.notify_error = None
        self.history_error = None
        self.start_error = None

    def history(self):
        if self.history_error:
            raise self.history_error
        return self.rows

    def entry(self, kind, text, metadata):
        if kind == "self_change_started" and self.start_error:
            raise self.start_error
        self.entries.append((kind, text, metadata))

    def write(self, row):
        if self.error:
            raise self.error
        self.rows.append(deepcopy(row))

    def follow_up(self, row, config):
        if self.followup_error:
            raise self.followup_error
        self.followups.append(row)

    def notify(self, row):
        if self.notify_error:
            raise self.notify_error
        self.messages.append(row)


def tool(name, **result):
    return {"tool": name, "args": {}, "result": result}


class CoreSelfChangeTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.proposals, self.coder, self.runtime, self.journal = FakeClock(), FakeProposals(), FakeCoder(), FakeRuntime(), FakeJournal()
        self.service = SelfChangeService(self.clock, self.proposals, self.coder, self.runtime, self.journal)

    def run_cycle(self, calls=(), config=None):
        self.coder.agent = {"response": "tested", "tool_calls": list(calls)}
        return self.service.run(config or {}, source="test")

    def patch(self):
        return tool("apply_patch", ok=True, paths=["eve_core/changes.py"])

    def test_disabled_never_prepares_a_session(self):
        self.assertFalse(self.run_cycle(config={"self_change_enabled": False})["executed"])
        self.assertEqual([], self.coder.sessions)

    def test_daily_budget_does_not_execute(self):
        self.journal.rows = [{"started_at": self.clock.utc()}]
        self.assertFalse(self.run_cycle(config={"self_change_max_per_day": 1})["executed"])

    def test_no_candidate_or_wrong_id_does_not_execute(self):
        result = self.service.run({}, source="test", proposal_id="absent")
        self.assertFalse(result["executed"])
        self.proposals.items = []
        self.assertFalse(self.run_cycle()["executed"])

    def test_preparation_failure_does_not_run_or_synchronize(self):
        self.coder.preparation_error = OSError("no space")
        self.assertFalse(self.run_cycle()["executed"])
        self.assertEqual(0, self.runtime.syncs)

    def test_missing_history_candidates_or_start_receipt_prevents_execution(self):
        for target, field in ((self.journal, "history_error"), (self.proposals, "candidates_error"), (self.journal, "start_error")):
            with self.subTest(field=field):
                setattr(target, field, OSError("unavailable"))
                self.assertFalse(self.run_cycle()["executed"])
                setattr(target, field, None)
        self.assertEqual(0, self.runtime.syncs)
        self.assertEqual([], self.journal.rows)

    def test_verified_code_requires_sync_and_acknowledged_restart(self):
        result = self.run_cycle([self.patch(), tool("run_tests", ok=True)])
        self.assertEqual("applied", result["outcome"])
        self.assertTrue(result["runtime_synced"] and result["restart_requested"])
        self.assertEqual(1, len(self.journal.messages))
        self.assertEqual(1, len(self.journal.followups))

    def test_operational_change_does_not_sync_or_restart(self):
        self.assertTrue(self.run_cycle([tool("set_config", ok=True)])["ok"])
        self.assertEqual(0, self.runtime.syncs)
        self.assertEqual([], self.runtime.restarts)

    def test_noop_is_not_applied(self):
        self.assertEqual("no_change", self.run_cycle([tool("set_config", ok=True, no_op=True)])["outcome"])
        self.assertEqual("archived", self.proposals.updated[-1][1])

    def test_deferred_only_does_not_spend_an_attempt(self):
        result = self.run_cycle([tool("apply_patch", ok=False, deferred_claim="other-session")])
        self.assertEqual("deferred_claim", result["outcome"])
        self.assertEqual(0, self.proposals.updated[-1][2]["self_change_attempts"])
        self.assertEqual(0, self.runtime.syncs)

    def test_failed_verification_rolls_back_and_cannot_restart(self):
        self.coder.reason = "please restart"
        result = self.run_cycle([self.patch(), tool("run_tests", ok=False)])
        self.assertEqual("failed", result["outcome"])
        self.assertTrue(result["rollback"])
        self.assertEqual(0, self.runtime.syncs)
        self.assertEqual([], self.runtime.restarts)

    def test_mixed_operational_effect_and_failed_patch_is_partial_not_applied(self):
        result = self.run_cycle([tool("set_config", ok=True), self.patch(), tool("run_tests", ok=False)])
        self.assertEqual("failed", result["outcome"])
        self.assertTrue(result["partial_effects"])
        self.assertFalse(result["ok"])
        self.assertEqual([], self.journal.messages)

    def test_failed_tests_are_sticky_even_after_a_later_pass(self):
        result = self.run_cycle([self.patch(), tool("run_tests", ok=False), tool("run_tests", ok=True)])
        self.assertEqual("failed", result["outcome"])
        self.assertEqual([False], self.coder.verifications)

    def test_missing_tests_uses_verifier(self):
        self.run_cycle([self.patch()])
        self.assertEqual([None], self.coder.verifications)

    def test_verifier_failure_is_audited_and_rolled_back(self):
        self.coder.verify_error = OSError("compiler unavailable")
        self.assertEqual("failed", self.run_cycle([self.patch()])["outcome"])
        self.assertTrue(self.coder.restored)
        self.assertEqual("failed", self.journal.rows[-1]["outcome"])

    def test_sync_exception_rolls_back_source_and_blocks_restart(self):
        self.runtime.sync_error = OSError("bundle canary failed")
        result = self.run_cycle([self.patch()])
        self.assertEqual("failed", result["outcome"])
        self.assertFalse(result["runtime_synced"] or result["restart_requested"])
        self.assertTrue(self.coder.restored)
        self.assertEqual([], self.runtime.restarts)

    def test_unverified_or_malformed_sync_receipt_is_never_success(self):
        for receipt in ({}, {"verified": False}, {"verified": "true"}, None):
            with self.subTest(receipt=receipt):
                self.setUp()
                self.runtime.receipt = receipt
                result = self.run_cycle([self.patch()])
                self.assertEqual("failed", result["outcome"])
                self.assertEqual([], self.runtime.restarts)

    def test_restart_failure_keeps_runtime_and_backup_evidence_separate(self):
        self.runtime.restart_error = OSError("request not written")
        result = self.run_cycle([self.patch()])
        self.assertEqual("failed", result["outcome"])
        self.assertTrue(result["runtime_synced"] and result["partial_effects"])
        self.assertFalse(result["restart_requested"])
        self.assertEqual([], self.coder.restored)

    def test_missing_restart_acknowledgment_is_not_accepted(self):
        self.runtime.ack = False
        self.assertFalse(self.run_cycle([self.patch()])["restart_requested"])

    def test_rollback_failure_is_visible(self):
        self.coder.rollback_error = OSError("backup inaccessible")
        result = self.run_cycle([self.patch(), tool("run_tests", ok=False)])
        self.assertFalse(result["ok"])
        self.assertIn("rollback failed", result["error"])
        self.assertFalse(result["source_restored"])
        self.assertTrue(result["partial_effects"])

    def test_missing_backup_cannot_be_reported_as_a_complete_rollback(self):
        self.coder.rollback_paths = []
        result = self.run_cycle([self.patch(), tool("run_tests", ok=False)])
        self.assertFalse(result["source_restored"])
        self.assertTrue(result["partial_effects"])
        self.assertIn("source rollback incomplete", result["error"])

    def test_model_system_exit_is_a_failed_attempt_not_a_process_exit(self):
        self.coder.error = SystemExit("timeout")
        result = self.run_cycle()
        self.assertEqual("failed", result["outcome"])
        self.assertIn("timeout", self.journal.rows[-1]["error"])

    def test_agent_error_after_reported_effect_cannot_be_applied(self):
        result = self.run_cycle([tool("set_config", ok=False, error="denied")])
        self.assertEqual("failed", result["outcome"])

    def test_malformed_tool_receipts_are_recorded_without_crashing(self):
        for call in (None, "text", {}, {"tool": "apply_patch", "result": None}, {"tool": "set_config", "args": "bad", "result": {"ok": True}}):
            with self.subTest(call=call):
                self.setUp()
                self.assertEqual("failed", self.run_cycle([call])["outcome"])

    def test_malformed_agent_cannot_be_no_change(self):
        for agent in (None, [], {"tool_calls": "bad"}):
            with self.subTest(agent=agent):
                self.setUp()
                self.coder.agent = agent
                self.assertEqual("failed", self.service.run({}, source="test")["outcome"])

    def test_successful_patch_requires_list_of_paths_not_a_string(self):
        for paths in (None, "eve.py", [], [None]):
            with self.subTest(paths=paths):
                self.setUp()
                self.assertFalse(self.run_cycle([tool("apply_patch", ok=True, paths=paths)])["ok"])

    def test_truthy_string_is_not_a_success_receipt(self):
        self.assertEqual("failed", self.run_cycle([tool("set_config", ok="true")])["outcome"])

    def test_non_json_arguments_are_invalid_evidence_not_a_crash(self):
        call = tool("set_config", ok=True)
        call["args"] = {"value": object()}
        result = self.run_cycle([call])
        self.assertEqual("failed", result["outcome"])
        self.assertIn("non-JSON", result["error"])

    def test_declarations_retain_their_reported_evidence_contract(self):
        call = tool("record_change", ok=True)
        call["args"] = {"what": "refreshed a state", "verification": "readback matched"}
        self.assertTrue(self.run_cycle([call])["ok"])
        call["args"] = {"what": "did a thing"}
        self.assertFalse(self.run_cycle([call])["ok"])

    def test_session_context_does_not_leak_to_next_session(self):
        self.coder.reason = "first session only"
        self.run_cycle([tool("request_restart", ok=True)])
        self.coder.reason = ""
        self.run_cycle([tool("set_config", ok=True)])
        self.assertEqual(1, len(self.runtime.restarts))
        self.assertIsNot(self.coder.sessions[0].context, self.coder.sessions[1].context)

    def test_attempts_are_bounded_and_second_failure_archives(self):
        self.proposals.items[0]["metadata"] = {"self_change_attempts": 1}
        self.run_cycle([tool("set_config", ok=False)])
        self.assertEqual("archived", self.proposals.updated[-1][1])
        self.proposals.items[0]["metadata"] = {"self_change_attempts": "invalid"}
        self.run_cycle([tool("set_config", ok=False)])
        self.assertEqual(1, self.proposals.updated[-1][2]["self_change_attempts"])

    def test_invalid_timeout_uses_bounded_default(self):
        self.service.run({"self_change_timeout_seconds": "invalid"}, source="test", timeout_seconds=99999)
        self.assertEqual(1800, self.coder.sessions[-1].config["code_timeout_seconds"])

    def test_persistence_failure_cannot_report_success(self):
        for target in (self.proposals, self.journal):
            with self.subTest(target=type(target).__name__):
                target.error = OSError("disk full")
                result = self.run_cycle([tool("set_config", ok=True)])
                self.assertFalse(result["ok"])
                self.assertIn("audit persistence", result["error"])
                target.error = None

    def test_followup_or_notification_failure_is_a_warning_not_lost_effect(self):
        self.journal.followup_error = OSError("followup unavailable")
        self.journal.notify_error = OSError("mail unavailable")
        result = self.run_cycle([tool("set_config", ok=True)])
        self.assertTrue(result["ok"])
        self.assertEqual(2, len(result["warnings"]))

    def test_paths_are_deduplicated_without_changing_order(self):
        evidence = collect_change_evidence({"tool_calls": [self.patch(), self.patch()]}, self.coder.authority_tools)
        self.assertEqual(("eve_core/changes.py",), evidence.paths)


if __name__ == "__main__":
    unittest.main()
