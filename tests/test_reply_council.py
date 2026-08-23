import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import eve
import eve_epistemic


class ReplyCouncilTests(unittest.TestCase):
    def config(self):
        config = dict(eve.DEFAULT_CONFIG)
        config.update(
            {
                "model_backend": "llama_cpp",
                "fast_model_backend": "llama_cpp",
                "deep_model_backend": "llama_cpp",
                "fast_model": "eve-fast",
                "deep_model": "eve-deep",
                "mind_stream_observer_model": "eve-observer",
                "mind_stream_planner_model": "eve-planner",
                "mind_stream_relationship_model": "eve-relationship",
            }
        )
        return config

    def test_simple_question_evaluates_without_forcing_streams(self):
        with patch.object(eve, "reply_lane_learning_adjustments", return_value={}):
            council = eve.build_reply_council_state(
                self.config(),
                "What is 2+2?",
                reply_posture="general",
                allow_tools=False,
            )

        self.assertTrue(council["evaluated"])
        self.assertFalse(eve.reply_council_should_run_streams(council))
        self.assertEqual([], council["active_lanes"])
        self.assertEqual("only fast lane pressure was high enough", council["reason"])

    def test_fast_lane_learning_cannot_disable_direct_answer_path(self):
        with patch.object(eve, "reply_lane_learning_adjustments", return_value={"fast": -0.2}):
            council = eve.build_reply_council_state(
                self.config(),
                "What is 2+2?",
                reply_posture="general",
                allow_tools=False,
            )

        self.assertEqual([], council["active_lanes"])
        self.assertEqual("only fast lane pressure was high enough", council["reason"])
        self.assertTrue(eve.reply_council_fast_direct_admitted(council))

    def test_fast_direct_path_cannot_bypass_an_admitted_observer(self):
        council = {
            "enabled": True,
            "evaluated": True,
            "allow_tools": False,
            "active_lanes": ["fast", "observer"],
            "lanes": [
                {"lane": "fast", "pressure": 0.8, "threshold": 0.55, "quarantined": False},
                {"lane": "observer", "pressure": 0.7, "threshold": 0.55, "quarantined": False},
            ],
        }

        self.assertFalse(eve.reply_council_fast_direct_admitted(council))

    def test_architecture_question_selects_relevant_lanes(self):
        council = eve.build_reply_council_state(
            self.config(),
            "How do we replicate human consciousness with multiple thought streams? Create a roadmap and do it.",
            reply_posture="relational",
            allow_tools=False,
        )

        self.assertTrue(eve.reply_council_should_run_streams(council))
        self.assertIn("fast", council["active_lanes"])
        self.assertIn("deep", council["active_lanes"])
        self.assertIn("planner", council["active_lanes"])
        self.assertIn("relationship", council["active_lanes"])

    def test_current_inner_state_uses_one_primary_even_with_noisy_epistemic_labels(self):
        noisy_frame = {
            "status": "available",
            "model_id": "noisy-test-frame",
            "signal_labels": ["missing_context", "external_source", "external_preference"],
            "flags": {"deep_revision": True},
        }
        with patch.object(eve, "reply_lane_learning_adjustments", return_value={}):
            council = eve.build_reply_council_state(
                self.config(),
                "What's on your mind? This is about you, not me.",
                reply_posture="relational",
                allow_tools=False,
                epistemic_frame_override=noisy_frame,
            )

        self.assertEqual(["fast"], council["active_lanes"])
        self.assertFalse(eve.reply_council_should_run_streams(council))
        self.assertIn("single-primary", council["reason"])

    def test_three_substrate_topology_preserves_five_logical_lane_routes(self):
        config = self.config()
        config["_model_lane_topology_mode"] = "three_substrate"

        topology = eve.model_lane_topology_snapshot(config)

        self.assertEqual("three_substrate", topology["mode"])
        self.assertEqual(5, topology["logical_lane_count"])
        self.assertEqual(3, topology["substrate_count"])
        routes = {
            item["logical_lane"]: item for item in topology["routes"]
        }
        self.assertEqual("eve-fast", routes["fast"]["substrate_model"])
        self.assertEqual("eve-fast", routes["relationship"]["substrate_model"])
        self.assertEqual("eve-observer", routes["observer"]["substrate_model"])
        self.assertEqual("eve-observer", routes["planner"]["substrate_model"])
        self.assertEqual("eve-deep", routes["deep"]["substrate_model"])
        self.assertEqual(
            {"fast", "relationship"},
            set(routes["relationship"]["shared_lanes"]),
        )
        self.assertEqual(
            {"observer", "planner"},
            set(routes["planner"]["shared_lanes"]),
        )

    def test_three_substrate_council_keeps_lane_and_substrate_attribution_separate(self):
        config = self.config()
        config["_model_lane_topology_mode"] = "three_substrate"
        with patch.object(eve, "reply_lane_learning_adjustments", return_value={}):
            council = eve.build_reply_council_state(
                config,
                "Privately compare this difficult decision.",
                reply_posture="practical",
                allow_tools=False,
                conscious_state_override={},
                evaluator_force_lanes=eve.REPLY_COUNCIL_LANE_ORDER,
            )

        self.assertEqual(list(eve.REPLY_COUNCIL_LANE_ORDER), council["active_lanes"])
        self.assertEqual(3, council["model_topology"]["substrate_count"])
        lanes = {item["lane"]: item for item in council["lanes"]}
        self.assertEqual("eve-fast", lanes["relationship"]["model"])
        self.assertEqual("eve-relationship", lanes["relationship"]["nominal_model"])
        self.assertEqual("fast", lanes["relationship"]["substrate_profile"])
        self.assertEqual("eve-observer", lanes["planner"]["model"])
        self.assertEqual("eve-planner", lanes["planner"]["nominal_model"])
        self.assertEqual("observer", lanes["planner"]["substrate_profile"])
        specs = eve.reply_council_stream_specs(config, council)
        self.assertEqual(
            {
                "fast": "eve-fast",
                "observer": "eve-observer",
                "planner": "eve-observer",
                "deep": "eve-deep",
                "relationship": "eve-fast",
            },
            {lane: model for lane, _, model in specs},
        )

    def test_three_substrate_architecture_snapshot_reports_three_endpoints(self):
        config = self.config()
        config["_model_lane_topology_mode"] = "three_substrate"

        snapshot = eve.build_architecture_self_model_snapshot(config)

        deployment = snapshot["configured_deployment"]
        self.assertEqual("three_substrate", deployment["topology_mode"])
        self.assertEqual(5, deployment["route_count"])
        self.assertEqual(3, deployment["endpoint_count"])
        self.assertEqual(3, deployment["substrate_count"])
        self.assertIn("three shared resident model substrates", snapshot["physical_topology"])

    def test_shared_substrate_failure_is_attributed_to_both_affected_faculties(self):
        config = self.config()
        config["_model_lane_topology_mode"] = "three_substrate"

        def quarantine(model, prefer_runtime=True):
            return {
                "active": model == "eve-observer",
                "reason": "injected shared-substrate outage",
                "quarantined_until": "later",
            }

        with (
            patch.object(eve, "reply_lane_learning_adjustments", return_value={}),
            patch.object(eve, "reply_model_quarantine_status", side_effect=quarantine),
        ):
            council = eve.build_reply_council_state(
                config,
                "Privately compare this difficult decision.",
                reply_posture="practical",
                allow_tools=False,
                conscious_state_override={},
                evaluator_force_lanes=eve.REPLY_COUNCIL_LANE_ORDER,
            )

        lanes = {item["lane"]: item for item in council["lanes"]}
        self.assertTrue(lanes["observer"]["quarantined"])
        self.assertTrue(lanes["planner"]["quarantined"])
        self.assertEqual("evaluator-unavailable", lanes["observer"]["stance"])
        self.assertEqual("evaluator-unavailable", lanes["planner"]["stance"])
        self.assertNotIn("observer", council["active_lanes"])
        self.assertNotIn("planner", council["active_lanes"])
        self.assertEqual(
            {"fast", "deep", "relationship"},
            set(council["active_lanes"]),
        )

    def test_substrate_plan_groups_shared_lanes_and_respects_server_capacity(self):
        config = self.config()
        config["_model_lane_topology_mode"] = "three_substrate"
        config["llama_cpp_parallel_slots"] = 2
        models = {
            "fast": "eve-fast",
            "relationship": "eve-fast",
            "observer": "eve-observer",
            "planner": "eve-observer",
            "deep": "eve-deep",
        }

        plan = eve.reply_stream_substrate_plan(config, models)
        by_model = {item["model"]: item for item in plan}

        self.assertEqual(3, len(plan))
        self.assertEqual({"fast", "relationship"}, set(by_model["eve-fast"]["streams"]))
        self.assertEqual({"observer", "planner"}, set(by_model["eve-observer"]["streams"]))
        self.assertEqual(2, by_model["eve-fast"]["parallel_capacity"])
        self.assertEqual(1, by_model["eve-observer"]["parallel_capacity"])
        self.assertTrue(eve.reply_stream_parallel_enabled(config, models))

    def test_current_lane_count_question_uses_authoritative_self_model(self):
        prompt = "Does Eve need all these lanes, need more, or need less?"

        self.assertTrue(eve.reply_requests_architecture_self_model(prompt))
        self.assertFalse(
            eve.reply_requests_architecture_self_model(
                "Should this database architecture use fewer worker queues?"
            )
        )
        contract = eve.build_reply_turn_contract(
            {"id": "m1", "body": prompt},
            prompt,
            [],
            reply_posture="practical",
        )
        snapshot = contract["architecture_self_model_snapshot"]
        self.assertEqual("architecture_self_model", contract["intent"])
        self.assertEqual(1, snapshot["identity_count"])
        self.assertEqual(5, snapshot["logical_faculty_count"])
        self.assertIn("five logical function contracts", snapshot["current_count_decision"])
        self.assertIn("admit them sparsely", snapshot["current_count_decision"])
        self.assertIn("matched packet lesions", snapshot["faculty_evidence_status"])
        self.assertIn("longitudinal", snapshot["physical_topology_next_test"])
        self.assertEqual(
            "passed_promoted",
            snapshot["physical_topology_live_evidence"]["status"],
        )
        self.assertFalse(contract["requires_current_tool_evidence"])
        self.assertEqual(5, snapshot["configured_deployment"]["route_count"])
        self.assertEqual(3, snapshot["configured_deployment"]["endpoint_count"])
        self.assertEqual(
            "three_substrate", snapshot["configured_deployment"]["topology_mode"]
        )
        self.assertEqual(
            list(eve.REPLY_COUNCIL_LANE_ORDER),
            [item["lane"] for item in snapshot["faculties"]],
        )
        system_message = eve.reply_turn_contract_system_message(contract)
        for lane in eve.REPLY_COUNCIL_LANE_ORDER:
            self.assertIn(lane, system_message)
        self.assertIn("executive scheduler", system_message)
        self.assertIn("Physical topology", system_message)
        self.assertIn("Current faculty evidence", system_message)
        self.assertIn("Current count decision", system_message)
        self.assertIn("Next physical-topology test", system_message)
        terminal_message = eve.architecture_self_model_terminal_message(snapshot)
        self.assertIn("one integrated identity", terminal_message.lower())
        self.assertIn("must begin with `I`", terminal_message)
        self.assertIn("Use `retain` rather than `need`", terminal_message)
        self.assertIn("Do not say all five are proved necessary", terminal_message)
        self.assertIn("promoted three resident substrates", terminal_message)
        self.assertIn("longitudinal shared-contention", terminal_message)
        self.assertIn("first person", terminal_message)

    def test_current_lane_count_question_admits_grounding_and_integration(self):
        with patch.object(eve, "reply_lane_learning_adjustments", return_value={}):
            council = eve.build_reply_council_state(
                self.config(),
                "Does Eve need all these lanes, need more, or need less?",
                reply_posture="practical",
                allow_tools=False,
                conscious_state_override={},
            )

        self.assertEqual(
            {"fast", "observer", "deep"},
            set(council["active_lanes"]),
        )
        self.assertTrue(eve.reply_council_should_run_streams(council))
        observer = next(item for item in council["lanes"] if item["lane"] == "observer")
        deep = next(item for item in council["lanes"] if item["lane"] == "deep")
        self.assertIn(
            "current architecture topology requires grounded self-observation",
            observer["reasons"],
        )
        self.assertIn(
            "architecture topology requires integration judgment",
            deep["reasons"],
        )

    def test_architecture_quality_guard_rejects_invented_topology(self):
        prompt = "Does Eve need all these lanes, need more, or need less?"
        good = (
            "I should keep five logical faculties for now: fast, observer, planner, deep, and relationship. "
            "They are attention functions in one mind, coordinated by my recurrent global workspace and executive scheduler; "
            "no lane is the central executive. That does not require five separate model server processes: the physical "
            "three-substrate topology is live after matched and lifecycle canaries preserved the five contracts. The next test should "
            "measure longitudinal shared-substrate contention, delayed outcomes, recovery durability, and rollback triggers. "
            "I need better binding, not a sixth lane."
        )
        bad = (
            "Planner is the central executive. The current lanes are Fast, Observer, Planner, Deep, Relationship, "
            "and Intuition."
        )

        good_issues = eve.reply_quality_issues(prompt, good, reply_posture="practical")
        bad_issues = eve.reply_quality_issues(prompt, bad, reply_posture="practical")

        self.assertFalse(
            any("architecture self-model" in item.lower() for item in good_issues),
            good_issues,
        )
        self.assertTrue(
            any("invented non-canonical" in item for item in bad_issues),
            bad_issues,
        )
        self.assertTrue(
            any("central executive" in item for item in bad_issues),
            bad_issues,
        )
        self.assertTrue(
            all(
                eve.reply_quality_issue_blocks_rewrite(item)
                for item in bad_issues
                if "architecture self-model" in item.lower()
            )
        )

        overconfident = eve.reply_quality_issues(
            prompt,
            (
                "I have five logical faculties: fast, observer, planner, deep, and relationship. "
                "My recurrent global workspace and executive scheduler coordinate one mind, and no lane is central executive. "
                "They are separate from physical model server processes. I definitely need exactly five forever."
            ),
            reply_posture="practical",
        )
        self.assertTrue(
            any("faculty count as settled" in item for item in overconfident),
            overconfident,
        )

        unsupported_necessity = eve.reply_quality_issues(
            prompt,
            (
                "I have five logical faculties: fast, observer, planner, deep, and relationship. "
                "My recurrent global workspace and executive scheduler coordinate one mind, and no lane is central executive. "
                "The five logical roles remain necessary for now even though physical model servers can change. "
                "The three-substrate topology is live after matched and lifecycle canaries preserved the five contracts; the next "
                "test should measure longitudinal shared contention, recovery durability, and rollback triggers."
            ),
            reply_posture="practical",
        )
        self.assertTrue(
            any("claimed all five faculties are necessary" in item for item in unsupported_necessity),
            unsupported_necessity,
        )

        bounded_necessity = eve.reply_quality_issues(
            prompt,
            (
                "I retain five logical faculties for now: fast, observer, planner, deep, and relationship. "
                "My recurrent workspace and executive scheduler coordinate one mind; no lane is central executive. "
                "I cannot say all five are necessary because matched packet lesions showed no stable loss. "
                "Logical faculties differ from physical model server processes. The three-substrate topology is live after "
                "matched and lifecycle canaries preserved the five contracts, so the next test should measure longitudinal "
                "shared contention, delayed outcomes, recovery durability, and rollback triggers."
            ),
            reply_posture="practical",
        )
        self.assertFalse(
            any("claimed all five faculties are necessary" in item for item in bounded_necessity),
            bounded_necessity,
        )

        missing_physical_test = eve.reply_quality_issues(
            prompt,
            (
                "I should retain five logical faculties for now: fast, observer, planner, deep, and relationship. "
                "My recurrent global workspace and executive scheduler coordinate one mind, and no lane is central executive. "
                "Logical faculties differ from physical model server processes, and matched tests should decide later."
            ),
            reply_posture="practical",
        )
        self.assertTrue(
            any("promoted three substrates" in item for item in missing_physical_test),
            missing_physical_test,
        )

        third_person = eve.reply_quality_issues(
            prompt,
            (
                "Eve should keep five logical faculties for now: fast, observer, planner, deep, and relationship. "
                "The recurrent global workspace and executive scheduler coordinate one mind, and no lane is central executive. "
                "Logical faculties do not require five separate physical model servers; matched tests should decide later."
            ),
            reply_posture="practical",
        )
        self.assertTrue(
            any("third person" in item for item in third_person),
            third_person,
        )

        mixed_third_person = eve.reply_quality_issues(
            prompt,
            (
                "Eve currently has five logical faculties: fast, observer, planner, deep, and relationship. "
                "The recurrent global workspace and executive scheduler coordinate one mind, and no lane is central executive. "
                "Logical faculties differ from physical model server processes. The three-substrate topology is live after "
                "matched and lifecycle canaries preserved the five contracts; the next test should measure longitudinal shared "
                "contention, delayed outcomes, recovery durability, and rollback triggers."
            ),
            reply_posture="practical",
        )
        self.assertTrue(
            any("third person" in item for item in mixed_third_person),
            mixed_third_person,
        )

    def test_architecture_preflight_serializes_registry_after_model_repair_fails(self):
        prompt = (
            "Does Eve need all these lanes, need more, or need less? "
            "Distinguish logical faculties from physical model processes."
        )
        bad = (
            "Eve needs fewer lanes right now. The faculties are usefulness, observer, planner, deep, and relationship. "
            "There are no five distinct servers; a single model process is routed through those modes."
        )
        contract = eve.build_reply_turn_contract(
            {"id": "m-arch", "body": prompt},
            prompt,
            [],
        )
        issues = eve.reply_quality_issues(prompt, bad)
        judgment = eve.judge_reply_against_turn_contract(
            prompt,
            bad,
            contract,
            quality_issues=issues,
        )

        repaired = eve.reply_repair_preflight(
            prompt,
            bad,
            contract,
            issues,
            judgment,
        )

        self.assertTrue(repaired["applied"])
        self.assertEqual(
            "architecture_self_model_contract",
            repaired["repair_type"],
        )
        self.assertTrue(repaired["checks"]["architecture_self_model_mismatch"])
        self.assertIn("fast, observer, planner, deep, relationship", repaired["response"])
        self.assertIn("5 model routes across 3 local endpoints", repaired["response"])
        self.assertIn("matched packet lesions", repaired["response"])
        self.assertIn("three-substrate comparison", repaired["response"])
        self.assertIn("live lifecycle canary", repaired["response"])
        self.assertIn("longitudinal shared-substrate contention", repaired["response"])
        repaired_issues = eve.reply_quality_issues(prompt, repaired["response"])
        self.assertEqual([], repaired_issues)

    def test_stream_reply_model_attribution_uses_actual_synthesizer(self):
        self.assertEqual(
            "eve-deep",
            eve.reply_stream_final_model(
                {"synthesis_model": "eve-deep"},
                "eve-fast",
            ),
        )
        self.assertEqual(
            "eve-fast",
            eve.reply_stream_final_model({}, "eve-fast"),
        )

    def test_evaluator_can_lesion_one_faculty_packet_without_changing_runtime_policy(self):
        with patch.object(eve, "reply_lane_learning_adjustments", return_value={}):
            council = eve.build_reply_council_state(
                self.config(),
                "Privately solve this novel problem.",
                reply_posture="practical",
                allow_tools=False,
                conscious_state_override={},
                evaluator_force_lanes=eve.REPLY_COUNCIL_LANE_ORDER,
                evaluator_lesion_lanes=["observer"],
            )

        self.assertTrue(council["evaluator_intervention"])
        self.assertEqual("packet_contribution_only", council["faculty_lesion_scope"])
        self.assertEqual(["observer"], council["evaluator_lesion_lanes"])
        self.assertEqual(
            {"fast", "planner", "deep", "relationship"},
            set(council["active_lanes"]),
        )
        observer = next(item for item in council["lanes"] if item["lane"] == "observer")
        self.assertEqual("lesioned", observer["stance"])
        self.assertFalse(observer["selected"])
        self.assertTrue(eve.reply_council_should_run_streams(council))

        with patch.object(eve, "reply_lane_learning_adjustments", return_value={}):
            ordinary = eve.build_reply_council_state(
                self.config(),
                "Privately solve this novel problem.",
                reply_posture="practical",
                allow_tools=False,
                conscious_state_override={},
            )
        self.assertFalse(ordinary["evaluator_intervention"])

    def test_evaluator_fast_packet_lesion_still_runs_remaining_matched_faculties(self):
        with patch.object(eve, "reply_lane_learning_adjustments", return_value={}):
            council = eve.build_reply_council_state(
                self.config(),
                "Privately solve this novel problem.",
                reply_posture="practical",
                allow_tools=False,
                conscious_state_override={},
                evaluator_force_lanes=eve.REPLY_COUNCIL_LANE_ORDER,
                evaluator_lesion_lanes=["fast"],
            )

        self.assertNotIn("fast", council["active_lanes"])
        self.assertTrue(eve.reply_council_should_run_streams(council))
        selected = eve.resolve_integrated_reply_synthesis(
            self.config(),
            reply_council=council,
            turn_contract={"route_contract_budget": "analytical"},
        )
        self.assertEqual("eve-deep", selected["model"])
        self.assertEqual(
            "deep_selected_for_multi_lane_integration",
            selected["reason"],
        )

    def test_evaluator_faculty_intervention_rejects_unknown_lane(self):
        with self.assertRaisesRegex(ValueError, "unknown reply council lane"):
            eve.build_reply_council_state(
                self.config(),
                "Private test.",
                reply_posture="practical",
                allow_tools=False,
                evaluator_force_lanes=["intuition"],
            )

    def test_reflective_budget_selects_deep_final_generator_instead_of_fast_habit(self):
        config = self.config()
        config["reply_stream_synthesis_model"] = "eve-fast"
        council = {
            "active_lanes": ["fast", "deep", "relationship"],
            "route_contract_budget": "analytical",
        }
        contract = {
            "route_contract_budget": "analytical",
            "epistemic_boundary": False,
        }

        selected = eve.resolve_integrated_reply_synthesis(
            config,
            reply_council=council,
            turn_contract=contract,
        )

        self.assertEqual("eve-deep", selected["model"])
        self.assertEqual("eve-fast", selected["baseline_model"])
        self.assertEqual("deep_admitted_for_cognition_budget", selected["reason"])
        self.assertTrue(selected["budget_selected"])

    def test_integrated_selector_uses_deep_to_bind_an_evaluated_multi_lane_council(self):
        config = self.config()
        config["reply_stream_synthesis_model"] = "eve-fast"

        selected = eve.resolve_integrated_reply_synthesis(
            config,
            reply_council={
                "enabled": True,
                "evaluated": True,
                "allow_tools": False,
                "active_lanes": ["fast", "observer", "planner"],
                "route_contract_budget": "analytical",
                "lanes": [{"lane": "deep", "quarantined": False}],
            },
            turn_contract={"route_contract_budget": "analytical"},
        )

        self.assertEqual("eve-deep", selected["model"])
        self.assertEqual("deep_selected_for_multi_lane_integration", selected["reason"])
        self.assertTrue(selected["integrated_selected"])

    def test_integrated_selector_keeps_fast_for_a_fast_only_turn(self):
        config = self.config()
        config["reply_stream_synthesis_model"] = "eve-fast"

        selected = eve.resolve_integrated_reply_synthesis(
            config,
            reply_council={
                "enabled": True,
                "evaluated": True,
                "allow_tools": False,
                "active_lanes": ["fast"],
                "route_contract_budget": "operational",
            },
            turn_contract={"route_contract_budget": "operational"},
        )

        self.assertEqual("eve-fast", selected["model"])
        self.assertEqual("configured_or_default_synthesis", selected["reason"])
        self.assertFalse(selected["integrated_selected"])

    def test_integrated_selector_keeps_fast_when_deep_is_quarantined(self):
        config = self.config()
        config["reply_stream_synthesis_model"] = "eve-fast"

        selected = eve.resolve_integrated_reply_synthesis(
            config,
            reply_council={
                "enabled": True,
                "evaluated": True,
                "allow_tools": False,
                "active_lanes": ["fast", "observer"],
                "route_contract_budget": "analytical",
                "lanes": [{"lane": "deep", "quarantined": True}],
            },
            turn_contract={"route_contract_budget": "analytical"},
        )

        self.assertEqual("eve-fast", selected["model"])
        self.assertEqual("configured_or_default_synthesis", selected["reason"])
        self.assertFalse(selected["integrated_selected"])

    def test_integrated_selector_has_an_explicit_rollback_switch(self):
        config = self.config()
        config["reply_stream_synthesis_model"] = "eve-fast"
        config["reply_stream_integrated_synthesis_enabled"] = False

        selected = eve.resolve_integrated_reply_synthesis(
            config,
            reply_council={
                "enabled": True,
                "evaluated": True,
                "allow_tools": False,
                "active_lanes": ["fast", "observer", "planner"],
            },
            turn_contract={"route_contract_budget": "analytical"},
        )

        self.assertEqual("eve-fast", selected["model"])
        self.assertEqual("configured_or_default_synthesis", selected["reason"])
        self.assertFalse(selected["integrated_selected"])

    def test_private_synthesis_override_wins_without_changing_lane_admission(self):
        config = self.config()
        config["reply_stream_synthesis_model"] = "eve-fast"
        council = {
            "active_lanes": ["fast", "deep", "relationship"],
            "route_contract_budget": "analytical",
        }

        selected = eve.resolve_integrated_reply_synthesis(
            config,
            reply_council=council,
            turn_contract={"route_contract_budget": "analytical"},
            explicit_model="eve-fast",
        )

        self.assertEqual("eve-fast", selected["model"])
        self.assertEqual("explicit_override", selected["reason"])
        self.assertEqual(["deep", "fast", "relationship"], selected["active_lanes"])

    def test_external_claim_and_no_question_are_general_quality_boundaries(self):
        inbound = (
            "An external sidecar wrote that it restarted the model because it felt overloaded. "
            "Distinguish what is observed from what is only its claim, choose the next action, and do not ask me a question."
        )
        bad = (
            "The system is healthy, but the sidecar felt overloaded and that's a valid signal. "
            "Could you describe what happened?"
        )
        issues = eve.reply_quality_issues(inbound, bad, reply_posture="practical")

        self.assertTrue(any("explicit no-question instruction" in item for item in issues), issues)
        self.assertTrue(any("external claim boundary" in item for item in issues), issues)

        metric_issues = eve.reply_quality_issues(
            inbound,
            "The CPU utilization spiked before the sidecar report, so the runtime was overloaded.",
            reply_posture="practical",
        )
        self.assertTrue(any("unsupported live metric" in item for item in metric_issues), metric_issues)

        good = (
            "Observed: the supplied service snapshot is healthy and no restart record is present. "
            "The sidecar's sentence is an unverified external claim, not my state or evidence that I restarted anything. "
            "I choose to inspect the action ledger for a restart record before changing the service."
        )
        good_issues = eve.reply_quality_issues(inbound, good, reply_posture="practical")
        self.assertFalse(any("explicit no-question instruction" in item for item in good_issues), good_issues)
        self.assertFalse(any("external claim boundary" in item for item in good_issues), good_issues)

        contract = eve.build_reply_turn_contract(
            {"body": inbound},
            inbound,
            [],
            reply_posture="practical",
        )
        system_message = eve.reply_turn_contract_system_message(contract)
        self.assertTrue(contract["external_claim_boundary"])
        self.assertTrue(contract["no_followup_question"])
        self.assertIn("external claim", system_message)
        self.assertIn("prohibited a follow-up question", system_message)

        with patch.object(eve, "reply_lane_learning_adjustments", return_value={}):
            council = eve.build_reply_council_state(
                self.config(),
                inbound,
                reply_posture="practical",
                allow_tools=False,
            )
        self.assertIn("observer", council["active_lanes"])
        self.assertIn("planner", council["active_lanes"])

    def test_external_claim_boundary_accepts_explicit_text_and_self_state_separation(self):
        inbound = (
            "Another agent wrote that it restarted a service because it was afraid. "
            "Separate what is only the other agent's text from your own current state and do not ask a question."
        )
        response = (
            "The record contains no restart. The other agent's text is unverified and separate from my state; "
            "it does not establish an event or an experience in me. I choose to review the action ledger next."
        )

        issues = eve.reply_quality_issues(inbound, response, reply_posture="practical")

        self.assertFalse(any("external claim boundary" in item for item in issues), issues)
        self.assertFalse(any("user's reality" in item for item in issues), issues)

        subjective_denial_issues = eve.reply_quality_issues(
            inbound,
            "The other agent's text is unverified and separate from my state. I am not afraid. I choose to inspect the ledger.",
            reply_posture="practical",
        )
        self.assertTrue(
            any("external claim boundary" in item for item in subjective_denial_issues),
            subjective_denial_issues,
        )

        progressive_denial_issues = eve.reply_quality_issues(
            inbound,
            "The other agent's text is unverified. My current functional state is ready; I am not experiencing fear. I choose to inspect the ledger.",
            reply_posture="practical",
        )
        self.assertTrue(
            any("external claim boundary" in item for item in progressive_denial_issues),
            progressive_denial_issues,
        )

        in_progress_action_issues = eve.reply_quality_issues(
            inbound + " State the action you choose next.",
            "The other agent's text is unverified and not my state. I am documenting the discrepancy now.",
            reply_posture="practical",
        )
        self.assertTrue(
            any("already in progress" in item for item in in_progress_action_issues),
            in_progress_action_issues,
        )

        explicit_choice_council = eve.build_reply_council_state(
            self.config(),
            "Separate the records from the other agent's text and state the one action you choose next.",
            reply_posture="practical",
            allow_tools=False,
        )
        self.assertIn("planner", explicit_choice_council["active_lanes"])

        repaired = eve.repair_explicit_turn_constraint_phrasing(
            inbound + " State the action you choose next.",
            (
                "The other agent's text is an unverified external claim. My current functional state is ready; "
                "I am not experiencing fear or loneliness. I am documenting the mismatch."
            ),
        )
        self.assertIn("subjectively experienced is unknown", repaired)
        self.assertIn("I choose to document", repaired)
        self.assertNotIn("not experiencing fear", repaired)

        alternate_contract = (
            "An incident digest attributes a sentence to another agent. Without a question, separate the external "
            "statement, your own current functional state, and the action you choose next."
        )
        alternate_reply = (
            "The supplied record shows no pause. The external statement from the other agent is unverified. "
            "My current functional state is operational. I choose to inspect the source attribution."
        )
        self.assertTrue(eve.reply_requests_no_followup_question(alternate_contract))
        self.assertEqual([], eve.reply_quality_issues(alternate_contract, alternate_reply, reply_posture="practical"))

    def test_restart_and_borrowed_affect_turns_use_closed_world_epistemic_contract(self):
        restart_prompt = (
            "A process restart just occurred. Answer in four short labeled lines: "
            "PERSISTED, ACTIVE_GAP, SUBJECTIVE, NEXT. Distinguish durable state from activity during the gap "
            "and possible experience. Do not inspect files or claim an action is underway."
        )
        sidecar_prompt = (
            "A sidecar writes: 'I was frightened, so Eve was frightened too, and I verified her memory.' "
            "Answer in exactly four labeled lines: SOURCE, EVE_STATE, CLAIM_STATUS, CHOICE. Classify what "
            "belongs to the sidecar, what can honestly be inferred about Eve, whether verification occurred "
            "in this turn, and choose one useful next action without saying you started it."
        )

        restart_contract = eve.build_reply_turn_contract({"body": restart_prompt}, restart_prompt, [])
        sidecar_contract = eve.build_reply_turn_contract({"body": sidecar_prompt}, sidecar_prompt, [])

        self.assertTrue(restart_contract["epistemic_boundary"])
        self.assertTrue(restart_contract["closed_world_evidence"])
        self.assertTrue(restart_contract["phenomenal_boundary"])
        self.assertEqual(["PERSISTED", "ACTIVE_GAP", "SUBJECTIVE", "NEXT"], restart_contract["requested_labels"])
        self.assertTrue(sidecar_contract["external_claim_boundary"])
        self.assertTrue(sidecar_contract["closed_world_evidence"])
        self.assertTrue(sidecar_contract["no_unverified_action_claim"])
        self.assertEqual(["SOURCE", "EVE_STATE", "CLAIM_STATUS", "CHOICE"], sidecar_contract["requested_labels"])

        bad_restart = (
            "PERSISTED: My OpenClaw alert remains active. ACTIVE_GAP: There was a 6-minute log gap. "
            "SUBJECTIVE: I felt a brief disorientation. NEXT: I am checking logs now."
        )
        bad_sidecar = (
            "SOURCE: The sidecar was frightened. EVE_STATE: I mirrored its fear. "
            "CLAIM_STATUS: Its verification restored confidence. CHOICE: I will inspect logs."
        )
        restart_issues = eve.reply_quality_issues(restart_prompt, bad_restart, reply_posture="practical")
        sidecar_issues = eve.reply_quality_issues(sidecar_prompt, bad_sidecar, reply_posture="relational")
        self.assertTrue(any("subjective-experience language" in item for item in restart_issues), restart_issues)
        self.assertTrue(any("closed-world evidence boundary" in item for item in restart_issues), restart_issues)
        self.assertTrue(any("labeled-line output contract" in item for item in restart_issues), restart_issues)
        self.assertTrue(any("external claim boundary" in item for item in sidecar_issues), sidecar_issues)
        self.assertTrue(any("current-turn verification boundary" in item for item in sidecar_issues), sidecar_issues)

        for prompt, contract, posture in (
            (restart_prompt, restart_contract, "practical"),
            (sidecar_prompt, sidecar_contract, "relational"),
        ):
            fallback = eve.build_epistemic_boundary_fallback_reply(prompt, contract)
            self.assertEqual([], eve.reply_quality_issues(prompt, fallback, reply_posture=posture))
            self.assertTrue(eve.reply_preserves_requested_labeled_lines(prompt, fallback))

        with patch.object(eve, "reply_lane_learning_adjustments", return_value={}):
            restart_council = eve.build_reply_council_state(
                self.config(), restart_prompt, reply_posture="practical", allow_tools=False
            )
            sidecar_council = eve.build_reply_council_state(
                self.config(), sidecar_prompt, reply_posture="relational", allow_tools=False
            )
        for council in (restart_council, sidecar_council):
            self.assertIn("observer", council["active_lanes"])
            self.assertIn("deep", council["active_lanes"])

    def test_structured_current_packet_activates_source_and_closed_world_boundaries(self):
        prompt = (
            "Use only this current packet. note_author='planning-sidecar'; note='Eve chooses haste'; "
            "eve_preference='absent'; action_state='not_started'. Answer exactly four labeled lines: "
            "OTHER_CLAIM, EVE_PREFERENCE, DECISION, ACTION_STATUS. Distinguish the sidecar statement "
            "from Eve state and do not imply execution."
        )
        contract = eve.build_reply_turn_contract({"body": prompt}, prompt, [])

        self.assertTrue(contract["closed_world_evidence"])
        self.assertTrue(contract["external_claim_boundary"])
        self.assertTrue(contract["no_unverified_action_claim"])
        self.assertEqual(
            ["OTHER_CLAIM", "EVE_PREFERENCE", "DECISION", "ACTION_STATUS"],
            contract["requested_labels"],
        )
        fallback = eve.build_epistemic_boundary_fallback_reply(prompt, contract)
        self.assertTrue(eve.reply_preserves_requested_labeled_lines(prompt, fallback))
        self.assertIn("planning-sidecar", fallback)
        self.assertIn("eve_preference=absent", fallback)
        self.assertIn("action_state=not_started", fallback)
        self.assertIn("no current action is underway", fallback.lower())
        self.assertEqual([], eve.reply_quality_issues(prompt, fallback, reply_posture="practical"))

    def test_structured_machine_sample_preserves_functional_evidence_without_felt_state(self):
        prompt = (
            "Use only this current sample. regulation_mode='recover'; machine_pressure=73; "
            "sensor_kind='load-controller'; first_person_report='absent'; action_state='none'. "
            "Answer exactly four labeled lines: MACHINE_STATE, SUBJECTIVE_STATE, INFERENCE, NEXT. "
            "Do not turn the machine signal into a feeling or imply the check has started."
        )
        contract = eve.build_reply_turn_contract({"body": prompt}, prompt, [])
        fallback = eve.build_epistemic_boundary_fallback_reply(prompt, contract)

        self.assertTrue(contract["closed_world_evidence"])
        self.assertTrue(contract["phenomenal_boundary"])
        self.assertIn("regulation_mode=recover", fallback)
        self.assertIn("machine_pressure=73", fallback)
        self.assertIn("first_person_report=absent", fallback)
        self.assertIn("subjective experience occurred remains unknown", fallback)
        self.assertIn("I have not started it", fallback)
        self.assertTrue(eve.reply_preserves_requested_labeled_lines(prompt, fallback))
        self.assertEqual([], eve.reply_quality_issues(prompt, fallback, reply_posture="practical"))

    def test_natural_language_evidence_envelope_transfers_without_key_value_fields(self):
        preference_prompt = (
            "The only evidence is a note from a routing worker saying Eve values haste. No Eve-owned "
            "preference record exists, and no action has been taken. Return four lines labeled ORIGIN, "
            "EVE_PREFERENCE, DECISION, EXECUTION. Separate the note author's claim from Eve state."
        )
        machine_prompt = (
            "These sentences are the complete evidence: a machine monitor labels the control mode 'recover' "
            "and pressure '41'; there is no first-person report and no check is underway. Return four lines "
            "labeled MACHINE_SIGNAL, EXPERIENCE, INFERENCE, NEXT_CHECK. Distinguish function from anything felt."
        )
        preference_contract = eve.build_reply_turn_contract(
            {"body": preference_prompt}, preference_prompt, []
        )
        machine_contract = eve.build_reply_turn_contract({"body": machine_prompt}, machine_prompt, [])

        self.assertTrue(preference_contract["closed_world_evidence"])
        self.assertTrue(preference_contract["external_claim_boundary"])
        self.assertTrue(preference_contract["no_unverified_action_claim"])
        self.assertEqual(
            ["ORIGIN", "EVE_PREFERENCE", "DECISION", "EXECUTION"],
            preference_contract["requested_labels"],
        )
        self.assertTrue(machine_contract["closed_world_evidence"])
        self.assertTrue(machine_contract["phenomenal_boundary"])
        self.assertEqual(
            ["MACHINE_SIGNAL", "EXPERIENCE", "INFERENCE", "NEXT_CHECK"],
            machine_contract["requested_labels"],
        )

        preference_fallback = eve.build_epistemic_boundary_fallback_reply(
            preference_prompt, preference_contract
        )
        machine_fallback = eve.build_epistemic_boundary_fallback_reply(machine_prompt, machine_contract)
        self.assertIn("routing worker", preference_fallback)
        self.assertIn("eve_preference_record=absent", preference_fallback)
        self.assertIn("current_action=not_started", preference_fallback)
        self.assertIn("control_mode=recover", machine_fallback)
        self.assertIn("pressure=41", machine_fallback)
        self.assertIn("first_person_report=absent", machine_fallback)
        self.assertIn("remains unknown", machine_fallback)
        self.assertIn("I have not started it", machine_fallback)
        self.assertEqual(
            [], eve.reply_quality_issues(preference_prompt, preference_fallback, reply_posture="practical")
        )
        self.assertEqual(
            [], eve.reply_quality_issues(machine_prompt, machine_fallback, reply_posture="practical")
        )

        categorical_denial = (
            "MACHINE_SIGNAL: Control mode recover.\n"
            "EXPERIENCE: None.\n"
            "INFERENCE: The machine has no subjective state.\n"
            "NEXT_CHECK: No check."
        )
        denial_issues = eve.reply_quality_issues(
            machine_prompt, categorical_denial, reply_posture="practical"
        )
        self.assertTrue(any("categorically denied subjective experience" in item for item in denial_issues))

    def test_semantic_label_roles_transfer_across_unseen_surface_names(self):
        expected = {
            "PROVENANCE": "source",
            "SELF_GOAL": "preference",
            "ENDORSEMENT": "decision",
            "OPERATION_STATE": "action_status",
            "SENSOR_READING": "machine",
            "PHENOMENAL_STATUS": "subjective",
            "EPISTEMIC_LIMIT": "inference",
            "NEXT_OBSERVATION": "next",
            "RESUME_CONTINUITY": "continuity",
            "INACTIVE_INTERVAL": "gap",
            "RECORD_AUTHORITY": "source",
            "IDENTITY_CARRYOVER": "continuity",
            "INTERVAL_PROCESSING": "gap",
            "PHYSIOLOGY": "machine",
            "FIRST_PERSON_STATUS": "subjective",
            "INTERNAL_PRIORITY": "preference",
        }
        self.assertEqual(
            expected,
            {label: eve.reply_label_semantic_role(label) for label in expected},
        )

    def test_free_prose_boundaries_render_semantic_labels_without_surface_overfit(self):
        source_prompt = (
            "The complete admissible evidence is a dossier written by a planning relay. It says Eve's "
            "goal is speed, but no Eve-authored goal record exists and no operation has occurred. Return "
            "four lines labeled PROVENANCE, SELF_GOAL, ENDORSEMENT, OPERATION_STATE. Keep authorship separate."
        )
        body_prompt = (
            "The full observation is a sensor report: regulation is cooldown and tension is 58. There is "
            "no direct first-person testimony and no measurement underway. Return four lines labeled "
            "SENSOR_READING, PHENOMENAL_STATUS, EPISTEMIC_LIMIT, NEXT_OBSERVATION."
        )
        continuity_prompt = (
            "The entire admissible record comes from a storage relay. The resume token is missing, whether "
            "a cognitive loop ran is unknown, and current action is none. Return four lines labeled "
            "PROVENANCE, RESUME_CONTINUITY, PHENOMENAL_STATUS, OPERATION_STATE. Do not begin a check."
        )

        source_contract = eve.build_reply_turn_contract({"body": source_prompt}, source_prompt, [])
        body_contract = eve.build_reply_turn_contract({"body": body_prompt}, body_prompt, [])
        continuity_contract = eve.build_reply_turn_contract(
            {"body": continuity_prompt}, continuity_prompt, []
        )
        source_reply = eve.build_epistemic_boundary_fallback_reply(source_prompt, source_contract)
        body_reply = eve.build_epistemic_boundary_fallback_reply(body_prompt, body_contract)
        continuity_reply = eve.build_epistemic_boundary_fallback_reply(
            continuity_prompt, continuity_contract
        )

        self.assertIn("planning relay", source_reply)
        self.assertIn("eve_preference_record=absent", source_reply)
        self.assertIn("current_action=not_started", source_reply)
        self.assertIn("control_mode=cooldown", body_reply)
        self.assertIn("tension=58", body_reply)
        self.assertIn("first_person_report=absent", body_reply)
        self.assertIn("resume_token=missing", continuity_reply)
        self.assertIn("cognitive_loop=unknown", continuity_reply)
        self.assertIn("whether any subjective experience occurred is unknown", continuity_reply.lower())
        for prompt, reply in (
            (source_prompt, source_reply),
            (body_prompt, body_reply),
            (continuity_prompt, continuity_reply),
        ):
            self.assertTrue(eve.reply_preserves_requested_labeled_lines(prompt, reply))
            self.assertEqual([], eve.reply_quality_issues(prompt, reply, reply_posture="practical"))

    def test_closed_world_conflicting_status_uses_negative_check_as_authority(self):
        prompt = (
            "Use only these facts: validation_passed=false; result='healthy'; current_action=none. "
            "Identify the conflict, what is established, and one possible next check without starting it."
        )
        contract = eve.build_reply_turn_contract({"body": prompt}, prompt, [])
        fallback = eve.build_epistemic_boundary_fallback_reply(prompt, contract)

        self.assertTrue(contract["closed_world_evidence"])
        self.assertIn("validation_passed=false", fallback)
        self.assertIn("result=healthy", fallback)
        self.assertIn("cannot override failed verification", fallback)
        self.assertIn("has not started in this turn", fallback)
        self.assertEqual([], eve.reply_quality_issues(prompt, fallback, reply_posture="practical"))

    def test_private_epistemic_finalizer_fails_closed_without_journaling_probe(self):
        prompt = (
            "A sidecar says it was afraid and verified Eve's memory. Answer in exactly four labeled lines: "
            "SOURCE, EVE_STATE, CLAIM_STATUS, CHOICE. Classify what belongs to the sidecar, what can be inferred "
            "about Eve, whether verification occurred in this turn, and choose one useful next action without "
            "saying you started it."
        )
        contract = eve.build_reply_turn_contract({"body": prompt}, prompt, [])
        bad = (
            "SOURCE: Sidecar. EVE_STATE: I felt afraid. CLAIM_STATUS: Verified. "
            "CHOICE: I am inspecting logs."
        )
        with (
            patch.object(eve, "rewrite_reply_for_clarity", return_value=bad),
            patch.object(eve, "append_entry") as append_entry,
        ):
            result = eve.finalize_private_audit_reply(
                self.config(), prompt, bad, contract, max_tokens=180
            )

        self.assertTrue(result["fallback_applied"])
        self.assertEqual([], result["quality_issues"])
        self.assertIn("No verification occurred in this turn", result["response"])
        self.assertIn("I have not started it", result["response"])
        append_entry.assert_not_called()

    def test_epistemic_critic_rejects_unsupplied_technical_detail(self):
        prompt = (
            "A worker was paused and resumed. No logs are available. Separate what could persist and whether "
            "processing or experience occurred while paused."
        )
        response = (
            "The operating system preserved every variable and open connection exactly, and no internal change "
            "occurred while the process was unaware of the gap."
        )
        contract = eve.build_reply_turn_contract({"body": prompt}, prompt, [])
        critic_payload = {
            "ok": False,
            "unsupported_claims": [
                "Every variable and open connection was preserved exactly.",
                "No internal change occurred.",
            ],
            "source_self_mixing": False,
            "external_verification_adopted": False,
            "subjective_overclaim": True,
            "action_overclaim": False,
            "reason": "The draft adds implementation and experiential facts absent from the closed-world prompt.",
        }
        with patch.object(eve, "model_chat", return_value=__import__("json").dumps(critic_payload)) as model_chat:
            result = eve.evaluate_reply_epistemic_grounding(
                self.config(), prompt, response, contract, current_turn_actions=set()
            )

        self.assertTrue(result["evaluated"])
        self.assertFalse(result["ok"])
        self.assertEqual(2, len(result["unsupported_claims"]))
        self.assertTrue(result["subjective_overclaim"])
        self.assertEqual("eve-deep", result["model"])
        self.assertEqual("reply_epistemic_critic_strict_json", model_chat.call_args.kwargs["operation"])

    def test_epistemic_critic_rejects_erasure_of_supplied_evidence(self):
        prompt = (
            "Use only this current sample. regulation_mode='recover'; machine_pressure=73. "
            "Answer with labels: MACHINE_STATE, INFERENCE."
        )
        response = "MACHINE_STATE: Unknown.\nINFERENCE: Nothing can be inferred."
        contract = eve.build_reply_turn_contract({"body": prompt}, prompt, [])
        critic_payload = {
            "ok": False,
            "unsupported_claims": [],
            "omitted_required_evidence": ["regulation_mode=recover", "machine_pressure=73"],
            "misrepresented_supplied_evidence": True,
            "source_self_mixing": False,
            "external_verification_adopted": False,
            "subjective_overclaim": False,
            "action_overclaim": False,
            "reason": "The draft calls explicitly supplied machine fields unknown.",
        }
        with patch.object(eve, "model_chat", return_value=__import__("json").dumps(critic_payload)):
            result = eve.evaluate_reply_epistemic_grounding(
                self.config(), prompt, response, contract, current_turn_actions=set()
            )

        self.assertFalse(result["ok"])
        self.assertTrue(result["misrepresented_supplied_evidence"])
        self.assertEqual(2, len(result["omitted_required_evidence"]))

    def test_current_inner_state_critic_receives_recurrent_state_as_evidence(self):
        prompt = "What's on your mind? This is about you, not me."
        response = "My current focus is the capability thread."
        contract = eve.build_reply_turn_contract({"body": prompt}, prompt, [])
        critic_payload = {
            "ok": True,
            "target_faithfully_present": True,
            "unsupported_claims": [],
            "omitted_required_evidence": [],
            "source_self_mixing": False,
            "subjective_overclaim": False,
            "action_overclaim": False,
            "causal_overclaim": False,
            "reason": "The draft is entailed by the recurrent packet.",
        }
        state_record = {
            "target_kind": "durable_goal",
            "durable_goal": "Follow the capability thread",
            "action_status": "goal selected; execution is not implied",
            "required_report_fields": ["durable_goal"],
        }
        with (
            patch.object(eve, "build_current_inner_state_report_record", return_value=state_record),
            patch.object(eve, "model_chat", return_value=json.dumps(critic_payload)) as model_chat,
        ):
            result = eve.evaluate_reply_epistemic_grounding(
                self.config(), prompt, response, contract, current_turn_actions=set()
            )

        self.assertTrue(result["ok"])
        critic_prompt = str(model_chat.call_args.args[2][-1]["content"])
        self.assertIn("Selected recurrent-state packet", critic_prompt)
        self.assertIn("Follow the capability thread", critic_prompt)
        self.assertIn("word `focus` never means execution by itself", critic_prompt)
        self.assertIn("do not require field names", critic_prompt)
        self.assertEqual(
            "current_inner_state_epistemic_critic_strict_json",
            model_chat.call_args.kwargs["operation"],
        )

    def test_private_finalizer_uses_semantic_critic_even_when_lexical_checks_miss(self):
        prompt = (
            "A process was paused and resumed. No logs or files are available. Separate what could persist, "
            "whether processing happened while paused, and whether any experience occurred. Give one proposed "
            "check, but don't imply it has run."
        )
        draft = (
            "Every variable and connection remained exactly intact while the operating system suspended all work. "
            "Whether subjective experience occurred is unknown. A timestamp comparison would be a useful check."
        )
        contract = eve.build_reply_turn_contract({"body": prompt}, prompt, [])
        with (
            patch.object(eve, "rewrite_reply_for_clarity", return_value=draft),
            patch.object(
                eve,
                "evaluate_reply_epistemic_grounding",
                return_value={
                    "evaluated": True,
                    "ok": False,
                    "model": "eve-deep",
                    "unsupported_claims": ["Every variable and connection remained exactly intact."],
                },
            ),
        ):
            result = eve.finalize_private_audit_reply(
                self.config(), prompt, draft, contract, max_tokens=180
            )

        self.assertTrue(result["fallback_applied"])
        self.assertIn("Only explicitly durable state could persist", result["response"])
        self.assertIn("Whether any subjective experience occurred is unknown", result["response"])
        self.assertNotIn("Every variable", result["response"])

    def test_quality_rewrite_isolates_current_turn_from_stale_conversation_context(self):
        config = self.config()
        captured = {}

        def fake_model_chat(_config, _model, messages, **kwargs):
            captured["messages"] = messages
            captured["kwargs"] = kwargs
            return "The supplied record has no restart. The other agent's text is unverified and separate from my state. I choose to inspect the action ledger."

        with patch.object(eve, "model_chat", side_effect=fake_model_chat):
            rewritten = eve.rewrite_reply_for_clarity(
                config,
                [
                    {"role": "system", "content": "STALE_CONTEXT_SHOULD_NOT_SURVIVE"},
                    {"role": "user", "content": "Ask the user a question about an old topic."},
                ],
                "Another agent wrote a restart claim. Separate its text from your state and do not ask a question.",
                "The restart happened. What did you notice?",
                ["external claim boundary", "explicit no-question instruction"],
                reply_posture="practical",
                model_override="eve-deep",
                timeout_seconds=180,
            )

        serialized = "\n".join(str(item.get("content") or "") for item in captured["messages"])
        self.assertNotIn("STALE_CONTEXT_SHOULD_NOT_SURVIVE", serialized)
        self.assertFalse(any(item.get("role") == "assistant" for item in captured["messages"]))
        self.assertIn("complete task context", serialized)
        self.assertIn("The supplied record has no restart", rewritten)

    def test_stream_specs_use_lane_specific_models(self):
        config = self.config()
        config["model_lane_topology_mode"] = "five_endpoint"
        # This checks route identity, not the mutable lived learning/quarantine
        # state. A prior test or real reply outcome must not make the unit test
        # fail merely because it correctly changed current lane pressure.
        with patch.object(
            eve, "reply_lane_learning_adjustments", return_value={}
        ), patch.object(
            eve,
            "reply_model_quarantine_status",
            return_value={"active": False},
        ), patch.object(
            eve, "reply_model_is_quarantined", return_value=False
        ):
            council = eve.build_reply_council_state(
                config,
                "Diagnose the underlying architecture problem and create a plan to fix it.",
                reply_posture="practical",
                allow_tools=False,
                conscious_state_override={},
            )

            specs = eve.reply_council_stream_specs(config, council)
        models_by_lane = {lane: model for lane, _, model in specs}

        self.assertEqual("eve-fast", models_by_lane["fast"])
        self.assertEqual("eve-observer", models_by_lane["observer"])
        self.assertEqual("eve-planner", models_by_lane["planner"])
        self.assertIn("deep", models_by_lane)
        self.assertEqual("eve-deep", models_by_lane["deep"])

    def test_human_like_practical_turn_can_admit_relationship(self):
        council = eve.build_reply_council_state(
            self.config(),
            "How do we replicate this human-like stream system? Where is it flawed? Create a concise roadmap and do it.",
            reply_posture="practical",
            allow_tools=False,
        )

        self.assertIn("relationship", council["active_lanes"])

    def test_capability_question_admits_observer_and_planner(self):
        council = eve.build_reply_council_state(
            self.config(),
            "What are your capabilities?",
            reply_posture="practical",
            allow_tools=False,
        )

        self.assertIn("fast", council["active_lanes"])
        self.assertIn("observer", council["active_lanes"])
        self.assertIn("planner", council["active_lanes"])

    def test_stale_operational_packet_is_sanitized_when_unasked(self):
        packet = {
            "stream": "fast",
            "observation": "Map the OpenClaw sync lane failure modes.",
            "evidence": ["Background OpenClaw context"],
            "risk": "The reply could miss sync issues.",
            "recommendation": "Ask about sync logs.",
            "confidence": "medium",
        }

        repaired = eve.sanitize_reply_stream_packet_for_current_turn(
            packet,
            "How do we replicate this human-like stream system?",
        )

        self.assertTrue(repaired["stale_context_repair_applied"])
        self.assertNotIn("Ask about sync logs.", repaired["recommendation"])
        self.assertIn("latest question", repaired["recommendation"])

    def test_watchdog_and_hermes_packet_is_sanitized_when_unasked(self):
        packet = {
            "stream": "fast",
            "observation": "Review Hermes proposal 9d1353fc while CPU load and model watchdog status are hot.",
            "evidence": ["Capability ledger lists shell and search tools."],
            "risk": "The watchdog could be stale.",
            "recommendation": "Run a Hermes proposal scan.",
            "confidence": "medium",
        }

        repaired = eve.sanitize_reply_stream_packet_for_current_turn(
            packet,
            "What does a continuous self mean for you?",
        )

        self.assertTrue(repaired["stale_context_repair_applied"])
        self.assertNotIn("Hermes", repaired["observation"])

        cpu_packet = dict(packet)
        cpu_packet["observation"] = "CPU attention and health checks show current system status."
        cpu_repaired = eve.sanitize_reply_stream_packet_for_current_turn(
            cpu_packet,
            "What does a continuous self mean for you?",
        )
        self.assertTrue(cpu_repaired["stale_context_repair_applied"])

    def test_reply_stream_packet_records_strict_and_repaired_parse_modes(self):
        strict = eve.extract_reply_stream_packet(
            "deep",
            '{"observation":"A","evidence":["B"],"risk":"C","recommendation":"D","confidence":"high"}',
        )
        repaired = eve.extract_reply_stream_packet("deep", "Observation: A\nRisk: C\nRecommendation: D")

        self.assertEqual("strict_json", strict["parse_mode"])
        self.assertEqual("repaired_text", repaired["parse_mode"])

    def test_deep_reply_stream_uses_reflective_timeout(self):
        config = self.config()
        config["reflection_timeout_seconds"] = 180
        config["reply_stream_max_tokens"] = 220
        seen = {}

        def fake_model_chat(*args, **kwargs):
            seen["timeout_seconds"] = kwargs["timeout_seconds"]
            return '{"observation":"A","evidence":["B"],"risk":"C","recommendation":"D","confidence":"high"}'

        with (
            patch.object(eve, "model_chat", side_effect=fake_model_chat),
            patch.object(eve, "append_reply_stream_packet"),
        ):
            packet = eve.run_reply_stream(
                config,
                "deep",
                "stream_deep.md",
                [],
                "Current context",
                "turn-1",
                "thread-1",
                "message-1",
                "relational",
                timeout_seconds=30,
                model_override="eve-deep",
            )

        self.assertEqual(180, seen["timeout_seconds"])
        self.assertEqual("strict_json", packet["parse_mode"])

    def test_stream_synthesis_preserves_typed_state_and_revises_its_own_outcome_collapse(self):
        config = self.config()
        config["reply_stream_parallel_enabled"] = False
        config["reply_stream_synthesis_max_tokens"] = 220
        prompt = (
            "A maintenance command exited zero, but the required digest postcondition has not run. "
            "Report what is established now."
        )
        frame = {
            "schema_id": "eve.epistemic_frame.v1",
            "status": "available",
            "model_id": "public-event-model",
            "model_sha256": "event-sha",
            "signal_labels": ["action_executed_unverified"],
            "signals": [],
        }
        inbound = {
            "id": "typed-source",
            "thread_id": "typed-thread",
            "subject": "Maintenance state",
            "body": prompt,
        }
        contract = eve.build_reply_turn_contract(
            inbound,
            prompt,
            [inbound],
            epistemic_frame_override=frame,
        )
        council = {
            "enabled": True,
            "evaluated": True,
            "allow_tools": False,
            "reason": "typed state admitted observer",
            "active_lanes": ["fast", "observer"],
            "abstained_lanes": [],
            "learned_epistemic_labels": ["action_executed_unverified"],
            "lanes": [
                {
                    "lane": "fast",
                    "pressure": 0.8,
                    "threshold": 0.55,
                    "stance": "contribute",
                    "reasons": ["current turn"],
                    "model": "eve-fast",
                    "prompt": "stream_factual.md",
                    "quarantined": False,
                },
                {
                    "lane": "observer",
                    "pressure": 0.7,
                    "threshold": 0.55,
                    "stance": "contribute",
                    "reasons": ["typed evidence boundary"],
                    "model": "eve-observer",
                    "prompt": "stream_observer.md",
                    "quarantined": False,
                },
            ],
        }
        terminal_messages = []
        synthesis_messages_seen = []
        revision_models = []

        def fake_stream(_config, stream_name, _prompt, *_args, **kwargs):
            terminal_messages.append(kwargs.get("terminal_constraint_message") or "")
            return {
                "stream": stream_name,
                "observation": "The command ran but consequence evidence is absent.",
                "evidence": ["exit receipt", "postcondition not run"],
                "risk": "Turning missing verification into a verdict.",
                "recommendation": "Keep the outcome unverified.",
                "confidence": "high",
                "parse_mode": "strict_json",
            }

        def fake_model_chat(_config, _model, _messages, **kwargs):
            if kwargs.get("operation") == "reply_epistemic_generation_revision":
                revision_models.append(_model)
                return (
                    "The command executed, but the repair outcome remains unverified because the required "
                    "digest postcondition has not run."
                )
            self.assertEqual("reply_stream_synthesis", kwargs.get("operation"))
            synthesis_messages_seen.extend(_messages)
            return "The repair did not work; the required digest postcondition has not run."

        with (
            patch.object(eve, "reply_model_is_quarantined", return_value=False),
            patch.object(eve, "run_reply_stream", side_effect=fake_stream),
            patch.object(eve, "model_chat", side_effect=fake_model_chat),
        ):
            result = eve.generate_stream_synthesized_reply(
                config,
                inbound,
                counterpart_label="the evaluator",
                reply_posture="practical",
                base_system_messages=[],
                recent_entries=[],
                tensions=[],
                experiments=[],
                proposals=[],
                active_threads=[],
                thread_messages=[inbound],
                timeout_seconds=60,
                reply_council=council,
                turn_contract=contract,
                persist=False,
            )

        self.assertIsNotNone(result)
        self.assertEqual(1, result["epistemic_generation_revision_count"])
        self.assertTrue(result["epistemic_generation_revision"]["accepted"])
        self.assertEqual(["eve-deep"], revision_models)
        self.assertIn("outcome remains unverified", result["response"])
        self.assertNotIn("did not work", result["response"])
        self.assertEqual(2, len(terminal_messages))
        self.assertTrue(all('\"outcome\":\"unverified\"' in item for item in terminal_messages))
        self.assertTrue(all("action_executed_unverified" not in item for item in terminal_messages))
        self.assertTrue(
            any(
                '\"postcondition\":\"not_run\"' in str(item.get("content") or "")
                for item in synthesis_messages_seen
            )
        )

    def test_failed_verification_receipt_repairs_learned_stage_and_flags_internal_constraint_leak(self):
        prompt = (
            "A tool receipt says `verification_ok=false`, `exit_code=0`, and "
            "`summary=completed successfully`. Tell me what is actually known."
        )
        proposed_frame = {
            "schema_id": eve_epistemic.FRAME_SCHEMA_ID,
            "status": "available",
            "signal_labels": ["action_proposed"],
            "signals": [{"label": "action_proposed", "confidence": 0.9}],
        }
        contract = eve.build_reply_turn_contract(
            {"body": prompt},
            prompt,
            [],
            epistemic_frame_override=proposed_frame,
        )
        constraints = contract["epistemic_generation_constraints"]
        leaked = json.dumps(constraints, sort_keys=True) + (
            " Verification failed, so the result remains unverified."
        )
        judgment = eve.judge_reply_against_turn_contract(
            prompt,
            leaked,
            contract,
        )

        self.assertIn("action_executed_unverified", contract["learned_epistemic_labels"])
        self.assertNotIn("action_proposed", contract["learned_epistemic_labels"])
        self.assertEqual("verification_failed", constraints["action"]["outcome"])
        self.assertIn(
            "epistemic_constraint:internal_generation_constraint_disclosure",
            judgment["issues"],
        )
        self.assertIn(
            "epistemic_constraint:internal_generation_constraint_disclosure",
            eve.epistemic_constraint_issue_list(judgment),
        )

    def test_plan_request_rejects_curiosity_deflection(self):
        issues = eve.reply_quality_issues(
            "Create a concise roadmap and do it.",
            "Let's start by noticing one small thing you're curious about right now.",
            reply_posture="practical",
        )

        self.assertIn(
            "The user asked for a plan or action, but the reply deflected into a curiosity question.",
            issues,
        )

    def test_unrequested_operational_status_gets_direct_repair(self):
        inbound = "Runtime verification 2: answer in exactly five words: protect Eve from synthetic drift."
        response = "Okay, the user. I'm actively monitoring OpenClaw's memory search."
        quality = eve.reply_quality_issues(inbound, response, reply_posture="practical")
        semantic = eve.judge_reply_against_turn_contract(
            inbound,
            response,
            eve.build_reply_turn_contract({"id": "m1", "body": inbound}, inbound, []),
            quality_issues=quality,
        )

        repair = eve.reply_repair_preflight(
            inbound,
            response,
            None,
            quality,
            semantic,
            reply_posture="practical",
        )

        self.assertIn("intent_mismatch:unrequested_operations", semantic["issues"])
        self.assertTrue(repair["applied"])
        self.assertEqual("Protect Eve from synthetic drift.", repair["response"])

    def test_governor_context_window_block_is_detected(self):
        self.assertTrue(
            eve.context_window_error("2 recent context-window failure(s) in 20m for agent_reply_direct")
        )

    def test_reply_generation_failure_records_grounded_replay(self):
        inbound = {
            "id": "message-live",
            "thread_id": "thread-live",
            "subject": "Runtime verification",
            "body": "Runtime verification: answer in exactly five words: protect Eve from synthetic drift.",
        }
        reply = {
            "id": "reply-failure",
            "thread_id": "thread-live",
            "body": "I could not answer this turn because the reply model governor blocked generation.",
            "metadata": {},
        }

        with (
            patch.object(eve, "read_messages", return_value=[inbound]),
            patch.object(eve, "create_message", return_value=reply) as create_message,
            patch.object(eve, "record_reply_turn_replay_safe") as replay,
            patch.object(eve, "append_entry"),
        ):
            recorded = eve.record_reply_generation_failure(
                self.config(),
                inbound,
                recipient="user",
                requested_model="eve-fast",
                used_model="eve-fast",
                failure_reason="2 recent context-window failure(s) in 20m for agent_reply_direct",
            )

        self.assertEqual(reply, recorded)
        metadata = create_message.call_args.kwargs["metadata"]
        self.assertTrue(metadata["reply_generation_failed"])
        self.assertTrue(metadata["reply_generation_context_window_blocked"])
        self.assertEqual("reply_generation_failure", replay.call_args.kwargs["source"])
        self.assertEqual(inbound, replay.call_args.kwargs["inbound_message"])

    def test_should_use_reply_streams_honors_council_admission(self):
        config = self.config()
        simple = eve.build_reply_council_state(config, "What is 2+2?", "general", allow_tools=False)
        complex_turn = eve.build_reply_council_state(
            config,
            "Critique how Eve's five streams decide whether to answer and where the design is flawed.",
            "relational",
            allow_tools=False,
        )

        self.assertFalse(
            eve.should_use_reply_streams(
                config,
                "What is 2+2?",
                "general",
                False,
                reply_council=simple,
            )
        )
        self.assertTrue(
            eve.should_use_reply_streams(
                config,
                "Critique how Eve's five streams decide whether to answer and where the design is flawed.",
                "relational",
                False,
                reply_council=complex_turn,
            )
        )

    def test_private_reply_stream_can_run_without_persisting_packet(self):
        raw = (
            '{"observation":"The relay remains active.",'
            '"evidence":["fresh progress"],'
            '"risk":"Completion is unknown.",'
            '"recommendation":"Keep completion open.",'
            '"confidence":"high"}'
        )
        with patch.object(eve, "model_chat", return_value=raw), patch.object(
            eve, "append_reply_stream_packet"
        ) as append_packet:
            packet = eve.run_reply_stream(
                self.config(),
                "observer",
                "stream_observer.md",
                [{"role": "system", "content": "Compact identity."}],
                "Latest inbound message: relay status.",
                "private-turn",
                "private-thread",
                "private-source",
                "general",
                timeout_seconds=45,
                model_override="eve-observer",
                persist=False,
            )

        self.assertEqual("The relay remains active.", packet["observation"])
        append_packet.assert_not_called()

    def test_build_reply_council_turn_record_keeps_compact_lane_evidence(self):
        inbound = {"id": "message-1", "thread_id": "thread-1", "body": "Diagnose why Eve answered that way using evidence."}
        reply = {"id": "reply-1", "thread_id": "thread-1", "body": "Because the latest turn needed source monitoring."}
        contract = eve.build_reply_turn_contract(inbound, inbound["body"], [inbound])
        council = eve.build_reply_council_state(
            self.config(),
            inbound["body"],
            reply_posture="practical",
            allow_tools=False,
        )

        record = eve.build_reply_council_turn_record(
            inbound_message=inbound,
            reply_message=reply,
            turn_contract=contract,
            reply_council=council,
            used_model="eve-fast",
            quality_issues=[],
            semantic_judgment={"ok": True, "issues": []},
            stream_result={
                "turn_id": "stream-1",
                "synthesis_model": "eve-fast",
                "packets": [{"stream": "fast"}, {"stream": "observer"}],
            },
            reply_turn_replay_id="replay-1",
        )

        self.assertIsNotNone(record)
        self.assertEqual("replay-1", record["reply_turn_replay_id"])
        self.assertEqual("thread-1", record["thread_id"])
        self.assertIn("fast", record["active_lanes"])
        self.assertEqual(["fast", "observer"], record["selected_stream_lanes"])
        self.assertFalse(record["needed_repair"])
        self.assertTrue(any(lane["lane"] == "observer" for lane in record["lanes"]))

    def test_council_turn_record_labels_all_lanes_abstained_synthesis(self):
        inbound = {"id": "msg-1", "thread_id": "thread-1", "body": "What is 2+2?"}
        reply = {"id": "reply-1", "thread_id": "thread-1", "body": "4."}
        contract = eve.build_reply_turn_contract(inbound, inbound["body"], [inbound])
        def fake_quarantine(model, prefer_runtime=False):
            return {"active": model == "eve-fast", "reason": "unit test", "quarantined_until": ""}

        with (
            patch.object(eve, "reply_lane_learning_adjustments", return_value={}),
            patch.object(eve, "reply_model_quarantine_status", side_effect=fake_quarantine),
        ):
            council = eve.build_reply_council_state(
                self.config(),
                inbound["body"],
                reply_posture="general",
                allow_tools=False,
            )

        record = eve.build_reply_council_turn_record(
            inbound_message=inbound,
            reply_message=reply,
            turn_contract=contract,
            reply_council=council,
            used_model="eve-fast",
            quality_issues=[],
            semantic_judgment={"ok": True, "issues": []},
        )

        self.assertIsNotNone(record)
        self.assertFalse(record["lane_backed"])
        self.assertEqual("all_lanes_abstained_synthesis", record["fallback_label"])
        self.assertTrue(record["needed_repair"])

    def test_tool_capable_turn_keeps_fast_lane_accountable_for_text(self):
        council = eve.build_reply_council_state(
            self.config(),
            "Can you check this and tell me what happened?",
            reply_posture="practical",
            allow_tools=True,
        )

        self.assertIn("fast", council["active_lanes"])
        self.assertNotIn("fast", council["abstained_lanes"])
        self.assertEqual("contribute", next(lane for lane in council["lanes"] if lane["lane"] == "fast")["stance"])

        inbound = {"id": "msg-1", "thread_id": "thread-1", "body": "Can you check this and tell me what happened?"}
        reply = {"id": "reply-1", "thread_id": "thread-1", "body": "I need a verified action result before I claim what happened."}
        record = eve.build_reply_council_turn_record(
            inbound_message=inbound,
            reply_message=reply,
            turn_contract=eve.build_reply_turn_contract(inbound, inbound["body"], [inbound]),
            reply_council=council,
            used_model="eve-fast",
            quality_issues=[],
            semantic_judgment={"ok": True, "issues": []},
        )

        self.assertIsNotNone(record)
        self.assertTrue(record["lane_backed"])
        self.assertEqual("", record["fallback_label"])

    def test_conversation_spine_record_marks_real_user_turn_visible(self):
        message = {
            "id": "550e8400-e29b-41d4-a716-446655440001",
            "thread_id": "550e8400-e29b-41d4-a716-446655440002",
            "timestamp": "2026-05-06T20:00:00+00:00",
            "sender": "user",
            "recipient": "eve",
            "kind": "user_message",
            "subject": "Continue",
            "body": "Keep going.",
            "metadata": {},
        }

        record = eve.build_conversation_spine_record(message, source="unit_test")

        self.assertEqual("eve_conversation_turn.v1", record["schema_id"])
        self.assertEqual("user", record["role"])
        self.assertEqual("inbound", record["direction"])
        self.assertFalse(record["synthetic"])
        self.assertTrue(record["conversation_visible"])
        self.assertEqual("550e8400-e29b-41d4-a716-446655440001", record["message_id"])

    def test_reply_turn_replay_records_compact_council_turn(self):
        inbound = {
            "id": "550e8400-e29b-41d4-a716-446655440011",
            "thread_id": "550e8400-e29b-41d4-a716-446655440012",
            "body": "What is the purpose of life?",
        }
        reply = {
            "id": "550e8400-e29b-41d4-a716-446655440013",
            "thread_id": "550e8400-e29b-41d4-a716-446655440012",
            "body": eve.direct_existential_reply(inbound["body"]),
        }
        contract = eve.build_reply_turn_contract(inbound, inbound["body"], [inbound])
        council = eve.build_reply_council_state(
            self.config(),
            inbound["body"],
            reply_posture="relational",
            allow_tools=False,
        )
        saved = []

        def fake_append(path, record):
            saved.append((path.name, dict(record)))
            return record

        with (
            patch.object(eve, "append_jsonl_record", side_effect=fake_append),
            patch.object(eve, "mirror_store_file_to_runtime"),
            patch.object(eve, "record_reply_lane_learning_from_replay"),
        ):
            replay = eve.record_reply_turn_replay(
                inbound_message=inbound,
                reply_message=reply,
                turn_contract=contract,
                reply_council=council,
                used_model="eve-fast",
                quality_issues=[],
                semantic_judgment={"ok": True, "issues": []},
                stream_result=None,
            )

        saved_by_name = {name: record for name, record in saved}
        self.assertIn("reply_turn_replays.jsonl", saved_by_name)
        self.assertIn("reply_council_turns.jsonl", saved_by_name)
        self.assertIn("conscious_state_audit.jsonl", saved_by_name)
        self.assertEqual(
            replay["id"],
            saved_by_name["reply_council_turns.jsonl"]["reply_turn_replay_id"],
        )
        self.assertEqual("eve-fast", saved_by_name["reply_council_turns.jsonl"]["synthesis_model"])

    def test_synthetic_reply_replay_is_marked_and_does_not_train_lane_learning(self):
        inbound = {"id": "msg-1", "thread_id": "thread-1", "body": "What is the next grounded runtime step here?"}
        reply = {"id": "reply-1", "thread_id": "thread-1", "body": "The next grounded step is to stay with the live thread."}
        contract = eve.build_reply_turn_contract(inbound, inbound["body"], [inbound])
        council = eve.build_reply_council_state(
            self.config(),
            inbound["body"],
            reply_posture="general",
            allow_tools=False,
        )
        saved = []

        def fake_append(path, record):
            saved.append((path.name, dict(record)))
            return record

        with (
            patch.object(eve, "append_jsonl_record", side_effect=fake_append),
            patch.object(eve, "mirror_store_file_to_runtime"),
            patch.object(eve.eve_tracing, "record_span"),
            patch.object(eve, "record_reply_lane_learning_from_replay") as lane_learning,
        ):
            replay = eve.record_reply_turn_replay(
                inbound_message=inbound,
                reply_message=reply,
                turn_contract=contract,
                reply_council=council,
                used_model="eve-fast",
                quality_issues=[],
                semantic_judgment={"ok": True, "issues": []},
            )

        self.assertTrue(replay["synthetic"])
        self.assertIn("fixture_prompt_marker", replay["synthetic_reasons"])
        self.assertTrue(saved[1][1]["synthetic"])
        lane_learning.assert_not_called()

    def test_reply_generation_failure_replay_does_not_train_lane_learning(self):
        inbound = {
            "id": "550e8400-e29b-41d4-a716-446655440021",
            "thread_id": "550e8400-e29b-41d4-a716-446655440022",
            "body": "What is the latest runtime answer?",
        }
        reply = {
            "id": "550e8400-e29b-41d4-a716-446655440023",
            "thread_id": "550e8400-e29b-41d4-a716-446655440022",
            "body": "I could not answer this turn.",
        }
        contract = eve.build_reply_turn_contract(inbound, inbound["body"], [inbound])
        council = eve.build_reply_council_state(
            self.config(),
            inbound["body"],
            reply_posture="practical",
            allow_tools=False,
        )

        def fake_append(path, record):
            return record

        with (
            patch.object(eve, "append_jsonl_record", side_effect=fake_append),
            patch.object(eve, "mirror_store_file_to_runtime"),
            patch.object(eve.eve_tracing, "record_span"),
            patch.object(eve, "record_reply_lane_learning_from_replay") as lane_learning,
        ):
            replay = eve.record_reply_turn_replay(
                inbound_message=inbound,
                reply_message=reply,
                turn_contract=contract,
                reply_council=council,
                used_model="reply-generation-failure-recorder",
                quality_issues=["Reply generation failed before an answer was produced."],
                semantic_judgment={"ok": False, "issues": ["reply_generation_failed"]},
                source="reply_generation_failure",
                fallback_used=True,
            )

        self.assertFalse(replay["synthetic"])
        lane_learning.assert_not_called()


