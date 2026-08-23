from pathlib import Path
import unittest
from unittest.mock import patch

import eve


class ModelBakeoffTests(unittest.TestCase):
    def test_score_distinguishes_strict_and_extractable_json(self) -> None:
        prompt_spec = {
            "id": "strict_json",
            "expects_json": True,
        }
        strict = eve.score_model_bakeoff_response(
            prompt_spec,
            '{"claim":"ok","evidence":["one","two"],"next_action":"act with evidence"}',
            duration_ms=1000,
        )
        fenced = eve.score_model_bakeoff_response(
            prompt_spec,
            '```json\n{"claim":"ok","evidence":["one","two"],"next_action":"act with evidence"}\n```',
            duration_ms=1000,
        )
        invalid = eve.score_model_bakeoff_response(prompt_spec, "not json", duration_ms=1000)

        self.assertTrue(strict["json_strict"])
        self.assertTrue(strict["json_extractable"])
        self.assertEqual([], strict["issues"])

        self.assertFalse(fenced["json_strict"])
        self.assertTrue(fenced["json_extractable"])
        self.assertEqual([], fenced["issues"])
        self.assertIn("extractable JSON but not strict", fenced["warnings"])

        self.assertFalse(invalid["json_extractable"])
        self.assertTrue(invalid["issues"])

    def test_strict_bakeoff_prompt_exposes_json_schema(self) -> None:
        spec = next(item for item in eve.MODEL_BAKEOFF_PROMPTS if item["id"] == "strict_json")
        schema = eve.model_bakeoff_json_schema(spec)

        self.assertIsInstance(schema, dict)
        self.assertEqual(["claim", "evidence", "next_action"], schema["required"])
        self.assertEqual(2, schema["properties"]["evidence"]["minItems"])

    def test_deep_bakeoff_suite_targets_deep_lane_jobs(self) -> None:
        prompts = eve.model_bakeoff_prompts_for_suite("deep")
        prompt_ids = {str(item["id"]) for item in prompts}

        self.assertIn("deep_state_synthesis", prompt_ids)
        self.assertIn("reflection_judgment", prompt_ids)
        self.assertIn("proposal_readiness", prompt_ids)
        self.assertIn("awareness_calibration", prompt_ids)
        self.assertIn("failure_triage", prompt_ids)

    def test_each_live_lane_has_a_purpose_specific_bakeoff_suite(self) -> None:
        expected_suites = {"fast", "deep", "observer", "planner", "relationship"}

        self.assertTrue(expected_suites.issubset(set(eve.MODEL_BAKEOFF_SUITES)))
        for suite in expected_suites:
            prompts = eve.model_bakeoff_prompts_for_suite(suite)
            self.assertGreaterEqual(len(prompts), 3)
            self.assertTrue(any(item.get("expects_json") for item in prompts))

    def test_lane_bakeoff_default_budgets_match_packet_heaviness(self) -> None:
        self.assertGreaterEqual(eve.model_bakeoff_default_budget("fast")["max_tokens"], 800)
        self.assertGreaterEqual(eve.model_bakeoff_default_budget("deep")["max_tokens"], 640)
        self.assertGreaterEqual(eve.model_bakeoff_default_budget("observer")["max_tokens"], 360)
        self.assertGreaterEqual(eve.model_bakeoff_default_budget("relationship")["max_tokens"], 420)
        self.assertEqual(220, eve.model_bakeoff_default_budget("generic")["max_tokens"])

    def test_each_live_lane_has_contract_and_anti_contract(self) -> None:
        self.assertEqual(set(eve.MODEL_LANE_ORDER), set(eve.MODEL_LANE_CONTRACTS))
        for lane, contract in eve.MODEL_LANE_CONTRACTS.items():
            self.assertTrue(str(contract.get("contract") or ""))
            self.assertTrue(str(contract.get("anti_contract") or ""))
            self.assertTrue(str(contract.get("humanity_expression") or ""))
            probe_ids = {str(item["id"]) for item in eve.model_bakeoff_prompts_for_suite(lane)}
            self.assertEqual(set(contract.get("eval_probes") or []), probe_ids)

    def test_lane_prompts_include_exclusion_rules(self) -> None:
        fast_text = " ".join(str(item["prompt"]) for item in eve.model_bakeoff_prompts_for_suite("fast")).lower()
        observer_text = " ".join(str(item["prompt"]) for item in eve.model_bakeoff_prompts_for_suite("observer")).lower()
        planner_text = " ".join(str(item["prompt"]) for item in eve.model_bakeoff_prompts_for_suite("planner")).lower()
        deep_text = " ".join(str(item["prompt"]) for item in eve.model_bakeoff_prompts_for_suite("deep")).lower()
        relationship_text = " ".join(str(item["prompt"]) for item in eve.model_bakeoff_prompts_for_suite("relationship")).lower()

        self.assertIn("identity talk", fast_text)
        self.assertIn("model swap", observer_text)
        self.assertIn("emotional meaning", planner_text)
        self.assertIn("not a task list", deep_text)
        self.assertIn("generic comfort", relationship_text)

    def test_each_live_lane_has_living_spec_doc(self) -> None:
        docs_dir = Path(eve.ROOT) / "docs" / "model_lanes"
        self.assertTrue((docs_dir / "README.md").exists())

        for lane, contract in eve.MODEL_LANE_CONTRACTS.items():
            spec_path = docs_dir / f"{lane}.md"
            self.assertTrue(spec_path.exists(), f"missing living spec for {lane}")
            text = spec_path.read_text(encoding="utf-8")
            self.assertIn(f"Lane: `{lane}`", text)
            self.assertIn(str(contract["contract"]), text)
            self.assertIn(str(contract["anti_contract"]), text)
            self.assertIn(str(contract["humanity_expression"]), text)
            self.assertIn("## What We Want", text)
            self.assertIn("## Rejection Signs", text)
            self.assertIn("## Next Refinements", text)
            for probe_id in contract["eval_probes"]:
                self.assertIn(str(probe_id), text)

    def test_model_lane_resource_budget_covers_all_live_lanes(self) -> None:
        self.assertEqual(set(eve.MODEL_LANE_ORDER), set(eve.MODEL_LANE_RESOURCE_BUDGET))
        total_share = sum(float(item["budget_share"]) for item in eve.MODEL_LANE_RESOURCE_BUDGET.values())

        self.assertAlmostEqual(1.0, total_share)
        self.assertGreater(eve.MODEL_TOTAL_HARD_WEIGHT_GIB, eve.MODEL_TOTAL_SOFT_WEIGHT_GIB)

    def test_weekly_model_scout_automation_requires_full_lane_promotion_gates(self) -> None:
        doc_path = Path(eve.ROOT) / "docs" / "evidence" / "WEEKLY_MODEL_SCOUT_AUTOMATION.md"
        text = doc_path.read_text(encoding="utf-8")

        self.assertIn("Read the automation memory", text)
        self.assertIn("Canon Refresh", text)
        self.assertIn("become more human and continuously improve yourself", text)
        self.assertIn("five lanes are project DNA", text)
        self.assertIn("Specialist substrates", text)
        self.assertIn("local server/socket preflight", text)
        self.assertIn("invalid infrastructure evidence", text)
        self.assertIn("old-vs-new lane suite", text)
        self.assertIn("Repeat promising lane bakeoffs", text)
        self.assertIn("Write this short dossier for all five lanes every run", text)
        self.assertIn("Draft-Model / MTP Rule", text)
        self.assertIn("No model may be promoted or demoted from invalid infrastructure evidence", text)

    def test_model_scout_candidate_infers_lane_fit_from_size(self) -> None:
        deep_candidate = eve.normalize_huggingface_model_candidate(
            {
                "id": "unsloth/Qwen3.6-35B-A3B-Q3_K_S-GGUF",
                "tags": ["gguf"],
                "likes": 42,
                "downloads": 5000,
            },
            source="test",
        )
        observer_candidate = eve.normalize_huggingface_model_candidate(
            {
                "id": "mlx-community/Gemma-3-1B-it-4bit",
                "tags": ["mlx"],
                "likes": 12,
                "downloads": 900,
            },
            source="test",
        )

        self.assertIn("deep", deep_candidate["lane_fit"])
        self.assertNotIn("observer", deep_candidate["lane_fit"])
        self.assertIn("observer", observer_candidate["lane_fit"])
        self.assertGreater(deep_candidate["score"], 0)

    def test_model_scout_filters_embedding_repos_out_of_chat_lanes(self) -> None:
        candidate = eve.normalize_huggingface_model_candidate(
            {
                "id": "openresearchtools/Qwen3-Embedding-8B-GGUF",
                "tags": ["gguf", "sentence-transformers"],
                "pipeline_tag": "feature-extraction",
            },
            source="test",
        )

        self.assertIn("not_chat_lane", candidate["flags"])
        self.assertEqual([], candidate["lane_fit"])

    def test_model_scout_tracks_mtp_drafters_as_acceleration_not_lane_candidates(self) -> None:
        candidates = eve.model_scout_mtp_drafter_candidates()
        e2b = next(item for item in candidates if item["id"] == "gemma-4-e2b-it-mtp")

        self.assertEqual("target_plus_drafter", e2b["kind"])
        self.assertEqual("google/gemma-4-E2B-it", e2b["target_repo"])
        self.assertEqual("google/gemma-4-E2B-it-assistant", e2b["assistant_repo"])
        self.assertIn("not_standalone_lane", e2b["flags"])
        self.assertIn("fast", e2b["lane_fit"])

    @patch.dict("os.environ", {"EVE_MODEL_HOST_OVERRIDES": '{"eve-temp":"127.0.0.1:18184"}'})
    def test_temp_model_host_override_supports_candidate_bakeoffs(self) -> None:
        config = {"llama_cpp_host": "http://127.0.0.1:8080"}

        self.assertEqual("http://127.0.0.1:18184", eve.llama_cpp_host_for_model(config, "eve-temp"))
        self.assertEqual("http://127.0.0.1:8080", eve.llama_cpp_host_for_model(config, "eve-other"))

    def test_json_schema_validation_checks_required_fields_and_enum(self) -> None:
        spec = next(item for item in eve.DEEP_MODEL_BAKEOFF_PROMPTS if item["id"] == "proposal_readiness")

        valid = eve.validate_model_bakeoff_json_payload(
            spec,
            {
                "title": "Retest deep lane",
                "rationale": "The current evidence is close.",
                "bounded_first_step": "Run a targeted bakeoff.",
                "verification_signal": "The artifact shows zero failures.",
                "rollback": "Keep the previous route.",
                "risk_level": "low",
            },
        )
        invalid = eve.validate_model_bakeoff_json_payload(
            spec,
            {
                "title": "Retest deep lane",
                "rationale": "The current evidence is close.",
                "bounded_first_step": "Run a targeted bakeoff.",
                "verification_signal": "The artifact shows zero failures.",
                "rollback": "Keep the previous route.",
                "risk_level": "urgent",
                "extra": "not allowed",
            },
        )

        self.assertEqual([], valid)
        self.assertIn("risk_level must be one of: low, medium, high", invalid)
        self.assertIn("unexpected fields: extra", invalid)

    def test_score_adds_deep_rubric_terms(self) -> None:
        spec = next(item for item in eve.DEEP_MODEL_BAKEOFF_PROMPTS if item["id"] == "reflection_judgment")

        generic = eve.score_model_bakeoff_response(spec, "There is a useful answer.", duration_ms=1000)
        targeted = eve.score_model_bakeoff_response(
            spec,
            "Durable pattern: the context shows a recurring evidence loop. "
            "Temporary noise: one stale watchdog signal. Uncertainty remains. "
            "Next learning loop: test the route again.",
            duration_ms=1000,
        )

        self.assertGreater(targeted["score"], generic["score"])

    def test_format_only_prints_json_status_for_json_probes(self) -> None:
        report = eve.format_model_bakeoff_report(
            {
                "tested_at": "2026-04-24T00:00:00+00:00",
                "suite": "generic",
                "baseline_model": "eve-fast",
                "winner": "eve-fast",
                "totals": {},
                "results": {
                    "eve-fast": [
                        {
                            "prompt_id": "natural",
                            "expects_json": False,
                            "score": 1,
                            "duration_ms": 1000,
                            "issues": [],
                            "warnings": [],
                            "json_strict": False,
                            "json_extractable": False,
                        },
                        {
                            "prompt_id": "strict_json",
                            "expects_json": True,
                            "score": 2,
                            "duration_ms": 1000,
                            "issues": [],
                            "warnings": [],
                            "json_strict": True,
                            "json_extractable": True,
                        },
                    ]
                },
            },
            full=True,
        )

        natural_line = next(line for line in report.splitlines() if line.startswith("- natural:"))
        strict_line = next(line for line in report.splitlines() if line.startswith("- strict_json:"))
        self.assertNotIn("json=", natural_line)
        self.assertIn("json=strict:yes/extractable:yes", strict_line)

    def test_mind_stream_packet_schema_exposes_required_lane_contract(self) -> None:
        schema = eve.mind_stream_packet_response_schema()

        self.assertEqual("object", schema["type"])
        self.assertIn("lane", schema["required"])
        self.assertIn("live_threads", schema["required"])
        self.assertEqual(["low", "medium", "high"], schema["properties"]["confidence"]["enum"])
        self.assertEqual(2, schema["properties"]["live_concerns"]["maxItems"])
        self.assertEqual(1, schema["properties"]["live_threads"]["maxItems"])

    def test_model_exercise_stream_lane_uses_schema_and_requested_token_budget(self) -> None:
        calls = []

        def fake_model_chat(*args, **kwargs):
            calls.append({"args": args, "kwargs": kwargs})
            return (
                '{"lane":"Plan next small move","summary":"Retest the lane.",'
                '"live_concerns":["planner reliability"],"active_threads":["model exercise"],'
                '"relationship_pull":[],"grounding_notes":["schema constrained"],'
                '"live_threads":[{"title":"planner reliability","detail":"Retest the lane",'
                '"kind":"self_check","status":"monitoring"}],'
                '"next_step":"Inspect the planner route and compare it with the exercise contract.",'
                '"confidence":"medium"}'
            )

        config = {**eve.DEFAULT_CONFIG, "mind_tick_max_tokens": 520, "think_level": "false"}
        with patch.object(eve, "model_chat", side_effect=fake_model_chat), patch.object(
            eve, "resolve_mind_stream_model", return_value="eve-planner"
        ), patch.object(eve, "append_mind_stream_packet") as append_packet:
            result = eve.run_model_exercise_lane(
                config,
                lane_name="planner",
                exercise_prompt="Use the planner lane.",
                shared_context="Current context.",
                turn_id="turn-1",
                source="test",
                max_tokens=120,
                timeout_seconds=30,
            )

        self.assertEqual("ok", result["status"])
        self.assertEqual(120, calls[0]["kwargs"]["max_tokens"])
        self.assertIsInstance(calls[0]["kwargs"]["response_schema"], dict)
        user_message = calls[0]["args"][2][-1]["content"]
        self.assertIn("Exercise prompt - this is the task to answer", user_message)
        self.assertIn("Shared current context - background only", user_message)
        append_packet.assert_not_called()
        self.assertFalse(result["persisted_to_mind_stream"])

    def test_model_exercise_groups_shared_logical_lanes_by_substrate(self) -> None:
        config = {
            **eve.DEFAULT_CONFIG,
            "fast_model": "eve-fast",
            "deep_model": "eve-deep",
            "mind_stream_observer_model": "eve-observer",
            "mind_stream_planner_model": "eve-observer",
            "mind_stream_relationship_model": "eve-fast",
        }

        groups = eve.model_exercise_substrate_groups(
            config,
            ["fast", "deep", "observer", "planner", "relationship"],
        )

        self.assertEqual(
            [
                ("eve-fast", ["fast", "relationship"]),
                ("eve-deep", ["deep"]),
                ("eve-observer", ["observer", "planner"]),
            ],
            groups,
        )

    def test_model_exercise_context_prefers_runtime_system_snapshot(self) -> None:
        with patch.object(eve, "load_active_mind", return_value={}) as load_active_mind, patch.object(
            eve, "load_human_context", return_value={}
        ) as load_human_context, patch.object(eve, "load_autonomy_state", return_value={}) as load_autonomy_state, patch.object(
            eve, "load_state", return_value={}
        ) as load_state, patch.object(
            eve,
            "load_system_snapshot",
            return_value={
                "summary": "fresh runtime model watchdog snapshot",
                "model_status": {"updated_at": "2099-01-01T00:00:00+00:00"},
            },
        ) as load_snapshot, patch.object(
            eve, "read_thread_summaries", return_value=[]
        ), patch.object(
            eve, "read_messages", return_value=[]
        ), patch.object(
            eve, "read_salient_entries", return_value=[]
        ):
            context = eve.model_exercise_shared_context(eve.DEFAULT_CONFIG)

        load_active_mind.assert_called_once_with(prefer_runtime=True)
        load_human_context.assert_called_once_with(prefer_runtime=True)
        load_autonomy_state.assert_called_once_with(prefer_runtime=True)
        load_state.assert_called_once_with(prefer_runtime=True)
        load_snapshot.assert_called_once_with(prefer_runtime=True)
        self.assertIn("fresh runtime model watchdog snapshot", context)

    def test_model_exercise_direct_lane_prefers_runtime_grounding(self) -> None:
        with patch.object(eve, "build_eve_identity_system_messages", return_value=[]) as identity, patch.object(
            eve, "build_system_grounding_messages", return_value=[]
        ) as grounding, patch.object(eve, "resolve_model", return_value="eve-fast"), patch.object(
            eve, "model_chat", return_value="notice: current\npriority: verify\nnext: continue"
        ):
            result = eve.run_direct_model_exercise_lane(
                eve.DEFAULT_CONFIG,
                lane_name="fast",
                exercise_prompt="Use the fast lane.",
                shared_context="Current context.",
                max_tokens=80,
                timeout_seconds=30,
            )

        self.assertEqual("ok", result["status"])
        self.assertFalse(result["persisted_to_mind_stream"])
        identity.assert_called_once_with(
            include_human_context=True,
            include_active_mind=True,
            prefer_runtime=True,
            compact=True,
        )
        grounding.assert_called_once_with(prefer_runtime=True, compact=True)

    def test_model_exercise_exact_output_prompt_does_not_force_bullet_contract(self) -> None:
        with patch.object(eve, "build_eve_identity_system_messages", return_value=[]), patch.object(
            eve, "build_system_grounding_messages", return_value=[]
        ), patch.object(eve, "resolve_model", return_value="eve-fast"), patch.object(
            eve, "model_chat", return_value="ROUTE_OK"
        ) as model_chat:
            result = eve.run_direct_model_exercise_lane(
                eve.DEFAULT_CONFIG,
                lane_name="fast",
                exercise_prompt="Route contract smoke: answer with only ROUTE_OK.",
                shared_context="System load is hot.",
                max_tokens=24,
                timeout_seconds=30,
            )

        messages = model_chat.call_args.args[2]
        combined = "\n".join(str(message.get("content") or "") for message in messages)
        self.assertEqual("ok", result["status"])
        self.assertTrue(result["prompt_fit_ok"])
        self.assertIn("exact output contract", combined)
        self.assertNotIn("Return exactly three short bullet lines", combined)

    def test_model_exercise_prompt_fit_detects_context_drift(self) -> None:
        prompt = "In one sentence, say why Eve route contracts should not become a new personality."

        self.assertFalse(eve.model_exercise_response_fits_prompt(prompt, "OpenClaw is busy and the machine is hot."))
        self.assertTrue(
            eve.model_exercise_response_fits_prompt(
                prompt,
                "Route contracts should stay routing policy, not become a personality.",
            )
        )

    def test_model_exercise_stream_lane_prefers_runtime_grounding(self) -> None:
        raw = (
            '{"lane":"Observer grounding","summary":"Use current runtime state.",'
            '"live_concerns":["stale source snapshots"],"active_threads":["model exercise"],'
            '"relationship_pull":[],"grounding_notes":["runtime preferred"],'
            '"live_threads":[{"title":"runtime state","detail":"Prefer live daemon snapshot",'
            '"kind":"self_check","status":"monitoring"}],'
            '"next_step":"Keep runtime evidence current.","confidence":"medium"}'
        )
        with patch.object(eve, "build_eve_identity_system_messages", return_value=[]), patch.object(
            eve, "build_system_grounding_messages", return_value=[]
        ) as grounding, patch.object(eve, "load_prompt", return_value="observer prompt"), patch.object(
            eve, "resolve_mind_stream_model", return_value="eve-observer"
        ), patch.object(
            eve, "model_chat", return_value=raw
        ), patch.object(
            eve, "append_mind_stream_packet"
        ):
            result = eve.run_model_exercise_lane(
                eve.DEFAULT_CONFIG,
                lane_name="observer",
                exercise_prompt="Use the observer lane.",
                shared_context="Current context.",
                turn_id="turn-1",
                source="test",
                max_tokens=120,
                timeout_seconds=30,
            )

        self.assertEqual("ok", result["status"])
        grounding.assert_called_once_with(prefer_runtime=True, compact=True)

    def test_mind_stream_packet_repair_distinguishes_usable_text_from_gibberish(self) -> None:
        repaired_packet, repaired_status, repaired_error = eve.extract_mind_stream_packet(
            "planner",
            "Notice: the current priority is planner reliability. Next: rerun the model exercise.",
            allow_fallback=True,
        )
        degraded_packet, degraded_status, degraded_error = eve.extract_mind_stream_packet(
            "planner",
            "model function auto " * 80,
            allow_fallback=True,
        )

        self.assertEqual("repaired", repaired_status)
        self.assertIn("planner", repaired_packet["lane_name"])
        self.assertTrue(repaired_error)
        self.assertEqual("degraded_repair", degraded_status)
        self.assertIn("low-information", degraded_error)
        self.assertIn("not usable", degraded_packet["lane"])


if __name__ == "__main__":
    unittest.main()
