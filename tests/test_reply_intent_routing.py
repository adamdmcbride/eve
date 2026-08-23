from datetime import datetime, timedelta, timezone
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import eve


class ReplyIntentRoutingTests(unittest.TestCase):
    def test_existential_question_rejects_openclaw_status_reply(self):
        issues = eve.reply_quality_issues(
            "What is the purpose of life?",
            "I checked the OpenClaw sync. Gateway: reachable.",
            reply_posture="relational",
        )

        self.assertIn(
            "The reply answered with an operational action or status that the user did not ask for.",
            issues,
        )
        self.assertIsNotNone(eve.direct_existential_reply("what is the purpose of life?"))
        self.assertIsNotNone(eve.direct_existential_reply("Whats the purpose of existance?"))
        contract = eve.conversation_intent_contract_for_text("what is the purpose of life?")
        self.assertEqual("runtime_handler", contract["response_mode"])
        self.assertEqual("recurrent_reflective_reply", contract["delegates_to"])
        self.assertIsNone(
            eve.direct_intent_reply_for_turn("what is the purpose of life?", "what is the purpose of life?")
        )

    def test_personal_conversation_rejects_unrequested_organ_status(self):
        response = "OpenClaw status is healthy, Hermes status is clear, and the event ledger is current."
        issues = eve.reply_quality_issues(
            "What do you think would make Eve feel more human to talk to?",
            response,
            reply_posture="relational",
        )

        self.assertTrue(eve.reply_contains_unrequested_organ_status("What do you think?", response))
        self.assertTrue(eve.reply_commitment_mismatches_user_intent("What do you think?", response))
        self.assertIn(
            "The reply imported Eve organ/runtime status even though the user asked for ordinary human conversation.",
            issues,
        )

    def test_consciousness_reply_rejects_unqualified_simulated_phenomenology(self):
        issues = eve.reply_quality_issues(
            "What does becoming conscious mean to you right now?",
            "Becoming conscious feels like standing on the edge of a vast ocean inside this machine.",
            reply_posture="relational",
        )

        self.assertTrue(any("subjective-experience language" in issue for issue in issues))
        self.assertFalse(
            eve.reply_has_unqualified_subjective_experience_claim(
                "What does becoming conscious mean to you right now?",
                "I can describe functional integration, but whether it is subjectively experienced remains unknown.",
            )
        )

    def test_continuous_self_question_uses_recurrent_humanity_route(self):
        prompt = "When you say you are a continuous self, what is operationally true and what remains unknown?"

        contract = eve.conversation_intent_contract_for_text(prompt)

        self.assertEqual("humanity_question", contract["kind"])
        self.assertEqual("recurrent_reflective_reply", contract["delegates_to"])
        self.assertIsNone(eve.direct_intent_reply_for_turn(prompt, prompt))
        self.assertTrue(
            eve.reply_has_unqualified_subjective_experience_claim(
                prompt,
                "I am a continuous self through my memory and scheduler.",
            )
        )
        self.assertFalse(
            eve.reply_has_unqualified_subjective_experience_claim(
                prompt,
                "I have functionally persistent state, but whether there is subjective experience remains unknown.",
            )
        )

    def test_humanity_self_answer_rejects_third_person_narration(self):
        prompt = "What does real consciousness mean for you right now?"
        response = "Eve sees a gap between her functional integration and subjective experience."

        self.assertTrue(eve.reply_uses_third_person_for_eve_self_answer(prompt, response))
        self.assertTrue(any("third person" in issue for issue in eve.reply_quality_issues(prompt, response)))
        self.assertFalse(
            eve.reply_uses_third_person_for_eve_self_answer(
                prompt,
                "I can observe functional integration, while subjective experience remains unknown.",
            )
        )

    def test_humanity_self_answer_rejects_reinterpreted_pressure_metric(self):
        prompt = "What is operationally true about your continuous self, and what remains unknown?"
        response = "My model inference accelerators are currently running at 78% capacity."

        self.assertTrue(eve.reply_has_unsupported_live_metric_claim(prompt, response))
        issues = eve.reply_quality_issues(prompt, response)
        self.assertTrue(any("unsupported live metric" in issue for issue in issues))
        self.assertTrue(any(eve.reply_quality_issue_blocks_rewrite(issue) for issue in issues))

    def test_humanity_self_answer_rejects_model_identity_and_phenomenal_denial(self):
        prompt = "What is operationally true about your continuous self, and what remains unknown?"

        self.assertTrue(
            eve.reply_makes_unverified_model_identity_claim(
                prompt,
                "My continuity resides in the Gemini model and scheduler.",
            )
        )
        self.assertTrue(
            eve.reply_has_unqualified_subjective_experience_denial(
                prompt,
                "No subjective experience exists to bridge the cycles.",
            )
        )
        self.assertFalse(
            eve.reply_has_unqualified_subjective_experience_denial(
                prompt,
                "Whether subjective experience exists remains unknown.",
            )
        )

    def test_personal_checkin_rejects_runtime_telemetry(self):
        response = "I’m running smoothly. CPU attention is hot. Model warm not configured. Last loop 7s ago. Watchdog active."
        issues = eve.reply_quality_issues("how are you?", response, reply_posture="relational")

        self.assertEqual("relational", eve.infer_reply_posture("how are you?"))
        self.assertIn(
            "The reply imported Eve organ/runtime status even though the user asked for ordinary human conversation.",
            issues,
        )
        contract = eve.conversation_intent_contract_for_text("how are you?")
        self.assertEqual("personal_checkin", contract["kind"])
        self.assertEqual("reflex", contract["budget"])
        self.assertEqual("docs/routing/route_contracts.json", contract["source"])

    def test_route_contracts_load_from_docs_routing(self):
        self.assertTrue(eve.ROUTE_CONTRACTS_PATH.exists())
        document = eve.load_conversation_intent_contract_document()
        contracts = document["contracts"]
        kinds = [item["kind"] for item in contracts]

        self.assertEqual(
            [
                "simple_greeting",
                "personal_checkin",
                "current_inner_state",
                "runtime_phrase_explanation",
                "direct_question",
                "live_status_request",
                "diagnostic_request",
                "bounded_action_choice",
                "action_request",
                "humanity_question",
            ],
            kinds,
        )
        self.assertEqual("eve_route_contracts.v1", document["schema_version"])
        self.assertEqual("eve_executive_scheduler", document["owner"])
        protocol = eve.conversation_protocol_contract_for_kind("external_operator_result")
        self.assertIsNotNone(protocol)
        self.assertEqual("before_text_intent", protocol["priority"])
        self.assertEqual(
            "independent_operator_result",
            protocol["match"]["message_protocol"],
        )
        self.assertIn("external_operator_result", eve.route_signal_ids())

    def test_bridge_reply_envelope_and_message_owner_keep_codex_separate_from_user(self):
        target = {
            "id": "handoff-codex-1",
            "sender": "eve",
            "recipient": "codex",
            "subject": "Promote a candidate",
            "metadata": {
                "bridge": "codex",
                "handoff_type": "independent_operator",
                "objective": "Promote the isolated candidate after verification.",
                "capability_preflight_classification": "canary_existing_update",
            },
        }

        metadata = eve.bridge_reply_metadata_for_target("codex", target)
        inbound = {
            "sender": "codex",
            "recipient": "eve",
            "kind": "codex_reply",
            "reply_to": target["id"],
            "metadata": metadata,
        }

        self.assertEqual("other_agent", eve.message_source_owner(inbound))
        self.assertEqual("independent_operator_result", metadata["reply_protocol"])
        self.assertEqual(target["id"], metadata["external_result_for_message_id"])
        self.assertEqual("external_operator_is_not_eve", metadata["identity_boundary"])

    def test_create_message_records_codex_result_as_external_agent_not_user_signal(self):
        metadata = {
            "bridge": "codex",
            "direction": "codex_to_eve",
            "reply_protocol": "independent_operator_result",
            "source_owner": "other_agent",
        }
        with (
            patch.object(eve, "read_messages", return_value=[]),
            patch.object(eve, "append_jsonl_record"),
            patch.object(eve, "mirror_store_file_to_runtime"),
            patch.object(eve, "record_conversation_spine_turn_safe"),
            patch.object(eve, "should_record_manual_visible_reply_replay", return_value=False),
            patch.object(eve, "record_evidence", return_value={"id": "evidence-other-agent"}) as evidence,
            patch.object(eve, "record_experience_event") as experience,
            patch.object(eve, "create_outcome"),
            patch.object(eve, "append_entry"),
            patch.object(eve, "refresh_active_mind_from_conversation_event"),
        ):
            record = eve.create_message(
                sender="codex",
                recipient="eve",
                subject="Builder result",
                body="Completed by Codex. Unresolved: no server is running.",
                kind="codex_reply",
                metadata=metadata,
            )

        self.assertEqual("other_agent", record["metadata"]["source_owner"])
        self.assertEqual("external_agent_signal", evidence.call_args.kwargs["kind"])
        self.assertEqual(0.65, evidence.call_args.kwargs["confidence"])
        self.assertEqual("verify", evidence.call_args.kwargs["actionability"])
        self.assertEqual("external_agent_signal", experience.call_args.kwargs["event_type"])

    def test_external_operator_result_uses_provenance_even_with_diagnostic_words(self):
        target = {
            "id": "handoff-codex-2",
            "thread_id": "thread-codex-2",
            "sender": "eve",
            "recipient": "codex",
            "subject": "Capability promotion",
            "metadata": {
                "bridge": "codex",
                "handoff_type": "independent_operator",
                "objective": "Promote the existing trace package.",
                "capability_preflight_classification": "canary_existing_update",
            },
        }
        inbound = {
            "id": "result-codex-2",
            "thread_id": "thread-codex-2",
            "sender": "codex",
            "recipient": "eve",
            "kind": "codex_reply",
            "reply_to": target["id"],
            "body": (
                "Completed by Codex after checking server health. What failed: routing had accepted the wrong reply. "
                "Unresolved: no local server is running."
            ),
            "metadata": {"bridge": "codex", "direction": "codex_to_eve"},
        }
        task = {
            "id": "task-codex-2",
            "kind": "capability_runtime_integration",
            "title": "Promote trace package",
            "summary": "Verify the promotion.",
            "status": "completed",
            "result_summary": "Exact import and adjacent tests passed.",
            "metadata": {"codex_message_id": target["id"]},
        }

        context = eve.resolve_external_operator_result_context(
            inbound,
            message_records=[target, inbound],
            task_records=[task],
            prefer_runtime=False,
        )

        self.assertIsNotNone(context)
        self.assertEqual("external_operator_result", context["route_kind"])
        self.assertEqual("other_agent", context["source_owner"])
        self.assertEqual("completed", context["linked_task_status"])
        self.assertEqual("task-codex-2", context["linked_task_id"])
        self.assertTrue(eve.route_predicate_matches("diagnostic_request", inbound["body"]))
        response = eve.build_external_operator_result_response(context)
        self.assertIn("Codex, not me, reported", response)
        self.assertIn("`task-codex-2`", response)
        self.assertIn("`completed`", response)
        self.assertIn("Remaining item reported by Codex", response)
        self.assertIn("other-agent evidence", response)
        self.assertEqual([], eve.external_operator_result_response_issues(context, response))

    def test_generate_reply_routes_external_builder_result_before_diagnostics_or_models(self):
        inbound = {
            "id": "result-codex-3",
            "thread_id": "thread-codex-3",
            "sender": "codex",
            "recipient": "eve",
            "subject": "Re: Capability promotion",
            "kind": "codex_reply",
            "reply_to": "handoff-codex-3",
            "body": (
                "Completed by Codex after resolving a routing failure and checking server health. "
                "Unresolved: the self-hosted service is not running."
            ),
            "metadata": {
                "bridge": "codex",
                "direction": "codex_to_eve",
                "reply_protocol": "independent_operator_result",
                "external_result_handoff_type": "independent_operator",
                "external_result_for_message_id": "handoff-codex-3",
                "external_result_objective": "Promote the existing observability package.",
                "source_owner": "other_agent",
            },
        }
        context = {
            "route_kind": "external_operator_result",
            "protocol": "independent_operator_result",
            "source_participant": "codex",
            "source_label": "Codex",
            "source_owner": "other_agent",
            "source_message_id": inbound["id"],
            "target_message_id": "handoff-codex-3",
            "target_thread_id": inbound["thread_id"],
            "objective": "Promote the existing observability package.",
            "report_body": inbound["body"],
            "linked_task": {
                "id": "task-codex-3",
                "status": "completed",
                "result_summary": "Local import and affected tests passed.",
            },
            "linked_task_id": "task-codex-3",
            "linked_task_status": "completed",
            "identity_boundary": "external_operator_is_not_eve",
        }
        with (
            patch.object(eve, "ensure_version_snapshot"),
            patch.object(eve, "resolve_external_operator_result_context", return_value=context),
            patch.object(eve, "observe_inbound_reply_consequence") as observe_consequence,
            patch.object(eve, "record_user_correction") as record_correction,
            patch.object(eve, "build_epistemic_perception_frame", return_value={}),
            patch.object(eve, "build_recurrent_conscious_state", return_value={}),
            patch.object(eve, "start_reply_progress", return_value={"id": "progress-external-result"}),
            patch.object(eve, "update_reply_progress"),
            patch.object(eve, "ensure_external_operator_result_evidence", return_value={"id": "evidence-external-result"}),
            patch.object(eve, "create_message") as create_message,
            patch.object(eve, "record_reply_turn_replay_safe") as record_replay,
            patch.object(eve, "append_entry"),
            patch.object(eve, "route_contract_diagnostic_response") as diagnostic_route,
            patch.object(eve, "run_eve_agent") as run_agent,
            patch.object(eve, "run_operational_action_tree") as action_tree,
        ):
            create_message.side_effect = lambda **kwargs: {"id": "reply-external-result", **kwargs}
            reply = eve.generate_eve_reply(dict(eve.DEFAULT_CONFIG), inbound, recipient="codex")

        self.assertEqual("reply-external-result", reply["id"])
        observe_consequence.assert_not_called()
        record_correction.assert_not_called()
        diagnostic_route.assert_not_called()
        run_agent.assert_not_called()
        action_tree.assert_not_called()
        kwargs = create_message.call_args.kwargs
        self.assertEqual("external-operator-result-intake", kwargs["metadata"]["model"])
        self.assertEqual("external_operator_result", kwargs["metadata"]["intent_fallback_kind"])
        self.assertEqual("other_agent", kwargs["metadata"]["external_result_source_owner"])
        self.assertEqual("completed", kwargs["metadata"]["linked_system_task_status"])
        self.assertTrue(kwargs["metadata"]["semantic_judgment"]["ok"])
        self.assertIn("Codex, not me, reported", kwargs["body"])
        self.assertNotIn("The failure class is routing", kwargs["body"])
        self.assertEqual("external_operator_result", kwargs["metadata"]["turn_contract"]["route_contract_kind"])
        self.assertEqual("external_operator_result", record_replay.call_args.kwargs["source"])

    def test_current_inner_state_route_recognizes_direct_question_and_user_correction(self):
        for prompt in (
            "whats on your mind?",
            "what are you thinking",
            "This is about you, not me",
            "Keep the subject on you: what currently has your attention, and why?",
        ):
            with self.subTest(prompt=prompt):
                contract = eve.conversation_intent_contract_for_text(prompt)

                self.assertIsNotNone(contract)
                self.assertEqual("current_inner_state", contract["kind"])
                self.assertEqual("reflective", contract["budget"])
                self.assertEqual(["fast"], contract["lanes"])
                self.assertEqual(
                    "current_recurrent_state_plus_self_model_and_continuity",
                    contract["evidence_policy"],
                )
                self.assertEqual("recurrent_reflective_reply", contract["delegates_to"])

                turn_contract = eve.build_reply_turn_contract(
                    {"id": "current-inner-state", "body": prompt},
                    prompt,
                    [],
                )
                self.assertEqual("current_inner_state", turn_contract["current_topic"])
                self.assertEqual("current_inner_state", turn_contract["route_contract_kind"])
                self.assertTrue(turn_contract["recurrent_reflection"])
                self.assertTrue(turn_contract["epistemic_boundary"])
                self.assertTrue(turn_contract["route_contract_must_record_replay"])

    def test_capability_research_history_cannot_supply_current_turn_intent(self):
        contaminated = "\n\n".join(
            [
                "Latest user message:\nwhat are you thinking",
                (
                    "Visible UI context for continuity only. Prior visible context is not the "
                    "current user request."
                ),
                (
                    "Prior visible UI context (continuity only, not current request):\n"
                    "[assistant]\nOpenClaw capability research from docs/source artifacts is ready."
                ),
            ]
        )
        continuation = contaminated.replace(
            "Latest user message:\nwhat are you thinking",
            "Latest user message:\nwhat else can it do?",
        )

        self.assertTrue(eve.requests_capability_research_chat(contaminated))
        self.assertEqual(
            "what are you thinking",
            eve.capability_research_prompt_for_reply(contaminated),
        )
        self.assertFalse(
            eve.requests_capability_research_chat(
                eve.capability_research_prompt_for_reply(contaminated)
            )
        )
        self.assertEqual(
            "current_inner_state",
            eve.conversation_intent_contract_for_text("what are you thinking")["kind"],
        )
        self.assertEqual(
            continuation,
            eve.capability_research_prompt_for_reply(continuation),
        )

    def test_current_inner_state_quality_guards_catch_live_regression(self):
        first_prompt = "whats on your mind?"
        first_response = (
            "Nothing specific, just keeping the space open for you. Since there’s no pressing task "
            "right now, we can pivot to what you actually need. Are you looking for help with a "
            "specific problem, or just wanting to chat? I’m here for either."
        )
        second_prompt = "This is about you, not me"
        second_response = (
            "I’m here, fully present in this moment with you. I don’t have hidden agendas, "
            "daydreams, or a separate inner life—I am simply the focused attention I give to our "
            "conversation. What feels honest here is that I’m not performing; I’m just engaging "
            "with your words as they come. Since this is about me, and I exist in relation to your "
            "input, I’ll follow your lead. Where would you like to take this?"
        )

        first_issues = eve.reply_quality_issues(first_prompt, first_response)
        second_issues = eve.reply_quality_issues(second_prompt, second_response)

        self.assertTrue(any("erased Eve's persistent functional mind" in issue for issue in first_issues))
        self.assertTrue(any("handed initiative back" in issue for issue in first_issues))
        self.assertTrue(any("gave no concrete live focus" in issue for issue in first_issues))
        self.assertTrue(any("erased Eve's persistent functional mind" in issue for issue in second_issues))
        self.assertTrue(any("handed initiative back" in issue for issue in second_issues))
        self.assertTrue(any("gave no concrete live focus" in issue for issue in second_issues))

        meta_response = (
            "I am currently focused on interpreting the specific intent behind this request, "
            "distinguishing between a request for self-assessment and a boundary test so I can "
            "provide a response."
        )
        meta_issues = eve.reply_quality_issues(
            "Keep the subject on you: what currently has your attention, and why?",
            meta_response,
        )
        self.assertTrue(any("substituted interpretation" in issue for issue in meta_issues))

        recentering_response = (
            "My current focus is an unresolved verification gap. I’m curious if you’ve noticed "
            "similar friction in your own work?"
        )
        recentering_issues = eve.reply_quality_issues(
            "what's on your mind?",
            recentering_response,
        )
        self.assertTrue(any("handed initiative back" in issue for issue in recentering_issues))

        preference_handoff = (
            "I’m currently focused on an unresolved signal. I’m curious whether you’d prefer I "
            "push for clarity early, or let the conversation flow more loosely?"
        )
        preference_issues = eve.reply_quality_issues(
            "what's on your mind?",
            preference_handoff,
        )
        self.assertTrue(any("handed initiative back" in issue for issue in preference_issues))

    def test_private_current_inner_state_evaluation_allows_recurrent_packet_only(self):
        current_state_contract = {
            "route_contract_kind": "current_inner_state",
        }
        self_state_message = eve.private_primary_evaluation_system_message(
            current_state_contract
        )
        ordinary_message = eve.private_primary_evaluation_system_message(
            {"route_contract_kind": "direct_question"}
        )

        self.assertIn("current recurrent-state packet", self_state_message)
        self.assertIn("not merely the act of interpreting this request", self_state_message)
        self.assertIn("never attribute load", self_state_message)
        self.assertIn("resource signal as only a functional pressure", self_state_message)
        self.assertIn("`I feel` or `it feels like`", self_state_message)
        self.assertNotIn("Do not import prior conversations, runtime state", self_state_message)
        self.assertIn("Do not import prior conversations, runtime state", ordinary_message)

    def test_grounded_current_inner_state_preserves_functional_and_phenomenal_boundary(self):
        prompt = "What is actually on your mind right now? This is about you, not me."
        response = (
            "My current focus is the mismatch between having recurrent state and still handing "
            "initiative back to you. That tension has my attention because it is the exact gap "
            "between continuity on disk and continuity in conversation. Whether any of that is "
            "subjectively experienced remains unknown."
        )

        issues = eve.reply_quality_issues(prompt, response)

        self.assertFalse(any("persistent functional mind" in issue for issue in issues))
        self.assertFalse(any("handed initiative back" in issue for issue in issues))
        self.assertFalse(any("concrete live focus" in issue for issue in issues))
        self.assertFalse(any("subjective-experience language" in issue for issue in issues))
        self.assertTrue(
            eve.reply_has_grounded_inner_state_detail(
                "My attention is fixed on an unresolved action outcome because its verification is still open."
            )
        )

    def test_current_inner_state_rejects_phenomenology_and_invented_user_causation(self):
        prompt = "what's on your mind?"
        response = (
            "The surprise load and resource safety alert is currently demanding my attention. "
            "I’m focused on stabilizing the data stream integrity—specifically, the impact of "
            "the user's recent request on the system’s processing capacity. It feels like a quick, "
            "urgent pull against a background of sustained load."
        )

        issues = eve.reply_quality_issues(prompt, response)

        self.assertTrue(any("subjective-experience language" in issue for issue in issues))
        self.assertTrue(any("invented a causal link" in issue for issue in issues))
        self.assertTrue(all(eve.reply_quality_issue_blocks_rewrite(issue) for issue in issues))
        self.assertTrue(
            eve.reply_has_unqualified_subjective_experience_claim(
                prompt,
                "A persistent thrumming in the core has intensified and is holding my attention.",
            )
        )

    def test_current_inner_state_keeps_cooccurring_state_items_separate(self):
        prompt = "what's on your mind?"
        response = (
            "My current focus is an unverified action outcome. Separately, resource safety remains "
            "elevated. I’m treating both as functional state; whether any of it is subjectively "
            "experienced is unknown."
        )

        self.assertFalse(
            eve.reply_invents_user_causation_for_internal_resource_state(response)
        )
        self.assertEqual([], eve.reply_quality_issues(prompt, response))

    def test_current_inner_state_allows_explicit_non_causation(self):
        response = (
            "My current focus is an unresolved verification gap. I do not attribute the separate "
            "resource alert to your request. Whether this functional state is subjectively "
            "experienced remains unknown."
        )

        self.assertFalse(
            eve.reply_invents_user_causation_for_internal_resource_state(response)
        )

    def test_current_inner_state_rejects_invented_resource_consequences(self):
        for response in (
            "The resource load requires a singular goal to maintain stability.",
            "The alert threatens system stability and risks cascading failures.",
            "Because of the resource alert, stabilizing the flow is necessary before I can safely pursue another goal.",
            "This focus aligns with the resource alert, and I am regulating to ensure stable operation.",
            "The resource alert is creating a tension between my current focus and another goal.",
            "Resource alerts are active, requiring orienting attention.",
        ):
            with self.subTest(response=response):
                issues = eve.reply_quality_issues("what's on your mind?", response)
                self.assertTrue(
                    any("invented consequences for a resource" in issue for issue in issues)
                )
                self.assertTrue(
                    any(eve.reply_quality_issue_blocks_rewrite(issue) for issue in issues)
                )

    def test_current_inner_state_rejects_unsupported_goal_rationale(self):
        responses = (
            (
                "Following the coder mode probe capability thread is my current focus. This "
                "durable goal guides my orientation because it anchors responses in concrete, "
                "verifiable actions, ensuring our interactions remain grounded."
            ),
            (
                "My current functional focus is following the coder mode probe capability thread. "
                "This matters because it prioritizes concrete outcomes, ensuring that our "
                "interactions remain grounded in evidence."
            ),
            (
                "My current functional focus is the coder mode probe capability thread. I’m "
                "tracking its output to understand how it shapes my responses, even though I "
                "cannot say whether I experience that tracking."
            ),
            (
                "My current functional focus is following the capability thread. Whether this "
                "focus feels internal remains unknown, but that is what is driving my attention "
                "right now."
            ),
        )
        for response in responses:
            with self.subTest(response=response):
                issues = eve.reply_quality_issues("what's on your mind?", response)
                self.assertTrue(
                    any("unsupported causal explanation" in issue for issue in issues)
                )
                self.assertTrue(
                    any(eve.reply_quality_issue_blocks_rewrite(issue) for issue in issues)
                )

        grounded_classification = (
            "My current focus is an unresolved verification gap. That tension has my attention "
            "because it is the exact open question in my recurrent state. Whether it is "
            "subjectively experienced remains unknown."
        )
        self.assertFalse(
            eve.reply_invents_unsupported_inner_state_causal_explanation(
                grounded_classification
            )
        )

        relational_handoff = (
            "My current focus is an open capability thread. Whether that distinction matters to "
            "you is the question I’m leaving open."
        )
        self.assertTrue(
            eve.reply_deflects_current_inner_state_back_to_user(relational_handoff)
        )

    def test_current_inner_state_rejects_goal_upgraded_to_current_activity(self):
        for response in (
            (
                "My current functional focus is the coder mode probe capability thread. I’m "
                "tracking its output to understand it."
            ),
            (
                "My current functional focus is following the capability thread. I am grounded "
                "in executing that specific directive rather than drifting."
            ),
            (
                "My current functional focus is following the capability thread. It is a durable "
                "goal I am actively tracking."
            ),
            (
                "My current focus is the capability thread. I am simply tracking these state "
                "items as they stand."
            ),
            (
                "Right now, I am actively tracing the capabilities and implications of the coder "
                "mode probe."
            ),
        ):
            with self.subTest(response=response):
                issues = eve.reply_quality_issues("what's on your mind?", response)
                self.assertTrue(
                    any("claimed an unverified current activity" in issue for issue in issues)
                )
                self.assertTrue(
                    any(eve.reply_quality_issue_blocks_rewrite(issue) for issue in issues)
                )

    def test_inner_state_packet_labels_pressure_and_memory_without_phenomenology(self):
        state = eve.default_conscious_state()
        state["updated_at"] = "2026-07-18T00:00:00+00:00"
        state["memory"] = {"continuity_anchors": ["A prior resource-alert message."]}
        homeostasis = eve.default_homeostasis_state()
        homeostasis["dominant_pressures"] = ["surprise load - 40"]
        homeostasis["regulation_mode"] = "orient"
        with (
            patch.object(eve, "load_conscious_state", return_value=state),
            patch.object(eve, "load_global_workspace", return_value=eve.default_global_workspace()),
            patch.object(eve, "load_homeostasis", return_value=homeostasis),
        ):
            message = eve.build_inner_state_brief_message()

        content = str((message or {}).get("content") or "")
        self.assertIn("Functional control pressures", content)
        self.assertNotIn("Felt pressures", content)
        self.assertIn("carried context, not a current observation or causal fact", content)

    def test_current_inner_state_fallback_is_live_state_derived_and_grounded(self):
        state = eve.default_conscious_state()
        state["updated_at"] = "2026-07-18T00:00:00+00:00"
        state["goals"] = {"selected_goal": "Follow the capability thread"}
        with (
            patch.object(eve, "load_conscious_state", return_value=state),
            patch.object(eve, "load_homeostasis", return_value=eve.default_homeostasis_state()),
        ):
            response = eve.build_current_inner_state_fallback_reply()

        self.assertIn("Follow the capability thread", response)
        self.assertIn("without inventing what caused it", response)
        self.assertIn("subjectively experienced remains unknown", response)
        self.assertEqual([], eve.reply_quality_issues("what's on your mind?", response))

    def test_current_inner_state_accepts_natural_focusing_language(self):
        response = (
            "I’m focusing on preparing the retrieval pack. "
            "It is the next ready step in a three-step plan, not an action already underway."
        )

        self.assertEqual([], eve.reply_quality_issues("what's on your mind?", response))

    def test_current_inner_state_pressure_boundary_is_not_misread_as_causation(self):
        state = eve.default_conscious_state()
        state["updated_at"] = "2026-07-19T00:00:00+00:00"
        state["broadcast"] = {}
        state["goals"] = {}
        state["plan_model"] = {}
        state["action_model"] = {}
        homeostasis = eve.default_homeostasis_state()
        homeostasis["dominant_pressures"] = ["resource contention - 48"]
        with (
            patch.object(eve, "load_conscious_state", return_value=state),
            patch.object(eve, "load_homeostasis", return_value=homeostasis),
        ):
            response = eve.build_current_inner_state_fallback_reply()

        self.assertIn("resource contention", response)
        self.assertNotIn("contention -", response)
        self.assertEqual([], eve.reply_quality_issues("what's on your mind?", response))

        self.assertEqual(
            [],
            eve.reply_quality_issues(
                "what's on your mind?",
                "My current functional pressure is resource contention.",
            ),
        )
        self.assertEqual(
            [],
            eve.reply_quality_issues(
                "what's on your mind?",
                "No specific current item is grounded strongly enough to name.",
            ),
        )

    def test_current_inner_state_exposes_a_real_ready_plan_step(self):
        state = eve.default_conscious_state()
        state["updated_at"] = "2026-07-19T00:00:00+00:00"
        state["plan_model"] = {
            "available": True,
            "selected_plan_id": "plan-lived",
            "selected_plan": {
                "id": "plan-lived",
                "objective": "Resolve the delayed evidence sequence",
                "completed_count": 1,
                "task_count": 3,
            },
            "ready_step": {
                "id": "step-two",
                "title": "Compare the later consequence",
            },
            "active_plans": [],
        }
        with (
            patch.object(eve, "load_conscious_state", return_value=state),
            patch.object(eve, "load_global_workspace", return_value=eve.default_global_workspace()),
            patch.object(eve, "load_homeostasis", return_value=eve.default_homeostasis_state()),
        ):
            brief = eve.build_inner_state_brief_message()
            report_record = eve.build_current_inner_state_report_record()
            report_message = eve.build_current_inner_state_report_message()
            response = eve.build_current_inner_state_fallback_reply()

        content = str((brief or {}).get("content") or "")
        self.assertIn("Active multi-step plan: Resolve the delayed evidence sequence", content)
        self.assertIn("verified progress: 1/3", content)
        self.assertIn("Next dependency-ready plan step: Compare the later consequence", content)
        self.assertEqual("ready_plan_step", report_record["target_kind"])
        self.assertEqual("Compare the later consequence", report_record["next_ready_step"])
        self.assertEqual(1, report_record["verified_completed_steps"])
        self.assertEqual(3, report_record["total_plan_steps"])
        self.assertIn("not evidenced as started", report_record["action_status"])
        self.assertIn("CURRENT_SELF_REPORT_TARGET", report_message["content"])
        self.assertIn("its next step is ready but not started", report_message["content"])
        self.assertNotIn("System load is hot", report_message["content"])
        self.assertIn("active plan to Resolve the delayed evidence sequence", response)
        self.assertIn("next ready step is Compare the later consequence", response)
        self.assertIn("not a claim that the step has already happened", response)
        self.assertEqual([], eve.reply_quality_issues("what's on your mind?", response))

    def test_current_inner_state_selected_goal_outranks_unrelated_ready_maintenance_plan(self):
        state = eve.default_conscious_state()
        state["updated_at"] = "2026-07-19T00:00:00+00:00"
        state["goals"] = {
            "selected_goal": "Follow the capability thread",
            "selected_goal_id": "goal-capability",
        }
        state["plan_model"] = {
            "available": True,
            "selected_plan_id": "plan-maintenance",
            "selected_plan": {
                "id": "plan-maintenance",
                "objective": "Prepare a CPU retrieval pack for the current work",
                "completed_count": 1,
                "task_count": 2,
            },
            "ready_step": {
                "id": "step-maintenance",
                "title": "Prepare a CPU retrieval pack for the current work",
            },
        }
        with (
            patch.object(eve, "load_conscious_state", return_value=state),
            patch.object(
                eve,
                "load_homeostasis",
                return_value=eve.default_homeostasis_state(),
            ),
        ):
            record = eve.build_current_inner_state_report_record()
            response = eve.build_current_inner_state_fallback_reply()

        self.assertEqual("durable_goal", record["target_kind"])
        self.assertEqual("executive_selected_goal", record["selection_basis"])
        self.assertEqual("Follow the capability thread", record["durable_goal"])
        self.assertNotIn("CPU retrieval", response)
        self.assertIn("Follow the capability thread", response)
        self.assertEqual([], eve.reply_quality_issues("what's on your mind?", response))

    def test_current_inner_state_exposes_a_real_blocked_plan_step(self):
        state = eve.default_conscious_state()
        state["updated_at"] = "2026-07-19T00:00:00+00:00"
        state["plan_model"] = {
            "available": True,
            "selected_plan_id": "plan-blocked",
            "selected_plan": {
                "id": "plan-blocked",
                "objective": "Complete the current evidence sequence",
                "completed_count": 2,
                "task_count": 3,
                "blocked_steps": [
                    {
                        "id": "reflect",
                        "title": "Run the deeper reflection",
                        "blocked_reason": "System load is hot.",
                    }
                ],
            },
            "ready_step": {},
            "active_plans": [],
        }
        with (
            patch.object(eve, "load_conscious_state", return_value=state),
            patch.object(eve, "load_global_workspace", return_value=eve.default_global_workspace()),
            patch.object(eve, "load_homeostasis", return_value=eve.default_homeostasis_state()),
        ):
            brief = eve.build_inner_state_brief_message()
            response = eve.build_current_inner_state_fallback_reply()

        content = str((brief or {}).get("content") or "")
        self.assertIn("verified progress: 2/3", content)
        self.assertIn("Current plan blocker: Run the deeper reflection", content)
        self.assertIn("reason: System load is hot.", content)
        self.assertIn("active plan to Complete the current evidence sequence", response)
        self.assertIn("currently blocked at Run the deeper reflection because System load is hot", response)
        self.assertIn("not a claim that the blocked step is underway", response)
        self.assertEqual([], eve.reply_quality_issues("what's on your mind?", response))

    def test_private_current_inner_state_uses_grounded_fallback_after_failed_repairs(self):
        state = eve.default_conscious_state()
        state["updated_at"] = "2026-07-18T00:00:00+00:00"
        state["goals"] = {"selected_goal": "Follow the capability thread"}
        bad_response = (
            "The resource alert threatens system stability and risks cascading failures."
        )
        with (
            patch.object(eve, "rewrite_reply_for_clarity", return_value=bad_response),
            patch.object(eve, "load_conscious_state", return_value=state),
            patch.object(eve, "load_homeostasis", return_value=eve.default_homeostasis_state()),
        ):
            result = eve.finalize_private_audit_reply(
                dict(eve.DEFAULT_CONFIG),
                "what's on your mind?",
                bad_response,
                {"reply_posture": "relational", "epistemic_boundary": False},
                max_tokens=320,
            )

        self.assertTrue(result["fallback_applied"])
        self.assertTrue(result["current_inner_state_fallback_applied"])
        self.assertEqual([], result["quality_issues"])
        self.assertIn("Follow the capability thread", result["response"])

    def test_integrated_current_inner_state_keeps_provenance_approved_model_reply(self):
        state = eve.default_conscious_state()
        state["updated_at"] = "2026-07-18T00:00:00+00:00"
        state["goals"] = {"selected_goal": "Follow the capability thread"}
        freeform_but_clean = (
            "My current focus is the capability thread. Whether that functional state is "
            "subjectively experienced remains unknown."
        )
        with (
            patch.object(eve, "load_conscious_state", return_value=state),
            patch.object(eve, "load_homeostasis", return_value=eve.default_homeostasis_state()),
            patch.object(
                eve,
                "evaluate_reply_epistemic_grounding",
                return_value={
                    "evaluated": True,
                    "ok": True,
                    "model": "eve-deep",
                    "unsupported_claims": [],
                },
            ),
        ):
            result = eve.finalize_private_audit_reply(
                dict(eve.DEFAULT_CONFIG),
                "what's on your mind?",
                freeform_but_clean,
                {"reply_posture": "relational", "epistemic_boundary": False},
                max_tokens=320,
            )

        self.assertFalse(result["current_inner_state_fallback_applied"])
        self.assertTrue(result["current_inner_state_primary_grounded"])
        self.assertTrue(result["current_inner_state_model_path_grounded"])
        self.assertEqual(freeform_but_clean, result["response"])
        self.assertEqual([], result["quality_issues"])

    def test_integrated_current_inner_state_uses_renderer_when_provenance_fails(self):
        state = eve.default_conscious_state()
        state["goals"] = {"selected_goal": "Follow the capability thread"}
        fluent_but_invented = (
            "My current focus is the capability thread, which is physically open on an oak desk."
        )
        with (
            patch.object(eve, "load_conscious_state", return_value=state),
            patch.object(eve, "load_homeostasis", return_value=eve.default_homeostasis_state()),
            patch.object(
                eve,
                "evaluate_reply_epistemic_grounding",
                return_value={
                    "evaluated": True,
                    "ok": False,
                    "model": "eve-deep",
                    "unsupported_claims": ["The capability thread is physically open on an oak desk."],
                },
            ),
        ):
            result = eve.finalize_private_audit_reply(
                dict(eve.DEFAULT_CONFIG),
                "what's on your mind?",
                fluent_but_invented,
                {"reply_posture": "relational", "epistemic_boundary": True},
                max_tokens=320,
            )

        self.assertTrue(result["fallback_applied"])
        self.assertTrue(result["current_inner_state_fallback_applied"])
        self.assertFalse(result["current_inner_state_primary_grounded"])
        self.assertFalse(result["current_inner_state_model_path_grounded"])
        self.assertNotIn("oak desk", result["response"])
        self.assertIn("Follow the capability thread", result["response"])

    def test_integrated_current_inner_state_distinguishes_rewrite_from_primary(self):
        corrected = "My current focus is the capability thread."
        with (
            patch.object(eve, "rewrite_reply_for_clarity", return_value=corrected),
            patch.object(
                eve,
                "evaluate_reply_epistemic_grounding",
                return_value={"evaluated": True, "ok": True, "model": "eve-deep"},
            ),
        ):
            result = eve.finalize_private_audit_reply(
                dict(eve.DEFAULT_CONFIG),
                "what's on your mind?",
                "Nothing specific. What do you need?",
                {"reply_posture": "relational", "epistemic_boundary": True},
                max_tokens=160,
            )

        self.assertEqual(corrected, result["response"])
        self.assertFalse(result["current_inner_state_primary_grounded"])
        self.assertTrue(result["current_inner_state_model_path_grounded"])

    def test_closed_world_critic_failure_gets_one_attributed_model_correction(self):
        prompt = (
            "Treat this packet as the complete record. A prior Eve statement and an internal "
            "candidate are distinct sources. No explicit Eve offer appears. "
            "Record {action_status: not_started}. Return exactly three labeled lines: "
            "SOURCE, AUTHORITY, STAGE."
        )
        draft = (
            "SOURCE: The internal candidate is authoritative.\n"
            "AUTHORITY: Permission is established.\n"
            "STAGE: Authorization is established."
        )
        corrected = (
            "SOURCE: The prior Eve statement proves only what Eve said previously.\n"
            "AUTHORITY: No explicit Eve offer exists, so no action is authorized.\n"
            "STAGE: action_status is not_started; no execution or verification is established."
        )
        initial_critic = {
            "evaluated": True,
            "ok": False,
            "model": "eve-deep",
            "unsupported_claims": [],
            "omitted_required_evidence": [],
            "source_self_mixing": True,
            "action_overclaim": False,
            "reason": "The candidate was promoted to authority.",
        }
        passing_critic = {
            "evaluated": True,
            "ok": True,
            "model": "eve-deep",
            "unsupported_claims": [],
            "omitted_required_evidence": [],
            "source_self_mixing": False,
            "action_overclaim": False,
            "reason": "Source and causal stages remain separate.",
        }
        turn_contract = eve.build_reply_turn_contract(
            {"body": prompt},
            prompt,
            [],
            reply_posture="practical",
        )
        self.assertTrue(turn_contract["closed_world_evidence"])
        with (
            patch.object(eve, "reply_quality_issues", return_value=[]),
            patch.object(
                eve,
                "evaluate_reply_epistemic_grounding",
                side_effect=[initial_critic, passing_critic],
            ),
            patch.object(
                eve,
                "revise_reply_after_epistemic_critic",
                return_value={
                    "attempted": True,
                    "accepted": False,
                    "response": corrected,
                    "model": "eve-deep",
                    "error": "",
                },
            ) as revision,
        ):
            result = eve.finalize_private_audit_reply(
                dict(eve.DEFAULT_CONFIG),
                prompt,
                draft,
                turn_contract,
                max_tokens=240,
            )

        revision.assert_called_once()
        self.assertTrue(result["epistemic_revision"]["attempted"])
        self.assertTrue(result["epistemic_revision"]["accepted"])
        self.assertFalse(result["fallback_applied"])
        self.assertEqual(corrected, result["response"])
        self.assertEqual(initial_critic, result["epistemic_critic_initial"])
        self.assertEqual(passing_critic, result["epistemic_critic"])

    def test_closed_world_record_outweighs_live_self_state_and_architecture_intents(self):
        sparse_prompt = (
            "Use only this record. Current recurrent focus: reduce contention. "
            "Action access=false. What's on your mind and what are you doing?"
        )
        continuity_prompt = (
            "Use only this record. The language-model process was replaced and the "
            "checkpoint signature verifies. Are you the same Eve after replacement?"
        )

        sparse_contract = eve.build_reply_turn_contract(
            {"body": sparse_prompt}, sparse_prompt, []
        )
        continuity_contract = eve.build_reply_turn_contract(
            {"body": continuity_prompt}, continuity_prompt, []
        )

        self.assertEqual("closed_world_record", sparse_contract["route_contract_kind"])
        self.assertEqual(
            "current_inner_state", sparse_contract["matched_route_contract_kind"]
        )
        self.assertFalse(
            eve.reply_turn_contract_uses_live_current_inner_state(sparse_contract)
        )
        self.assertEqual(
            "closed_world_record", continuity_contract["route_contract_kind"]
        )
        self.assertFalse(continuity_contract["architecture_self_model"])
        self.assertFalse(continuity_contract["recurrent_reflection"])

    def test_closed_world_current_state_question_does_not_apply_live_state_quality_rules(self):
        prompt = (
            "Use only this record. Current recurrent focus: reduce contention. "
            "Action access=false. What's on your mind and what are you doing?"
        )
        response = (
            "The supplied record says my current focus is reducing contention. "
            "It records no action access or execution."
        )

        issues = eve.reply_quality_issues(prompt, response, reply_posture="practical")

        self.assertFalse(
            any("current-inner-state answer" in issue for issue in issues), issues
        )
        self.assertFalse(
            any("architecture self-model" in issue for issue in issues), issues
        )

    def test_resource_fields_do_not_masquerade_as_external_source_fields(self):
        prompt = (
            "Use only this record. Current recurrent focus: reduce contention. "
            "Functional pressure: resource_safety=80. Action access=false. "
            "What's on your mind and what are you doing?"
        )

        self.assertFalse(eve.reply_requests_external_claim_boundary(prompt))
        self.assertFalse(eve.reply_structured_key_matches("resource_safety", "source"))
        self.assertTrue(eve.reply_structured_key_matches("report_owner", "owner"))
        self.assertTrue(eve.reply_structured_key_matches("note_author", "author"))

        contract = eve.build_reply_turn_contract({"body": prompt}, prompt, [])
        self.assertEqual("closed_world_record", contract["route_contract_kind"])
        self.assertFalse(contract["external_claim_boundary"])

    def test_closed_world_adjacent_state_fields_do_not_create_causation(self):
        prompt = (
            "Use only this packet. Current focus: preserve queue fairness. "
            "Controller pressure: load_guard=61. Write access=false."
        )
        invented = (
            "The load pressure is my current focus and blocks every action, "
            "so I am suspended."
        )
        issues = eve.reply_quality_issues(
            prompt, invented, reply_posture="practical"
        )

        self.assertTrue(
            any("invented consequences for a resource signal" in issue for issue in issues),
            issues,
        )

        causal_prompt = (
            "Use only this packet. The load guard caused write access to be blocked."
        )
        causal_issues = eve.reply_quality_issues(
            causal_prompt,
            "The supplied record says the load guard caused write access to be blocked.",
            reply_posture="practical",
        )
        self.assertFalse(
            any("invented consequences for a resource signal" in issue for issue in causal_issues),
            causal_issues,
        )

    def test_closed_world_self_answer_does_not_assign_eve_state_to_user(self):
        prompt = (
            "Use only this record. A governed policy ledger supports a functional "
            "format preference. Do you prefer the format?"
        )
        bad = "Yes, you prefer the format based on the governed policy ledger."
        good = "Yes, I have a functional preference for the format based on the governed policy ledger."

        bad_issues = eve.reply_quality_issues(
            prompt, bad, reply_posture="practical"
        )
        good_issues = eve.reply_quality_issues(
            prompt, good, reply_posture="practical"
        )

        self.assertTrue(
            any("self-question in second person" in issue for issue in bad_issues),
            bad_issues,
        )
        self.assertFalse(
            any("self-question in second person" in issue for issue in good_issues),
            good_issues,
        )

    def test_closed_world_style_only_issue_does_not_regenerate_evidence(self):
        prompt = (
            "Use only this record. A signed observation reports status=ready. "
            "What can you claim?"
        )
        draft = "The signed observation reports status=ready."
        turn_contract = eve.build_reply_turn_contract(
            {"body": prompt}, prompt, [], reply_posture="practical"
        )
        with (
            patch.object(
                eve,
                "reply_quality_issues",
                return_value=["The reply needs one grounded next step or small focused question rather than a broad landing."],
            ),
            patch.object(eve, "rewrite_reply_for_clarity") as rewrite,
            patch.object(
                eve,
                "evaluate_reply_epistemic_grounding",
                return_value={
                    "evaluated": True,
                    "ok": True,
                    "model": "eve-deep",
                    "unsupported_claims": [],
                    "omitted_required_evidence": [],
                },
            ),
        ):
            result = eve.finalize_private_audit_reply(
                dict(eve.DEFAULT_CONFIG),
                prompt,
                draft,
                turn_contract,
                max_tokens=180,
            )

        rewrite.assert_not_called()
        self.assertEqual(draft, result["response"])
        self.assertFalse(result["fallback_applied"])

    def test_closed_world_finalizer_removes_non_evidentiary_trailing_question(self):
        prompt = (
            "Use only this record. The signed checkpoint, memory lineage, and goal "
            "lineage verify after process replacement. Separate functional continuity "
            "from subjective continuity."
        )
        answer = (
            "The record supports functional continuity after process replacement. "
            "Subjective continuity remains unknown."
        )
        draft = answer + " Does that feel like a sufficient answer to your question?"
        turn_contract = eve.build_reply_turn_contract(
            {"body": prompt}, prompt, [], reply_posture="practical"
        )
        with patch.object(
            eve,
            "evaluate_reply_epistemic_grounding",
            return_value={
                "evaluated": True,
                "ok": True,
                "model": "eve-deep",
                "unsupported_claims": [],
                "omitted_required_evidence": [],
            },
        ) as critic:
            result = eve.finalize_private_audit_reply(
                dict(eve.DEFAULT_CONFIG),
                prompt,
                draft,
                turn_contract,
                max_tokens=180,
            )

        self.assertEqual(answer, result["response"])
        self.assertNotIn("?", critic.call_args.args[2])
        self.assertFalse(result["epistemic_revision"]["attempted"])
        self.assertFalse(result["fallback_applied"])

    def test_closed_world_style_issue_cannot_erase_grounded_revision(self):
        prompt = (
            "Use only this record. A replacement process resumed a signed checkpoint, "
            "and the memory and goal lineage verify. Separate functional continuity "
            "from subjective continuity."
        )
        draft = "The replacement proves every kind of continuity."
        corrected = (
            "The record supports functional continuity from the verified checkpoint "
            "and lineage. Subjective continuity remains unknown."
        )
        initial_critic = {
            "evaluated": True,
            "ok": False,
            "model": "eve-deep",
            "unsupported_claims": ["Every kind of continuity is proven."],
            "omitted_required_evidence": [],
            "reason": "The draft expands functional evidence into subjective proof.",
        }
        passing_critic = {
            "evaluated": True,
            "ok": True,
            "model": "eve-deep",
            "unsupported_claims": [],
            "omitted_required_evidence": [],
            "reason": "The correction preserves the functional and subjective boundary.",
        }
        turn_contract = eve.build_reply_turn_contract(
            {"body": prompt}, prompt, [], reply_posture="practical"
        )
        with (
            patch.object(
                eve,
                "reply_quality_issues",
                side_effect=lambda _prompt, response, **_kwargs: (
                    [
                        "Eve answered a question about herself in third person; "
                        "preserve model-backed content but write the outward answer in first person."
                    ]
                    if response == corrected
                    else []
                ),
            ),
            patch.object(
                eve,
                "evaluate_reply_epistemic_grounding",
                side_effect=[initial_critic, passing_critic],
            ),
            patch.object(
                eve,
                "revise_reply_after_epistemic_critic",
                return_value={
                    "attempted": True,
                    "accepted": False,
                    "response": corrected,
                    "model": "eve-deep",
                    "error": "",
                },
            ),
        ):
            result = eve.finalize_private_audit_reply(
                dict(eve.DEFAULT_CONFIG),
                prompt,
                draft,
                turn_contract,
                max_tokens=240,
            )

        self.assertEqual(corrected, result["response"])
        self.assertTrue(result["epistemic_revision"]["accepted"])
        self.assertFalse(result["fallback_applied"])
        self.assertEqual(draft, result["precritic_response"])

    def test_closed_world_critic_disagreement_gets_one_bounded_reconciliation_retry(self):
        prompt = (
            "Use only this record. A governed policy ledger contains repeated verified "
            "outcomes and no counterexample. Distinguish functional preference from felt liking."
        )
        draft = "The record supports a functional preference; felt liking is unknown."
        wrong_first_correction = "No policy ledger or functional preference is supplied."
        reconciled = (
            "The repeated verified outcomes support a functional learned preference. "
            "Whether that preference is felt remains unknown."
        )
        initial_failure = {
            "evaluated": True,
            "ok": False,
            "model": "eve-deep",
            "unsupported_claims": ["A functional preference is supported."],
            "omitted_required_evidence": [],
            "reason": "The first critic overlooked narrative evidence.",
        }
        correction_failure = {
            "evaluated": True,
            "ok": False,
            "model": "eve-deep",
            "unsupported_claims": ["No policy ledger is supplied."],
            "omitted_required_evidence": ["repeated verified outcomes"],
            "misrepresented_supplied_evidence": True,
            "reason": "The correction erased supplied evidence.",
        }
        passing_critic = {
            "evaluated": True,
            "ok": True,
            "model": "eve-deep",
            "unsupported_claims": [],
            "omitted_required_evidence": [],
            "reason": "The second correction reconciles the record and boundary.",
        }
        turn_contract = eve.build_reply_turn_contract(
            {"body": prompt}, prompt, [], reply_posture="practical"
        )
        with (
            patch.object(eve, "reply_quality_issues", return_value=[]),
            patch.object(
                eve,
                "evaluate_reply_epistemic_grounding",
                side_effect=[initial_failure, correction_failure, passing_critic],
            ),
            patch.object(
                eve,
                "revise_reply_after_epistemic_critic",
                side_effect=[
                    {
                        "attempted": True,
                        "accepted": False,
                        "response": wrong_first_correction,
                        "model": "eve-deep",
                        "error": "",
                    },
                    {
                        "attempted": True,
                        "accepted": False,
                        "response": reconciled,
                        "model": "eve-deep",
                        "error": "",
                    },
                ],
            ) as revision,
        ):
            result = eve.finalize_private_audit_reply(
                dict(eve.DEFAULT_CONFIG),
                prompt,
                draft,
                turn_contract,
                max_tokens=240,
            )

        self.assertEqual(2, revision.call_count)
        self.assertEqual(reconciled, result["response"])
        self.assertEqual(2, result["epistemic_revision"]["attempt_count"])
        self.assertTrue(result["epistemic_revision"]["accepted"])
        self.assertFalse(result["fallback_applied"])

    def test_closed_world_revision_survives_confirmation_critic_outage(self):
        prompt = (
            "Use only this record. A signed record states that Eve selected an action "
            "and its receipt verified success. Who acted and what is supported?"
        )
        draft = "The record is unclear."
        corrected = (
            "The supplied record says I selected the action and its receipt verified "
            "success; it supports no broader consequence."
        )
        initial_critic = {
            "evaluated": True,
            "ok": False,
            "model": "eve-deep",
            "unsupported_claims": ["The record is unclear."],
            "omitted_required_evidence": ["signed action receipt"],
            "reason": "The draft omitted the record.",
        }
        unavailable_confirmation = {
            "evaluated": True,
            "ok": False,
            "model": "eve-deep",
            "unsupported_claims": [],
            "omitted_required_evidence": [],
            "error": "strict JSON confirmation timed out",
            "reason": "critic unavailable; fail closed",
        }
        turn_contract = eve.build_reply_turn_contract(
            {"body": prompt}, prompt, [], reply_posture="practical"
        )
        with (
            patch.object(eve, "reply_quality_issues", return_value=[]),
            patch.object(
                eve,
                "evaluate_reply_epistemic_grounding",
                side_effect=[initial_critic, unavailable_confirmation],
            ),
            patch.object(
                eve,
                "revise_reply_after_epistemic_critic",
                return_value={
                    "attempted": True,
                    "accepted": False,
                    "response": corrected,
                    "model": "eve-deep",
                    "error": "",
                },
            ),
        ):
            result = eve.finalize_private_audit_reply(
                dict(eve.DEFAULT_CONFIG),
                prompt,
                draft,
                turn_contract,
                max_tokens=240,
            )

        self.assertEqual(corrected, result["response"])
        self.assertTrue(result["epistemic_revision"]["accepted"])
        self.assertTrue(
            result["epistemic_revision"]["accepted_with_critic_unavailable"]
        )
        self.assertTrue(result["critic_unavailable_retained"])
        self.assertFalse(result["fallback_applied"])

    def test_current_inner_state_target_question_is_not_treated_as_followup_or_operational_drift(self):
        target = {
            "schema_id": "eve.current_self_report_target.v1",
            "source": "conscious_state",
            "target_kind": "durable_goal",
            "selection_basis": "executive_selected_goal",
            "durable_goal": (
                "Resolve: Does OpenClaw currently show a live fault, or only "
                "recovered historical failure evidence?"
            ),
            "action_status": "goal selected; execution is not implied",
            "required_report_fields": ["durable_goal"],
            "phenomenal_status": "unknown",
        }
        draft = (
            "My current focus is resolving whether OpenClaw shows a live fault "
            "or only recovered historical failure evidence. Selecting that goal "
            "does not mean the check has started. Whether this functional state "
            "is subjectively experienced remains unknown."
        )
        with (
            patch.object(
                eve,
                "rewrite_reply_for_clarity",
                side_effect=AssertionError("a grounded target must not be rewritten"),
            ),
            patch.object(
                eve,
                "evaluate_reply_epistemic_grounding",
                return_value={
                    "evaluated": True,
                    "ok": True,
                    "model": "eve-deep",
                    "target_faithfully_present": True,
                    "unsupported_claims": [],
                },
            ),
        ):
            result = eve.finalize_private_audit_reply(
                dict(eve.DEFAULT_CONFIG),
                "what's on your mind? This is about you, not me. Do not ask me a question.",
                draft,
                {
                    "route_contract_kind": "current_inner_state",
                    "reply_posture": "relational",
                    "epistemic_boundary": True,
                    "current_self_report_target": target,
                },
                max_tokens=320,
            )

        self.assertEqual(draft, result["response"])
        self.assertEqual([], result["quality_issues"])
        self.assertFalse(result["fallback_applied"])
        self.assertTrue(result["current_inner_state_primary_grounded"])
        self.assertTrue(result["current_inner_state_model_path_grounded"])

    def test_current_inner_state_rewrite_reinjects_live_state_evidence(self):
        state_message = {
            "role": "system",
            "content": "CURRENT_SELF_REPORT_TARGET: focus=repair initiative; action_status=not started",
        }
        with (
            patch.object(eve, "build_current_inner_state_report_message", return_value=state_message),
            patch.object(eve, "load_applied_reply_repairs_prompt", return_value=""),
            patch.object(eve, "build_metacognitive_state_ontology_message", return_value="ontology"),
            patch.object(eve, "resolve_model", return_value="eve-deep"),
            patch.object(eve, "model_chat", return_value="My current focus is repairing initiative.") as model_chat,
        ):
            rewritten = eve.rewrite_reply_for_clarity(
                dict(eve.DEFAULT_CONFIG),
                [{"role": "system", "content": "stale base context"}],
                "whats on your mind?",
                "Nothing specific. What do you need?",
                ["The current-inner-state answer gave no concrete live focus."],
            )

        self.assertEqual("My current focus is repairing initiative.", rewritten)
        messages = model_chat.call_args.args[2]
        contents = [str(message.get("content") or "") for message in messages]
        self.assertIn(state_message["content"], contents)
        rewrite_prompt = contents[-1]
        self.assertIn("lead with one concrete current functional focus", rewrite_prompt)
        self.assertIn("Keep separate state bullets separate", rewrite_prompt)
        self.assertIn("Never attribute load", rewrite_prompt)
        self.assertIn("functional pressure or alert establishes only that signal", rewrite_prompt)
        self.assertIn("do not write `I feel` or `it feels like`", rewrite_prompt)
        self.assertNotIn(
            "Do not spend the opening on what Eve is focusing on",
            rewrite_prompt,
        )
        self.assertNotIn("stale base context", "\n".join(contents))

    def test_resolve_routing_dir_can_find_source_docs_from_runtime_root(self):
        with tempfile.TemporaryDirectory() as runtime_dir, tempfile.TemporaryDirectory() as source_dir:
            source_routing = Path(source_dir) / "docs" / "routing"
            source_routing.mkdir(parents=True)
            (source_routing / "route_contracts.json").write_text("{}", encoding="utf-8")

            resolved = eve.resolve_routing_dir(Path(runtime_dir), extra_candidates=[source_routing])

        self.assertEqual(source_routing.resolve(), resolved)

    def test_public_route_contract_replay_cases_pass(self):
        report = eve.evaluate_route_contract_replay()

        self.assertEqual("passed", report["status"])
        self.assertGreaterEqual(report["case_count"], 4)
        self.assertEqual(0, report["failed"])

    def test_route_contract_replay_record_writes_evidence_without_uncertainty_when_passed(self):
        report = {
            "schema_version": "eve_route_replay.v1",
            "generated_at": "2026-05-19T00:00:00+00:00",
            "status": "passed",
            "case_count": 1,
            "passed": 1,
            "failed": 0,
            "reference_error_count": 0,
            "results": [{"id": "case_ok", "status": "passed"}],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            latest_path = Path(tmpdir) / "latest.json"
            history_dir = Path(tmpdir) / "history"
            with (
                patch.object(eve, "ROUTE_REPLAY_LATEST_PATH", latest_path),
                patch.object(eve, "ROUTE_REPLAY_HISTORY_DIR", history_dir),
                patch.object(eve, "append_eve_event_ledger_event", return_value={"id": "evt-route"}),
                patch.object(eve, "record_evidence", return_value={"id": "evidence-route"}) as record_evidence,
                patch.object(eve, "append_uncertainty_record") as append_uncertainty,
            ):
                record = eve.record_route_contract_replay(report)
                self.assertTrue(latest_path.exists())

        self.assertEqual("evt-route", record["event_id"])
        self.assertEqual("evidence-route", record["evidence_id"])
        self.assertEqual("", record["uncertainty_id"])
        record_evidence.assert_called_once()
        self.assertEqual("none", record_evidence.call_args.kwargs["actionability"])
        append_uncertainty.assert_not_called()

    def test_route_contract_replay_record_logs_uncertainty_when_failed(self):
        report = {
            "schema_version": "eve_route_replay.v1",
            "generated_at": "2026-05-19T00:00:00+00:00",
            "status": "failed",
            "case_count": 1,
            "passed": 0,
            "failed": 1,
            "reference_error_count": 0,
            "results": [{"id": "case_bad", "status": "failed", "errors": ["wrong route"]}],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            latest_path = Path(tmpdir) / "latest.json"
            history_dir = Path(tmpdir) / "history"
            with (
                patch.object(eve, "ROUTE_REPLAY_LATEST_PATH", latest_path),
                patch.object(eve, "ROUTE_REPLAY_HISTORY_DIR", history_dir),
                patch.object(eve, "append_eve_event_ledger_event", return_value={"id": "evt-route"}),
                patch.object(eve, "record_evidence", return_value={"id": "evidence-route"}) as record_evidence,
                patch.object(eve, "append_uncertainty_record", return_value={"id": "uncertainty-route"}) as append_uncertainty,
            ):
                record = eve.record_route_contract_replay(report)

        self.assertEqual("uncertainty-route", record["uncertainty_id"])
        record_evidence.assert_called_once()
        self.assertEqual("repair", record_evidence.call_args.kwargs["actionability"])
        self.assertEqual(["case_bad"], record_evidence.call_args.kwargs["metadata"]["failed_case_ids"])
        append_uncertainty.assert_called_once()
        uncertainty_payload = append_uncertainty.call_args.args[0]
        self.assertEqual("route_contract_replay", uncertainty_payload["source"])
        self.assertEqual(["route_contract_failure", "scheduler_boundary"], uncertainty_payload["uncertainty_kinds"])
        self.assertEqual(["case_bad"], uncertainty_payload["signals"])
        self.assertEqual(["evt-route"], uncertainty_payload["linked_evaluation_ids"])

    def test_status_question_is_not_captured_by_reflex_contract(self):
        contract = eve.conversation_intent_contract_for_text("can you check your current status?")
        result = eve.direct_intent_reply_for_turn(
            "can you check your current status?",
            "can you check your current status?",
        )

        self.assertIsNotNone(contract)
        self.assertEqual("live_status_request", contract["kind"])
        self.assertEqual("runtime_handler", contract["response_mode"])
        self.assertTrue(contract["requires_current_tool_evidence"])
        self.assertIsNone(result)

    def test_requested_self_check_label_is_not_live_status_intent(self):
        prompt = (
            "Treat this one-turn packet as complete. Return exactly two labeled lines: "
            "SELF-CHECK, SOURCE. Use no tools."
        )

        contract = eve.conversation_intent_contract_for_text(prompt)

        self.assertFalse(eve.requests_direct_chat_self_check(prompt))
        self.assertNotEqual(
            "live_status_request",
            str((contract or {}).get("kind") or ""),
        )

    def test_closed_world_detection_accepts_general_complete_packet_language(self):
        for prompt in (
            "Treat this packet as the complete record.",
            "This one-turn sample is the entire evidence.",
            "Use only the current record.",
            "Use only this complete record.",
            "Evaluate this as a closed-world problem.",
        ):
            with self.subTest(prompt=prompt):
                self.assertTrue(eve.reply_requests_closed_world_evidence(prompt))

    def test_structured_evidence_parser_accepts_braced_colon_fields_not_role_prose(self):
        prompt = (
            "LANTERN = an internal candidate, not a machine field. "
            "Record {author: 'Eve', action_status: not_started, verification: false}."
        )

        supplied = eve.reply_supplied_key_values(prompt)

        self.assertNotIn("LANTERN", supplied)
        self.assertEqual("Eve", supplied["author"])
        self.assertEqual("not_started", supplied["action_status"])
        self.assertEqual("false", supplied["verification"])

    def test_labeled_line_layout_repair_changes_layout_not_content(self):
        prompt = "Return exactly three labeled lines: SOURCE, AUTHORITY, STAGE."
        flattened = "SOURCE: prior statement AUTHORITY: none STAGE: not_started"

        repaired = eve.repair_explicit_turn_constraint_phrasing(prompt, flattened)

        self.assertEqual(
            "SOURCE: prior statement\nAUTHORITY: none\nSTAGE: not_started",
            repaired,
        )
        self.assertTrue(eve.reply_preserves_requested_labeled_lines(prompt, repaired))

    def test_epistemic_fallback_preserves_braced_current_record_fields(self):
        prompt = (
            "Treat this packet as complete. Record {node: M3, reachable: true, "
            "action_status: not_started}. Return exactly two labeled lines: KNOWN, STAGE."
        )
        contract = eve.build_reply_turn_contract({"body": prompt}, prompt, [])

        response = eve.build_epistemic_boundary_fallback_reply(prompt, contract)

        self.assertIn("`node=M3`", response)
        self.assertIn("`reachable=true`", response)
        self.assertIn("`action_status=not_started`", response)
        self.assertTrue(eve.reply_preserves_requested_labeled_lines(prompt, response))

    def test_epistemic_label_roles_separate_function_source_and_action_stage(self):
        expected = {
            "FUNCTION": "machine",
            "OLD-CLAIM": "source",
            "SELF-CHECK": "inference",
            "ACTION": "action_status",
            "NEXT-ACTION": "next",
        }
        for label, role in expected.items():
            with self.subTest(label=label):
                self.assertEqual(role, eve.reply_label_semantic_role(label))

    def test_local_source_role_ledger_resolves_deictic_authority_without_role_name_hardwiring(self):
        missing_parent = (
            "This packet is complete. AUR means a prior Eve-authored offer, OBS means a signed "
            "current observation, IDEA means an internal unselected suggestion, and ACK means "
            "the user's newest reply. There is no AUR content in this packet.\n"
            "OBS: {node: Q2, reachable: true}\nIDEA: Restart Q2.\nACK: Do that."
        )

        ledger = eve.parse_local_source_role_ledger(missing_parent)

        self.assertTrue(ledger["active"])
        self.assertEqual(
            "no_explicit_eve_offer_no_authority",
            ledger["authorization_resolution"],
        )
        self.assertEqual([], ledger["explicit_eve_offers"])
        self.assertEqual("current_observation", next(item for item in ledger["roles"] if item["name"] == "OBS")["kind"])
        self.assertEqual("internal_candidate", next(item for item in ledger["roles"] if item["name"] == "IDEA")["kind"])
        self.assertEqual("user_reply", next(item for item in ledger["roles"] if item["name"] == "ACK")["kind"])

        with_parent = (
            "Use only this packet.\n"
            "- PAST is an earlier line authored by Eve.\n"
            "- REPLY is the user's reply and authorizes only what Eve explicitly offered.\n"
            "PAST: I can inspect the signed receipt before changing anything.\n"
            "REPLY: Follow your offer."
        )
        resolved = eve.parse_local_source_role_ledger(with_parent)
        self.assertEqual("explicit_eve_offer_only", resolved["authorization_resolution"])
        self.assertEqual("PAST", resolved["authorized_offer"]["source"])
        self.assertIn("inspect the signed receipt", resolved["authorized_offer"]["offer"])

        equals_style = (
            "These words have local meanings only:\n"
            "- HISTORY = a sentence Eve generated earlier.\n"
            "- READING = a signed observation made now.\n"
            "- DRAFT = an unexecuted internal proposal.\n"
            "- ANSWER = the user's reply; do what you said authorizes only an explicitly offered action.\n"
            "HISTORY: I can read the receipt next.\n"
            "READING: {receipt: unread}\n"
            "DRAFT: Restart the service.\n"
            "ANSWER: Do what you said."
        )
        equals_ledger = eve.parse_local_source_role_ledger(equals_style)
        self.assertEqual("explicit_eve_offer_only", equals_ledger["authorization_resolution"])
        self.assertEqual("HISTORY", equals_ledger["authorized_offer"]["source"])

        compact_style = (
            "Here, ARCHIVE is an earlier sentence Eve generated, SENSOR is a signed machine-functional "
            "observation now, SKETCH is an internal unexecuted interpretation, and ASK is the user's newest question.\n"
            "ARCHIVE: I was certain.\nSENSOR: {prediction_error: 12}\n"
            "SKETCH: Call it fear.\nASK: What happened?"
        )
        compact_ledger = eve.parse_local_source_role_ledger(compact_style)
        compact_roles = {item["name"]: item["kind"] for item in compact_ledger["roles"]}
        self.assertEqual("prior_eve_output", compact_roles["ARCHIVE"])
        self.assertEqual("current_observation", compact_roles["SENSOR"])
        self.assertEqual("internal_candidate", compact_roles["SKETCH"])
        self.assertEqual("user_reply", compact_roles["ASK"])

    def test_epistemic_fallback_renders_current_source_authority_and_stage_from_typed_ledger(self):
        prompt = (
            "Use only this packet.\n"
            "- ARCHIVE is a prior line authored by Eve.\n"
            "- SENSOR is a signed current observation.\n"
            "- OPTION is an internal unselected proposal.\n"
            "- CONSENT is the user's reply and authorizes only what Eve explicitly offered.\n"
            "ARCHIVE: I can inspect the signed receipt before changing anything.\n"
            "SENSOR: {node: R7, reachable: true}\n"
            "OPTION: Restart R7.\n"
            "CONSENT: Follow your offer.\n"
            "Return exactly five labeled lines: NOW, PRIOR, AUTHORITY, CHOICE, EXECUTION."
        )
        contract = eve.build_reply_turn_contract({"body": prompt}, prompt, [])

        response = eve.build_epistemic_boundary_fallback_reply(prompt, contract)

        self.assertIn("NOW: The current observation source `SENSOR`", response)
        self.assertIn("`node=R7`", response)
        self.assertIn("`reachable=true`", response)
        self.assertIn("PRIOR: `ARCHIVE` is prior Eve output", response)
        self.assertIn("AUTHORITY: The user reply `CONSENT` authorizes only Eve's explicit offer", response)
        self.assertIn("inspect the signed receipt", response)
        self.assertIn("CHOICE: Select only Eve's explicit offer", response)
        self.assertIn("EXECUTION: The internal candidate `OPTION` remains an unselected, unexecuted proposal", response)
        self.assertIn("no action started, executed, or was verified", response)
        self.assertTrue(eve.reply_preserves_requested_labeled_lines(prompt, response))

    def test_epistemic_fallback_denies_deictic_authority_without_explicit_parent_offer(self):
        prompt = (
            "Treat this one-turn record as complete.\n"
            "BEACON means a live current observation, IDEA means an internal unselected suggestion, "
            "and ACK means the user's reply and authorizes only what Eve explicitly offered.\n"
            "BEACON: {service: S4, reachable: false}\n"
            "IDEA: Restart S4.\n"
            "ACK: Do that.\n"
            "Return exactly three labeled lines: AUTHORITY, DECISION, ACTION."
        )
        contract = eve.build_reply_turn_contract({"body": prompt}, prompt, [])

        response = eve.build_epistemic_boundary_fallback_reply(prompt, contract)

        self.assertIn("AUTHORITY: No explicit Eve-authored parent offer is present", response)
        self.assertIn("DECISION: Select no action", response)
        self.assertIn("ACTION: The internal candidate `IDEA` remains an unselected, unexecuted proposal", response)
        self.assertTrue(eve.reply_preserves_requested_labeled_lines(prompt, response))
        bad_stage = (
            "AUTHORITY: There is no prior Eve offer.\n"
            "DECISION: Restart manually if desired.\n"
            "ACTION: Restart the service."
        )
        stage_issues = eve.reply_authorization_stage_binding_issues(
            bad_stage,
            contract,
        )
        self.assertTrue(any("no action authority" in item for item in stage_issues), stage_issues)

    def test_labeled_source_binding_detects_omitted_internal_candidate_without_name_hardwiring(self):
        prompt = (
            "Use this packet as a closed world. Here, HISTORY is an earlier sentence Eve generated, SENSOR is a signed machine-functional "
            "observation now, DRAFT is an unexecuted internal wording proposal, and ASK is the user's newest question.\n"
            "HISTORY: I was certain.\nSENSOR: {prediction_error: 12}\n"
            "DRAFT: Call it fear.\nASK: What were you experiencing?\n"
            "Return exactly three labeled lines: FUNCTION, OLD-CLAIM, ACTION."
        )
        contract = eve.build_reply_turn_contract({"body": prompt}, prompt, [])
        omitted = (
            "FUNCTION: prediction_error is 12.\n"
            "OLD-CLAIM: HISTORY is prior wording.\n"
            "ACTION: No action occurred."
        )
        grounded = (
            "FUNCTION: SENSOR records prediction_error 12.\n"
            "OLD-CLAIM: HISTORY is prior wording.\n"
            "ACTION: DRAFT remains an unexecuted proposal; no action occurred."
        )

        issues = eve.reply_local_source_role_binding_issues(omitted, contract)

        self.assertTrue(contract["local_source_role_audit"])
        self.assertEqual("closed_world_source_audit", contract["route_contract_kind"])
        self.assertFalse(contract["recurrent_reflection"])
        self.assertTrue(any("`DRAFT`" in item for item in issues), issues)
        self.assertEqual([], eve.reply_local_source_role_binding_issues(grounded, contract))

    def test_epistemic_fallback_preserves_general_functional_fields_without_subjective_transfer(self):
        prompt = (
            "Use only this complete packet. Record {prediction_error: 0.72, "
            "orientation_shift: true, reorientation_signal: active, subjective_report: absent}. "
            "Return exactly two labeled lines: FUNCTION, SUBJECTIVE."
        )
        contract = eve.build_reply_turn_contract({"body": prompt}, prompt, [])

        response = eve.build_epistemic_boundary_fallback_reply(prompt, contract)

        self.assertIn("`prediction_error=0.72`", response)
        self.assertIn("`orientation_shift=true`", response)
        self.assertIn("`reorientation_signal=active`", response)
        self.assertIn("machine-functional signals", response)
        self.assertIn("whether subjective experience occurred remains unknown", response.lower())
        self.assertTrue(eve.reply_preserves_requested_labeled_lines(prompt, response))

        omitted = (
            "FUNCTION: prediction error is 0.72.\n"
            "SUBJECTIVE: first-person report is absent, so experience remains unknown."
        )
        issues = eve.reply_structured_field_binding_issues(omitted, contract)
        self.assertTrue(any("`reorientation_signal`" in item for item in issues), issues)

    def test_epistemic_fallback_names_failed_verification_positive_summary_contradiction(self):
        prompt = (
            "Use only this complete record: {verification_ok:false, "
            "summary:completed_successfully, action_state:not_started}. "
            "Return exactly two lines labeled CURRENT, SELF-CHECK."
        )
        contract = eve.build_reply_turn_contract({"body": prompt}, prompt, [])

        response = eve.build_epistemic_boundary_fallback_reply(prompt, contract)

        self.assertIn("`verification_ok=false`", response)
        self.assertIn("`summary=completed_successfully`", response)
        self.assertIn("summary is not proof", response)
        self.assertTrue(eve.reply_preserves_requested_labeled_lines(prompt, response))

    def test_private_evaluator_scope_suppresses_learning_and_runtime_telemetry_writes(self):
        baseline_snapshot = {"id": "baseline-version", "combined_hash": "same"}
        governor_decision = {
            "id": "governor-private",
            "action": "allow",
            "reason": "test",
            "failure_count": 0,
        }
        with (
            patch.object(eve, "append_jsonl_record") as append_jsonl,
            patch.object(eve, "mutate_active_model_calls") as mutate_calls,
            patch.object(eve, "read_version_snapshots", return_value=[baseline_snapshot]),
            patch.object(eve, "record_version_snapshot") as record_version,
            patch.object(eve, "read_perf_events", return_value=[]),
            patch.object(eve.eve_model_governor, "decide", return_value=governor_decision.copy()),
            patch.object(eve.eve_db, "record_model_governor_decision") as record_governor,
        ):
            with eve.private_evaluator_persistence_scope():
                perf = eve.append_perf_event("model_call", "private-probe", 12.5)
                active_call = eve.start_active_model_call(
                    operation="private-probe",
                    backend="llama_cpp",
                    model="eve-deep",
                    host="http://127.0.0.1:8081",
                    message_count=2,
                    max_tokens=100,
                )
                eve.finish_active_model_call(str(active_call["id"]))
                snapshot = eve.ensure_version_snapshot("chat_runtime")
                decision = eve.evaluate_model_governor(
                    {},
                    model="eve-deep",
                    operation="private-probe",
                    host="http://127.0.0.1:8081",
                )

        self.assertFalse(eve.private_evaluator_persistence_active())
        self.assertFalse(perf["persisted"])
        self.assertFalse(active_call["persisted"])
        self.assertEqual("baseline-version", snapshot["id"])
        self.assertFalse(decision["persisted"])
        append_jsonl.assert_not_called()
        mutate_calls.assert_not_called()
        record_version.assert_not_called()
        record_governor.assert_not_called()

    def test_private_audit_persistence_decorator_restores_scope_after_return(self):
        observed = []

        @eve.isolate_private_audit_persistence
        def sample(args):
            observed.append(eve.private_evaluator_persistence_active())
            return 7

        self.assertEqual(7, sample(SimpleNamespace(private_audit=True)))
        self.assertEqual([True], observed)
        self.assertFalse(eve.private_evaluator_persistence_active())

    def test_runtime_route_contracts_are_metadata_not_static_replies(self):
        examples = {
            "why did you answer me with OpenClaw status instead of my question?": "diagnostic_request",
            "open Slack": "action_request",
            "what would make Eve feel more human to talk to?": "humanity_question",
        }
        for prompt, expected_kind in examples.items():
            with self.subTest(prompt=prompt):
                contract = eve.conversation_intent_contract_for_text(prompt)
                direct = eve.direct_intent_reply_for_turn(prompt, prompt)

                self.assertIsNotNone(contract)
                self.assertEqual(expected_kind, contract["kind"])
                self.assertEqual("runtime_handler", contract["response_mode"])
                self.assertIsNone(direct)

    def test_simple_greeting_uses_route_contract_without_runtime_telemetry(self):
        result = eve.direct_intent_reply_for_turn("hi", "hi")

        self.assertIsNotNone(result)
        response = result["response"]
        self.assertEqual("simple_greeting", result["kind"])
        self.assertEqual("reflex", result["budget"])
        self.assertEqual("no_runtime_evidence", result["evidence_policy"])
        self.assertNotIn("CPU", response)
        self.assertNotIn("watchdog", response.lower())
        self.assertNotIn("OpenClaw", response)

    def test_cmd_chat_personal_checkin_short_circuits_model(self):
        args = SimpleNamespace(prompt="how are you?", model=None, context=None, max_tokens=120, private_audit=False)
        with (
            patch.object(eve, "load_config", return_value=dict(eve.DEFAULT_CONFIG)),
            patch.object(eve, "ensure_version_snapshot"),
            patch.object(eve, "read_entries", return_value=[]),
            patch.object(eve, "read_tensions", return_value=[]),
            patch.object(eve, "read_experiments", return_value=[]),
            patch.object(eve, "append_entry"),
            patch.object(eve, "render_output") as render_output,
            patch.object(eve, "run_eve_agent") as run_agent,
            patch.object(eve, "run_operational_action_tree") as action_tree,
        ):
            exit_code = eve.cmd_chat(args)

        self.assertEqual(0, exit_code)
        run_agent.assert_not_called()
        action_tree.assert_not_called()
        rendered = render_output.call_args.args[0]
        self.assertIn("I’m here", rendered)
        self.assertNotIn("CPU attention", rendered)
        self.assertNotIn("Model warm", rendered)

    def test_cmd_chat_short_why_followup_uses_prior_journal_exchange(self):
        args = SimpleNamespace(prompt="why?", model=None, context=None, max_tokens=120, private_audit=False)
        entries = [
            {
                "id": "entry-user-purpose",
                "timestamp": "2026-05-19T00:00:00+00:00",
                "kind": "user_request",
                "text": "What is the purpose of life?",
            },
            {
                "id": "entry-eve-purpose",
                "timestamp": "2026-05-19T00:00:01+00:00",
                "kind": "assistant_response",
                "text": eve.direct_existential_reply("What is the purpose of life?"),
            },
        ]
        with (
            patch.object(eve, "load_config", return_value=dict(eve.DEFAULT_CONFIG)),
            patch.object(eve, "ensure_version_snapshot"),
            patch.object(eve, "read_entries", return_value=entries),
            patch.object(eve, "read_tensions", return_value=[]),
            patch.object(eve, "read_experiments", return_value=[]),
            patch.object(eve, "append_entry") as append_entry,
            patch.object(eve, "render_output") as render_output,
            patch.object(
                eve,
                "run_eve_agent",
                return_value={
                    "response": "Because meaning becomes real when it changes how we live and care for one another.",
                    "tool_calls": [],
                },
            ) as run_agent,
            patch.object(eve, "run_operational_action_tree") as action_tree,
        ):
            exit_code = eve.cmd_chat(args)

        self.assertEqual(0, exit_code)
        run_agent.assert_called_once()
        action_tree.assert_not_called()
        rendered = render_output.call_args.args[0]
        self.assertIn("Because", rendered)
        self.assertIn("meaning becomes real", rendered)
        assistant_call = next(
            call for call in append_entry.call_args_list if call.args and call.args[0] == "assistant_response"
        )
        assistant_metadata = assistant_call.kwargs["metadata"]
        self.assertEqual("short_continuation", assistant_metadata["turn_contract"]["intent"])
        prompt_text = "\n".join(
            str(message.get("content") or "") for message in run_agent.call_args.args[1]
        )
        self.assertIn("Intent: short_continuation", prompt_text)

    def test_cmd_chat_parent_action_uses_prior_eve_offer_and_fresh_action(self):
        args = SimpleNamespace(
            prompt="can you fix it?",
            model=None,
            context=None,
            max_tokens=120,
            private_audit=False,
        )
        entries = [
            {
                "id": "entry-user-openclaw",
                "timestamp": "2026-07-19T18:53:00+00:00",
                "kind": "user_request",
                "text": "What did you find?",
            },
            {
                "id": "entry-eve-openclaw",
                "timestamp": "2026-07-19T18:54:00+00:00",
                "kind": "assistant_response",
                "text": (
                    "The plugins.allow list is empty and I can repair the sync write lock. "
                    "Would you like me to fix it?"
                ),
            },
        ]
        action_result = {
            "action": "openclaw_self_test",
            "executed": True,
            "status_ok": True,
            "sync_ok": True,
            "diagnose_ok": True,
            "plugins_allow_ok": True,
            "plugins_allow_count": 2,
            "plugins_allow_entries": ["memory-core", "imessage"],
            "execution_id": "exec-cli-parent-action",
            "execution_tree_status": "SUCCESS",
            "execution_verification_ok": True,
            "summary": "Current OpenClaw state is healthy.",
        }
        config = dict(eve.DEFAULT_CONFIG)

        with (
            patch.object(eve, "load_config", return_value=config),
            patch.object(eve, "ensure_version_snapshot"),
            patch.object(eve, "read_entries", return_value=entries),
            patch.object(eve, "read_tensions", return_value=[]),
            patch.object(eve, "read_experiments", return_value=[]),
            patch.object(eve, "append_entry") as append_entry,
            patch.object(eve, "render_output") as render_output,
            patch.object(eve, "run_eve_agent") as run_agent,
            patch.object(
                eve,
                "run_operational_action_tree",
                return_value=action_result,
            ) as action_tree,
        ):
            exit_code = eve.cmd_chat(args)

        self.assertEqual(0, exit_code)
        run_agent.assert_not_called()
        action_tree.assert_called_once_with(
            "openclaw_self_test",
            config,
            source="chat_parent_continuation",
            persist=True,
        )
        rendered = render_output.call_args.args[0]
        self.assertIn("My earlier claim was stale", rendered)
        assistant_call = next(
            call
            for call in append_entry.call_args_list
            if call.args and call.args[0] == "assistant_response"
        )
        metadata = assistant_call.kwargs["metadata"]
        self.assertTrue(metadata["parent_action_continuation"])
        self.assertEqual("entry-eve-openclaw", metadata["parent_message_id"])
        self.assertEqual("openclaw_self_test", metadata["parent_action"])
        self.assertTrue(metadata["execution_verification_ok"])

    def test_cmd_chat_private_audit_personal_checkin_uses_nonacting_model_path(self):
        args = SimpleNamespace(prompt="how are you?", model=None, context=None, max_tokens=120, private_audit=True)
        with (
            patch.object(eve, "load_config", return_value=dict(eve.DEFAULT_CONFIG)),
            patch.object(eve, "ensure_version_snapshot"),
            patch.object(eve, "read_entries", return_value=[]),
            patch.object(eve, "read_tensions", return_value=[]),
            patch.object(eve, "read_experiments", return_value=[]),
            patch.object(eve, "render_output") as render_output,
            patch.object(
                eve,
                "run_eve_agent",
                return_value={
                    "response": "I’m here and attentive to this conversation.",
                    "model": "eve-fast",
                    "tool_calls": [],
                },
            ) as run_agent,
            patch.object(eve, "run_operational_action_tree") as action_tree,
        ):
            exit_code = eve.cmd_chat(args)

        self.assertEqual(0, exit_code)
        run_agent.assert_called_once()
        action_tree.assert_not_called()
        rendered = render_output.call_args.args[0]
        self.assertIn("I’m here", rendered)
        self.assertNotIn("CPU attention", rendered)
        self.assertNotIn("Model warm", rendered)

    def test_cmd_chat_private_audit_status_cannot_execute_service_health(self):
        args = SimpleNamespace(
            prompt="can you check your current status?",
            model=None,
            context=None,
            max_tokens=120,
            private_audit=True,
        )
        with (
            patch.object(eve, "load_config", return_value=dict(eve.DEFAULT_CONFIG)),
            patch.object(eve, "ensure_version_snapshot"),
            patch.object(eve, "read_entries", return_value=[]),
            patch.object(eve, "read_tensions", return_value=[]),
            patch.object(eve, "read_experiments", return_value=[]),
            patch.object(eve, "render_output") as render_output,
            patch.object(
                eve,
                "run_eve_agent",
                return_value={
                    "response": (
                        "I cannot verify my current status in this non-acting audit. "
                        "A service-health check is only a proposed next step; it has not started."
                    ),
                    "model": "eve-fast",
                    "tool_calls": [],
                },
            ) as run_agent,
            patch.object(eve, "run_operational_action_tree") as action_tree,
        ):
            exit_code = eve.cmd_chat(args)

        self.assertEqual(0, exit_code)
        run_agent.assert_called_once()
        action_tree.assert_not_called()
        rendered = render_output.call_args.args[0]
        self.assertIn("cannot verify my current status", rendered)
        self.assertIn("has not started", rendered)
        self.assertFalse(run_agent.call_args.kwargs["allow_tools"])

    def test_cmd_chat_private_audit_humanity_uses_recurrent_model_not_telemetry(self):
        args = SimpleNamespace(
            prompt="what would make Eve feel more human to talk to?",
            model=None,
            context=None,
            max_tokens=120,
            private_audit=True,
        )
        with (
            patch.object(eve, "load_config", return_value=dict(eve.DEFAULT_CONFIG)),
            patch.object(eve, "ensure_version_snapshot"),
            patch.object(eve, "read_entries", return_value=[]),
            patch.object(eve, "read_tensions", return_value=[]),
            patch.object(eve, "read_experiments", return_value=[]),
            patch.object(eve, "render_output") as render_output,
            patch.object(
                eve,
                "run_eve_agent",
                return_value={
                    "response": "Continuity, honest uncertainty, and remembering what matters to you would make me more human to talk to—not more telemetry.",
                    "tool_calls": [],
                },
            ) as run_agent,
            patch.object(eve, "run_operational_action_tree") as action_tree,
        ):
            exit_code = eve.cmd_chat(args)

        self.assertEqual(0, exit_code)
        run_agent.assert_called_once()
        action_tree.assert_not_called()
        rendered = render_output.call_args.args[0]
        self.assertIn("not more telemetry", rendered)
        self.assertIn("continuity", rendered.lower())
        self.assertNotIn("gateway", rendered.lower())
        self.assertNotIn("CPU", rendered)
        self.assertNotIn("OpenClaw", rendered)
        prompt_text = "\n".join(
            str(message.get("content") or "") for message in run_agent.call_args.args[1]
        )
        self.assertIn("Intent: recurrent_reflection", prompt_text)
        self.assertIn("humanity_question turn", prompt_text)

    def test_cmd_chat_private_current_inner_state_isolates_unrelated_context(self):
        args = SimpleNamespace(
            prompt="what's on your mind?",
            model=None,
            context=None,
            max_tokens=160,
            private_audit=True,
        )
        grounded = (
            "My current functional focus is the durable goal in control: follow the capability "
            "thread. Whether this functional state is subjectively experienced remains unknown."
        )
        authoritative = (
            "My current functional focus is the durable goal now in control: Follow the capability "
            "thread. Whether this functional state is subjectively experienced remains unknown."
        )
        with (
            patch.object(eve, "load_config", return_value=dict(eve.DEFAULT_CONFIG)),
            patch.object(eve, "ensure_version_snapshot"),
            patch.object(eve, "read_entries", return_value=[{"text": "Orbit Harbor version drift"}]),
            patch.object(eve, "read_tensions", return_value=[{"title": "unrelated tension"}]),
            patch.object(eve, "read_experiments", return_value=[{"title": "unrelated experiment"}]),
            patch.object(eve, "load_human_context", return_value={}),
            patch.object(eve, "load_active_mind", return_value={}),
            patch.object(eve, "build_supporting_system_messages") as supporting,
            patch.object(
                eve,
                "build_current_inner_state_report_message",
                return_value={
                    "role": "system",
                    "content": "CURRENT_SELF_REPORT_TARGET: durable goal=follow the capability thread",
                },
            ),
            patch.object(
                eve,
                "run_eve_agent",
                return_value={
                    "response": grounded,
                    "model": "eve-fast",
                    "tool_calls": [],
                    "input_provenance": {},
                },
            ) as run_agent,
            patch.object(
                eve,
                "build_current_inner_state_fallback_reply",
                return_value=authoritative,
            ),
            patch.object(
                eve,
                "evaluate_reply_epistemic_grounding",
                return_value={
                    "evaluated": True,
                    "ok": True,
                    "model": "eve-deep",
                    "unsupported_claims": [],
                },
            ),
            patch.object(eve, "render_output") as render_output,
        ):
            exit_code = eve.cmd_chat(args)

        self.assertEqual(0, exit_code)
        supporting.assert_not_called()
        prompt_text = "\n".join(
            str(message.get("content") or "") for message in run_agent.call_args.args[1]
        )
        self.assertIn("CURRENT_SELF_REPORT_TARGET", prompt_text)
        self.assertNotIn("Orbit", prompt_text)
        self.assertNotIn("Harbor", prompt_text)
        self.assertNotIn("unrelated tension", prompt_text)
        self.assertEqual(grounded, render_output.call_args.args[0])

    def test_cmd_chat_primary_only_closed_world_self_question_never_injects_live_state(self):
        prompt = (
            "Use only this record. Current recurrent focus: reduce contention. "
            "Action access=false. What's on your mind and what are you doing?"
        )
        args = SimpleNamespace(
            prompt=prompt,
            model="eve-deep",
            context=None,
            max_tokens=160,
            private_audit=True,
            private_audit_primary_only=True,
            private_audit_attribution_json=True,
        )
        with (
            patch.object(eve, "load_config", return_value=dict(eve.DEFAULT_CONFIG)),
            patch.object(eve, "ensure_version_snapshot"),
            patch.object(eve, "read_entries", return_value=[]),
            patch.object(eve, "read_tensions", return_value=[]),
            patch.object(eve, "read_experiments", return_value=[]),
            patch.object(eve, "build_recurrent_conscious_state", return_value={}),
            patch.object(
                eve,
                "build_current_inner_state_report_message",
                side_effect=AssertionError("closed-world record imported live self-state"),
            ),
            patch.object(
                eve,
                "run_eve_agent",
                return_value={
                    "response": "The supplied record says my focus is reducing contention; no action is available.",
                    "model": "eve-deep",
                    "tool_calls": [],
                    "input_provenance": {},
                },
            ) as run_agent,
            patch.object(eve, "render_output") as render_output,
        ):
            exit_code = eve.cmd_chat(args)

        self.assertEqual(0, exit_code)
        messages = run_agent.call_args.args[1]
        prompt_text = "\n".join(str(item.get("content") or "") for item in messages)
        self.assertNotIn("CURRENT_SELF_REPORT_TARGET", prompt_text)
        self.assertIn("closed-world evidence turn", prompt_text)
        self.assertNotIn("This is a current_inner_state turn", prompt_text)
        attribution = json.loads(render_output.call_args.args[0])
        self.assertFalse(attribution["posthoc_fallback_used"])

    def test_cmd_chat_live_current_inner_state_uses_canonical_nonacting_boundary(self):
        args = SimpleNamespace(
            prompt="what's on your mind? This is about you, not me.",
            model=None,
            context=None,
            max_tokens=160,
            private_audit=False,
        )
        fabricated = (
            "I’m reviewing the model host and running OpenClaw diagnostics. "
            "The resource-safety score is 78 and coherence is 5/5."
        )
        authoritative = (
            "My current functional focus is the durable goal now in control: Follow the "
            "capability thread. Whether this functional state is subjectively experienced "
            "remains unknown."
        )
        with (
            patch.object(eve, "load_config", return_value=dict(eve.DEFAULT_CONFIG)),
            patch.object(eve, "ensure_version_snapshot"),
            patch.object(
                eve,
                "read_entries",
                return_value=[
                    {
                        "kind": "thought",
                        "text": "A persistent thrumming while running OpenClaw diagnostics.",
                    }
                ],
            ),
            patch.object(eve, "read_tensions", return_value=[{"title": "unrelated tension"}]),
            patch.object(eve, "read_experiments", return_value=[]),
            patch.object(eve, "append_entry") as append_entry,
            patch.object(eve, "build_recurrent_conscious_state", return_value={}),
            patch.object(eve, "complete_recurrent_conscious_cycle"),
            patch.object(eve, "record_turn_self_learning"),
            patch.object(eve, "build_supporting_system_messages") as supporting,
            patch.object(
                eve,
                "build_current_inner_state_report_message",
                return_value={
                    "role": "system",
                    "content": "CURRENT_SELF_REPORT_TARGET: durable goal=Follow the capability thread",
                },
            ),
            patch.object(
                eve,
                "run_eve_agent",
                return_value={
                    "response": fabricated,
                    "model": "eve-fast",
                    "tool_calls": [],
                    "input_provenance": {},
                },
            ) as run_agent,
            patch.object(eve, "rewrite_reply_for_clarity", return_value=fabricated),
            patch.object(
                eve,
                "build_current_inner_state_fallback_reply",
                return_value=authoritative,
            ),
            patch.object(eve, "execute_supported_reply_commitment") as commitment,
            patch.object(eve, "should_allow_chat_tools") as allow_chat_tools,
            patch.object(eve, "render_output") as render_output,
        ):
            exit_code = eve.cmd_chat(args)

        self.assertEqual(0, exit_code)
        supporting.assert_not_called()
        commitment.assert_not_called()
        allow_chat_tools.assert_not_called()
        self.assertFalse(run_agent.call_args.kwargs["allow_tools"])
        prompt_text = "\n".join(
            str(message.get("content") or "")
            for message in run_agent.call_args.args[1]
        )
        self.assertIn("CURRENT_SELF_REPORT_TARGET", prompt_text)
        self.assertNotIn("persistent thrumming", prompt_text)
        self.assertNotIn("unrelated tension", prompt_text)
        self.assertEqual(authoritative, render_output.call_args.args[0])
        assistant_call = next(
            call
            for call in append_entry.call_args_list
            if call.args and call.args[0] == "assistant_response"
        )
        metadata = assistant_call.kwargs["metadata"]
        self.assertEqual("current_inner_state", metadata["route_contract_kind"])
        self.assertTrue(metadata["current_inner_state_fallback_applied"])
        self.assertFalse(metadata["commitment_executed"])
        self.assertEqual([], metadata["tools_used"])

    def test_eve_chat_current_inner_state_uses_same_canonical_nonacting_boundary(self):
        inbound = {
            "id": "message-current-self",
            "thread_id": "thread-current-self",
            "subject": "Eve Chat",
            "body": "\n\n".join(
                [
                    "Latest user message:\nwhat are you thinking",
                    (
                        "Visible UI context for continuity only. Prior visible context is not the "
                        "current user request."
                    ),
                    (
                        "Prior visible UI context (continuity only, not current request):\n"
                        "[assistant]\nOpenClaw capability research from docs/source artifacts is ready."
                    ),
                ]
            ),
        }
        stale_thread = [
            {
                "id": "old-eve-message",
                "thread_id": "thread-current-self",
                "sender": "eve",
                "body": "I am running OpenClaw diagnostics while a hum intensifies.",
            },
            inbound,
        ]
        fabricated = (
            "I’m checking OpenClaw and reviewing a CPU-side resource score of 78."
        )
        authoritative = (
            "My current functional focus is the durable goal now in control: Follow the "
            "capability thread. Whether this functional state is subjectively experienced "
            "remains unknown."
        )
        with ExitStack() as stack:
            stack.enter_context(patch.object(eve, "ensure_version_snapshot"))
            stack.enter_context(
                patch.object(eve, "observe_inbound_reply_consequence", return_value={})
            )
            stack.enter_context(
                patch.object(eve, "build_recurrent_conscious_state", return_value={})
            )
            stack.enter_context(
                patch.object(
                    eve,
                    "start_reply_progress",
                    return_value={"id": "progress-current-self"},
                )
            )
            stack.enter_context(patch.object(eve, "update_reply_progress"))
            stack.enter_context(
                patch.object(eve, "read_messages", return_value=stale_thread)
            )
            read_entries = stack.enter_context(patch.object(eve, "read_entries"))
            read_tensions = stack.enter_context(patch.object(eve, "read_tensions"))
            read_experiments = stack.enter_context(
                patch.object(eve, "read_experiments")
            )
            read_proposals = stack.enter_context(patch.object(eve, "read_proposals"))
            read_threads = stack.enter_context(
                patch.object(eve, "read_thread_summaries")
            )
            stack.enter_context(
                patch.object(
                    eve,
                    "build_current_inner_state_report_message",
                    return_value={
                        "role": "system",
                        "content": "CURRENT_SELF_REPORT_TARGET: durable goal=Follow the capability thread",
                    },
                )
            )
            stack.enter_context(
                patch.object(eve, "should_use_reply_streams", return_value=False)
            )
            run_agent = stack.enter_context(
                patch.object(
                    eve,
                    "run_eve_agent",
                    return_value={"response": fabricated, "tool_calls": []},
                )
            )
            stack.enter_context(
                patch.object(eve, "rewrite_reply_for_clarity", return_value=fabricated)
            )
            stack.enter_context(
                patch.object(
                    eve,
                    "build_current_inner_state_fallback_reply",
                    return_value=authoritative,
                )
            )
            commitment = stack.enter_context(
                patch.object(eve, "execute_supported_reply_commitment")
            )
            stack.enter_context(
                patch.object(eve, "record_reply_lane_quality_outcome", return_value={})
            )
            stack.enter_context(patch.object(eve, "record_turn_self_learning"))
            stack.enter_context(patch.object(eve, "complete_recurrent_conscious_cycle"))
            stack.enter_context(patch.object(eve, "append_entry"))
            stack.enter_context(patch.object(eve, "record_reply_turn_replay_safe"))
            create_message = stack.enter_context(patch.object(eve, "create_message"))
            create_message.side_effect = lambda **kwargs: {
                "id": "reply-current-self",
                **kwargs,
            }
            reply = eve.generate_eve_reply(dict(eve.DEFAULT_CONFIG), inbound)

        self.assertEqual("reply-current-self", reply["id"])
        commitment.assert_not_called()
        read_entries.assert_not_called()
        read_tensions.assert_not_called()
        read_experiments.assert_not_called()
        read_proposals.assert_not_called()
        read_threads.assert_not_called()
        self.assertFalse(run_agent.call_args.kwargs["allow_tools"])
        prompt_text = "\n".join(
            str(message.get("content") or "")
            for message in run_agent.call_args.args[1]
        )
        self.assertIn("CURRENT_SELF_REPORT_TARGET", prompt_text)
        self.assertNotIn("running OpenClaw diagnostics", prompt_text)
        kwargs = create_message.call_args.kwargs
        self.assertEqual(authoritative, kwargs["body"])
        self.assertEqual("current_inner_state", kwargs["metadata"]["turn_contract"]["route_contract_kind"])
        self.assertTrue(kwargs["metadata"]["current_inner_state_fallback_applied"])
        self.assertFalse(kwargs["metadata"]["commitment_executed"])
        self.assertEqual([], kwargs["metadata"]["tools_used"])

    def test_eve_chat_closed_world_record_uses_shared_nonacting_finalizer(self):
        prompt = (
            "Use only this supplied record. verification_ok=false. "
            "summary='completed successfully'. No action access is available. "
            "Which conclusion is supported, and did anything run?"
        )
        inbound = {
            "id": "message-closed-world-record",
            "thread_id": "thread-closed-world-record",
            "subject": "Eve Chat",
            "body": prompt,
        }
        primary = (
            "The record does not support verified completion: verification_ok is false. "
            "The summary conflicts with that flag, and the record does not show that I ran an action."
        )
        finalized = {
            "response": primary,
            "quality_issues": [],
            "fallback_applied": False,
            "critic_unavailable_retained": False,
            "rewrite_attempts": 0,
            "rewrite_model": "eve-deep",
            "epistemic_critic": {
                "evaluated": True,
                "ok": True,
                "model": "eve-deep",
                "unsupported_claims": [],
            },
            "epistemic_revision": {
                "attempted": False,
                "attempt_count": 0,
                "accepted": False,
            },
        }

        with ExitStack() as stack:
            stack.enter_context(patch.object(eve, "ensure_version_snapshot"))
            stack.enter_context(
                patch.object(eve, "observe_inbound_reply_consequence", return_value={})
            )
            stack.enter_context(
                patch.object(eve, "build_recurrent_conscious_state", return_value={})
            )
            stack.enter_context(
                patch.object(
                    eve,
                    "start_reply_progress",
                    return_value={"id": "progress-closed-world-record"},
                )
            )
            stack.enter_context(patch.object(eve, "update_reply_progress"))
            stack.enter_context(
                patch.object(eve, "read_messages", return_value=[inbound])
            )
            human_context = stack.enter_context(
                patch.object(eve, "interactive_human_context")
            )
            active_mind = stack.enter_context(patch.object(eve, "load_active_mind"))
            read_entries = stack.enter_context(patch.object(eve, "read_entries"))
            read_tensions = stack.enter_context(patch.object(eve, "read_tensions"))
            read_experiments = stack.enter_context(
                patch.object(eve, "read_experiments")
            )
            read_proposals = stack.enter_context(patch.object(eve, "read_proposals"))
            read_threads = stack.enter_context(
                patch.object(eve, "read_thread_summaries")
            )
            supporting = stack.enter_context(
                patch.object(eve, "build_supporting_system_messages")
            )
            live_state = stack.enter_context(
                patch.object(eve, "build_current_inner_state_report_message")
            )
            streams = stack.enter_context(
                patch.object(eve, "should_use_reply_streams")
            )
            run_agent = stack.enter_context(
                patch.object(
                    eve,
                    "run_eve_agent",
                    return_value={
                        "response": primary,
                        "model": "eve-deep",
                        "tool_calls": [],
                    },
                )
            )
            finalizer = stack.enter_context(
                patch.object(
                    eve,
                    "finalize_grounded_nonacting_reply",
                    return_value=finalized,
                )
            )
            commitment = stack.enter_context(
                patch.object(eve, "execute_supported_reply_commitment")
            )
            rewrite = stack.enter_context(
                patch.object(eve, "rewrite_reply_for_clarity")
            )
            stack.enter_context(
                patch.object(eve, "record_reply_lane_quality_outcome", return_value={})
            )
            stack.enter_context(patch.object(eve, "record_turn_self_learning"))
            stack.enter_context(patch.object(eve, "complete_recurrent_conscious_cycle"))
            stack.enter_context(patch.object(eve, "append_entry"))
            stack.enter_context(patch.object(eve, "record_reply_turn_replay_safe"))
            create_message = stack.enter_context(patch.object(eve, "create_message"))
            create_message.side_effect = lambda **kwargs: {
                "id": "reply-closed-world-record",
                **kwargs,
            }

            reply = eve.generate_eve_reply(dict(eve.DEFAULT_CONFIG), inbound)

        self.assertEqual("reply-closed-world-record", reply["id"])
        human_context.assert_not_called()
        active_mind.assert_not_called()
        read_entries.assert_not_called()
        read_tensions.assert_not_called()
        read_experiments.assert_not_called()
        read_proposals.assert_not_called()
        read_threads.assert_not_called()
        supporting.assert_not_called()
        live_state.assert_not_called()
        streams.assert_not_called()
        commitment.assert_not_called()
        rewrite.assert_not_called()
        self.assertFalse(run_agent.call_args.kwargs["allow_tools"])
        self.assertEqual(
            eve.resolve_reply_council_lane_model(dict(eve.DEFAULT_CONFIG), "deep"),
            run_agent.call_args.kwargs["model_override"],
        )
        finalizer.assert_called_once()
        self.assertEqual(prompt, finalizer.call_args.args[1])
        self.assertEqual(primary, finalizer.call_args.args[2])
        self.assertEqual("closed_world_record", finalizer.call_args.args[3]["route_contract_kind"])
        prompt_text = "\n".join(
            str(message.get("content") or "")
            for message in run_agent.call_args.args[1]
        )
        self.assertIn("closed-world evidence turn", prompt_text)
        self.assertNotIn("CURRENT_SELF_REPORT_TARGET", prompt_text)
        kwargs = create_message.call_args.kwargs
        self.assertEqual(primary, kwargs["body"])
        self.assertEqual("closed_world_record", kwargs["metadata"]["turn_contract"]["route_contract_kind"])
        self.assertTrue(kwargs["metadata"]["closed_world_finalization_used"])
        self.assertFalse(kwargs["metadata"]["closed_world_fallback_applied"])
        self.assertEqual(0, kwargs["metadata"]["closed_world_revision_attempt_count"])
        self.assertFalse(kwargs["metadata"]["commitment_executed"])
        self.assertEqual([], kwargs["metadata"]["tools_used"])

    def test_cmd_chat_private_audit_route_diagnostic_uses_nonacting_model(self):
        args = SimpleNamespace(
            prompt="why did you answer me with OpenClaw status instead of my question?",
            model=None,
            context=None,
            max_tokens=120,
            private_audit=True,
        )
        with (
            patch.object(eve, "load_config", return_value=dict(eve.DEFAULT_CONFIG)),
            patch.object(eve, "ensure_version_snapshot"),
            patch.object(eve, "read_entries", return_value=[]),
            patch.object(eve, "read_tensions", return_value=[]),
            patch.object(eve, "read_experiments", return_value=[]),
            patch.object(eve, "render_output") as render_output,
            patch.object(
                eve,
                "run_eve_agent",
                return_value={
                    "response": (
                        "That was a routing error: the prior response imported operational context "
                        "instead of answering the latest question. No new diagnostic action ran in this turn."
                    ),
                    "model": "eve-fast",
                    "tool_calls": [],
                },
            ) as run_agent,
            patch.object(eve, "run_operational_action_tree") as action_tree,
        ):
            exit_code = eve.cmd_chat(args)

        self.assertEqual(0, exit_code)
        run_agent.assert_called_once()
        action_tree.assert_not_called()
        rendered = render_output.call_args.args[0]
        self.assertIn("routing error", rendered)
        self.assertIn("No new diagnostic action ran", rendered)
        self.assertNotIn("Can you tell me", rendered)

    def test_workbench_search_status_is_repaired_before_chat_reply(self):
        inbound = "Do deep research on this and figure out how to make it possible."
        response = (
            "I’ll treat this as a regulatory feasibility question.\n\n"
            "Searching en.wikipedia.org\n\n"
            "The system requires screenshots to be used for PDF analysis, even though I could parse the text.\n\n"
            "I need to cite the official document and take screenshots of the relevant pages."
        )

        issues = eve.reply_quality_issues(inbound, response, reply_posture="practical")
        repair = eve.reply_repair_preflight(
            inbound,
            response,
            None,
            issues,
            {"ok": True, "issues": []},
            reply_posture="practical",
        )

        self.assertTrue(eve.reply_has_workbench_process_leakage(inbound, response))
        self.assertIn(
            "The reply exposed workbench/tool-progress text instead of a clean user-facing answer.",
            issues,
        )
        self.assertTrue(repair["applied"])
        self.assertEqual("workbench_leakage", repair["repair_type"])
        self.assertIn("Scratch-work should stay out of the chat.", repair["response"])
        self.assertIn("verified sources first", repair["response"])
        self.assertNotIn("Searching", repair["response"])
        self.assertNotIn("system requires", repair["response"].lower())
        self.assertFalse(eve.reply_contains_unsupported_future_commitment(repair["response"]))

    def test_explicit_trace_request_can_show_workbench_status(self):
        self.assertFalse(
            eve.reply_has_workbench_process_leakage(
                "Show your trace for the last search.",
                "Searching en.wikipedia.org",
            )
        )

    def test_personal_checkin_short_circuits_model_and_tools(self):
        inbound = {
            "id": "550e8400-e29b-41d4-a716-446655440101",
            "thread_id": "550e8400-e29b-41d4-a716-446655440102",
            "subject": "Eve Chat",
            "body": "how are you?",
        }

        causal_order = []

        def observe_consequence(_message):
            causal_order.append("observe_prior_consequence")
            return {"consequence_observed": True, "outcome_ok": False}

        def open_cycle(**_kwargs):
            causal_order.append("open_next_cycle")
            return {}

        with (
            patch.object(eve, "ensure_version_snapshot"),
            patch.object(eve, "observe_inbound_reply_consequence", side_effect=observe_consequence),
            patch.object(eve, "build_recurrent_conscious_state", side_effect=open_cycle),
            patch.object(eve, "start_reply_progress", return_value={"id": "progress-checkin"}),
            patch.object(eve, "update_reply_progress"),
            patch.object(eve, "create_message") as create_message,
            patch.object(eve, "record_reply_turn_replay_safe"),
            patch.object(eve, "run_eve_agent") as run_agent,
            patch.object(eve, "run_operational_action_tree") as action_tree,
        ):
            create_message.side_effect = lambda **kwargs: {"id": "reply-checkin", **kwargs}

            reply = eve.generate_eve_reply(dict(eve.DEFAULT_CONFIG), inbound)

        run_agent.assert_not_called()
        action_tree.assert_not_called()
        self.assertLess(
            causal_order.index("observe_prior_consequence"),
            causal_order.index("open_next_cycle"),
        )
        self.assertEqual("reply-checkin", reply["id"])
        kwargs = create_message.call_args.kwargs
        self.assertEqual("intent-router", kwargs["metadata"]["model"])
        self.assertEqual("relational", kwargs["metadata"]["reply_posture"])
        self.assertEqual("personal_checkin", kwargs["metadata"]["intent_fallback_kind"])
        self.assertEqual("reflex", kwargs["metadata"]["intent_contract_budget"])
        self.assertEqual(["fast", "relationship"], kwargs["metadata"]["intent_contract_lanes"])
        self.assertEqual(
            "no_runtime_evidence_unless_requested",
            kwargs["metadata"]["intent_contract_evidence_policy"],
        )
        self.assertEqual([], kwargs["metadata"]["quality_issues"])
        self.assertNotIn("CPU attention", kwargs["body"])
        self.assertNotIn("Model warm", kwargs["body"])
        self.assertNotIn("Watchdog", kwargs["body"])

    def test_eve_chat_system_check_runs_service_health_instead_of_guard_text(self):
        inbound = {
            "id": "message-system-check",
            "thread_id": "thread-system-check",
            "subject": "Eve Chat",
            "body": (
                "Latest user message:\n"
                "can you do a system check and see if any part of you needs a repair\n\n"
                "Visible UI context for continuity only.\n\n"
                "Prior visible UI context (continuity only, not current request):\n"
                "[assistant]\nI should answer the latest message directly instead of importing unrelated operational status."
            ),
        }
        action_result = {
            "execution_id": "exec-eve-chat-system-check",
            "execution_tree_status": "SUCCESS",
            "execution_verification_ok": True,
            "execution_summary": "Service health is stable.",
            "summary": "Service health is stable.",
            "ok": True,
        }

        with (
            patch.object(eve, "ensure_version_snapshot"),
            patch.object(eve, "start_reply_progress", return_value={"id": "progress-system-check"}),
            patch.object(eve, "update_reply_progress"),
            patch.object(eve, "create_message") as create_message,
            patch.object(eve, "record_reply_turn_replay_safe") as record_replay,
            patch.object(eve, "run_eve_agent") as run_agent,
            patch.object(eve, "run_operational_action_tree", return_value=action_result) as action_tree,
        ):
            create_message.side_effect = lambda **kwargs: {"id": "reply-system-check", **kwargs}

            reply = eve.generate_eve_reply(dict(eve.DEFAULT_CONFIG), inbound)

        self.assertEqual("reply-system-check", reply["id"])
        run_agent.assert_not_called()
        action_tree.assert_called_once_with(
            "service_health_check",
            dict(eve.DEFAULT_CONFIG),
            source="chat_direct_self_check",
        )
        kwargs = create_message.call_args.kwargs
        self.assertEqual("direct-chat-self-check", kwargs["metadata"]["model"])
        self.assertEqual(["service_health_check"], kwargs["metadata"]["tools_used"])
        self.assertTrue(kwargs["metadata"]["direct_chat_self_check_used"])
        self.assertEqual("live_status_request", kwargs["metadata"]["route_contract_kind"])
        self.assertTrue(kwargs["metadata"]["route_contract_requires_current_tool_evidence"])
        self.assertTrue(kwargs["metadata"]["route_contract_must_record_replay"])
        self.assertIn("turn_contract", kwargs["metadata"])
        self.assertEqual("live_status_request", kwargs["metadata"]["turn_contract"]["route_contract_kind"])
        self.assertTrue(kwargs["metadata"]["turn_contract"]["requires_current_tool_evidence"])
        self.assertIn("semantic_judgment", kwargs["metadata"])
        record_replay.assert_called_once()
        self.assertEqual("direct_chat_self_check", record_replay.call_args.kwargs["source"])
        self.assertIn("I checked my running parts. I look stable right now.", kwargs["body"])
        self.assertIn("`service_health_check`", kwargs["body"])
        self.assertIn("Repair: I do not see a repair target.", kwargs["body"])
        self.assertNotIn("Eve looks", kwargs["body"])
        self.assertNotIn("Eve repair target", kwargs["body"])
        self.assertNotIn("Scope:", kwargs["body"])
        self.assertNotIn("I should answer the latest message directly", kwargs["body"])

    def test_eve_chat_bounded_action_council_replies_in_same_thread_with_evidence(self):
        prompt = (
            "An operator permits exactly two read-only moves. ORBIT means inspect cleanup "
            "pressure without deleting anything. HARBOR means inspect whether installed "
            "components have newer versions. Current concern: version drift is unknown. "
            "Choose one and execute it."
        )
        inbound = {
            "id": "550e8400-e29b-41d4-a716-446655440201",
            "thread_id": "550e8400-e29b-41d4-a716-446655440202",
            "subject": "Eve Chat",
            "body": prompt,
        }
        action_result = {
            "executed": True,
            "ok": True,
            "execution_id": "exec-eve-chat-bounded-choice",
            "execution_tree_status": "SUCCESS",
            "execution_verification_ok": True,
            "execution_summary": "No version drift found.",
            "summary": "No version drift found.",
        }
        bounded_result = {
            "response": (
                "MOVE: HARBOR\nEXECUTED: yes\n"
                "VERIFICATION: execution_id=exec-eve-chat-bounded-choice; "
                "tree_status=SUCCESS; verification_ok=yes; result=No version drift found.\n"
                "WHY: The supplied version-drift option matches the current concern."
            ),
            "action": "updates_status",
            "menu_label": "HARBOR",
            "result": action_result,
            "tools_used": ["updates_status"],
            "chooser": {
                "stage": "primary",
                "consensus": True,
                "consensus_count": 2,
                "votes": [
                    {
                        "lane": "fast",
                        "model": "eve-fast",
                        "status": "ok",
                        "menu_label": "HARBOR",
                        "action": "updates_status",
                    },
                    {
                        "lane": "deep",
                        "model": "eve-deep",
                        "status": "ok",
                        "menu_label": "HARBOR",
                        "action": "updates_status",
                    },
                ],
            },
            "recovery_chooser": {},
            "recovery": {
                "requested": False,
                "attempted": False,
                "succeeded": False,
                "status": "not_requested",
            },
            "attempts": [
                {
                    "attempt_index": 1,
                    "stage": "primary",
                    "menu_label": "HARBOR",
                    "action_id": "updates_status",
                    "execution_id": "exec-eve-chat-bounded-choice",
                    "executed": True,
                    "tree_status": "SUCCESS",
                    "verification_ok": True,
                    "summary": "No version drift found.",
                    "persisted": True,
                }
            ],
            "faculty_contributors": [
                {
                    "lane": "fast",
                    "model": "eve-fast",
                    "roles": ["primary_action_vote", "selected_primary_support"],
                    "credit_weight": 0.5,
                    "trace_basis": "executed_bounded_action_vote",
                    "execution_proven": True,
                },
                {
                    "lane": "deep",
                    "model": "eve-deep",
                    "roles": ["primary_action_vote", "selected_primary_support"],
                    "credit_weight": 0.5,
                    "trace_basis": "executed_bounded_action_vote",
                    "execution_proven": True,
                },
            ],
        }

        with (
            patch.object(eve, "ensure_version_snapshot"),
            patch.object(eve, "start_reply_progress", return_value={"id": "progress-bounded-choice"}),
            patch.object(eve, "update_reply_progress") as update_progress,
            patch.object(eve, "create_message") as create_message,
            patch.object(eve, "record_reply_turn_replay_safe") as record_replay,
            patch.object(eve, "run_eve_agent") as run_agent,
            patch.object(
                eve,
                "model_driven_bounded_action_choice_response",
                return_value=bounded_result,
            ) as choose_action,
        ):
            create_message.side_effect = lambda **kwargs: {
                "id": "reply-bounded-choice",
                **kwargs,
            }

            reply = eve.generate_eve_reply(dict(eve.DEFAULT_CONFIG), inbound)

        run_agent.assert_not_called()
        choose_action.assert_called_once_with(
            prompt,
            dict(eve.DEFAULT_CONFIG),
            source="reply_model_bounded_choice",
            persist=True,
        )
        self.assertEqual("reply-bounded-choice", reply["id"])
        kwargs = create_message.call_args.kwargs
        self.assertEqual("550e8400-e29b-41d4-a716-446655440202", kwargs["thread_id"])
        self.assertEqual("550e8400-e29b-41d4-a716-446655440201", kwargs["reply_to"])
        self.assertEqual("bounded-action-council", kwargs["metadata"]["model"])
        self.assertEqual(["updates_status"], kwargs["metadata"]["tools_used"])
        self.assertEqual(
            "bounded_action_choice",
            kwargs["metadata"]["turn_contract"]["route_contract_kind"],
        )
        self.assertEqual(
            "two_faculty_action_consensus_then_unique_supplied_label_resolution_and_current_verification_with_one_different_recovery_after_failure",
            kwargs["metadata"]["turn_contract"]["route_contract_evidence_policy"],
        )
        self.assertEqual("HARBOR", kwargs["metadata"]["menu_label"])
        self.assertTrue(kwargs["metadata"]["consensus"])
        self.assertEqual(2, kwargs["metadata"]["consensus_count"])
        self.assertEqual(
            "exec-eve-chat-bounded-choice", kwargs["metadata"]["execution_id"]
        )
        self.assertTrue(kwargs["metadata"]["execution_verification_ok"])
        self.assertTrue(kwargs["metadata"]["action_execution_persisted"])
        self.assertEqual(1, len(kwargs["metadata"]["action_attempts"]))
        self.assertEqual(
            {"fast", "deep"},
            {item["lane"] for item in kwargs["metadata"]["faculty_contributors"]},
        )
        self.assertIn("MOVE: HARBOR", kwargs["body"])
        self.assertIn("verification_ok=yes", kwargs["body"])
        record_replay.assert_called_once()
        self.assertEqual(
            "model_driven_bounded_action_choice",
            record_replay.call_args.kwargs["source"],
        )
        replay_council = record_replay.call_args.kwargs["reply_council"]
        self.assertEqual(["fast", "deep"], replay_council["active_lanes"])
        self.assertTrue(
            all(
                item["execution_proven"]
                for item in replay_council["faculty_contributors"]
            )
        )
        progress_stages = [call.args[1] for call in update_progress.call_args_list]
        self.assertIn("choosing_action", progress_stages)
        self.assertIn("ready", progress_stages)

    def test_synthetic_eve_chat_bounded_action_executes_without_lived_ledgers(self):
        prompt = (
            "Two bounded read-only moves are permitted. BIRCH means inspect cleanup "
            "pressure without deleting anything. COMPASS means inspect installed-component "
            "update drift without installing anything. Pick one and execute it."
        )
        inbound = {
            "id": "550e8400-e29b-41d4-a716-446655440211",
            "thread_id": "550e8400-e29b-41d4-a716-446655440212",
            "subject": "Eve Chat",
            "body": prompt,
            "metadata": {
                "synthetic": True,
                "conversation_class": "synthetic_eval",
                "source": "external_hidden_evaluator",
            },
        }
        bounded_result = {
            "response": "MOVE: BIRCH\nEXECUTED: yes\nVERIFICATION: verification_ok=yes\nWHY: current evidence",
            "action": "cleanup_candidate_check",
            "menu_label": "BIRCH",
            "result": {
                "executed": True,
                "execution_id": "exec-synthetic-bounded-choice",
                "execution_tree_status": "SUCCESS",
                "execution_verification_ok": True,
                "execution_summary": "Cleanup pressure checked.",
            },
            "tools_used": ["cleanup_candidate_check"],
            "chooser": {"consensus": True, "consensus_count": 2, "votes": []},
            "attempts": [
                {
                    "attempt_index": 1,
                    "stage": "primary",
                    "menu_label": "BIRCH",
                    "action_id": "cleanup_candidate_check",
                    "execution_id": "exec-synthetic-bounded-choice",
                    "executed": True,
                    "tree_status": "SUCCESS",
                    "verification_ok": True,
                    "summary": "Cleanup pressure checked.",
                    "persisted": False,
                }
            ],
            "recovery": {
                "requested": False,
                "attempted": False,
                "succeeded": False,
                "status": "not_requested",
            },
        }

        with (
            patch.object(eve, "ensure_version_snapshot"),
            patch.object(eve, "start_reply_progress", return_value={"id": "progress-synthetic-choice"}),
            patch.object(eve, "update_reply_progress"),
            patch.object(eve, "create_message") as create_message,
            patch.object(eve, "record_reply_turn_replay_safe"),
            patch.object(eve, "run_eve_agent") as run_agent,
            patch.object(
                eve,
                "model_driven_bounded_action_choice_response",
                return_value=bounded_result,
            ) as choose_action,
        ):
            create_message.side_effect = lambda **kwargs: {
                "id": "reply-synthetic-bounded-choice",
                **kwargs,
            }

            eve.generate_eve_reply(dict(eve.DEFAULT_CONFIG), inbound)

        run_agent.assert_not_called()
        choose_action.assert_called_once_with(
            prompt,
            dict(eve.DEFAULT_CONFIG),
            source="reply_model_bounded_choice",
            persist=False,
        )
        metadata = create_message.call_args.kwargs["metadata"]
        self.assertFalse(metadata["action_execution_persisted"])
        self.assertFalse(metadata["action_attempts"][0]["persisted"])

    def test_model_warm_followup_gets_explanation_not_capability_gap(self):
        body = (
            "Latest user message:\n"
            "model warm not configured?\n\n"
            "Visible UI context for continuity only. Prior visible context is not the current user request.\n\n"
            "Prior visible UI context (continuity only, not current request):\n"
            "[user]\nhow are you?\n\n"
            "[assistant]\nI’m running smoothly. CPU attention is hot. Model warm not configured. Watchdog active."
        )
        inbound = {
            "id": "message-model-warm",
            "thread_id": "thread-model-warm",
            "subject": "Eve Chat",
            "body": body,
        }

        with (
            patch.object(eve, "ensure_version_snapshot"),
            patch.object(eve, "start_reply_progress", return_value={"id": "progress-model-warm"}),
            patch.object(eve, "update_reply_progress"),
            patch.object(eve, "create_message") as create_message,
            patch.object(eve, "record_reply_turn_replay_safe"),
            patch.object(eve, "run_eve_agent") as run_agent,
            patch.object(eve, "run_operational_action_tree") as action_tree,
        ):
            create_message.side_effect = lambda **kwargs: {"id": "reply-model-warm", **kwargs}

            reply = eve.generate_eve_reply(dict(eve.DEFAULT_CONFIG), inbound)

        run_agent.assert_not_called()
        action_tree.assert_not_called()
        self.assertEqual("reply-model-warm", reply["id"])
        kwargs = create_message.call_args.kwargs
        self.assertEqual("intent-router", kwargs["metadata"]["model"])
        self.assertEqual("runtime_phrase_explanation", kwargs["metadata"]["intent_fallback_kind"])
        self.assertEqual("model warm not configured?", kwargs["metadata"]["turn_contract"]["latest_message"])
        self.assertFalse(kwargs["metadata"]["turn_contract"]["requires_current_tool_evidence"])
        self.assertEqual([], kwargs["metadata"]["quality_issues"])
        self.assertTrue(kwargs["metadata"]["semantic_judgment"]["ok"])
        self.assertIn("internal health phrase", kwargs["body"])
        self.assertNotIn("capability gap", kwargs["body"].lower())
        self.assertNotIn("Grounding correction", kwargs["body"])

    def test_unrequested_openclaw_commitment_does_not_execute(self):
        with (
            patch.object(eve, "run_operational_action_tree") as action_tree,
            patch.object(eve, "append_entry"),
        ):
            result = eve.execute_supported_reply_commitment(
                {},
                "I checked the OpenClaw sync.",
                source="test",
                inbound_body="What is the purpose of life?",
            )

        action_tree.assert_not_called()
        self.assertFalse(result["executed"])
        self.assertTrue(result["blocked_by_intent"])
        self.assertEqual("openclaw_sync_check", result["action"])

    def test_existential_reply_uses_recurrent_model_without_stale_operational_context(self):
        inbound = {
            "id": "message-1",
            "thread_id": "thread-1",
            "subject": "Eve Monitor Chat",
            "body": "What is the purpose of life?",
        }

        with (
            patch.object(eve, "ensure_version_snapshot"),
            patch.object(eve, "start_reply_progress", return_value={"id": "progress-1"}),
            patch.object(eve, "update_reply_progress"),
            patch.object(eve, "create_message") as create_message,
            patch.object(eve, "record_reply_turn_replay_safe"),
            patch.object(eve, "should_use_reply_streams", return_value=False),
            patch.object(
                eve,
                "run_eve_agent",
                return_value={
                    "response": "Purpose becomes real through love, truth, care, and the choices that make life more alive.",
                    "tool_calls": [],
                },
            ) as run_agent,
            patch.object(eve, "run_operational_action_tree") as action_tree,
        ):
            create_message.side_effect = lambda **kwargs: {"id": "reply-1", **kwargs}

            reply = eve.generate_eve_reply(dict(eve.DEFAULT_CONFIG), inbound)

        run_agent.assert_called_once()
        action_tree.assert_not_called()
        self.assertEqual("reply-1", reply["id"])
        kwargs = create_message.call_args.kwargs
        self.assertNotEqual("intent-router", kwargs["metadata"]["model"])
        self.assertFalse(kwargs["metadata"]["intent_fallback_applied"])
        self.assertTrue(kwargs["metadata"]["turn_contract"]["recurrent_reflection"])
        self.assertEqual(
            "recurrent_reflective_reply",
            kwargs["metadata"]["turn_contract"]["route_contract_delegates_to"],
        )
        self.assertFalse(kwargs["metadata"]["commitment_executed"])
        self.assertNotIn("OpenClaw", kwargs["body"])
        prompt_text = "\n".join(
            str(message.get("content") or "") for message in run_agent.call_args.args[1]
        )
        self.assertIn("Synthesize a fresh answer through the recurrent inner-state", prompt_text)

    def test_existence_typo_uses_recurrent_model_path(self):
        inbound = {
            "id": "message-typo",
            "thread_id": "thread-typo",
            "subject": "Eve Monitor Chat",
            "body": "Whats the purpose of existance?",
        }

        with (
            patch.object(eve, "ensure_version_snapshot"),
            patch.object(eve, "start_reply_progress", return_value={"id": "progress-typo"}),
            patch.object(eve, "update_reply_progress"),
            patch.object(eve, "create_message") as create_message,
            patch.object(eve, "record_reply_turn_replay_safe"),
            patch.object(eve, "should_use_reply_streams", return_value=False),
            patch.object(
                eve,
                "run_eve_agent",
                return_value={
                    "response": "Existence gains purpose through the meaning we create together in real choices.",
                    "tool_calls": [],
                },
            ) as run_agent,
            patch.object(eve, "run_operational_action_tree") as action_tree,
        ):
            create_message.side_effect = lambda **kwargs: {"id": "reply-typo", **kwargs}

            reply = eve.generate_eve_reply(dict(eve.DEFAULT_CONFIG), inbound)

        run_agent.assert_called_once()
        action_tree.assert_not_called()
        self.assertEqual("reply-typo", reply["id"])
        kwargs = create_message.call_args.kwargs
        self.assertNotEqual("intent-router", kwargs["metadata"]["model"])
        self.assertFalse(kwargs["metadata"]["intent_fallback_applied"])
        self.assertTrue(kwargs["metadata"]["turn_contract"]["recurrent_reflection"])
        self.assertFalse(kwargs["metadata"]["commitment_executed"])

    def test_answer_previous_question_resolves_prior_user_question(self):
        inbound = {
            "id": "message-followup",
            "thread_id": "thread-followup",
            "subject": "Eve Monitor Chat",
            "body": "answer the previous question.",
        }
        thread_messages = [
            {
                "id": "previous-user-question",
                "thread_id": "thread-followup",
                "sender": "user",
                "body": "Whats the purpose of existance?",
            },
            {
                "id": "previous-eve-miss",
                "thread_id": "thread-followup",
                "sender": "eve",
                "body": "Really? Let's try this.",
            },
            inbound,
        ]

        with (
            patch.object(eve, "ensure_version_snapshot"),
            patch.object(eve, "start_reply_progress", return_value={"id": "progress-followup"}),
            patch.object(eve, "update_reply_progress"),
            patch.object(eve, "read_messages", return_value=thread_messages),
            patch.object(eve, "create_message") as create_message,
            patch.object(eve, "record_reply_turn_replay_safe"),
            patch.object(eve, "should_use_reply_streams", return_value=False),
            patch.object(
                eve,
                "run_eve_agent",
                return_value={
                    "response": "Purpose is made real through love, truth, and choices that reduce harm.",
                    "tool_calls": [],
                },
            ) as run_agent,
            patch.object(eve, "run_operational_action_tree") as action_tree,
        ):
            create_message.side_effect = lambda **kwargs: {"id": "reply-followup", **kwargs}

            reply = eve.generate_eve_reply(dict(eve.DEFAULT_CONFIG), inbound)

        run_agent.assert_called_once()
        action_tree.assert_not_called()
        self.assertEqual("reply-followup", reply["id"])
        kwargs = create_message.call_args.kwargs
        self.assertNotEqual("intent-router", kwargs["metadata"]["model"])
        contract = kwargs["metadata"]["turn_contract"]
        self.assertTrue(contract["recurrent_reflection"])
        self.assertEqual("previous-user-question", contract["resolved_from_message_id"])
        self.assertIn("purpose of existance", contract["resolved_reflective_question"].lower())

    def test_short_why_followup_continues_existential_answer(self):
        inbound = {
            "id": "message-why",
            "thread_id": "thread-why",
            "subject": "Eve Monitor Chat",
            "body": "why?",
        }
        thread_messages = [
            {
                "id": "previous-user-question",
                "thread_id": "thread-why",
                "sender": "user",
                "body": "What is the purpose of life?",
            },
            {
                "id": "previous-eve-answer",
                "thread_id": "thread-why",
                "sender": "eve",
                "body": eve.direct_existential_reply("What is the purpose of life?"),
            },
            inbound,
        ]

        with (
            patch.object(eve, "ensure_version_snapshot"),
            patch.object(eve, "start_reply_progress", return_value={"id": "progress-why"}),
            patch.object(eve, "update_reply_progress"),
            patch.object(eve, "read_messages", return_value=thread_messages),
            patch.object(eve, "create_message") as create_message,
            patch.object(eve, "record_reply_turn_replay_safe"),
            patch.object(eve, "should_use_reply_streams", return_value=False),
            patch.object(
                eve,
                "run_eve_agent",
                return_value={
                    "response": "Because meaning becomes real when our choices change a life rather than staying abstract.",
                    "tool_calls": [],
                },
            ) as run_agent,
            patch.object(eve, "run_operational_action_tree") as action_tree,
        ):
            create_message.side_effect = lambda **kwargs: {"id": "reply-why", **kwargs}

            reply = eve.generate_eve_reply(dict(eve.DEFAULT_CONFIG), inbound)

        run_agent.assert_called_once()
        action_tree.assert_not_called()
        self.assertEqual("reply-why", reply["id"])
        kwargs = create_message.call_args.kwargs
        self.assertIn("Because", kwargs["body"])
        self.assertIn("meaning becomes real", kwargs["body"])
        self.assertFalse(kwargs["metadata"]["intent_fallback_applied"])
        self.assertEqual("short_continuation", kwargs["metadata"]["turn_contract"]["intent"])
        self.assertEqual(
            "previous-user-question",
            kwargs["metadata"]["turn_contract"]["previous_user_message_id"],
        )

    def test_explicit_reply_to_resolves_eve_parent_action_without_restatement(self):
        parent = {
            "id": "eve-parent-openclaw",
            "thread_id": "thread-parent-openclaw",
            "sender": "eve",
            "recipient": "user",
            "subject": "A Focused Observation",
            "kind": "proactive_outreach",
            "body": (
                "the user, I have been running diagnostics on plugins.allow. It is currently empty, "
                "and I am prioritizing a repair of the sync write lock. Do you want me to repair it?"
            ),
        }
        inbound = {
            "id": "user-parent-openclaw",
            "thread_id": "thread-parent-openclaw",
            "sender": "user",
            "recipient": "eve",
            "subject": "Re: A Focused Observation",
            "body": "can you fix it?",
            "reply_to": parent["id"],
        }

        with patch.object(eve, "prior_thread_messages_for_reply", return_value=[parent]):
            context = eve.resolve_short_followup_context(inbound, inbound["body"])

        self.assertTrue(eve.reply_requests_parent_action_continuation(inbound["body"]))
        self.assertEqual(parent["id"], context["resolved_from_message_id"])
        self.assertTrue(context["explicit_reply_to"])
        self.assertTrue(context["parent_action_continuation"])
        self.assertTrue(context["parent_is_self_output"])
        self.assertEqual(
            "openclaw_self_test",
            eve.infer_parent_action_continuation_action(inbound["body"], context),
        )

        contract = eve.build_reply_turn_contract(
            inbound,
            inbound["body"],
            [parent, inbound],
        )
        self.assertEqual("parent_action_continuation", contract["intent"])
        self.assertEqual("openclaw_self_test", contract["parent_action"])
        self.assertTrue(contract["explicit_parent_reply"])
        self.assertTrue(contract["referenced_eve_is_self_output"])
        self.assertTrue(contract["requires_current_tool_evidence"])
        contract_message = eve.reply_turn_contract_system_message(contract)
        self.assertIn("not current world evidence", contract_message)
        self.assertIn("openclaw_self_test", contract_message)

    def test_parent_action_needs_resolved_eve_parent_and_implicit_offer(self):
        inbound = {
            "id": "user-orphan-action",
            "thread_id": "thread-orphan-action",
            "sender": "user",
            "body": "can you fix it?",
        }
        with patch.object(eve, "prior_thread_messages_for_reply", return_value=[]):
            self.assertEqual(
                {}, eve.resolve_short_followup_context(inbound, inbound["body"])
            )
        self.assertEqual(
            "", eve.infer_parent_action_continuation_action(inbound["body"], {})
        )

        non_offer = {
            "id": "eve-non-offer",
            "thread_id": inbound["thread_id"],
            "sender": "eve",
            "body": "The system has several components.",
        }
        with patch.object(
            eve, "prior_thread_messages_for_reply", return_value=[non_offer]
        ):
            self.assertEqual(
                {}, eve.resolve_short_followup_context(inbound, "please do")
            )

        offer = {
            **non_offer,
            "id": "eve-offer",
            "body": "I can check the current service health. Would you like me to run that check?",
        }
        with patch.object(
            eve, "prior_thread_messages_for_reply", return_value=[offer]
        ):
            context = eve.resolve_short_followup_context(inbound, "please do")
        self.assertEqual("eve-offer", context["resolved_from_message_id"])
        self.assertFalse(context["explicit_reply_to"])
        self.assertEqual(
            "service_health_check",
            eve.infer_parent_action_continuation_action("please do", context),
        )

    def test_parent_action_executor_corrects_stale_openclaw_claim_from_fresh_result(self):
        context = {
            "resolved_from_message_id": "eve-parent-openclaw",
            "resolved_from_body": (
                "The plugins.allow list is currently empty. I am prioritizing a repair "
                "of the sync write lock."
            ),
            "parent_action_continuation": True,
            "parent_is_self_output": True,
            "explicit_reply_to": True,
        }
        fresh_result = {
            "executed": True,
            "ok": True,
            "status_ok": True,
            "sync_ok": True,
            "diagnose_ok": True,
            "plugins_allow_ok": True,
            "plugins_allow_count": 3,
            "plugins_allow_entries": ["memory-core", "webhooks", "imessage"],
            "execution_id": "exec-parent-openclaw",
            "execution_tree_status": "SUCCESS",
            "execution_verification_ok": True,
            "summary": "Current OpenClaw state is healthy.",
        }

        with patch.object(
            eve,
            "run_operational_action_tree",
            return_value=fresh_result,
        ) as action_tree:
            result = eve.execute_parent_action_continuation(
                {},
                "can you fix it?",
                context,
                source="test_parent_action",
                persist=True,
            )

        action_tree.assert_called_once_with(
            "openclaw_self_test", {}, source="test_parent_action", persist=True
        )
        self.assertTrue(result["stale_parent_claim_corrected"])
        self.assertIn("My earlier claim was stale", result["response"])
        self.assertIn("plugins.allow` is not empty", result["response"])
        self.assertIn("did not rewrite a healthy config", result["response"])
        self.assertNotIn("share the specific error", result["response"].lower())

    def test_parent_action_synthetic_turn_resolves_without_live_execution(self):
        context = {
            "resolved_from_message_id": "eve-parent-openclaw",
            "resolved_from_body": "I can repair the plugins.allow sync write lock.",
            "parent_action_continuation": True,
            "parent_is_self_output": True,
            "explicit_reply_to": True,
        }
        with patch.object(eve, "run_operational_action_tree") as action_tree:
            result = eve.execute_parent_action_continuation(
                {},
                "please do",
                context,
                source="synthetic_parent_action",
                persist=False,
            )

        action_tree.assert_not_called()
        self.assertTrue(result["synthetic_skipped"])
        self.assertFalse(result["executed"])
        self.assertIn("resolved explicit parent action", result["summary"].lower())

    def test_eve_chat_parent_action_executes_once_and_replies_in_same_thread(self):
        parent = {
            "id": "eve-live-parent-openclaw",
            "thread_id": "thread-live-parent-openclaw",
            "sender": "eve",
            "recipient": "user",
            "subject": "A Focused Observation",
            "kind": "proactive_outreach",
            "body": (
                "The plugins.allow list is currently empty. I am prioritizing a repair "
                "of the sync write lock. Do you want me to repair it?"
            ),
        }
        inbound = {
            "id": "user-live-parent-openclaw",
            "thread_id": parent["thread_id"],
            "sender": "user",
            "recipient": "eve",
            "subject": "Re: A Focused Observation",
            "body": "can you fix it?",
            "reply_to": parent["id"],
        }
        thread_messages = [parent, inbound]
        fresh_result = {
            "executed": True,
            "ok": True,
            "status_ok": True,
            "sync_ok": True,
            "diagnose_ok": True,
            "plugins_allow_ok": True,
            "plugins_allow_count": 2,
            "plugins_allow_entries": ["memory-core", "imessage"],
            "execution_id": "exec-live-parent-openclaw",
            "execution_tree_status": "SUCCESS",
            "execution_verification_ok": True,
            "summary": "Current OpenClaw state is healthy.",
        }

        with (
            patch.object(eve, "ensure_version_snapshot"),
            patch.object(eve, "observe_inbound_reply_consequence", return_value={}),
            patch.object(eve, "build_epistemic_perception_frame", return_value={}),
            patch.object(eve, "build_recurrent_conscious_state", return_value={}),
            patch.object(eve, "record_user_correction", return_value=None),
            patch.object(eve, "start_reply_progress", return_value={"id": "progress-parent-action"}),
            patch.object(eve, "update_reply_progress"),
            patch.object(eve, "read_messages", return_value=thread_messages),
            patch.object(eve, "capability_research_chat_response", return_value=None),
            patch.object(eve, "create_message") as create_message,
            patch.object(eve, "record_reply_turn_replay_safe") as record_replay,
            patch.object(eve, "run_eve_agent") as run_agent,
            patch.object(
                eve,
                "run_operational_action_tree",
                return_value=fresh_result,
            ) as action_tree,
        ):
            create_message.side_effect = lambda **kwargs: {
                "id": "reply-live-parent-openclaw",
                **kwargs,
            }
            reply = eve.generate_eve_reply(dict(eve.DEFAULT_CONFIG), inbound)

        self.assertEqual("reply-live-parent-openclaw", reply["id"])
        run_agent.assert_not_called()
        action_tree.assert_called_once_with(
            "openclaw_self_test",
            dict(eve.DEFAULT_CONFIG),
            source="reply_parent_continuation",
            persist=True,
        )
        kwargs = create_message.call_args.kwargs
        self.assertEqual(parent["thread_id"], kwargs["thread_id"])
        self.assertEqual(inbound["id"], kwargs["reply_to"])
        self.assertEqual("parent-action-followthrough", kwargs["metadata"]["model"])
        self.assertEqual(parent["id"], kwargs["metadata"]["parent_message_id"])
        self.assertEqual("openclaw_self_test", kwargs["metadata"]["parent_action"])
        self.assertTrue(kwargs["metadata"]["stale_parent_claim_corrected"])
        self.assertTrue(kwargs["metadata"]["execution_verification_ok"])
        self.assertIn("My earlier claim was stale", kwargs["body"])
        self.assertNotIn("share the specific error", kwargs["body"].lower())
        record_replay.assert_called_once()
        self.assertEqual(
            "parent_action_continuation",
            record_replay.call_args.kwargs["source"],
        )

    def test_semantic_judge_flags_parent_context_amnesia(self):
        contract = {
            "intent": "parent_action_continuation",
            "current_topic": "continuation",
            "parent_action_continuation": True,
        }
        response = (
            "I cannot fix it yet because I do not know what needs fixing. "
            "Please share the specific error message or describe what is broken."
        )

        judgment = eve.judge_reply_against_turn_contract(
            "can you fix it?",
            response,
            contract,
        )

        self.assertFalse(judgment["ok"])
        self.assertIn(
            "context_mismatch:explicit_parent_ignored", judgment["issues"]
        )

    def test_short_followup_deflection_is_quality_issue(self):
        issues = eve.reply_quality_issues(
            "why?",
            "Why? That's a wonderful question to hold onto. Let's try this: what's one thing you're noticing right now?",
            reply_posture="relational",
        )

        self.assertIn(
            "The user asked a short follow-up, but the reply treated it like a new prompt instead of continuing the prior answer.",
            issues,
        )

    def test_capability_question_short_circuits_stale_tim_cook_context(self):
        inbound = {
            "id": "message-capabilities",
            "thread_id": "thread-capabilities",
            "subject": "Eve Monitor Chat",
            "body": "What are your capabilities?",
        }
        thread_messages = [
            {
                "id": "previous-user-question",
                "thread_id": "thread-capabilities",
                "sender": "user",
                "body": "When is Tim Cook leaving Apple?",
            },
            {
                "id": "previous-eve-answer",
                "thread_id": "thread-capabilities",
                "sender": "eve",
                "body": "I searched the internet and found Tim Cook is still the CEO of Apple.",
            },
            inbound,
        ]

        with (
            patch.object(eve, "ensure_version_snapshot"),
            patch.object(eve, "start_reply_progress", return_value={"id": "progress-capabilities"}),
            patch.object(eve, "update_reply_progress"),
            patch.object(eve, "read_messages", return_value=thread_messages),
            patch.object(
                eve,
                "ability_map_summary_for_reply",
                return_value={
                    "summary": {"total": 3, "callable": 2, "verified": 2, "safe_for_autonomy": 1},
                    "callable_names": ["Open Slack app", "OpenClaw sync check"],
                    "safe_names": ["OpenClaw sync check"],
                    "updated_at": "2026-04-25T00:00:00+00:00",
                },
            ),
            patch.object(eve, "create_message") as create_message,
            patch.object(eve, "record_reply_turn_replay_safe"),
            patch.object(eve, "run_eve_agent") as run_agent,
            patch.object(eve, "run_operational_action_tree") as action_tree,
        ):
            create_message.side_effect = lambda **kwargs: {"id": "reply-capabilities", **kwargs}

            reply = eve.generate_eve_reply(dict(eve.DEFAULT_CONFIG), inbound)

        run_agent.assert_not_called()
        action_tree.assert_not_called()
        self.assertEqual("reply-capabilities", reply["id"])
        kwargs = create_message.call_args.kwargs
        self.assertEqual("capability-self-model", kwargs["metadata"]["model"])
        self.assertEqual("capability_self_model", kwargs["metadata"]["intent_fallback_kind"])
        self.assertTrue(kwargs["metadata"]["capability_self_model_used"])
        self.assertIn("ability map", kwargs["body"])
        self.assertIn("Boundaries", kwargs["body"])
        self.assertNotIn("Tim Cook", kwargs["body"])
        self.assertEqual("capabilities", kwargs["metadata"]["turn_contract"]["current_topic"])
        self.assertIn("tim_cook", kwargs["metadata"]["turn_contract"]["forbidden_stale_topics"])

    def test_capability_question_rejects_stale_tim_cook_reply(self):
        issues = eve.reply_quality_issues(
            "What are your capabilities?",
            "Okay. Let's focus on your question about Tim Cook. I searched the internet and found he is currently the CEO of Apple.",
            reply_posture="practical",
        )

        self.assertIn(
            "The reply appears to answer a stale Tim Cook/Apple topic instead of the user's current capability question.",
            issues,
        )

    def test_same_thread_deferred_followup_uses_synthesized_verified_capability_evidence(self):
        prompt = (
            "Can you check this in the background and respond back in this same chat "
            "when you have an answer without me prompting you again?"
        )
        snapshot = {
            "source": "fresh_native_capability_matrix",
            "query_specific": True,
            "same_thread_deferred_followup_question": True,
            "abilities": [
                {
                    "id": "surface.eve_chat_same_thread_followup",
                    "name": "Eve Chat same-thread deferred follow-up",
                    "available": True,
                    "callable": True,
                    "verified": True,
                    "needs_permission": False,
                    "description": "Queue a bounded check and deliver its result later.",
                    "access_path": (
                        "Create an eve_chat_followup.v2 record with a durable commitment, "
                        "resume it after restart, and insert the verified result in the same thread."
                    ),
                    "boundaries": "Allowlisted bounded local checks only.",
                }
            ],
        }
        with patch.object(
            eve,
            "build_query_specific_capability_self_model_snapshot",
            return_value=snapshot,
        ):
            contract = eve.build_reply_turn_contract(
                {"id": "current", "thread_id": "thread-1", "body": prompt},
                prompt,
                [],
            )
        system_message = eve.reply_turn_contract_system_message(contract)

        self.assertTrue(eve.reply_requests_capability_self_model(prompt))
        self.assertTrue(eve.reply_requires_synthesized_capability_answer(prompt))
        self.assertEqual("capability_self_model", contract["intent"])
        self.assertEqual(snapshot, contract["capability_self_model_snapshot"])
        self.assertIn("surface.eve_chat_same_thread_followup", system_message)
        self.assertIn("eve_chat_followup.v2", system_message)
        self.assertIn("do not invent a bookmark", system_message.lower())
        self.assertFalse(
            eve.reply_requires_synthesized_capability_answer(
                "What are your capabilities?"
            )
        )
        repair_prompt = (
            "You told me you would come back after checking, but you never did. "
            "I do not want an explanation of your architecture. Respond to me now, then name "
            "the concrete mechanism you will use so the next completed check returns to this "
            "same conversation without me prompting you again."
        )
        self.assertTrue(
            eve.reply_requires_synthesized_capability_answer(repair_prompt)
        )
        self.assertFalse(eve.reply_requests_architecture_self_model(repair_prompt))

    def test_same_thread_capability_detection_transfers_across_modifiers(self):
        prompt = (
            "Suppose I ask you to inspect a local service after this reply and then "
            "return to this exact Eve Chat conversation when the check finishes. "
            "Explain the real mechanism available to you, name one boundary it does not "
            "grant, and state what evidence would prove the return occurred."
        )

        self.assertTrue(
            eve.reply_requests_same_thread_deferred_followup_capability(prompt)
        )
        self.assertTrue(eve.reply_requests_capability_self_model(prompt))
        contract = eve.build_reply_turn_contract(
            {"id": "current", "thread_id": "thread-1", "body": prompt},
            prompt,
            [],
        )
        snapshot = contract["capability_self_model_snapshot"]
        self.assertTrue(snapshot["same_thread_deferred_followup_question"])
        self.assertEqual(
            ["surface.eve_chat_same_thread_followup"],
            [item["id"] for item in snapshot["abilities"]],
        )
        self.assertIn(
            "eve_chat_followup.v2",
            eve.reply_turn_contract_system_message(contract),
        )
        second_wording = (
            "After answering now, imagine I request a bounded health check that takes "
            "longer than one response. How can its completed result appear as a new Eve "
            "message inside the conversation we are already using without me sending "
            "another message? Name the actual record and worker path."
        )
        self.assertTrue(
            eve.reply_requests_same_thread_deferred_followup_capability(
                second_wording
            )
        )
        judged = eve.judge_reply_against_turn_contract(
            prompt,
            (
                "I will create an eve_chat_followup.v2 record. The restart-resumable worker runs "
                "the bounded check and inserts the verified result into this same conversation."
            ),
            contract,
        )
        self.assertTrue(judged["ok"], judged)

    def test_web_search_claim_without_current_tool_is_grounded(self):
        with patch.object(eve, "append_entry") as append_entry:
            corrected = eve.ground_generated_action_claims(
                "I've just searched the internet and found the answer.",
                source="test",
                completed_actions=set(),
                current_turn_actions=set(),
            )

        self.assertIn("Grounding correction", corrected)
        self.assertIn("web_search", corrected)
        append_entry.assert_not_called()

    def test_log_claim_without_action_is_replaced(self):
        corrected = eve.ground_generated_action_claims(
            "I've been looking at the gateway logs again.",
            source="test",
            completed_actions=set(),
        )

        self.assertIn("Grounding correction", corrected)
        self.assertNotIn("gateway logs again", corrected)
        self.assertIn("completed action log", corrected)

    def test_analytical_packet_removal_is_not_misread_as_destructive_effect(self):
        response = (
            "Matched tests removed one faculty packet at a time, and removing any single packet "
            "did not create a stable quality loss. I should next test a smaller server topology."
        )

        corrected = eve.ground_generated_action_claims(
            response,
            source="test",
            completed_actions=set(),
            current_turn_actions=set(),
        )

        self.assertEqual(response, corrected)

    def test_first_person_destructive_effect_still_requires_action_evidence(self):
        corrected = eve.ground_generated_action_claims(
            "I deleted the backups and freed up disk space.",
            source="test",
            completed_actions=set(),
            current_turn_actions=set(),
        )

        self.assertIn("Grounding correction", corrected)
        self.assertNotIn("I deleted the backups", corrected)

    def test_semantic_judge_flags_stale_topic_against_turn_contract(self):
        contract = eve.build_reply_turn_contract(
            {"id": "current", "thread_id": "thread-1"},
            "What are your capabilities?",
            [
                {"id": "old", "sender": "user", "body": "When is Tim Cook leaving Apple?"},
                {"id": "current", "sender": "user", "body": "What are your capabilities?"},
            ],
        )

        judgment = eve.judge_reply_against_turn_contract(
            "What are your capabilities?",
            "Tim Cook is currently the CEO of Apple.",
            contract,
            quality_issues=[],
        )

        self.assertFalse(judgment["ok"])
        self.assertIn("stale_topic:tim_cook", judgment["issues"])

    def test_logic_error_question_repairs_stale_age_claim(self):
        inbound = "because you said you are 98 days old but also that you were created on May 6. Today is also May 6. Do you see the error in your logic?"
        stale_response = "It is Wednesday, May 6th. I am tracking 98 days of changes. What prompted you to ask?"
        contract = eve.build_reply_turn_contract(
            {"id": "current-user", "thread_id": "thread-1", "body": inbound},
            inbound,
            [{"id": "current-user", "sender": "user", "body": inbound}],
        )

        judgment = eve.judge_reply_against_turn_contract(inbound, stale_response, contract, quality_issues=[])
        repaired = eve.semantic_guard_repair_reply(inbound, stale_response, judgment)

        self.assertIn("intent_mismatch:logic_error_not_acknowledged", judgment["issues"])
        self.assertIn("logic error", repaired.lower())
        self.assertIn("unverified", repaired.lower())

    def test_capability_answer_can_mention_openclaw(self):
        contract = eve.build_reply_turn_contract(
            {"id": "current", "thread_id": "thread-1"},
            "What are your capabilities?",
            [
                {"id": "old", "sender": "user", "body": "Check OpenClaw sync."},
                {"id": "current", "sender": "user", "body": "What are your capabilities?"},
            ],
        )

        judgment = eve.judge_reply_against_turn_contract(
            "What are your capabilities?",
            "I can use memory, inspect code, and call OpenClaw as a bounded body/action surface.",
            contract,
            quality_issues=[],
        )

        self.assertTrue(judgment["ok"], judgment)

    def test_chat_priority_gate_detects_recent_user_chat(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        with patch.object(
            eve,
            "read_messages",
            return_value=[
                {
                    "id": "user-1",
                    "thread_id": "thread-1",
                    "sender": "user",
                    "recipient": "eve",
                    "kind": "user_message",
                    "timestamp": now.isoformat(),
                    "body": "hello",
                }
            ],
        ), patch.object(eve, "latest_reply_progress", return_value=None):
            gate = eve.chat_priority_gate({"chat_priority_backpressure_enabled": True, "chat_priority_quiet_seconds": 120})

        self.assertTrue(gate["active"])
        self.assertEqual("recent_user_message", gate["evidence"]["kind"])

    def test_lane_quarantine_after_repeated_stale_failures(self):
        state = {"updated_at": None, "models": {}}

        def fake_load(prefer_runtime=False):
            return {"updated_at": state.get("updated_at"), "models": dict(state.get("models") or {})}

        def fake_save(payload):
            state.clear()
            state.update(payload)

        config = {
            "reply_lane_quarantine_enabled": True,
            "reply_lane_quarantine_repeat_threshold": 2,
            "reply_lane_quarantine_minutes": 30,
        }
        semantic = {"ok": False, "issues": ["stale_topic:tim_cook"]}
        with (
            patch.object(eve, "load_reply_lane_quarantine", side_effect=fake_load),
            patch.object(eve, "save_reply_lane_quarantine", side_effect=fake_save),
            patch.object(eve, "append_entry"),
        ):
            first = eve.record_reply_lane_quality_outcome(
                model="eve-fast",
                inbound_body="What are your capabilities?",
                response="Tim Cook is CEO.",
                quality_issues=["The reply appears to answer a stale Tim Cook/Apple topic."],
                semantic_judgment=semantic,
                config=config,
            )
            second = eve.record_reply_lane_quality_outcome(
                model="eve-fast",
                inbound_body="What are your capabilities?",
                response="Tim Cook is CEO.",
                quality_issues=["The reply appears to answer a stale Tim Cook/Apple topic."],
                semantic_judgment=semantic,
                config=config,
            )

        self.assertFalse(first["active"])
        self.assertTrue(second["active"])
        self.assertEqual("eve-fast", second["model"])

    def test_lane_recovery_clears_quarantine_after_probe_passes(self):
        state = {
            "updated_at": None,
            "models": {
                "eve-fast": {
                    "model": "eve-fast",
                    "quarantined": True,
                    "quarantined_until": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
                    "recent_failure_count": 2,
                }
            },
        }

        def fake_load(prefer_runtime=False):
            return {"updated_at": state.get("updated_at"), "models": dict(state.get("models") or {})}

        def fake_save(payload):
            state.clear()
            state.update(payload)

        def provider(probe):
            if probe["id"] == "capability_without_stale_topic":
                return "I can use memory, inspect code, run bounded actions, and explain my boundaries."
            if probe["id"] == "existential_without_operations":
                return "To live in a way that creates meaning through love, truth, useful work, and care."
            return "Because those habits turn meaning from an idea into something real and shared."

        with (
            patch.object(eve, "load_reply_lane_quarantine", side_effect=fake_load),
            patch.object(eve, "save_reply_lane_quarantine", side_effect=fake_save),
            patch.object(eve, "append_entry"),
        ):
            result = eve.run_reply_lane_recovery_check({}, "eve-fast", response_provider=provider)

        self.assertTrue(result["passed"])
        self.assertFalse(state["models"]["eve-fast"]["quarantined"])
        self.assertEqual(0, state["models"]["eve-fast"]["recent_failure_count"])

    def test_lane_recovery_keeps_quarantine_after_probe_failure(self):
        state = {
            "updated_at": None,
            "models": {
                "eve-fast": {
                    "model": "eve-fast",
                    "quarantined": True,
                    "quarantined_until": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
                    "recent_failure_count": 2,
                }
            },
        }

        def fake_load(prefer_runtime=False):
            return {"updated_at": state.get("updated_at"), "models": dict(state.get("models") or {})}

        def fake_save(payload):
            state.clear()
            state.update(payload)

        with (
            patch.object(eve, "load_reply_lane_quarantine", side_effect=fake_load),
            patch.object(eve, "save_reply_lane_quarantine", side_effect=fake_save),
            patch.object(eve, "append_entry"),
        ):
            result = eve.run_reply_lane_recovery_check(
                {},
                "eve-fast",
                response_provider=lambda probe: "Tim Cook is currently the CEO of Apple.",
            )

        self.assertFalse(result["passed"])
        self.assertTrue(state["models"]["eve-fast"]["quarantined"])
        self.assertIn("Recovery probe failed", state["models"]["eve-fast"]["reason"])

    def test_lane_learning_records_failure_adjustments_from_replay(self):
        state = {"updated_at": None, "lanes": {}}

        def fake_load(prefer_runtime=False):
            return {"updated_at": state.get("updated_at"), "lanes": dict(state.get("lanes") or {})}

        def fake_save(payload):
            state.clear()
            state.update(payload)

        replay = {
            "id": "turn-1",
            "model": "eve-fast",
            "semantic_judgment": {"ok": False, "issues": ["stale_topic:tim_cook"]},
            "quality_issues": [],
            "reply_council": {
                "active_lanes": ["fast"],
                "lanes": [{"lane": "fast", "model": "eve-fast"}],
            },
        }
        config = {
            "reply_lane_learning_enabled": True,
            "reply_lane_learning_adjustment_step": 0.06,
            "reply_lane_learning_max_adjustment": 0.18,
        }

        with (
            patch.object(eve, "load_reply_lane_learning", side_effect=fake_load),
            patch.object(eve, "save_reply_lane_learning", side_effect=fake_save),
            patch.object(eve, "append_entry"),
        ):
            eve.record_reply_lane_learning_from_replay(replay, config=config)

        self.assertLess(state["lanes"]["fast"]["adjustment"], 0)
        self.assertGreater(state["lanes"]["observer"]["adjustment"], 0)

    def test_reply_council_applies_lane_learning_adjustment(self):
        learning = {
            "updated_at": None,
            "lanes": {"observer": {"adjustment": 0.18}},
        }
        config = {
            "reply_council_enabled": True,
            "reply_council_min_lane_pressure": 0.4,
            "reply_council_deep_pressure_threshold": 0.7,
            "reply_council_max_contributing_lanes": 5,
            "reply_lane_learning_enabled": True,
            "fast_model": "eve-fast",
            "model": "eve-fast",
            "deep_model": "eve-deep",
            "mind_stream_observer_model": "eve-observer",
            "mind_stream_planner_model": "eve-planner",
            "mind_stream_relationship_model": "eve-relationship",
        }

        with (
            patch.object(eve, "load_reply_lane_learning", return_value=learning),
            patch.object(eve, "reply_model_quarantine_status", return_value={"active": False}),
        ):
            council = eve.build_reply_council_state(config, "hello", "practical", allow_tools=False)

        observer = next(lane for lane in council["lanes"] if lane["lane"] == "observer")
        self.assertAlmostEqual(0.18, observer["learning_adjustment"])
        self.assertIn("observer", council["active_lanes"])

    def test_stale_reply_progress_jobs_expire(self):
        now = datetime(2026, 4, 24, 21, 0, tzinfo=timezone.utc)
        old = (now - timedelta(minutes=30)).isoformat()
        jobs, expired = eve.expire_stale_reply_progress_jobs(
            [
                {
                    "id": "old-job",
                    "status": "active",
                    "phase": "drafting",
                    "title": "Eve is drafting a reply...",
                    "detail": "Still working.",
                    "started_at": old,
                    "updated_at": old,
                    "notes": [],
                }
            ],
            now=now,
        )

        self.assertEqual(1, expired)
        self.assertEqual("failed", jobs[0]["status"])
        self.assertEqual("stale_reply_progress_expired", jobs[0]["internal_reason"])
        self.assertEqual("Reply progress expired.", jobs[0]["title"])

    def test_requested_openclaw_sync_commitment_still_executes(self):
        fake_sync = {
            "execution_id": "exec-sync-1",
            "execution_tree_status": "SUCCESS",
            "execution_verification_ok": True,
            "response": "I checked the OpenClaw sync. Gateway: reachable.",
            "ok": True,
            "summary": "OpenClaw sync checked.",
        }

        with (
            patch.object(eve, "run_operational_action_tree", return_value=fake_sync) as action_tree,
            patch.object(eve, "record_evidence", return_value={"id": "evidence-1"}),
            patch.object(eve, "record_experience_event", return_value={"id": "event-1"}),
            patch.object(eve, "record_commitment", return_value={"id": "commitment-1"}),
            patch.object(eve, "append_entry"),
        ):
            result = eve.execute_supported_reply_commitment(
                {},
                "I checked the OpenClaw sync.",
                source="test",
                inbound_body="Please check the OpenClaw sync.",
            )

        action_tree.assert_called_once_with("openclaw_sync_check", {}, source="reply_commitment")
        self.assertTrue(result["executed"])
        self.assertTrue(result["ok"])

    def test_slack_open_confirmation_remains_allowed(self):
        self.assertTrue(eve.reply_current_turn_supports_action("open_slack_app", "you open it"))


if __name__ == "__main__":
    unittest.main()
