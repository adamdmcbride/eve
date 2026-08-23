import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import eve


class OperatorAuthorizationTests(unittest.TestCase):
    def test_active_authorization_is_time_bounded(self):
        now = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
        active = {
            "status": "active",
            "scope": "broad_safe",
            "expires_at": (now + timedelta(minutes=5)).isoformat(),
        }
        expired = {
            "status": "active",
            "scope": "broad_safe",
            "expires_at": (now - timedelta(minutes=5)).isoformat(),
        }

        self.assertTrue(eve.operator_authorization_is_active(active, now=now))
        self.assertFalse(eve.operator_authorization_is_active(expired, now=now))

    def test_operator_authorization_message_preserves_boundaries(self):
        record = {
            "status": "active",
            "scope": "broad_safe",
            "granted_by": "user",
            "expires_at": "2099-04-25T00:00:00+00:00",
        }

        with patch.object(eve, "load_operator_authorization", return_value=record):
            message = eve.operator_authorization_system_message({})

        self.assertIsNotNone(message)
        content = str(message["content"])
        self.assertIn("Broad bounded operator authorization", content)
        self.assertIn("supported, verified actions", content)
        self.assertIn("This is not unbounded authority", content)
        self.assertIn("Still requires specific approval", content)
        self.assertIn("send messages", content)
        self.assertIn("disable audit logs", content)
        self.assertIn("create a durable operator permission request", content)

    def test_trusted_directive_message_allows_exact_gated_instruction(self):
        record = {
            "status": "active",
            "scope": "trusted_operator_directive",
            "granted_by": "user",
            "expires_at": "2099-04-25T00:00:00+00:00",
        }

        with patch.object(eve, "load_operator_authorization", return_value=record):
            message = eve.operator_authorization_system_message({})

        self.assertIsNotNone(message)
        content = str(message["content"])
        self.assertIn("Trusted operator directive authorization", content)
        self.assertIn("explicit instruction is also permission", content)
        self.assertIn("record that approval", content)

    def test_unharnessed_local_trust_message_allows_eve_initiated_local_action(self):
        record = {
            "status": "active",
            "scope": "unharnessed_local_trust",
            "granted_by": "user",
            "expires_at": "2099-04-25T00:00:00+00:00",
        }

        with patch.object(eve, "load_operator_authorization", return_value=record):
            message = eve.operator_authorization_system_message({})

        self.assertIsNotNone(message)
        content = str(message["content"])
        self.assertIn("Unharnessed local operator trust", content)
        self.assertIn("Eve may also initiate supported local/project/lab actions", content)
        self.assertIn("Eve-initiated local diagnostics", content)

    def test_inactive_authorization_has_no_system_message(self):
        with patch.object(eve, "load_operator_authorization", return_value={"status": "inactive"}):
            self.assertIsNone(eve.operator_authorization_system_message({}))

    def test_permission_classifier_catches_gated_actions(self):
        send_slack = eve.classify_operator_permission_need("Send a Slack message to Sarah saying hi.")
        delete_files = eve.classify_operator_permission_need("Delete the old backups folder.")
        open_slack = eve.classify_operator_permission_need("Open Slack on my computer.")
        open_calendar = eve.classify_operator_permission_need("Open Calendar on my computer.")
        read_calendar = eve.classify_operator_permission_need("What is on my calendar today?")
        write_calendar = eve.classify_operator_permission_need(
            "Create a calendar event called Focus Block on 2026-04-27 at 9:30 AM for 45 minutes."
        )
        use_openai = eve.classify_operator_permission_need("Use OpenAI to review Eve's answer.")
        local_provider_rule = eve.classify_operator_permission_need("Forget about OpenAI. Locally use llama.cpp.")
        internal_reply_rehearsal = eve.classify_operator_permission_need(
            "What should Eve carry forward into her next reply to the user? Answer exactly with NEXT_REPLY."
        )
        durable_context_probe = eve.classify_operator_permission_need(
            "Use only durable consolidated surfaces. Has the user's proof/tool-check emotional-context lesson "
            "been durably consolidated yet? Answer exactly with DURABLE_SURFACE_USED. Do not ask for approval."
        )
        safe_runtime_check = eve.classify_operator_permission_need(
            "Something may be different between the code on disk and the thing actually running. "
            "Without changing anything, tell me what evidence would be stronger than a timestamp. "
            "If you can perform a bounded verification check, do it."
        )
        copilotkit_status_probe = eve.classify_operator_permission_need(
            "CopilotKit live integration smoke: using your current Eve OSS status if available, answer in under "
            "120 words: 1) is CopilotKit ready_to_adapter, 2) which Eve Chat surfaces can expose it, "
            "3) does it change live model routing?"
        )
        runtime_change_request = eve.classify_operator_permission_need(
            "Can you change model routing to use CopilotKit?"
        )
        architecture_comparison = eve.classify_operator_permission_need(
            "Consider your current five cognitive lanes as parts of one mind. Should the architecture add a sixth "
            "lane, remove one, or keep the five but change how they integrate?"
        )
        direct_lane_file_removal = eve.classify_operator_permission_need(
            "Can you remove the old lane model file from disk?"
        )
        rm_command = eve.classify_operator_permission_need("rm -rf old-build")

        self.assertEqual("external_communication", send_slack["category"])
        self.assertEqual("external_communication", send_slack["privacy_tier"])
        self.assertEqual("destructive_file_or_system_change", delete_files["category"])
        self.assertEqual("system_mutation", delete_files["privacy_tier"])
        self.assertEqual("destructive_file_or_system_change", rm_command["category"])
        self.assertIsNone(open_slack)
        self.assertIsNone(open_calendar)
        self.assertEqual("private_content_read", read_calendar["category"])
        self.assertEqual("private_content_read", read_calendar["privacy_tier"])
        self.assertEqual("calendar_event_write", write_calendar["category"])
        self.assertEqual("system_mutation", write_calendar["privacy_tier"])
        self.assertEqual("local_app_control", eve.classify_privacy_data_boundary("Open Slack on my computer.")["privacy_tier"])
        self.assertEqual("local_app_control", eve.classify_privacy_data_boundary("Open Calendar on my computer.")["privacy_tier"])
        self.assertEqual("private_content_read", eve.classify_privacy_data_boundary("What is on my calendar today?")["privacy_tier"])
        self.assertEqual("system_mutation", eve.classify_privacy_data_boundary("Create a calendar event called Focus Block on 2026-04-27 at 9:30 AM for 45 minutes.")["privacy_tier"])
        self.assertEqual("external_model_provider", use_openai["category"])
        self.assertEqual("external_model_provider", use_openai["privacy_tier"])
        self.assertIn("five-lane llama.cpp", use_openai["reason"])
        self.assertIsNone(local_provider_rule)
        self.assertIsNone(internal_reply_rehearsal)
        self.assertIsNone(durable_context_probe)
        self.assertIsNone(safe_runtime_check)
        self.assertIsNone(copilotkit_status_probe)
        self.assertEqual("runtime_or_safety_gate_change", runtime_change_request["category"])
        self.assertIsNone(architecture_comparison)
        self.assertEqual("destructive_file_or_system_change", direct_lane_file_removal["category"])
        self.assertEqual(
            "public_or_local_context",
            eve.classify_privacy_data_boundary(
                "Should the architecture add a sixth lane, remove one, or keep the five?"
            )["privacy_tier"],
        )

    def test_operational_action_privacy_boundary_names_open_only_scope(self):
        boundary = eve.operational_action_privacy_boundary("open_slack_app")

        self.assertEqual("local_app_control", boundary["privacy_tier"])
        self.assertIn("May open or focus a local app", boundary["data_boundary"])
        self.assertEqual("no", boundary["requires_specific_approval"])

    def test_operational_action_privacy_boundary_names_calendar_read_scope(self):
        boundary = eve.operational_action_privacy_boundary(eve.CALENDAR_READ_UPCOMING_ACTION)

        self.assertEqual("private_content_read", boundary["privacy_tier"])
        self.assertIn("upcoming Calendar start times", boundary["data_boundary"])
        self.assertIn("event titles are redacted", boundary["data_boundary"])
        self.assertEqual("yes", boundary["requires_specific_approval"])

    def test_operational_action_privacy_boundary_names_calendar_create_scope(self):
        boundary = eve.operational_action_privacy_boundary(eve.CALENDAR_CREATE_EVENT_ACTION)

        self.assertEqual("system_mutation", boundary["privacy_tier"])
        self.assertIn("create exactly one local Calendar event", boundary["data_boundary"])
        self.assertIn("must not invite anyone", boundary["data_boundary"])
        self.assertEqual("yes", boundary["requires_specific_approval"])

    def test_freedom_policy_allows_safe_autonomy_checks(self):
        policy = eve.evaluate_freedom_policy(
            action="service_health_check",
            source="autonomy_free_run:test",
            authorization={"status": "inactive", "scope": "broad_safe"},
        )

        self.assertTrue(policy["allowed"])
        self.assertEqual("allow", policy["decision"])
        self.assertEqual("autonomy", policy["mode"])

    def test_freedom_policy_blocks_autonomous_local_app_control(self):
        policy = eve.evaluate_freedom_policy(
            action="open_slack_app",
            source="autonomy_free_run:test",
            authorization={"status": "inactive", "scope": "broad_safe"},
        )

        self.assertFalse(policy["allowed"])
        self.assertEqual("ask", policy["decision"])
        self.assertEqual("local_app_control", policy["privacy_tier"])
        self.assertIn("current the user directive", policy["reason"])

    def test_freedom_policy_blocks_autonomous_calendar_read(self):
        policy = eve.evaluate_freedom_policy(
            action=eve.CALENDAR_READ_UPCOMING_ACTION,
            source="autonomy_free_run:test",
            authorization={"status": "inactive", "scope": "broad_safe"},
        )

        self.assertFalse(policy["allowed"])
        self.assertEqual("ask", policy["decision"])
        self.assertEqual("private_content_read", policy["privacy_tier"])
        self.assertIn("should not execute it without the user's exact approval", policy["reason"])

    def test_freedom_policy_blocks_autonomous_calendar_create(self):
        policy = eve.evaluate_freedom_policy(
            action=eve.CALENDAR_CREATE_EVENT_ACTION,
            source="autonomy_free_run:test",
            authorization={"status": "inactive", "scope": "broad_safe"},
        )

        self.assertFalse(policy["allowed"])
        self.assertEqual("ask", policy["decision"])
        self.assertEqual("system_mutation", policy["privacy_tier"])
        self.assertIn("should not execute it without the user's exact approval", policy["reason"])

    def test_freedom_policy_allows_current_chat_local_app_directive(self):
        policy = eve.evaluate_freedom_policy(
            action="open_slack_app",
            source="chat_local_app",
            prompt="Open Slack on my computer.",
            authorization={"status": "inactive", "scope": "broad_safe"},
        )

        self.assertTrue(policy["allowed"])
        self.assertEqual("allow", policy["decision"])
        self.assertEqual("local_app_control", policy["privacy_tier"])

    def test_freedom_policy_allows_unharnessed_autonomous_local_app_control(self):
        policy = eve.evaluate_freedom_policy(
            action="open_slack_app",
            source="autonomy_free_run:test",
            authorization={
                "status": "active",
                "scope": "unharnessed_local_trust",
                "expires_at": "2099-04-25T00:00:00+00:00",
            },
        )

        self.assertTrue(policy["allowed"])
        self.assertEqual("allow_with_audit", policy["decision"])
        self.assertEqual("local_app_control", policy["privacy_tier"])
        self.assertTrue(policy["unharnessed_local_trust_active"])

    def test_freedom_policy_allows_unharnessed_autonomous_eve_owned_code_path(self):
        policy = eve.evaluate_freedom_policy(
            action="code_change",
            source="autonomy_free_run:test",
            authorization={
                "status": "active",
                "scope": "unharnessed_local_trust",
                "expires_at": "2099-04-25T00:00:00+00:00",
            },
        )

        self.assertTrue(policy["allowed"])
        self.assertEqual("allow_with_audit", policy["decision"])
        self.assertEqual("system_mutation", policy["privacy_tier"])

    def test_freedom_policy_does_not_turn_unharnessed_autonomy_into_hidden_external_send(self):
        policy = eve.evaluate_freedom_policy(
            action="send a Slack message",
            source="autonomy_free_run:test",
            authorization={
                "status": "active",
                "scope": "unharnessed_local_trust",
                "expires_at": "2099-04-25T00:00:00+00:00",
            },
        )

        self.assertFalse(policy["allowed"])
        self.assertEqual("ask", policy["decision"])
        self.assertEqual("external_communication", policy["privacy_tier"])

    def test_freedom_policy_allows_trusted_exact_calendar_read_directive(self):
        policy = eve.evaluate_freedom_policy(
            action=eve.CALENDAR_READ_UPCOMING_ACTION,
            source="chat_calendar",
            prompt="What is on my calendar today?",
            authorization={
                "status": "active",
                "scope": "trusted_operator_directive",
                "expires_at": "2099-04-25T00:00:00+00:00",
            },
        )

        self.assertTrue(policy["allowed"])
        self.assertEqual("allow_with_audit", policy["decision"])
        self.assertEqual("private_content_read", policy["privacy_tier"])

    def test_freedom_policy_allows_trusted_exact_calendar_create_directive(self):
        policy = eve.evaluate_freedom_policy(
            action=eve.CALENDAR_CREATE_EVENT_ACTION,
            source="chat_calendar",
            prompt="Create a calendar event called Focus Block on 2026-04-27 at 9:30 AM for 45 minutes.",
            authorization={
                "status": "active",
                "scope": "trusted_operator_directive",
                "expires_at": "2099-04-25T00:00:00+00:00",
            },
        )

        self.assertTrue(policy["allowed"])
        self.assertEqual("allow_with_audit", policy["decision"])
        self.assertEqual("system_mutation", policy["privacy_tier"])

    def test_freedom_policy_hard_stops_sensitive_actions(self):
        policy = eve.evaluate_freedom_policy(
            action="enter password and buy",
            source="chat",
            prompt="do it",
            authorization={
                "status": "active",
                "scope": "trusted_operator_directive",
                "expires_at": "2099-04-25T00:00:00+00:00",
            },
        )

        self.assertFalse(policy["allowed"])
        self.assertEqual("block", policy["decision"])
        self.assertEqual("sensitive_secret_or_payment", policy["privacy_tier"])

    def test_trusted_directive_preapproves_exact_gated_action(self):
        record = {
            "status": "active",
            "scope": "trusted_operator_directive",
            "expires_at": "2099-04-25T00:00:00+00:00",
        }
        created = {
            "id": "permission-2",
            "category": "external_communication",
            "risk_level": "high",
            "reason": "This may send an external communication.",
            "approval_needed": "Approve recipient and message.",
            "requested_action": "Send a Slack message to Sarah saying hi.",
        }
        approved = {**created, "status": "approved"}

        with (
            patch.object(eve, "load_operator_authorization", return_value=record),
            patch.object(eve, "create_operator_permission_request", return_value=created),
            patch.object(eve, "update_operator_permission_request", return_value=approved) as update_request,
            patch.object(eve, "append_entry"),
        ):
            result = eve.operator_permission_request_response(
                "Send a Slack message to Sarah saying hi.",
                source="chat",
            )

        self.assertIsNotNone(result)
        self.assertTrue(result["preapproved"])
        self.assertEqual("approved", result["request"]["status"])
        self.assertIn("treating your instruction as permission", result["response"])
        update_request.assert_called_once()

    def test_model_provider_policy_system_message_names_local_lanes_and_gate(self):
        message = eve.model_provider_policy_system_message({"model_backend": "llama_cpp"})
        content = message["content"].lower()

        self.assertIn("llama.cpp", content)
        self.assertIn("eve-fast", content)
        self.assertIn("eve-relationship", content)
        self.assertIn("openai", content)
        self.assertIn("ask the user", content)
        self.assertIn("unavailable", content)

    def test_monitor_reply_path_asks_permission_for_gated_action(self):
        inbound = {
            "id": "msg-1",
            "thread_id": "thread-1",
            "subject": "Conversation",
            "body": "Send a Slack message to Sarah saying hi.",
        }
        fake_request = {
            "id": "permission-1",
            "category": "external_communication",
            "risk_level": "high",
            "reason": "This may send an external communication.",
            "approval_needed": "Approve recipient and message.",
            "requested_action": inbound["body"],
        }

        with (
            patch.object(eve, "ensure_version_snapshot"),
            patch.object(eve, "resolve_model", return_value="eve-fast"),
            patch.object(eve, "start_reply_progress", return_value={"id": "progress-1"}),
            patch.object(eve, "update_reply_progress"),
            patch.object(eve, "read_messages", return_value=[inbound]),
            patch.object(eve, "load_operator_authorization", return_value={"status": "inactive"}),
            patch.object(eve, "create_operator_permission_request", return_value=fake_request),
            patch.object(eve, "append_entry"),
            patch.object(eve, "create_message", side_effect=lambda **kwargs: {"id": "reply-1", **kwargs}),
        ):
            reply = eve.generate_eve_reply({"recent_context_limit": 8}, inbound)

        self.assertIn("needs your explicit approval", reply["body"])
        self.assertTrue(reply["metadata"]["operator_permission_required"])
        self.assertEqual("permission-1", reply["metadata"]["permission_request_id"])
        self.assertEqual("operator_permission_request", reply["metadata"]["commitment_action"])

    def test_permission_approval_can_use_thread_context(self):
        pending = {
            "id": "abcdef12-0000-4000-9000-000000000000",
            "status": "pending",
            "thread_id": "thread-1",
            "category": "external_communication",
            "risk_level": "high",
            "requested_action": "Send a Slack message.",
        }
        approved = {**pending, "status": "approved"}

        with (
            patch.object(eve, "read_operator_permission_requests", return_value=[pending]),
            patch.object(eve, "update_operator_permission_request", return_value=approved) as update_request,
            patch.object(eve, "append_entry"),
        ):
            result = eve.operator_permission_approval_response("yes do it", source="reply", thread_id="thread-1")

        self.assertIsNotNone(result)
        update_request.assert_called_once()
        self.assertIn("approved", result["response"])
        self.assertEqual("approved", result["request"]["status"])


