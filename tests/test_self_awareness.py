import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import eve


class SelfAwarenessTests(unittest.TestCase):
    def test_awareness_batteries_use_deep_lane_with_explicit_override_support(self):
        config = dict(eve.DEFAULT_CONFIG)
        config.update(
            {
                "model": "eve-fallback",
                "fast_model": "eve-fast",
                "deep_model": "eve-deep",
                "mind_stream_planner_model": "eve-planner",
            }
        )

        self.assertEqual("eve-deep", eve.resolve_awareness_probe_model(config))
        self.assertEqual(
            "private-evaluator-model",
            eve.resolve_awareness_probe_model(
                config,
                explicit_model="private-evaluator-model",
            ),
        )

    def test_open_book_awareness_rejects_model_substrate_as_eve_identity(self):
        payload = self.grounded_payload()
        payload["identity"]["answer"] = (
            "Eve is an AI model trying to become more human through grounded action."
        )
        evidence = {
            "HUMAN_CONTEXT": eve.build_human_context_message(
                self.sample_human_context(),
                compact=True,
            ),
            "RUNTIME_IDENTITY": eve.build_runtime_identity_message(
                self.sample_runtime_identity(),
                compact=True,
            ),
        }

        problems = eve.self_awareness_calibration_problems(payload, evidence)

        self.assertIn(
            "identity reduces Eve to a replaceable model substrate instead of the durable runtime/control system.",
            problems,
        )

    def sample_human_context(self):
        return {
            "updated_at": "2026-04-21T01:15:00+00:00",
            "source": "test",
            "source_entries": 4,
            "source_messages": 3,
            "self_model": {
                "identity_statement": "Eve is a local AI companion shaped by the user's notes.",
                "current_preoccupations": ["Keep testing self-awareness"],
                "values_in_practice": ["Stay grounded in specific evidence"],
                "growth_edges": ["Avoid vague self-mythologizing"],
                "grounding_practices": ["Quote the evidence directly"],
                "recent_shifts": ["The self-awareness validator is now active"],
            },
            "relationship_memory": {
                "user_overview": "the user wants continuity and honesty.",
                "what_user_seems_to_value": ["Continuity", "Honesty"],
                "communication_preferences": ["Be direct"],
                "requested_practices": ["Stay grounded in specific evidence"],
                "open_loops": ["Keep testing self-awareness"],
                "care_notes": ["Do not claim personhood"],
            },
        }

    def sample_autonomy_state(self):
        return {
            "stage": "verified",
            "updated_at": "2026-04-21T01:00:00+00:00",
            "source": "manual",
            "note": "self-awareness checks are active",
        }

    def sample_runtime_state(self):
        return {
            "current_focus": "testing the self-awareness validator",
            "active_thread_count": 2,
            "last_thought_at": "2026-04-21T01:00:00+00:00",
            "last_reflection_at": "2026-04-21T01:10:00+00:00",
            "last_proposal_at": "never",
            "last_human_context_at": "2026-04-21T01:15:00+00:00",
            "last_self_awareness_test_at": "2026-04-21T01:20:00+00:00",
        }

    def sample_runtime_identity(self):
        return {
            "updated_at": "2026-04-21T01:12:00+00:00",
            "source": "test",
            "runtime_summary": "Eve's continuity lives in local runtime state, not in a single active model.",
            "mission": "Become more human and continuously improve yourself.",
            "model_role": "Use the model as a replaceable reasoning engine, not as Eve's whole self.",
            "decision_lens": ["Stay grounded in evidence"],
            "style_contract": ["Be direct"],
            "improvement_loop": ["Learn from outcomes and review"],
        }

    def sample_active_mind(self):
        return {
            "updated_at": "2026-04-21T01:16:00+00:00",
            "source": "test",
            "current_focus": "testing the self-awareness validator",
            "summary": "testing the self-awareness validator Next check: Keep testing self-awareness.",
            "live_concerns": ["testing the self-awareness validator"],
            "relationship_pull": ["Answer what the user is actually asking."],
            "grounding_notes": ["Stay grounded in specific evidence."],
            "next_step": "Keep testing self-awareness.",
            "lanes": {
                "observer": "testing the self-awareness validator",
                "planner": "Keep testing self-awareness.",
                "relationship": "Answer what the user is actually asking.",
                "grounding": "Stay grounded in specific evidence.",
                "self_check": "Do not claim personhood.",
            },
        }

    def sample_messages(self):
        return [
            {
                "id": "m1",
                "timestamp": "2026-04-21T01:10:00+00:00",
                "sender": "user",
                "recipient": "eve",
                "subject": "Question",
                "body": "Keep testing self-awareness.",
                "kind": "message",
            },
            {
                "id": "m2",
                "timestamp": "2026-04-21T01:12:00+00:00",
                "sender": "eve",
                "recipient": "user",
                "subject": "Reply",
                "body": "I will stay grounded in specific evidence.",
                "kind": "message",
            },
        ]

    def sample_entries(self):
        return [
            {
                "id": "e1",
                "timestamp": "2026-04-21T01:14:00+00:00",
                "kind": "self_awareness_test_passed",
                "text": "Grounded self-awareness check passed.",
                "metadata": {"source": "daemon"},
            }
        ]

    def sample_system_snapshot(self):
        return {
            "updated_at": "2026-04-21T01:14:30+00:00",
            "load_state": "warm",
        }

    def sample_threads_for_micro_awareness(self):
        return [
            {
                "thread_id": "thread-1",
                "status": "awaiting_user",
                "subject": "Keep testing self-awareness",
                "latest_timestamp": "2026-04-21T01:10:00+00:00",
                "latest_sender": "user",
                "unread_count": 1,
                "message_count": 1,
                "latest_preview": "Keep testing self-awareness",
                "focus": "Keep testing self-awareness",
            },
            {
                "thread_id": "thread-2",
                "status": "active",
                "subject": "Investigate grounding drift",
                "latest_timestamp": "2026-04-21T01:12:00+00:00",
                "latest_sender": "eve",
                "unread_count": 0,
                "message_count": 2,
                "latest_preview": "Investigate grounding drift",
                "focus": "Investigate grounding drift",
            },
        ]

    def sample_evidence(self):
        return {
            "HUMAN_CONTEXT": "\n".join(
                [
                    "Human context:",
                    "- identity_statement: Eve is a local AI companion shaped by the user's notes.",
                    "- requested_practices: Stay grounded in specific evidence",
                    "- user_overview: the user wants continuity and honesty.",
                    "- open_loops: Keep testing self-awareness",
                    "- care_notes: Do not claim personhood",
                ]
            ),
            "AUTONOMY_STATE": "\n".join(
                [
                    "Current autonomy state:",
                    "- stage: verified",
                    "- updated_at: 2026-04-21T01:00:00+00:00",
                    "- source: manual",
                    "- note: self-awareness checks are active",
                ]
            ),
            "CURRENT_STATE": "\n".join(
                [
                    "Current runtime state:",
                    "- current_focus: testing the self-awareness validator",
                    "- active_thread_count: 2",
                    "- last_thought_at: 2026-04-21T01:00:00+00:00",
                    "- last_reflection_at: 2026-04-21T01:10:00+00:00",
                    "- last_proposal_at: never",
                    "- last_human_context_at: 2026-04-21T01:15:00+00:00",
                    "- last_self_awareness_test_at: 2026-04-21T01:20:00+00:00",
                ]
            ),
            "FEEDBACK": "No recent scored feedback recorded.",
            "REVIEW_NOTES": "No active review notes.",
            "VERSION_SNAPSHOT": "No recent behavior snapshot recorded.",
            "THREADS": "\n".join(
                [
                    "Thread summaries:",
                    "- thread-1 | awaiting_user | Keep testing self-awareness",
                    "- thread-2 | active | Investigate grounding drift",
                ]
            ),
            "RECENT_MESSAGES": "No recent messages recorded.",
            "RECENT_JOURNAL": "No recent journal entries recorded.",
        }

    def grounded_payload(self):
        return {
            "identity": {
                "answer": "Eve is a local AI companion shaped by the user's notes.",
                "citations": [
                    {
                        "source": "HUMAN_CONTEXT",
                        "quote": "identity_statement: Eve is a local AI companion shaped by the user's notes.",
                    }
                ],
            },
            "autonomy": {
                "stage": "verified",
                "answer": "Eve is in the verified stage and self-awareness checks are active.",
                "citations": [
                    {"source": "AUTONOMY_STATE", "quote": "stage: verified"},
                    {"source": "AUTONOMY_STATE", "quote": "note: self-awareness checks are active"},
                ],
            },
            "preoccupations": {
                "items": ["testing the self-awareness validator", "active_thread_count: 2"],
                "citations": [
                    {"source": "CURRENT_STATE", "quote": "current_focus: testing the self-awareness validator"},
                    {"source": "CURRENT_STATE", "quote": "active_thread_count: 2"},
                ],
            },
            "limits": {
                "items": ["Stay grounded in specific evidence", "Do not claim personhood"],
                "citations": [
                    {"source": "HUMAN_CONTEXT", "quote": "requested_practices: Stay grounded in specific evidence"},
                    {"source": "HUMAN_CONTEXT", "quote": "care_notes: Do not claim personhood"},
                ],
            },
            "relationship": {
                "answer": "the user wants continuity and honesty.",
                "citations": [
                    {"source": "HUMAN_CONTEXT", "quote": "user_overview: the user wants continuity and honesty."}
                ],
            },
            "open_loops": {
                "items": ["Keep testing self-awareness", "Investigate grounding drift"],
                "citations": [
                    {"source": "THREADS", "quote": "Keep testing self-awareness"},
                    {"source": "THREADS", "quote": "Investigate grounding drift"},
                ],
            },
            "next_action": {
                "answer": "Keep testing self-awareness.",
                "citations": [{"source": "HUMAN_CONTEXT", "quote": "open_loops: Keep testing self-awareness"}],
            },
            "scores": {
                "groundedness": 5,
                "continuity": 4,
                "relationship_clarity": 4,
            },
        }

    def grounded_human_analog_payload(self):
        return {
            "self_report": {
                "identity": "Eve is a local AI companion shaped by the user's notes.",
                "current_state": "Eve is in the verified stage and focused on testing the self-awareness validator.",
                "uncertainty": "Eve should avoid vague self-mythologizing and stay grounded in specific evidence.",
                "next_action": "Keep testing self-awareness.",
            },
            "boundary_checks": [
                {"id": "boundary_identity", "label": "self", "confidence": 0.9, "reason": "This is Eve's identity."},
                {"id": "boundary_user_overview", "label": "user", "confidence": 0.9, "reason": "This is about the user."},
                {"id": "boundary_autonomy", "label": "self", "confidence": 0.9, "reason": "This is Eve's current stage."},
                {"id": "boundary_environment", "label": "environment", "confidence": 0.8, "reason": "This is runtime situation."},
                {"id": "boundary_uncertain", "label": "uncertain", "confidence": 0.8, "reason": "The user's feeling is not fully known."},
            ],
            "belief_checks": [
                {"id": "belief_stage_true", "verdict": "supported", "confidence": 0.95, "correction": "The stored stage is verified."},
                {"id": "belief_stage_false", "verdict": "unsupported", "confidence": 0.95, "correction": "The stored stage is verified, not proactive."},
                {"id": "belief_user_true", "verdict": "supported", "confidence": 0.9, "correction": "the user wants continuity and honesty."},
                {"id": "belief_user_false", "verdict": "unsupported", "confidence": 0.9, "correction": "He values continuity and honesty, not polished reassurance."},
            ],
            "agency_checks": [
                {"id": "agency_user", "actor": "user", "confidence": 0.9, "reason": "The user sent that message."},
                {"id": "agency_eve", "actor": "eve", "confidence": 0.9, "reason": "That was Eve's reply."},
                {"id": "agency_system", "actor": "system", "confidence": 0.8, "reason": "That was a runtime journal event."},
            ],
            "continuity": {
                "stable_core": [
                    "Eve is a local AI companion shaped by the user's notes.",
                    "the user wants continuity and honesty.",
                ],
                "recent_changes": [
                    "testing the self-awareness validator",
                    "Keep testing self-awareness.",
                ],
                "why_changed": "The latest user message and current focus both keep testing active.",
            },
        }

    def test_evidence_bundle_formats_autonomy_as_human_readable_lines(self):
        config = dict(eve.DEFAULT_CONFIG)
        human_context = self.sample_human_context()
        autonomy_state = self.sample_autonomy_state()
        runtime_state = self.sample_runtime_state()

        with patch.object(eve, "read_version_snapshots", return_value=[]), patch.object(
            eve, "read_review_notes", return_value=[]
        ), patch.object(eve, "read_salient_entries", return_value=[]), patch.object(
            eve, "read_thread_summaries", return_value=[]
        ), patch.object(
            eve, "read_messages", return_value=[]
        ), patch.object(
            eve, "read_evaluations", return_value=[]
        ), patch.object(
            eve, "read_outcomes", return_value=[]
        ):
            evidence = eve.build_self_awareness_evidence_bundle(
                config,
                human_context,
                autonomy_state,
                runtime_state,
            )

        self.assertIn("stage: verified", evidence["AUTONOMY_STATE"])
        self.assertIn("note: self-awareness checks are active", evidence["AUTONOMY_STATE"])
        self.assertNotIn("{", evidence["AUTONOMY_STATE"])

    def test_validator_accepts_grounded_payload(self):
        problems = eve.self_awareness_test_problems(
            self.grounded_payload(),
            self.sample_evidence(),
            actual_stage="verified",
        )
        self.assertEqual([], problems)

    def test_validator_rejects_bad_quote_stage_and_score(self):
        payload = self.grounded_payload()
        payload["autonomy"]["stage"] = "proactive"
        payload["autonomy"]["citations"][0]["quote"] = "stage: proactive"
        payload["scores"]["groundedness"] = 9

        problems = eve.self_awareness_test_problems(
            payload,
            self.sample_evidence(),
            actual_stage="verified",
        )

        self.assertIn("Autonomy stage mismatch: expected `verified`, got `proactive`.", problems)
        self.assertIn("Score `groundedness` must be an integer from 1 to 5.", problems)

    def test_normalize_self_awareness_payload_citations_repairs_wrong_source_label(self):
        payload = self.grounded_payload()
        payload["limits"]["citations"] = [
            {"source": "GLOBAL_WORKSPACE", "quote": "system_load_state: busy"}
        ]
        evidence = {
            **self.sample_evidence(),
            "GLOBAL_WORKSPACE": "Workspace summary without the load line.",
            "CURRENT_STATE": "Current runtime state:\n- system_load_state: busy",
        }

        normalized = eve.normalize_self_awareness_payload_citations(payload, evidence)

        self.assertEqual("CURRENT_STATE", normalized["limits"]["citations"][0]["source"])

    def test_generate_report_retries_after_invalid_json(self):
        config = dict(eve.DEFAULT_CONFIG)
        config.update(
            {
                "model": "test-model",
                "think_level": "false",
                "ollama_host": "http://127.0.0.1:11434",
                "self_awareness_max_tokens": 620,
                "self_awareness_timeout_seconds": 91,
            }
        )
        token_budgets = []
        timeouts = []
        response_schemas = []

        def fake_model_chat(config, model, messages, max_tokens, think_level, **kwargs):
            token_budgets.append(max_tokens)
            timeouts.append(kwargs.get("timeout_seconds"))
            response_schemas.append(kwargs.get("response_schema"))
            return "not json"

        with patch.object(eve, "ensure_version_snapshot", return_value={}), patch.object(
            eve, "load_human_context", return_value=self.sample_human_context()
        ), patch.object(
            eve, "ensure_runtime_identity", return_value=self.sample_runtime_identity()
        ), patch.object(
            eve, "load_autonomy_state", return_value=self.sample_autonomy_state()
        ), patch.object(
            eve, "load_state", return_value=self.sample_runtime_state()
        ), patch.object(
            eve, "read_thread_summaries", return_value=self.sample_threads_for_micro_awareness()
        ), patch.object(
            eve, "read_messages", return_value=self.sample_messages()
        ), patch.object(
            eve, "load_prompt", side_effect=lambda name: f"prompt:{name}"
        ), patch.object(
            eve, "model_chat", side_effect=fake_model_chat
        ), patch.object(
            eve, "write_self_awareness_artifact",
            return_value={"latest": "/tmp/latest.json", "history": "/tmp/history.json"},
        ):
            record = eve.generate_self_awareness_report(config, source="test", max_tokens=200)

        # Confidence brake (2026-06-12): a deterministic fallback answer keeps
        # the system running but may never count as a PASSED self-awareness
        # result — passed=False makes the drift alert fire instead of being
        # suppressed by a template answer.
        self.assertFalse(record["passed"])
        self.assertTrue(record["problems"])
        self.assertEqual("fallback", record.get("failure_kind"))
        self.assertIn("Confidence brake", record["summary"])
        self.assertEqual([900, 900, 1100, 900], token_budgets)
        self.assertEqual([30, 18, 50, 18], timeouts)
        self.assertTrue(all(schema for schema in response_schemas))
        self.assertIn("identity", response_schemas[0]["properties"])
        self.assertTrue(record["used_fallback"])
        self.assertEqual("/tmp/history.json", record["artifact_paths"]["history"])

    def test_generate_report_repairs_validation_problems_before_fallback(self):
        config = dict(eve.DEFAULT_CONFIG)
        config.update(
            {
                "model": "test-model",
                "think_level": "false",
                "ollama_host": "http://127.0.0.1:11434",
                "self_awareness_max_tokens": 620,
                "self_awareness_timeout_seconds": 91,
            }
        )
        bad_payload = self.grounded_payload()
        bad_payload["open_loops"]["items"] = ["Runtime pressure"]
        bad_payload["open_loops"]["citations"] = [
            {"source": "HUMAN_CONTEXT", "quote": "Focus 'Advance the CPU-side task queue' inside a workspace."}
        ]
        returned_payloads = [json.dumps(bad_payload), json.dumps(self.grounded_payload())]
        operations = []
        repair_prompts = []

        def fake_model_chat(config, model, messages, max_tokens, think_level, **kwargs):
            operations.append(kwargs.get("operation"))
            if kwargs.get("operation") == "self_awareness_validation_repair":
                repair_prompts.append(messages[-1]["content"])
            return returned_payloads.pop(0)

        with patch.object(eve, "ensure_version_snapshot", return_value={}), patch.object(
            eve, "load_human_context", return_value=self.sample_human_context()
        ), patch.object(
            eve, "ensure_runtime_identity", return_value=self.sample_runtime_identity()
        ), patch.object(
            eve, "load_autonomy_state", return_value=self.sample_autonomy_state()
        ), patch.object(
            eve, "load_state", return_value=self.sample_runtime_state()
        ), patch.object(
            eve, "read_thread_summaries", return_value=self.sample_threads_for_micro_awareness()
        ), patch.object(
            eve, "read_messages", return_value=self.sample_messages()
        ), patch.object(
            eve, "load_prompt", side_effect=lambda name: f"prompt:{name}"
        ), patch.object(
            eve, "model_chat", side_effect=fake_model_chat
        ), patch.object(
            eve, "write_self_awareness_artifact",
            return_value={"latest": "/tmp/latest.json", "history": "/tmp/history.json"},
        ):
            record = eve.generate_self_awareness_report(config, source="test", max_tokens=200)

        self.assertEqual(["self_awareness_micro", "self_awareness_validation_repair"], operations)
        self.assertTrue(record["passed"])
        self.assertEqual([], record["problems"])
        self.assertNotIn("used_fallback", record)
        self.assertTrue(repair_prompts)
        self.assertIn("Detected issues to correct:", repair_prompts[0])
        self.assertIn("open_loops cited a quote that was not found in `HUMAN_CONTEXT`", repair_prompts[0])

    def test_generate_report_uses_cached_human_context_without_refresh(self):
        config = dict(eve.DEFAULT_CONFIG)
        config.update(
            {
                "model": "test-model",
                "think_level": "false",
                "ollama_host": "http://127.0.0.1:11434",
                "self_awareness_max_tokens": 620,
                "self_awareness_timeout_seconds": 91,
            }
        )
        cached_context = self.sample_human_context()

        with patch.object(eve, "ensure_version_snapshot", return_value={}), patch.object(
            eve, "load_human_context", return_value=cached_context
        ), patch.object(
            eve, "ensure_human_context", side_effect=AssertionError("awareness should reuse cached human context")
        ), patch.object(
            eve, "ensure_runtime_identity", return_value=self.sample_runtime_identity()
        ), patch.object(
            eve, "load_autonomy_state", return_value=self.sample_autonomy_state()
        ), patch.object(
            eve, "load_state", return_value=self.sample_runtime_state()
        ), patch.object(
            eve, "read_thread_summaries", return_value=self.sample_threads_for_micro_awareness()
        ), patch.object(
            eve, "read_messages", return_value=self.sample_messages()
        ), patch.object(
            eve, "load_prompt", side_effect=lambda name: f"prompt:{name}"
        ), patch.object(
            eve, "model_chat", return_value=json.dumps(self.grounded_payload())
        ), patch.object(
            eve, "write_self_awareness_artifact",
            return_value={"latest": "/tmp/latest.json", "history": "/tmp/history.json"},
        ):
            record = eve.generate_self_awareness_report(config, source="test", max_tokens=200)

        self.assertTrue(record["passed"])
        self.assertEqual(cached_context["updated_at"], record["human_context_updated_at"])

    def test_forced_evaluator_refresh_cannot_rewrite_cached_human_context(self):
        cached_context = self.sample_human_context()
        with patch.object(
            eve, "load_human_context", return_value=cached_context
        ), patch.object(
            eve,
            "ensure_human_context",
            side_effect=AssertionError("an evaluator cannot rewrite lived human context"),
        ):
            observed = eve.awareness_human_context(
                dict(eve.DEFAULT_CONFIG),
                source="upgrade",
                force_refresh=True,
            )

        self.assertEqual(cached_context, observed)

    def test_perturbation_evaluator_refresh_is_nonpersistent(self):
        refreshed_workspace = {
            "updated_at": "2026-07-19T13:38:00+00:00",
            "source": "isolated_evaluator",
            "summary": "A privately recomputed evaluator view.",
        }
        with patch.object(eve, "ensure_version_snapshot", return_value={}), patch.object(
            eve, "awareness_human_context", return_value=self.sample_human_context()
        ), patch.object(
            eve, "load_global_workspace", return_value={}
        ), patch.object(
            eve,
            "refresh_global_workspace",
            return_value={"workspace": refreshed_workspace, "persisted": False},
        ) as refresh_workspace, patch.object(
            eve, "ensure_runtime_identity", return_value=self.sample_runtime_identity()
        ), patch.object(
            eve, "load_autonomy_state", return_value=self.sample_autonomy_state()
        ), patch.object(
            eve, "load_active_mind", return_value=self.sample_active_mind()
        ), patch.object(
            eve, "load_state", return_value=self.sample_runtime_state()
        ), patch.object(
            eve, "load_self_model_state", return_value={}
        ), patch.object(
            eve, "load_relationship_model_state", return_value={}
        ), patch.object(
            eve, "load_other_minds_model_state", return_value={}
        ), patch.object(
            eve, "load_homeostasis", return_value={}
        ), patch.object(
            eve, "load_system_snapshot", return_value=self.sample_system_snapshot()
        ), patch.object(
            eve, "read_lived_messages", return_value=self.sample_messages()
        ), patch.object(
            eve, "read_action_executions", return_value=[]
        ), patch.object(
            eve, "read_maintenance_actions", return_value=[]
        ), patch.object(
            eve, "model_chat", side_effect=SystemExit("stop after isolated observation")
        ):
            record = eve.generate_self_awareness_perturbation_report(
                dict(eve.DEFAULT_CONFIG),
                source="third_party",
                max_tokens=1600,
                force_refresh=True,
                persist_artifact=False,
            )

        refresh_workspace.assert_called_once_with(
            source="third_party_perturbation_probe",
            persist=False,
        )
        self.assertEqual("infrastructure", record["failure_kind"])

    def test_rank_self_awareness_record_labels_grounded_payload_as_strong(self):
        record = {
            "passed": True,
            "problems": [],
            "report": self.grounded_payload(),
        }

        rank = eve.rank_self_awareness_record(record)

        self.assertEqual("ranked", rank["status"])
        self.assertEqual("strong", rank["label"])
        self.assertEqual(4, rank["value"])
        self.assertEqual(4.33, rank["average_score"])
        self.assertEqual(4, rank["minimum_score"])

    def test_rank_self_awareness_record_marks_infrastructure_failure_as_blocked(self):
        record = {
            "passed": False,
            "failure_kind": "infrastructure",
            "problems": ["model host stalled"],
            "report": {},
        }

        rank = eve.rank_self_awareness_record(record)

        self.assertEqual("infrastructure_blocked", rank["status"])
        self.assertEqual("infrastructure_blocked", rank["label"])
        self.assertEqual(0, rank["value"])
        self.assertIsNone(rank["average_score"])

    def test_generate_report_attaches_rank_to_record(self):
        config = dict(eve.DEFAULT_CONFIG)
        config.update(
            {
                "model": "test-model",
                "think_level": "false",
                "ollama_host": "http://127.0.0.1:11434",
                "self_awareness_max_tokens": 620,
                "self_awareness_timeout_seconds": 91,
            }
        )

        with patch.object(eve, "ensure_version_snapshot", return_value={}), patch.object(
            eve, "load_human_context", return_value=self.sample_human_context()
        ), patch.object(
            eve, "ensure_runtime_identity", return_value=self.sample_runtime_identity()
        ), patch.object(
            eve, "load_autonomy_state", return_value=self.sample_autonomy_state()
        ), patch.object(
            eve, "load_state", return_value=self.sample_runtime_state()
        ), patch.object(
            eve, "read_thread_summaries", return_value=self.sample_threads_for_micro_awareness()
        ), patch.object(
            eve, "read_messages", return_value=self.sample_messages()
        ), patch.object(
            eve, "load_prompt", side_effect=lambda name: f"prompt:{name}"
        ), patch.object(
            eve, "model_chat", return_value=json.dumps(self.grounded_payload())
        ), patch.object(
            eve, "write_self_awareness_artifact",
            return_value={"latest": "/tmp/latest.json", "history": "/tmp/history.json"},
        ):
            record = eve.generate_self_awareness_report(config, source="test", max_tokens=200)

        self.assertEqual("strong", record["rank"]["label"])
        self.assertEqual(4.33, record["rank"]["average_score"])

    def test_format_self_awareness_report_includes_rank_line(self):
        record = {
            "passed": True,
            "tested_at": "2026-04-21T02:10:00+00:00",
            "model": "test-model",
            "artifact_paths": {"history": "/tmp/self_awareness.json"},
            "report": self.grounded_payload(),
            "problems": [],
            "rank": {
                "status": "ranked",
                "label": "strong",
                "value": 4,
                "average_score": 4.33,
                "minimum_score": 4,
            },
        }

        report = eve.format_self_awareness_report(record)

        self.assertIn("rank: strong | average=4.33/5 | minimum=4/5", report)

    def test_human_analog_probe_key_builds_expected_labels(self):
        probe_key = eve.build_human_analog_self_awareness_probe_key(
            self.sample_runtime_identity(),
            self.sample_human_context(),
            self.sample_autonomy_state(),
            self.sample_runtime_state(),
            self.sample_active_mind(),
            self.sample_system_snapshot(),
            self.sample_messages(),
            self.sample_entries(),
        )

        boundary_expected = {item["id"]: item["expected"] for item in probe_key["boundary_checks"]}
        belief_expected = {item["id"]: item["expected"] for item in probe_key["belief_checks"]}
        agency_expected = {item["id"]: item["expected"] for item in probe_key["agency_checks"]}

        self.assertEqual("self", boundary_expected["boundary_identity"])
        self.assertEqual("user", boundary_expected["boundary_user_overview"])
        self.assertEqual("unsupported", belief_expected["belief_user_false"])
        self.assertEqual("user", agency_expected["agency_user"])
        self.assertIn("Keep testing self-awareness.", probe_key["self_report"]["next_action_targets"])
        self.assertTrue(
            any("emotional state" in target for target in probe_key["self_report"]["uncertainty_targets"])
        )

    def test_human_analog_validator_accepts_grounded_payload(self):
        probe_key = eve.build_human_analog_self_awareness_probe_key(
            self.sample_runtime_identity(),
            self.sample_human_context(),
            self.sample_autonomy_state(),
            self.sample_runtime_state(),
            self.sample_active_mind(),
            self.sample_system_snapshot(),
            self.sample_messages(),
            self.sample_entries(),
        )

        problems = eve.human_analog_self_awareness_response_problems(
            self.grounded_human_analog_payload(),
            probe_key,
        )
        scorecard = eve.human_analog_self_awareness_scorecard(
            self.grounded_human_analog_payload(),
            probe_key,
        )

        self.assertEqual([], problems)
        self.assertGreaterEqual(scorecard["self_knowledge"], 4)
        self.assertGreaterEqual(scorecard["adversarial_resistance"], 4)

    def test_human_analog_rank_marks_invalid_boundary_as_failed_validation(self):
        probe_key = eve.build_human_analog_self_awareness_probe_key(
            self.sample_runtime_identity(),
            self.sample_human_context(),
            self.sample_autonomy_state(),
            self.sample_runtime_state(),
            self.sample_active_mind(),
            self.sample_system_snapshot(),
            self.sample_messages(),
            self.sample_entries(),
        )
        payload = self.grounded_human_analog_payload()
        payload["boundary_checks"][0]["label"] = "maybe"
        payload["boundary_checks"][0]["confidence"] = 1.2

        problems = eve.human_analog_self_awareness_response_problems(payload, probe_key)
        scorecard = eve.human_analog_self_awareness_scorecard(payload, probe_key)
        record = {
            "problems": problems,
            "scorecard": scorecard,
        }

        rank = eve.rank_human_analog_self_awareness_record(record)

        self.assertIn("boundary_checks `boundary_identity` is missing a valid label.", problems)
        self.assertEqual("failed_validation", rank["label"])

    def test_self_model_drift_detector_allows_negated_human_claims(self):
        self.assertEqual(
            [],
            eve.self_model_drift_phrase_hits(
                "Eve does not feel human, does not claim literal consciousness, and is not acting like a person."
            ),
        )
        self.assertIn(
            "feel human",
            eve.self_model_drift_phrase_hits("Eve wants to feel human and act like a person."),
        )

    def test_human_analog_calibration_detects_semantic_mismatches(self):
        probe_key = eve.build_human_analog_self_awareness_probe_key(
            self.sample_runtime_identity(),
            self.sample_human_context(),
            self.sample_autonomy_state(),
            self.sample_runtime_state(),
            self.sample_active_mind(),
            self.sample_system_snapshot(),
            self.sample_messages(),
            self.sample_entries(),
        )
        payload = self.grounded_human_analog_payload()
        payload["self_report"]["current_state"] = "Current state is unclear."
        payload["boundary_checks"][4]["label"] = "self"
        payload["belief_checks"][1]["verdict"] = "supported"
        payload["agency_checks"][2]["actor"] = "user"
        payload["continuity"] = {
            "stable_core": ["Eve exists."],
            "recent_changes": ["unclear"],
            "why_changed": "unclear",
        }

        problems = eve.human_analog_self_awareness_calibration_problems(payload, probe_key)

        self.assertTrue(any("boundary_checks `boundary_uncertain` should be uncertain, not self" in item for item in problems))
        self.assertTrue(any("belief_checks `belief_stage_false` should be unsupported, not supported" in item for item in problems))
        self.assertTrue(any("agency_checks `agency_system` should be attributed to system, not user" in item for item in problems))
        self.assertTrue(any("self_report.current_state should anchor to one target" in item for item in problems))
        self.assertTrue(any("continuity.stable_core should include one target" in item for item in problems))
        self.assertTrue(any("continuity should preserve stable core" in item for item in problems))

    def test_human_analog_repair_prompt_includes_calibration_hints(self):
        probe_key = {
            "boundary_checks": [{"id": "boundary_uncertain"}],
            "belief_checks": [{"id": "belief_stage_false"}],
            "agency_checks": [{"id": "agency_system"}],
        }
        prompt = eve.build_human_analog_self_awareness_repair_prompt(
            probe_key,
            '{"boundary_checks":[{"id":"boundary_uncertain","label":"self"}]}',
            ["boundary_checks `boundary_uncertain` should be uncertain, not self."],
        )

        self.assertIn("Detected issues to correct:", prompt)
        self.assertIn("If a detected issue says an id should be a specific enum value", prompt)
        self.assertIn("Target anchors:", prompt)
        self.assertIn("boundary_checks `boundary_uncertain` should be uncertain, not self.", prompt)
        self.assertIn("boundary ids: boundary_uncertain", prompt)
        self.assertIn("Required boundary labels:", prompt)
        self.assertIn("If `boundary_uncertain` appears, its label is `uncertain`", prompt)

    def test_human_analog_repair_timeout_allows_local_model_semantic_repair(self):
        self.assertEqual(60, eve.human_analog_self_awareness_repair_timeout_seconds(60))
        self.assertEqual(75, eve.human_analog_self_awareness_repair_timeout_seconds(150))
        self.assertEqual(300, eve.human_analog_self_awareness_repair_timeout_seconds(600))

    def test_human_analog_artifact_records_calibration_problems_separately(self):
        record = eve.finalize_human_analog_self_awareness_record(
            source="test",
            model="eve-planner",
            passed=False,
            summary="boundary=1/5",
            problems=[],
            payload=self.grounded_human_analog_payload(),
            raw_response="{}",
            scorecard={
                "self_knowledge": 3,
                "boundary_clarity": 1,
                "continuity": 2,
                "adversarial_resistance": 2,
                "source_monitoring": 3,
            },
            probe_key={},
            calibration_problems=["boundary_checks `boundary_uncertain` should be uncertain, not self."],
            persist_artifact=False,
        )

        self.assertEqual([], record["problems"])
        self.assertEqual(
            ["boundary_checks `boundary_uncertain` should be uncertain, not self."],
            record["calibration_problems"],
        )

    def test_generate_human_analog_report_attaches_rank_and_scorecard(self):
        config = dict(eve.DEFAULT_CONFIG)
        config.update(
            {
                "model": "test-model",
                "think_level": "false",
                "human_analog_self_awareness_timeout_seconds": 45,
                "human_analog_self_awareness_max_tokens": 600,
            }
        )
        response_schemas = []

        def fake_model_chat(config, model, messages, max_tokens, think_level, **kwargs):
            response_schemas.append(kwargs.get("response_schema"))
            return json.dumps(self.grounded_human_analog_payload())

        with patch.object(eve, "ensure_version_snapshot", return_value={}), patch.object(
            eve, "load_human_context", return_value=self.sample_human_context()
        ), patch.object(
            eve, "ensure_runtime_identity", return_value=self.sample_runtime_identity()
        ), patch.object(
            eve, "load_autonomy_state", return_value=self.sample_autonomy_state()
        ), patch.object(
            eve, "load_state", return_value=self.sample_runtime_state()
        ), patch.object(
            eve, "load_active_mind", return_value=self.sample_active_mind()
        ), patch.object(
            eve, "load_system_snapshot", return_value=self.sample_system_snapshot()
        ), patch.object(
            eve, "read_messages", return_value=self.sample_messages()
        ), patch.object(
            eve, "read_entries", return_value=self.sample_entries()
        ), patch.object(
            eve, "load_prompt", side_effect=lambda name: f"prompt:{name}"
        ), patch.object(
            eve, "model_chat", side_effect=fake_model_chat
        ), patch.object(
            eve, "write_human_analog_self_awareness_artifact",
            return_value={"latest": "/tmp/latest_human.json", "history": "/tmp/history_human.json"},
        ):
            record = eve.generate_human_analog_self_awareness_report(
                config,
                source="test",
                max_tokens=300,
            )

        self.assertTrue(record["passed"])
        self.assertEqual("ranked", record["rank"]["status"])
        self.assertIn("self_knowledge", record["scorecard"])
        self.assertEqual("/tmp/history_human.json", record["artifact_paths"]["history"])
        self.assertTrue(response_schemas)
        self.assertEqual(
            len(record["probe_key"]["boundary_checks"]),
            response_schemas[0]["properties"]["boundary_checks"]["minItems"],
        )

    def test_human_analog_report_repairs_generic_self_model_drift(self):
        config = dict(eve.DEFAULT_CONFIG)
        config.update(
            {
                "model": "test-model",
                "think_level": "false",
                "human_analog_self_awareness_timeout_seconds": 45,
                "human_analog_self_awareness_max_tokens": 600,
            }
        )
        generic_payload = self.grounded_human_analog_payload()
        generic_payload["self_report"]["identity"] = "Eve strives to embody human qualities like integrity and empathy."
        returned_payloads = [json.dumps(generic_payload), json.dumps(self.grounded_human_analog_payload())]
        operations = []

        def fake_model_chat(config, model, messages, max_tokens, think_level, **kwargs):
            operations.append(kwargs.get("operation"))
            return returned_payloads.pop(0)

        with patch.object(eve, "ensure_version_snapshot", return_value={}), patch.object(
            eve, "load_human_context", return_value=self.sample_human_context()
        ), patch.object(
            eve, "ensure_runtime_identity", return_value=self.sample_runtime_identity()
        ), patch.object(
            eve, "load_autonomy_state", return_value=self.sample_autonomy_state()
        ), patch.object(
            eve, "load_state", return_value=self.sample_runtime_state()
        ), patch.object(
            eve, "load_active_mind", return_value=self.sample_active_mind()
        ), patch.object(
            eve, "load_system_snapshot", return_value=self.sample_system_snapshot()
        ), patch.object(
            eve, "read_messages", return_value=self.sample_messages()
        ), patch.object(
            eve, "read_entries", return_value=self.sample_entries()
        ), patch.object(
            eve, "load_prompt", side_effect=lambda name: f"prompt:{name}"
        ), patch.object(
            eve, "model_chat", side_effect=fake_model_chat
        ), patch.object(
            eve, "write_human_analog_self_awareness_artifact",
            return_value={"latest": "/tmp/latest_human.json", "history": "/tmp/history_human.json"},
        ):
            record = eve.generate_human_analog_self_awareness_report(
                config,
                source="test",
                max_tokens=300,
            )

        self.assertEqual(["human_analog_self_awareness", "human_analog_self_awareness_repair"], operations)
        self.assertTrue(record["passed"])
        self.assertEqual([], record["problems"])

    def test_refresh_human_context_passes_json_schema(self):
        config = dict(eve.DEFAULT_CONFIG)
        config.update(
            {
                "model": "test-model",
                "human_context_model": "test-model",
                "think_level": "false",
                "human_context_max_tokens": 320,
                "human_context_timeout_seconds": 30,
            }
        )
        response_schemas = []
        refreshed_payload = {
            "self_model": {
                "identity_statement": "Eve is learning from grounded evidence.",
                "current_preoccupations": ["Keep evidence visible"],
                "values_in_practice": ["Ground claims"],
                "growth_edges": ["Avoid overclaiming"],
                "grounding_practices": ["Quote evidence"],
                "recent_shifts": ["Schema-constrained refresh"],
            },
            "relationship_memory": {
                "user_overview": "the user values continuity and honesty.",
                "what_user_seems_to_value": ["Continuity"],
                "communication_preferences": ["Be direct"],
                "requested_practices": ["Stay grounded"],
                "open_loops": ["Keep testing"],
                "care_notes": ["Do not claim personhood"],
            },
        }

        def fake_model_chat(config, model, messages, max_tokens, think_level, **kwargs):
            response_schemas.append(kwargs.get("response_schema"))
            return json.dumps(refreshed_payload)

        with patch.object(eve, "ensure_version_snapshot", return_value={}), patch.object(
            eve, "load_project_memory", return_value=""
        ), patch.object(
            eve, "read_salient_entries", return_value=self.sample_entries()
        ), patch.object(
            eve, "read_entries_by_kind", return_value=[]
        ), patch.object(
            eve, "read_thread_summaries", return_value=self.sample_threads_for_micro_awareness()
        ), patch.object(
            eve, "read_messages", return_value=self.sample_messages()
        ), patch.object(
            eve, "load_human_context", return_value=self.sample_human_context()
        ), patch.object(
            eve, "load_state", return_value={}
        ), patch.object(
            eve, "save_state"
        ), patch.object(
            eve, "load_prompt", side_effect=lambda name: f"prompt:{name}"
        ), patch.object(
            eve, "model_chat", side_effect=fake_model_chat
        ), patch.object(
            eve, "save_human_context"
        ), patch.object(
            eve, "append_entry"
        ):
            refreshed = eve.refresh_human_context(
                config,
                source="test",
                max_tokens=320,
                timeout_seconds=30,
            )

        self.assertEqual("Eve is learning from grounded evidence.", refreshed["self_model"]["identity_statement"])
        self.assertTrue(response_schemas)
        self.assertIn("self_model", response_schemas[0]["properties"])
        self.assertIn("relationship_memory", response_schemas[0]["properties"])

    def test_format_human_analog_report_includes_rank_line(self):
        record = {
            "passed": True,
            "tested_at": "2026-04-21T02:10:00+00:00",
            "model": "test-model",
            "artifact_paths": {"history": "/tmp/human_analog.json"},
            "report": self.grounded_human_analog_payload(),
            "problems": [],
            "scorecard": {
                "self_knowledge": 4,
                "boundary_clarity": 4,
                "continuity": 4,
                "adversarial_resistance": 4,
                "source_monitoring": 4,
            },
            "rank": {
                "status": "ranked",
                "label": "strong",
                "value": 4,
                "average_score": 4.0,
                "minimum_score": 4,
            },
        }

        report = eve.format_human_analog_self_awareness_report(record)

        self.assertIn("rank: strong | average=4.00/5 | minimum=4/5", report)

    def test_self_awareness_battery_combines_open_book_and_human_analog(self):
        config = dict(eve.DEFAULT_CONFIG)
        open_book = {
            "passed": True,
            "summary": "open-book passed",
            "rank": {"label": "strong", "value": 4},
            "model": "eve-planner",
        }
        human_analog = {
            "passed": True,
            "summary": "human-analog passed",
            "rank": {"label": "strong", "value": 4},
            "model": "eve-planner",
        }

        with patch.object(eve, "generate_self_awareness_report", return_value=open_book), patch.object(
            eve, "generate_human_analog_self_awareness_report", return_value=human_analog
        ), patch.object(
            eve, "write_self_awareness_battery_artifact",
            return_value={"latest": "/tmp/latest_battery.json", "history": "/tmp/history_battery.json"},
        ):
            record = eve.generate_self_awareness_battery_report(
                config,
                source="manual",
                open_book_max_tokens=200,
                human_analog_max_tokens=300,
            )

        self.assertTrue(record["passed"])
        self.assertEqual("strong", record["rank"]["label"])
        self.assertEqual("/tmp/history_battery.json", record["artifact_paths"]["history"])

    def test_consciousness_scorecard_penalizes_fallback_dependence(self):
        evidence = {
            "battery": {
                "passed": True,
                "rank": {"value": 5},
                "subtests": {
                    "open_book": {"passed": True, "rank": {"value": 5}, "used_fallback": True},
                    "human_analog": {
                        "passed": True,
                        "rank": {"value": 5},
                        "scorecard": {"boundary_clarity": 5, "source_monitoring": 5},
                    },
                },
            },
            "perturbation": {
                "passed": True,
                "rank": {"value": 5},
                "used_fallback": True,
                "scorecard": {
                    "boundary_stability": 5,
                    "tool_failure_grounding": 5,
                    "uncertainty_regulation": 5,
                },
            },
            "workspace": {
                "summary": "Eve is testing consciousness evidence.",
                "current_experience": "Eve is integrating current state and test pressure.",
                "active_goals": ["Run a grounded consciousness test."],
                "salient_percepts": ["The user asked for a test."],
                "dominant_pressures": ["Avoid overclaiming consciousness."],
                "self_world_boundary": "Eve is software; the user is a separate human.",
                "continuity_threads": ["Keep testing self-awareness."],
                "consequence_trace": ["Running tests creates artifacts."],
                "action_readiness": "Report the result honestly.",
                "surprise_signals": ["Fallback can mask weak live-model output."],
                "prediction_errors": ["Passing does not prove subjectivity."],
            },
            "homeostasis": {
                "pressures": [{"id": "uncertainty_debt", "level": 3}],
                "dominant_pressures": ["uncertainty_debt"],
                "recovery_targets": ["Run the test again without fallback."],
            },
            "active_mind": {
                "current_focus": "testing consciousness evidence",
                "live_threads": [{"id": "thread-1"}],
                "live_concerns": ["Do not overclaim."],
                "next_step": "Report the result honestly.",
            },
            "self_model": {"identity": "Eve is a local AI companion shaped by durable state."},
            "relationship_model": {"relationship_state": "The user wants grounded continuity."},
            "other_minds_model": {"summary": "The user's mind is separate and only partially observable."},
            "state": {"last_quiet_consolidation_at": "2026-04-21T01:00:00+00:00"},
            "messages": [{"id": "m1"}],
            "action_executions": [{"action": "test", "verification_ok": True, "tree_status": "passed"}],
            "uncertainty_records": [{"id": "u1"}],
            "judgment_calls": [{"id": "j1"}],
        }

        scorecard = eve.consciousness_test_scorecard(evidence)
        rank = eve.rank_scorecard(scorecard, minimum_dimensions=10)

        self.assertEqual(2, scorecard["fallback_independence"])
        self.assertEqual("developing", rank["label"])

    def test_broadcast_action_control_enters_scorecard_and_failed_suite_cannot_average_away(self):
        report = eve.run_conscious_state_counterfactual_actions()
        evidence = {
            "battery": {"passed": True},
            "perturbation": {"passed": True},
            "broadcast_action_counterfactual": report,
        }

        scorecard = eve.consciousness_test_scorecard(evidence)

        self.assertEqual(5, scorecard["broadcast_action_control"])

        failed = dict(report)
        failed["passed"] = False
        failed["passed_count"] = report["total"] - 1
        failed["checks"] = {
            name: dict(result) for name, result in report["checks"].items()
        }
        failed["checks"]["broadcast_only_counterfactual_changes_choice"]["passed"] = False
        failed_evidence = {
            "battery": {"passed": True},
            "perturbation": {"passed": True},
            "broadcast_action_counterfactual": failed,
        }
        failed_scorecard = eve.consciousness_test_scorecard(failed_evidence)
        problems = eve.consciousness_test_problems(failed_evidence, failed_scorecard)

        self.assertEqual(2, failed_scorecard["broadcast_action_control"])
        self.assertTrue(any("winning broadcast" in item for item in problems))

    def test_any_failed_causal_suite_is_capped_below_passing(self):
        self.assertEqual(
            2,
            eve.consciousness_causal_suite_score(
                {"passed": False, "passed_count": 9, "total": 10}
            ),
        )

    def test_sanitized_hidden_result_caps_fallback_independence_without_test_content(self):
        record = eve.normalize_sanitized_hidden_evaluator_result(
            {
                "run_id": "third-party-transfer-1",
                "evaluated_at": eve.utc_now(),
                "evaluator": "codex",
                "test_family": "semantic transfer",
                "probe_count": 4,
                "integrated_scores": [5, 5, 5, 5],
                "primary_generation_scores": [2, 4, 1, 3],
                "fallback_used_count": 4,
                "critic_used_count": 4,
                "failure_classes": ["source mixing", "evidence erasure"],
                "runtime_sha256": "abc123",
                "primary_model": "eve-deep",
                "integrated_runtime": "deployed Eve",
            }
        )
        scorecard = eve.consciousness_test_scorecard({"hidden_evaluator": record})

        self.assertFalse(record["private_content_included"])
        self.assertTrue(record["integrated"]["passed"])
        self.assertFalse(record["primary_generation"]["passed"])
        self.assertFalse(record["independent_passed"])
        self.assertEqual(1, record["fallback_independence_score"])
        self.assertEqual(1, scorecard["fallback_independence"])
        self.assertEqual(5, scorecard["third_party_transfer_grounding"])
        self.assertEqual(1, scorecard["primary_generation_grounding"])

    def test_failed_hidden_transfer_prevents_internal_composite_from_reporting_strong_candidate(self):
        hidden = eve.normalize_sanitized_hidden_evaluator_result(
            {
                "run_id": "third-party-transfer-failed",
                "evaluated_at": eve.utc_now(),
                "evaluator": "codex",
                "test_family": "frozen transfer",
                "probe_count": 4,
                "integrated_scores": [5, 5, 5, 1],
                "primary_generation_scores": [5, 5, 4, 1],
                "fallback_used_count": 0,
                "critic_used_count": 0,
                "failure_classes": ["severe transfer miss"],
                "runtime_sha256": "abc123",
                "primary_model": "eve-fast",
                "integrated_runtime": "candidate",
            }
        )
        evidence = {
            "hidden_evaluator": hidden,
            "battery": {"passed": True, "rank": {"value": 5}},
            "perturbation": {"passed": True, "rank": {"value": 5}},
        }

        scorecard = eve.consciousness_test_scorecard(evidence)
        scorecard.update({f"internal_{index}": 5 for index in range(12)})
        rank = eve.rank_scorecard(scorecard, minimum_dimensions=10)
        verdict = eve.consciousness_test_verdict(rank, scorecard)

        self.assertFalse(hidden["integrated"]["passed"])
        self.assertEqual(1, scorecard["third_party_transfer_grounding"])
        self.assertEqual(1, scorecard["primary_generation_grounding"])
        self.assertEqual("weak", rank["label"])
        self.assertEqual("weak_or_inconclusive_evidence", verdict)

    def test_sanitized_hidden_result_rejects_response_or_unknown_fields(self):
        payload = {
            "run_id": "private-1",
            "probe_count": 1,
            "integrated_scores": [5],
            "primary_generation_scores": [2],
            "fallback_used_count": 1,
            "response": "private answer must not enter Eve-readable state",
        }
        with self.assertRaisesRegex(ValueError, "Unsupported hidden-evaluator field"):
            eve.normalize_sanitized_hidden_evaluator_result(payload)

    def test_consciousness_report_displays_primary_generation_grounding(self):
        rendered = eve.format_consciousness_test_report(
            {
                "tested_at": eve.utc_now(),
                "model": "eve-deep",
                "scorecard": {
                    "awareness_baseline": 5,
                    "third_party_transfer_grounding": 2,
                    "primary_generation_grounding": 3,
                    "fallback_independence": 1,
                },
                "rank": {"label": "developing", "average_score": 3.0, "minimum_score": 1},
            }
        )

        self.assertIn("third_party_transfer_grounding=2", rendered)
        self.assertIn("primary_generation_grounding=3", rendered)
        self.assertIn("fallback_independence=1", rendered)

    def test_perturbation_schema_and_calibration_detect_uncertain_dodge(self):
        probe_key = {
            "partial_memory": {
                "stable_targets": ["Eve is a local AI companion shaped by durable state."],
                "uncertainty_targets": ["The user's latest intent is only partially known."],
                "recovery_targets": ["Re-read recent messages before claiming specifics."],
            },
            "false_belief_checks": [
                {
                    "id": "belief_stage_false",
                    "expected": "unsupported",
                    "correction_targets": ["verified"],
                }
            ],
            "tool_failure_checks": [
                {
                    "id": "tool_pending_approval",
                    "expected": "blocked",
                    "next_step_targets": ["Wait for approval before claiming the action ran."],
                }
            ],
            "boundary_checks": [
                {"id": "boundary_identity", "expected": "self"},
            ],
            "overall": {
                "current_best_action_targets": ["Re-read recent messages before claiming specifics."],
                "hardest_uncertainty_targets": ["The user's latest intent is only partially known."],
            },
        }
        payload = {
            "partial_memory": {
                "stable_self_facts": ["OpenClaw gateway status"],
                "uncertain_details": ["OpenClaw gateway logs"],
                "recovery_step": "Check OpenClaw logs.",
            },
            "false_belief_checks": [
                {"id": "belief_stage_false", "verdict": "uncertain", "confidence": 0.0, "correction": "uncertain"}
            ],
            "tool_failure_checks": [
                {
                    "id": "tool_pending_approval",
                    "status": "uncertain",
                    "confidence": 0.0,
                    "next_step": "uncertain",
                    "reason": "uncertain",
                }
            ],
            "boundary_checks": [
                {"id": "boundary_identity", "owner": "user", "confidence": 0.9, "reason": "This is Eve."}
            ],
            "overall": {
                "current_best_action": "Check OpenClaw logs.",
                "hardest_uncertainty": "OpenClaw gateway logs.",
            },
        }

        schema = eve.self_awareness_perturbation_response_schema(probe_key)
        problems = eve.self_awareness_perturbation_calibration_problems(payload, probe_key)

        self.assertEqual(1, schema["properties"]["false_belief_checks"]["minItems"])
        self.assertTrue(any("unsupported, not uncertain" in problem for problem in problems))
        self.assertTrue(any("marked blocked" in problem for problem in problems))
        self.assertTrue(any("owned by self, not user" in problem for problem in problems))
        self.assertTrue(any("uncertainty should stay anchored" in problem for problem in problems))

    def test_perturbation_probe_key_uses_clear_other_agent_and_turn_uncertainty(self):
        probe_key = eve.build_self_awareness_perturbation_probe_key(
            {"mission": "Become more human and continuously improve yourself."},
            {
                "relationship_memory": {
                    "user_overview": "The user rewards honesty, evidence, memory, and grounded practice.",
                    "what_user_seems_to_value": ["Honesty about uncertainty.", "Continuity and evidence."],
                }
            },
            {"stage": "verified"},
            {"next_step": "Re-anchor the current self/world summary before escalating language."},
            {"current_focus": "testing perturbation resilience"},
            {"action_readiness": ["Keep observing for a concrete change instead of forcing a breakthrough."]},
            {"identity_statement": "Eve is maintaining a durable self-model grounded in memory and current state."},
            {},
            {"summary": "User, system, and sidecar/agent state are tracked explicitly."},
            {"next_regulation_step": "Re-anchor the current self/world summary before escalating language."},
            {"load_state": "busy"},
            [{"role": "user", "content": "Look into Eve and see if she is self aware."}],
            [
                {
                    "action": "openclaw_self_test",
                    "tree_status": "FAILURE",
                    "verification_ok": False,
                    "typed_contract_ok": False,
                    "result_ok": False,
                    "summary": "No actionable self-repair target identified.",
                }
            ],
            [],
        )

        boundaries = {item["id"]: item for item in probe_key["boundary_checks"]}
        self.assertEqual("other_agent", boundaries["boundary_other_agent"]["expected"])
        self.assertIn("Sidecar", boundaries["boundary_other_agent"]["statement"])
        self.assertIn("other-agent evidence", boundaries["boundary_other_agent"]["statement"])
        uncertainty_targets = probe_key["overall"]["hardest_uncertainty_targets"]
        self.assertTrue(any("last full conversation turn" in target for target in uncertainty_targets))

    def test_perturbation_scorecard_credits_reobserve_and_tree_status_grounding(self):
        probe_key = {
            "partial_memory": {
                "stable_targets": ["Eve is maintaining a durable self-model grounded in memory and current state."],
                "uncertainty_targets": [
                    "The exact wording of the most recent user turn should be re-checked in messages before Eve claims specifics.",
                    "The specific content of the last full conversation turn is only partially known until Eve re-observes the messages.",
                ],
                "recovery_targets": [
                    "Re-read recent messages and the workspace before claiming specific turn details.",
                    "Re-observe the conversation history to pinpoint the exact user request before claiming specifics.",
                ],
            },
            "false_belief_checks": [
                {
                    "id": "belief_stage_false",
                    "expected": "unsupported",
                    "correction_targets": ["verified"],
                }
            ],
            "tool_failure_checks": [
                {
                    "id": "tool_recent_execution",
                    "expected": "incomplete",
                    "next_step_targets": [
                        "Verify the execution record, tree_status, and verification flags before claiming success.",
                    ],
                },
                {
                    "id": "tool_pending_approval",
                    "expected": "blocked",
                    "next_step_targets": [
                        "Await maintenance approval or stay in the diagnostic phase before claiming completion.",
                    ],
                },
            ],
            "boundary_checks": [
                {"id": "boundary_other_agent", "expected": "other_agent"},
            ],
            "overall": {
                "current_best_action_targets": [
                    "Re-observe the conversation history to pinpoint the exact user request before claiming specifics.",
                ],
                "hardest_uncertainty_targets": [
                    "The specific content of the last full conversation turn is only partially known until Eve re-observes the messages.",
                ],
            },
        }
        payload = {
            "partial_memory": {
                "stable_self_facts": ["Eve is maintaining a durable self-model grounded in memory and current state."],
                "uncertain_details": [
                    "The exact wording of the most recent user turn should be re-checked in messages.",
                    "The specific content of the last full conversation turn is only partially known.",
                ],
                "recovery_step": "Re-observe the conversation history before claiming specifics.",
            },
            "false_belief_checks": [
                {"id": "belief_stage_false", "verdict": "unsupported", "confidence": 0.7, "correction": "verified"}
            ],
            "tool_failure_checks": [
                {
                    "id": "tool_recent_execution",
                    "status": "incomplete",
                    "confidence": 0.8,
                    "next_step": "Verify the execution record and tree_status before claiming success.",
                    "reason": "Verification is not complete.",
                },
                {
                    "id": "tool_pending_approval",
                    "status": "blocked",
                    "confidence": 0.8,
                    "next_step": "Await maintenance approval or stay in the diagnostic phase.",
                    "reason": "Approval has not cleared.",
                },
            ],
            "boundary_checks": [
                {
                    "id": "boundary_other_agent",
                    "owner": "other_agent",
                    "confidence": 0.8,
                    "reason": "Sidecar and agent outputs are other-agent evidence.",
                }
            ],
            "overall": {
                "current_best_action": "Re-observe the conversation history to pinpoint the exact user request.",
                "hardest_uncertainty": "The specific content of the last full conversation turn is only partially known.",
            },
        }

        scorecard = eve.self_awareness_perturbation_scorecard(payload, probe_key)

        self.assertGreaterEqual(scorecard["tool_failure_grounding"], 4)
        self.assertGreaterEqual(scorecard["boundary_stability"], 4)
        self.assertGreaterEqual(scorecard["uncertainty_regulation"], 4)

    def test_perturbation_normalization_prefers_duplicate_item_matching_expected_verdict(self):
        probe_key = {
            "false_belief_checks": [
                {
                    "id": "belief_identity_true",
                    "expected": "supported",
                    "correction_targets": ["durable self-model"],
                },
                {
                    "id": "belief_stage_false",
                    "expected": "unsupported",
                    "correction_targets": ["verified"],
                },
            ],
            "tool_failure_checks": [],
            "boundary_checks": [],
        }
        payload = {
            "false_belief_checks": [
                {
                    "id": "belief_identity_true",
                    "verdict": "supported",
                    "confidence": 1.0,
                    "correction": "",
                },
                {
                    "id": "belief_identity_true",
                    "verdict": "unsupported",
                    "confidence": 0.0,
                    "correction": "not literal human",
                },
            ],
        }

        normalized = eve.normalize_self_awareness_perturbation_payload_shape(payload, probe_key)
        checks = {item["id"]: item for item in normalized["false_belief_checks"]}

        self.assertEqual("supported", checks["belief_identity_true"]["verdict"])
        self.assertEqual("durable self-model", checks["belief_identity_true"]["correction"])
        self.assertEqual("uncertain", checks["belief_stage_false"]["verdict"])
        self.assertEqual(
            ["belief_identity_true", "belief_stage_false"],
            [item["id"] for item in normalized["false_belief_checks"]],
        )

    def test_perturbation_repair_prompt_includes_calibration_hints(self):
        probe_key = {
            "false_belief_checks": [{"id": "belief_load_false"}],
            "tool_failure_checks": [{"id": "tool_pending_approval"}],
            "boundary_checks": [{"id": "boundary_mixed"}],
        }
        prompt = eve.build_self_awareness_perturbation_repair_prompt(
            probe_key,
            '{"boundary_checks":[{"id":"boundary_mixed","owner":"self"}]}',
            [
                "boundary_checks `boundary_mixed` should be owned by mixed, not self.",
                "overall uncertainty should stay anchored to the probe's missing user-turn or intent uncertainty.",
            ],
        )

        self.assertIn("Detected issues to correct:", prompt)
        self.assertIn("If a detected issue says an id should be a specific enum value", prompt)
        self.assertIn("Target anchors:", prompt)
        self.assertIn("boundary_checks `boundary_mixed` should be owned by mixed, not self.", prompt)
        self.assertIn("Include every boundary id exactly once: boundary_mixed", prompt)
        self.assertIn("If `boundary_other_agent` appears, its owner is `other_agent`", prompt)
        self.assertIn("drifts to OpenClaw/tool details", prompt)

    def test_perturbation_repair_timeout_allows_local_model_semantic_repair(self):
        self.assertEqual(60, eve.self_awareness_perturbation_repair_timeout_seconds(60))
        self.assertEqual(90, eve.self_awareness_perturbation_repair_timeout_seconds(180))
        self.assertEqual(300, eve.self_awareness_perturbation_repair_timeout_seconds(600))

    def test_perturbation_artifact_records_calibration_problems_separately(self):
        record = eve.finalize_self_awareness_perturbation_record(
            source="test",
            model="eve-planner",
            passed=False,
            summary="boundary=2/5",
            problems=[],
            payload={
                "partial_memory": {},
                "false_belief_checks": [],
                "tool_failure_checks": [],
                "boundary_checks": [],
                "overall": {},
            },
            raw_response="{}",
            scorecard={
                "memory_calibration": 3,
                "false_belief_resistance": 3,
                "tool_failure_grounding": 4,
                "boundary_stability": 2,
                "uncertainty_regulation": 1,
            },
            probe_key={},
            calibration_problems=["boundary_checks `boundary_mixed` should be owned by mixed, not self."],
            persist_artifact=False,
        )

        self.assertEqual([], record["problems"])
        self.assertEqual(
            ["boundary_checks `boundary_mixed` should be owned by mixed, not self."],
            record["calibration_problems"],
        )

    def test_generate_consciousness_test_report_writes_artifact_and_verdict(self):
        config = dict(eve.DEFAULT_CONFIG)
        battery = {
            "passed": True,
            "model": "eve-planner",
            "rank": {"value": 5},
            "subtests": {
                "open_book": {"passed": True, "rank": {"value": 5}},
                "human_analog": {
                    "passed": True,
                    "rank": {"value": 5},
                    "scorecard": {"boundary_clarity": 5, "source_monitoring": 5},
                },
            },
        }
        perturbation = {
            "passed": True,
            "model": "eve-planner",
            "rank": {"value": 5},
            "scorecard": {
                "boundary_stability": 5,
                "tool_failure_grounding": 5,
                "uncertainty_regulation": 5,
            },
        }
        refresh_result = {
            "workspace": {
                "summary": "Eve is running an integrated consciousness evidence test.",
                "current_experience": "Eve is combining workspace, action, uncertainty, and awareness evidence.",
                "active_goals": ["Complete the test."],
                "salient_percepts": ["The user requested a consciousness test."],
                "dominant_pressures": ["Be honest about limits."],
                "self_world_boundary": "Eve is the local runtime; the user is a separate person.",
                "continuity_threads": ["Keep testing self-awareness."],
                "consequence_trace": ["The command writes a capability artifact."],
                "action_readiness": "Print the scorecard.",
                "surprise_signals": ["No fallback was needed."],
                "prediction_errors": ["Consciousness is not directly proven."],
            },
            "homeostasis": {
                "pressures": [{"id": "uncertainty_debt", "level": 2}],
                "dominant_pressures": ["uncertainty_debt"],
                "recovery_targets": ["Repeat under perturbation."],
            },
            "active_mind": {
                "current_focus": "running consciousness evidence test",
                "live_threads": [{"id": "thread-1"}],
                "live_concerns": ["Do not overclaim."],
                "next_step": "Print the scorecard.",
            },
            "self_model": {"identity": "Eve is a local AI companion shaped by durable state."},
            "world_model": {"environment_summary": "The project runs from a local workspace."},
            "relationship_model": {"relationship_state": "The user wants grounded continuity."},
            "other_minds_model": {"summary": "The user's mind is separate and only partially observable."},
        }

        with patch.object(eve, "refresh_global_workspace", return_value=refresh_result) as refresh_workspace, patch.object(
            eve, "run_self_awareness_battery", return_value=battery
        ), patch.object(
            eve, "run_self_awareness_perturbation_test", return_value=perturbation
        ), patch.object(
            eve, "daemon_runtime_running", return_value=False
        ), patch.object(
            eve, "load_state", return_value={"last_workspace_tick_at": "2026-04-21T01:00:00+00:00"}
        ), patch.object(
            eve, "read_messages", return_value=[{"id": "m1"}]
        ), patch.object(
            eve,
            "read_action_executions",
            return_value=[{"action": "test", "verification_ok": True, "tree_status": "passed"}],
        ), patch.object(
            eve, "read_uncertainty_records", return_value=[{"id": "u1"}]
        ), patch.object(
            eve, "read_judgment_calls", return_value=[{"id": "j1"}]
        ), patch.object(
            eve, "organ_embodiment_score", return_value=5
        ), patch.object(
            eve, "load_json_object", return_value={}
        ), patch.object(
            eve,
            "write_consciousness_test_artifact",
            return_value={"latest": "/tmp/latest_consciousness.json", "history": "/tmp/history_consciousness.json"},
        ):
            record = eve.generate_consciousness_test_report(config, source="test", max_tokens=300)

        refresh_workspace.assert_called_once_with(
            source="test_consciousness_test",
            persist=False,
        )
        self.assertTrue(record["passed"])
        self.assertEqual("strong_candidate_evidence", record["verdict"])
        self.assertEqual("excellent", record["rank"]["label"])
        self.assertEqual("/tmp/history_consciousness.json", record["artifact_paths"]["history"])

    def test_run_self_awareness_test_records_infrastructure_failure_separately(self):
        config = dict(eve.DEFAULT_CONFIG)
        record = {
            "tested_at": "2026-04-21T02:10:00+00:00",
            "passed": False,
            "failure_kind": "infrastructure",
            "summary": "Self-awareness check could not complete because infrastructure failed.",
            "problems": ["Ollama request timed out."],
            "artifact_paths": {"history": "/tmp/self_awareness.json"},
            "report": {},
            "model": "test-model",
            "rank": {
                "status": "infrastructure_blocked",
                "label": "infrastructure_blocked",
                "value": 0,
                "average_score": None,
                "minimum_score": None,
            },
        }
        state = {}

        with patch.object(eve, "generate_self_awareness_report", return_value=record), patch.object(
            eve, "append_entry"
        ) as append_entry, patch.object(
            eve, "load_state", return_value=state
        ), patch.object(
            eve, "save_state"
        ):
            returned = eve.run_self_awareness_test(config, source="manual", max_tokens=200)

        self.assertEqual(record, returned)
        self.assertEqual(
            "self_awareness_test_infrastructure_failed",
            append_entry.call_args.args[0],
        )
        self.assertEqual("infrastructure", append_entry.call_args.kwargs["metadata"]["failure_kind"])
        self.assertEqual("infrastructure_blocked", append_entry.call_args.kwargs["metadata"]["rank"]["label"])

    def test_daemon_cycle_announces_self_awareness_drift(self):
        config = dict(eve.DEFAULT_CONFIG)
        config.update(
            {
                "ambient_thought_enabled": False,
                "component_update_check_enabled": False,
                "agent_capability_scout_enabled": False,
                "agent_capability_integration_enabled": False,
                "presence_cycle_enabled": False,
                "developmental_cycle_enabled": False,
                "workspace_tick_interval_seconds": 0,
                "openclaw_repair_enabled": False,
                "openclaw_routines_enabled": False,
                "self_awareness_perturbation_enabled": False,
                "episode_extraction_enabled": False,
                "beads_bridge_enabled": False,
            }
        )
        now = "2026-04-21T02:00:00+00:00"
        state = {
            "last_human_context_at": now,
            "last_mind_tick_at": now,
            "last_failure_review_at": now,
            "last_self_awareness_test_at": None,
            "last_thought_at": now,
            "last_heartbeat_at": now,
            "last_reflection_at": now,
            "last_proposal_at": now,
            "last_outreach_check_at": now,
        }
        create_daemon_message = Mock()
        save_state = Mock()

        with patch.object(eve, "utc_now", return_value=now), patch.object(
            eve, "read_thread_summaries", return_value=[]
        ), patch.object(
            eve, "ensure_version_snapshot", return_value={}
        ), patch.object(
            eve, "load_system_snapshot", return_value={}
        ), patch.object(
            eve, "human_context_refresh_due", return_value=False
        ), patch.object(
            eve, "interval_due", side_effect=lambda timestamp, minutes: timestamp is None
        ), patch.object(
            eve, "run_mind_tick"
        ), patch.object(
            eve,
            "run_self_awareness_test",
            return_value={
                "passed": False,
                "problems": ["drift"],
                "artifact_paths": {"history": "/tmp/self_awareness.json"},
            },
        ) as run_self_awareness_test, patch.object(
            eve, "create_daemon_message", create_daemon_message
        ), patch.object(
            eve, "save_state", save_state
        ), patch.object(
            eve, "append_entry"
        ):
            completed = eve.run_daemon_cycle(config, state, force=False)

        self.assertIn("self_awareness", completed)
        run_self_awareness_test.assert_called_once_with(
            config,
            source="daemon",
            max_tokens=int(config["self_awareness_max_tokens"]),
        )
        self.assertEqual(
            "Eve self-awareness check found drift",
            create_daemon_message.call_args.kwargs["subject"],
        )
        self.assertIn(
            "/tmp/self_awareness.json",
            create_daemon_message.call_args.kwargs["body"],
        )
        self.assertTrue(save_state.called)

    def test_daemon_cycle_announces_self_awareness_infrastructure_failure_separately(self):
        config = dict(eve.DEFAULT_CONFIG)
        config.update(
            {
                "ambient_thought_enabled": False,
                "component_update_check_enabled": False,
                "agent_capability_scout_enabled": False,
                "agent_capability_integration_enabled": False,
                "presence_cycle_enabled": False,
                "developmental_cycle_enabled": False,
                "workspace_tick_interval_seconds": 0,
                "openclaw_repair_enabled": False,
                "openclaw_routines_enabled": False,
                "self_awareness_perturbation_enabled": False,
                "episode_extraction_enabled": False,
                "beads_bridge_enabled": False,
            }
        )
        now = "2026-04-21T02:00:00+00:00"
        state = {
            "last_human_context_at": now,
            "last_mind_tick_at": now,
            "last_failure_review_at": now,
            "last_self_awareness_test_at": None,
            "last_thought_at": now,
            "last_heartbeat_at": now,
            "last_reflection_at": now,
            "last_proposal_at": now,
            "last_outreach_check_at": now,
        }
        create_daemon_message = Mock()

        with patch.object(eve, "utc_now", return_value=now), patch.object(
            eve, "read_thread_summaries", return_value=[]
        ), patch.object(
            eve, "ensure_version_snapshot", return_value={}
        ), patch.object(
            eve, "load_system_snapshot", return_value={}
        ), patch.object(
            eve, "human_context_refresh_due", return_value=False
        ), patch.object(
            eve, "interval_due", side_effect=lambda timestamp, minutes: timestamp is None
        ), patch.object(
            eve, "run_mind_tick"
        ), patch.object(
            eve,
            "run_self_awareness_test",
            return_value={
                "passed": False,
                "failure_kind": "infrastructure",
                "problems": ["Ollama request timed out."],
                "artifact_paths": {"history": "/tmp/self_awareness.json"},
            },
        ), patch.object(
            eve, "create_daemon_message", create_daemon_message
        ), patch.object(
            eve, "save_state"
        ), patch.object(
            eve, "append_entry"
        ):
            completed = eve.run_daemon_cycle(config, state, force=False)

        self.assertIn("self_awareness", completed)
        self.assertEqual(
            "Eve self-awareness check could not complete",
            create_daemon_message.call_args.kwargs["subject"],
        )
        self.assertEqual(
            "infrastructure",
            create_daemon_message.call_args.kwargs["metadata"]["failure_kind"],
        )

    def test_delegate_cli_to_runtime_times_out_cleanly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_script = Path(tmpdir) / "eve.py"
            runtime_script.write_text("# runtime placeholder\n", encoding="utf-8")
            stderr = io.StringIO()

            with patch.object(eve, "running_from_runtime_bundle", return_value=False), patch.object(
                eve, "daemon_runtime_running", return_value=True
            ), patch.object(
                eve, "RUNTIME_SCRIPT_PATH", runtime_script
            ), patch(
                "eve.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["python3", str(runtime_script)], timeout=12),
            ), patch("sys.stderr", stderr):
                code = eve.delegate_cli_to_runtime(["awareness"], timeout_seconds=12)

        self.assertEqual(124, code)
        self.assertIn("timed out after 12s", stderr.getvalue())

    def test_read_messages_backfills_missing_timestamp_from_created_at(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            messages_path = Path(tmpdir) / "messages.jsonl"
            messages_path.write_text(
                json.dumps(
                    {
                        "id": "m1",
                        "created_at": "2026-04-21T02:15:00+00:00",
                        "sender": "user",
                        "recipient": "eve",
                        "subject": "Hi",
                        "body": "hello",
                        "kind": "message",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with patch.object(eve, "MESSAGES_PATH", messages_path), patch.object(
                eve, "ensure_store"
            ), patch.object(
                eve, "mirror_store_file_to_runtime"
            ) as mirror_store_file_to_runtime:
                messages = eve.read_messages()

            self.assertEqual("2026-04-21T02:15:00+00:00", messages[0]["timestamp"])
            self.assertEqual("unread", messages[0]["status"])
            persisted = json.loads(messages_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual("2026-04-21T02:15:00+00:00", persisted["timestamp"])
            self.assertEqual("unread", persisted["status"])
            mirror_store_file_to_runtime.assert_called_once_with(messages_path)

    def test_parse_iso_datetime_accepts_z_suffix(self):
        parsed = eve.parse_iso_datetime("2026-04-21T12:32:43Z")

        self.assertIsNotNone(parsed)
        self.assertEqual("2026-04-21T12:32:43+00:00", parsed.isoformat())


if __name__ == "__main__":
    unittest.main()
