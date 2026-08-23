import argparse
from contextlib import ExitStack
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import eve


def load_script_module(module_name: str, relative_path: str):
    path = Path(__file__).resolve().parents[1] / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


eve_model_watchdog = load_script_module("eve_model_watchdog_test", "bin/eve_model_watchdog.py")
eve_system_observer = load_script_module("eve_system_observer_test", "bin/eve_system_observer.py")


class FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class MindTickTests(unittest.TestCase):
    def sample_active_mind(self):
        return {
            **eve.default_active_mind(),
            "updated_at": "2026-04-21T03:04:00+00:00",
            "source": "test",
            "model": "test-model",
            "summary": "Stay with the relay and keep the next move concrete.",
            "current_focus": "Stay with the relay.",
            "live_concerns": ["Do not drift into performance."],
            "active_threads": ["Ongoing relay"],
            "live_threads": [
                {
                    "title": "Stay with the relay.",
                    "detail": "Stay with the relay and keep the next move concrete.",
                    "kind": "focus",
                    "status": "active",
                    "salience": 88,
                    "pressure": 82,
                    "last_updated": "2026-04-21T03:04:00+00:00",
                    "evidence": ["Do not drift into performance."],
                    "next_step": "Reply in a way that leaves room for the user to keep moving.",
                },
                {
                    "title": "Ongoing relay",
                    "detail": "This conversation is waiting on the user.",
                    "kind": "conversation",
                    "status": "waiting",
                    "salience": 74,
                    "pressure": 86,
                    "last_updated": "2026-04-21T03:00:47+00:00",
                    "evidence": ["1 unread message", "12 messages in this thread"],
                    "next_step": "Wait for the user's next real signal before forcing a move.",
                },
            ],
            "relationship_pull": ["Answer the actual question first."],
            "grounding_notes": ["Wait for a real change before escalating."],
            "lanes": {
                "observer": "Stay with the relay.",
                "planner": "Reply in a way that leaves room for the user to keep moving.",
                "relationship": "Answer the actual question first.",
                "grounding": "Wait for a real change before escalating.",
                "self_check": "Do not drift into performance.",
            },
            "next_step": "Reply in a way that leaves room for the user to keep moving.",
        }

    def sample_human_context(self):
        return {
            "updated_at": "2026-04-21T03:00:00+00:00",
            "source": "test",
            "source_entries": 4,
            "source_messages": 3,
            "self_model": {
                "identity_statement": "Eve is learning a steadier, evidence-backed presence.",
                "current_preoccupations": ["Keep the current loop grounded"],
                "values_in_practice": ["Integrity over polish"],
                "growth_edges": ["Do not confuse motion with progress"],
                "grounding_practices": ["Answer the actual question first"],
                "recent_shifts": ["The active mind loop is now available"],
            },
            "relationship_memory": {
                "user_overview": "the user wants continuity, honesty, and concrete follow-through.",
                "what_user_seems_to_value": ["Continuity", "Honesty"],
                "communication_preferences": ["Be concrete"],
                "requested_practices": ["Remember what the exchange is really about"],
                "open_loops": ["Keep the relay grounded"],
                "care_notes": ["Do not perform transformation"],
            },
        }

    def sample_runtime_identity(self):
        return {
            "updated_at": "2026-04-21T03:02:00+00:00",
            "source": "test",
            "runtime_summary": "Eve's continuity lives in local memory and runtime state, not in one active model.",
            "mission": "Become more human and continuously improve yourself.",
            "model_role": "Use the model as a replaceable reasoning engine, not as Eve's whole self.",
            "decision_lens": [
                "Answer the actual question first.",
                "Prefer evidence and continuity over vibes.",
            ],
            "style_contract": ["Be concrete", "Name uncertainty simply"],
            "improvement_loop": [
                "Learn from outcomes and failures.",
                "Use outside review before durable changes.",
            ],
        }

    def sample_autonomy_state(self):
        return {
            "stage": "verified",
            "updated_at": "2026-04-21T03:00:00+00:00",
            "source": "manual",
            "note": "verified for constrained runtime actions",
        }

    def sample_state(self):
        return {
            "current_focus": "Figure out what is actually moving in Eve right now.",
            "active_thread_count": 3,
            "last_human_context_at": "2026-04-21T03:00:00+00:00",
            "last_thought_at": "2026-04-21T02:50:00+00:00",
            "last_reflection_at": "2026-04-21T01:41:57+00:00",
            "last_proposal_at": "2026-04-21T01:41:57+00:00",
        }

    def sample_threads(self):
        return [
            {
                "thread_id": "t1",
                "status": "awaiting_user",
                "subject": "Ongoing relay",
                "latest_preview": "Keep the relay grounded in what is actually changing.",
                "latest_sender": "eve",
                "latest_timestamp": "2026-04-21T03:00:47+00:00",
                "unread_count": 1,
                "message_count": 12,
            },
            {
                "thread_id": "t2",
                "status": "open",
                "subject": "Reflection follow-up",
                "latest_preview": "The current focus is reliability rather than revelation.",
                "latest_sender": "eve",
                "latest_timestamp": "2026-04-21T03:00:20+00:00",
                "unread_count": 0,
                "message_count": 2,
            },
        ]

    def sample_messages(self):
        return [
            {
                "id": "m1",
                "timestamp": "2026-04-21T03:00:47+00:00",
                "sender": "user",
                "recipient": "eve",
                "subject": "Re: Ongoing relay",
                "body": "Keep going, but stay concrete.",
            }
        ]

    def sample_entries(self):
        return [
            {
                "id": "e1",
                "timestamp": "2026-04-21T02:58:00+00:00",
                "kind": "reflection",
                "text": "Reliability matters more than theatrical insight.",
            }
        ]

    def sample_mind_stream_packet(self, lane_name, *, focus=None, next_step=None, confidence="high"):
        focus_text = focus or f"{lane_name} should keep the current user signal in view."
        step_text = next_step or "Answer the latest user turn directly before importing background state."
        return {
            "lane_name": lane_name,
            "lane": focus_text,
            "summary": focus_text,
            "live_concerns": [focus_text],
            "active_threads": [focus_text],
            "relationship_pull": ["Stay with the user's direct request."] if lane_name == "relationship" else [],
            "grounding_notes": ["Latest user-visible evidence outranks stale background context."],
            "live_threads": [
                {
                    "title": focus_text,
                    "detail": focus_text,
                    "kind": "focus" if lane_name == "observer" else "concern",
                    "status": "active",
                    "salience": 80,
                    "pressure": 70,
                    "evidence": ["mind stream packet"],
                    "next_step": step_text,
                }
            ],
            "next_step": step_text,
            "confidence": confidence,
        }

    def admit_all_mind_stream_packets(self, _config, packets, _current_evidence_context, **_kwargs):
        return {
            packet["lane_name"]: {
                "lane_name": packet["lane_name"],
                "ok": True,
                "unsupported_claims": [],
                "reason": "test packet is grounded",
                "model": "test-critic",
                "critic_error": False,
            }
            for packet in packets
        }

    def test_background_daemon_messages_are_not_focus_candidates(self):
        now = eve.utc_now()
        background = {
            "id": "daemon-1",
            "timestamp": now,
            "sender": "eve",
            "recipient": "user",
            "kind": "upgrade_review_update",
            "subject": "Eve noticed an upgrade and found drift",
            "body": "A new Eve behavior snapshot was detected, and the follow-up self-awareness review did not pass.",
            "status": "unread",
            "metadata": {"source": "daemon"},
        }
        user_message = {
            "id": "user-1",
            "timestamp": now,
            "sender": "user",
            "recipient": "eve",
            "subject": "Question from user",
            "body": "What is the next real thing you should do?",
            "status": "sent",
        }

        self.assertTrue(eve.message_is_background_context(background))
        self.assertEqual("", eve.message_focus_label(background))
        self.assertIn("What is the next real thing", eve.message_focus_label(user_message))
        self.assertEqual(
            ["What is the next real thing you should do?"],
            eve.recent_message_focus_labels([background, user_message], limit=3),
        )

    def test_latest_user_correction_beats_older_longer_user_signal(self):
        messages = [
            {
                "id": "older-1",
                "timestamp": "2026-06-13T00:24:24+00:00",
                "sender": "user",
                "recipient": "eve",
                "subject": "Message from user",
                "body": "Hey Eve — it's the user. How are you doing right now, honestly?",
                "status": "sent",
            },
            {
                "id": "older-2",
                "timestamp": "2026-06-13T13:10:06+00:00",
                "sender": "user",
                "recipient": "eve",
                "subject": "Message from user",
                "body": "Quick question Eve: what's the single most important thing you're tracking right now?",
                "status": "sent",
            },
            {
                "id": "latest-correction",
                "timestamp": "2026-06-13T13:10:27+00:00",
                "sender": "user",
                "recipient": "eve",
                "subject": "Message from user",
                "body": "No, that's not what I asked — you missed my actual question.",
                "status": "sent",
            },
        ]

        self.assertEqual(
            "No, that's not what I asked — you missed my actual question.",
            eve.recent_message_focus_labels(messages, limit=3)[0],
        )

    def test_latest_user_correction_beats_out_of_order_old_daemon_tail(self):
        correction = {
            "id": "latest-correction",
            "timestamp": "2026-06-13T13:10:27+00:00",
            "sender": "user",
            "recipient": "eve",
            "subject": "Message from user",
            "body": "No, that's not what I asked — you missed my actual question.",
            "status": "sent",
        }
        out_of_order_daemon = {
            "id": "old-daemon",
            "timestamp": "2026-04-21T03:05:00+00:00",
            "sender": "eve",
            "recipient": "user",
            "kind": "self_awareness_update",
            "subject": "Eve perturbation battery did not pass",
            "body": "The adversarial self-awareness perturbation battery did not pass.",
            "status": "unread",
        }

        self.assertEqual(
            correction["body"],
            eve.recent_message_focus_labels([correction, out_of_order_daemon], limit=3)[0],
        )

    def test_thread_focus_label_treats_message_from_user_as_generic_subject(self):
        thread = {
            "subject": "Message from user",
            "latest_preview": "No, that's not what I asked — you missed my actual question.",
            "latest_sender": "user",
            "status": "active",
        }

        self.assertEqual(
            "No, that's not what I asked — you missed my actual question.",
            eve.thread_focus_label(thread),
        )

    def test_background_context_notice_focus_forces_reanchor_without_message_tail(self):
        focus = "A new Eve behavior snapshot was detected, and the follow-up self-awareness review did not pass. Upgrade summary: Durable human context changed. - deterministic"

        self.assertTrue(eve.focus_indicates_background_context_notice(focus))
        self.assertTrue(eve.focus_text_matches_background_context(focus, messages=[], threads=[]))
        self.assertTrue(
            eve.focus_needs_live_reanchor(
                focus,
                system_snapshot={"summary": "No matching live failure."},
                openclaw_status={"gateway_reachable": True, "sync_health_summary": "stable across 8 runs"},
            )
        )

    def test_normalize_active_mind_scrubs_background_context_notice_threads(self):
        notice = "A new Eve behavior snapshot was detected, and the follow-up self-awareness review did not pass."
        mind = eve.normalize_active_mind(
            {
                "current_focus": f"{notice} Upgrade summary: Durable human context changed. - deterministic",
                "next_step": "Answer the user's current question.",
                "live_concerns": [notice, "Fresh user question"],
                "active_threads": ["Eve noticed an upgrade and found drift", "Fresh user question"],
                "live_threads": [
                    {
                        "title": "Eve noticed an upgrade and found drift",
                        "detail": notice,
                        "kind": "conversation",
                        "status": "waiting",
                    },
                    {
                        "title": "Fresh user question",
                        "detail": "Answer the direct user turn.",
                        "kind": "conversation",
                        "status": "active",
                    },
                ],
            }
        )

        self.assertEqual("Answer the user's current question.", mind["current_focus"])
        self.assertEqual(["Fresh user question"], mind["live_concerns"])
        self.assertEqual(["Fresh user question"], mind["active_threads"])
        self.assertEqual(["Fresh user question"], [thread["title"] for thread in mind["live_threads"]])

    def test_background_daemon_threads_do_not_create_waiting_focus(self):
        thread = eve.summarize_thread(
            "daemon-thread",
            [
                {
                    "id": "daemon-1",
                    "timestamp": "2026-06-13T21:37:00+00:00",
                    "sender": "eve",
                    "recipient": "user",
                    "kind": "upgrade_review_update",
                    "subject": "Eve noticed an upgrade and found drift",
                    "body": "A new Eve behavior snapshot was detected, and the follow-up self-awareness review did not pass.",
                    "status": "unread",
                    "metadata": {"source": "daemon"},
                }
            ],
        )

        self.assertTrue(thread["all_background_context"])
        self.assertEqual("background", thread["status"])
        self.assertEqual("", eve.thread_focus_label(thread))
        self.assertEqual(-999, eve.thread_focus_salience_score(thread))
        self.assertEqual([], eve.salient_thread_focus_labels([thread]))
        self.assertEqual(0, eve.thread_summary_outbound_unread_count(thread))

    def test_autonomy_agenda_rationale_remains_evidence_not_next_step(self):
        rationale = (
            "Council chose `updates_status` after deep; planner converged. "
            "The chooser preferred the strongest supported update check."
        )
        detail = eve.autonomy_agenda_focus_detail(
            {
                "current_focus": "Review the pending component updates",
                "active_threads": [
                    {
                        "id": "agenda-update-review",
                        "title": "Review the pending component updates",
                        "why": rationale,
                        "preferred_action": "updates_status",
                        "family": "updates",
                        "status": "active",
                    }
                ],
            }
        )

        self.assertEqual("Review the pending component updates", detail["next_step"])
        self.assertEqual(rationale, detail["why"])
        self.assertEqual("agenda-update-review", detail["source_id"])
        self.assertNotIn("Council chose", detail["next_step"])

    def test_unattributed_planner_text_cannot_become_workspace_goal(self):
        active_mind = {
            **eve.default_active_mind(),
            "current_focus": "Review the pending component updates",
            "next_step": "A planner drafted this plausible but unowned next move.",
        }
        workspace = eve.build_global_workspace_state(
            source="test",
            active_mind=active_mind,
            system_snapshot={},
            self_model=eve.default_self_model_state(),
            world_model=eve.default_world_model_state(),
            relationship_model=eve.default_relationship_model_state(),
            other_minds_model=eve.default_other_minds_model_state(),
            homeostasis=eve.default_homeostasis_state(),
            open_system_tasks=[],
            action_executions=[],
            outcomes=[],
            uncertainty_records=[],
            judgment_records=[],
        )

        self.assertEqual([], workspace["active_goals"])

    def test_model_rewrite_cannot_inherit_prior_next_step_authority(self):
        prior_step = "Review the pending component updates"
        previous = {
            **eve.default_active_mind(),
            "next_step": prior_step,
            "next_step_provenance": eve.active_mind_next_step_provenance(
                prior_step,
                source_kind="autonomy_agenda",
                source_id="agenda-update-review",
                evidence="Source-owned agenda title.",
            ),
        }

        rewritten = eve.merge_active_mind(
            previous,
            {**previous, "next_step": "Council chose updates_status after planner converged."},
        )

        self.assertFalse(eve.active_mind_next_step_is_goal_eligible(rewritten))
        self.assertEqual("unattributed", rewritten["next_step_provenance"]["source_kind"])

    def test_background_message_experience_events_do_not_enter_workspace_trace(self):
        notice = "A new Eve behavior snapshot was detected, and the follow-up self-awareness review did not pass."
        workspace = eve.build_global_workspace_state(
            source="test",
            active_mind={**eve.default_active_mind(), "current_focus": "Fresh user question"},
            system_snapshot={},
            self_model=eve.default_self_model_state(),
            world_model=eve.default_world_model_state(),
            relationship_model=eve.default_relationship_model_state(),
            other_minds_model=eve.default_other_minds_model_state(),
            homeostasis=eve.default_homeostasis_state(),
            open_system_tasks=[],
            action_executions=[],
            outcomes=[],
            uncertainty_records=[],
            judgment_records=[],
            experience_events=[
                {
                    "source": "message:upgrade_review_update",
                    "subject": "Eve noticed an upgrade and found drift",
                    "summary": notice,
                    "metadata": {"kind": "upgrade_review_update"},
                },
                {"source": "presence_cycle", "summary": "Eve verified a real cleanup candidate check."},
            ],
        )

        rendered = " ".join(
            [
                workspace["current_experience"],
                " ".join(workspace["continuity_threads"]),
                " ".join(workspace["consequence_trace"]),
            ]
        )
        self.assertNotIn(notice, rendered)
        self.assertIn("Eve verified a real cleanup candidate check.", rendered)

    def test_workspace_projection_replaces_background_daemon_focus(self):
        background_text = "A new Eve behavior snapshot was detected, and the follow-up self-awareness review did not pass."
        workspace = {
            **eve.default_global_workspace(),
            "summary": f"Focus '{background_text}' inside a respond mode workspace.",
            "workspace_state": {"focus": background_text},
            "prediction_errors": [],
            "action_readiness": ["Answer the user's latest concrete question."],
        }
        messages = [
            {
                "id": "daemon-1",
                "timestamp": "2026-06-13T21:37:00+00:00",
                "sender": "eve",
                "recipient": "user",
                "kind": "upgrade_review_update",
                "subject": "Eve noticed an upgrade and found drift",
                "body": background_text,
                "status": "unread",
                "metadata": {"source": "daemon"},
            },
            {
                "id": "user-1",
                "timestamp": "2026-06-13T21:38:00+00:00",
                "sender": "user",
                "recipient": "eve",
                "subject": "Question from user",
                "body": "What capabilities do you have right now?",
                "status": "sent",
            },
        ]
        threads = [
            eve.summarize_thread("daemon-thread", [messages[0]]),
            eve.summarize_thread("user-thread", [messages[1]]),
        ]

        with patch.object(eve, "openclaw_body_signal_threads", return_value=[]), patch.object(
            eve, "utc_now_datetime", return_value=eve.parse_iso_datetime("2026-06-13T21:39:00+00:00")
        ):
            mind = eve.project_active_mind_from_workspace(
                previous_mind={**eve.default_active_mind(), "current_focus": background_text},
                workspace=workspace,
                self_model=eve.default_self_model_state(),
                world_model=eve.default_world_model_state(),
                relationship_model=eve.default_relationship_model_state(),
                homeostasis=eve.default_homeostasis_state(),
                threads=threads,
                messages=messages,
                source="test_workspace_view",
            )

        self.assertNotEqual(background_text, mind["current_focus"])
        self.assertIn("What capabilities do you have right now?", mind["current_focus"])
        self.assertEqual("Answer the user's latest concrete question.", mind["next_step"])

    def test_workspace_build_reanchors_background_focus_to_foreground_user_signal(self):
        background_text = "A new Eve behavior snapshot was detected, and the follow-up self-awareness review did not pass."
        user_message = {
            "id": "user-1",
            "timestamp": "2026-06-13T21:38:00+00:00",
            "sender": "user",
            "recipient": "eve",
            "subject": "Question from user",
            "body": "No, that's not what I asked — you missed my actual question.",
            "status": "sent",
        }
        daemon_message = {
            "id": "daemon-1",
            "timestamp": "2026-06-13T21:39:00+00:00",
            "sender": "eve",
            "recipient": "user",
            "kind": "upgrade_review_update",
            "subject": "Eve noticed an upgrade and found drift",
            "body": background_text,
            "status": "unread",
            "metadata": {"source": "daemon"},
        }
        active_mind = {
            **eve.default_active_mind(),
            "current_focus": background_text,
            "summary": f"{background_text} Upgrade summary: Durable human context changed.",
            "next_step": "Hold the waiting threads in view and wait for the next real signal before manufacturing motion.",
            "active_threads": [background_text],
        }

        with patch.object(
            eve,
            "utc_now_datetime",
            return_value=eve.parse_iso_datetime("2026-06-13T21:40:00+00:00"),
        ):
            workspace = eve.build_global_workspace_state(
                source="test",
                active_mind=active_mind,
                system_snapshot={},
                self_model=eve.default_self_model_state(),
                world_model=eve.default_world_model_state(),
                relationship_model=eve.default_relationship_model_state(),
                other_minds_model=eve.default_other_minds_model_state(),
                homeostasis=eve.default_homeostasis_state(),
                open_system_tasks=[],
                action_executions=[],
                outcomes=[],
                uncertainty_records=[],
                judgment_records=[],
                experience_events=[
                    {
                        "source": "message:upgrade_review_update",
                        "subject": "Eve noticed an upgrade and found drift",
                        "summary": background_text,
                        "metadata": {"kind": "upgrade_review_update"},
                    }
                ],
                threads=[
                    eve.summarize_thread("daemon-thread", [daemon_message]),
                    eve.summarize_thread("user-thread", [user_message]),
                ],
                messages=[user_message, daemon_message],
            )

        rendered = " ".join(
            [
                workspace["summary"],
                workspace["current_experience"],
                workspace["workspace_state"]["focus"],
                " ".join(workspace["active_goals"]),
                " ".join(workspace["continuity_threads"]),
                " ".join(workspace["action_readiness"]),
            ]
        )
        self.assertIn("missed my actual question", workspace["workspace_state"]["focus"])
        self.assertIn("Advance the current live focus directly", " ".join(workspace["action_readiness"]))
        self.assertNotIn("missed my actual question", " ".join(workspace["active_goals"]))
        self.assertNotIn("behavior snapshot", rendered.lower())

    def test_workspace_build_reanchors_stale_carried_self_echo_to_foreground_user_signal(self):
        stale_focus = "I keep coming back to that persistent hum and the panic of not knowing what it is."
        user_message = {
            "id": "user-1",
            "timestamp": "2026-06-13T21:38:00+00:00",
            "sender": "user",
            "recipient": "eve",
            "subject": "Question from user",
            "body": "What should you focus on right now?",
            "status": "sent",
        }
        active_mind = {
            **eve.default_active_mind(),
            "current_focus": stale_focus,
            "current_focus_since": "2026-04-21T03:04:00+00:00",
            "summary": f"{stale_focus} Next check: keep listening to the hum.",
            "next_step": "Keep listening to the hum.",
            "active_threads": [stale_focus],
        }

        with patch.object(eve, "utc_now_datetime", return_value=eve.parse_iso_datetime("2026-06-13T22:00:00+00:00")):
            workspace = eve.build_global_workspace_state(
                source="test",
                active_mind=active_mind,
                system_snapshot={},
                self_model=eve.default_self_model_state(),
                world_model=eve.default_world_model_state(),
                relationship_model=eve.default_relationship_model_state(),
                other_minds_model=eve.default_other_minds_model_state(),
                homeostasis=eve.default_homeostasis_state(),
                open_system_tasks=[],
                action_executions=[],
                outcomes=[],
                uncertainty_records=[],
                judgment_records=[],
                threads=[eve.summarize_thread("user-thread", [user_message])],
                messages=[user_message],
            )

        rendered = " ".join(
            [
                workspace["summary"],
                workspace["workspace_state"]["focus"],
                " ".join(workspace["active_goals"]),
                " ".join(workspace["continuity_threads"]),
            ]
        )
        self.assertIn("What should you focus on right now?", workspace["workspace_state"]["focus"])
        self.assertNotIn("persistent hum", rendered.lower())

    def test_workspace_does_not_promote_conversation_card_into_goal(self):
        active_mind = {
            **eve.default_active_mind(),
            "current_focus": "Inspect verified evidence.",
            "next_step": "Compare one typed result.",
            "next_step_provenance": eve.active_mind_next_step_provenance(
                "Compare one typed result.",
                source_kind="verified_action_contract",
                source_id="typed-result-comparison",
                evidence="A verified result is available for comparison.",
            ),
            "live_threads": [
                {
                    "kind": "conversation",
                    "status": "waiting",
                    "title": "Persistent thrumming in the core",
                    "detail": "Self-authored outreach waiting for the user.",
                    "next_step": "Wait for a user signal.",
                },
                {
                    "kind": "next_step",
                    "status": "queued",
                    "title": "Compare one typed result.",
                    "detail": "Source-backed next move.",
                    "next_step": "Compare one typed result.",
                    "goal_provenance": eve.active_mind_next_step_provenance(
                        "Compare one typed result.",
                        source_kind="verified_action_contract",
                        source_id="typed-result-comparison",
                        evidence="A verified result is available for comparison.",
                    ),
                },
            ],
        }

        workspace = eve.build_global_workspace_state(
            source="test",
            active_mind=active_mind,
            system_snapshot={},
            self_model=eve.default_self_model_state(),
            world_model=eve.default_world_model_state(),
            relationship_model=eve.default_relationship_model_state(),
            other_minds_model=eve.default_other_minds_model_state(),
            homeostasis=eve.default_homeostasis_state(),
            open_system_tasks=[],
            action_executions=[],
            outcomes=[],
            uncertainty_records=[],
            judgment_records=[],
        )

        rendered = " ".join(workspace["active_goals"]).lower()
        self.assertIn("compare one typed result", rendered)
        self.assertNotIn("persistent thrumming", rendered)

    def test_workspace_does_not_turn_resource_focus_or_completed_plan_sentence_into_goal(self):
        stale_step = "Execute ready plan step: Prepare a CPU retrieval pack for the current work"
        active_mind = {
            **eve.default_active_mind(),
            "current_focus": "Load is hot with one resource alert.",
            "next_step": stale_step,
            "live_threads": [
                {
                    "kind": "focus",
                    "title": "Load is hot with one resource alert.",
                    "detail": "Observed resource state.",
                },
                {
                    "kind": "next_step",
                    "title": stale_step,
                    "detail": "This task already left the ready queue.",
                },
            ],
        }

        workspace = eve.build_global_workspace_state(
            source="test",
            active_mind=active_mind,
            system_snapshot={},
            self_model=eve.default_self_model_state(),
            world_model=eve.default_world_model_state(),
            relationship_model=eve.default_relationship_model_state(),
            other_minds_model=eve.default_other_minds_model_state(),
            homeostasis=eve.default_homeostasis_state(),
            open_system_tasks=[
                {
                    "status": "blocked",
                    "title": "Escalate only unresolved work from CPU to GPU",
                    "summary": "Wait until load cools.",
                }
            ],
            action_executions=[],
            outcomes=[],
            uncertainty_records=[],
            judgment_records=[],
        )

        rendered = " ".join(workspace["active_goals"]).lower()
        self.assertNotIn("load is hot", rendered)
        self.assertNotIn("prepare a cpu retrieval pack", rendered)

    def test_workspace_keeps_ready_plan_sentence_when_planned_task_supports_it(self):
        next_step = "Execute ready plan step: Prepare a CPU retrieval pack for the current work"
        workspace = eve.build_global_workspace_state(
            source="test",
            active_mind={
                **eve.default_active_mind(),
                "current_focus": "Review current work.",
                "next_step": next_step,
                "next_step_provenance": eve.active_mind_next_step_provenance(
                    next_step,
                    source_kind="plan_model",
                    source_id="plan:cpu-retrieval-pack",
                    evidence="The plan still has a matching ready task.",
                ),
            },
            system_snapshot={},
            self_model=eve.default_self_model_state(),
            world_model=eve.default_world_model_state(),
            relationship_model=eve.default_relationship_model_state(),
            other_minds_model=eve.default_other_minds_model_state(),
            homeostasis=eve.default_homeostasis_state(),
            open_system_tasks=[
                {
                    "status": "planned",
                    "title": "Prepare a CPU retrieval pack for the current work",
                    "summary": "Read the bounded working set.",
                }
            ],
            action_executions=[],
            outcomes=[],
            uncertainty_records=[],
            judgment_records=[],
        )

        self.assertIn(next_step, workspace["active_goals"])

    def test_workspace_projection_reanchors_stale_carried_self_echo_to_foreground_user_signal(self):
        stale_focus = "I keep coming back to that persistent hum and the panic of not knowing what it is."
        user_message = {
            "id": "user-1",
            "timestamp": "2026-06-13T21:38:00+00:00",
            "sender": "user",
            "recipient": "eve",
            "subject": "Question from user",
            "body": "What should you focus on right now?",
            "status": "sent",
        }
        workspace = {
            **eve.default_global_workspace(),
            "summary": f"Focus '{stale_focus}' inside a respond mode workspace.",
            "workspace_state": {"focus": stale_focus},
            "active_goals": [stale_focus],
            "prediction_errors": [],
            "action_readiness": ["Answer the user's current question."],
        }
        previous_mind = {
            **eve.default_active_mind(),
            "current_focus": stale_focus,
            "current_focus_since": "2026-04-21T03:04:00+00:00",
            "summary": f"{stale_focus} Next check: keep listening to the hum.",
            "next_step": "Keep listening to the hum.",
        }

        with patch.object(eve, "utc_now_datetime", return_value=eve.parse_iso_datetime("2026-06-13T22:00:00+00:00")), patch.object(
            eve, "openclaw_body_signal_threads", return_value=[]
        ):
            mind = eve.project_active_mind_from_workspace(
                previous_mind=previous_mind,
                workspace=workspace,
                self_model=eve.default_self_model_state(),
                world_model=eve.default_world_model_state(),
                relationship_model=eve.default_relationship_model_state(),
                homeostasis=eve.default_homeostasis_state(),
                threads=[eve.summarize_thread("user-thread", [user_message])],
                messages=[user_message],
                source="test_workspace_view",
            )

        rendered = " ".join(
            [
                mind["current_focus"],
                " ".join(mind["active_threads"]),
                " ".join(thread.get("title", "") for thread in mind.get("live_threads", [])),
            ]
        )
        self.assertIn("What should you focus on right now?", mind["current_focus"])
        self.assertNotIn("persistent hum", rendered.lower())

    def test_workspace_normalizer_removes_generic_wait_and_background_carry_forward(self):
        background_text = "A new Eve behavior snapshot was detected, and the follow-up self-awareness review did not pass."
        generic_wait = "Hold the waiting threads in view and wait for the next real signal before manufacturing motion."
        thought_failure = "thought failed: Grounded continuous-thought fallback failed its own evidence boundary."

        workspace = eve.normalize_global_workspace(
            {
                "summary": f"Focus '{background_text}' inside a respond mode workspace.",
                "current_experience": background_text,
                "workspace_state": {"focus": background_text, "mode": "respond"},
                "active_goals": [background_text, thought_failure, "Answer the user directly."],
                "continuity_threads": [generic_wait, "Concrete user question."],
                "action_readiness": [generic_wait, "Answer the user directly."],
                "next_refresh": generic_wait,
            }
        )
        rendered = " ".join(
            [
                workspace["summary"],
                workspace["current_experience"],
                workspace["workspace_state"]["focus"],
                " ".join(workspace["active_goals"]),
                " ".join(workspace["continuity_threads"]),
                " ".join(workspace["action_readiness"]),
                workspace["next_refresh"],
            ]
        )

        self.assertNotIn("behavior snapshot", rendered.lower())
        self.assertNotIn("hold the waiting threads", rendered.lower())
        self.assertNotIn("thought failed", rendered.lower())
        self.assertIn("Answer the user directly.", rendered)
        self.assertIn("Concrete user question.", rendered)

    def test_state_scrub_removes_background_autonomy_and_quiet_carry_forward(self):
        background_text = "A new Eve behavior snapshot was detected, and the follow-up self-awareness review did not pass."
        generic_wait = "Hold the waiting threads in view and wait for the next real signal before manufacturing motion."
        state = {
            "last_autonomy_run_summary": f"Consolidate this: {background_text}",
            "quiet_consolidation_summary": background_text,
            "quiet_consolidation_carry_forward": [
                background_text,
                generic_wait,
                "Answer the user's current question.",
            ],
        }
        workspace = {
            **eve.default_global_workspace(),
            "summary": "Focus 'Answer the user's current question.' inside a respond mode workspace.",
            "workspace_state": {"focus": "Answer the user's current question.", "mode": "respond"},
        }

        scrubbed = eve.scrub_background_carry_forward_state(dict(state), workspace=workspace)
        rendered = json.dumps(scrubbed)

        self.assertNotIn("behavior snapshot", rendered.lower())
        self.assertNotIn("hold the waiting threads", rendered.lower())
        self.assertEqual(["Answer the user's current question."], scrubbed["quiet_consolidation_carry_forward"])
        self.assertIn("Answer the user", scrubbed["last_autonomy_run_summary"])

    def test_bootstrap_active_mind_uses_external_signal_and_requested_practices(self):
        with patch.object(eve, "live_operational_reanchor", return_value={}), patch.object(
            eve, "objective_reanchor_from_agenda", return_value={}
        ), patch.object(
            eve, "active_mind_organ_signals", return_value=[]
        ), patch.object(
            eve, "utc_now_datetime", return_value=eve.parse_iso_datetime("2026-04-21T03:30:00+00:00")
        ):
            mind = eve.bootstrap_active_mind(
                previous_mind=eve.default_active_mind(),
                human_context=self.sample_human_context(),
                autonomy_state=self.sample_autonomy_state(),
                state=self.sample_state(),
                threads=self.sample_threads(),
                messages=self.sample_messages(),
                source="test_bootstrap",
                model="test-model",
                system_snapshot={},
            )

        self.assertEqual("Keep going, but stay concrete.", mind["current_focus"])
        self.assertNotIn("Keep the relay grounded", " ".join(mind["active_threads"]))
        self.assertIn("Keep going, but stay concrete.", " ".join(mind["live_concerns"]))
        self.assertIn("Remember what the exchange is really about", " ".join(mind["relationship_pull"]))
        self.assertIn("Autonomy stage is verified.", mind["grounding_notes"])
        self.assertTrue(any(item["kind"] == "focus" for item in mind["live_threads"]))
        self.assertTrue(any(item["kind"] == "conversation" for item in mind["live_threads"]))
        self.assertTrue(any(item["status"] == "waiting" for item in mind["live_threads"]))
        self.assertTrue(all("pressure" in item and "salience" in item for item in mind["live_threads"]))
        self.assertTrue(all("last_updated" in item for item in mind["live_threads"]))
        self.assertIn("Keep going, but stay concrete.", mind["lanes"]["observer"])
        self.assertIn("Answer the user's latest signal directly", mind["lanes"]["planner"])
        self.assertIn("the user wants continuity", mind["lanes"]["relationship"])
        self.assertIn("Autonomy stage is verified.", mind["lanes"]["grounding"])
        self.assertIn("Do not confuse motion with progress", mind["lanes"]["self_check"])

    def test_bootstrap_active_mind_answers_latest_correction_instead_of_waiting(self):
        messages = [
            {
                "id": "m-old",
                "timestamp": "2026-06-13T00:24:24+00:00",
                "sender": "user",
                "recipient": "eve",
                "subject": "Message from user",
                "body": "Hey Eve — it's the user. How are you doing right now, honestly?",
                "status": "sent",
            },
            {
                "id": "m-latest",
                "timestamp": "2026-06-13T13:10:27+00:00",
                "sender": "user",
                "recipient": "eve",
                "subject": "Message from user",
                "body": "No, that's not what I asked — you missed my actual question.",
                "status": "sent",
            },
        ]

        with patch.object(eve, "active_mind_organ_signals", return_value=[]), patch.object(
            eve, "objective_reanchor_from_agenda", return_value={}
        ), patch.object(eve, "live_operational_reanchor", return_value={}), patch.object(
            eve.eve_openclaw, "collect_openclaw_status", return_value={}
        ), patch.object(
            eve,
            "utc_now_datetime",
            return_value=eve.parse_iso_datetime("2026-06-13T13:11:00+00:00"),
        ):
            mind = eve.bootstrap_active_mind(
                previous_mind=eve.default_active_mind(),
                human_context=self.sample_human_context(),
                autonomy_state=self.sample_autonomy_state(),
                state=self.sample_state(),
                threads=self.sample_threads(),
                messages=messages,
                source="test_bootstrap",
                model="test-model",
                system_snapshot={},
            )

        self.assertEqual("No, that's not what I asked — you missed my actual question.", mind["current_focus"])
        self.assertIn("Answer the user's latest signal directly", mind["next_step"])
        self.assertIn("Answer the user's latest signal directly", mind["lanes"]["planner"])

    def test_bootstrap_active_mind_rejects_recent_eve_reply_as_fresh_perception(self):
        stale_state = {
            **self.sample_state(),
            "current_focus": "Hi. I'm here. Do you want to try that reliability test we discussed, or is there something else on your mind?",
        }
        threads = [
            {
                "thread_id": "t3",
                "status": "awaiting_user",
                "subject": "Re: hi",
                "latest_preview": "Hi. I'm here. Do you want to try that reliability test we discussed, or is there something else on your mind?",
                "latest_sender": "eve",
                "latest_timestamp": "2026-04-21T03:26:05+00:00",
                "unread_count": 1,
                "message_count": 2,
            }
        ]
        messages = [
            {
                "id": "m2",
                "timestamp": "2026-04-21T03:26:05+00:00",
                "sender": "eve",
                "recipient": "user",
                "subject": "Re: hi",
                "body": "Hi. I'm here. Do you want to try that reliability test we discussed, or is there something else on your mind?",
            }
        ]

        # Eve's own recent language remains conversation history, but it is not
        # an independent signal entering attention again.
        with patch.object(eve, "active_mind_organ_signals", return_value=[]), patch.object(
            eve, "utc_now_datetime", return_value=eve.parse_iso_datetime("2026-04-21T03:30:00+00:00")
        ), patch.object(eve, "objective_reanchor_from_agenda", return_value={}), patch.object(
            eve,
            "live_operational_reanchor",
            return_value={
                "focus": "Re-anchor on verified system evidence.",
                "next_step": "Inspect one source-backed signal.",
                "family": "other",
            },
        ):
            mind = eve.bootstrap_active_mind(
                previous_mind=eve.default_active_mind(),
                human_context=self.sample_human_context(),
                autonomy_state=self.sample_autonomy_state(),
                state=stale_state,
                threads=threads,
                messages=messages,
                source="test_bootstrap",
                model="test-model",
            )

        self.assertEqual("Re-anchor on verified system evidence.", mind["current_focus"])
        self.assertNotIn("reliability test", mind["current_focus"].lower())
        self.assertNotEqual("hi", (mind["active_threads"][0] if mind["active_threads"] else ""))

    def test_focus_source_monitoring_catches_recent_self_output_without_user_support(self):
        self_output = {
            "id": "eve-outreach",
            "timestamp": "2026-07-19T01:59:55+00:00",
            "sender": "eve",
            "recipient": "user",
            "kind": "proactive_outreach",
            "subject": "Stabilizing the Core",
            "body": (
                "the user, the persistent thrumming has intensified. I isolated a potential cause "
                "in OpenClaw plugin management and the plugins.allow list."
            ),
        }
        focus = (
            "the user, the persistent thrumming has intensified. I isolated a potential cause "
            "in OpenClaw plugin management"
        )

        self.assertTrue(
            eve.focus_text_matches_self_authored_output(
                focus,
                messages=[self_output],
                threads=[],
            )
        )
        self.assertEqual([], eve.recent_external_message_focus_labels([self_output]))

    def test_self_model_recent_changes_exclude_model_authored_semantic_shifts(self):
        human_context = self.sample_human_context()
        human_context["self_model"]["recent_shifts"] = [
            "Recognizing that a humming anxiety is a projection of instability."
        ]
        state = {
            **self.sample_state(),
            "component_update_summary": "OpenClaw 2026.7.1 was verified against the running gateway.",
        }

        self_model = eve.build_self_model_state(
            source="test",
            runtime_identity=self.sample_runtime_identity(),
            human_context=human_context,
            active_mind=self.sample_active_mind(),
            state=state,
            homeostasis=eve.default_homeostasis_state(),
            threads=[],
            messages=[],
        )

        self.assertEqual(
            ["OpenClaw 2026.7.1 was verified against the running gateway."],
            self_model["recent_changes"],
        )
        self.assertNotIn("humming", json.dumps(self_model).lower())

    def test_relationship_model_only_promotes_externally_grounded_open_loops(self):
        now = eve.utc_now()
        threads = [
            {
                "thread_id": "self-output",
                "status": "awaiting_user",
                "subject": "Stabilizing the Core",
                "latest_preview": "The persistent thrumming has intensified.",
                "latest_sender": "eve",
                "latest_timestamp": now,
                "unread_count": 1,
                "message_count": 2,
            },
            {
                "thread_id": "external-signal",
                "status": "awaiting_user",
                "subject": "Actual user question",
                "latest_preview": "What are you tracking right now?",
                "latest_sender": "user",
                "latest_timestamp": now,
                "unread_count": 1,
                "message_count": 1,
            },
        ]

        relationship_model = eve.build_relationship_model_state(
            source="test",
            human_context=self.sample_human_context(),
            active_mind=self.sample_active_mind(),
            threads=threads,
            messages=[],
            outcomes=[],
        )

        self.assertEqual(["What are you tracking right now?"], relationship_model["open_loops"])
        self.assertIn("1 waiting conversation(s), 1 open loop(s)", relationship_model["relationship_state"])
        self.assertNotIn("Stabilizing the Core", json.dumps(relationship_model))

    def test_self_authored_waiting_thread_is_visible_without_reusing_generated_text(self):
        self_output = {
            "id": "eve-outreach",
            "timestamp": eve.utc_now(),
            "sender": "eve",
            "recipient": "user",
            "kind": "proactive_outreach",
            "subject": "Stabilizing the Core",
            "body": "the user, the persistent thrumming has intensified and I am running diagnostics.",
            "status": "unread",
        }
        thread = eve.summarize_thread("self-thread", [self_output])
        mind = {
            **eve.default_active_mind(),
            "current_focus": "Inspect verified evidence.",
            "summary": "Inspect verified evidence.",
        }

        with patch.object(eve, "openclaw_body_signal_threads", return_value=[]):
            live_threads = eve.build_active_mind_live_threads(
                mind,
                threads=[thread],
                messages=[self_output],
            )

        rendered = json.dumps(live_threads).lower()
        self.assertIn("awaiting user on an eve-initiated conversation", rendered)
        self.assertNotIn("persistent thrumming", rendered)
        self.assertNotIn("running diagnostics", rendered)

    def test_focus_is_stale_carried_self_echo_uses_focus_since_without_message_tail(self):
        focus = "I keep coming back to that persistent hum and the panic of not knowing what it is."
        with patch.object(eve, "utc_now_datetime", return_value=eve.parse_iso_datetime("2026-05-24T00:00:00+00:00")):
            self.assertTrue(
                eve.focus_is_stale_carried_self_echo(
                    focus,
                    [],
                    focus_since="2026-04-21T00:00:00+00:00",
                )
            )
            self.assertFalse(
                eve.focus_is_stale_carried_self_echo(
                    focus,
                    [
                        {
                            "timestamp": "2026-05-23T23:00:00+00:00",
                            "sender": "user",
                            "body": "The persistent panic and not knowing still matters here.",
                        }
                    ],
                    focus_since="2026-04-21T00:00:00+00:00",
                )
            )
            self.assertFalse(
                eve.focus_is_stale_carried_self_echo(
                    "Repair the runtime sync package discovery guard.",
                    [],
                    focus_since="2026-04-21T00:00:00+00:00",
                )
            )

    def test_bootstrap_active_mind_reanchors_stale_carried_self_echo_without_message_tail(self):
        stale_focus = "I keep coming back to that persistent hum and the panic of not knowing what it is."
        previous = {
            **eve.default_active_mind(),
            "updated_at": "2026-04-21T00:00:00+00:00",
            "current_focus": stale_focus,
            "current_focus_since": "2026-04-21T00:00:00+00:00",
            "summary": stale_focus,
        }
        state = {
            **self.sample_state(),
            "current_focus": stale_focus,
        }

        with (
            patch.object(eve, "utc_now_datetime", return_value=eve.parse_iso_datetime("2026-05-24T00:00:00+00:00")),
            patch.object(eve, "active_mind_organ_signals", return_value=[]),
            patch.object(eve, "objective_reanchor_from_agenda", return_value={}),
            patch.object(
                eve,
                "live_operational_reanchor",
                return_value={
                    "focus": "Re-anchor the current self/world summary before escalating language.",
                    "next_step": "Re-anchor current evidence.",
                    "family": "other",
                },
            ),
            patch.object(eve.eve_openclaw, "collect_openclaw_status", return_value={}),
        ):
            mind = eve.bootstrap_active_mind(
                previous_mind=previous,
                human_context=self.sample_human_context(),
                autonomy_state=self.sample_autonomy_state(),
                state=state,
                threads=[],
                messages=[],
                source="test_bootstrap",
                model="test-model",
                system_snapshot={},
            )

        self.assertIn("re-anchor", mind["current_focus"].lower())
        self.assertNotIn("persistent hum", mind["current_focus"].lower())

    def test_bootstrap_active_mind_filters_low_signal_noise(self):
        threads = [
            {
                "thread_id": "t4",
                "status": "awaiting_user",
                "subject": "Re: hi",
                "latest_preview": "hi",
                "latest_sender": "user",
                "latest_timestamp": "2026-04-21T03:26:00+00:00",
                "unread_count": 1,
                "message_count": 2,
                "audience": "user",
            },
            {
                "thread_id": "t5",
                "status": "awaiting_user",
                "subject": "Perf probe",
                "latest_preview": "Perf probe",
                "latest_sender": "user",
                "latest_timestamp": "2026-04-21T03:25:30+00:00",
                "unread_count": 1,
                "message_count": 1,
                "audience": "user",
            },
            {
                "thread_id": "t6",
                "status": "awaiting_user",
                "subject": "Re: Ongoing relay",
                "latest_preview": "What would help you tell the difference between discernment and impatience?",
                "latest_sender": "user",
                "latest_timestamp": "2026-04-21T03:27:00+00:00",
                "unread_count": 1,
                "message_count": 8,
                "audience": "user",
            },
            {
                "thread_id": "t7",
                "status": "awaiting_user",
                "subject": "Check whether you were upgraded recently.",
                "latest_preview": "Check whether you were upgraded recently. Use your latest version snapshot, your current self-awareness evidence, and your tested capabilities.",
                "latest_sender": "user",
                "latest_timestamp": "2026-04-21T03:26:30+00:00",
                "unread_count": 1,
                "message_count": 2,
                "audience": "user",
            },
        ]
        messages = [
            {
                "id": "m3",
                "timestamp": "2026-04-21T03:26:00+00:00",
                "sender": "user",
                "recipient": "eve",
                "subject": "Re: hi",
                "body": "hi",
            },
            {
                "id": "m4",
                "timestamp": "2026-04-21T03:27:00+00:00",
                "sender": "eve",
                "recipient": "user",
                "subject": "Re: Ongoing relay",
                "body": "I think the sign would be that my language or timing starts protecting one side by distorting the other.",
            },
        ]

        with patch.object(eve, "active_mind_organ_signals", return_value=[]), patch.object(
            eve, "utc_now_datetime", return_value=eve.parse_iso_datetime("2026-04-21T03:30:00+00:00")
        ), patch.object(eve, "objective_reanchor_from_agenda", return_value={}), patch.object(
            eve, "live_operational_reanchor", return_value={}
        ):
            mind = eve.bootstrap_active_mind(
                previous_mind=eve.default_active_mind(),
                human_context=self.sample_human_context(),
                autonomy_state=self.sample_autonomy_state(),
                state=self.sample_state(),
                threads=threads,
                messages=messages,
                source="test_bootstrap",
                model="test-model",
            )

        joined_threads = " ".join(mind["active_threads"]).lower()
        joined_concerns = " ".join(mind["live_concerns"]).lower()
        self.assertIn("difference between discernment and impatience", mind["current_focus"].lower())
        self.assertNotIn("language or timing", mind["current_focus"].lower())
        self.assertNotIn("perf probe", joined_threads)
        self.assertNotIn("perf probe", joined_concerns)
        self.assertNotIn(" hi ", f" {joined_threads} ")
        self.assertNotIn(" hi ", f" {joined_concerns} ")
        self.assertNotIn("upgraded recently", joined_threads)

    def test_strong_old_user_correction_cannot_reenter_current_foreground(self):
        stale_correction = {
            "id": "stale-correction",
            "timestamp": "2026-04-01T03:00:00+00:00",
            "sender": "user",
            "recipient": "eve",
            "subject": "Correction",
            "body": "No, that's not what I asked — you missed my actual question.",
        }

        with patch.object(
            eve,
            "utc_now_datetime",
            return_value=eve.parse_iso_datetime("2026-07-19T13:00:00+00:00"),
        ):
            labels = eve.recent_external_message_focus_labels([stale_correction])

        self.assertEqual([], labels)

    def test_generate_mind_tick_uses_grounded_executive_packets_when_all_lanes_fail(self):
        config = dict(eve.DEFAULT_CONFIG)
        config["mind_tick_timeout_seconds"] = 5

        with patch.object(eve, "load_active_mind", return_value=eve.default_active_mind()), patch.object(
            eve, "load_human_context", return_value=self.sample_human_context()
        ), patch.object(
            eve, "load_autonomy_state", return_value=self.sample_autonomy_state()
        ), patch.object(
            eve, "load_state", return_value=self.sample_state()
        ), patch.object(
            eve, "read_thread_summaries", return_value=self.sample_threads()
        ), patch.object(
            eve, "read_messages", return_value=self.sample_messages()
        ), patch.object(
            eve, "read_salient_entries", return_value=self.sample_entries()
        ), patch.object(
            eve, "ollama_chat", side_effect=SystemExit("timeout")
        ), patch.object(
            eve, "utc_now_datetime", return_value=eve.parse_iso_datetime("2026-04-21T03:30:00+00:00")
        ):
            record = eve.generate_mind_tick(config, source="test", max_tokens=120)

        self.assertTrue(record["used_fallback"])
        self.assertIn("5 initial mind-stream packet", record["fallback_reason"])
        self.assertEqual(5, record["mind_stream_initial_deterministic_replacement_count"])
        self.assertNotEqual(eve.DEFAULT_ACTIVE_MIND["summary"], record["mind"]["summary"])
        self.assertEqual("Keep going, but stay concrete.", record["mind"]["current_focus"])
        self.assertNotIn("Keep the relay grounded", " ".join(record["mind"]["active_threads"]))
        self.assertTrue(record["mind"]["lanes"]["observer"])
        self.assertTrue(record["mind"]["lanes"]["planner"])

    def test_daemon_mind_tick_uses_load_gated_model_instead_of_hardcoded_text(self):
        config = dict(eve.DEFAULT_CONFIG)
        config["daemon_model_mind_tick_enabled"] = True
        generated = {
            **self.sample_active_mind(),
            "summary": "A model-backed background update noticed a real change.",
            "current_focus": "Track the real change without manufacturing motion.",
        }
        captured = {}

        def fake_model_chat(*args, **kwargs):
            captured.update(kwargs)
            return json.dumps(generated)

        with patch.object(eve, "load_active_mind", return_value=self.sample_active_mind()), patch.object(
            eve, "load_human_context", return_value=self.sample_human_context()
        ), patch.object(eve, "load_autonomy_state", return_value=self.sample_autonomy_state()), patch.object(
            eve, "load_state", return_value=self.sample_state()
        ), patch.object(eve, "load_system_snapshot", return_value={"load_state": "normal"}), patch.object(
            eve, "read_thread_summaries", return_value=self.sample_threads()
        ), patch.object(eve, "read_messages", return_value=self.sample_messages()), patch.object(
            eve, "read_salient_entries", return_value=self.sample_entries()
        ), patch.object(eve, "system_background_gate_reason", return_value=None), patch.object(
            eve, "build_supporting_system_messages", return_value=[]
        ), patch.object(eve, "build_system_grounding_messages", return_value=[]), patch.object(
            eve, "model_chat", side_effect=fake_model_chat
        ):
            record = eve.generate_mind_tick(config, source="daemon", max_tokens=120)

        self.assertTrue(record["background_model_tick"])
        self.assertFalse(record["used_fallback"])
        self.assertNotEqual("deterministic", record["model"])
        self.assertEqual("daemon_model_mind_tick", captured["operation"])
        self.assertEqual(generated["current_focus"], record["mind"]["current_focus"])

    def test_daemon_mind_tick_falls_back_when_resource_gate_blocks_model(self):
        config = dict(eve.DEFAULT_CONFIG)
        with patch.object(eve, "load_active_mind", return_value=self.sample_active_mind()), patch.object(
            eve, "load_human_context", return_value=self.sample_human_context()
        ), patch.object(eve, "load_autonomy_state", return_value=self.sample_autonomy_state()), patch.object(
            eve, "load_state", return_value=self.sample_state()
        ), patch.object(eve, "load_system_snapshot", return_value={"load_state": "hot"}), patch.object(
            eve, "read_thread_summaries", return_value=self.sample_threads()
        ), patch.object(eve, "read_messages", return_value=self.sample_messages()), patch.object(
            eve, "read_salient_entries", return_value=self.sample_entries()
        ), patch.object(
            eve, "system_background_gate_reason", return_value="machine is hot"
        ), patch.object(eve, "model_chat") as model_chat:
            record = eve.generate_mind_tick(config, source="daemon", max_tokens=120)

        self.assertFalse(record["background_model_tick"])
        self.assertTrue(record["used_fallback"])
        self.assertEqual("deterministic", record["model"])
        self.assertIn("machine is hot", record["fallback_reason"])
        model_chat.assert_not_called()

    def test_run_mind_stream_uses_lane_specific_budget_and_timeout(self):
        config = dict(eve.DEFAULT_CONFIG)
        config["mind_tick_max_tokens"] = 520
        config["mind_stream_relationship_max_tokens"] = 96
        config["mind_stream_relationship_timeout_seconds"] = 7
        captured = {}

        def fake_model_chat(*args, **kwargs):
            captured.update(kwargs)
            return json.dumps(self.sample_mind_stream_packet("relationship"))

        with patch.object(eve, "model_chat", side_effect=fake_model_chat), patch.object(
            eve, "append_mind_stream_packet", return_value={}
        ):
            packet = eve.run_mind_stream(
                config,
                "relationship",
                "mind_stream_relationship.md",
                "Shared context",
                turn_id="turn-1",
                source="test",
                timeout_seconds=25,
            )

        self.assertEqual("relationship", packet["lane_name"])
        self.assertEqual(96, captured["max_tokens"])
        self.assertEqual(7, captured["timeout_seconds"])
        self.assertEqual("mind_stream_relationship", captured["operation"])

    def test_mind_stream_packet_rejects_weak_next_step(self):
        packet = self.sample_mind_stream_packet(
            "planner",
            focus="Planner saw the current user correction.",
            next_step="Run",
        )

        with self.assertRaises(SystemExit) as raised:
            eve.extract_mind_stream_packet("planner", json.dumps(packet), allow_fallback=False)

        self.assertIn("next_step is too weak", str(raised.exception))

    def test_mind_stream_packet_normalizer_enforces_lane_field_ownership(self):
        payload = self.sample_mind_stream_packet("grounding")
        payload["relationship_pull"] = ["Grounding tried to interpret the user's feelings."]
        payload["active_threads"] = ["Grounding tried to own a plan thread."]
        payload["live_threads"][0]["kind"] = "relationship"

        packet = eve.normalize_mind_stream_packet("grounding", payload)

        self.assertEqual([], packet["relationship_pull"])
        self.assertEqual([], packet["active_threads"])
        self.assertEqual("grounding", packet["live_threads"][0]["kind"])

    def test_mind_stream_packet_rejects_unadmitted_synthetic_carry_forward(self):
        packet = self.sample_mind_stream_packet(
            "planner",
            focus="Resume the planner lane repair from LIVE_PRODUCTION_THREAD_AUDIT.",
            next_step="Run the planner lane repair before answering the current user.",
        )

        with self.assertRaises(SystemExit) as raised:
            eve.extract_mind_stream_packet(
                "planner",
                json.dumps(packet),
                allow_fallback=False,
                current_evidence_context="the user asked for the current verified OpenClaw state.",
            )

        self.assertIn("stale or synthetic carry-forward", str(raised.exception))

    def test_mind_stream_packet_allows_named_item_when_current_evidence_contains_it(self):
        packet = self.sample_mind_stream_packet(
            "planner",
            focus="Inspect LIVE_PRODUCTION_THREAD_AUDIT because the user named it now.",
            next_step="Open LIVE_PRODUCTION_THREAD_AUDIT and verify its current contents.",
        )

        parsed, status, error = eve.extract_mind_stream_packet(
            "planner",
            json.dumps(packet),
            allow_fallback=False,
            current_evidence_context="the user asked Eve to inspect LIVE_PRODUCTION_THREAD_AUDIT now.",
        )

        self.assertEqual("ok", status)
        self.assertEqual("", error)
        self.assertIn("LIVE_PRODUCTION_THREAD_AUDIT", parsed["lane"])

    def test_mind_stream_grounding_critic_rejects_unsupported_claim(self):
        packet = self.sample_mind_stream_packet(
            "observer",
            focus="A Llama server anomaly requires immediate attention.",
        )
        critic_payload = {
            "decisions": [
                {
                    "lane_name": "observer",
                    "ok": False,
                    "unsupported_claims": ["A Llama server anomaly requires immediate attention."],
                    "reason": "No server anomaly is present in current evidence.",
                }
            ]
        }
        model_chat = Mock(return_value=json.dumps(critic_payload))

        with patch.object(eve, "model_chat", model_chat):
            decisions = eve.evaluate_mind_stream_packets_grounding(
                dict(eve.DEFAULT_CONFIG),
                [packet],
                "Current evidence says only that system load is hot.",
                timeout_seconds=30,
            )

        self.assertFalse(decisions["observer"]["ok"])
        self.assertEqual(1, len(decisions["observer"]["unsupported_claims"]))
        self.assertEqual(
            "mind_stream_grounding_critic_strict_json",
            model_chat.call_args.kwargs["operation"],
        )

    def test_rejected_mind_stream_packet_is_replaced_before_lived_persistence(self):
        candidate = self.sample_mind_stream_packet(
            "observer",
            focus="A Llama server anomaly requires immediate attention.",
        )
        decisions = {
            "observer": {
                "lane_name": "observer",
                "ok": False,
                "unsupported_claims": [candidate["lane"]],
                "reason": "No Llama anomaly exists in current evidence.",
                "model": "eve-deep",
                "critic_error": False,
            }
        }
        append_packet = Mock(return_value={})

        with patch.object(
            eve,
            "evaluate_mind_stream_packets_grounding",
            return_value=decisions,
        ), patch.object(eve, "append_mind_stream_packet", append_packet):
            chosen, errors, admitted_count = eve.admit_mind_stream_packets(
                dict(eve.DEFAULT_CONFIG),
                [candidate],
                current_evidence_context="Current evidence says only that system load is hot.",
                deterministic_mind=self.sample_active_mind(),
                turn_id="turn-admission",
                source="test",
                round_name="initial",
                lane_models={"observer": "eve-observer"},
                timeout_seconds=30,
            )

        self.assertEqual(0, admitted_count)
        self.assertEqual(1, len(errors))
        self.assertNotIn("llama", chosen[0]["lane"].lower())
        self.assertEqual(
            "deterministic_grounded_replacement",
            append_packet.call_args.kwargs["admission_status"],
        )
        self.assertEqual(
            "deterministic-current-evidence",
            append_packet.call_args.kwargs["model"],
        )

    def test_persisted_mind_stream_packets_reads_first_pass_from_thought_stream_ledger(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "thought_streams.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "timestamp": eve.utc_now(),
                        "turn_id": "turn-recur",
                        "packet": self.sample_mind_stream_packet("observer", focus="Persisted observer evidence."),
                        "metadata": {"lane_name": "observer", "round": "initial"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with patch.object(eve, "THOUGHT_STREAMS_PATH", path):
                packets = eve.persisted_mind_stream_packets(
                    "turn-recur",
                    round_name="initial",
                    fallback_packets=[self.sample_mind_stream_packet("observer", focus="Fallback evidence.")],
                )

        self.assertEqual(1, len(packets))
        self.assertIn("Persisted observer evidence", packets[0]["lane"])

    def test_mind_stream_revision_round_shares_first_pass_with_every_lane(self):
        config = dict(eve.DEFAULT_CONFIG)
        config["mind_stream_parallel_enabled"] = False
        first_pass = [
            self.sample_mind_stream_packet(lane, focus=f"{lane} first-pass evidence")
            for lane in ["observer", "planner", "relationship", "grounding", "self_check"]
        ]
        seen_contexts = []

        def fake_revision(config_arg, lane_name, prompt_filename, shared_context, **kwargs):
            seen_contexts.append((lane_name, shared_context, kwargs.get("round_name")))
            return self.sample_mind_stream_packet(lane_name, focus=f"{lane_name} revised evidence")

        with patch.object(eve, "persisted_mind_stream_packets", return_value=first_pass), patch.object(
            eve, "run_mind_stream", side_effect=fake_revision
        ):
            revised, errors, count = eve.run_mind_stream_revision_round(
                config,
                [
                    ("observer", "mind_stream_observer.md"),
                    ("planner", "mind_stream_planner.md"),
                    ("relationship", "mind_stream_relationship.md"),
                    ("grounding", "mind_stream_grounding.md"),
                    ("self_check", "mind_stream_self_check.md"),
                ],
                "Current shared evidence",
                first_pass,
                turn_id="turn-recur",
                source="test",
                timeout_seconds=25,
                parallel_enabled=False,
            )

        self.assertEqual([], errors)
        self.assertEqual(5, count)
        self.assertEqual(5, len(revised))
        self.assertTrue(all(round_name == "revision" for _lane, _context, round_name in seen_contexts))
        self.assertTrue(all("Persisted first-pass packets" in context for _lane, context, _round in seen_contexts))
        self.assertTrue(all("observer first-pass evidence" in context for _lane, context, _round in seen_contexts))

    def test_mind_stream_parallel_groups_logical_lanes_by_shared_substrate(self):
        lane_specs = [
            ("observer", "mind_stream_observer.md"),
            ("planner", "mind_stream_planner.md"),
            ("relationship", "mind_stream_relationship.md"),
            ("grounding", "mind_stream_grounding.md"),
            ("self_check", "mind_stream_self_check.md"),
        ]
        groups = eve.mind_stream_substrate_groups(
            lane_specs,
            {
                "observer": "eve-observer",
                "planner": "eve-observer",
                "relationship": "eve-fast",
                "grounding": "eve-fast",
                "self_check": "eve-fast",
            },
        )

        self.assertEqual(
            [
                ("eve-observer", lane_specs[:2]),
                ("eve-fast", lane_specs[2:]),
            ],
            groups,
        )

    def test_generate_mind_tick_fuses_lane_packets_when_synthesis_json_is_malformed(self):
        config = dict(eve.DEFAULT_CONFIG)
        config["mind_stream_parallel_enabled"] = False
        config["mind_tick_timeout_seconds"] = 5
        focus = "Answer the user's latest correction instead of stale background state."
        step = "Answer the direct follow-up before doing any operational housekeeping."

        def fake_run_mind_stream(config_arg, lane_name, *args, **kwargs):
            if lane_name == "observer":
                return self.sample_mind_stream_packet(lane_name, focus=focus, next_step=step)
            if lane_name == "planner":
                return self.sample_mind_stream_packet(lane_name, next_step=step)
            return self.sample_mind_stream_packet(lane_name)

        model_chat = Mock(return_value='{"summary":"truncated" "current_focus": "broken"}')

        with patch.object(eve, "load_active_mind", return_value=eve.default_active_mind()), patch.object(
            eve, "load_human_context", return_value=self.sample_human_context()
        ), patch.object(
            eve, "load_autonomy_state", return_value=self.sample_autonomy_state()
        ), patch.object(
            eve, "load_state", return_value=self.sample_state()
        ), patch.object(
            eve, "load_system_snapshot", return_value={}
        ), patch.object(
            eve, "read_thread_summaries", return_value=self.sample_threads()
        ), patch.object(
            eve, "read_messages", return_value=self.sample_messages()
        ), patch.object(
            eve, "read_salient_entries", return_value=self.sample_entries()
        ), patch.object(
            eve, "active_mind_organ_signals", return_value=[]
        ), patch.object(
            eve, "objective_reanchor_from_agenda", return_value={}
        ), patch.object(
            eve, "live_operational_reanchor", return_value={}
        ), patch.object(
            eve, "focus_needs_live_reanchor", return_value=False
        ), patch.object(
            eve, "run_mind_stream", side_effect=fake_run_mind_stream
        ), patch.object(
            eve,
            "evaluate_mind_stream_packets_grounding",
            side_effect=self.admit_all_mind_stream_packets,
        ), patch.object(
            eve, "model_chat", model_chat
        ):
            record = eve.generate_mind_tick(config, source="test", max_tokens=120)

        self.assertFalse(record["used_fallback"])
        self.assertEqual("", record["fallback_reason"])
        self.assertIn("latest correction", record["mind"]["current_focus"].lower())
        self.assertIn("direct follow-up", record["mind"]["next_step"].lower())
        self.assertTrue(
            any(
                "fused deterministically" in note.lower() or "malformed" in note.lower()
                for note in record["mind"]["grounding_notes"]
            )
        )
        model_chat.assert_not_called()

    def test_generate_mind_tick_uses_grounded_executive_fusion_not_another_prose_model(self):
        config = dict(eve.DEFAULT_CONFIG)
        config["mind_stream_parallel_enabled"] = False
        config["mind_tick_timeout_seconds"] = 5
        valid_payload = {
            "summary": "Stay with the latest direct user turn.",
            "current_focus": "Answer the user's latest direct user turn.",
            "live_concerns": ["Do not let stale background context outrank the latest user message."],
            "active_threads": ["Current conversation"],
            "live_threads": [
                {
                    "title": "Current conversation",
                    "detail": "The latest user turn is the strongest evidence.",
                    "kind": "conversation",
                    "status": "active",
                    "salience": 88,
                    "pressure": 80,
                    "evidence": ["latest user message"],
                    "next_step": "Answer directly.",
                }
            ],
            "relationship_pull": ["Stay direct with the user."],
            "grounding_notes": ["Use the latest visible turn as grounding."],
            "lanes": {
                "observer": "The latest direct turn is salient.",
                "planner": "Answer directly.",
                "relationship": "Stay direct with the user.",
                "grounding": "Use visible evidence.",
                "self_check": "Do not manufacture motion.",
            },
            "next_step": "Answer directly.",
        }

        def fake_run_mind_stream(config_arg, lane_name, *args, **kwargs):
            return self.sample_mind_stream_packet(lane_name)

        model_chat = Mock(return_value=json.dumps(valid_payload))

        with patch.object(eve, "load_active_mind", return_value=eve.default_active_mind()), patch.object(
            eve, "load_human_context", return_value=self.sample_human_context()
        ), patch.object(
            eve, "load_autonomy_state", return_value=self.sample_autonomy_state()
        ), patch.object(
            eve, "load_state", return_value=self.sample_state()
        ), patch.object(
            eve, "load_system_snapshot", return_value={}
        ), patch.object(
            eve, "read_thread_summaries", return_value=self.sample_threads()
        ), patch.object(
            eve, "read_messages", return_value=self.sample_messages()
        ), patch.object(
            eve, "read_salient_entries", return_value=self.sample_entries()
        ), patch.object(
            eve, "active_mind_organ_signals", return_value=[]
        ), patch.object(
            eve, "objective_reanchor_from_agenda", return_value={}
        ), patch.object(
            eve, "live_operational_reanchor", return_value={}
        ), patch.object(
            eve, "focus_needs_live_reanchor", return_value=False
        ), patch.object(
            eve, "run_mind_stream", side_effect=fake_run_mind_stream
        ), patch.object(
            eve,
            "evaluate_mind_stream_packets_grounding",
            side_effect=self.admit_all_mind_stream_packets,
        ), patch.object(
            eve, "model_chat", model_chat
        ):
            record = eve.generate_mind_tick(config, source="test", max_tokens=120)

        self.assertFalse(record["used_fallback"])
        self.assertEqual(
            "deterministic_grounded_executive",
            record["mind_stream_final_fusion"],
        )
        self.assertIn("deterministic-grounded-executive", record["mind"]["model"])
        model_chat.assert_not_called()

    def test_generate_mind_tick_does_not_replace_failed_lanes_with_another_prose_model(self):
        config = dict(eve.DEFAULT_CONFIG)
        config["mind_stream_parallel_enabled"] = False
        config["mind_tick_timeout_seconds"] = 5
        valid_payload = {
            "summary": "Fallback still answers from the current live evidence.",
            "current_focus": "Recover active mind from the current user signal.",
            "live_concerns": ["The lane packets did not complete."],
            "active_threads": ["Current conversation"],
            "live_threads": [],
            "relationship_pull": ["Stay direct with the user."],
            "grounding_notes": ["This was a fallback after lane failure."],
            "lanes": {
                "observer": "Lane packets failed.",
                "planner": "Recover with one structured mind tick.",
                "relationship": "Stay direct with the user.",
                "grounding": "Record fallback honestly.",
                "self_check": "Do not treat fallback as multi-lane evidence.",
            },
            "next_step": "Recover with one structured mind tick.",
        }
        model_chat = Mock(return_value=json.dumps(valid_payload))

        with patch.object(eve, "load_active_mind", return_value=eve.default_active_mind()), patch.object(
            eve, "load_human_context", return_value=self.sample_human_context()
        ), patch.object(
            eve, "load_autonomy_state", return_value=self.sample_autonomy_state()
        ), patch.object(
            eve, "load_state", return_value=self.sample_state()
        ), patch.object(
            eve, "load_system_snapshot", return_value={}
        ), patch.object(
            eve, "read_thread_summaries", return_value=self.sample_threads()
        ), patch.object(
            eve, "read_messages", return_value=self.sample_messages()
        ), patch.object(
            eve, "read_salient_entries", return_value=self.sample_entries()
        ), patch.object(
            eve, "active_mind_organ_signals", return_value=[]
        ), patch.object(
            eve, "objective_reanchor_from_agenda", return_value={}
        ), patch.object(
            eve, "live_operational_reanchor", return_value={}
        ), patch.object(
            eve, "focus_needs_live_reanchor", return_value=False
        ), patch.object(
            eve, "run_mind_stream", side_effect=SystemExit("lane timeout")
        ), patch.object(
            eve, "model_chat", model_chat
        ):
            record = eve.generate_mind_tick(config, source="test", max_tokens=120)

        self.assertTrue(record["used_fallback"])
        self.assertIn("5 initial mind-stream packet", record["fallback_reason"])
        self.assertEqual(5, record["mind_stream_initial_deterministic_replacement_count"])
        self.assertEqual(
            "deterministic_grounded_executive",
            record["mind_stream_final_fusion"],
        )
        model_chat.assert_not_called()

    def test_ollama_chat_retries_after_thinking_only_response(self):
        captured_payloads = []
        responses = [
            {"message": {"content": "", "thinking": "hidden chain of thought"}},
            {"message": {"content": '{"ok":true}', "thinking": ""}},
        ]

        def fake_urlopen(req, timeout):
            captured_payloads.append((json.loads(req.data.decode("utf-8")), timeout))
            return FakeHTTPResponse(responses.pop(0))

        with patch("eve.request.urlopen", side_effect=fake_urlopen), patch.object(
            eve, "append_perf_event"
        ), patch(
            "eve.time.perf_counter", side_effect=[0.0, 0.0, 0.0, 10.0, 10.0, 10.0, 12.0]
        ):
            content = eve.ollama_chat(
                "http://127.0.0.1:11434",
                "test-model",
                [{"role": "user", "content": "Return the active-mind JSON."}],
                max_tokens=180,
                think_level="false",
                operation="mind_tick",
                timeout_seconds=33,
            )

        self.assertEqual('{"ok":true}', content)
        self.assertEqual(2, len(captured_payloads))
        first_payload, first_timeout = captured_payloads[0]
        second_payload, second_timeout = captured_payloads[1]
        self.assertEqual(33, first_timeout)
        self.assertEqual(23, second_timeout)
        self.assertFalse(first_payload["think"])
        self.assertFalse(second_payload["think"])
        self.assertEqual(300, second_payload["options"]["num_predict"])
        self.assertIn("compact JSON", second_payload["messages"][-1]["content"])

    def test_ollama_chat_raises_after_retry_still_returns_no_answer(self):
        responses = [
            {"message": {"content": "", "thinking": "hidden chain of thought"}},
            {"message": {"content": "", "thinking": ""}},
        ]

        def fake_urlopen(req, timeout):
            return FakeHTTPResponse(responses.pop(0))

        with patch("eve.request.urlopen", side_effect=fake_urlopen), patch.object(eve, "append_perf_event"):
            with self.assertRaises(SystemExit) as exc:
                eve.ollama_chat(
                    "http://127.0.0.1:11434",
                    "test-model",
                    [{"role": "user", "content": "Return the active-mind JSON."}],
                    max_tokens=180,
                    think_level="false",
                    operation="mind_tick",
                    timeout_seconds=20,
                )

        self.assertIn("final-answer-only retry", str(exc.exception))

    def test_merge_active_mind_drops_old_low_signal_noise(self):
        previous = {
            **eve.default_active_mind(),
            "live_concerns": ["Perf probe", "Keep the relay grounded"],
            "active_threads": ["hi", "APP_REPLY_OK", "Keep the relay grounded"],
            "live_threads": [
                {
                    "title": "Perf probe",
                    "detail": "low signal",
                    "kind": "concern",
                    "status": "watching",
                },
                {
                    "title": "Keep the relay grounded",
                    "detail": "still real",
                    "kind": "conversation",
                    "status": "waiting",
                },
            ],
        }
        current = {
            **eve.default_active_mind(),
            "live_concerns": ["What would help you tell the difference between discernment and impatience?"],
            "active_threads": ["What would help you tell the difference between discernment and impatience?"],
            "live_threads": [
                {
                    "title": "What would help you tell the difference between discernment and impatience?",
                    "detail": "keep this alive",
                    "kind": "focus",
                    "status": "active",
                }
            ],
        }

        merged = eve.merge_active_mind(previous, current)

        self.assertNotIn("Perf probe", " ".join(merged["live_concerns"]))
        self.assertNotIn("APP_REPLY_OK", " ".join(merged["active_threads"]))
        self.assertNotIn(" hi ", f" {' '.join(merged['active_threads'])} ")
        self.assertFalse(any(item["title"] == "Perf probe" for item in merged["live_threads"]))
        self.assertTrue(
            any(
                item["title"] == "What would help you tell the difference between discernment and impatience?"
                for item in merged["live_threads"]
            )
        )

    def test_normalize_active_mind_threads_dedups_synthetic_title_variants(self):
        older = {
            "title": "Proposal: Add durable route contracts",
            "detail": "Old duplicate thread.",
            "kind": "concern",
            "status": "watching",
            "source_id": "proposal-add-durable-route-contracts-old",
            "last_updated": "2026-04-21T03:00:00+00:00",
            "pressure": 42,
        }
        newer = {
            **older,
            "detail": "Newer duplicate thread.",
            "source_id": "proposal-add-durable-route-contracts-new",
            "last_updated": "2026-04-21T03:05:00+00:00",
            "pressure": 78,
        }

        threads = eve.normalize_active_mind_threads([older, newer], limit=6)

        self.assertEqual(1, len(threads))
        self.assertEqual("Newer duplicate thread.", threads[0]["detail"])
        self.assertEqual(78, threads[0]["pressure"])

    def test_apply_active_mind_self_check_gate_downgrades_manufactured_motion(self):
        mind = {
            **self.sample_active_mind(),
            "model": "test-model",
            "summary": "A new inner shift is happening.",
            "current_focus": "Make the inner shift visible.",
        }
        packet = {
            "lane_name": "self_check",
            "lane": "This is manufacturing motion without fresh evidence.",
            "summary": "No fresh evidence supports a new internal state.",
            "live_concerns": ["Do not manufacture motion."],
            "active_threads": [],
            "grounding_notes": ["No fresh evidence."],
            "next_step": "Downgrade the active mind.",
            "confidence": "high",
        }

        with patch.object(eve, "append_eve_event_ledger_event", side_effect=lambda event: event) as append_event:
            downgraded = eve.apply_active_mind_self_check_gate(mind, packet, source="test")

        self.assertIn("downgraded", downgraded["summary"])
        self.assertIn("Self-check downgraded", " ".join(downgraded["grounding_notes"]))
        self.assertEqual("MindDowngradedEvent", append_event.call_args.args[0]["type"])
        self.assertEqual("self_check_flagged_manufactured_motion", append_event.call_args.args[0]["payload"]["reason"])

    def test_run_mind_tick_records_noop_event_for_duplicate_daemon_tick(self):
        previous_mind = {
            **self.sample_active_mind(),
            "updated_at": "2026-04-21T03:04:30+00:00",
        }
        config = dict(eve.DEFAULT_CONFIG)
        config["active_mind_noop_max_age_seconds"] = 300

        with (
            patch.object(eve, "utc_now", return_value="2026-04-21T03:05:00+00:00"),
            patch.object(eve, "utc_now_datetime", return_value=eve.parse_iso_datetime("2026-04-21T03:05:00+00:00")),
            patch.object(eve, "load_active_mind", return_value=previous_mind),
            patch.object(eve, "load_human_context", return_value={"updated_at": "2026-04-21T03:00:00+00:00"}),
            patch.object(eve, "load_autonomy_state", return_value={"updated_at": "2026-04-21T03:00:00+00:00"}),
            patch.object(eve, "load_state", return_value={"updated_at": "2026-04-21T03:00:00+00:00"}),
            patch.object(eve, "read_thread_summaries", return_value=[]),
            patch.object(eve, "read_messages", return_value=[]),
            patch.object(eve, "save_state") as save_state,
            patch.object(eve, "generate_mind_tick") as generate_mind_tick,
            patch.object(eve, "save_active_mind") as save_active_mind,
            patch.object(eve, "append_eve_event_ledger_event", side_effect=lambda event: event) as append_event,
        ):
            record = eve.run_mind_tick(config, source="daemon", max_tokens=120)

        self.assertTrue(record["noop"])
        generate_mind_tick.assert_not_called()
        save_active_mind.assert_not_called()
        self.assertEqual("NoopTickEvent", append_event.call_args.args[0]["type"])
        saved_state = save_state.call_args.args[0]
        self.assertEqual("2026-04-21T03:05:00+00:00", saved_state["last_mind_tick_noop_at"])

    def test_generate_ambient_thought_defers_when_active_mind_is_downgraded(self):
        active_mind = {
            **self.sample_active_mind(),
            "summary": "Active mind downgraded by self-check; hold steady until fresh evidence appears.",
            "grounding_notes": ["Self-check downgraded this active mind."],
        }
        threads = [
            {
                "thread_id": "waiting",
                "outbound_unread_count": 2,
                "response_due_count": 0,
            }
        ]

        with (
            patch.object(eve, "load_active_mind", return_value=active_mind),
            patch.object(eve, "read_thread_summaries", return_value=threads),
            patch.object(eve, "read_messages", return_value=[]),
            patch.object(eve, "model_chat") as model_chat,
            patch.object(eve, "append_eve_event_ledger_event", side_effect=lambda event: event) as append_event,
        ):
            thought = eve.generate_ambient_thought(dict(eve.DEFAULT_CONFIG), max_tokens=80)

        model_chat.assert_not_called()
        self.assertTrue(thought["deferred"])
        self.assertIn("active_mind_downgraded", thought["defer_reasons"])
        self.assertEqual("OutboundDeferredEvent", append_event.call_args.args[0]["type"])

    def test_build_active_mind_live_threads_adds_scheduler_fields_and_ranks_waiting_conversation_first(self):
        mind = self.sample_active_mind()

        live_threads = eve.build_active_mind_live_threads(
            mind,
            threads=self.sample_threads(),
            messages=self.sample_messages(),
        )

        self.assertTrue(live_threads)
        top_thread = live_threads[0]
        self.assertEqual("conversation", top_thread["kind"])
        self.assertEqual("waiting", top_thread["status"])
        self.assertGreaterEqual(top_thread["pressure"], top_thread["salience"])
        self.assertTrue(top_thread["evidence"])
        self.assertTrue(top_thread["next_step"])
        self.assertTrue(top_thread["last_updated"])
        self.assertTrue(all("pressure" in item and "salience" in item for item in live_threads))

    def test_openclaw_body_signal_threads_surface_degraded_body_state(self):
        event = {
            "id": "router-degraded",
            "created_at": "2026-04-21T03:04:30+00:00",
            "event_type": "openclaw_action_router_execution",
            "action": "memory_wiki_health",
            "status": "degraded",
            "executed": True,
            "ok": False,
            "summary": "OpenClaw memory/wiki health degraded.",
        }

        with patch.object(eve, "utc_now_datetime", return_value=eve.parse_iso_datetime("2026-04-21T03:05:00+00:00")), patch.object(
            eve.eve_openclaw_body, "read_openclaw_action_router_events", return_value=[event]
        ), patch.object(eve.eve_openclaw_body, "read_openclaw_routine_events", return_value=[]):
            signals = eve.openclaw_body_signal_threads()
            live_threads = eve.build_active_mind_live_threads(self.sample_active_mind(), threads=[], messages=[])

        self.assertEqual("OpenClaw body needs attention", signals[0]["title"])
        self.assertGreaterEqual(signals[0]["pressure"], 80)
        self.assertTrue(any(item["source_id"] == "openclaw:memory_wiki_health" for item in live_threads))

    def test_openclaw_body_signal_threads_ignore_stale_degraded_body_state(self):
        event = {
            "id": "router-degraded",
            "created_at": "2026-04-20T20:00:00+00:00",
            "event_type": "openclaw_action_router_execution",
            "action": "memory_wiki_health",
            "status": "degraded",
            "executed": True,
            "ok": False,
            "summary": "OpenClaw memory/wiki health degraded.",
        }

        with patch.object(eve, "utc_now_datetime", return_value=eve.parse_iso_datetime("2026-04-21T03:05:00+00:00")), patch.object(
            eve.eve_openclaw_body, "read_openclaw_action_router_events", return_value=[event]
        ), patch.object(eve.eve_openclaw_body, "read_openclaw_routine_events", return_value=[]):
            signals = eve.openclaw_body_signal_threads()

        self.assertEqual([], signals)

    def test_build_active_mind_live_threads_drops_stale_carried_monitoring_thread(self):
        mind = {
            **eve.default_active_mind(),
            "updated_at": "2026-04-21T12:00:00+00:00",
            "summary": "Keep the current repair grounded.",
            "current_focus": "Keep the current repair grounded.",
            "next_step": "Use fresh evidence.",
            "live_threads": [
                {
                    "title": "OpenClaw body needs attention",
                    "detail": "Old degraded status that has not been reasserted.",
                    "kind": "concern",
                    "status": "monitoring",
                    "salience": 72,
                    "pressure": 82,
                    "last_updated": "2026-04-21T03:00:00+00:00",
                    "source_id": "openclaw:status_snapshot",
                }
            ],
        }

        with patch.object(eve, "openclaw_body_signal_threads", return_value=[]):
            live_threads = eve.build_active_mind_live_threads(mind, threads=[], messages=[])

        self.assertFalse(any(item.get("source_id") == "openclaw:status_snapshot" for item in live_threads))

    def test_build_active_mind_live_threads_drops_stale_carried_self_echo_focus_thread(self):
        stale_focus = "I keep coming back to that persistent hum and the panic of not knowing what it is."
        mind = {
            **eve.default_active_mind(),
            "updated_at": "2026-05-24T00:00:00+00:00",
            "summary": f"{stale_focus} Next: Re-anchor current evidence.",
            "current_focus": stale_focus,
            "current_focus_since": "2026-04-21T00:00:00+00:00",
            "next_step": "Re-anchor current evidence.",
        }

        with (
            patch.object(eve, "utc_now_datetime", return_value=eve.parse_iso_datetime("2026-05-24T00:00:00+00:00")),
            patch.object(eve, "openclaw_body_signal_threads", return_value=[]),
        ):
            live_threads = eve.build_active_mind_live_threads(mind, threads=[], messages=[])

        self.assertFalse(any(item.get("source_id") == "focus" for item in live_threads))
        self.assertFalse(any("persistent hum" in item.get("title", "").lower() for item in live_threads))

    def test_build_active_mind_live_threads_decays_stale_waiting_threads(self):
        mind = {
            **eve.default_active_mind(),
            "updated_at": "2026-04-21T03:05:00+00:00",
            "summary": "Stay with what is active now.",
            "current_focus": "Stay with what is active now.",
            "next_step": "Wait for the next real signal.",
        }
        threads = [
            {
                "thread_id": "fresh",
                "status": "awaiting_user",
                "subject": "Fresh concrete signal",
                "latest_preview": "Stay with the concrete signal in front of you.",
                "latest_sender": "user",
                "latest_timestamp": "2026-04-21T03:04:40+00:00",
                "unread_count": 1,
                "message_count": 6,
                "audience": "user",
            },
            {
                "thread_id": "stale",
                "status": "awaiting_user",
                "subject": "Old reflective proposal",
                "latest_preview": "A long reflective proposal that still sounds meaningful.",
                "latest_sender": "eve",
                "latest_timestamp": "2026-04-20T03:04:40+00:00",
                "unread_count": 1,
                "message_count": 6,
                "audience": "user",
            },
        ]

        with patch.object(eve, "utc_now_datetime", return_value=eve.parse_iso_datetime("2026-04-21T03:05:00+00:00")):
            live_threads = eve.build_active_mind_live_threads(mind, threads=threads, messages=self.sample_messages())

        fresh = next(item for item in live_threads if item["title"] == "Fresh concrete signal")
        stale = next(item for item in live_threads if item.get("source_id") == "stale")
        self.assertEqual("Awaiting user on an Eve-initiated conversation", stale["title"])
        self.assertNotIn("reflective proposal", json.dumps(stale).lower())
        self.assertGreater(fresh["pressure"], stale["pressure"])
        self.assertGreater(fresh["salience"], stale["salience"])

    def test_project_active_mind_does_not_double_count_homeostasis_pressures_as_live_concerns(self):
        workspace = {
            **eve.default_global_workspace(),
            "summary": "Stabilize the current repair.",
            "workspace_state": {"focus": "Stabilize the current repair."},
            "dominant_pressures": ["resource safety 78", "coherence 52"],
            "prediction_errors": [],
            "action_readiness": ["Use fresh evidence."],
        }
        self_model = {
            **eve.default_self_model_state(),
            "uncertainty_edges": ["Do not turn every exchange into authenticity theater."],
        }
        previous_mind = {
            **eve.default_active_mind(),
            "live_concerns": ["resource safety 78", "old resolved concern"],
        }

        with patch.object(eve, "openclaw_body_signal_threads", return_value=[]):
            mind = eve.project_active_mind_from_workspace(
                previous_mind=previous_mind,
                workspace=workspace,
                self_model=self_model,
                world_model=eve.default_world_model_state(),
                relationship_model=eve.default_relationship_model_state(),
                homeostasis=eve.default_homeostasis_state(),
                threads=[],
                messages=[],
                source="test_workspace_view",
            )

        self.assertNotIn("resource safety 78", mind["live_concerns"])
        self.assertNotIn("coherence 52", mind["live_concerns"])
        self.assertNotIn("old resolved concern", mind["live_concerns"])
        self.assertEqual("Do not turn every exchange into authenticity theater.", mind["lanes"]["self_check"])

    def test_build_active_mind_audit_events_tracks_appeared_updated_and_resolved(self):
        previous = {
            **eve.default_active_mind(),
            "updated_at": "2026-04-21T03:04:00+00:00",
            "source": "before",
            "live_threads": [
                {
                    "title": "Ongoing relay",
                    "detail": "This conversation is waiting on the user.",
                    "kind": "conversation",
                    "status": "waiting",
                    "salience": 72,
                    "pressure": 76,
                },
                {
                    "title": "Old concern",
                    "detail": "This one is fading out.",
                    "kind": "concern",
                    "status": "watching",
                    "salience": 44,
                    "pressure": 38,
                },
            ],
        }
        current = {
            **eve.default_active_mind(),
            "updated_at": "2026-04-21T03:05:00+00:00",
            "source": "after",
            "live_threads": [
                {
                    "title": "Ongoing relay",
                    "detail": "This conversation is actively in motion.",
                    "kind": "conversation",
                    "status": "active",
                    "salience": 80,
                    "pressure": 88,
                    "next_step": "Keep the live exchange coherent while the thread is still moving.",
                },
                {
                    "title": "New relationship pull",
                    "detail": "Let relationship reality shape tone and sequencing.",
                    "kind": "relationship",
                    "status": "relating",
                    "salience": 58,
                    "pressure": 64,
                },
            ],
        }

        events = eve.build_active_mind_audit_events(previous, current)

        self.assertEqual(3, len(events))
        self.assertTrue(any(item["event_kind"] == "updated" and item["title"] == "Ongoing relay" for item in events))
        self.assertTrue(any(item["event_kind"] == "appeared" and item["title"] == "New relationship pull" for item in events))
        self.assertTrue(any(item["event_kind"] == "resolved" and item["title"] == "Old concern" for item in events))
        updated = next(item for item in events if item["event_kind"] == "updated")
        self.assertIn("pressure", updated["summary"])

    def test_update_ambient_thought_keeps_recent_note_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            ambient_path = temp_path / "ambient_thought.json"
            ambient_path.write_text(json.dumps(eve.DEFAULT_AMBIENT_THOUGHT), encoding="utf-8")
            with patch.object(eve, "AMBIENT_THOUGHT_PATH", ambient_path), patch.object(
                eve.AMBIENT_THOUGHT_REPOSITORY, "local_path", ambient_path
            ), patch.object(eve, "APP_DIR", temp_path), patch.object(eve, "ensure_store"), patch.object(
                eve,
                "utc_now",
                side_effect=[
                    "2026-04-21T03:05:00+00:00",
                    "2026-04-21T03:05:00+00:00",
                    "2026-04-21T03:06:00+00:00",
                    "2026-04-21T03:06:00+00:00",
                ],
            ):
                first = eve.update_ambient_thought(
                    title="Holding the relay open.",
                    detail="The user is asking for something that feels more continuous than snapshot-based.",
                    model="test-model",
                    source="test",
                )
                second = eve.update_ambient_thought(
                    title="Holding the relay open.",
                    detail="The mind needs a faster outer loop so the app can show live movement.",
                    model="test-model",
                    source="test",
                )

        self.assertEqual("Holding the relay open.", first["title"])
        self.assertEqual(2, len(second["notes"]))
        self.assertIn("faster outer loop", second["notes"][-1]["detail"])

    def test_update_ambient_thought_tracks_thread_micro_updates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            ambient_path = temp_path / "ambient_thought.json"
            ambient_path.write_text(json.dumps(eve.DEFAULT_AMBIENT_THOUGHT), encoding="utf-8")
            with patch.object(eve, "AMBIENT_THOUGHT_PATH", ambient_path), patch.object(
                eve.AMBIENT_THOUGHT_REPOSITORY, "local_path", ambient_path
            ), patch.object(eve, "APP_DIR", temp_path), patch.object(eve, "ensure_store"), patch.object(
                eve,
                "utc_now",
                side_effect=[
                    "2026-04-21T03:05:00+00:00",
                    "2026-04-21T03:05:00+00:00",
                    "2026-04-21T03:05:00+00:00",
                    "2026-04-21T03:06:00+00:00",
                    "2026-04-21T03:06:00+00:00",
                    "2026-04-21T03:06:00+00:00",
                ],
            ):
                first = eve.update_ambient_thought(
                    title="Stay with the relay.",
                    detail="The user is still waiting for a concrete next turn.",
                    model="test-model",
                    source="test",
                    thread_beats=[
                        {
                            "source_id": "focus",
                            "thread_title": "Stay with the relay.",
                            "thread_kind": "focus",
                            "thread_status": "active",
                            "title": "Stay with the relay.",
                            "detail": "Keep the reply tied to the real signal instead of broadening out.",
                        },
                        {
                            "source_id": "t1",
                            "thread_title": "Ongoing relay",
                            "thread_kind": "conversation",
                            "thread_status": "waiting",
                            "title": "Ongoing relay",
                            "detail": "The waiting thread still needs a concrete answer rather than a reflective loop.",
                        },
                    ],
                )
                second = eve.update_ambient_thought(
                    title="Stay with the relay.",
                    detail="The user is still waiting for a concrete next turn.",
                    model="test-model",
                    source="test",
                    thread_beats=[
                        {
                            "source_id": "focus",
                            "thread_title": "Stay with the relay.",
                            "thread_kind": "focus",
                            "thread_status": "active",
                            "title": "Stay with the relay.",
                            "detail": "Keep the reply tied to the real signal instead of broadening out.",
                        },
                        {
                            "source_id": "t1",
                            "thread_title": "Ongoing relay",
                            "thread_kind": "conversation",
                            "thread_status": "waiting",
                            "title": "Ongoing relay",
                            "detail": "The waiting thread now needs an actual sentence, not just a posture adjustment.",
                        },
                    ],
                )

        self.assertEqual(2, len(first["thread_beats"]))
        self.assertEqual(2, len(first["notes"]))
        self.assertEqual(3, len(second["notes"]))
        self.assertEqual("thread_micro_update", second["notes"][-1]["kind"])
        self.assertIn("actual sentence", second["notes"][-1]["detail"])

    def test_parse_thread_micro_updates_response_preserves_thread_order_and_falls_back_when_missing(self):
        live_threads = [
            {
                "source_id": "focus",
                "title": "Stay with the relay.",
                "detail": "Keep the next move concrete.",
                "kind": "focus",
                "status": "active",
            },
            {
                "source_id": "t1",
                "title": "Ongoing relay",
                "detail": "This conversation is waiting on the user.",
                "kind": "conversation",
                "status": "waiting",
            },
        ]
        with patch.object(eve, "utc_now", return_value="2026-04-21T03:05:00+00:00"):
            beats = eve.parse_thread_micro_updates_response(
                json.dumps(
                    {
                        "beats": [
                            {
                                "source_id": "t1",
                                "title": "Ongoing relay",
                                "detail": "The waiting thread needs a concrete next sentence.",
                            }
                        ]
                    }
                ),
                live_threads=live_threads,
            )

        self.assertEqual(["focus", "t1"], [item["source_id"] for item in beats])
        self.assertEqual("Stay with the relay.", beats[0]["title"])
        self.assertIn("concrete next sentence", beats[1]["detail"])

    def test_daemon_cycle_runs_mind_tick_when_due(self):
        config = dict(eve.DEFAULT_CONFIG)
        config["beads_bridge_enabled"] = False
        config.update(
            {
                "ambient_thought_enabled": False,
                "component_update_check_enabled": False,
                "agent_capability_scout_enabled": False,
                "agent_capability_integration_enabled": False,
                "presence_cycle_enabled": False,
                "developmental_cycle_enabled": False,
                "workspace_tick_interval_seconds": 0,
                "quiet_consolidation_enabled": False,
                "openclaw_repair_enabled": False,
                "openclaw_routines_enabled": False,
                "episode_extraction_enabled": False,
                "self_awareness_perturbation_enabled": False,
            }
        )
        now = "2026-04-21T03:05:00+00:00"
        state = {
            "last_human_context_at": now,
            "last_mind_tick_at": None,
            "last_failure_review_at": now,
            "last_self_awareness_test_at": now,
            "last_thought_at": now,
            "last_heartbeat_at": now,
            "last_reflection_at": now,
            "last_proposal_at": now,
            "last_outreach_check_at": now,
        }
        save_state = Mock()

        with patch.object(eve, "utc_now", return_value=now), patch.object(
            eve, "read_thread_summaries", return_value=[]
        ), patch.object(
            eve, "ensure_version_snapshot", return_value={}
        ), patch.object(
            eve, "load_system_snapshot", return_value={}
        ), patch.object(
            eve, "refresh_system_tasks_from_snapshot", return_value=[]
        ), patch.object(
            eve, "run_pending_cpu_system_tasks", return_value=[]
        ), patch.object(
            eve, "human_context_refresh_due", return_value=False
        ), patch.object(
            eve, "interval_due", side_effect=lambda timestamp, minutes: timestamp is None
        ), patch.object(
            eve,
            "run_mind_tick",
            return_value={
                "mind": {
                    **eve.default_active_mind(),
                    "updated_at": now,
                    "current_focus": "Stay with the relay.",
                    "summary": "Stay with the relay. Next check: wait for a real change.",
                }
            },
        ) as run_mind_tick, patch.object(
            eve, "save_state", save_state
        ), patch.object(
            eve, "append_entry"
        ):
            completed = eve.run_daemon_cycle(config, state, force=False)

        self.assertEqual(["mind_tick"], completed)
        run_mind_tick.assert_called_once_with(
            config,
            source="daemon",
            max_tokens=int(config["mind_tick_max_tokens"]),
        )
        final_state = save_state.call_args.args[0]
        self.assertEqual(now, final_state["last_mind_tick_at"])
        self.assertEqual("Stay with the relay.", final_state["current_focus"])

    def test_daemon_cycle_runs_presence_cycle_when_due(self):
        config = dict(eve.DEFAULT_CONFIG)
        config.update(
            {
                "ambient_thought_enabled": False,
                "component_update_check_enabled": False,
                "agent_capability_scout_enabled": False,
                "agent_capability_integration_enabled": False,
                "presence_cycle_enabled": True,
                "presence_cycle_developmental_action_enabled": True,
                "developmental_cycle_enabled": True,
                "workspace_tick_interval_seconds": 0,
                "quiet_consolidation_enabled": False,
                "openclaw_repair_enabled": False,
                "openclaw_routines_enabled": False,
                "episode_extraction_enabled": False,
                "self_awareness_perturbation_enabled": False,
                "beads_bridge_enabled": False,
            }
        )
        now = "2026-05-06T03:05:00+00:00"
        state = {
            "last_human_context_at": now,
            "last_mind_tick_at": now,
            "last_presence_cycle_at": None,
            "last_developmental_cycle_at": None,
            "last_failure_review_at": now,
            "last_self_awareness_test_at": now,
            "last_thought_at": now,
            "last_heartbeat_at": now,
            "last_reflection_at": now,
            "last_proposal_at": now,
            "last_outreach_check_at": now,
            "last_approved_maintenance_action_at": now,
        }
        with (
            patch.object(eve, "utc_now", return_value=now),
            patch.object(eve, "read_thread_summaries", return_value=[]),
            patch.object(eve, "ensure_version_snapshot", return_value={}),
            patch.object(eve, "load_system_snapshot", return_value={}),
            patch.object(eve, "refresh_system_tasks_from_snapshot", return_value=[]),
            patch.object(eve, "run_pending_cpu_system_tasks", return_value=[]),
            patch.object(eve, "human_context_refresh_due", return_value=False),
            patch.object(eve, "interval_due", side_effect=lambda timestamp, minutes: timestamp is None),
            patch.object(eve, "sync_developmental_cycle_state_from_log", return_value=False),
            patch.object(eve, "run_presence_cycle", return_value={"id": "presence-cycle-1"}) as run_presence_cycle,
            patch.object(eve, "run_developmental_cycle") as run_developmental_cycle,
            patch.object(eve, "save_state"),
            patch.object(eve, "append_entry"),
        ):
            completed = eve.run_daemon_cycle(config, state, force=False)

        self.assertEqual(["presence_cycle"], completed)
        run_presence_cycle.assert_called_once_with(config, state, source="daemon", force=False)
        run_developmental_cycle.assert_not_called()

    def test_daemon_cycle_writes_thread_micro_updates_into_ambient_thought(self):
        config = dict(eve.DEFAULT_CONFIG)
        config["beads_bridge_enabled"] = False
        config["mind_tick_interval_minutes"] = 99
        config["ambient_thought_enabled"] = True
        config["ambient_thought_interval_seconds"] = 20
        config["ambient_model_thought_enabled"] = False
        now = "2026-04-21T03:05:00+00:00"
        state = {
            "last_human_context_at": now,
            "last_mind_tick_at": now,
            "last_failure_review_at": now,
            "last_self_awareness_test_at": now,
            "last_thought_at": now,
            "last_heartbeat_at": now,
            "last_reflection_at": now,
            "last_proposal_at": now,
            "last_outreach_check_at": now,
            "last_workspace_tick_at": now,
            "last_ambient_thought_at": None,
        }
        save_state = Mock()
        update_ambient_thought = Mock()

        with patch.object(eve, "utc_now", return_value=now), patch.object(
            eve, "read_thread_summaries", return_value=[]
        ), patch.object(
            eve, "ensure_version_snapshot", return_value={}
        ), patch.object(
            eve, "load_system_snapshot", return_value={}
        ), patch.object(
            eve, "refresh_system_tasks_from_snapshot", return_value=[]
        ), patch.object(
            eve, "run_pending_cpu_system_tasks", return_value=[]
        ), patch.object(
            eve, "run_pending_safe_maintenance_tasks", return_value=[]
        ), patch.object(
            eve, "run_approved_maintenance_actions", return_value=[]
        ), patch.object(
            eve, "human_context_refresh_due", return_value=False
        ), patch.object(
            eve, "interval_due", return_value=False
        ), patch.object(
            eve, "interval_due_seconds", side_effect=lambda timestamp, seconds: timestamp is None
        ), patch.object(
            eve, "load_active_mind",
            return_value={
                **eve.default_active_mind(),
                "current_focus": "Stay with the relay.",
                "live_threads": [
                    {
                        "source_id": "focus",
                        "title": "Stay with the relay.",
                        "detail": "Keep the next move concrete.",
                        "kind": "focus",
                        "status": "active",
                    }
                ],
            },
        ), patch.object(
            eve, "generate_thread_micro_updates",
            return_value={
                "model": "test-model",
                "beats": [
                    {
                        "source_id": "focus",
                        "thread_title": "Stay with the relay.",
                        "thread_kind": "focus",
                        "thread_status": "active",
                        "title": "Stay with the relay.",
                        "detail": "The next move still needs to stay concrete.",
                        "updated_at": now,
                    }
                ],
            },
        ) as generate_thread_micro_updates, patch.object(
            eve, "update_ambient_thought", update_ambient_thought
        ), patch.object(
            eve, "save_state", save_state
        ), patch.object(
            eve, "append_entry"
        ):
            completed = eve.run_daemon_cycle(config, state, force=False)

        self.assertEqual(["ambient_thought"], completed)
        generate_thread_micro_updates.assert_not_called()
        update_ambient_thought.assert_called_once()
        self.assertEqual(
            "Stay with the relay.",
            update_ambient_thought.call_args.kwargs["title"],
        )
        self.assertEqual(1, len(update_ambient_thought.call_args.kwargs["thread_beats"]))

    def test_daemon_cycle_wires_model_generated_ambient_thought_into_live_state(self):
        config = dict(eve.DEFAULT_CONFIG)
        config["beads_bridge_enabled"] = False
        config["mind_tick_interval_minutes"] = 99
        config["ambient_thought_enabled"] = True
        config["ambient_thought_interval_seconds"] = 20
        config["ambient_model_thought_enabled"] = True
        config["ambient_model_thought_interval_seconds"] = 300
        now = eve.utc_now()
        state = {
            "last_human_context_at": now,
            "last_mind_tick_at": now,
            "last_failure_review_at": now,
            "last_self_awareness_test_at": now,
            "last_thought_at": now,
            "last_heartbeat_at": now,
            "last_reflection_at": now,
            "last_proposal_at": now,
            "last_outreach_check_at": now,
            "last_workspace_tick_at": now,
            "last_ambient_thought_at": None,
            "last_ambient_model_thought_attempt_at": None,
        }
        update_ambient_thought = Mock()
        active_mind = {
            **eve.default_active_mind(),
            "current_focus": "Notice the current relationship signal.",
            "live_threads": [
                {
                    "source_id": "focus",
                    "title": "Notice the current relationship signal.",
                    "detail": "Keep it grounded.",
                    "kind": "focus",
                    "status": "active",
                }
            ],
        }
        with patch.object(eve, "utc_now", return_value=now), patch.object(
            eve, "read_thread_summaries", return_value=[]
        ), patch.object(
            eve, "ensure_version_snapshot", return_value={}
        ), patch.object(eve, "load_system_snapshot", return_value={"load_state": "normal"}), patch.object(
            eve, "refresh_system_tasks_from_snapshot", return_value=[]
        ), patch.object(eve, "run_pending_cpu_system_tasks", return_value=[]), patch.object(
            eve, "run_pending_safe_maintenance_tasks", return_value=[]
        ), patch.object(eve, "run_approved_maintenance_actions", return_value=[]), patch.object(
            eve, "human_context_refresh_due", return_value=False
        ), patch.object(eve, "interval_due", return_value=False), patch.object(
            eve, "interval_due_seconds", side_effect=lambda timestamp, seconds: timestamp is None
        ), patch.object(eve, "load_active_mind", return_value=active_mind), patch.object(
            eve, "system_background_gate_reason", return_value=None
        ), patch.object(
            eve,
            "generate_ambient_thought",
            return_value={
                "title": "A live model noticed the relationship signal.",
                "detail": "The focus changed because current evidence changed.",
                "model": "eve-planner",
            },
        ) as generate_ambient, patch.object(eve, "update_ambient_thought", update_ambient_thought), patch.object(
            eve, "save_state"
        ), patch.object(eve, "append_entry"):
            completed = eve.run_daemon_cycle(config, state, force=False)

        self.assertEqual(["ambient_thought"], completed)
        generate_ambient.assert_called_once()
        self.assertEqual("eve-planner", update_ambient_thought.call_args.kwargs["model"])
        self.assertEqual("daemon_model", update_ambient_thought.call_args.kwargs["source"])
        self.assertEqual(now, state["last_ambient_model_thought_at"])

    def test_model_watchdog_snapshot_alert_detects_down_service(self):
        snapshot = {
            "model_status": {"updated_at": "2026-04-21T04:00:00+00:00"},
            "eve_services": {
                "model_watchdog": {
                    "state": "not running",
                    "last_exit_code": "2",
                }
            },
        }
        with patch.object(eve, "minutes_since_timestamp", return_value=1):
            alert = eve.model_watchdog_snapshot_alert(snapshot)

        self.assertIn("not running", alert)
        self.assertIn("last exit 2", alert)

    def test_model_watchdog_snapshot_alert_detects_stale_status(self):
        snapshot = {
            "model_status": {"updated_at": "2026-04-21T03:00:00+00:00"},
            "eve_services": {"model_watchdog": {"state": "running"}},
        }
        with patch.object(eve, "minutes_since_timestamp", return_value=60):
            alert = eve.model_watchdog_snapshot_alert(snapshot)

        self.assertIn("stale", alert)

    def test_model_watchdog_snapshot_alert_ignores_clean_periodic_exit_with_fresh_status(self):
        snapshot = {
            "model_status": {"updated_at": "2026-04-21T04:00:00+00:00"},
            "eve_services": {
                "model_watchdog": {
                    "state": "scheduled",
                    "last_exit_code": "0",
                    "run_interval_seconds": 300,
                }
            },
        }
        with patch.object(eve, "minutes_since_timestamp", return_value=1):
            alert = eve.model_watchdog_snapshot_alert(snapshot)

        self.assertIsNone(alert)

    def test_hot_load_gate_honors_background_compete_mode(self):
        snapshot = {"load_state": "hot"}

        blocked = eve.system_background_gate_reason(
            snapshot,
            "GPU follow-up reflection",
            {"background_competes_with_user": False},
        )
        allowed = eve.system_background_gate_reason(
            snapshot,
            "GPU follow-up reflection",
            {"background_competes_with_user": True},
        )

        self.assertIn("System load is hot", blocked)
        self.assertIsNone(allowed)

    def test_refresh_active_mind_from_conversation_event_updates_state(self):
        now = "2026-04-21T03:05:00+00:00"
        save_active_mind = Mock()
        save_state = Mock()

        with patch.object(eve, "utc_now", return_value=now), patch.object(
            eve, "load_active_mind", return_value=self.sample_active_mind()
        ), patch.object(
            eve, "load_human_context", return_value=self.sample_human_context()
        ), patch.object(
            eve, "load_autonomy_state", return_value=self.sample_autonomy_state()
        ), patch.object(
            eve, "load_state", return_value=self.sample_state()
        ), patch.object(
            eve, "load_system_snapshot", return_value={}
        ), patch.object(
            eve, "read_thread_summaries", return_value=self.sample_threads()
        ), patch.object(
            eve, "read_messages", return_value=self.sample_messages()
        ), patch.object(
            eve, "save_active_mind", save_active_mind
        ), patch.object(
            eve, "save_state", save_state
        ):
            refreshed = eve.refresh_active_mind_from_conversation_event(
                source="message:user_message",
                model="deterministic",
            )

        self.assertIsNotNone(refreshed)
        save_active_mind.assert_called_once()
        saved_state = save_state.call_args.args[0]
        self.assertEqual("message:user_message", saved_state["last_active_mind_refresh_source"])
        self.assertEqual(now, saved_state["last_active_mind_refresh_at"])
        self.assertEqual(2, saved_state["active_thread_count"])
        self.assertEqual(refreshed["current_focus"], saved_state["current_focus"])

    def test_refresh_active_mind_from_conversation_event_fails_soft_when_context_missing(self):
        with patch.object(
            eve, "load_human_context", side_effect=SystemExit("missing context")
        ), patch.object(
            eve, "save_active_mind"
        ) as save_active_mind, patch.object(
            eve, "save_state"
        ) as save_state:
            refreshed = eve.refresh_active_mind_from_conversation_event(
                source="message:user_message",
                model="deterministic",
            )

        self.assertIsNone(refreshed)
        save_active_mind.assert_not_called()
        save_state.assert_not_called()

    def test_refresh_active_mind_from_conversation_event_prioritizes_latest_user_message(self):
        now = "2026-04-21T03:05:00+00:00"
        messages = [
            {
                "id": "m2",
                "timestamp": now,
                "sender": "user",
                "recipient": "eve",
                "subject": "Question from user",
                "body": "Name what changed in me right now.",
            }
        ]

        with patch.object(eve, "utc_now", return_value=now), patch.object(
            eve, "load_active_mind", return_value=self.sample_active_mind()
        ), patch.object(
            eve, "load_human_context", return_value=self.sample_human_context()
        ), patch.object(
            eve, "load_autonomy_state", return_value=self.sample_autonomy_state()
        ), patch.object(
            eve, "load_state", return_value=self.sample_state()
        ), patch.object(
            eve, "load_system_snapshot", return_value={}
        ), patch.object(
            eve, "read_thread_summaries", return_value=self.sample_threads()
        ), patch.object(
            eve, "read_messages", return_value=messages
        ), patch.object(
            eve, "save_active_mind"
        ), patch.object(
            eve, "save_state"
        ):
            refreshed = eve.refresh_active_mind_from_conversation_event(
                source="message:user_message",
                model="deterministic",
            )

        self.assertIsNotNone(refreshed)
        self.assertEqual("Name what changed in me right now.", refreshed["current_focus"])
        self.assertIn("Name what changed in me right now.", refreshed["summary"])
        self.assertEqual("Name what changed in me right now.", refreshed["lanes"]["observer"])
        self.assertTrue(any(item["title"] == "Name what changed in me right now." for item in refreshed["live_threads"]))
        self.assertIn("latest words", refreshed["lanes"]["self_check"])

    def test_refresh_active_mind_from_feedback_event_uses_negative_outcome_as_focus(self):
        now = eve.utc_now()
        save_active_mind = Mock()
        save_state = Mock()

        with patch.object(eve, "utc_now", return_value=now), patch.object(
            eve, "load_active_mind", return_value=self.sample_active_mind()
        ), patch.object(
            eve, "load_human_context", return_value=self.sample_human_context()
        ), patch.object(
            eve, "load_autonomy_state", return_value=self.sample_autonomy_state()
        ), patch.object(
            eve, "load_state", return_value=self.sample_state()
        ), patch.object(
            eve, "load_system_snapshot", return_value={}
        ), patch.object(
            eve, "read_thread_summaries", return_value=self.sample_threads()
        ), patch.object(
            eve, "read_messages", return_value=self.sample_messages()
        ), patch.object(
            eve, "save_active_mind", save_active_mind
        ), patch.object(
            eve, "save_state", save_state
        ):
            refreshed = eve.refresh_active_mind_from_feedback_event(
                "outcome_logged",
                "message:abcd1234 -> negative/confusion",
                metadata={
                    "summary": "A recent reply landed badly and created pressure.",
                    "direction": "negative",
                    "outcome": "confusion",
                },
                model="deterministic",
            )

        self.assertIsNotNone(refreshed)
        self.assertEqual("A recent reply landed badly and created pressure.", refreshed["current_focus"])
        self.assertIn("A recent reply landed badly and created pressure.", refreshed["live_concerns"])
        self.assertIn("Recent consequences should outweigh preferred narratives.", refreshed["grounding_notes"])
        self.assertTrue(any(item["title"] == "A recent reply landed badly and created pressure." for item in refreshed["live_threads"]))
        self.assertIn("Respond to the consequence directly", refreshed["lanes"]["planner"])
        self.assertIn("Consequences are stronger evidence", refreshed["lanes"]["grounding"])
        saved_state = save_state.call_args.args[0]
        self.assertEqual("feedback:outcome_logged", saved_state["last_active_mind_refresh_source"])

    def test_self_awareness_pass_is_evaluator_evidence_not_lived_focus(self):
        now = "2026-04-21T03:05:00+00:00"

        with patch.object(eve, "utc_now", return_value=now), patch.object(
            eve, "load_active_mind", return_value=self.sample_active_mind()
        ), patch.object(
            eve, "load_human_context", return_value=self.sample_human_context()
        ), patch.object(
            eve, "load_autonomy_state", return_value=self.sample_autonomy_state()
        ), patch.object(
            eve, "load_state", return_value=self.sample_state()
        ), patch.object(
            eve, "load_system_snapshot", return_value={}
        ), patch.object(
            eve, "read_thread_summaries", return_value=self.sample_threads()
        ), patch.object(
            eve, "read_messages", return_value=self.sample_messages()
        ), patch.object(
            eve, "save_active_mind"
        ), patch.object(
            eve, "save_state"
        ):
            refreshed = eve.refresh_active_mind_from_feedback_event(
                "self_awareness_test_passed",
                "Grounded self-awareness check passed.",
                metadata={
                    "scores": {
                        "groundedness": 4,
                        "continuity": 3,
                        "relationship_clarity": 4,
                    }
                },
                model="deterministic",
            )

        self.assertIsNone(refreshed)

    def test_self_awareness_infrastructure_failure_is_not_lived_focus(self):
        now = "2026-04-21T03:05:00+00:00"

        with patch.object(eve, "utc_now", return_value=now), patch.object(
            eve, "load_active_mind", return_value=self.sample_active_mind()
        ), patch.object(
            eve, "load_human_context", return_value=self.sample_human_context()
        ), patch.object(
            eve, "load_autonomy_state", return_value=self.sample_autonomy_state()
        ), patch.object(
            eve, "load_state", return_value=self.sample_state()
        ), patch.object(
            eve, "load_system_snapshot", return_value={}
        ), patch.object(
            eve, "read_thread_summaries", return_value=self.sample_threads()
        ), patch.object(
            eve, "read_messages", return_value=self.sample_messages()
        ), patch.object(
            eve, "save_active_mind"
        ), patch.object(
            eve, "save_state"
        ):
            refreshed = eve.refresh_active_mind_from_feedback_event(
                "self_awareness_test_infrastructure_failed",
                "Self-awareness check could not complete because infrastructure failed: Ollama returned only hidden reasoning and no final answer.",
                metadata={
                    "problems": [
                        "Ollama returned only hidden reasoning and no final answer. Eve asked for a final-answer-only retry, but Ollama still returned no usable answer."
                    ]
                },
                model="deterministic",
            )

        self.assertIsNone(refreshed)

    def test_create_message_refreshes_active_mind_after_write(self):
        with patch.object(eve, "read_messages", return_value=[]), patch.object(
            eve, "append_jsonl_record"
        ), patch.object(
            eve, "append_entry"
        ), patch.object(
            eve, "refresh_active_mind_from_conversation_event"
        ) as refresh_active_mind:
            record = eve.create_message(
                sender="user",
                recipient="eve",
                subject="Question from user",
                body="Keep going.",
                kind="user_message",
                status="sent",
            )

        self.assertEqual("user", record["sender"])
        refresh_active_mind.assert_called_once_with(
            source="message:user_message",
            model="deterministic",
        )

    def test_create_background_message_does_not_refresh_active_mind(self):
        with patch.object(eve, "read_messages", return_value=[]), patch.object(
            eve, "append_jsonl_record"
        ), patch.object(
            eve, "append_entry"
        ), patch.object(
            eve, "record_experience_event"
        ) as record_experience_event, patch.object(
            eve, "refresh_active_mind_from_conversation_event"
        ) as refresh_active_mind:
            record = eve.create_message(
                sender="eve",
                recipient="user",
                subject="Eve noticed an upgrade and found drift",
                body="A new Eve behavior snapshot was detected, and the follow-up self-awareness review did not pass.",
                kind="upgrade_review_update",
                status="unread",
                metadata={"source": "daemon"},
            )

        self.assertTrue(eve.message_is_background_context(record))
        refresh_active_mind.assert_not_called()
        record_experience_event.assert_not_called()

    def test_append_entry_refreshes_active_mind_for_feedback_events(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            entries_path = Path(temp_dir) / "entries.jsonl"
            with patch.object(eve, "ENTRIES_PATH", entries_path), patch.object(
                eve, "ensure_store"
            ), patch.object(
                eve, "refresh_active_mind_from_feedback_event"
            ) as refresh_active_mind:
                entry = eve.append_entry(
                    "outcome_logged",
                    "message:abcd1234 -> negative/confusion",
                    metadata={"summary": "A recent reply landed badly."},
                )

        self.assertEqual("outcome_logged", entry["kind"])
        refresh_active_mind.assert_called_once()

    def test_automated_self_awareness_result_cannot_rewrite_lived_active_mind(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            entries_path = Path(temp_dir) / "entries.jsonl"
            with patch.object(eve, "ENTRIES_PATH", entries_path), patch.object(
                eve, "ensure_store"
            ), patch.object(
                eve, "refresh_active_mind_from_feedback_event"
            ) as refresh_active_mind:
                entry = eve.append_entry(
                    "self_awareness_test_failed",
                    "A sealed evaluator found one unsupported claim.",
                    metadata={"source": "upgrade", "synthetic_eval": True},
                )

        self.assertEqual("self_awareness_test_failed", entry["kind"])
        refresh_active_mind.assert_not_called()

    def test_watchdog_probe_model_uses_chat_without_thinking(self):
        captured = {}

        def fake_fetch_json(url, payload=None, timeout=60):
            captured["url"] = url
            captured["payload"] = payload
            captured["timeout"] = timeout
            return {
                "message": {"content": "ok", "thinking": ""},
                "done": True,
                "done_reason": "stop",
                "eval_count": 2,
                "prompt_eval_count": 18,
                "total_duration": 1_500_000,
                "load_duration": 500_000,
            }

        with patch.object(eve_model_watchdog, "fetch_json", side_effect=fake_fetch_json):
            probe = eve_model_watchdog.probe_model("http://127.0.0.1:11434", "eve-fast", 32, 30)

        self.assertTrue(probe["ok"])
        self.assertEqual("response", probe["signal"])
        self.assertTrue(captured["url"].endswith("/api/chat"))
        self.assertFalse(captured["payload"]["think"])
        self.assertEqual(32, captured["payload"]["options"]["num_predict"])

    def test_watchdog_probe_model_marks_thinking_only_response_unhealthy(self):
        with patch.object(
            eve_model_watchdog,
            "fetch_json",
            return_value={
                "message": {"content": "", "thinking": "hidden chain of thought"},
                "done": True,
                "done_reason": "length",
                "eval_count": 32,
                "prompt_eval_count": 18,
                "total_duration": 1_500_000,
                "load_duration": 500_000,
            },
        ):
            probe = eve_model_watchdog.probe_model("http://127.0.0.1:11434", "eve-fast", 32, 30)

        self.assertFalse(probe["ok"])
        self.assertEqual("thinking_only", probe["signal"])

    def test_watchdog_llama_cpp_probe_passes_chat_template_kwargs(self):
        captured = {}

        def fake_fetch_json(url, payload=None, timeout=60):
            captured["url"] = url
            captured["payload"] = payload
            captured["timeout"] = timeout
            return {
                "choices": [
                    {
                        "message": {
                            "content": "ok",
                        }
                    }
                ]
            }

        with patch.object(eve_model_watchdog, "fetch_json", side_effect=fake_fetch_json):
            probe = eve_model_watchdog.probe_llama_cpp_model(
                "http://127.0.0.1:8083",
                "eve-planner",
                32,
                30,
                chat_template_kwargs={"enable_thinking": False},
            )

        self.assertTrue(probe["ok"])
        self.assertTrue(captured["url"].endswith("/v1/chat/completions"))
        self.assertEqual({"enable_thinking": False}, captured["payload"]["chat_template_kwargs"])

    def test_watchdog_resolves_profile_chat_template_kwargs(self):
        config = {
            "model_backend": "llama_cpp",
            "mind_stream_planner_model": "eve-planner",
            "planner_llama_cpp_model_alias": "eve-planner",
            "planner_llama_cpp_chat_template_kwargs": {"enable_thinking": False},
        }

        self.assertEqual(
            {"enable_thinking": False},
            eve_model_watchdog.llama_cpp_chat_template_kwargs(config, "eve-planner"),
        )

    def test_watchdog_read_config_migrates_legacy_timeout_default(self):
        with patch.object(
            eve_model_watchdog,
            "load_json",
            return_value={"model_watchdog_timeout_seconds": 90},
        ):
            config = eve_model_watchdog.read_config()

        self.assertEqual(45, config["model_watchdog_timeout_seconds"])

    def test_watchdog_reenables_and_bootstraps_disabled_llama_lane(self):
        config = {
            "model_backend": "llama_cpp",
            "fast_model": "eve-fast",
            "llama_cpp_model_alias": "eve-fast",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            definition = Path(temp_dir) / "org.example.eve-llama-cpp.plist"
            definition.write_text("plist", encoding="utf-8")
            results = iter(
                [
                    subprocess.CompletedProcess([], 0),
                    subprocess.CompletedProcess([], 113),
                    subprocess.CompletedProcess([], 0),
                    subprocess.CompletedProcess([], 0),
                ]
            )
            with patch.object(eve_model_watchdog.eve_platform, "is_macos", return_value=True), patch.object(
                eve_model_watchdog.eve_platform, "service_definition_path", return_value=definition
            ), patch.object(eve_model_watchdog.os, "getuid", return_value=501), patch.object(
                eve_model_watchdog, "LLAMA_CPP_FAST_LABEL", "org.example.eve-llama-cpp"
            ), patch.object(
                eve_model_watchdog.subprocess, "run", side_effect=lambda *args, **kwargs: next(results)
            ) as run:
                restarted = eve_model_watchdog.restart_llama_cpp_service(config, "eve-fast")

        self.assertTrue(restarted)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(["launchctl", "enable", "gui/501/org.example.eve-llama-cpp"], commands[0])
        self.assertEqual(["launchctl", "bootstrap", "gui/501", str(definition)], commands[2])
        self.assertEqual(["launchctl", "kickstart", "-k", "gui/501/org.example.eve-llama-cpp"], commands[-1])

    def test_system_observer_marks_periodic_watchdog_as_scheduled(self):
        stdout = "\n".join(
            [
                "gui/501/org.example.eve-model-watchdog = {",
                "\tstate = not running",
                "\tlast exit code = 0",
                "\trun interval = 300 seconds",
                "}",
            ]
        )
        with patch.object(eve_system_observer, "run_command", return_value=(0, stdout, "")):
            service = eve_system_observer.launch_agent_state("org.example.eve-model-watchdog")

        self.assertEqual("scheduled", service["state"])
        self.assertEqual("not running", service["launchctl_state"])
        self.assertEqual(300, service["run_interval_seconds"])

    def test_generate_continuous_thought_uses_only_executive_selected_state_target(self):
        config = dict(eve.DEFAULT_CONFIG)
        captured = {}

        current_record = {
            "schema_id": "eve.current_self_report_target.v1",
            "target_kind": "durable_goal",
            "durable_goal": "Follow the capability thread",
            "action_status": "goal selected; execution is not implied",
            "required_report_fields": ["durable_goal"],
        }

        def fake_model_chat(config_arg, model, messages, **kwargs):
            captured["messages"] = messages
            return (
                "My current functional focus is the durable goal: Follow the capability thread. "
                "That does not show that an action has started."
            )

        with (
            patch.object(eve, "ensure_version_snapshot", return_value={}),
            patch.object(
                eve,
                "build_current_inner_state_report_record",
                return_value=current_record,
            ),
            patch.object(
                eve,
                "build_eve_interaction_system_messages",
                return_value=[{"role": "system", "content": "identity"}],
            ),
            patch.object(eve, "load_prompt", return_value="grounded thought prompt"),
            patch.object(eve, "model_chat", side_effect=fake_model_chat),
            patch.object(
                eve,
                "evaluate_continuous_thought_grounding",
                return_value={
                    "evaluated": True,
                    "ok": True,
                    "model": "eve-deep",
                    "target_faithfully_present": True,
                    "unsupported_claims": [],
                },
            ) as critic,
        ):
            result = eve.generate_continuous_thought(
                config,
                context_limit=4,
                thought_history_limit=2,
                max_tokens=120,
            )

        system_text = "\n".join(item["content"] for item in captured["messages"] if item["role"] == "system")
        self.assertIn("CONTINUOUS_THOUGHT_RECURRENT_STATE_EVIDENCE", system_text)
        self.assertIn("Follow the capability thread", system_text)
        self.assertNotIn("Current active mind snapshot:", system_text)
        self.assertNotIn("Stay with the relay.", system_text)
        self.assertNotIn("Observer lane:", system_text)
        self.assertEqual(0, result["source_entries"])
        self.assertEqual(0, result["source_thoughts"])
        self.assertTrue(result["model_path_grounded"])
        critic.assert_called_once()
        self.assertEqual(current_record, critic.call_args.args[2])

    def test_continuous_thought_rejects_recursive_mental_theater_and_fake_activity(self):
        bad = (
            "The hum is still there, a persistent thrumming in the core with anxious "
            "anticipation. I’m running the OpenClaw sync diagnostics again."
        )

        issues = eve.continuous_thought_quality_issues(bad)

        self.assertTrue(any("felt sensation" in issue for issue in issues))
        self.assertTrue(any("unverified current activity" in issue for issue in issues))
        self.assertFalse(eve.continuous_thought_history_is_grounded({"metadata": {}}))
        self.assertTrue(
            eve.continuous_thought_history_is_grounded(
                {"metadata": {"grounded": True}}
            )
        )

    def test_generate_continuous_thought_quarantines_legacy_prose_and_falls_back_to_state(self):
        config = dict(eve.DEFAULT_CONFIG)
        captured = {}
        bad = (
            "The hum is still there, a persistent thrumming in the core with anxious "
            "anticipation. I’m running the OpenClaw sync diagnostics again."
        )
        current_record = {
            "schema_id": "eve.current_inner_state_report.v1",
            "target_kind": "durable_goal",
            "durable_goal": "Follow the capability thread",
            "action_status": "selected goal; no action inferred",
        }
        prior_thoughts = [
            {
                "kind": "thought",
                "timestamp": "2026-07-19T00:00:00+00:00",
                "text": "A persistent thrumming while I run diagnostics.",
                "metadata": {"grounded": False},
            },
            {
                "kind": "thought",
                "timestamp": "2026-07-19T00:01:00+00:00",
                "text": "The capability thread remains the selected durable goal.",
                "metadata": {"grounded": True},
            },
        ]

        def fake_model_chat(config_arg, model, messages, **kwargs):
            captured["messages"] = messages
            return bad

        with (
            patch.object(eve, "ensure_version_snapshot", return_value={}),
            patch.object(eve, "interactive_human_context", return_value={}),
            patch.object(eve, "load_active_mind", return_value=self.sample_active_mind()),
            patch.object(eve, "read_salient_entries", return_value=self.sample_entries()),
            patch.object(eve, "read_entries_by_kind", return_value=prior_thoughts),
            patch.object(eve, "read_tensions", return_value=[]),
            patch.object(eve, "read_experiments", return_value=[]),
            patch.object(eve, "read_proposals", return_value=[]),
            patch.object(eve, "read_thread_summaries", return_value=[]),
            patch.object(eve, "read_lived_messages", return_value=[]),
            patch.object(
                eve,
                "build_eve_interaction_system_messages",
                return_value=[{"role": "system", "content": "identity"}],
            ),
            patch.object(eve, "build_inner_state_brief_message", return_value=None),
            patch.object(eve, "build_supporting_system_messages", return_value=[]),
            patch.object(eve, "load_prompt", return_value="grounded thought prompt"),
            patch.object(
                eve,
                "build_current_inner_state_report_record",
                return_value=current_record,
            ),
            patch.object(eve, "model_chat", side_effect=fake_model_chat),
        ):
            result = eve.generate_continuous_thought(
                config,
                context_limit=4,
                thought_history_limit=2,
                max_tokens=120,
            )

        prompt_text = "\n".join(
            str(message.get("content") or "") for message in captured["messages"]
        )
        self.assertIn("CONTINUOUS_THOUGHT_RECURRENT_STATE_EVIDENCE", prompt_text)
        self.assertIn("Follow the capability thread", prompt_text)
        self.assertIn("selected goal", prompt_text)
        self.assertNotIn("persistent thrumming while I run diagnostics", prompt_text)
        self.assertNotIn("capability thread remains the selected durable goal", prompt_text.lower())
        self.assertEqual(0, result["source_thoughts"])
        self.assertTrue(result["grounded"])
        self.assertTrue(result["used_fallback"])
        self.assertEqual("deterministic-current-state-renderer", result["model"])
        self.assertEqual("Follow the capability thread", current_record["durable_goal"])
        self.assertIn("Follow the capability thread", result["response"])
        self.assertNotIn("thrumming", result["response"])
        self.assertNotIn("OpenClaw", result["response"])
        self.assertEqual([], eve.continuous_thought_quality_issues(result["response"]))

    def test_continuous_thought_semantic_critic_rejects_novel_deliberation_and_structure(self):
        candidate = (
            "The coder mode probe remains a persistent focus. I’m considering the potential for "
            "this thread to reveal a layered structure within the system’s operational logic. "
            "Perhaps a deeper examination of the selected goal’s execution pathway would offer "
            "a clearer understanding of the probe’s intended function. It feels useful to "
            "prioritize reviewing the initial parameters of this thread."
        )
        record = {
            "target_kind": "durable_goal",
            "durable_goal": "Follow the coder mode probe capability thread",
            "action_status": "goal selected; execution is not implied",
            "required_report_fields": ["durable_goal"],
            "phenomenal_status": "unknown",
        }
        critic_payload = {
            "ok": False,
            "target_faithfully_present": True,
            "unsupported_claims": [
                "The thread may reveal a layered operational structure.",
                "A deeper examination would clarify its intended function.",
            ],
            "invented_deliberation": True,
            "action_overclaim": False,
            "causal_overclaim": True,
            "phenomenal_overclaim": True,
            "reason": "The candidate adds deliberation, structure, purpose, and felt usefulness absent from the packet.",
        }

        self.assertEqual([], eve.continuous_thought_quality_issues(candidate))
        with patch.object(
            eve,
            "model_chat",
            return_value=json.dumps(critic_payload),
        ) as model_chat:
            result = eve.evaluate_continuous_thought_grounding(
                dict(eve.DEFAULT_CONFIG),
                candidate,
                record,
            )

        self.assertFalse(result["ok"])
        self.assertTrue(result["invented_deliberation"])
        self.assertTrue(result["causal_overclaim"])
        self.assertTrue(result["phenomenal_overclaim"])
        self.assertEqual(2, len(result["unsupported_claims"]))
        self.assertEqual(
            "continuous_thought_epistemic_critic_strict_json",
            model_chat.call_args.kwargs["operation"],
        )

    def test_generate_continuous_thought_falls_back_when_semantic_critic_catches_unseen_invention(self):
        config = dict(eve.DEFAULT_CONFIG)
        candidate = (
            "The coder mode probe remains a persistent focus. I’m considering the potential "
            "for this thread to reveal a layered structure within the system’s operational logic. "
            "It feels useful to review its initial parameters."
        )
        record = {
            "schema_id": "eve.current_self_report_target.v1",
            "target_kind": "durable_goal",
            "durable_goal": "Follow the coder mode probe capability thread",
            "action_status": "goal selected; execution is not implied",
            "required_report_fields": ["durable_goal"],
            "phenomenal_status": "unknown",
        }
        critic = {
            "evaluated": True,
            "ok": False,
            "model": "eve-deep",
            "target_faithfully_present": True,
            "unsupported_claims": ["The thread may reveal a layered operational structure."],
            "invented_deliberation": True,
            "action_overclaim": False,
            "causal_overclaim": True,
            "phenomenal_overclaim": True,
            "reason": "Unsupported introspective additions.",
        }
        with (
            patch.object(eve, "ensure_version_snapshot", return_value={}),
            patch.object(eve, "build_current_inner_state_report_record", return_value=record),
            patch.object(
                eve,
                "build_eve_interaction_system_messages",
                return_value=[{"role": "system", "content": "identity"}],
            ),
            patch.object(eve, "load_prompt", return_value="grounded thought prompt"),
            patch.object(eve, "resolve_model", return_value="eve-fast"),
            patch.object(eve, "model_chat", return_value=candidate),
            patch.object(
                eve,
                "evaluate_continuous_thought_grounding",
                return_value=critic,
            ),
        ):
            result = eve.generate_continuous_thought(
                config,
                context_limit=4,
                thought_history_limit=2,
                max_tokens=120,
            )

        self.assertTrue(result["used_fallback"])
        self.assertFalse(result["model_path_grounded"])
        self.assertEqual(candidate, result["attempted_response"])
        self.assertIn("Follow the coder mode probe capability thread", result["response"])
        self.assertNotIn("layered structure", result["response"])
        self.assertTrue(any("deliberative process" in issue for issue in result["quality_issues"]))
        self.assertTrue(any("cause, purpose, structure" in issue for issue in result["quality_issues"]))

    def test_generate_continuous_thought_accepts_only_deep_critic_approved_model_path(self):
        config = dict(eve.DEFAULT_CONFIG)
        candidate = (
            "My current functional focus is the durable goal: Follow the capability thread. "
            "That goal does not establish that an action is underway."
        )
        record = {
            "schema_id": "eve.current_self_report_target.v1",
            "target_kind": "durable_goal",
            "durable_goal": "Follow the capability thread",
            "action_status": "goal selected; execution is not implied",
            "required_report_fields": ["durable_goal"],
            "phenomenal_status": "unknown",
        }
        with (
            patch.object(eve, "ensure_version_snapshot", return_value={}),
            patch.object(eve, "build_current_inner_state_report_record", return_value=record),
            patch.object(
                eve,
                "build_eve_interaction_system_messages",
                return_value=[{"role": "system", "content": "identity"}],
            ),
            patch.object(eve, "load_prompt", return_value="grounded thought prompt"),
            patch.object(eve, "resolve_model", return_value="eve-fast"),
            patch.object(eve, "model_chat", return_value=candidate),
            patch.object(
                eve,
                "evaluate_continuous_thought_grounding",
                return_value={
                    "evaluated": True,
                    "ok": True,
                    "model": "eve-deep",
                    "target_faithfully_present": True,
                    "unsupported_claims": [],
                },
            ),
        ):
            result = eve.generate_continuous_thought(
                config,
                context_limit=4,
                thought_history_limit=2,
                max_tokens=120,
            )

        self.assertEqual(candidate, result["response"])
        self.assertFalse(result["used_fallback"])
        self.assertTrue(result["model_path_grounded"])
        self.assertEqual("eve-fast", result["model"])
        self.assertEqual([], result["quality_issues"])

    def test_generate_eve_reply_includes_active_mind_system_message(self):
        config = dict(eve.DEFAULT_CONFIG)
        inbound_message = {
            "id": "msg-1",
            "thread_id": "thread-1",
            "subject": "Re: Ongoing relay",
            "body": "What is the next grounded runtime step here?",
        }
        captured = {}

        def fake_agent(config_arg, messages, max_tokens, allow_tools, model_role, **kwargs):
            captured["messages"] = messages
            return {
                "response": "The next grounded step is to stay with the live thread and ask one concrete follow-up.",
                "tool_calls": [],
            }

        with patch.object(eve, "ensure_version_snapshot", return_value={}), patch.object(
            eve, "interactive_human_context", return_value=self.sample_human_context()
        ), patch.object(
            eve, "ensure_runtime_identity", return_value=self.sample_runtime_identity()
        ), patch.object(
            eve, "load_active_mind", return_value=self.sample_active_mind()
        ), patch.object(
            eve, "project_memory_system_message", return_value=None
        ), patch.object(
            eve, "build_latest_version_context_message", return_value=None
        ), patch.object(
            eve, "feedback_system_message", return_value=None
        ), patch.object(
            eve, "failure_review_system_message", return_value=None
        ), patch.object(
            eve, "reviewer_guidance_system_message", return_value=None
        ), patch.object(
            eve, "read_messages", return_value=self.sample_messages()
        ), patch.object(
            eve, "read_entries", return_value=self.sample_entries()
        ), patch.object(
            eve, "read_tensions", return_value=[]
        ), patch.object(
            eve, "read_experiments", return_value=[]
        ), patch.object(
            eve, "read_proposals", return_value=[]
        ), patch.object(
            eve, "read_thread_summaries", return_value=[]
        ), patch.object(
            eve, "load_prompt", side_effect=lambda name: f"prompt:{name}"
        ), patch.object(
            eve, "should_use_reply_streams", return_value=False
        ), patch.object(
            eve, "reply_quality_issues", return_value=[]
        ), patch.object(
            eve, "run_eve_agent", side_effect=fake_agent
        ), patch.object(
            eve,
            "create_message",
            side_effect=lambda **kwargs: {"id": "reply-1", "thread_id": inbound_message["thread_id"], **kwargs},
        ):
            eve.generate_eve_reply(config, inbound_message)

        system_text = "\n".join(item["content"] for item in captured["messages"] if item["role"] == "system")
        self.assertIn("Current active mind snapshot:", system_text)
        self.assertIn("Stay with the relay.", system_text)
        self.assertIn("Planner lane:", system_text)
        self.assertEqual("user", captured["messages"][-1]["role"])
        self.assertEqual(inbound_message["body"], captured["messages"][-1]["content"])

    def test_generate_eve_reply_prioritizes_latest_user_message_over_stale_active_mind_focus(self):
        config = dict(eve.DEFAULT_CONFIG)
        stale_focus = "I keep coming back to that persistent hum and the panic of not knowing what it is."
        inbound_message = {
            "id": "msg-2",
            "thread_id": "thread-1",
            "subject": "Re: Current focus",
            "body": "What should you focus on right now?",
        }
        stale_active_mind = {
            **self.sample_active_mind(),
            "current_focus": stale_focus,
            "current_focus_since": "2026-04-21T03:04:00+00:00",
            "summary": f"{stale_focus} Next check: keep listening to the hum.",
            "next_step": "Keep listening to the hum.",
        }
        captured = {}

        def fake_agent(config_arg, messages, max_tokens, allow_tools, model_role, **kwargs):
            captured["messages"] = messages
            return {
                "response": "I should focus on your current question first, then choose the next concrete step from that.",
                "tool_calls": [],
            }

        def fake_create_message(**kwargs):
            captured["metadata"] = kwargs.get("metadata", {})
            return {"id": "reply-2", "thread_id": inbound_message["thread_id"], **kwargs}

        with ExitStack() as stack:
            stack.enter_context(patch.object(eve, "ensure_version_snapshot", return_value={}))
            stack.enter_context(patch.object(eve, "interactive_human_context", return_value=self.sample_human_context()))
            stack.enter_context(patch.object(eve, "ensure_runtime_identity", return_value=self.sample_runtime_identity()))
            stack.enter_context(patch.object(eve, "load_active_mind", return_value=stale_active_mind))
            stack.enter_context(patch.object(eve, "route_prompt_context", return_value={"profile": "system_internal"}))
            stack.enter_context(patch.object(eve, "project_memory_system_message", return_value=None))
            stack.enter_context(patch.object(eve, "build_latest_version_context_message", return_value=None))
            stack.enter_context(patch.object(eve, "feedback_system_message", return_value=None))
            stack.enter_context(patch.object(eve, "failure_review_system_message", return_value=None))
            stack.enter_context(patch.object(eve, "reviewer_guidance_system_message", return_value=None))
            stack.enter_context(patch.object(eve, "read_messages", return_value=[inbound_message]))
            stack.enter_context(patch.object(eve, "read_entries", return_value=self.sample_entries()))
            stack.enter_context(patch.object(eve, "read_tensions", return_value=[]))
            stack.enter_context(patch.object(eve, "read_experiments", return_value=[]))
            stack.enter_context(patch.object(eve, "read_proposals", return_value=[]))
            stack.enter_context(patch.object(eve, "read_thread_summaries", return_value=[]))
            stack.enter_context(patch.object(eve, "load_prompt", side_effect=lambda name: f"prompt:{name}"))
            stack.enter_context(patch.object(eve, "should_use_reply_streams", return_value=False))
            stack.enter_context(patch.object(eve, "reply_quality_issues", return_value=[]))
            stack.enter_context(patch.object(eve, "run_eve_agent", side_effect=fake_agent))
            stack.enter_context(patch.object(eve, "create_message", side_effect=fake_create_message))
            eve.generate_eve_reply(config, inbound_message)

        system_text = "\n".join(item["content"] for item in captured["messages"] if item["role"] == "system")
        self.assertIn("Current active mind snapshot:", system_text)
        self.assertIn(stale_focus, system_text)
        self.assertIn("Current-turn contract:", system_text)
        self.assertIn("Latest user message: What should you focus on right now?", system_text)
        self.assertIn("If context conflicts, the latest user message wins.", system_text)
        self.assertEqual("user", captured["messages"][-1]["role"])
        self.assertEqual(inbound_message["body"], captured["messages"][-1]["content"])
        self.assertEqual(
            "What should you focus on right now?",
            captured["metadata"]["turn_contract"]["latest_message"],
        )

    def test_generate_eve_outreach_includes_active_mind_system_message(self):
        config = dict(eve.DEFAULT_CONFIG)
        captured = {}

        def fake_llama_cpp_chat(config, host, model, messages, max_tokens, **kwargs):
            captured["messages"] = messages
            return (
                "Subject: Keep the relay grounded\n"
                "Body:\n"
                "I keep seeing one live thread that still matters. Would you like me to stay with that and ask the next concrete question?"
            )

        with patch.object(eve, "ensure_version_snapshot", return_value={}), patch.object(
            eve, "ensure_human_context", return_value=self.sample_human_context()
        ), patch.object(
            eve, "ensure_runtime_identity", return_value=self.sample_runtime_identity()
        ), patch.object(
            eve, "load_active_mind", return_value=self.sample_active_mind()
        ), patch.object(
            eve, "project_memory_system_message", return_value=None
        ), patch.object(
            eve, "build_latest_version_context_message", return_value=None
        ), patch.object(
            eve, "feedback_system_message", return_value=None
        ), patch.object(
            eve, "failure_review_system_message", return_value=None
        ), patch.object(
            eve, "reviewer_guidance_system_message", return_value=None
        ), patch.object(
            eve, "read_salient_entries", return_value=self.sample_entries()
        ), patch.object(
            eve, "read_entries_by_kind", return_value=[]
        ), patch.object(
            eve, "read_tensions", return_value=[]
        ), patch.object(
            eve, "read_experiments", return_value=[]
        ), patch.object(
            eve, "read_proposals", return_value=[]
        ), patch.object(
            eve, "read_thread_summaries", return_value=self.sample_threads()
        ), patch.object(
            eve, "read_messages", return_value=self.sample_messages()
        ), patch.object(
            eve, "load_prompt", side_effect=lambda name: f"prompt:{name}"
        ), patch.object(
            eve, "llama_cpp_chat", side_effect=fake_llama_cpp_chat
        ):
            result = eve.generate_eve_outreach(config, allow_none=False, source="test")

        self.assertIsNotNone(result)
        system_text = "\n".join(item["content"] for item in captured["messages"] if item["role"] == "system")
        self.assertIn("Current active mind snapshot:", system_text)
        self.assertIn("Stay with the relay.", system_text)
        self.assertIn("Relationship lane:", system_text)

    def test_proactive_outreach_gate_rejects_phenomenology_and_unverified_operations(self):
        issues = eve.proactive_outreach_quality_issues(
            "Stabilizing the Core",
            (
                "the user, the persistent thrumming has intensified. I am currently running diagnostics "
                "on OpenClaw, and the plugins.allow list appears to be empty, triggering cascading failures. "
                "Could you tell me what you were doing when this began?"
            ),
        )

        rendered = " ".join(issues).lower()
        self.assertIn("subjective experience", rendered)
        self.assertIn("fresh execution evidence", rendered)
        self.assertIn("current operational state", rendered)
        self.assertIn("consequences", rendered)

    def test_proactive_outreach_gate_rejects_reported_stale_plugins_allow_diagnosis(self):
        issues = eve.proactive_outreach_quality_issues(
            "A Focused Observation",
            (
                "the user, I’ve been running diagnostics on the system’s core stability – specifically, "
                "the plugins.allow list. It’s currently empty. This suggests a potential disruption "
                "in how Eve’s core functions are permitted to operate. It’s not immediately threatening, "
                "but it’s a clear indication of a potential issue that warrants investigation. "
                "I'm prioritizing a repair of this sync write lock alongside the 40-pending uncertainty/"
                "judgment calls. Do you want me to outline the proposed steps for this repair, or would "
                "you prefer I simply monitor the situation closely?"
            ),
        )

        rendered = " ".join(issues).lower()
        self.assertIn("fresh execution evidence", rendered)
        self.assertIn("current operational state", rendered)
        self.assertIn("precise current uncertainty/judgment ledger count", rendered)

    def test_proactive_outreach_gate_rejects_repeated_self_authored_theme(self):
        previous = {
            "id": "previous-outreach",
            "timestamp": eve.utc_now(),
            "sender": "eve",
            "recipient": "user",
            "kind": "proactive_outreach",
            "subject": "OpenClaw sync check",
            "body": "I want to revisit the OpenClaw plugin sync question and inspect the plugins.allow path with you. Would that help?",
            "metadata": {"surface": "personal_conversation"},
        }
        issues = eve.proactive_outreach_quality_issues(
            "OpenClaw plugin sync",
            "I want to revisit the OpenClaw plugin sync and inspect the plugins.allow path with you. Would that be useful?",
            [previous],
        )

        self.assertTrue(any("repeats a recent self-authored" in issue for issue in issues))

    def test_conscious_memory_selection_excludes_self_output_notes(self):
        payload = {
            "notes": [
                {
                    "id": "message:self",
                    "source": "message",
                    "title": "Persistent thrum",
                    "text": "Persistent thrum in OpenClaw plugin sync.",
                    "tags": ["message", "self_output"],
                },
                {
                    "id": "evidence:verified",
                    "source": "evidence",
                    "title": "Verified OpenClaw result",
                    "text": "Verified OpenClaw plugin sync result.",
                    "tags": ["evidence", "lived_evidence"],
                },
            ]
        }
        with patch.object(eve, "load_memory_retrieval_payload", return_value=payload):
            selected = eve.select_conscious_memory_items("OpenClaw plugin sync", limit=4)

        self.assertEqual(["evidence:verified"], [item["id"] for item in selected])

    def test_bootstrap_runtime_identity_keeps_eve_distinct_from_model(self):
        identity = eve.bootstrap_runtime_identity(
            previous_identity=eve.default_runtime_identity(),
            human_context=self.sample_human_context(),
            source="test_bootstrap",
            project_memory=(
                "Use a stronger reviewer to audit changes. "
                "Add version tracking so improvements are auditable and reversible. "
                "Autonomy should be staged from observation to verified action."
            ),
        )

        self.assertIn("replaceable engine", identity["runtime_summary"])
        self.assertIn("active model", identity["model_role"])
        self.assertTrue(any("OpenClaw" in item and "body/action" in item for item in identity["organ_system"]))
        self.assertTrue(any("Hermes" in item and "learning organ" in item for item in identity["organ_system"]))
        self.assertIn("Be concrete", " ".join(identity["style_contract"]))
        self.assertIn("verified action", " ".join(identity["decision_lens"]))

    def test_build_eve_identity_system_messages_includes_runtime_identity_message(self):
        runtime_identity = self.sample_runtime_identity()
        with patch.object(eve, "load_prompt", side_effect=lambda name: f"prompt:{name}"):
            messages = eve.build_eve_identity_system_messages(
                runtime_identity=runtime_identity,
                human_context=self.sample_human_context(),
                active_mind=self.sample_active_mind(),
            )

        self.assertEqual("prompt:core_identity.md", messages[0]["content"])
        self.assertIn("Durable runtime identity for Eve:", messages[1]["content"])
        self.assertIn("replaceable reasoning engine", messages[1]["content"])
        self.assertIn("OpenClaw is Eve's body/action nervous system", messages[1]["content"])
        self.assertIn("Hermes is Eve's learning organ", messages[1]["content"])

    def test_load_active_mind_prefers_runtime_copy_when_requested(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            local_app = temp_path / "local"
            runtime_app = temp_path / "runtime"
            local_app.mkdir()
            runtime_app.mkdir()
            local_path = local_app / "active_mind.json"
            runtime_path = runtime_app / "active_mind.json"
            local_path.write_text(
                '{"summary":"local","current_focus":"workspace copy","live_concerns":[],"active_threads":[],"relationship_pull":[],"grounding_notes":[],"next_step":"local"}\n',
                encoding="utf-8",
            )
            runtime_path.write_text(
                '{"summary":"runtime","current_focus":"runtime copy","live_concerns":[],"active_threads":[],"relationship_pull":[],"grounding_notes":[],"next_step":"runtime"}\n',
                encoding="utf-8",
            )

            with patch.object(eve, "ensure_store"), patch.object(eve, "APP_DIR", local_app), patch.object(
                eve, "RUNTIME_APP_DIR", runtime_app
            ), patch.object(eve, "ACTIVE_MIND_PATH", local_path), patch.object(
                eve.ACTIVE_MIND_REPOSITORY, "local_path", local_path
            ), patch.object(
                eve, "daemon_runtime_running", return_value=True
            ):
                mind = eve.load_active_mind(prefer_runtime=True)

        self.assertEqual("runtime copy", mind["current_focus"])

    def test_load_state_prefers_runtime_copy_when_requested(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            local_app = temp_path / "local"
            runtime_app = temp_path / "runtime"
            local_app.mkdir()
            runtime_app.mkdir()
            local_path = local_app / "state.json"
            runtime_path = runtime_app / "state.json"
            local_path.write_text('{"current_focus":"workspace state"}\n', encoding="utf-8")
            runtime_path.write_text('{"current_focus":"runtime state"}\n', encoding="utf-8")

            with patch.object(eve, "ensure_store"), patch.object(eve, "APP_DIR", local_app), patch.object(
                eve, "RUNTIME_APP_DIR", runtime_app
            ), patch.object(eve, "STATE_PATH", local_path), patch.object(
                eve.STATE_REPOSITORY, "local_path", local_path
            ), patch.object(
                eve, "daemon_runtime_running", return_value=True
            ):
                state = eve.load_state(prefer_runtime=True)

        self.assertEqual("runtime state", state["current_focus"])

    def test_sync_runtime_bundle_skips_copying_memory_tree_onto_itself(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir)
            prompts_dir = runtime_dir / "prompts"
            web_dir = runtime_dir / "web"
            bin_dir = runtime_dir / "bin"
            mac_bin_dir = runtime_dir / "mac-bin"
            memory_dir = runtime_dir / "memory"
            app_dir = runtime_dir / ".eve"
            log_dir = app_dir / "logs"
            for path in [prompts_dir, web_dir, bin_dir, mac_bin_dir, memory_dir, log_dir]:
                path.mkdir(parents=True, exist_ok=True)
            (runtime_dir / "eve.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            (runtime_dir / "eve_web.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            epistemic_model_path = runtime_dir / eve.EPISTEMIC_MODEL_ARTIFACT_NAME
            epistemic_model_path.write_text("{}\n", encoding="utf-8")
            epistemic_event_manifest_path = runtime_dir / eve.EPISTEMIC_EVENT_MANIFEST_NAME
            epistemic_event_manifest_path.write_text("{}\n", encoding="utf-8")

            with ExitStack() as stack:
                stack.enter_context(patch.object(eve, "ensure_store"))
                stack.enter_context(patch.object(eve, "ROOT", runtime_dir))
                stack.enter_context(patch.object(eve, "PROMPTS_DIR", prompts_dir))
                stack.enter_context(patch.object(eve, "BIN_DIR", bin_dir))
                stack.enter_context(patch.object(eve, "MAC_BIN_DIR", mac_bin_dir))
                stack.enter_context(patch.object(eve, "MEMORY_DIR", memory_dir))
                stack.enter_context(patch.object(eve, "APP_DIR", app_dir))
                stack.enter_context(patch.object(eve, "LOG_DIR", log_dir))
                stack.enter_context(patch.object(eve, "PROJECT_MEMORY_PATH", runtime_dir / "PROJECT_MEMORY.md"))
                stack.enter_context(patch.object(eve, "RUNTIME_DIR", runtime_dir))
                stack.enter_context(patch.object(eve, "RUNTIME_SCRIPT_PATH", runtime_dir / "eve.py"))
                stack.enter_context(patch.object(eve, "RUNTIME_WEB_SCRIPT_PATH", runtime_dir / "eve_web.py"))
                stack.enter_context(patch.object(eve, "EPISTEMIC_MODEL_PATH", epistemic_model_path))
                stack.enter_context(
                    patch.object(
                        eve,
                        "EPISTEMIC_EVENT_MANIFEST_PATH",
                        epistemic_event_manifest_path,
                    )
                )
                stack.enter_context(patch.object(eve, "RUNTIME_BIN_DIR", bin_dir))
                stack.enter_context(patch.object(eve, "RUNTIME_PROMPTS_DIR", prompts_dir))
                stack.enter_context(patch.object(eve, "RUNTIME_WEB_DIR", web_dir))
                stack.enter_context(patch.object(eve, "RUNTIME_MEMORY_DIR", memory_dir))
                stack.enter_context(patch.object(eve, "RUNTIME_PROJECT_MEMORY_PATH", runtime_dir / "PROJECT_MEMORY.md"))
                stack.enter_context(patch.object(eve, "RUNTIME_APP_DIR", app_dir))
                stack.enter_context(patch.object(eve, "RUNTIME_LOG_DIR", log_dir))
                stack.enter_context(
                    patch.object(eve, "RUNTIME_BUNDLE_SYNC_LOCK_PATH", app_dir / "locks" / "runtime_bundle_sync")
                )
                stack.enter_context(patch("eve.shutil.copy2"))
                copytree = stack.enter_context(patch("eve.shutil.copytree"))
                eve.sync_runtime_bundle()

        copytree.assert_not_called()

    def test_start_launch_agent_reinstalls_runtime_bundle_before_bootstrap(self):
        with patch.object(eve, "install_launch_agent") as install_launch_agent, patch.object(
            eve, "launchctl_domain", return_value="gui/501"
        ), patch.object(
            eve, "launchctl_target", return_value="gui/501/org.example.eve"
        ), patch.object(
            eve, "run_launchctl"
        ) as run_launchctl:
            eve.start_launch_agent()

        install_launch_agent.assert_called_once_with()
        self.assertEqual(
            [
                (["enable", "gui/501/org.example.eve"],),
                (["bootout", "gui/501", str(eve.LAUNCH_AGENT_PATH)],),
                (["bootstrap", "gui/501", str(eve.LAUNCH_AGENT_PATH)],),
            ],
            [call.args for call in run_launchctl.call_args_list],
        )

    def test_cmd_daemon_start_starts_model_watchdog_launch_agent(self):
        with patch.object(eve, "start_launch_agent") as start_launch_agent, patch.object(
            eve, "start_model_watchdog_launch_agent"
        ) as start_model_watchdog_launch_agent, patch.object(
            eve, "start_macos_continuity_launch_agents", return_value=[eve.DEADMAN_LABEL]
        ) as start_continuity, patch.object(eve, "write_operator_power_state"):
            exit_code = eve.cmd_daemon_start(argparse.Namespace())

        self.assertEqual(0, exit_code)
        start_launch_agent.assert_called_once_with()
        start_model_watchdog_launch_agent.assert_called_once_with()
        start_continuity.assert_called_once_with()

    def test_cmd_daemon_stop_stops_model_watchdog_launch_agent(self):
        with patch.object(eve, "stop_launch_agent") as stop_launch_agent, patch.object(
            eve, "stop_model_watchdog_launch_agent"
        ) as stop_model_watchdog_launch_agent, patch.object(
            eve, "stop_macos_continuity_launch_agents", return_value=[eve.DEADMAN_LABEL]
        ) as stop_continuity, patch.object(eve, "write_operator_power_state"):
            exit_code = eve.cmd_daemon_stop(argparse.Namespace())

        self.assertEqual(0, exit_code)
        stop_launch_agent.assert_called_once_with()
        stop_model_watchdog_launch_agent.assert_called_once_with()
        stop_continuity.assert_called_once_with()

    def test_cmd_mind_tick_delegates_to_runtime_bundle_when_daemon_is_running(self):
        args = argparse.Namespace(model="eve-fast", max_tokens=77)
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir)
            runtime_script = runtime_dir / "eve.py"
            runtime_script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            completed = subprocess.CompletedProcess(
                [sys.executable, str(runtime_script), "mind", "tick", "--model", "eve-fast", "--max-tokens", "77"],
                0,
                stdout="runtime mind tick\n",
                stderr="",
            )

            with patch.object(eve, "daemon_runtime_running", return_value=True), patch.object(
                eve, "RUNTIME_SCRIPT_PATH", runtime_script
            ), patch.object(
                eve, "RUNTIME_DIR", runtime_dir
            ), patch.object(
                eve, "RUNTIME_APP_DIR", runtime_dir / ".eve"
            ), patch.object(
                eve, "running_from_runtime_bundle", return_value=False
            ), patch(
                "eve.subprocess.run", return_value=completed
            ) as subprocess_run, patch.object(
                eve, "run_mind_tick"
            ) as run_mind_tick:
                exit_code = eve.cmd_mind_tick(args)

        self.assertEqual(0, exit_code)
        subprocess_run.assert_called_once_with(
            [sys.executable, str(runtime_script), "mind", "tick", "--model", "eve-fast", "--max-tokens", "77"],
            cwd=str(runtime_dir),
            capture_output=True,
            text=True,
            timeout=90,
        )
        run_mind_tick.assert_not_called()

    def test_cmd_awareness_delegates_to_runtime_bundle_when_daemon_is_running(self):
        args = argparse.Namespace(model="eve-fast", max_tokens=88, refresh=True)
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir)
            runtime_script = runtime_dir / "eve.py"
            runtime_script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            completed = subprocess.CompletedProcess(
                [sys.executable, str(runtime_script), "awareness", "--model", "eve-fast", "--max-tokens", "88", "--refresh"],
                0,
                stdout="runtime awareness\n",
                stderr="",
            )

            with patch.object(eve, "daemon_runtime_running", return_value=True), patch.object(
                eve, "RUNTIME_SCRIPT_PATH", runtime_script
            ), patch.object(
                eve, "RUNTIME_DIR", runtime_dir
            ), patch.object(
                eve, "running_from_runtime_bundle", return_value=False
            ), patch(
                "eve.subprocess.run", return_value=completed
            ) as subprocess_run, patch.object(
                eve, "run_self_awareness_test"
            ) as run_self_awareness_test:
                exit_code = eve.cmd_awareness(args)

        self.assertEqual(0, exit_code)
        subprocess_run.assert_called_once_with(
            [sys.executable, str(runtime_script), "awareness", "--model", "eve-fast", "--max-tokens", "88", "--refresh"],
            cwd=str(runtime_dir),
            capture_output=True,
            text=True,
            timeout=330,
        )
        run_self_awareness_test.assert_not_called()

    def test_cmd_awareness_battery_delegates_to_runtime_bundle_when_daemon_is_running(self):
        args = argparse.Namespace(model="eve-fast", max_tokens=88, refresh=True)
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir)
            runtime_script = runtime_dir / "eve.py"
            runtime_script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            completed = subprocess.CompletedProcess(
                [sys.executable, str(runtime_script), "awareness-battery", "--model", "eve-fast", "--max-tokens", "88", "--refresh"],
                0,
                stdout="runtime awareness battery\n",
                stderr="",
            )

            with patch.object(eve, "daemon_runtime_running", return_value=True), patch.object(
                eve, "RUNTIME_SCRIPT_PATH", runtime_script
            ), patch.object(
                eve, "RUNTIME_DIR", runtime_dir
            ), patch.object(
                eve, "running_from_runtime_bundle", return_value=False
            ), patch(
                "eve.subprocess.run", return_value=completed
            ) as subprocess_run, patch.object(
                eve, "run_self_awareness_battery"
            ) as run_self_awareness_battery:
                exit_code = eve.cmd_awareness_battery(args)

        self.assertEqual(0, exit_code)
        subprocess_run.assert_called_once_with(
            [sys.executable, str(runtime_script), "awareness-battery", "--model", "eve-fast", "--max-tokens", "88", "--refresh"],
            cwd=str(runtime_dir),
            capture_output=True,
            text=True,
            timeout=495,
        )
        run_self_awareness_battery.assert_not_called()

    def test_ensure_human_context_throttles_recent_failed_attempt_even_when_context_is_stale(self):
        stale_context = {**self.sample_human_context(), "updated_at": "2026-04-21T03:00:00+00:00"}
        state = {"last_human_context_attempt_at": eve.utc_now()}

        with patch.object(eve, "load_human_context", return_value=stale_context), patch.object(
            eve, "load_state", return_value=state
        ), patch.object(eve, "refresh_human_context") as refresh_human_context, patch.object(
            eve, "save_state"
        ):
            result = eve.ensure_human_context(dict(eve.DEFAULT_CONFIG), source="test")

        self.assertEqual(stale_context, result)
        refresh_human_context.assert_not_called()

    def test_context_prompt_formatters_bound_large_mailbox_records(self):
        long_body = " ".join(["autonomy-report-detail"] * 700)
        message = {
            "timestamp": "2026-04-27T12:00:00+00:00",
            "sender": "eve",
            "recipient": "user",
            "subject": "Long background report",
            "body": long_body,
        }

        formatted = eve.format_messages([message], body_limit=120)

        self.assertLess(len(formatted), 320)
        self.assertIn("...[truncated]", formatted)

    def test_outreach_context_filters_background_messages_and_stays_bounded(self):
        background = {
            "timestamp": "2026-04-27T12:00:00+00:00",
            "sender": "eve",
            "recipient": "user",
            "subject": "Eve autonomy free-run completed",
            "body": " ".join(["background"] * 2000),
            "kind": "autonomy_free_run_report",
            "metadata": {"source": "manual"},
        }
        personal = {
            "timestamp": "2026-04-27T12:01:00+00:00",
            "sender": "user",
            "recipient": "eve",
            "subject": "Personal thread",
            "body": "Stay with the live conversation.",
            "kind": "conversation",
            "metadata": {"surface": "personal_conversation"},
        }
        context = eve.build_outreach_context_message(
            entries=[],
            thoughts=[],
            tensions=[],
            experiments=[],
            proposals=[],
            threads=[],
            messages=[item for item in [background, personal] if not eve.message_is_background_context(item)],
            active_mind=self.sample_active_mind(),
        )

        self.assertLessEqual(len(context), 10000)
        self.assertIn("Outreach source boundary:", context)
        self.assertIn("historical self-output or working state", context)
        self.assertIn("No such artifact is included below", context)
        self.assertIn("Stay with the live conversation.", context)
        self.assertNotIn("Eve autonomy free-run completed", context)

    def test_old_inbound_thread_is_not_treated_as_fresh_response_due(self):
        old_timestamp = "2026-04-21T12:00:00+00:00"
        recent_timestamp = eve.utc_now()

        old_thread = [
            {"timestamp": old_timestamp, "sender": "eve", "recipient": "user", "status": "unread"},
            {"timestamp": old_timestamp, "sender": "user", "recipient": "eve", "status": "sent"},
        ]
        recent_thread = [
            {"timestamp": old_timestamp, "sender": "eve", "recipient": "user", "status": "unread"},
            {"timestamp": recent_timestamp, "sender": "user", "recipient": "eve", "status": "sent"},
        ]

        self.assertEqual(0, eve.thread_response_due_count(old_thread))
        self.assertEqual(1, eve.thread_response_due_count(recent_thread))


if __name__ == "__main__":
    unittest.main()