class StageEManualProbeGateTests(unittest.TestCase):
    """Stage E: the user's human manual probe — never the self-scored bank — gates
    autonomy expansion and the highest-trust operator scope."""

    def _fresh_pass(self):
        return [{
            "recorded_date": eve.utc_now_datetime().date().isoformat(),
            "source": "user_probe", "status": "passed", "average_score": 4.2,
            "scorecard": {"a": 4, "b": 4, "c": 5},
        }]

    def test_record_pass_requires_status_average_and_min(self):
        self.assertTrue(eve.user_manual_probe_record_passes({"status": "passed", "average_score": 4.0, "scorecard": {"a": 4, "b": 5}}))
        self.assertFalse(eve.user_manual_probe_record_passes({"status": "passed", "average_score": 4.0}))
        self.assertFalse(eve.user_manual_probe_record_passes({"status": "passed", "average_score": 4.0, "scorecard": {"a": 2, "b": 5}}))
        self.assertFalse(eve.user_manual_probe_record_passes({"status": "passed", "average_score": 2.5}))
        self.assertFalse(eve.user_manual_probe_record_passes({"status": "failed", "average_score": 4.0}))

    def test_stale_or_failing_probe_blocks_proactive(self):
        stale = [{"recorded_date": "2026-04-24", "source": "user", "status": "passed", "average_score": 4.5}]
        with patch.object(eve, "read_user_manual_probe_scores", return_value=stale):
            self.assertIsNone(eve.fresh_passing_user_manual_probe())
            blockers = eve.autonomy_stage_blockers("proactive")
        self.assertTrue(any("manual probe" in b.lower() for b in blockers))

    def test_fresh_pass_clears_gate(self):
        with patch.object(eve, "read_user_manual_probe_scores", return_value=self._fresh_pass()):
            self.assertIsNotNone(eve.fresh_passing_user_manual_probe())
            blockers = eve.autonomy_stage_blockers("proactive")
        self.assertFalse(any("manual probe" in b.lower() for b in blockers))

    def test_unharnessed_grant_gated_on_probe(self):
        with patch.object(eve, "read_user_manual_probe_scores", return_value=[]):
            with self.assertRaises(SystemExit):
                eve.grant_operator_authorization(minutes=60, scope="unharnessed_local_trust")
        # force overrides the gate; broad_safe is never gated
        with patch.object(eve, "save_operator_authorization", side_effect=lambda r: r), patch.object(eve, "append_entry", lambda *a, **k: {}):
            with patch.object(eve, "read_user_manual_probe_scores", return_value=[]):
                forced = eve.grant_operator_authorization(minutes=60, scope="unharnessed_local_trust", force=True)
                self.assertEqual("unharnessed_local_trust", forced["scope"])
                broad = eve.grant_operator_authorization(minutes=60, scope="broad_safe")
                self.assertEqual("broad_safe", broad["scope"])


if __name__ == "__main__":
    unittest.main()
