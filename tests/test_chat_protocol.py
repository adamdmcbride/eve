import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import eve_chat_protocol
import eve_web


ROOT = Path(__file__).resolve().parents[1]
EXPORTED_NAMES = (
    "canonical_eve_chat_local_origin",
    "dict_field",
    "durable_eve_chat_followup_action_result",
    "eve_chat_followup_ack_text",
    "eve_chat_followup_action_for_messages",
    "eve_chat_followup_delay_seconds",
    "eve_chat_followup_delivery_text",
    "eve_chat_followup_due_at",
    "eve_chat_followup_requested",
    "eve_chat_followup_seconds_until_due",
    "first_transport_value",
    "openai_chat_evaluation_metadata",
    "openai_chat_thread_id",
    "openai_chat_transport_metadata",
    "recover_eve_chat_followup_action_result",
)


class ChatProtocolModuleTests(unittest.TestCase):
    def test_eve_web_is_a_compatibility_facade_for_chat_protocol(self):
        web_source = (ROOT / "eve_web.py").read_text(encoding="utf-8")

        for name in EXPORTED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(eve_chat_protocol, name),
                    getattr(eve_web, name),
                )
                self.assertNotIn(f"def {name}(", web_source)

        for name in (
            "EVE_CHAT_FOLLOWUP_LEASE_SECONDS",
            "EVE_CHAT_FOLLOWUP_MAX_DELAY_SECONDS",
            "EVE_CHAT_FOLLOWUP_POLL_ORIGINS",
            "EVE_CHAT_FOLLOWUP_SUPPORTED_ACTIONS",
            "EVE_CHAT_FOLLOWUP_WAIT_SLICE_SECONDS",
        ):
            self.assertIs(
                getattr(eve_chat_protocol, name),
                getattr(eve_web, name),
            )

    def test_protocol_module_does_not_import_http_service(self):
        tree = ast.parse((ROOT / "eve_chat_protocol.py").read_text(encoding="utf-8"))
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

        self.assertNotIn("eve_web", imported_modules)

    def test_explicit_relative_followup_is_bounded_and_deterministic(self):
        messages = [
            {
                "role": "user",
                "content": "Check service health in thirty minutes and put the result in this same thread without another prompt.",
            }
        ]
        now = datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc)

        self.assertTrue(eve_chat_protocol.eve_chat_followup_requested(messages))
        self.assertEqual(30 * 60, eve_chat_protocol.eve_chat_followup_delay_seconds(messages))
        self.assertEqual(
            "2026-08-24T00:30:00+00:00",
            eve_chat_protocol.eve_chat_followup_due_at(messages, now=now),
        )

        excessive = [{"role": "user", "content": "Tell me after 999999 days."}]
        self.assertEqual(
            eve_chat_protocol.EVE_CHAT_FOLLOWUP_MAX_DELAY_SECONDS,
            eve_chat_protocol.eve_chat_followup_delay_seconds(excessive),
        )

    def test_immediate_check_does_not_become_a_durable_followup(self):
        messages = [{"role": "user", "content": "Check service health now."}]

        self.assertFalse(eve_chat_protocol.eve_chat_followup_requested(messages))
        self.assertEqual(0, eve_chat_protocol.eve_chat_followup_delay_seconds(messages))

    def test_transport_identity_is_bounded_and_thread_id_hides_external_id(self):
        external_chat_id = "openwebui-private-chat-id"
        metadata = eve_chat_protocol.openai_chat_transport_metadata(
            {
                "metadata": {
                    "chat_id": external_chat_id,
                    "user_message_id": "message-1",
                },
                "id": "assistant-1",
            }
        )
        thread_id = eve_chat_protocol.openai_chat_thread_id(metadata)

        self.assertEqual(external_chat_id, metadata["openwebui_chat_id"])
        self.assertEqual("message-1", metadata["openwebui_user_message_id"])
        self.assertEqual("assistant-1", metadata["openwebui_assistant_message_id"])
        self.assertTrue(thread_id.startswith("eve-chat-openwebui-"))
        self.assertNotIn(external_chat_id, thread_id)
        self.assertEqual(thread_id, eve_chat_protocol.openai_chat_thread_id(metadata))

    def test_evaluation_metadata_requires_explicit_synthetic_provenance(self):
        self.assertEqual(
            {},
            eve_chat_protocol.openai_chat_evaluation_metadata(
                {"metadata": {"source": "untrusted-client", "evaluation_id": "eval-1"}}
            ),
        )
        admitted = eve_chat_protocol.openai_chat_evaluation_metadata(
            {
                "_eve_evaluation": {
                    "synthetic": True,
                    "source": "hidden-evaluator",
                    "evaluation_id": "eval-1",
                }
            }
        )
        self.assertEqual(
            {
                "synthetic": True,
                "conversation_class": "synthetic_eval",
                "source": "hidden-evaluator",
                "evaluation_id": "eval-1",
            },
            admitted,
        )

    def test_poll_origin_is_allowlisted_not_reflected(self):
        self.assertEqual(
            "http://127.0.0.1:3000",
            eve_chat_protocol.canonical_eve_chat_local_origin(
                "http://127.0.0.1:3000"
            ),
        )
        self.assertEqual(
            "",
            eve_chat_protocol.canonical_eve_chat_local_origin(
                "http://attacker.example"
            ),
        )

    def test_durable_action_result_never_promotes_unverified_success(self):
        with patch.object(
            eve_chat_protocol.eve,
            "action_result_verified_for_completion",
            return_value=False,
        ):
            result = eve_chat_protocol.durable_eve_chat_followup_action_result(
                "service_health_check",
                {
                    "executed": True,
                    "ok": True,
                    "summary": "Everything passed.",
                },
            )

        self.assertTrue(result["executed"])
        self.assertFalse(result["ok"])
        self.assertFalse(result["verification_ok"])
        self.assertEqual("Everything passed.", result["summary"])


if __name__ == "__main__":
    unittest.main()
