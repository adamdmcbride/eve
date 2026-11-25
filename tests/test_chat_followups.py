import ast
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import eve_chat_followups
import eve_web


ROOT = Path(__file__).resolve().parents[1]


class EveChatFollowupServiceBoundaryTests(unittest.TestCase):
    def test_followup_module_is_one_way_and_owns_no_http_surface(self):
        tree = ast.parse((ROOT / "eve_chat_followups.py").read_text(encoding="utf-8"))
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

        self.assertNotIn("eve_web", imported_modules)
        self.assertFalse(
            any(module.startswith("http") for module in imported_modules),
            imported_modules,
        )

    def test_runtime_service_composes_one_worker_owner(self):
        service = eve_web.EveRuntimeService()

        self.assertIsInstance(
            service._eve_chat_followup_service,
            eve_chat_followups.EveChatFollowupService,
        )
        self.assertIs(
            service._followup_workers_lock,
            service._eve_chat_followup_service._followup_workers_lock,
        )
        self.assertIs(
            service._active_followup_workers,
            service._eve_chat_followup_service._active_followup_workers,
        )

    def test_composition_policy_is_immutable_and_preserves_patch_seams(self):
        with (
            patch.object(eve_web, "EVE_CHAT_FOLLOWUP_LEASE_SECONDS", 17),
            patch.object(eve_web, "EVE_CHAT_FOLLOWUP_WAIT_SLICE_SECONDS", 0.25),
            patch.object(eve_web, "EVE_CHAT_FOLLOWUP_SUPPORTED_ACTIONS", {"bounded-check"}),
        ):
            policy = eve_web._eve_chat_followup_policy()

        self.assertEqual(17, policy.lease_seconds)
        self.assertEqual(0.25, policy.wait_slice_seconds)
        self.assertEqual(frozenset({"bounded-check"}), policy.supported_actions)
        with self.assertRaises(FrozenInstanceError):
            policy.lease_seconds = 1

    def test_composition_hooks_preserve_legacy_runtime_patch_seams(self):
        service = eve_web.EveRuntimeService()
        hooks = service._eve_chat_followup_service._hooks
        record = {"id": "followup-1"}

        with (
            patch.object(service, "_run_mutation", return_value={"mutated": True}) as mutate,
            patch.object(service, "start_eve_chat_followup_worker") as start,
            patch.object(
                service,
                "_existing_eve_chat_followup_delivery",
                return_value={"id": "delivery-1"},
            ) as existing,
            patch.object(
                service,
                "_complete_eve_chat_followup_cycle",
                return_value={"cycle_id": "cycle-1"},
            ) as complete,
            patch.object(
                eve_web,
                "recover_eve_chat_followup_action_result",
                return_value={"execution_id": "execution-1"},
            ) as recover,
        ):
            self.assertEqual({"mutated": True}, hooks.run_mutation(lambda: {}))
            hooks.start_worker("followup-1")
            self.assertEqual(
                {"id": "delivery-1"},
                hooks.existing_delivery("followup-1", "thread-1"),
            )
            self.assertEqual(
                {"cycle_id": "cycle-1"},
                hooks.complete_cycle(record=record),
            )
            self.assertEqual(
                {"execution_id": "execution-1"},
                hooks.recover_action_result(record),
            )

        mutate.assert_called_once()
        start.assert_called_once_with("followup-1")
        existing.assert_called_once_with("followup-1", "thread-1")
        complete.assert_called_once_with(record=record)
        recover.assert_called_once_with(record)

    def test_runtime_service_methods_remain_compatible_delegates(self):
        service = eve_web.EveRuntimeService()
        child = service._eve_chat_followup_service

        with patch.object(
            child,
            "eve_chat_followups",
            return_value={"items": [], "count": 0},
        ) as read:
            payload = service.eve_chat_followups(
                status="waiting",
                surface="eve_chat_ui",
                include_seen=True,
                limit=7,
            )
        self.assertEqual(0, payload["count"])
        read.assert_called_once_with(
            status="waiting",
            surface="eve_chat_ui",
            include_seen=True,
            limit=7,
        )

        with patch.object(child, "run_eve_chat_followup_worker") as run:
            service.run_eve_chat_followup_worker("followup-1")
        run.assert_called_once_with("followup-1")

    def test_worker_admission_deduplicates_one_in_process_owner(self):
        service = eve_web.EveRuntimeService()
        child = service._eve_chat_followup_service
        workers = []

        class FakeThread:
            def __init__(self, **kwargs):
                workers.append(kwargs)

            def start(self):
                return None

        with patch.object(eve_chat_followups.threading, "Thread", FakeThread):
            child.start_eve_chat_followup_worker("followup-12345678")
            child.start_eve_chat_followup_worker("followup-12345678")
            child.start_eve_chat_followup_worker("")

        self.assertEqual(1, len(workers))
        self.assertEqual("eve-chat-followup-followup", workers[0]["name"])
        self.assertTrue(workers[0]["daemon"])
        self.assertEqual({"followup-12345678"}, child._active_followup_workers)

    def test_terminal_worker_releases_in_process_admission(self):
        service = eve_web.EveRuntimeService()
        child = service._eve_chat_followup_service
        child._active_followup_workers.add("followup-terminal")

        with patch.object(
            eve_chat_followups.eve,
            "eve_chat_followup_record",
            return_value={"id": "followup-terminal", "status": "delivered"},
        ):
            child.run_eve_chat_followup_worker("followup-terminal")

        self.assertNotIn("followup-terminal", child._active_followup_workers)


if __name__ == "__main__":
    unittest.main()
