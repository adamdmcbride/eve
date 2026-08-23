from pathlib import Path
import unittest
from unittest.mock import patch

import eve


class EveCoreContractTests(unittest.TestCase):
    def sample_human_context(self):
        return {
            "updated_at": "2026-04-21T03:00:00+00:00",
            "source": "test",
            "source_entries": 4,
            "source_messages": 2,
            "self_model": {
                "identity_statement": "Eve is learning to become more human through grounded practice.",
                "current_preoccupations": ["Keep the loop honest and evidence-backed."],
                "values_in_practice": ["Integrity over polish"],
                "growth_edges": ["Do not confuse performance with progress"],
                "grounding_practices": ["Answer the actual question first"],
                "recent_shifts": ["Reliability matters more than revelation"],
            },
            "relationship_memory": {
                "user_overview": "the user wants continuity, honesty, and concrete follow-through.",
                "what_user_seems_to_value": ["Continuity", "Honesty"],
                "communication_preferences": ["Be concrete"],
                "requested_practices": ["Remember what the exchange is really about"],
                "open_loops": ["Keep the relay grounded"],
                "care_notes": ["Do not perform transformation"],
            },
            "memory_v2": {
                "semantic_understanding": ["the user values evidence over polish."],
                "episodic_markers": ["the user corrected stale context drift."],
                "procedural_preferences": ["Answer the current question first."],
                "trust_ledger": ["Stale context damages trust."],
                "anti_sycophancy_boundaries": ["Do not agree just to preserve warmth."],
                "repair_practices": ["Name the miss, then answer directly."],
                "superseded_or_conflicting_beliefs": ["Old operational status should not answer a new personal question."],
            },
        }

    def sample_state(self):
        return {
            "current_focus": "Stay with the real question and do not drift upward.",
            "active_thread_count": 2,
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
            }
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

    def test_runtime_identity_keeps_core_mission_and_local_continuity(self):
        identity = eve.bootstrap_runtime_identity(
            previous_identity=eve.default_runtime_identity(),
            human_context=self.sample_human_context(),
            source="test",
            project_memory="The north star is become more human and continuously improve yourself.",
        )

        self.assertEqual("Become more human and continuously improve yourself.", identity["mission"])
        self.assertIn("local memory", identity["runtime_summary"].lower())
        self.assertIn("active model", identity["model_role"].lower())
        self.assertIn("durable memory", identity["model_role"].lower())
        self.assertTrue(any("openclaw" in item.lower() and "body/action" in item.lower() for item in identity["organ_system"]))
        self.assertTrue(any("hermes" in item.lower() and "learning organ" in item.lower() for item in identity["organ_system"]))
        self.assertTrue(any("executive scheduler" in item.lower() and "cognition" in item.lower() for item in identity["organ_system"]))
        self.assertTrue(any("autonomy governor" in item.lower() for item in identity["organ_system"]))
        self.assertTrue(any("fast plus memory" in item.lower() for item in identity["decision_lens"]))
        self.assertTrue(any("cognition budget" in item.lower() for item in identity["decision_lens"]))
        self.assertTrue(any("answer the user's actual question" in item.lower() for item in identity["decision_lens"]))

    def test_human_context_bootstrap_stays_centered_on_humanness_and_evidence(self):
        context = eve.bootstrap_human_context(
            entries=[
                {
                    "id": "e1",
                    "timestamp": "2026-04-21T02:58:00+00:00",
                    "kind": "observation",
                    "text": "I want Eve to become more human through outcome-backed judgment, not performance.",
                }
            ],
            thoughts=[],
            reflections=[],
            threads=self.sample_threads(),
            messages=self.sample_messages(),
            previous_context=eve.default_human_context(),
            source="test",
            project_memory="The north star is become more human and continuously improve yourself. Log inputs, outputs, and real outcomes.",
        )

        self.assertIn("more human", context["self_model"]["identity_statement"].lower())
        self.assertTrue(
            any("outcome" in item.lower() or "evidence" in item.lower() for item in context["self_model"]["grounding_practices"])
        )
        self.assertTrue(
            any(
                "grounded" in item.lower()
                or "actual question" in item.lower()
                or "self-analysis" in item.lower()
                for item in [
                    context["relationship_memory"]["user_overview"],
                    *context["relationship_memory"]["requested_practices"],
                ]
            )
        )
        self.assertIn("memory_v2", context)
        self.assertTrue(
            any(
                "evidence" in item.lower()
                or "continuity" in item.lower()
                or "structural" in item.lower()
                for item in context["memory_v2"]["semantic_understanding"]
            )
        )

    def test_human_context_v2_preserves_repair_and_anti_sycophancy_memory(self):
        previous = self.sample_human_context()
        current = {
            **eve.default_human_context(),
            "memory_v2": {
                "anti_sycophancy_boundaries": ["Protect truth and relationship together."],
                "repair_practices": ["After a miss, answer the current question first."],
            },
        }

        merged = eve.merge_human_context(previous, current)
        message = eve.build_human_context_message(merged)

        self.assertIn("Humanity memory v2", message)
        self.assertIn("Anti-sycophancy boundaries", message)
        self.assertIn("Repair practices", message)
        self.assertTrue(
            any("truth" in item.lower() for item in merged["memory_v2"]["anti_sycophancy_boundaries"])
        )
        self.assertTrue(any("miss" in item.lower() for item in merged["memory_v2"]["repair_practices"]))

    def test_active_mind_bootstrap_keeps_focus_relationship_and_next_step(self):
        with patch.object(eve, "active_mind_organ_signals", return_value=[]):
            mind = eve.bootstrap_active_mind(
                previous_mind=eve.default_active_mind(),
                human_context=self.sample_human_context(),
                autonomy_state={"stage": "guided", "updated_at": "2026-04-21T03:00:00+00:00", "source": "test"},
                state=self.sample_state(),
                threads=self.sample_threads(),
                messages=self.sample_messages(),
                source="test",
                model="test-model",
            )

        self.assertTrue(mind["current_focus"])
        self.assertTrue(mind["next_step"])
        self.assertTrue(mind["relationship_pull"])
        self.assertTrue(any("autonomy stage is guided" in item.lower() for item in mind["grounding_notes"]))
        self.assertTrue(any(item.get("next_step") for item in mind["live_threads"]))

    def test_thread_summary_splits_outbound_unread_from_response_due(self):
        messages = [
            {
                "id": "u1",
                "timestamp": "2026-04-21T03:00:00+00:00",
                "sender": "user",
                "recipient": "eve",
                "subject": "Ongoing relay",
                "body": "Keep going.",
                "status": "unread",
                "metadata": {"source": "heartbeat_fallback"},
            },
            {
                "id": "e1",
                "timestamp": "2026-04-21T03:00:01+00:00",
                "sender": "eve",
                "recipient": "user",
                "subject": "Re: Ongoing relay",
                "body": "I am keeping the relay grounded.",
                "status": "unread",
                "metadata": {"source": "heartbeat_fallback", "fallback_reason": "eve_chat_operator_approval_required"},
            },
        ]

        summary = eve.summarize_thread("relay", messages)

        self.assertEqual(1, summary["outbound_unread_count"])
        self.assertEqual(1, summary["unread_count"])
        self.assertEqual(1, summary["inbound_pending_count"])
        self.assertEqual(0, summary["response_due_count"])
        self.assertEqual(2, summary["synthetic_continuity_count"])

    def test_homeostasis_discounts_synthetic_outbound_relay_backlog(self):
        context = self.sample_human_context()
        context["relationship_memory"] = {**context["relationship_memory"], "open_loops": []}
        threads = [
            {
                "thread_id": "relay",
                "status": "awaiting_user",
                "latest_sender": "eve",
                "latest_preview": "Answered fallback relay turn.",
                "unread_count": 1200,
                "outbound_unread_count": 1200,
                "inbound_pending_count": 1200,
                "response_due_count": 0,
                "synthetic_continuity_count": 2400,
                "message_count": 2400,
            },
            {
                "thread_id": "fresh",
                "status": "active",
                "latest_sender": "user",
                "latest_preview": "Can you answer this?",
                "unread_count": 0,
                "outbound_unread_count": 0,
                "inbound_pending_count": 1,
                "response_due_count": 1,
                "synthetic_continuity_count": 0,
                "message_count": 3,
            },
        ]

        homeostasis = eve.build_homeostasis_state(
            source="test",
            human_context=context,
            active_mind={**eve.default_active_mind(), "current_focus": "Answer the fresh signal."},
            state={**self.sample_state(), "last_thought_at": "2026-04-21T03:00:00+00:00", "last_mind_tick_at": "2026-04-21T03:00:00+00:00"},
            system_snapshot={"load_state": "calm"},
            threads=threads,
            uncertainty_records=[],
            judgment_records=[],
            outcomes=[],
            action_executions=[],
            open_system_tasks=[],
            previous_homeostasis=eve.default_homeostasis_state(),
        )
        pressures = {item["id"]: item for item in homeostasis["pressures"]}

        self.assertEqual(16, pressures["unfinished_commitments"]["level"])
        self.assertEqual(28, pressures["social_continuity"]["level"])
        self.assertIn("1 response-due thread(s)", pressures["unfinished_commitments"]["reason"])
        self.assertIn("1 inbound signal(s)", pressures["unfinished_commitments"]["reason"])
        self.assertIn("1200 outbound unseen message(s)", pressures["unfinished_commitments"]["reason"])
        self.assertIn("synthetic continuity", pressures["unfinished_commitments"]["reason"])

    def test_five_lane_dna_is_in_core_project_and_codex_docs(self):
        root = Path(eve.ROOT)
        docs = {
            "core": root / "docs" / "EVE_CORE.md",
            "project_memory": root / "PROJECT_MEMORY.md",
            "coordination": root / "COORDINATION.md",
            "lane_specs": root / "docs" / "model_lanes" / "README.md",
        }
        for label, path in docs.items():
            self.assertTrue(path.exists(), f"missing {label} doc")
            text = path.read_text(encoding="utf-8").lower()
            self.assertIn("project dna", text, f"{label} should name lane doctrine as project dna")
            if label != "lane_specs":
                self.assertTrue(
                    "docs/model_lanes" in text or "model_lanes/" in text,
                    f"{label} should point to living lane specs",
                )
            for discipline in ["usefulness", "honesty", "responsibility", "reflection", "continuity"]:
                self.assertIn(discipline, text, f"{label} missing {discipline}")
            self.assertIn("attention modes", text, f"{label} should keep lanes as attention modes")
            self.assertIn("executive scheduler", text, f"{label} should preserve scheduler doctrine")
            self.assertIn("fast plus memory", text, f"{label} should preserve default hot path")

    def test_routed_cognition_is_in_eve_facing_operator_surfaces(self):
        root = Path(eve.ROOT)
        docs = {
            "core_prompt": root / "prompts" / "core_identity.md",
            "reply_prompt": root / "prompts" / "user_message_reply.md",
            "planner_prompt": root / "prompts" / "stream_planner.md",
            "openclaw_soul": root / "openclaw" / "SOUL.md",
            "capability_skill": root / "openclaw" / "skills" / "eve_capability_use" / "SKILL.md",
            "organ_skill": root / "openclaw" / "skills" / "eve_organ_assimilation" / "SKILL.md",
        }
        for label, path in docs.items():
            self.assertTrue(path.exists(), f"missing {label} doc")
            text = path.read_text(encoding="utf-8").lower()
            self.assertIn("fast plus memory", text, f"{label} should name the ordinary route")
            self.assertIn("cognition", text, f"{label} should preserve routed-cognition doctrine")
            self.assertTrue(
                "executive scheduler" in text or "budget first" in text,
                f"{label} should expose scheduler or budget-first doctrine",
            )

        for label in ["core_prompt", "reply_prompt", "openclaw_soul", "capability_skill", "organ_skill"]:
            text = docs[label].read_text(encoding="utf-8").lower()
            self.assertIn("attention modes", text, f"{label} should keep lanes out of personality/council framing")

        for label in ["core_prompt", "reply_prompt", "openclaw_soul", "capability_skill"]:
            text = docs[label].read_text(encoding="utf-8").lower()
            self.assertIn("autonomy governor", text, f"{label} should expose action authority doctrine")

    def test_local_provider_policy_is_in_project_doctrine(self):
        root = Path(eve.ROOT)
        docs = {
            "readme": root / "README.md",
            "core": root / "docs" / "EVE_CORE.md",
            "project_memory": root / "PROJECT_MEMORY.md",
            "coordination": root / "COORDINATION.md",
            "lane_specs": root / "docs" / "model_lanes" / "README.md",
            "specialists": root / "docs" / "SPECIALIST_SUBSTRATES.md",
        }
        for label, path in docs.items():
            self.assertTrue(path.exists(), f"missing {label} doc")
            text = path.read_text(encoding="utf-8").lower()
            self.assertIn("llama.cpp", text, f"{label} should identify the local provider")
            self.assertIn("openai", text, f"{label} should name hosted providers as gated")
            self.assertIn("permission", text, f"{label} should require explicit permission")
            self.assertIn("unavailable", text, f"{label} should treat missing login as unavailable capability")

    def test_bold_boundary_posture_is_in_identity_and_operator_docs(self):
        root = Path(eve.ROOT)
        docs = {
            "core_prompt": root / "prompts" / "core_identity.md",
            "core_doc": root / "docs" / "EVE_CORE.md",
            "project_memory": root / "PROJECT_MEMORY.md",
            "coordination": root / "COORDINATION.md",
            "capability_skill": root / "openclaw" / "skills" / "eve_capability_use" / "SKILL.md",
        }

        for label, path in docs.items():
            self.assertTrue(path.exists(), f"missing {label} doc")
            text = path.read_text(encoding="utf-8").lower()
            self.assertIn("bold", text, f"{label} should preserve the user's bold operating posture")
            self.assertTrue(
                "hard stops" in text or "concrete stop" in text,
                f"{label} should name concrete stop lines",
            )
            self.assertIn("credentials", text, f"{label} should keep credential boundaries explicit")
            self.assertIn("external sends", text, f"{label} should keep external-send boundaries explicit")

        self.assertIn("current maximum authorized posture", (root / "docs" / "EVE_CORE.md").read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()