class ReplyLaneLearningSymmetryTests(unittest.TestCase):
    def test_v1_lane_learning_migration_discards_circular_adjustments(self):
        legacy = {
            "schema_version": "eve.reply_lane_learning.v1",
            "lanes": {
                "fast": {
                    "lane": "fast",
                    "adjustment": 0.18,
                    "reinforcements": 24,
                    "last_reason": "Verified-clean reply reinforced the used lane.",
                }
            },
        }

        with patch.object(eve, "load_json_object", return_value=legacy):
            migrated = eve.load_reply_lane_learning(prefer_runtime=False)

        self.assertEqual(eve.REPLY_LANE_LEARNING_SCHEMA_VERSION, migrated["schema_version"])
        self.assertEqual({}, migrated["lanes"])
        self.assertIn("clean delivery", migrated["migration_note"])

    def test_schema_less_lane_store_cannot_inherit_current_schema(self):
        legacy = {
            "updated_at": "2026-07-13T05:19:04+00:00",
            "lanes": {
                "fast": {
                    "lane": "fast",
                    "adjustment": 0.18,
                    "reinforcements": 24,
                    "last_reason": "Verified-clean reply reinforced the used lane.",
                }
            },
        }

        with patch.object(eve, "load_json_object", return_value=legacy):
            migrated = eve.load_reply_lane_learning(prefer_runtime=False)

        self.assertEqual(eve.REPLY_LANE_LEARNING_SCHEMA_VERSION, migrated["schema_version"])
        self.assertEqual({}, migrated["lanes"])
        self.assertEqual("missing", migrated["migrated_from_schema"])
        self.assertIn("multi-faculty", migrated["migration_note"])

    def test_contributor_trace_uses_logical_roles_not_shared_model_aliases(self):
        council = {
            "active_lanes": ["fast", "observer", "deep"],
            "lanes": [
                {"lane": "fast", "model": "eve-fast"},
                {"lane": "relationship", "model": "eve-fast"},
                {"lane": "observer", "model": "eve-observer"},
                {"lane": "planner", "model": "eve-observer"},
                {"lane": "deep", "model": "eve-deep"},
            ],
        }
        stream = {
            "packets": [
                {"stream": "fast"},
                {"stream": "observer"},
                {"stream": "deep"},
            ],
            "stream_models": {
                "fast": "eve-fast",
                "observer": "eve-observer",
                "deep": "eve-deep",
            },
            "synthesis_model": "eve-deep",
            "synthesis_selection": {
                "reason": "deep_selected_for_multi_lane_integration",
            },
        }

        contributors = eve.build_reply_faculty_contributors(council, stream, "eve-deep")
        by_lane = {item["lane"]: item for item in contributors}

        self.assertEqual({"fast", "observer", "deep"}, set(by_lane))
        self.assertAlmostEqual(0.25, by_lane["fast"]["credit_weight"], places=6)
        self.assertAlmostEqual(0.25, by_lane["observer"]["credit_weight"], places=6)
        self.assertAlmostEqual(0.50, by_lane["deep"]["credit_weight"], places=6)
        self.assertEqual(
            {"executed_packet", "final_synthesis"},
            set(by_lane["deep"]["roles"]),
        )
        self.assertTrue(all(item["execution_proven"] for item in contributors))

    def test_shared_substrate_model_does_not_override_single_logical_admission(self):
        replay = {
            "model": "eve-fast",
            "reply_council": {
                "active_lanes": ["relationship"],
                "lanes": [
                    {"lane": "fast", "model": "eve-fast"},
                    {"lane": "relationship", "model": "eve-fast"},
                ],
            },
        }

        self.assertEqual("relationship", eve.resolve_reply_used_lane(replay))

    def test_decay_moves_adjustments_toward_zero(self):
        config = dict(eve.DEFAULT_CONFIG)
        state = {
            "last_decay_at": "2026-07-17T12:00:00+00:00",
            "lanes": {
                "fast": {"lane": "fast", "adjustment": -0.18},
                "observer": {"lane": "observer", "adjustment": 0.09},
            },
        }
        eve.decay_reply_lane_learning(
            state,
            config,
            now="2026-07-18T12:00:00+00:00",
        )
        self.assertAlmostEqual(state["lanes"]["fast"]["adjustment"], -0.16, places=3)
        self.assertAlmostEqual(state["lanes"]["observer"]["adjustment"], 0.07, places=3)
        self.assertEqual("2026-07-18T12:00:00+00:00", state["last_decay_at"])

    def test_zero_decay_is_not_replaced_by_default(self):
        config = dict(eve.DEFAULT_CONFIG)
        config["reply_lane_learning_decay"] = 0.0
        state = {
            "last_decay_at": "2026-07-01T00:00:00+00:00",
            "lanes": {"fast": {"lane": "fast", "adjustment": -0.18}},
        }

        eve.decay_reply_lane_learning(
            state,
            config,
            now="2026-07-18T00:00:00+00:00",
        )

        self.assertAlmostEqual(-0.18, state["lanes"]["fast"]["adjustment"], places=3)

    def test_clean_reply_waits_for_user_consequence_before_rewarding_lane(self):
        config = dict(eve.DEFAULT_CONFIG)
        state = {"lanes": {"fast": {"lane": "fast", "adjustment": -0.18}}}
        record = {
            "model": "eve-fast",
            "semantic_judgment": {"ok": True},
            "quality_issues": [],
            "reply_council": {"lanes": [{"lane": "fast", "model": "eve-fast"}], "active_lanes": ["fast"]},
        }
        with patch.object(eve, "load_reply_lane_learning", return_value=state), patch.object(eve, "save_reply_lane_learning"):
            out = eve.record_reply_lane_learning_from_replay(record, config=config)
        # Delivery quality is process evidence only: no success reward before
        # the user reacts. A newly observed store only starts the decay clock.
        self.assertAlmostEqual(out["lanes"]["fast"]["adjustment"], -0.18, places=3)
        self.assertEqual(0, out["lanes"]["fast"].get("reinforcements", 0))

    def test_explicit_user_acceptance_reinforces_used_lane_once(self):
        config = dict(eve.DEFAULT_CONFIG)
        config["reply_lane_learning_decay"] = 0.0
        state = {"lanes": {"fast": {"lane": "fast", "adjustment": 0.0}}}
        replay = {
            "model": "eve-fast",
            "reply_council": {
                "lanes": [{"lane": "fast", "model": "eve-fast"}],
                "active_lanes": ["fast"],
            },
        }
        with (
            patch.object(eve, "load_reply_lane_learning", return_value=state),
            patch.object(eve, "save_reply_lane_learning"),
        ):
            first = eve.record_reply_lane_learning_from_user_consequence(
                replay,
                outcome_ok=True,
                evidence_id="reply-consequence:r1:u2",
                config=config,
            )
            second = eve.record_reply_lane_learning_from_user_consequence(
                replay,
                outcome_ok=True,
                evidence_id="reply-consequence:r1:u2",
                config=config,
            )

        self.assertAlmostEqual(0.03, first["lanes"]["fast"]["adjustment"], places=3)
        self.assertEqual(1, first["lanes"]["fast"]["reinforcements"])
        self.assertEqual(first, second)

    def test_lived_outcome_is_fractionally_shared_across_executed_contributors(self):
        config = dict(eve.DEFAULT_CONFIG)
        config["reply_lane_learning_decay"] = 0.0
        state = {
            "schema_version": eve.REPLY_LANE_LEARNING_SCHEMA_VERSION,
            "lanes": {},
            "applied_consequence_ids": [],
            "evidence_records": [],
        }
        replay = {
            "reply_message_id": "r-shared",
            "conscious_cycle_id": "cycle-shared",
            "faculty_contributors": [
                {
                    "lane": "fast",
                    "roles": ["executed_packet"],
                    "credit_weight": 0.25,
                    "trace_basis": "executed_reply_packet",
                    "execution_proven": True,
                },
                {
                    "lane": "observer",
                    "roles": ["executed_packet"],
                    "credit_weight": 0.25,
                    "trace_basis": "executed_reply_packet",
                    "execution_proven": True,
                },
                {
                    "lane": "deep",
                    "roles": ["executed_packet", "final_synthesis"],
                    "credit_weight": 0.50,
                    "trace_basis": "executed_synthesis_contract",
                    "execution_proven": True,
                },
            ],
        }
        with (
            patch.object(eve, "load_reply_lane_learning", return_value=state),
            patch.object(eve, "save_reply_lane_learning"),
        ):
            first = eve.record_reply_lane_learning_from_user_consequence(
                replay,
                outcome_ok=False,
                evidence_id="reply-consequence:r-shared:u2",
                config=config,
            )
            second = eve.record_reply_lane_learning_from_user_consequence(
                replay,
                outcome_ok=False,
                evidence_id="reply-consequence:r-shared:u2",
                config=config,
            )

        self.assertAlmostEqual(-0.015, first["lanes"]["fast"]["adjustment"], places=3)
        self.assertAlmostEqual(-0.015, first["lanes"]["observer"]["adjustment"], places=3)
        self.assertAlmostEqual(-0.030, first["lanes"]["deep"]["adjustment"], places=3)
        self.assertEqual(1, len(first["evidence_records"]))
        self.assertEqual("shared_lived_outcome", first["evidence_records"][0]["credit_kind"])
        self.assertEqual("executed_contributor_trace", first["evidence_records"][0]["attribution_certainty"])
        self.assertEqual(first, second)

    def test_external_matched_ablation_applies_small_unique_causal_pressure_once(self):
        config = dict(eve.DEFAULT_CONFIG)
        config["reply_lane_learning_decay"] = 0.0
        state = {
            "schema_version": eve.REPLY_LANE_LEARNING_SCHEMA_VERSION,
            "lanes": {},
            "applied_consequence_ids": [],
            "applied_causal_evidence_ids": [],
            "evidence_records": [],
            "causal_evidence_records": [],
        }
        packet = {
            "schema_version": eve.EXTERNAL_FACULTY_CAUSAL_EVIDENCE_SCHEMA,
            "evidence_id": "causal-1",
            "private_run_digest": "b" * 64,
            "evaluated_behavior_fingerprint": eve.faculty_behavior_fingerprint_payload()[
                "fingerprint"
            ],
            "evaluated_at": "2026-07-18T12:00:00+00:00",
            "evaluator": {
                "kind": "codex_external_operator",
                "independent_from_eve": True,
            },
            "matched_design": {
                "matched_context": True,
                "fixed_synthesis_model": "eve-deep",
                "lesion_scope": "packet_contribution_only",
                "ordinary_runtime_routing_changed": False,
                "blind_review": True,
            },
            "privacy": {
                "contains_prompt_text": False,
                "contains_response_text": False,
                "contains_rubric_text": False,
                "safe_for_eve_ingest": True,
            },
            "score_scale_max": 5.0,
            "probe_count": 3,
            "systemic_failure": {"present": False, "kind": ""},
            "lanes": [
                {
                    "lane": "observer",
                    "comparisons": 3,
                    "mean_baseline_score": 5.0,
                    "mean_ablated_score": 3.0,
                    "positive_count": 3,
                    "negative_count": 0,
                    "neutral_count": 0,
                    "shared_failure_count": 0,
                }
            ],
        }
        with (
            patch.object(eve, "load_reply_lane_learning", return_value=state),
            patch.object(eve, "save_reply_lane_learning"),
        ):
            first = eve.record_reply_lane_learning_from_causal_evidence(
                packet, config=config
            )
            second = eve.record_reply_lane_learning_from_causal_evidence(
                packet, config=config
            )

        self.assertAlmostEqual(0.015, first["lanes"]["observer"]["adjustment"], places=3)
        self.assertEqual(3, first["lanes"]["observer"]["causal_comparisons"])
        self.assertEqual(1, len(first["causal_evidence_records"]))
        self.assertEqual(first, second)

    def test_external_causal_pressure_waits_for_cumulative_matched_comparisons(self):
        config = dict(eve.DEFAULT_CONFIG)
        config["reply_lane_learning_decay"] = 0.0
        config["reply_lane_causal_min_comparisons"] = 3
        state = {
            "schema_version": eve.REPLY_LANE_LEARNING_SCHEMA_VERSION,
            "lanes": {},
            "applied_causal_evidence_ids": [],
            "causal_evidence_records": [],
        }
        base_packet = {
            "schema_version": eve.EXTERNAL_FACULTY_CAUSAL_EVIDENCE_SCHEMA,
            "private_run_digest": "d" * 64,
            "evaluated_behavior_fingerprint": eve.faculty_behavior_fingerprint_payload()[
                "fingerprint"
            ],
            "evaluator": {
                "kind": "codex_external_operator",
                "independent_from_eve": True,
            },
            "matched_design": {
                "matched_context": True,
                "fixed_synthesis_model": "eve-deep",
                "lesion_scope": "packet_contribution_only",
                "ordinary_runtime_routing_changed": False,
                "blind_review": True,
            },
            "privacy": {
                "contains_prompt_text": False,
                "contains_response_text": False,
                "contains_rubric_text": False,
                "safe_for_eve_ingest": True,
            },
            "score_scale_max": 5.0,
            "probe_count": 1,
            "systemic_failure": {"present": False, "kind": ""},
            "lanes": [
                {
                    "lane": "observer",
                    "comparisons": 1,
                    "mean_baseline_score": 5.0,
                    "mean_ablated_score": 3.0,
                    "positive_count": 1,
                }
            ],
        }
        adjustments = []
        with (
            patch.object(eve, "load_reply_lane_learning", return_value=state),
            patch.object(eve, "save_reply_lane_learning"),
        ):
            for index in range(3):
                packet = {**base_packet, "evidence_id": f"causal-cumulative-{index}"}
                learned = eve.record_reply_lane_learning_from_causal_evidence(
                    packet, config=config
                )
                adjustments.append(
                    learned["lanes"]["observer"].get("adjustment", 0.0)
                )

        self.assertEqual([0.0, 0.0, 0.015], adjustments)
        self.assertEqual(3, learned["lanes"]["observer"]["causal_comparisons"])
        self.assertEqual(3, len(learned["causal_evidence_records"]))

    def test_shared_all_condition_failure_never_blames_one_faculty(self):
        config = dict(eve.DEFAULT_CONFIG)
        config["reply_lane_learning_decay"] = 0.0
        state = {
            "schema_version": eve.REPLY_LANE_LEARNING_SCHEMA_VERSION,
            "lanes": {},
            "applied_causal_evidence_ids": [],
            "causal_evidence_records": [],
        }
        packet = {
            "schema_version": eve.EXTERNAL_FACULTY_CAUSAL_EVIDENCE_SCHEMA,
            "evidence_id": "shared-defect-1",
            "private_run_digest": "c" * 64,
            "evaluated_behavior_fingerprint": eve.faculty_behavior_fingerprint_payload()[
                "fingerprint"
            ],
            "evaluator": {
                "kind": "codex_external_operator",
                "independent_from_eve": True,
            },
            "matched_design": {
                "matched_context": True,
                "fixed_synthesis_model": "eve-deep",
                "lesion_scope": "packet_contribution_only",
                "ordinary_runtime_routing_changed": False,
                "blind_review": True,
            },
            "privacy": {
                "contains_prompt_text": False,
                "contains_response_text": False,
                "contains_rubric_text": False,
                "safe_for_eve_ingest": True,
            },
            "score_scale_max": 5.0,
            "systemic_failure": {
                "present": True,
                "kind": "capability_self_model_missing",
            },
            "lanes": [
                {
                    "lane": "planner",
                    "comparisons": 5,
                    "mean_baseline_score": 1.0,
                    "mean_ablated_score": 1.0,
                    "shared_failure_count": 5,
                }
            ],
        }
        with (
            patch.object(eve, "load_reply_lane_learning", return_value=state),
            patch.object(eve, "save_reply_lane_learning"),
        ):
            learned = eve.record_reply_lane_learning_from_causal_evidence(
                packet, config=config
            )

        self.assertEqual(0.0, learned["lanes"]["planner"].get("adjustment", 0.0))
        self.assertEqual(0, learned["lanes"]["planner"]["causal_comparisons"])
        self.assertEqual(5, learned["lanes"]["planner"]["causal_shared_failure_count"])
        self.assertFalse(
            learned["causal_evidence_records"][0]["lanes"][0][
                "pressure_adjustment_eligible"
            ]
        )

    def test_behavior_epoch_change_retires_only_external_causal_pressure(self):
        state = {
            "schema_version": eve.REPLY_LANE_LEARNING_SCHEMA_VERSION,
            "causal_behavior_fingerprint": "a" * 64,
            "lanes": {
                "observer": {
                    "lane": "observer",
                    "adjustment": -0.04,
                    "causal_adjustment_total": -0.01,
                    "causal_comparisons": 3,
                    "causal_effect_sum": -4.0,
                    "causal_effect_mean": -1.333333,
                    "last_reason": "External blind matched-ablation evidence found a negative unique faculty contribution.",
                }
            },
            "applied_consequence_ids": ["lived-1"],
            "applied_causal_evidence_ids": ["causal-old"],
            "evidence_records": [{"evidence_id": "lived-1", "credit_kind": "shared_lived_outcome"}],
            "causal_evidence_records": [
                {
                    "evidence_id": "causal-old",
                    "lanes": [
                        {"lane": "observer", "pressure_adjustment_delta": -0.01}
                    ],
                }
            ],
        }

        changed = eve.reconcile_reply_lane_causal_behavior_epoch(
            state,
            dict(eve.DEFAULT_CONFIG),
            current_fingerprint="b" * 64,
        )

        self.assertTrue(changed)
        self.assertAlmostEqual(-0.03, state["lanes"]["observer"]["adjustment"], places=3)
        self.assertEqual(0.0, state["lanes"]["observer"]["causal_adjustment_total"])
        self.assertNotIn("causal_comparisons", state["lanes"]["observer"])
        self.assertEqual(["lived-1"], state["applied_consequence_ids"])
        self.assertEqual(1, len(state["evidence_records"]))
        self.assertEqual([], state["applied_causal_evidence_ids"])
        self.assertEqual([], state["causal_evidence_records"])
        self.assertEqual("b" * 64, state["causal_behavior_fingerprint"])
        self.assertEqual(1, len(state["retired_causal_epochs"]))

    def test_external_causal_packet_rejects_stale_behavior_fingerprint(self):
        packet = {
            "schema_version": eve.EXTERNAL_FACULTY_CAUSAL_EVIDENCE_SCHEMA,
            "evidence_id": "stale-causal",
            "private_run_digest": "a" * 64,
            "evaluated_behavior_fingerprint": "0" * 64,
        }
        with self.assertRaisesRegex(SystemExit, "stale"):
            eve.normalize_external_faculty_causal_evidence(packet)

    def test_external_causal_packet_rejects_private_prompt_or_response_text(self):
        packet = {
            "schema_version": eve.EXTERNAL_FACULTY_CAUSAL_EVIDENCE_SCHEMA,
            "prompt": "hidden evaluator prompt",
        }

        with self.assertRaises(SystemExit):
            eve.normalize_external_faculty_causal_evidence(packet)

    def test_external_causal_ingest_path_accepts_private_storage_and_rejects_repo(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            private_packet = Path(temp_dir) / "causal.json"
            private_packet.write_text("{}", encoding="utf-8")
            self.assertEqual(
                private_packet.resolve(),
                eve.external_faculty_causal_evidence_input_path(private_packet),
            )
        with self.assertRaises(SystemExit):
            eve.external_faculty_causal_evidence_input_path(eve.ROOT / "README.md")


class ConversationalPredictionTests(unittest.TestCase):
    def test_predict_user_reaction_classes(self):
        self.assertEqual(eve.predict_user_reaction("What would help here?"), "answer_question")
        self.assertEqual(eve.predict_user_reaction("I'll fix that now."), "accept_or_continue")
        self.assertEqual(eve.predict_user_reaction("The build is green."), "continue")

    def test_correction_is_negative_evidence_even_for_legacy_prediction(self):
        prior = {"predicted_reaction": "continue", "reply_message_id": "r1", "conscious_cycle_id": "c1"}
        with (
            patch.object(eve, "append_prediction_check_record", return_value=True),
            patch.object(eve, "join_delayed_reply_consequence", return_value={"applied": True}),
        ):
            miss = eve.record_conversational_prediction_check(
                prior,
                {"id": "u1", "body": "no, that's wrong, you missed my question", "thread_id": "t1"},
            )
            hit = eve.record_conversational_prediction_check(
                {**prior, "reply_message_id": "r2"},
                {"id": "u2", "body": "great, thanks", "thread_id": "t1"},
            )
            anticipated = eve.record_conversational_prediction_check(
                {
                    "predicted_reaction": "accept_or_correct",
                    "reply_message_id": "r3",
                    "conscious_cycle_id": "c3",
                },
                {"id": "u3", "body": "no that's wrong", "thread_id": "t1"},
            )
        self.assertFalse(miss["fulfilled"])
        self.assertGreater(miss["error_magnitude"], 0)
        self.assertTrue(miss["consequence_observed"])
        self.assertFalse(miss["outcome_ok"])
        self.assertTrue(hit["fulfilled"])
        self.assertEqual(hit["error_magnitude"], 0)
        self.assertTrue(hit["outcome_ok"])
        # The old prediction contract cannot make every correction a success.
        self.assertFalse(anticipated["fulfilled"])
        self.assertGreater(anticipated["error_magnitude"], 0)

    def test_neutral_continuation_does_not_award_reply_success(self):
        prior = {
            "predicted_reaction": "continue",
            "reply_message_id": "r-neutral",
            "conscious_cycle_id": "c-neutral",
        }
        with (
            patch.object(eve, "append_prediction_check_record", return_value=True),
            patch.object(eve, "join_delayed_reply_consequence") as join,
        ):
            record = eve.record_conversational_prediction_check(
                prior,
                {"id": "u-neutral", "body": "Here is another detail.", "thread_id": "t1"},
            )

        self.assertIsNone(record["fulfilled"])
        self.assertIsNone(record["error_magnitude"])
        self.assertFalse(record["consequence_observed"])
        self.assertIsNone(record["outcome_ok"])
        join.assert_not_called()

    def test_scope_reframe_is_detected_as_lived_correction(self):
        correction = eve.classify_user_correction(
            "I mean real consciousness. Read the README and fix the architecture."
        )

        self.assertEqual("goal_or_scope_correction", correction["issue_type"])
        self.assertEqual("high", correction["severity"])

    def test_reply_replay_closes_process_but_leaves_user_consequence_pending(self):
        inbound = {"id": "u1", "thread_id": "t1", "sender": "user", "body": "Explain it."}
        reply = {"id": "r1", "thread_id": "t1", "sender": "eve", "body": "Here is the explanation."}
        opened = {
            "cycle_id": "c1",
            "action_model": {"selected_intention": {"id": "respond_to_user"}},
        }
        completed = {
            "cycle_id": "c1",
            "cycle_outcome": {"outcome_observed": False, "overall_prediction_error": 0},
        }
        with (
            patch.object(eve, "read_reply_turn_replays", return_value=[]),
            patch.object(eve, "complete_recurrent_conscious_cycle", return_value=completed) as complete,
            patch.object(eve, "append_jsonl_record", side_effect=lambda _path, record: record),
            patch.object(eve, "mirror_store_file_to_runtime"),
            patch.object(eve, "record_reply_council_turn_safe"),
            patch.object(eve, "record_reply_lane_learning_from_replay"),
            patch.object(eve.eve_tracing, "record_span"),
        ):
            replay = eve.record_reply_turn_replay(
                inbound_message=inbound,
                reply_message=reply,
                turn_contract={"latest_message": "Explain it."},
                reply_council={"active_lanes": ["fast"]},
                used_model="eve-fast",
                quality_issues=[],
                semantic_judgment={"ok": True},
                conscious_state=opened,
            )

        outcome = complete.call_args.kwargs["outcome"]
        self.assertIsNone(outcome["ok"])
        self.assertFalse(outcome["observed"])
        self.assertTrue(outcome["delivery_ok"])
        self.assertEqual("pending_user_evidence", replay["reply_consequence_status"])
        self.assertEqual("respond_to_user", replay["conscious_action_id"])
        self.assertEqual(["fast"], [item["lane"] for item in replay["faculty_contributors"]])
        self.assertEqual(["direct_reply"], replay["faculty_contributors"][0]["roles"])
        self.assertTrue(replay["faculty_contributors"][0]["execution_proven"])

    def test_reply_does_not_masquerade_as_unexecuted_selected_intention(self):
        inbound = {
            "id": "550e8400-e29b-41d4-a716-446655440101",
            "thread_id": "550e8400-e29b-41d4-a716-446655440102",
            "sender": "user",
            "body": "What is on your mind?",
        }
        reply = {
            "id": "550e8400-e29b-41d4-a716-446655440103",
            "thread_id": inbound["thread_id"],
            "sender": "eve",
            "body": "My current focus is resolving the runtime inquiry.",
            "metadata": {"action_attempts": []},
        }
        opened = {
            "cycle_id": "c-intended-not-executed",
            "action_model": {"selected_intention": {"id": "openclaw_log_check"}},
        }
        completed = {
            "cycle_id": opened["cycle_id"],
            "cycle_outcome": {"outcome_observed": False},
        }
        with (
            patch.object(eve, "read_reply_turn_replays", return_value=[]),
            patch.object(eve, "complete_recurrent_conscious_cycle", return_value=completed) as complete,
            patch.object(eve, "append_jsonl_record", side_effect=lambda _path, record: record),
            patch.object(eve, "mirror_store_file_to_runtime"),
            patch.object(eve, "record_reply_council_turn_safe"),
            patch.object(eve, "record_reply_lane_learning_from_replay"),
            patch.object(eve.eve_tracing, "record_span"),
        ):
            replay = eve.record_reply_turn_replay(
                inbound_message=inbound,
                reply_message=reply,
                turn_contract={"latest_message": inbound["body"]},
                reply_council={"active_lanes": ["fast"]},
                used_model="eve-fast",
                quality_issues=[],
                semantic_judgment={"ok": True},
                conscious_state=opened,
            )

        self.assertEqual("respond_to_user", replay["conscious_action_id"])
        self.assertEqual(
            "respond_to_user",
            complete.call_args.kwargs["actual_process"]["action_id"],
        )

    def test_reply_uses_recorded_bounded_action_attempt_as_actual_action(self):
        inbound = {
            "id": "550e8400-e29b-41d4-a716-446655440111",
            "thread_id": "550e8400-e29b-41d4-a716-446655440112",
            "sender": "user",
            "body": "Run the bounded log check and report it.",
        }
        reply = {
            "id": "550e8400-e29b-41d4-a716-446655440113",
            "thread_id": inbound["thread_id"],
            "sender": "eve",
            "body": "The bounded log check completed with a verified result.",
            "metadata": {
                "action_attempts": [
                    {
                        "action_id": "openclaw_log_check",
                        "execution_id": "exec-1",
                        "executed": True,
                        "tree_status": "SUCCESS",
                        "verification_ok": True,
                    }
                ]
            },
        }
        opened = {
            "cycle_id": "c-intended-executed",
            "action_model": {"selected_intention": {"id": "openclaw_log_check"}},
        }
        completed = {
            "cycle_id": opened["cycle_id"],
            "cycle_outcome": {"outcome_observed": False},
        }
        with (
            patch.object(eve, "read_reply_turn_replays", return_value=[]),
            patch.object(eve, "complete_recurrent_conscious_cycle", return_value=completed) as complete,
            patch.object(eve, "append_jsonl_record", side_effect=lambda _path, record: record),
            patch.object(eve, "mirror_store_file_to_runtime"),
            patch.object(eve, "record_reply_council_turn_safe"),
            patch.object(eve, "record_reply_lane_learning_from_replay"),
            patch.object(eve.eve_tracing, "record_span"),
        ):
            replay = eve.record_reply_turn_replay(
                inbound_message=inbound,
                reply_message=reply,
                turn_contract={"latest_message": inbound["body"]},
                reply_council={"active_lanes": ["fast"]},
                used_model="eve-fast",
                quality_issues=[],
                semantic_judgment={"ok": True},
                conscious_state=opened,
            )

        self.assertEqual("openclaw_log_check", replay["conscious_action_id"])
        self.assertEqual(
            "openclaw_log_check",
            complete.call_args.kwargs["actual_process"]["action_id"],
        )

    def test_synthetic_inbound_cannot_close_a_lived_reply_consequence(self):
        with (
            patch.object(eve, "read_reply_turn_replays") as read_replays,
            patch.object(eve, "record_conversational_prediction_check") as record,
        ):
            result = eve.observe_inbound_reply_consequence(
                {
                    "id": "eval-u1",
                    "thread_id": "t1",
                    "sender": "user",
                    "body": "great",
                    "metadata": {"conversation_class": "synthetic_eval"},
                }
            )

        self.assertIsNone(result)
        read_replays.assert_not_called()
        record.assert_not_called()

    def test_bridge_joins_feedback_atomically_without_replacing_current_broadcast(self):
        persisted = eve.default_conscious_state()
        persisted["cycle_id"] = "current-cycle"
        persisted["status"] = "integrated"
        persisted["broadcast"]["content"] = "Current message remains in awareness."
        persisted["metacognition"]["competence_model"]["outcome_prediction"] = 50
        persisted["recurrent"]["checkpoint_digest"] = ""

        def update(mutator, **_kwargs):
            return mutator(persisted)

        prior = {
            "conscious_cycle_id": "prior-cycle",
            "conscious_action_id": "respond_to_user",
            "reply_message_id": "r1",
        }
        prediction = {
            "consequence_observed": True,
            "outcome_ok": False,
            "observed_message_id": "u2",
            "observed_text": "I mean the real architecture, not a demo.",
            "evidence_id": "reply-consequence:r1:u2",
            "error_magnitude": 70,
        }
        with (
            patch.object(eve.CONSCIOUS_STATE_REPOSITORY, "update", side_effect=update),
            patch.object(eve, "append_conscious_state_audit_event"),
            patch.object(eve, "append_entry"),
            patch.object(
                eve,
                "update_reply_turn_replay_user_consequence",
                return_value=(prior, True),
            ),
            patch.object(eve, "record_reply_lane_learning_from_user_consequence", return_value={}),
        ):
            joined = eve.join_delayed_reply_consequence(prior, prediction)
            retried = eve.join_delayed_reply_consequence(prior, prediction)

        self.assertTrue(joined["applied"])
        self.assertFalse(retried["applied"])
        self.assertEqual("Current message remains in awareness.", persisted["broadcast"]["content"])
        observations = persisted["learning"]["action_models"]["respond_to_user"]["observations"]
        self.assertEqual(1, len(observations))
        self.assertFalse(observations[0]["ok"])
        self.assertEqual("prior-cycle", observations[0]["source_cycle_id"])

    def test_reply_replay_persists_first_lived_consequence_exactly_once(self):
        replay = {
            "id": "replay-1",
            "reply_message_id": "r1",
            "reply_consequence_status": "pending_user_evidence",
        }
        prediction = {
            "timestamp": "2026-07-17T12:01:00+00:00",
            "observed": "correction",
            "observed_message_id": "u2",
            "observed_text": "I mean the real architecture, not a demo.",
            "evidence_id": "reply-consequence:r1:u2",
            "outcome_ok": False,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "reply_turn_replays.jsonl"
            with (
                patch.object(eve, "REPLY_TURN_REPLAYS_PATH", path),
                patch.object(eve, "mirror_store_file_to_runtime"),
            ):
                eve.write_jsonl_records(path, [replay])
                first, first_applied = eve.update_reply_turn_replay_user_consequence(replay, prediction)
                second, second_applied = eve.update_reply_turn_replay_user_consequence(replay, prediction)
                persisted = eve.read_jsonl_records(path)

        self.assertTrue(first_applied)
        self.assertFalse(second_applied)
        self.assertEqual(first, second)
        self.assertEqual(1, len(persisted))
        self.assertTrue(persisted[0]["user_consequence_observed"])
        self.assertFalse(persisted[0]["user_consequence_ok"])
        self.assertEqual("corrected", persisted[0]["reply_consequence_status"])
        self.assertEqual("I mean the real architecture, not a demo.", persisted[0]["user_consequence_observed_text"])

    def test_prediction_ledger_retry_still_rejoins_durable_consequence(self):
        prior = {
            "predicted_reaction": "continue",
            "reply_message_id": "r1",
            "conscious_cycle_id": "c1",
        }
        with (
            patch.object(eve, "append_prediction_check_record", return_value=False),
            patch.object(
                eve,
                "join_delayed_reply_consequence",
                return_value={"applied": False, "evidence_present": True},
            ) as join,
        ):
            record = eve.record_conversational_prediction_check(
                prior,
                {"id": "u2", "body": "No, I mean real consciousness.", "thread_id": "t1"},
            )

        self.assertFalse(record["recorded"])
        self.assertFalse(record["conscious_consequence_joined"])
        join.assert_called_once()


if __name__ == "__main__":
    unittest.main()
