"""Synthetic interruption controls over the existing follow-up service.

No live action, database, message, lease or memory is read/written. A process
death is represented by BaseException so ordinary error cleanup cannot hide it.
"""
from contextlib import ExitStack
import unittest
from unittest.mock import patch

import eve
from eve_chat_followups import EveChatFollowupHooks, EveChatFollowupPolicy, EveChatFollowupService
from eve_chat_protocol import recover_eve_chat_followup_action_result


class SimulatedProcessDeath(BaseException):
    pass


class FollowupRecoveryControls(unittest.TestCase):
    def exercise(self, crash_point, *, verified=True):
        state = {"id": "synthetic-followup", "status": "running", "requested_action": "service_health_check",
                 "thread_id": "synthetic-thread", "due_at": "2020-01-01T00:00:00Z"}
        journal, deliveries, effects = [], [], []
        pending_crash = [crash_point]

        def interrupt(point):
            if pending_crash[0] == point:
                pending_crash[0] = None
                raise SimulatedProcessDeath(point)

        def update(identifier, **changes):
            self.assertEqual(state["id"], identifier)
            state.update(changes)
            if "worker_cycle_id" in changes:
                interrupt("before_effect")
            if changes.get("status") == "result_ready":
                interrupt("after_result_checkpoint")
            return dict(state)

        def action(name, _config, *, source, persist):
            effects.append(name)
            interrupt("after_effect_before_receipt")
            receipt = {"id": "synthetic-execution", "execution_id": "synthetic-execution", "action": name,
                       "source": source, "executed": True, "ok": verified, "verification_ok": verified,
                       "execution_verification_ok": verified, "tree_status": "SUCCESS" if verified else "FAILURE",
                       "summary": "Synthetic effect result", "backend": "py_trees"}
            journal.append(receipt)
            interrupt("after_action_receipt")
            return receipt

        def deliver(**kwargs):
            self.assertEqual("synthetic-thread", kwargs["thread_id"])
            deliveries.append({"id": "synthetic-delivery"})
            interrupt("after_delivery_before_checkpoint")
            return deliveries[-1]

        hooks = EveChatFollowupHooks(run_mutation=lambda fn: fn(), start_worker=lambda _id: None,
                 existing_delivery=lambda _id, _thread: deliveries[-1] if deliveries else {},
                 complete_cycle=lambda **kwargs: {"cycle_id": "synthetic-cycle"},
                 recover_action_result=recover_eve_chat_followup_action_result)
        make_service = lambda: EveChatFollowupService(policy_provider=lambda: EveChatFollowupPolicy(
            lease_seconds=1, wait_slice_seconds=.01, supported_actions=frozenset({"service_health_check"})), hooks=hooks)
        with ExitStack() as patches:
            for name, kwargs in {
                "eve_chat_followup_record": {"side_effect": lambda _id: dict(state)},
                "claim_eve_chat_followup_record": {"side_effect": lambda *a, **k: {"claimed": True, "record": dict(state)}},
                "load_config": {"return_value": {}},
                "build_recurrent_conscious_state": {"return_value": {"cycle_id": "synthetic-cycle"}},
                "update_eve_chat_followup_record": {"side_effect": update},
                "run_operational_action_tree": {"side_effect": action},
                "read_action_executions": {"side_effect": lambda **kwargs: list(journal)},
                "create_message": {"side_effect": deliver},
            }.items():
                patches.enter_context(patch.object(eve, name, **kwargs))
            first = make_service()
            if crash_point:
                with self.assertRaises(SimulatedProcessDeath):
                    first.run_eve_chat_followup_worker(state["id"])
                self.assertNotIn(state["id"], first._active_followup_workers)
            else:
                first.run_eve_chat_followup_worker(state["id"])
            # A fresh service has no in-process worker state. Claim success here
            # models lease expiry; this does not replace the real lease tests.
            make_service().run_eve_chat_followup_worker(state["id"])
        return state, effects, deliveries

    def test_restart_at_recoverable_boundaries_does_not_duplicate_receipted_work(self):
        for point in ("before_effect", "after_action_receipt", "after_result_checkpoint", "after_delivery_before_checkpoint"):
            with self.subTest(point=point):
                state, effects, deliveries = self.exercise(point)
                self.assertEqual(1, len(effects))
                self.assertEqual(1, len(deliveries))
                self.assertEqual("delivered", state["status"])
                self.assertTrue(state["action_result_ok"])

    def test_recovered_negative_receipt_never_becomes_verified_success(self):
        state, effects, deliveries = self.exercise("after_action_receipt", verified=False)
        self.assertEqual(1, len(effects))
        self.assertEqual(1, len(deliveries))
        self.assertFalse(state["action_result_ok"])

    def test_known_unreceipted_effect_window_is_not_an_exactly_once_guarantee(self):
        # Negative control: current service cannot distinguish no effect from an
        # effect followed by process death before its receipt. Retain this gap;
        # target reconciliation/idempotency is required before general writes.
        _, effects, _ = self.exercise("after_effect_before_receipt")
        self.assertEqual(2, len(effects))


if __name__ == "__main__":
    unittest.main()
