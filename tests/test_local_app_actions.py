import unittest
import subprocess
from unittest.mock import patch

import eve


class LocalAppActionTests(unittest.TestCase):
    def test_open_slack_request_is_supported_commitment(self):
        self.assertTrue(eve.requests_open_slack_app("Please open Slack on my computer."))
        self.assertEqual("open_slack_app", eve.classify_supported_reply_commitment("I will open Slack now."))
        self.assertTrue(
            eve.should_execute_open_slack_app_reply(
                "you open it",
                [
                    {
                        "sender": "user",
                        "body": "Can you open the app slack on my computer",
                    }
                ],
            )
        )

    def test_open_calendar_request_is_supported_bounded_local_app_commitment(self):
        self.assertTrue(eve.requests_open_calendar_app("Please open Calendar on my computer."))
        self.assertEqual("open_calendar_app", eve.requested_open_local_app_action("launch the Calendar app"))
        self.assertEqual("open_calendar_app", eve.classify_supported_reply_commitment("I will open Calendar now."))

    def test_calendar_read_request_is_separate_from_open_only_calendar(self):
        self.assertFalse(eve.requests_calendar_read_upcoming("Open Calendar on my computer."))
        self.assertTrue(eve.requests_calendar_read_upcoming("What is on my calendar today?"))
        self.assertEqual(
            eve.CALENDAR_READ_UPCOMING_ACTION,
            eve.classify_supported_reply_commitment("I will check your Calendar now."),
        )

    def test_open_calendar_chat_response_runs_without_event_access(self):
        fake_result = {
            "execution_id": "exec-calendar",
            "execution_tree_status": "SUCCESS",
            "execution_verification_ok": True,
            "summary": "Calendar is open; open_exit=0; was_running=no.",
            "app_name": "Calendar",
            "ok": True,
            "process_running": True,
        }
        with patch.object(eve, "run_operational_action_tree", return_value=fake_result) as action_tree:
            result = eve.open_local_app_request_response("Open Calendar on my computer.", {})

        action_tree.assert_called_once_with("open_calendar_app", {}, source="chat_local_app")
        self.assertIsNotNone(result)
        response = str(result["response"])
        self.assertIn("ACTION_ATTEMPTED: open_calendar_app", response)
        self.assertIn("I did not read calendar events", response)

    def test_calendar_read_upcoming_contract_redacts_titles(self):
        validated, issues = eve.validate_calendar_read_upcoming_result_contract(
            {
                "executed": True,
                "ok": True,
                "summary": "Calendar read-only preview completed.",
                "response": "I checked Calendar metadata.",
                "event_count": 1,
                "events_preview": [{"start": "Monday, April 27, 2026 at 9:00 AM", "calendar": "Work"}],
                "window_days": 7,
                "limit": 8,
                "scope": eve.CALENDAR_READ_UPCOMING_SCOPE,
                "title_redaction": True,
                "metadata": {"source": "test"},
            }
        )

        self.assertEqual([], issues)
        self.assertTrue(validated["typed_contract"]["valid"])
        self.assertTrue(validated["events_preview"][0]["title_redacted"])
        self.assertNotIn("summary", validated["events_preview"][0])

    def test_run_bounded_calendar_read_upcoming_reads_metadata_only(self):
        completed = subprocess.CompletedProcess(
            ["/usr/bin/osascript", "-e", "script"],
            returncode=0,
            stdout="Monday, April 27, 2026 at 9:00:00 AM | Work\nTuesday, April 28, 2026 at 2:00:00 PM | Home\n",
            stderr="",
        )
        with (
            patch.object(eve.sys, "platform", "darwin"),
            patch.object(eve, "local_app_bundle_path", return_value="/System/Applications/Calendar.app"),
            patch.object(eve.Path, "exists", return_value=True),
            patch.object(eve.subprocess, "run", return_value=completed) as run_command,
        ):
            result = eve.run_bounded_calendar_read_upcoming(
                {"calendar_read_window_days": 3, "calendar_read_limit": 2, "calendar_read_backend": "applescript"},
                source="test",
            )

        run_command.assert_called_once()
        self.assertTrue(result["ok"])
        self.assertEqual(2, result["event_count"])
        self.assertEqual(eve.CALENDAR_READ_UPCOMING_SCOPE, result["scope"])
        self.assertTrue(all(item["title_redacted"] for item in result["events_preview"]))
        self.assertIn("redacted event titles", result["response"])

    def test_run_bounded_calendar_read_upcoming_prefers_sqlite_cache(self):
        sqlite_result = {
            "ok": True,
            "event_count": 1,
            "events_preview": [{"start": "2026-04-27T09:00-06:00", "calendar": "Work", "title_redacted": True}],
            "backend": "calendar_sqlite",
            "db_path": "/Users/example/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb",
        }
        with (
            patch.object(eve.sys, "platform", "darwin"),
            patch.object(eve, "read_calendar_upcoming_from_sqlite", return_value=sqlite_result) as sqlite_read,
            patch.object(eve.subprocess, "run") as run_command,
        ):
            result = eve.run_bounded_calendar_read_upcoming(
                {"calendar_read_window_days": 3, "calendar_read_limit": 2},
                source="test",
            )

        sqlite_read.assert_called_once()
        run_command.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertEqual(1, result["event_count"])
        self.assertEqual("calendar_sqlite", result["metadata"]["backend"])
        self.assertIn("local Calendar cache", result["response"])

    def test_calendar_read_chat_response_uses_action_tree_and_boundary(self):
        fake_result = {
            "execution_id": "exec-calendar-read",
            "execution_tree_status": "SUCCESS",
            "execution_verification_ok": True,
            "executed": True,
            "summary": "Calendar read-only preview completed; 1 upcoming event metadata row(s).",
            "ok": True,
            "event_count": 1,
            "scope": eve.CALENDAR_READ_UPCOMING_SCOPE,
            "title_redaction": True,
        }
        with patch.object(eve, "run_operational_action_tree", return_value=fake_result) as action_tree:
            result = eve.calendar_read_upcoming_request_response("What is on my calendar today?", {})

        action_tree.assert_called_once_with(eve.CALENDAR_READ_UPCOMING_ACTION, {}, source="chat_calendar")
        self.assertIsNotNone(result)
        response = str(result["response"])
        self.assertIn(f"ACTION_ATTEMPTED: {eve.CALENDAR_READ_UPCOMING_ACTION}", response)
        self.assertIn("redacted event titles", response)
        self.assertIn("did not create, edit, delete", response)

    def test_calendar_create_request_is_separate_bounded_write_action(self):
        prompt = "Create a calendar event called Focus Block on 2026-04-27 at 9:30 AM for 45 minutes."

        self.assertTrue(eve.requests_calendar_create_event(prompt))
        self.assertEqual(
            eve.CALENDAR_CREATE_EVENT_ACTION,
            eve.classify_supported_reply_commitment("I will create that Calendar event now."),
        )
        request = eve.calendar_create_event_request_from_text(prompt)
        self.assertTrue(request["complete"])
        self.assertEqual("Focus Block", request["title"])
        self.assertEqual("2026-04-27T09:30:00", request["start_iso"])
        self.assertEqual(45, request["duration_minutes"])
        self.assertTrue(request["time_explicit"])
        self.assertTrue(request["duration_explicit"])

    def test_calendar_create_request_requires_explicit_time_and_duration(self):
        prompt = "Create a calendar event called Focus Block on 2026-04-27."

        request = eve.calendar_create_event_request_from_text(prompt)

        self.assertFalse(request["complete"])
        self.assertIn("time", eve.calendar_create_event_missing_fields(request))
        self.assertIn("duration", eve.calendar_create_event_missing_fields(request))

    def test_calendar_create_event_contract_enforces_no_invites_scope(self):
        validated, issues = eve.validate_calendar_create_event_result_contract(
            {
                "executed": True,
                "ok": True,
                "summary": "Calendar event creation completed.",
                "response": "I created one local Calendar event.",
                "event_created": True,
                "event_title": "Focus Block",
                "event_uid": "uid-1",
                "start_iso": "2026-04-27T09:30:00",
                "end_iso": "2026-04-27T10:15:00",
                "duration_minutes": 45,
                "calendar": "Work",
                "scope": eve.CALENDAR_CREATE_EVENT_SCOPE,
                "invites_sent": False,
                "metadata": {"source": "test"},
            }
        )

        self.assertEqual([], issues)
        self.assertTrue(validated["typed_contract"]["valid"])
        self.assertEqual(eve.CALENDAR_CREATE_EVENT_SCOPE, validated["scope"])
        self.assertFalse(validated["invites_sent"])

    def test_run_bounded_calendar_create_event_creates_one_event_without_invites(self):
        completed = subprocess.CompletedProcess(
            ["/usr/bin/osascript", "-e", "script"],
            returncode=0,
            stdout="uid-1 | Focus Block\n",
            stderr="",
        )
        with (
            patch.object(eve.sys, "platform", "darwin"),
            patch.object(eve, "local_app_bundle_path", return_value="/System/Applications/Calendar.app"),
            patch.object(eve.Path, "exists", return_value=True),
            patch.object(eve.subprocess, "run", return_value=completed) as run_command,
        ):
            result = eve.run_bounded_calendar_create_event(
                {
                    "calendar_create_event_request": {
                        "title": "Focus Block",
                        "date": "2026-04-27",
                        "hour": 9,
                        "minute": 30,
                        "duration_minutes": 45,
                    }
                },
                source="test",
            )

        run_command.assert_called_once()
        self.assertTrue(result["ok"])
        self.assertTrue(result["event_created"])
        self.assertEqual(eve.CALENDAR_CREATE_EVENT_SCOPE, result["scope"])
        self.assertFalse(result["invites_sent"])
        self.assertIn("created exactly one event", result["response"])

    def test_calendar_create_chat_response_previews_before_write_without_confirmation(self):
        prompt = "Create a calendar event called Focus Block on 2026-04-27 at 9:30 AM for 45 minutes."

        with patch.object(eve, "run_operational_action_tree") as action_tree:
            result = eve.calendar_create_event_request_response(prompt, {})

        action_tree.assert_not_called()
        self.assertIsNotNone(result)
        self.assertEqual(eve.CALENDAR_CREATE_EVENT_PREVIEW_ACTION, result["action"])
        response = str(result["response"])
        self.assertIn(f"ACTION_ATTEMPTED: {eve.CALENDAR_CREATE_EVENT_PREVIEW_ACTION}", response)
        self.assertIn("No Calendar event was created", response)
        self.assertIn("title=Focus Block", response)
        self.assertIn("start=2026-04-27T09:30:00", response)
        self.assertIn("duration_minutes=45", response)
        self.assertIn("confirm create calendar event called Focus Block", response)
        self.assertIn("did not create, edit, delete, invite, or send anything", response)
        self.assertTrue(result["calendar_create_event_pending_preview"]["request"]["complete"])

    def test_calendar_create_pending_confirmation_reuses_latest_preview(self):
        request = eve.calendar_create_event_request_from_text(
            "Create a calendar event called Focus Block on 2026-04-27 at 9:30 AM for 45 minutes."
        )
        pending = eve.calendar_create_event_pending_preview_payload(request, source="test")
        fake_result = {
            "execution_id": "exec-calendar-create",
            "execution_tree_status": "SUCCESS",
            "execution_verification_ok": True,
            "executed": True,
            "summary": "Calendar event creation completed; title=Focus Block.",
            "ok": True,
            "event_created": True,
            "scope": eve.CALENDAR_CREATE_EVENT_SCOPE,
            "invites_sent": False,
        }

        with (
            patch.object(eve, "latest_pending_calendar_create_preview_from_entries", return_value=pending),
            patch.object(eve, "run_operational_action_tree", return_value=fake_result) as action_tree,
        ):
            result = eve.calendar_create_event_pending_confirmation_response("yes create it", {})

        action_tree.assert_called_once()
        self.assertEqual(eve.CALENDAR_CREATE_EVENT_ACTION, action_tree.call_args.args[0])
        self.assertEqual("chat_calendar_pending", action_tree.call_args.kwargs["source"])
        self.assertIsNotNone(result)
        self.assertEqual(eve.CALENDAR_CREATE_EVENT_ACTION, result["action"])
        self.assertIn("PENDING_PREVIEW_USED", result["response"])
        self.assertEqual("Focus Block", result["calendar_create_event_request"]["title"])

    def test_calendar_create_pending_preview_from_thread_blocks_after_create(self):
        request = eve.calendar_create_event_request_from_text(
            "Create a calendar event called Focus Block on 2026-04-27 at 9:30 AM for 45 minutes."
        )
        pending = eve.calendar_create_event_pending_preview_payload(request, source="test", thread_id="thread-1")
        messages = [
            {
                "id": "preview-message",
                "thread_id": "thread-1",
                "sender": "eve",
                "body": "Preview only.",
                "metadata": {
                    "action": eve.CALENDAR_CREATE_EVENT_PREVIEW_ACTION,
                    "calendar_create_event_pending_preview": pending,
                },
            }
        ]

        found = eve.latest_pending_calendar_create_preview_from_messages(messages)
        self.assertEqual("Focus Block", found["request"]["title"])
        self.assertTrue(eve.should_execute_pending_calendar_create_confirmation("yes create it", found))

        messages.append(
            {
                "id": "created-message",
                "thread_id": "thread-1",
                "sender": "eve",
                "body": "Created.",
                "metadata": {
                    "action": eve.CALENDAR_CREATE_EVENT_ACTION,
                    "event_created": True,
                },
            }
        )
        self.assertEqual({}, eve.latest_pending_calendar_create_preview_from_messages(messages))

    def test_calendar_create_pending_preview_can_be_cancelled(self):
        request = eve.calendar_create_event_request_from_text(
            "Create a calendar event called Focus Block on 2026-04-27 at 9:30 AM for 45 minutes."
        )
        pending = eve.calendar_create_event_pending_preview_payload(request, source="test")

        with patch.object(eve, "latest_pending_calendar_create_preview_from_entries", return_value=pending):
            result = eve.calendar_create_event_preview_cancel_response("cancel the pending calendar")

        self.assertIsNotNone(result)
        self.assertEqual(eve.CALENDAR_CREATE_EVENT_PREVIEW_CANCEL_ACTION, result["action"])
        self.assertIn("CANCELLED_PREVIEW", result["response"])
        self.assertIn("did not create, edit, delete, invite, or send anything", result["response"])

        messages = [
            {
                "id": "preview-message",
                "thread_id": "thread-1",
                "sender": "eve",
                "body": "Preview only.",
                "metadata": {
                    "action": eve.CALENDAR_CREATE_EVENT_PREVIEW_ACTION,
                    "calendar_create_event_pending_preview": pending,
                },
            },
            {
                "id": "cancel-message",
                "thread_id": "thread-1",
                "sender": "eve",
                "body": "Cancelled.",
                "metadata": {"action": eve.CALENDAR_CREATE_EVENT_PREVIEW_CANCEL_ACTION},
            },
        ]
        self.assertEqual({}, eve.latest_pending_calendar_create_preview_from_messages(messages))

    def test_calendar_create_chat_response_uses_action_tree_after_confirmation(self):
        fake_result = {
            "execution_id": "exec-calendar-create",
            "execution_tree_status": "SUCCESS",
            "execution_verification_ok": True,
            "executed": True,
            "summary": "Calendar event creation completed; title=Focus Block.",
            "ok": True,
            "event_created": True,
            "scope": eve.CALENDAR_CREATE_EVENT_SCOPE,
            "invites_sent": False,
        }
        prompt = "Confirm create a calendar event called Focus Block on 2026-04-27 at 9:30 AM for 45 minutes."
        with patch.object(eve, "run_operational_action_tree", return_value=fake_result) as action_tree:
            result = eve.calendar_create_event_request_response(prompt, {})

        action_tree.assert_called_once()
        self.assertEqual(eve.CALENDAR_CREATE_EVENT_ACTION, action_tree.call_args.args[0])
        self.assertEqual("chat_calendar", action_tree.call_args.kwargs["source"])
        self.assertIsNotNone(result)
        response = str(result["response"])
        self.assertIn(f"ACTION_ATTEMPTED: {eve.CALENDAR_CREATE_EVENT_ACTION}", response)
        self.assertIn("created exactly one local Calendar event", response)
        self.assertIn("did not invite anyone", response)

    def test_open_slack_chat_response_runs_bounded_action(self):
        fake_result = {
            "execution_id": "exec-1",
            "execution_tree_status": "SUCCESS",
            "execution_verification_ok": True,
            "summary": "Slack is open; open_exit=0; was_running=no.",
            "app_name": "Slack",
            "ok": True,
            "process_running": True,
        }
        with patch.object(eve, "run_operational_action_tree", return_value=fake_result) as action_tree:
            result = eve.open_slack_app_response("Open Slack on my computer.", {})

        action_tree.assert_called_once_with("open_slack_app", {}, source="chat_local_app")
        self.assertIsNotNone(result)
        response = str(result["response"])
        self.assertIn("ACTION_ATTEMPTED: open_slack_app", response)
        self.assertIn("I did not read Slack messages", response)

    def test_open_slack_chat_response_does_not_claim_success_without_verification(self):
        fake_result = {
            "execution_id": "exec-unverified",
            "execution_tree_status": "SUCCESS",
            "execution_verification_ok": False,
            "summary": "Slack open command returned, but process verification did not complete.",
            "app_name": "Slack",
            "ok": True,
            "process_running": True,
        }
        with patch.object(eve, "run_operational_action_tree", return_value=fake_result):
            result = eve.open_slack_app_response("Open Slack on my computer.", {})

        response = str(result["response"])
        self.assertIn("ACTION_ATTEMPTED: open_slack_app", response)
        self.assertIn("verification_ok=no", response)
        self.assertIn("I only attempted to open Slack", response)
        self.assertNotIn("BOUNDARY: I opened Slack only", response)

    def test_open_slack_request_accepts_screenshot_phrase(self):
        self.assertTrue(eve.requests_open_slack_app("Can you open the app slack on my computer"))

    def test_open_local_app_contract_validates_open_only_scope(self):
        validated, issues = eve.validate_open_local_app_result_contract(
            {
                "executed": True,
                "ok": True,
                "summary": "Slack is open; open_exit=0; was_running=no.",
                "response": "I opened Slack.",
                "app_name": "Slack",
                "bundle_path": "/Applications/Slack.app",
                "process_running": True,
                "scope": "open_app_only_no_messages",
                "metadata": {"source": "test"},
            }
        )

        self.assertEqual([], issues)
        self.assertTrue(validated["typed_contract"]["valid"])
        self.assertEqual("open_app_only_no_messages", validated["scope"])

    def test_open_local_app_contract_allows_private_content_boundary_scope(self):
        validated, issues = eve.validate_open_local_app_result_contract(
            {
                "executed": True,
                "ok": True,
                "summary": "Calendar is open; open_exit=0; was_running=no.",
                "response": "I opened Calendar.",
                "app_name": "Calendar",
                "bundle_path": "/System/Applications/Calendar.app",
                "process_running": True,
                "scope": "open_app_only_no_private_content",
                "metadata": {"source": "test"},
            }
        )

        self.assertEqual([], issues)
        self.assertTrue(validated["typed_contract"]["valid"])
        self.assertEqual("open_app_only_no_private_content", validated["scope"])

    def test_operational_action_input_contract_blocks_incomplete_calendar_create(self):
        normalized, contract = eve.validate_operational_action_input_contract(
            eve.CALENDAR_CREATE_EVENT_ACTION,
            {"calendar_create_event_request": {"title": "Focus Block", "date": "2026-04-27"}},
            source="test",
        )

        self.assertFalse(contract["valid"])
        self.assertEqual("calendar_create_event_input.v1", contract["schema_id"])
        self.assertFalse(normalized["calendar_create_event_request"]["complete"])
        self.assertIn("calendar_create_event_request", contract["issues"][0]["field"])
        self.assertIn("missing_fields", contract["normalized_fields"]["calendar_create_event_request"])

    def test_operational_action_input_contract_normalizes_calendar_read_bounds(self):
        normalized, contract = eve.validate_operational_action_input_contract(
            eve.CALENDAR_READ_UPCOMING_ACTION,
            {"calendar_read_backend": "auto", "calendar_read_window_days": 90, "calendar_read_limit": 99},
            source="test",
        )

        self.assertTrue(contract["valid"])
        self.assertEqual("calendar_read_upcoming_input.v1", contract["schema_id"])
        self.assertEqual("auto", normalized["calendar_read_backend"])
        self.assertEqual(31, normalized["calendar_read_window_days"])
        self.assertEqual(20, normalized["calendar_read_limit"])

    def test_open_local_app_precondition_blocks_missing_app(self):
        with patch.object(eve.sys, "platform", "darwin"), patch.object(eve, "local_app_bundle_path", return_value=""):
            ok, message = eve.operational_action_precondition("open_slack_app", {})

        self.assertFalse(ok)
        self.assertIn("not installed", message)

    def test_action_tree_blocks_invalid_calendar_create_before_tool_action(self):
        with (
            patch.object(eve, "record_operational_action_execution", side_effect=lambda record: record) as record_action,
            patch.object(eve, "run_direct_operational_action") as run_direct,
        ):
            result = eve.run_operational_action_tree(
                eve.CALENDAR_CREATE_EVENT_ACTION,
                {"calendar_create_event_request": {"title": "Focus Block", "date": "2026-04-27"}},
                source="chat_calendar",
            )

        self.assertTrue(result["blocked"])
        self.assertTrue(result["blocked_by_input_contract"])
        self.assertFalse(result["executed"])
        self.assertEqual("BLOCKED", result["execution_tree_status"])
        self.assertFalse(result["execution_input_contract_ok"])
        self.assertFalse(result["input_contract"]["valid"])
        run_direct.assert_not_called()
        record_action.assert_called_once()
        self.assertFalse(record_action.call_args.args[0]["input_contract_ok"])

    def test_autonomy_cannot_open_local_app_without_current_directive(self):
        with (
            patch.object(eve, "record_operational_action_execution", side_effect=lambda record: record) as record_action,
            patch.object(eve, "run_direct_operational_action") as run_direct,
        ):
            result = eve.run_operational_action_tree("open_slack_app", {}, source="autonomy_free_run:test")

        self.assertTrue(result["blocked"])
        self.assertFalse(result["executed"])
        self.assertEqual("BLOCKED", result["execution_tree_status"])
        self.assertEqual("local_app_control", result["freedom_policy"]["privacy_tier"])
        self.assertTrue(result["execution_input_contract_ok"])
        run_direct.assert_not_called()
        record_action.assert_called_once()

    def test_monitor_reply_path_runs_open_slack_action(self):
        inbound = {
            "id": "msg-1",
            "thread_id": "thread-1",
            "subject": "Conversation",
            "body": "Can you open the app slack on my computer",
        }
        fake_result = {
            "execution_id": "exec-1",
            "execution_tree_status": "SUCCESS",
            "execution_verification_ok": True,
            "summary": "Slack is open; open_exit=0; was_running=no.",
            "app_name": "Slack",
            "ok": True,
            "process_running": True,
        }

        def fake_create_message(**kwargs):
            return {"id": "reply-1", **kwargs}

        with (
            patch.object(eve, "ensure_version_snapshot"),
            patch.object(eve, "resolve_model", return_value="eve-fast"),
            patch.object(eve, "start_reply_progress", return_value={"id": "progress-1"}),
            patch.object(eve, "update_reply_progress"),
            patch.object(eve, "read_messages", return_value=[inbound]),
            patch.object(eve, "run_operational_action_tree", return_value=fake_result) as action_tree,
            patch.object(eve, "record_evidence", return_value={"id": "evidence-1"}),
            patch.object(eve, "record_experience_event", return_value={"id": "experience-1"}),
            patch.object(eve, "record_commitment", return_value={"id": "commitment-1"}),
            patch.object(eve, "append_entry"),
            patch.object(eve, "create_message", side_effect=fake_create_message) as create_message,
        ):
            reply = eve.generate_eve_reply({"recent_context_limit": 8}, inbound)

        action_tree.assert_called_once_with("open_slack_app", {"recent_context_limit": 8}, source="reply_commitment")
        create_message.assert_called_once()
        self.assertEqual("reply-1", reply["id"])
        self.assertIn("I opened Slack", reply["body"])
        self.assertEqual(1, reply["metadata"]["tool_call_count"])
        self.assertEqual(["open_slack_app"], reply["metadata"]["tools_used"])
        self.assertTrue(reply["metadata"]["commitment_executed"])
        self.assertTrue(reply["metadata"]["commitment_ok"])

    def test_monitor_reply_path_runs_open_calendar_action(self):
        inbound = {
            "id": "msg-calendar",
            "thread_id": "thread-1",
            "subject": "Conversation",
            "body": "Can you open the app calendar on my computer",
        }
        fake_result = {
            "execution_id": "exec-calendar",
            "execution_tree_status": "SUCCESS",
            "execution_verification_ok": True,
            "summary": "Calendar is open; open_exit=0; was_running=no.",
            "app_name": "Calendar",
            "ok": True,
            "process_running": True,
        }

        with (
            patch.object(eve, "ensure_version_snapshot"),
            patch.object(eve, "resolve_model", return_value="eve-fast"),
            patch.object(eve, "start_reply_progress", return_value={"id": "progress-calendar"}),
            patch.object(eve, "update_reply_progress"),
            patch.object(eve, "read_messages", return_value=[inbound]),
            patch.object(eve, "run_operational_action_tree", return_value=fake_result) as action_tree,
            patch.object(eve, "record_evidence", return_value={"id": "evidence-calendar"}),
            patch.object(eve, "record_experience_event", return_value={"id": "experience-calendar"}),
            patch.object(eve, "record_commitment", return_value={"id": "commitment-calendar"}),
            patch.object(eve, "append_entry"),
            patch.object(eve, "create_message", side_effect=lambda **kwargs: {"id": "reply-calendar", **kwargs}),
        ):
            reply = eve.generate_eve_reply({"recent_context_limit": 8}, inbound)

        action_tree.assert_called_once_with("open_calendar_app", {"recent_context_limit": 8}, source="reply_commitment")
        self.assertIn("I opened Calendar", reply["body"])
        self.assertIn("I did not read calendar events", reply["body"])
        self.assertEqual("open_calendar_app", reply["metadata"]["commitment_action"])

    def test_reply_commitment_executes_verified_calendar_read_when_allowed(self):
        fake_result = {
            "execution_id": "exec-calendar-read",
            "execution_tree_status": "SUCCESS",
            "execution_verification_ok": True,
            "executed": True,
            "summary": "Calendar read-only preview completed; 1 upcoming event metadata row(s).",
            "ok": True,
            "event_count": 1,
            "scope": eve.CALENDAR_READ_UPCOMING_SCOPE,
            "title_redaction": True,
        }

        with (
            patch.object(eve, "run_operational_action_tree", return_value=fake_result) as action_tree,
            patch.object(eve, "record_evidence", return_value={"id": "evidence-calendar-read"}),
            patch.object(eve, "record_experience_event", return_value={"id": "experience-calendar-read"}),
            patch.object(eve, "record_commitment", return_value={"id": "commitment-calendar-read"}),
            patch.object(eve, "append_entry"),
        ):
            result = eve.execute_supported_reply_commitment(
                {},
                "I will check your Calendar now.",
                source="reply",
                inbound_body="What is on my calendar today?",
            )

        action_tree.assert_called_once_with(eve.CALENDAR_READ_UPCOMING_ACTION, {}, source="reply_commitment")
        self.assertTrue(result["executed"])
        self.assertTrue(result["ok"])
        self.assertEqual(eve.CALENDAR_READ_UPCOMING_ACTION, result["action"])
        self.assertIn("redacted titles", result["response"])

    def test_reply_commitment_previews_calendar_create_until_confirmed(self):
        with (
            patch.object(eve, "run_operational_action_tree") as action_tree,
            patch.object(eve, "record_evidence", return_value={"id": "evidence-calendar-create-preview"}),
            patch.object(eve, "record_experience_event", return_value={"id": "experience-calendar-create-preview"}),
            patch.object(eve, "record_commitment", return_value={"id": "commitment-calendar-create-preview"}),
            patch.object(eve, "append_entry"),
        ):
            result = eve.execute_supported_reply_commitment(
                {},
                "I will create that Calendar event now.",
                source="reply",
                inbound_body="Create a calendar event called Focus Block on 2026-04-27 at 9:30 AM for 45 minutes.",
            )

        action_tree.assert_not_called()
        self.assertEqual(eve.CALENDAR_CREATE_EVENT_PREVIEW_ACTION, result["action"])
        self.assertFalse(result["executed"])
        self.assertFalse(result["event_created"])
        self.assertIn("No Calendar event was created", result["response"])
        self.assertIn("CONFIRMATION_REQUIRED", result["response"])
        self.assertTrue(result["calendar_create_event_pending_preview"]["request"]["complete"])

    def test_reply_commitment_executes_verified_calendar_create_when_confirmed(self):
        fake_result = {
            "execution_id": "exec-calendar-create",
            "execution_tree_status": "SUCCESS",
            "execution_verification_ok": True,
            "executed": True,
            "summary": "Calendar event creation completed; title=Focus Block.",
            "ok": True,
            "event_created": True,
            "scope": eve.CALENDAR_CREATE_EVENT_SCOPE,
            "invites_sent": False,
        }

        with (
            patch.object(eve, "run_operational_action_tree", return_value=fake_result) as action_tree,
            patch.object(eve, "record_evidence", return_value={"id": "evidence-calendar-create"}),
            patch.object(eve, "record_experience_event", return_value={"id": "experience-calendar-create"}),
            patch.object(eve, "record_commitment", return_value={"id": "commitment-calendar-create"}),
            patch.object(eve, "append_entry"),
        ):
            result = eve.execute_supported_reply_commitment(
                {},
                "I will create that Calendar event now.",
                source="reply",
                inbound_body="Confirm create a calendar event called Focus Block on 2026-04-27 at 9:30 AM for 45 minutes.",
            )

        action_tree.assert_called_once()
        self.assertEqual(eve.CALENDAR_CREATE_EVENT_ACTION, action_tree.call_args.args[0])
        self.assertEqual(eve.CALENDAR_CREATE_EVENT_ACTION, result["action"])
        self.assertTrue(result["executed"])
        self.assertTrue(result["ok"])
        self.assertIn("did not invite anyone", result["response"])

    def test_monitor_followup_open_it_uses_prior_slack_context(self):
        inbound = {
            "id": "msg-2",
            "thread_id": "thread-1",
            "subject": "Conversation",
            "body": "you open it",
        }
        thread_messages = [
            {"id": "msg-1", "sender": "user", "body": "Can you open the app slack on my computer"},
            {"id": "reply-old", "sender": "eve", "body": "Would you like me to open Slack?"},
            inbound,
        ]
        fake_result = {
            "execution_id": "exec-2",
            "execution_tree_status": "SUCCESS",
            "execution_verification_ok": True,
            "summary": "Slack is open; open_exit=0; was_running=yes.",
            "app_name": "Slack",
            "ok": True,
            "process_running": True,
        }

        with (
            patch.object(eve, "ensure_version_snapshot"),
            patch.object(eve, "resolve_model", return_value="eve-fast"),
            patch.object(eve, "start_reply_progress", return_value={"id": "progress-2"}),
            patch.object(eve, "update_reply_progress"),
            patch.object(eve, "read_messages", return_value=thread_messages),
            patch.object(eve, "run_operational_action_tree", return_value=fake_result) as action_tree,
            patch.object(eve, "record_evidence", return_value={"id": "evidence-2"}),
            patch.object(eve, "record_experience_event", return_value={"id": "experience-2"}),
            patch.object(eve, "record_commitment", return_value={"id": "commitment-2"}),
            patch.object(eve, "append_entry"),
            patch.object(eve, "create_message", side_effect=lambda **kwargs: {"id": "reply-2", **kwargs}),
        ):
            reply = eve.generate_eve_reply({"recent_context_limit": 8}, inbound)

        action_tree.assert_called_once_with("open_slack_app", {"recent_context_limit": 8}, source="reply_commitment")
        self.assertIn("I opened Slack", reply["body"])
        self.assertEqual("open_slack_app", reply["metadata"]["commitment_action"])

    def test_slack_open_claim_requires_current_turn_action(self):
        corrected = eve.ground_generated_action_claims(
            "Okay, I’ve opened Slack for you. It’s now running.",
            source="test",
            completed_actions={"open_slack_app"},
            current_turn_actions=set(),
        )

        self.assertIn("Grounding correction", corrected)
        self.assertNotIn("opened Slack for you", corrected)
        self.assertIn("earlier action log is stale", corrected)

    def test_indirect_slack_status_claim_is_replaced_not_appended(self):
        corrected = eve.ground_generated_action_claims(
            "Slack is open; I handled it this turn.",
            source="test",
            completed_actions={"open_slack_app"},
            current_turn_actions=set(),
        )

        self.assertEqual(
            "Grounding correction: I should not say Slack or the app is open, running, or handled this turn "
            "unless this reply completed a fresh `open_slack_app` action. An earlier action log is stale "
            "evidence for the current turn.",
            corrected,
        )

    def test_recent_completed_actions_ignore_unverified_bypassed_action(self):
        with patch.object(
            eve,
            "read_action_executions",
            return_value=[
                {
                    "id": "action-1",
                    "action": "open_slack_app",
                    "tree_status": "BYPASSED",
                    "verification_ok": False,
                    "result_ok": True,
                    "created_at": eve.utc_now(),
                    "summary": "Bypassed action should not count as completed.",
                }
            ],
        ):
            completed = eve.recent_completed_action_names(since_minutes=30)

        self.assertNotIn("open_slack_app", completed)

    def test_reply_commitment_open_slack_requires_verified_execution(self):
        fake_result = {
            "execution_id": "exec-unverified",
            "execution_tree_status": "SUCCESS",
            "execution_verification_ok": False,
            "summary": "Slack open command returned, but process verification did not complete.",
            "app_name": "Slack",
            "ok": True,
            "process_running": True,
        }

        with (
            patch.object(eve, "run_operational_action_tree", return_value=fake_result),
            patch.object(eve, "record_evidence", return_value={"id": "evidence-1"}),
            patch.object(eve, "record_experience_event", return_value={"id": "event-1"}),
            patch.object(eve, "record_commitment", return_value={"id": "commitment-1"}),
            patch.object(eve, "append_entry"),
        ):
            result = eve.execute_supported_reply_commitment(
                {},
                "I will open Slack now.",
                source="test",
                inbound_body="Open Slack on my computer.",
            )

        self.assertTrue(result["executed"])
        self.assertFalse(result["ok"])
        self.assertFalse(result["completion_verified"])
        self.assertIn("I tried to open Slack", result["response"])
        self.assertNotIn("I opened Slack on this Mac", result["response"])


if __name__ == "__main__":
    unittest.main()
