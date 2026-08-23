import unittest
from unittest.mock import patch

import eve


class LocalConversationInitiativeTests(unittest.TestCase):
    def test_local_conversation_is_allowed_even_when_outreach_blocked_by_failure_clusters(self):
        with (
            patch.object(eve, "load_autonomy_state", return_value={"stage": "verified"}),
            patch.object(eve, "read_failure_clusters", return_value=[{"id": "failure-1", "status": "open"}]),
        ):
            self.assertIsNone(eve.autonomy_action_block_reason("daemon_local_conversation"))
            self.assertIn("still gated", eve.autonomy_action_block_reason("daemon_outreach"))

    def test_local_conversation_does_not_require_proactive_stage(self):
        with patch.object(eve, "load_autonomy_state", return_value={"stage": "observe"}):
            self.assertIsNone(eve.autonomy_action_block_reason("daemon_local_conversation"))

    def test_local_conversation_ignores_waiting_thread_backlog(self):
        config = dict(eve.DEFAULT_CONFIG)
        config["max_waiting_threads_before_outreach"] = 1
        threads = [{"status": "awaiting_user"} for _ in range(6)]
        with patch.object(eve, "latest_outbound_message", return_value=None):
            self.assertIsNone(eve.outreach_pacing_reason(config, threads, ignore_waiting_threads=True))
            self.assertIn("already waiting", eve.outreach_pacing_reason(config, threads))

    def test_personal_conversation_pacing_ignores_regular_replies(self):
        config = dict(eve.DEFAULT_CONFIG)
        config["personal_conversation_minimum_gap_minutes"] = 60
        recent_reply = {
            "sender": "eve",
            "recipient": "user",
            "kind": "reply",
            "reply_to": "user-message-1",
            "timestamp": eve.utc_now(),
            "subject": "Re: Ongoing relay",
        }
        recent_personal = {
            "sender": "eve",
            "recipient": "user",
            "kind": "proactive_outreach",
            "reply_to": None,
            "timestamp": eve.utc_now(),
            "subject": "A personal note",
            "metadata": {"surface": "personal_conversation"},
        }

        with patch.object(eve, "read_messages", return_value=[recent_reply]):
            self.assertIsNone(eve.personal_conversation_pacing_reason(config))
        with patch.object(eve, "read_messages", return_value=[recent_reply, recent_personal]):
            self.assertIn("opened a personal thread recently", eve.personal_conversation_pacing_reason(config))

    def test_daemon_local_conversation_creates_local_only_message_despite_failure_clusters(self):
        config = dict(eve.DEFAULT_CONFIG)
        generated = {
            "subject": "A small question",
            "body": "I noticed one thread we keep circling. Want to look at it together for a minute?",
            "model": "eve-relationship",
            "source_entries": 1,
            "source_thoughts": 0,
            "source_threads": 1,
            "source_messages": 1,
        }

        def fake_create_message(**kwargs):
            return {"id": "message-1", "thread_id": "thread-1", **kwargs}

        with (
            patch.object(eve, "load_autonomy_state", return_value={"stage": "verified"}),
            patch.object(eve, "read_failure_clusters", return_value=[{"id": "failure-1", "status": "open"}]),
            patch.object(eve, "read_thread_summaries", return_value=[]),
            patch.object(eve, "latest_outbound_message", return_value=None),
            patch.object(eve, "generate_eve_outreach", return_value=generated),
            patch.object(eve, "create_message", side_effect=fake_create_message) as create_message,
            patch.object(eve, "append_entry"),
        ):
            record = eve.create_eve_outreach_message(
                config,
                source="daemon",
                notify=False,
                allow_none=True,
                state={},
            )

        self.assertIsNotNone(record)
        self.assertEqual("proactive_outreach", record["kind"])
        self.assertTrue(record["metadata"]["local_only"])
        self.assertFalse(record["metadata"]["external_send_attempted"])
        create_message.assert_called_once()

    def test_daemon_local_conversation_records_quiet_check(self):
        config = dict(eve.DEFAULT_CONFIG)
        state = {}

        with (
            patch.object(eve, "load_autonomy_state", return_value={"stage": "verified"}),
            patch.object(eve, "read_failure_clusters", return_value=[]),
            patch.object(eve, "read_messages", return_value=[]),
            patch.object(eve, "generate_eve_outreach", return_value=None),
            patch.object(eve, "append_entry"),
        ):
            record = eve.create_eve_outreach_message(
                config,
                source="daemon",
                notify=False,
                allow_none=True,
                state=state,
            )

        self.assertIsNone(record)
        self.assertEqual("quiet", state["last_personal_conversation_status"])
        self.assertIn("did not find", state["last_personal_conversation_reason"])
        self.assertEqual("daemon", state["last_personal_conversation_source"])


if __name__ == "__main__":
    unittest.main()
