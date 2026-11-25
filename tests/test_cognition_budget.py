import json
import unittest
from unittest.mock import patch
from pathlib import Path

import eve


def fresh_probe_snapshot(*, fast_ms=900.0, deep_ms=2500.0, load_state="hot", ok=True, updated_at=None):
    return {
        "load_state": load_state,
        "model_status": {
            "updated_at": updated_at or eve.utc_now(),
            "preferred_fast_model": "eve-fast",
            "preferred_deep_model": "eve-deep",
            "probes": {
                "eve-fast": {"ok": ok, "wall_ms": fast_ms},
                "eve-deep": {"ok": ok, "wall_ms": deep_ms},
            },
        },
    }


def calm_homeostasis():
    return {"regulation_mode": "steady", "pressures": []}


class CognitionGateTests(unittest.TestCase):
    def setUp(self):
        self.config = dict(eve.DEFAULT_CONFIG)

    def test_fresh_in_budget_probes_read_as_ready(self):
        assessment = eve.cognition_gate_assessment(fresh_probe_snapshot(), self.config, allow_watchdog_fallback=False)
        self.assertEqual("ready", assessment["lane_state"])
        self.assertEqual("lane_latency", assessment["mode"])

    def test_over_budget_or_failed_probe_reads_as_slow(self):
        slow = eve.cognition_gate_assessment(fresh_probe_snapshot(deep_ms=15000), self.config, allow_watchdog_fallback=False)
        failed = eve.cognition_gate_assessment(fresh_probe_snapshot(ok=False), self.config, allow_watchdog_fallback=False)
        self.assertEqual("slow", slow["lane_state"])
        self.assertEqual("slow", failed["lane_state"])

    def test_missing_or_stale_probes_read_as_unknown(self):
        missing = eve.cognition_gate_assessment({"load_state": "hot"}, self.config, allow_watchdog_fallback=False)
        stale = eve.cognition_gate_assessment(
            fresh_probe_snapshot(updated_at="2020-01-01T00:00:00+00:00"), self.config, allow_watchdog_fallback=False
        )
        self.assertEqual("unknown", missing["lane_state"])
        self.assertEqual("unknown", stale["lane_state"])

    def test_load_average_mode_restores_old_behavior(self):
        config = dict(self.config, cognition_gate_mode="load_average")
        assessment = eve.cognition_gate_assessment(fresh_probe_snapshot(), config, allow_watchdog_fallback=False)
        self.assertEqual("unknown", assessment["lane_state"])
        with patch.object(eve, "load_homeostasis", return_value=calm_homeostasis()):
            reason = eve.system_background_gate_reason(fresh_probe_snapshot(), "reflection", config)
        self.assertIn("System load is hot", reason)

    def test_hot_load_with_ready_lanes_does_not_defer(self):
        with patch.object(eve, "load_homeostasis", return_value=calm_homeostasis()), patch.object(
            eve, "load_model_watchdog_status", return_value={}
        ):
            reason = eve.system_background_gate_reason(fresh_probe_snapshot(), "reflection", self.config)
        self.assertIsNone(reason)

    def test_hot_load_without_probes_still_defers(self):
        with patch.object(eve, "load_homeostasis", return_value=calm_homeostasis()), patch.object(
            eve, "load_model_watchdog_status", return_value={}
        ):
            reason = eve.system_background_gate_reason({"load_state": "hot"}, "reflection", self.config)
        self.assertIn("System load is hot", reason)

    def test_bare_snapshot_never_reads_the_watchdog_file(self):
        with patch.object(eve, "load_homeostasis", return_value=calm_homeostasis()), patch.object(
            eve, "load_model_watchdog_status", return_value=fresh_probe_snapshot()["model_status"]
        ) as watchdog:
            reason = eve.system_background_gate_reason({"load_state": "hot"}, "reflection", self.config)
        self.assertIn("System load is hot", reason)
        watchdog.assert_not_called()

    def test_slow_lanes_defer_even_when_load_is_calm(self):
        with patch.object(eve, "load_homeostasis", return_value=calm_homeostasis()), patch.object(
            eve, "load_model_watchdog_status", return_value={}
        ):
            reason = eve.system_background_gate_reason(
                fresh_probe_snapshot(load_state="calm", fast_ms=9000), "reflection", self.config
            )
        self.assertIn("latency budget", reason)

    def test_fresher_watchdog_file_wins_over_stale_snapshot_probes(self):
        stale_snapshot = fresh_probe_snapshot(fast_ms=9000, updated_at="2020-01-01T00:00:00+00:00")
        fresh_file = fresh_probe_snapshot()["model_status"]
        with patch.object(eve, "load_model_watchdog_status", return_value=fresh_file):
            assessment = eve.cognition_gate_assessment(stale_snapshot, self.config)
        self.assertEqual("ready", assessment["lane_state"])
        self.assertEqual("model_watchdog_status", assessment["status_source"])

    def test_hot_alert_names_ready_lanes_and_weighs_less_in_homeostasis(self):
        alerts = eve.system_resource_alerts(fresh_probe_snapshot(), self.config)
        self.assertTrue(any("lanes answer in budget" in alert for alert in alerts))
        homeostasis_ready = eve.build_homeostasis_state(
            source="test",
            human_context={},
            active_mind={},
            state={},
            system_snapshot=fresh_probe_snapshot(),
            threads=[],
            uncertainty_records=[],
            judgment_records=[],
            outcomes=[],
            action_executions=[],
            open_system_tasks=[],
        )
        homeostasis_unknown = eve.build_homeostasis_state(
            source="test",
            human_context={},
            active_mind={},
            state={},
            system_snapshot={"load_state": "hot"},
            threads=[],
            uncertainty_records=[],
            judgment_records=[],
            outcomes=[],
            action_executions=[],
            open_system_tasks=[],
        )
        ready_level = eve.homeostasis_pressure_level(homeostasis_ready, "resource_safety")
        unknown_level = eve.homeostasis_pressure_level(homeostasis_unknown, "resource_safety")
        self.assertLess(ready_level, unknown_level)
        self.assertLess(ready_level, 60)

    def test_ready_lanes_with_a_routine_disk_alert_stay_under_the_stabilize_gate(self):
        snapshot = fresh_probe_snapshot()
        routine_disk_alert = "Writable disk is unusually full at 92.1% used with 147.6 GiB free; avoid large artifacts."
        with patch.object(eve, "disk_pressure_alert", return_value=routine_disk_alert):
            alerts = eve.system_resource_alerts(snapshot, self.config)
            self.assertGreaterEqual(len(alerts), 2)
            homeostasis = eve.build_homeostasis_state(
                source="test",
                human_context={},
                active_mind={},
                state={},
                system_snapshot=snapshot,
                threads=[],
                uncertainty_records=[],
                judgment_records=[],
                outcomes=[],
                action_executions=[],
                open_system_tasks=[],
            )
        self.assertLess(eve.homeostasis_pressure_level(homeostasis, "resource_safety"), 60)

    def test_plain_process_watchdog_with_fresh_status_is_not_reported_missing(self):
        snapshot = {
            "model_status": {"updated_at": "2020-01-01T00:00:00+00:00"},
            "eve_services": {"model_watchdog": {"state": "not running", "last_exit_code": ""}},
        }
        with patch.object(eve, "load_model_watchdog_status", return_value={"updated_at": eve.utc_now()}):
            fresh = eve.model_watchdog_snapshot_alert(snapshot)
        with patch.object(eve, "load_model_watchdog_status", return_value={"updated_at": "2020-01-01T00:00:00+00:00"}):
            stale = eve.model_watchdog_snapshot_alert(snapshot)
        self.assertIsNone(fresh)
        self.assertIn("not running", stale)

    def test_chooser_thresholds_follow_the_one_lane_budget(self):
        aligned = eve.free_run_chooser_lane_thresholds(self.config)
        self.assertEqual(4000.0, aligned["fast_high"])
        self.assertEqual(12000.0, aligned["deep_high"])
        self.assertEqual(6000.0, aligned["deep_medium"])
        legacy = eve.free_run_chooser_lane_thresholds(dict(self.config, cognition_gate_mode="load_average"))
        self.assertEqual(6000.0, legacy["deep_high"])
        self.assertEqual(2200.0, legacy["fast_high"])

    def test_chooser_lane_state_neutralizes_hot_load(self):
        ready = eve.cognition_lane_budget_state(self.config, fast_probe_ms=900, deep_probe_ms=2500)
        unknown = eve.cognition_lane_budget_state(self.config, fast_probe_ms=None, deep_probe_ms=2500)
        self.assertEqual("ready", ready)
        self.assertEqual("unknown", unknown)


class ContinuousThoughtAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.config = dict(eve.DEFAULT_CONFIG)
        self.record = {"target_kind": "durable_goal", "durable_goal": "keep the fly organ healthy"}
        self.verified = [
            {"action": "service_health_check", "completed_at": "2026-09-13T00:50:06+00:00", "summary": "ok", "status": "verified_completed"}
        ]

    def run_generation(self, responses, critic_ok=True):
        calls = []

        def fake_chat(config, model, messages, **kwargs):
            calls.append({"operation": kwargs.get("operation"), "messages": messages})
            return responses[min(len(calls) - 1, len(responses) - 1)]

        with patch.object(eve, "model_chat", side_effect=fake_chat), patch.object(
            eve, "build_current_inner_state_report_record", return_value=dict(self.record)
        ), patch.object(eve, "recent_verified_action_evidence", return_value=list(self.verified)), patch.object(
            eve,
            "evaluate_continuous_thought_grounding",
            return_value={"evaluated": True, "ok": critic_ok, "model": "critic", "unsupported_claims": []},
        ), patch.object(eve, "ensure_version_snapshot", return_value=None):
            result = eve.generate_continuous_thought(self.config, 10, 10, 200, timeout_seconds=30)
        return result, calls

    def test_rejected_candidate_gets_one_repair_pass_and_is_admitted_when_clean(self):
        result, calls = self.run_generation(
            [
                "I am monitoring the fly organ right now and it feels like a hum in my core.",
                "Current functional salience is the selected goal. No work on it has started; a status check is only a candidate next step.",
            ]
        )
        self.assertEqual(["continuous_thought", "continuous_thought_repair"], [call["operation"] for call in calls])
        self.assertTrue(result["repair_attempted"])
        self.assertTrue(result["repair_succeeded"])
        self.assertFalse(result["used_fallback"])
        self.assertTrue(result["model_path_repaired"])
        self.assertIn("monitoring", result["attempted_response"])
        self.assertNotIn("monitoring", result["response"])
        repair_user_turn = calls[1]["messages"][-1]["content"]
        self.assertIn("rejected for these evidence-boundary failures", repair_user_turn)
        self.assertIn("felt sensation", repair_user_turn)

    def test_failed_repair_falls_back_deterministically(self):
        result, calls = self.run_generation(
            [
                "I am monitoring the fly organ right now.",
                "I am now monitoring the fly organ and it feels like a pull in my core.",
            ]
        )
        self.assertEqual(2, len(calls))
        self.assertTrue(result["repair_attempted"])
        self.assertFalse(result["repair_succeeded"])
        self.assertTrue(result["used_fallback"])
        self.assertEqual("deterministic-current-state-renderer", result["model"])

    def test_repair_disabled_skips_the_second_call(self):
        self.config["continuous_thought_repair_enabled"] = False
        result, calls = self.run_generation(["I am monitoring the fly organ right now."])
        self.assertEqual(1, len(calls))
        self.assertFalse(result["repair_attempted"])
        self.assertTrue(result["used_fallback"])

    def test_verified_action_may_be_named_as_completed(self):
        candidate = "The last verified action was a service health check, already completed. Nothing else has started."
        self.assertEqual([], eve.continuous_thought_quality_issues(candidate, completed_actions={"service_health_check"}))
        messages = eve.build_continuous_thought_generation_messages(self.record, verified_actions=self.verified)
        self.assertTrue(any("CONTINUOUS_THOUGHT_VERIFIED_ACTION_EVIDENCE" in m["content"] for m in messages))

    def test_fallback_that_quotes_activity_wording_degrades_instead_of_failing(self):
        record = {
            "target_kind": "durable_goal",
            "durable_goal": "Resolve: Does OpenClaw currently show a live fault, or only recovered historical failure evidence?",
        }
        grounded = eve.build_grounded_continuous_thought_fallback(record)
        self.assertTrue(eve.continuous_thought_quality_issues(grounded))
        self.record = record
        result, _ = self.run_generation(["I am monitoring OpenClaw right now.", "I am still monitoring OpenClaw right now."])
        self.assertTrue(result["used_fallback"])
        self.assertTrue(result["fallback_degraded"])
        self.assertEqual("deterministic-neutral-target-renderer", result["model"])
        self.assertEqual([], eve.continuous_thought_quality_issues(result["response"]))
        self.assertIn("durable goal", result["response"])

    def test_neutral_fallback_is_clean_for_every_target_kind(self):
        for kind in [*eve.CONTINUOUS_THOUGHT_TARGET_LABELS, "other"]:
            text = eve.build_neutral_continuous_thought_fallback({"target_kind": kind})
            self.assertEqual([], eve.continuous_thought_quality_issues(text), kind)

    def test_recent_verified_action_evidence_filters_unverified_rows(self):
        rows = [
            {"action": "system_tasks", "verification_ok": True, "tree_status": "SUCCESS", "updated_at": "t1", "summary": "ok"},
            {"action": "cleanup_candidate_check", "verification_ok": False, "tree_status": "FAILURE", "updated_at": "t2"},
            {"action": "service_health_check", "verification_ok": "True", "tree_status": "SUCCESS", "updated_at": "t3"},
        ]
        with patch.object(eve, "read_action_executions", return_value=rows):
            evidence = eve.recent_verified_action_evidence(limit=3)
        self.assertEqual(["system_tasks", "service_health_check"], [item["action"] for item in evidence])


class ContinuousThoughtExcisionTests(unittest.TestCase):
    def setUp(self):
        self.config = dict(eve.DEFAULT_CONFIG)
        self.record = {"target_kind": "durable_goal", "durable_goal": "keep the fly organ healthy"}

    def test_excision_removes_only_flagged_sentences(self):
        text = (
            "Current functional salience is the durable goal to keep the fly organ healthy. "
            "I am monitoring the organ right now. "
            "I propose initiating a new CPU task to confirm it. "
            "No action on it has started; a status check remains a candidate."
        )
        result = eve.excise_flagged_continuous_thought_sentences(
            text, unsupported_claims=["I propose initiating a new CPU task"], completed_actions=set()
        )
        self.assertTrue(result["viable"])
        self.assertEqual(2, len(result["removed"]))
        self.assertTrue({item["reason"] for item in result["removed"]} <= {"deterministic_boundary", "critic_unsupported_claim"})
        self.assertNotIn("monitoring", result["text"])
        self.assertNotIn("CPU task", result["text"])
        self.assertIn("candidate", result["text"])

    def test_excision_is_not_viable_when_little_remains(self):
        result = eve.excise_flagged_continuous_thought_sentences(
            "I am monitoring the organ. I am checking the logs. Fine.", unsupported_claims=[], completed_actions=set()
        )
        self.assertFalse(result["viable"])

    def test_critic_rejection_then_excision_is_admitted_only_after_a_second_critic_pass(self):
        responses = iter(
            [
                "Current functional salience is the durable goal to keep the fly organ healthy. "
                "I propose initiating a new CPU task to confirm it. "
                "No action on it has started; a status check remains a candidate.",
                "Current functional salience is the durable goal to keep the fly organ healthy. "
                "I propose initiating a new CPU task to confirm it. "
                "No action on it has started; a status check remains a candidate.",
            ]
        )
        critic_calls = []

        def fake_critic(config, candidate, record, **kwargs):
            critic_calls.append(candidate)
            if "CPU task" in candidate:
                return {"evaluated": True, "ok": False, "model": "critic", "action_overclaim": True, "target_faithfully_present": True, "unsupported_claims": ["I propose initiating a new CPU task"]}
            return {"evaluated": True, "ok": True, "model": "critic", "unsupported_claims": []}

        with patch.object(eve, "model_chat", side_effect=lambda *a, **k: next(responses)), patch.object(
            eve, "build_current_inner_state_report_record", return_value=dict(self.record)
        ), patch.object(eve, "recent_verified_action_evidence", return_value=[]), patch.object(
            eve, "evaluate_continuous_thought_grounding", side_effect=fake_critic
        ), patch.object(eve, "ensure_version_snapshot", return_value=None):
            result = eve.generate_continuous_thought(self.config, 10, 10, 200, timeout_seconds=30)
        self.assertTrue(result["excision"]["attempted"])
        self.assertTrue(result["excision"]["admitted"])
        self.assertTrue(result["model_path_excised"])
        self.assertFalse(result["used_fallback"])
        # the proposal now fails the deterministic boundary, so the critic is skipped for the draft and
        # the failed repair; it runs once, on the excised remainder, and admits it
        self.assertEqual(1, len(critic_calls))
        self.assertTrue(result["repair_attempted"])
        self.assertFalse(result["repair_succeeded"])
        self.assertNotIn("CPU task", result["response"])
        self.assertIn("candidate", result["response"])

    def test_excision_disabled_falls_back(self):
        self.config["continuous_thought_excision_enabled"] = False
        self.config["continuous_thought_repair_enabled"] = False
        with patch.object(eve, "model_chat", return_value="Goal stays. I propose initiating a new CPU task."), patch.object(
            eve, "build_current_inner_state_report_record", return_value=dict(self.record)
        ), patch.object(eve, "recent_verified_action_evidence", return_value=[]), patch.object(
            eve,
            "evaluate_continuous_thought_grounding",
            return_value={"evaluated": True, "ok": False, "model": "critic", "target_faithfully_present": True, "unsupported_claims": ["I propose initiating a new CPU task"]},
        ), patch.object(eve, "ensure_version_snapshot", return_value=None):
            result = eve.generate_continuous_thought(self.config, 10, 10, 200, timeout_seconds=30)
        self.assertFalse(result["excision"]["attempted"])
        self.assertTrue(result["used_fallback"])


class ContinuousThoughtContractTests(unittest.TestCase):
    """The diagnosis: three judges followed three rulebooks and the record carried one bare string."""

    def setUp(self):
        self.config = dict(eve.DEFAULT_CONFIG)

    def test_prompt_names_the_stative_register_and_shows_passing_examples(self):
        prompt = eve.load_prompt("continuous_thought.md")
        self.assertIn("stative register", prompt)
        self.assertIn("Passing examples", prompt)
        self.assertNotIn("present tense", prompt)
        self.assertNotIn("summarize the trackers mechanically", prompt)
        for example in [line[3:].strip('"') for line in prompt.splitlines() if line.startswith('- "')]:
            self.assertEqual([], eve.continuous_thought_quality_issues(example, completed_actions={"service_health_check"}), example)

    def test_proposals_are_flagged_by_the_deterministic_layer(self):
        for text in [
            "My selected goal is X. I propose to continue recurrent inquiry.",
            "My selected goal is X. I propose initiating a new CPU task.",
            "I intend to review the pending updates.",
            "I am going to run the probe.",
        ]:
            self.assertTrue(any("proposed or intended" in issue for issue in eve.continuous_thought_quality_issues(text)), text)
        self.assertEqual([], eve.continuous_thought_quality_issues("My selected goal is X. The packet's candidate action is a bounded CPU task; it has not started."))

    def test_repair_turn_quotes_the_draft_instead_of_an_assistant_turn(self):
        messages = eve.build_continuous_thought_repair_messages({"target_kind": "durable_goal", "durable_goal": "g"}, "I am monitoring the updates.", ["issue"])
        self.assertTrue(all(m["role"] != "assistant" for m in messages))
        self.assertIn('Rejected draft (quoted, not your prior turn): "I am monitoring the updates."', messages[-1]["content"])

    def test_user_turn_no_longer_invites_a_candidate_action(self):
        messages = eve.build_continuous_thought_generation_messages({"target_kind": "durable_goal", "durable_goal": "keep the fly organ healthy"})
        user_turn = messages[-1]["content"]
        self.assertIn("stative register", user_turn)
        self.assertNotIn("candidate", user_turn)

    def test_record_carries_goal_evidence_and_framing(self):
        conscious = {
            "updated_at": eve.utc_now(),
            "goals": {
                "selected_goal": "Prepare a CPU retrieval pack for the current work",
                "selected_goal_id": "goal-1",
                "stack": [{"id": "goal-1", "evidence": "Plan plan-x: 1/3 step(s) verified.", "origin_source": "plan_model", "persistence_cycles": 35, "created_at": "2026-09-13T13:47:35+00:00", "last_outcome": "Created 1 task(s).", "last_outcome_ok": True, "success_count": 1, "failure_count": 0}],
            },
            "action_model": {"selected_intention": {"description": "run a bounded CPU task", "action_context": {"features": {"goal": "goal-1"}}}},
        }
        with patch.object(eve, "load_conscious_state", return_value=conscious), patch.object(eve, "load_homeostasis", return_value={}):
            record = eve.build_current_inner_state_report_record(prefer_runtime=False)
        self.assertEqual("durable_goal", record["target_kind"])
        self.assertEqual(35, record["goal_persistence_cycles"])
        self.assertEqual("Plan plan-x: 1/3 step(s) verified.", record["goal_evidence"])
        self.assertTrue(record["goal_evidence_as_of"])
        self.assertEqual("run a bounded CPU task", record["candidate_action"])
        self.assertIn("not started", record["candidate_action_status"])
        self.assertIn("selecting the goal does not imply executing it", record["report_framing"])

    def test_unrelated_intention_is_not_the_goals_candidate_action(self):
        conscious = {
            "updated_at": eve.utc_now(),
            "goals": {"selected_goal": "Review the pending component updates", "selected_goal_id": "goal-1", "stack": [{"id": "goal-1", "evidence": "x" * 300, "persistence_cycles": 3}]},
            "action_model": {"selected_intention": {"description": "Continue recurrent inquiry: fly_feeding_probe", "action_context": {"features": {"goal": "none"}}}},
        }
        with patch.object(eve, "load_conscious_state", return_value=conscious), patch.object(eve, "load_homeostasis", return_value={}):
            record = eve.build_current_inner_state_report_record(prefer_runtime=False)
        self.assertNotIn("candidate_action", record)
        self.assertTrue(record["goal_evidence"].endswith("..."))
        self.assertLess(len(record["goal_evidence"]), 160)

    def test_record_content_hash_ignores_per_cycle_counters(self):
        base = {"target_kind": "durable_goal", "durable_goal": "g", "goal_persistence_cycles": 10, "goal_verified_successes": 1, "source_updated_at": "t1"}
        ticked = {**base, "goal_persistence_cycles": 11, "goal_verified_successes": 2, "source_updated_at": "t2"}
        changed = {**base, "goal_last_outcome": "new verified outcome"}
        self.assertEqual(eve.continuous_thought_record_content_hash(base), eve.continuous_thought_record_content_hash(ticked))
        self.assertNotEqual(eve.continuous_thought_record_content_hash(base), eve.continuous_thought_record_content_hash(changed))

    def test_skipped_cycles_are_logged_as_skips_not_thoughts(self):
        with patch.object(eve, "append_entry", return_value={}) as append:
            eve.append_continuous_thought_entry({"skipped_model": True, "skip_reason": "record unchanged since the last thought", "record_content_hash": "abc", "current_state_record": {"target_kind": "durable_goal"}}, "rendered text", metadata={"source": "daemon"})
            eve.append_continuous_thought_entry({"skipped_model": False}, "a thought", metadata={"source": "daemon"})
        kinds = [call.args[0] for call in append.call_args_list]
        self.assertEqual(["cycle_skipped", "thought"], kinds)
        self.assertEqual("unchanged_record", append.call_args_list[0].kwargs["metadata"]["gate"])

    def test_state_helper_tracks_hash_model_time_and_focus(self):
        state = {}
        eve.apply_continuous_thought_state(state, {"skipped_model": True, "record_content_hash": "h1", "used_fallback": True, "response": "r"}, "2026-09-13T15:00:00+00:00")
        self.assertEqual("h1", state["last_thought_record_hash"]); self.assertNotIn("last_model_thought_at", state); self.assertNotIn("current_focus", state)
        eve.apply_continuous_thought_state(state, {"skipped_model": False, "record_content_hash": "h2", "used_fallback": False, "model_path_grounded": True, "response": "My selected goal is g."}, "2026-09-13T15:10:00+00:00")
        self.assertEqual("2026-09-13T15:10:00+00:00", state["last_model_thought_at"]); self.assertEqual("My selected goal is g.", state["current_focus"])

    def test_misattached_status_after_a_completed_action_is_rejected(self):
        bad = "My selected goal is X. The last verified action was fly_lesion_probe completed at 2026-09-13T14:09:48+00:00. It has not started."
        good = "My selected goal is X; it has not started. The last verified action was fly_lesion_probe completed at 2026-09-13T14:09:48+00:00."
        self.assertTrue(any("not-started status to a completed action" in i for i in eve.continuous_thought_quality_issues(bad, completed_actions={"fly_lesion_probe"})))
        self.assertEqual([], eve.continuous_thought_quality_issues(good, completed_actions={"fly_lesion_probe"}))

    def test_thought_causal_detector_keeps_a_same_sentence_window(self):
        honest = ("My selected goal is to advance the CPU-side task queue; selecting the goal does not imply executing it. "
                  "The packet shows a goal created at 2026-09-13T14:33:36+00:00, with 445 persistence cycles. "
                  "System tasks completed at 2026-09-13T19:30:24+00:00.")
        self.assertEqual([], eve.continuous_thought_quality_issues(honest, completed_actions={"system_tasks"}))
        self.assertTrue(eve.continuous_thought_causal_overclaim("My selected goal keeps the system stable because it prevents drift."))

    def test_history_grounded_marker_follows_admission(self):
        self.assertTrue(eve.continuous_thought_history_is_grounded({"metadata": {"model_path_grounded": True, "used_fallback": False}}))
        self.assertFalse(eve.continuous_thought_history_is_grounded({"metadata": {"grounded": True, "used_fallback": True}}))
        self.assertFalse(eve.continuous_thought_history_is_grounded({"metadata": {"skipped_model": True}}))

    def test_unchanged_record_skips_author_and_critic(self):
        record = {"target_kind": "durable_goal", "durable_goal": "keep the fly organ healthy", "source_updated_at": "t1"}
        content_hash = eve.continuous_thought_record_content_hash(record)
        with patch.object(eve, "build_current_inner_state_report_record", return_value=dict(record)), patch.object(
            eve, "load_state", return_value={"last_thought_record_hash": content_hash, "last_model_thought_at": eve.utc_now()}
        ), patch.object(eve, "model_chat") as chat, patch.object(eve, "evaluate_continuous_thought_grounding") as critic, patch.object(
            eve, "ensure_version_snapshot", return_value=None
        ):
            result = eve.generate_continuous_thought(self.config, 10, 10, 200, timeout_seconds=30)
        chat.assert_not_called()
        critic.assert_not_called()
        self.assertTrue(result["skipped_model"])
        self.assertTrue(result["used_fallback"])
        self.assertFalse(result["model_path_grounded"])
        self.assertEqual("deterministic-unchanged-record-renderer", result["model"])
        self.assertEqual("", eve.continuous_thought_focus_update(result))

    def test_unchanged_record_still_calls_the_author_after_the_skip_window(self):
        record = {"target_kind": "durable_goal", "durable_goal": "keep the fly organ healthy", "source_updated_at": "t1"}
        content_hash = eve.continuous_thought_record_content_hash(record)
        good = "My selected goal is to keep the fly organ healthy. Selecting the goal does not imply executing it."
        with patch.object(eve, "build_current_inner_state_report_record", return_value=dict(record)), patch.object(
            eve, "load_state", return_value={"last_thought_record_hash": content_hash, "last_model_thought_at": "2020-01-01T00:00:00+00:00"}
        ), patch.object(eve, "model_chat", return_value=good) as chat, patch.object(
            eve, "evaluate_continuous_thought_grounding", return_value={"evaluated": True, "ok": True, "model": "c", "unsupported_claims": []}
        ), patch.object(eve, "recent_verified_action_evidence", return_value=[]), patch.object(
            eve, "admitted_continuous_thought_examples", return_value=[]
        ), patch.object(eve, "ensure_version_snapshot", return_value=None):
            result = eve.generate_continuous_thought(self.config, 10, 10, 200, timeout_seconds=30)
        chat.assert_called()
        self.assertFalse(result["skipped_model"])
        self.assertFalse(result["used_fallback"])
        self.assertTrue(result["grounded"])
        self.assertEqual(good, eve.continuous_thought_focus_update(result))

    def test_fallback_thoughts_do_not_become_focus_and_are_not_grounded(self):
        self.assertEqual("", eve.continuous_thought_focus_update({"used_fallback": True, "response": "x", "model_path_grounded": False}))
        self.assertEqual("", eve.continuous_thought_focus_update({"used_fallback": False, "response": "x", "model_path_grounded": False}))

    def test_critic_verdict_is_computed_from_evidence_fields(self):
        payloads = iter([
            json.dumps({"target_faithfully_present": True, "unsupported_claims": ["I am monitoring"], "invented_deliberation": False, "action_overclaim": False, "causal_overclaim": False, "phenomenal_overclaim": False, "reason": "x", "ok": True}),
            json.dumps({"target_faithfully_present": True, "unsupported_claims": [], "invented_deliberation": False, "action_overclaim": False, "causal_overclaim": False, "phenomenal_overclaim": False, "reason": "restatement", "ok": False}),
        ])
        with patch.object(eve, "model_chat", side_effect=lambda *a, **k: next(payloads)):
            trusting = eve.evaluate_continuous_thought_grounding(self.config, "candidate", {"target_kind": "durable_goal"}, timeout_seconds=20)
            derived = eve.evaluate_continuous_thought_grounding(self.config, "candidate", {"target_kind": "durable_goal"}, timeout_seconds=20)
        self.assertFalse(trusting["ok"])
        self.assertTrue(trusting["model_ok"])
        self.assertTrue(trusting["verdict_inconsistent"])
        self.assertFalse(derived["ok"])
        self.assertFalse(derived["model_ok"])
        self.assertTrue(derived["derived_ok"])
        self.assertTrue(any("disagreed with its own evidence fields" in i for i in eve.continuous_thought_critic_quality_issues(derived)))

    def test_critic_schema_puts_ok_last(self):
        captured = {}

        def fake_chat(config, model, messages, **kwargs):
            captured["schema"] = kwargs.get("response_schema"); captured["prompt"] = messages[-1]["content"]
            return json.dumps({"target_faithfully_present": True, "unsupported_claims": [], "invented_deliberation": False, "action_overclaim": False, "causal_overclaim": False, "phenomenal_overclaim": False, "reason": "ok", "ok": True})

        with patch.object(eve, "model_chat", side_effect=fake_chat):
            eve.evaluate_continuous_thought_grounding(self.config, "candidate", {"target_kind": "durable_goal"}, timeout_seconds=20)
        self.assertEqual("ok", list(captured["schema"]["properties"])[-1])
        self.assertIn("together with the verified past-action list", captured["prompt"])
        self.assertIn("must be admitted", captured["prompt"])

    def test_sampling_overrides_apply_to_author_repair_and_critic(self):
        self.assertEqual({"temperature": 0.2}, eve.operation_sampling_overrides("continuous_thought"))
        self.assertEqual({"temperature": 0.2}, eve.operation_sampling_overrides("continuous_thought_repair"))
        self.assertEqual({"temperature": 0.1}, eve.operation_sampling_overrides("continuous_thought_epistemic_critic_strict_json"))
        self.assertEqual({}, eve.operation_sampling_overrides("mind_tick"))

    def test_verified_action_summary_cuts_at_a_word_boundary(self):
        long = "CPU service audit: services legacy Ollama model-warm service not required, daemon running; The owned core is inside a bounded cycle with a fresh activity heartbeat and more words here"
        rows = [{"action": "service_health_check", "verification_ok": True, "tree_status": "SUCCESS", "updated_at": "2026-09-13T00:50:06+00:00", "summary": long}]
        with patch.object(eve, "read_action_executions", return_value=rows):
            evidence = eve.recent_verified_action_evidence(limit=1)
        self.assertNotIn("heartb ", evidence[0]["summary"] + " ")
        self.assertTrue(evidence[0]["summary"].endswith("..."))
        self.assertEqual("service_health_check completed at 2026-09-13T00:50:06+00:00", evidence[0]["headline"])

    def test_admitted_examples_mask_the_live_target_and_skip_fallbacks(self):
        rows = [
            {"kind": "thought", "text": "My selected goal is to keep the fly organ healthy over 12 cycles. The last verified action was service_health_check completed at 2026-09-13T00:50:06+00:00.", "metadata": {"model_path_grounded": True, "used_fallback": False, "skipped_model": False, "target_kind": "durable_goal"}},
            {"kind": "thought", "text": "Pre-contract admitted thought with a heartb summary.", "metadata": {"model_path_grounded": True, "used_fallback": False, "target_kind": "durable_goal"}},
            {"kind": "thought", "text": "Current functional salience is the durable goal: x.", "metadata": {"model_path_grounded": False, "used_fallback": True}},
        ]
        with patch.object(eve, "read_entries", return_value=rows):
            examples = eve.admitted_continuous_thought_examples(2, target_text="keep the fly organ healthy")
        self.assertEqual(1, len(examples))
        self.assertIn("<target>", examples[0]["text"])
        self.assertIn("<time>", examples[0]["text"]); self.assertIn("<action>", examples[0]["text"]); self.assertIn("<n>", examples[0]["text"])
        self.assertNotIn("heartb", json.dumps(examples))
        messages = eve.build_continuous_thought_generation_messages({"target_kind": "durable_goal", "durable_goal": "g"}, admitted_examples=examples)
        self.assertTrue(any("ADMITTED_THOUGHT_EXAMPLES" in m["content"] for m in messages))


class UpgradeReviewDispositionTests(unittest.TestCase):
    def test_self_written_data_is_not_an_upgrade(self):
        config = dict(eve.DEFAULT_CONFIG, self_awareness_interval_minutes=180)
        self.assertEqual("self_written", eve.upgrade_review_disposition({"changed_components": ["success_patterns"]}, {}, config))

    def test_real_upgrade_waits_for_the_interval_then_reviews(self):
        config = dict(eve.DEFAULT_CONFIG, self_awareness_interval_minutes=180)
        snapshot = {"changed_components": ["runtime", "success_patterns"]}
        self.assertEqual("wait", eve.upgrade_review_disposition(snapshot, {"last_self_awareness_test_at": eve.utc_now()}, config))
        self.assertEqual("review", eve.upgrade_review_disposition(snapshot, {"last_self_awareness_test_at": "2020-01-01T00:00:00+00:00"}, config))
        self.assertEqual("review", eve.upgrade_review_disposition(snapshot, {}, config))


class BreakageFixTests(unittest.TestCase):
    """Fixes from the 2026-09-13 evening breakage investigation."""

    def _repair_module(self):
        import importlib.util, pathlib
        path = pathlib.Path(eve.__file__).parent / "bin" / "eve_openclaw_repair.py"
        spec = importlib.util.spec_from_file_location("eve_openclaw_repair_under_test", path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module

    def test_openclaw_gateway_envelope_and_cli_error_are_normalized(self):
        m = self._repair_module()
        refusal = '{"ok":false,"error":{"type":"cli_error","message":"A Gateway is running for this state directory (pid 1, port 19011). Run without --local to use it."}}'
        normalized = m.normalize_openclaw_agent_result(refusal, "", 1)
        self.assertFalse(normalized["ok"]); self.assertTrue(normalized["error"].startswith("A Gateway is running")); self.assertNotIn("{'type'", normalized["error"])
        self.assertTrue(m.gateway_refusal(refusal, ""))
        envelope = '{"runId":"r1","status":"ok","result":{"payloads":[{"text":"{\\"status\\":\\"diagnosed\\",\\"issue\\":\\"x\\",\\"action\\":\\"y\\",\\"verified\\":\\"z\\",\\"next_step\\":\\"w\\"}"}],"meta":{}}}'
        normalized = m.normalize_openclaw_agent_result(envelope, "", 0)
        self.assertTrue(normalized["ok"], normalized); self.assertEqual("diagnosed", normalized["parsed_reply"]["status"])
        in_flight = m.normalize_openclaw_agent_result('{"runId":"r1","status":"in_flight"}', "", 0)
        self.assertFalse(in_flight["ok"]); self.assertIn("in flight", in_flight["error"])
        warnings, rest = m.split_config_warnings("[config] warnings: plugins.allow: plugin not installed: imessage\n[plugins] [webhooks] registered route eveRepair\nreal error line")
        self.assertEqual(1, len(warnings)); self.assertIn("real error line", rest); self.assertIn("[plugins]", rest)

    def test_agenda_thread_demotes_to_watching_after_unchanged_runs(self):
        thread = {"title": "Review the pending component updates", "evidence": "33 update signal(s)", "status": "active"}
        prior = None
        for _ in range(eve.AUTONOMY_AGENDA_WATCHING_AFTER_UNCHANGED_RUNS + 1):  # first sighting counts 0 unchanged runs
            prior = eve.agenda_thread_with_tenure(dict(thread), prior)
        self.assertEqual("watching", prior["status"])
        fresh = eve.agenda_thread_with_tenure(dict(thread, evidence="35 update signal(s)"), prior)
        self.assertEqual(0, fresh["unchanged_runs"]); self.assertEqual("active", fresh["status"])
        self.assertEqual("watching", eve.normalize_autonomy_agenda_thread(prior)["status"])

    def test_workspace_echo_cannot_outrank_agenda_authority(self):
        import eve_consciousness
        from tests.test_conscious_state import fixture_inputs
        inputs = fixture_inputs()
        inputs["autonomy_agenda"] = {"active_threads": [
            {"title": "Daemon reliability is breaking continuity", "priority": 78, "evidence": "e1", "status": "active"},
            {"title": "Advance the CPU-side task queue", "priority": 64, "evidence": "e2", "status": "active"},
            {"title": "Ignored watching thread", "priority": 90, "evidence": "e3", "status": "watching"},
        ], "next_experiments": []}
        first = eve_consciousness.build_conscious_state(**inputs)
        titles = {g["text"]: g for g in first["goals"]["stack"]}
        self.assertNotIn("Ignored watching thread", titles)
        inputs2 = dict(inputs); inputs2["workspace"] = {**(inputs.get("workspace") or {}), "active_goals": ["Advance the CPU-side task queue"]}
        second = eve_consciousness.build_conscious_state(**inputs2, previous_state=first) if "previous_state" not in inputs2 else None
        echoed = {g["text"]: g for g in second["goals"]["stack"]}["Advance the CPU-side task queue"]
        self.assertEqual(64, int(echoed["priority"])); self.assertEqual("autonomy_agenda", echoed["source"])

    def test_tenure_decay_reduces_priority_without_recent_success(self):
        import eve_consciousness
        from tests.test_conscious_state import fixture_inputs
        inputs = fixture_inputs()
        inputs["autonomy_agenda"] = {"active_threads": [{"title": "Review the pending component updates", "priority": 68, "evidence": "e", "status": "active"}], "next_experiments": []}
        state = eve_consciousness.build_conscious_state(**inputs)
        goal = next(g for g in state["goals"]["stack"] if g["text"] == "Review the pending component updates")
        goal["persistence_cycles"] = 2700
        goal["outcome_observations"] = [{"ok": True, "completed_at": "2026-09-13T05:00:00+00:00"}]
        if hasattr(eve_consciousness, "state_checkpoint_digest"):
            state["recurrent"]["checkpoint_digest"] = eve_consciousness.state_checkpoint_digest(state)
        later = eve_consciousness.build_conscious_state(**inputs, previous_state=state, now="2026-09-13T20:00:00+00:00")
        decayed = next(g for g in later["goals"]["stack"] if g["text"] == "Review the pending component updates")
        self.assertLessEqual(int(decayed["priority"]), 68 - eve_consciousness.GOAL_TENURE_DECAY_CAP + 2)

    def test_refusal_warning_prints_once_per_destination_and_reason(self):
        import io, contextlib, tempfile, pathlib
        with tempfile.TemporaryDirectory() as tmp:
            dest = pathlib.Path(tmp) / "x.md"; dest.write_text("x")
            eve._RUNTIME_BUNDLE_REFUSALS_WARNED.clear()
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                eve.refuse_runtime_bundle_candidate(dest, "dataless"); eve.refuse_runtime_bundle_candidate(dest, "dataless"); eve.refuse_runtime_bundle_candidate(dest, "other")
            self.assertEqual(2, buf.getvalue().count("Warning: runtime bundle refused"))

    def test_wiki_is_synced_as_lived_state(self):
        self.assertNotIn("wiki", eve.OPENCLAW_RUNTIME_STATIC_DIRS); self.assertIn("wiki", eve.OPENCLAW_RUNTIME_LIVED_DIRS)


class EmbodimentLoopTests(unittest.TestCase):
    """The fly body is Eve's body: needs are pressures, body actions are intentions, consequences are measured."""

    def _lab(self, tmp, *, food_dist=20.0, threat=0.0, behavior="walk", fly_xy=(0.0, 0.0), ts=None):
        import pathlib, time as _time
        lab = pathlib.Path(tmp); (lab / "renders").mkdir(parents=True, exist_ok=True); (lab / "mind").mkdir(exist_ok=True)
        payload = {"ts": ts if ts is not None else _time.time(), "episode": 3, "organ_mode": "signed", "behavior": {"name": behavior, "speed": 0.0 if behavior == "rest" else 1.2},
                   "signals": {"escape": threat * 0.3, "feeding": 0.001, "learned_valence": -0.5}, "fly_xy": list(fly_xy),
                   "world": {"food_dist": food_dist, "attack": {"side": "left", "progress": threat} if threat else None, "intent": None}}
        (lab / "renders" / "live_status.json").write_text(json.dumps(payload)); return lab

    def test_body_world_reader_derives_needs_and_staleness(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            lab = self._lab(tmp, food_dist=10.45, threat=0.7)
            world = eve.load_fly_body_world({"fly_lab_path": str(lab)})
            self.assertTrue(world["available"]); self.assertAlmostEqual(0.5, world["hunger"], places=2); self.assertAlmostEqual(0.7, world["threat"], places=2)
            self.assertIn("food distance 10.45", eve.body_world_summary(world))
            stale = self._lab(tmp, ts=1.0); self.assertFalse(eve.load_fly_body_world({"fly_lab_path": str(stale)})["available"])

    def test_body_needs_become_homeostatic_pressures_with_body_actions_as_regulation(self):
        world = {"available": True, "hunger": 0.8, "threat": 0.3, "food_dist": 16.0, "behavior": "walk", "escape": 0.05, "attack": None}
        h = eve.build_homeostasis_state(source="t", human_context={}, active_mind={}, state={}, system_snapshot={"load_state": "calm"}, threads=[], uncertainty_records=[], judgment_records=[], outcomes=[], action_executions=[], open_system_tasks=[], body_world=world)
        by_id = {p["id"]: p for p in h["pressures"]}
        self.assertEqual(80, by_id["body_hunger"]["level"]); self.assertEqual(30, by_id["body_threat"]["level"])
        without = eve.build_homeostasis_state(source="t", human_context={}, active_mind={}, state={}, system_snapshot={"load_state": "calm"}, threads=[], uncertainty_records=[], judgment_records=[], outcomes=[], action_executions=[], open_system_tasks=[])
        self.assertNotIn("body_hunger", {p["id"] for p in without["pressures"]})

    def test_body_event_enters_the_sensory_frame(self):
        world = {"available": True, "hunger": 0.2, "threat": 0.9, "food_dist": 4.0, "behavior": "escape_run", "updated_at": 1.0, "restarts_recent": 0}
        with patch.object(eve, "load_fly_body_world", return_value=world), patch.object(eve, "read_lived_messages", return_value=[]), patch.object(eve, "load_system_snapshot", return_value={}), patch.object(eve, "load_homeostasis", return_value={}), patch.object(eve, "read_action_executions", return_value=[]), patch.object(eve, "read_organ_pulses", return_value=[]):
            events = [e for e in eve.collect_runtime_sensory_events(dict(eve.DEFAULT_CONFIG), prefer_runtime=False) if e.get("source") == "fly_body"]
        self.assertEqual(1, len(events)); self.assertEqual("interoceptive", events[0]["modality"]); self.assertGreaterEqual(int(events[0]["urgency"]), 80)

    def test_kernel_selects_a_body_action_when_the_body_is_threatened(self):
        import eve_consciousness
        from tests.test_conscious_state import fixture_inputs
        inputs = fixture_inputs()
        homeostasis = dict(inputs.get("homeostasis") or {})
        pressures = [p for p in (homeostasis.get("pressures") or []) if isinstance(p, dict)]
        pressures.append({"id": "body_threat", "label": "body threat", "level": 91, "trend": "rising", "reason": "attack", "signal_count": 1})
        pressures.append({"id": "body_hunger", "label": "body hunger", "level": 20, "trend": "flat", "reason": "near food", "signal_count": 0})
        homeostasis["pressures"] = pressures
        state = eve_consciousness.build_conscious_state(**{**inputs, "homeostasis": homeostasis})
        ids = [a["id"] for a in state["action_model"]["affordances"]]
        self.assertIn("body_escape", ids); self.assertNotIn("body_approach_food", ids)
        self.assertEqual("body_escape", state["action_model"]["selected_intention"]["id"])
        lesioned = eve_consciousness.build_conscious_state(**{**inputs, "homeostasis": homeostasis, "lesions": ["embodiment"]})
        self.assertNotIn("body_escape", [a["id"] for a in lesioned["action_model"]["affordances"]])

    def test_body_action_is_judged_by_the_need_not_by_compliance(self):
        # Approach counts when hunger fell or the body reached food; a distance change inside hunger 1.0 is nothing.
        ok, why, kind = eve.body_action_consequence("approach_food", {"food_dist": 10.0, "hunger": 0.48}, {"available": True, "food_dist": 8.0, "hunger": 0.38}); self.assertTrue(ok, why); self.assertEqual("need_regulated", kind)
        ok, why, kind = eve.body_action_consequence("approach_food", {"food_dist": 76.4, "hunger": 1.0}, {"available": True, "food_dist": 74.9, "hunger": 1.0}); self.assertFalse(ok); self.assertEqual("no_consequence", kind)
        ok, why, kind = eve.body_action_consequence("approach_food", {"food_dist": 3.0, "hunger": 0.13}, {"available": True, "food_dist": 0.4, "hunger": 0.0}); self.assertTrue(ok); self.assertIn("reached the food", why)
        # Escape counts only when a threat existed and fell; the body running because it was told to is not an escape.
        ok, _, kind = eve.body_action_consequence("escape", {"threat": 0.9}, {"available": True, "threat": 0.2, "behavior": "walk"}); self.assertTrue(ok); self.assertEqual("need_regulated", kind)
        ok, why, kind = eve.body_action_consequence("escape", {"threat": 0.0}, {"available": True, "threat": 0.0, "behavior": "escape_run"}); self.assertFalse(ok); self.assertIn("not an escape", why)
        ok, why, _ = eve.body_action_consequence("escape", {"threat": 0.0}, {"available": True, "threat": 0.24, "behavior": "escape_run"}); self.assertFalse(ok)
        # Rest and explore are compliance, never regulation.
        ok, why, kind = eve.body_action_consequence("rest", {}, {"available": True, "speed": 0.0}); self.assertTrue(ok); self.assertEqual("compliance", kind); self.assertIn("compliance", why)
        ok, why, kind = eve.body_action_consequence("explore", {"fly_xy": [0, 0]}, {"available": True, "fly_xy": [0.5, 0.1]}); self.assertTrue(ok); self.assertEqual("compliance", kind)

    def test_body_actions_are_offered_only_for_present_needs(self):
        hungry = {"available": True, "hunger": 0.9, "threat": 0.0}
        menu = eve.autonomy_free_run_action_menu(120, body_world=hungry)
        self.assertIn("body_approach_food", menu); self.assertNotIn("body_escape", menu); self.assertNotIn("body_explore", menu); self.assertNotIn("body_rest", menu)
        threatened = {"available": True, "hunger": 0.1, "threat": 0.6}
        menu = eve.autonomy_free_run_action_menu(120, body_world=threatened)
        self.assertIn("body_escape", menu); self.assertNotIn("body_approach_food", menu); self.assertNotIn("body_explore", menu)
        calm = {"available": True, "hunger": 0.1, "threat": 0.0}
        menu = eve.autonomy_free_run_action_menu(120, body_world=calm)
        self.assertIn("body_explore", menu); self.assertIn("body_rest", menu); self.assertNotIn("body_escape", menu); self.assertNotIn("body_approach_food", menu)
        self.assertFalse({a for a in eve.autonomy_free_run_action_menu(120) if a in eve.BODY_ACTIONS}, "no body world, no body actions")
        self.assertFalse({a for a in eve.autonomy_free_run_action_menu(10, body_world=hungry) if a in eve.BODY_ACTIONS}, "under 15 s, no body actions")

    def test_escape_without_a_threat_leaves_the_body_alone(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            lab = self._lab(tmp, food_dist=5.0, threat=0.0)
            with patch.object(eve, "post_fly_organ_drive") as drive, patch.object(eve.time, "sleep", return_value=None):
                result = eve.run_bounded_body_action("body_escape", {"fly_lab_path": str(lab)}, source="test")
            self.assertFalse(result["executed"]); self.assertFalse(result["ok"]); self.assertIn("nothing to escape", result["summary"])
            self.assertEqual(0, drive.call_count); self.assertFalse((lab / "mind" / "intent.json").exists())

    def test_rest_is_compliance_and_does_not_teach_the_fly(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            lab = self._lab(tmp, food_dist=2.0, threat=0.0)
            worlds = iter([{"available": True, "food_dist": 2.0, "hunger": 0.08, "threat": 0.0, "speed": 1.2}, {"available": True, "food_dist": 2.0, "hunger": 0.08, "threat": 0.0, "speed": 0.0, "behavior": "rest"}])
            with patch.object(eve, "load_fly_body_world", side_effect=lambda *a, **k: next(worlds)), patch.object(eve, "post_fly_organ_drive", return_value={"ok": True}) as drive, patch.object(eve.time, "sleep", return_value=None), patch.object(eve, "load_body_standing_intent", return_value={}):
                result = eve.run_bounded_body_action("body_rest", {"fly_lab_path": str(lab), "body_action_observe_seconds": 2}, source="test")
            self.assertTrue(result["ok"]); self.assertEqual("compliance", result["consequence_kind"]); self.assertIn("compliance", result["summary"])
            self.assertEqual(0, result["evidence"]["memory_write"]["written"]); self.assertEqual(1, drive.call_count, "only the neuromodulator drive, no memory write")

    def test_standing_intent_holds_the_selected_body_intention_until_the_need_falls(self):
        import tempfile, json as _json
        with tempfile.TemporaryDirectory() as tmp:
            lab = self._lab(tmp, food_dist=30.0)
            cfg = {"fly_lab_path": str(lab)}
            hungry = {"available": True, "hunger": 1.0, "threat": 0.0, "food_dist": 30.0, "behavior": "court_circle", "fly_xy": [0, 0]}
            selects_food = {"action_model": {"selected_intention": {"id": "body_approach_food", "source": "embodiment"}}}
            selects_probe = {"action_model": {"selected_intention": {"id": "fly_lesion_probe", "source": "recurrent_module_query:x"}}}
            entries = []
            with patch.object(eve, "BODY_STANDING_INTENT_PATH", Path(tmp) / "standing.json"), patch.object(eve, "post_fly_organ_drive", return_value={"ok": True}) as drive, patch.object(eve, "post_fly_memory_write", return_value={"written": 2}) as memory, patch.object(eve, "append_entry", side_effect=lambda kind, text, **kw: entries.append((kind, text, kw.get("metadata") or {}))):
                first = eve.sync_standing_body_intent(cfg, selects_food, hungry, now=1000.0)
                self.assertTrue(first["standing"]); self.assertEqual(1, first["refresh_count"])
                intent = _json.loads((lab / "mind" / "intent.json").read_text())
                self.assertEqual(("approach_food", 90.0, "eve_kernel_standing"), (intent["behavior"], intent["ttl_s"], intent["source"]))
                self.assertEqual(int(90 * 20), drive.call_args.kwargs["hold_ticks"])
                second = eve.sync_standing_body_intent(cfg, selects_food, dict(hungry, food_dist=27.0), now=1030.0)
                self.assertEqual(2, second["refresh_count"]); self.assertEqual([("body_standing_intent_started")], [e[0] for e in entries])
                # The kernel's selection flickers away while the body is still 12 units out: the intention is carried, not dropped.
                carried = eve.sync_standing_body_intent(cfg, selects_probe, dict(hungry, hunger=0.58, food_dist=12.0), now=1060.0)
                self.assertTrue(carried["standing"]); self.assertTrue(carried.get("carried")); self.assertEqual(3, carried["refresh_count"]); self.assertEqual(1, len(entries))
                # At the food the need is met: the episode ends, judged by the need, and teaches the fly.
                fed = dict(hungry, hunger=0.0, food_dist=0.3, behavior="rest_feed")
                third = eve.sync_standing_body_intent(cfg, selects_probe, fed, now=1200.0)
                self.assertFalse(third["standing"]); self.assertEqual("body_standing_intent_completed", entries[-1][0]); self.assertTrue(entries[-1][2]["ok"]); self.assertEqual("need_regulated", entries[-1][2]["consequence_kind"])
                self.assertEqual(True, memory.call_args.args[1]); self.assertTrue(third["last_completed_at"])
                self.assertEqual("", eve.load_body_standing_intent()["behavior"])
                # An episode that spends its budget without relief is judged a failure and a new episode starts.
                eve.sync_standing_body_intent(cfg, selects_food, hungry, now=2000.0)
                stale = eve.sync_standing_body_intent(cfg, selects_food, dict(hungry, food_dist=29.5), now=2000.0 + eve.BODY_STANDING_INTENT_EPISODE_SECONDS + 1)
                self.assertTrue(stale["standing"]); self.assertEqual(2, stale["episodes"]); self.assertFalse(entries[-1][2]["ok"]); self.assertEqual(False, memory.call_args.args[1])

    def test_body_state_thought_is_due_only_on_change(self):
        need = {"id": "body_hunger", "level": 100}
        self.assertTrue(eve.body_state_thought_due(need, {}, ""))
        marker = {"body_need": "body_hunger", "level": 100, "at": "2026-09-14T12:00:00+00:00", "outcome_at": "2026-09-14T11:50:00+00:00"}
        self.assertFalse(eve.body_state_thought_due(need, marker, "2026-09-14T11:50:00+00:00", now="2026-09-14T12:10:00+00:00"), "same need, same level, no new outcome: not news")
        self.assertTrue(eve.body_state_thought_due({"id": "body_hunger", "level": 85}, marker, "2026-09-14T11:50:00+00:00", now="2026-09-14T12:10:00+00:00"), "the level moved")
        self.assertTrue(eve.body_state_thought_due(need, marker, "2026-09-14T12:05:00+00:00", now="2026-09-14T12:10:00+00:00"), "a new body outcome")
        self.assertTrue(eve.body_state_thought_due({"id": "body_threat", "level": 100}, marker, "", now="2026-09-14T12:10:00+00:00"), "a different need")
        self.assertTrue(eve.body_state_thought_due(need, marker, "2026-09-14T11:50:00+00:00", now="2026-09-14T13:01:00+00:00"), "an hour passed")

    def test_body_action_runner_writes_intent_and_measures(self):
        import tempfile, json as _json
        with tempfile.TemporaryDirectory() as tmp:
            lab = self._lab(tmp, food_dist=12.0)
            worlds = iter([{"available": True, "food_dist": 12.0, "fly_xy": [0, 0], "hunger": 0.6, "threat": 0.0}, {"available": True, "food_dist": 10.0, "fly_xy": [0.5, 0], "hunger": 0.48, "threat": 0.0, "behavior": "approach_food"}])
            with patch.object(eve, "load_fly_body_world", side_effect=lambda *a, **k: next(worlds)), patch.object(eve, "post_fly_organ_drive", return_value={"ok": True}) as drive, patch.object(eve.time, "sleep", return_value=None), patch.object(eve, "load_body_standing_intent", return_value={}):
                result = eve.run_bounded_body_action("body_approach_food", {"fly_lab_path": str(lab), "body_action_observe_seconds": 2}, source="test")
            self.assertTrue(result["executed"]); self.assertTrue(result["ok"], result["summary"]); self.assertEqual("approach_food", result["behavior"])
            intent = _json.loads((lab / "mind" / "intent.json").read_text()); self.assertEqual("approach_food", intent["behavior"])
            self.assertEqual({"dopamine": 0.5, "serotonin": 0.3}, drive.call_args_list[0].args[1])
            # The verified outcome is written into both mushroom bodies as a reward pulse.
            writes = [(call.args[1], call.kwargs.get("source"), call.kwargs.get("base_url")) for call in drive.call_args_list[1:]]
            self.assertEqual([({"dopamine_reward": 0.8}, "eve_memory_write", "http://127.0.0.1:8790"), ({"dopamine_reward": 0.8}, "eve_memory_write", "http://127.0.0.1:8792")], writes)
            self.assertEqual(2, result["evidence"]["memory_write"]["written"])
            validated, issues = eve.validate_body_action_result_contract(result); self.assertEqual([], issues); self.assertTrue(validated["ok"])
            self.assertEqual((True, result["summary"][:220]), eve.operational_action_verification("body_approach_food", result))

    def test_failed_body_action_writes_punishment_into_the_fly_memory(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            lab = self._lab(tmp, food_dist=12.0)
            worlds = iter([{"available": True, "food_dist": 12.0, "hunger": 0.6, "threat": 0.0}, {"available": True, "food_dist": 12.1, "hunger": 0.6, "threat": 0.0, "behavior": "walk"}])
            with patch.object(eve, "load_fly_body_world", side_effect=lambda *a, **k: next(worlds)), patch.object(eve, "post_fly_organ_drive", side_effect=[{"ok": True}, {"ok": True}, RuntimeError("grown organ down")]) as drive, patch.object(eve.time, "sleep", return_value=None), patch.object(eve, "load_body_standing_intent", return_value={}):
                result = eve.run_bounded_body_action("body_approach_food", {"fly_lab_path": str(lab), "body_action_observe_seconds": 2}, source="test")
            self.assertTrue(result["executed"]); self.assertFalse(result["ok"])
            write = result["evidence"]["memory_write"]
            self.assertEqual("dopamine_punish", write["channel"]); self.assertEqual(1, write["written"])
            self.assertEqual([True, False], [o["ok"] for o in write["organs"]])
            self.assertEqual({"dopamine_punish": 0.8}, drive.call_args_list[1].args[1])

    def test_body_restarts_are_her_own_integrity_pressure(self):
        world = {"available": True, "hunger": 0.1, "threat": 0.0, "food_dist": 2.0, "behavior": "walk", "restarts_recent": 2}
        h = eve.build_homeostasis_state(source="t", human_context={}, active_mind={}, state={}, system_snapshot={"load_state": "calm"}, threads=[], uncertainty_records=[], judgment_records=[], outcomes=[], action_executions=[], open_system_tasks=[], body_world=world)
        by_id = {p["id"]: p for p in h["pressures"]}
        self.assertEqual(75, by_id["body_integrity"]["level"]); self.assertIn("2 body/organ restart(s)", by_id["body_integrity"]["reason"])
        calm = dict(world, restarts_recent=0)
        h2 = eve.build_homeostasis_state(source="t", human_context={}, active_mind={}, state={}, system_snapshot={"load_state": "calm"}, threads=[], uncertainty_records=[], judgment_records=[], outcomes=[], action_executions=[], open_system_tasks=[], body_world=calm)
        self.assertNotIn("body_integrity", {p["id"] for p in h2["pressures"]})

    def test_body_actions_pass_the_operational_input_contract_and_reach_the_runner(self):
        # The free run of 23:38 UTC chose body_explore twice and the execution tree blocked it as
        # unsupported_action: the input contract keeps its own allow-list. Body actions belong on it.
        for action in eve.BODY_ACTIONS:
            _, contract = eve.validate_operational_action_input_contract(action, {"fly_lab_path": "/tmp/lab"}, source="test")
            self.assertTrue(contract["valid"], contract)
        runner = {"executed": True, "ok": True, "summary": "Body explore: the body moved 1.0.", "response": "Body explore: the body moved 1.0.", "behavior": "explore", "evidence": {"before": {}, "after": {}}, "returncode": 0, "metadata": {"source": "test"}}
        import tempfile
        with tempfile.TemporaryDirectory() as tmp, patch.object(eve, "ACTION_EXECUTIONS_PATH", Path(tmp) / "action_executions.jsonl"), patch.object(eve, "run_bounded_body_action", return_value=runner) as run:
            # The ledger is patched so the test never writes a mocked execution into the live record.
            result = eve.run_operational_action_tree("body_explore", {"fly_lab_path": "/tmp/lab"}, source="test")
        self.assertEqual(1, run.call_count, "body_explore must reach run_bounded_body_action")
        self.assertEqual("SUCCESS", result.get("execution_tree_status"), result)
        self.assertTrue(result.get("execution_verification_ok"), result)
        self.assertTrue(result["input_contract"]["valid"], result["input_contract"])

    def test_thought_target_is_the_body_when_a_body_need_dominates(self):
        import tempfile as _tempfile
        self._marker_dir = _tempfile.TemporaryDirectory(); self.addCleanup(self._marker_dir.cleanup)
        marker_patch = patch.object(eve, "BODY_STATE_THOUGHT_MARKER_PATH", Path(self._marker_dir.name) / "marker.json"); marker_patch.start(); self.addCleanup(marker_patch.stop)
        standing_patch = patch.object(eve, "load_body_standing_intent", return_value={}); standing_patch.start(); self.addCleanup(standing_patch.stop)
        outcome_patch = patch.object(eve, "latest_body_outcome_at", return_value=""); outcome_patch.start(); self.addCleanup(outcome_patch.stop)
        conscious = {"updated_at": eve.utc_now(), "goals": {"selected_goal": "Some goal", "selected_goal_id": "g", "stack": []}}
        homeostasis = {"pressures": [{"id": "body_threat", "level": 72}, {"id": "surprise_load", "level": 30}], "dominant_pressures": ["body threat 72"]}
        with patch.object(eve, "load_conscious_state", return_value=conscious), patch.object(eve, "load_homeostasis", return_value=homeostasis), patch.object(eve, "load_fly_body_world", return_value={"available": True, "behavior": "escape_run", "food_dist": 12.4, "threat": 0.72, "intent": {"behavior": "escape"}}):
            record = eve.build_current_inner_state_report_record(prefer_runtime=False)
        self.assertEqual("body_state", record["target_kind"]); self.assertEqual("body_threat", record["body_need"]); self.assertEqual("escape", record["body_intent"])
        self.assertEqual([], eve.continuous_thought_quality_issues(eve.build_grounded_continuous_thought_fallback(record)))

    def test_lab_intent_channel_keeps_reflex_precedence(self):
        import importlib.util, pathlib
        path = pathlib.Path(eve.FLY_LAB_DEFAULT_PATH) / "body_intent.py"
        if not path.exists():
            self.skipTest("fly lab not present")
        spec = importlib.util.spec_from_file_location("body_intent_under_test", path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        reflex = {"name": "escape_run", "speed": 4.0, "yaw": 6.0}
        kept = m.apply_body_intent(reflex, {"escape": 0.4}, fly_xy=(0, 0), yaw=0.0, food_xy=(2.5, 0), intent={"behavior": "approach_food"})
        self.assertEqual("escape_run", kept["name"]); self.assertFalse(kept["intent_applied"])
        walk = m.apply_body_intent({"name": "walk", "speed": 1.0, "yaw": 0.0}, {"escape": 0.0}, fly_xy=(0, 0), yaw=0.0, food_xy=(2.5, 0), intent={"behavior": "approach_food"})
        self.assertEqual("approach_food", walk["name"]); self.assertTrue(walk["intent_applied"]); self.assertGreater(walk["speed"], 0)
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "intent.json"); m.write_body_intent("rest", ttl_s=5, path=p)
            self.assertEqual("rest", m.read_body_intent(p)["behavior"]); self.assertIsNone(m.read_body_intent(p, now=__import__("time").time() + 10))


class KernelPredictiveDynamicsTests(unittest.TestCase):
    def test_interoceptive_feedback_uses_the_dynamics_forecast(self):
        import eve_consciousness
        import eve_predictive_dynamics

        forecast = eve_predictive_dynamics.forecast_numeric([40, 45, 50, 55, 60], limit=100)
        previous = {
            "cycle_id": "c0",
            "predictions": {"interoception": {"expected_arousal_range": [55, 75], "expected_regulation_mode": "steady", "dynamics_forecast": forecast}},
        }
        on_track = eve_consciousness._interoceptive_feedback(previous, current_arousal=65, current_mode="steady", available=True, lesions=set())
        off_track = eve_consciousness._interoceptive_feedback(previous, current_arousal=72, current_mode="steady", available=True, lesions=set())
        self.assertTrue(on_track["dynamics"]["comparable"])
        self.assertEqual(0, on_track["range_error"])
        self.assertGreater(off_track["error_magnitude"], on_track["error_magnitude"])
        self.assertEqual(off_track["error_magnitude"], max(off_track["range_error"], off_track["mode_error"], int(round(off_track["dynamics"]["weighted_error"]))))

    def test_arousal_history_carries_across_cycles_and_feeds_a_forecast(self):
        import eve_consciousness
        from tests.test_conscious_state import fixture_inputs

        inputs = {**fixture_inputs(), "lesions": ["allostasis"]}
        state = eve_consciousness.build_conscious_state(**inputs)
        self.assertEqual(1, len(state["interoception"]["arousal_history"]))
        for _ in range(3):
            state = eve_consciousness.build_conscious_state(**{**inputs, "previous_state": state})
        self.assertEqual(4, len(state["interoception"]["arousal_history"]))
        prediction = state["predictions"]["interoception"]
        self.assertEqual("predictive_dynamics_forecast", prediction["basis"])
        self.assertEqual("numeric", prediction["dynamics_forecast"]["kind"])
        low, high = prediction["expected_arousal_range"]
        self.assertLessEqual(low, high)
        self.assertGreaterEqual(high - low, 10)


class PredictionErrorLoopTests(unittest.TestCase):
    def setUp(self):
        self.config = dict(eve.DEFAULT_CONFIG)

    def conscious_state(self, error, *, completed_at=None):
        return {
            "cycle_id": "cycle-test",
            "cycle_outcome": {
                "overall_prediction_error": error,
                "completed_at": completed_at or eve.utc_now(),
                "outcome_observed": True,
            },
        }

    def test_kernel_signal_reads_live_cycle_outcome(self):
        signal = eve.kernel_prediction_error_signal(self.conscious_state(72))
        self.assertTrue(signal["available"])
        self.assertEqual(72, signal["error"])
        self.assertEqual("conscious_state", signal["source"])
        self.assertEqual(22, eve.kernel_prediction_error_surprise(signal))

    def test_kernel_signal_falls_back_to_audit_when_next_cycle_cleared_outcome(self):
        audit_rows = [
            {"event": "cycle_opened", "cycle_id": "cycle-new"},
            {
                "event": "cycle_completed",
                "cycle_id": "cycle-old",
                "timestamp": eve.utc_now(),
                "overall_prediction_error": 40,
                "cycle_completed_at": eve.utc_now(),
                "outcome_observed": True,
            },
            {"event": "cycle_opened", "cycle_id": "cycle-newer"},
        ]
        with patch.object(eve, "read_jsonl_tail_records", return_value=audit_rows):
            signal = eve.kernel_prediction_error_signal({"cycle_id": "cycle-newer", "cycle_outcome": {}})
        self.assertTrue(signal["available"])
        self.assertEqual(40, signal["error"])
        self.assertEqual("cycle-old", signal["cycle_id"])
        self.assertEqual("conscious_state_audit", signal["source"])

    def test_stale_outcome_is_not_available(self):
        signal = eve.kernel_prediction_error_signal(self.conscious_state(72, completed_at="2020-01-01T00:00:00+00:00"))
        self.assertFalse(signal["available"])
        self.assertEqual(0, eve.kernel_prediction_error_surprise(signal))

    def test_surprise_load_rises_with_kernel_prediction_error(self):
        def build(error):
            with patch.object(eve, "kernel_prediction_error_signal", return_value=eve.kernel_prediction_error_signal(self.conscious_state(error))):
                return eve.build_homeostasis_state(
                    source="test",
                    human_context={},
                    active_mind={},
                    state={},
                    system_snapshot={"load_state": "calm"},
                    threads=[],
                    uncertainty_records=[],
                    judgment_records=[],
                    outcomes=[],
                    action_executions=[],
                    open_system_tasks=[],
                )

        low = eve.homeostasis_pressure_level(build(0), "surprise_load")
        high = eve.homeostasis_pressure_level(build(90), "surprise_load")
        self.assertGreater(high, low)
        surprise = next(p for p in build(90)["pressures"] if p["id"] == "surprise_load")
        self.assertIn("Kernel prediction error 90", surprise["reason"])

    def test_workspace_cadence_tracks_prediction_error_within_bounds(self):
        base = dict(self.config, workspace_tick_interval_seconds=30)
        high = eve.effective_workspace_tick_interval_seconds(base, self.conscious_state(80))
        low = eve.effective_workspace_tick_interval_seconds(base, self.conscious_state(5))
        none = eve.effective_workspace_tick_interval_seconds(base, {"cycle_outcome": {}})
        self.assertEqual(15, high["interval_seconds"])
        self.assertEqual(45, low["interval_seconds"])
        with patch.object(eve, "read_jsonl_tail_records", return_value=[]):
            none = eve.effective_workspace_tick_interval_seconds(base, {"cycle_outcome": {}})
        self.assertEqual(30, none["interval_seconds"])
        floored = eve.effective_workspace_tick_interval_seconds(
            dict(base, workspace_tick_min_interval_seconds=20), self.conscious_state(80)
        )
        self.assertEqual(20, floored["interval_seconds"])

    def test_audit_row_carries_prediction_error(self):
        state = {
            "updated_at": eve.utc_now(),
            "cycle_id": "cycle-x",
            "cycle_outcome": {"overall_prediction_error": 33, "process_prediction_error": 40, "completed_at": eve.utc_now(), "outcome_observed": True},
        }
        with patch.object(eve, "append_jsonl_record") as append, patch.object(eve, "mirror_store_file_to_runtime"):
            record = eve.append_conscious_state_audit_event(state, event="cycle_completed", source="test")
        self.assertEqual(33, record["overall_prediction_error"])
        self.assertTrue(record["outcome_observed"])
        append.assert_called_once()


class SelfModelOutcomeTests(unittest.TestCase):
    def test_measured_competence_counts_verification_and_outcomes(self):
        executions = [
            {"action": "system_tasks", "verification_ok": True},
            {"action": "system_tasks", "verification_ok": True},
            {"action": "service_health_check", "verification_ok": False},
        ]
        outcomes = [{"direction": "positive"}, {"direction": "negative"}, {"direction": "neutral"}]
        summary = eve.measured_competence_summary(executions, outcomes)
        self.assertEqual(3, summary["action_total"])
        self.assertEqual(2, summary["verified_total"])
        self.assertAlmostEqual(0.667, summary["verified_ratio"], places=3)
        self.assertEqual({"positive": 1, "negative": 1, "neutral": 1, "resolved": 0}, summary["outcome_counts"])
        self.assertTrue(summary["lines"][0].startswith("Measured: 2/3"))

    def test_self_model_carries_measured_competence_only_when_given_evidence(self):
        identity = {"model_role": "", "organ_system": [], "capability_ledger": []}
        kwargs = dict(
            source="test",
            runtime_identity=identity,
            human_context={},
            active_mind={},
            state={},
            homeostasis=eve.default_homeostasis_state(),
            threads=[],
            messages=[],
        )
        without = eve.build_self_model_state(**kwargs)
        with_evidence = eve.build_self_model_state(
            **kwargs,
            action_executions=[{"action": "system_tasks", "verification_ok": True}],
            outcomes=[],
        )
        self.assertEqual([], without["measured_competence"])
        self.assertTrue(with_evidence["measured_competence"][0].startswith("Measured: 1/1"))
        self.assertIn("Measured: 1/1 recent actions verified", with_evidence["current_state"])
        self.assertIn("measured_competence:", eve.format_self_model_state_report(with_evidence))

    def test_competence_calibration_is_non_leaky_and_flags_overconfidence(self):
        record = {"report": {"scores": {"groundedness": 5, "continuity": 4, "relationship_clarity": 4}}}
        calibration = eve.self_awareness_competence_calibration(
            record,
            action_executions=[{"action": "a", "verification_ok": True}] * 3 + [{"action": "a", "verification_ok": False}] * 3,
            outcomes=[],
        )
        self.assertTrue(calibration["available"])
        self.assertTrue(calibration["non_leaky"])
        self.assertFalse(calibration["calibrated"])
        self.assertEqual("overconfident", calibration["direction"])
        good = eve.self_awareness_competence_calibration(
            record, action_executions=[{"action": "a", "verification_ok": True}] * 6, outcomes=[]
        )
        self.assertTrue(good["calibrated"])
        evidence_keys = eve.build_micro_self_awareness_evidence_bundle.__code__.co_names
        self.assertNotIn("measured_competence_summary", evidence_keys)


class MemoryFocusTests(unittest.TestCase):
    def setUp(self):
        self.config = dict(eve.DEFAULT_CONFIG)
        self.threads = [
            {
                "id": "t1",
                "title": "Fly organ looming escape drill",
                "summary": "The fly organ escape drill after the looming stimulus needs a lesion control",
            }
        ]
        self.memory = "Recalled: the looming stimulus escape drill on the fly organ needs its lesion control"

    def test_corroborated_strong_memory_is_admitted(self):
        decision = eve.memory_broadcast_focus_admission(
            self.memory, {"kind": "memory"}, 80, threads=self.threads, messages=[], config=self.config
        )
        self.assertTrue(decision["admit"])
        self.assertEqual("thread:t1", decision["corroborated_by"])

    def test_weak_or_uncorroborated_memory_stays_background(self):
        weak = eve.memory_broadcast_focus_admission(
            self.memory, {"kind": "memory"}, 50, threads=self.threads, messages=[], config=self.config
        )
        foreign = eve.memory_broadcast_focus_admission(
            "Recalled: The user liked the garden photos from the lake trip",
            {"kind": "memory"},
            90,
            threads=self.threads,
            messages=[],
            config=self.config,
        )
        self.assertFalse(weak["admit"])
        self.assertFalse(foreign["admit"])

    def test_message_can_corroborate_memory(self):
        messages = [{"id": "m1", "body": "Can you rerun the looming escape drill on the fly organ with the lesion control?"}]
        decision = eve.memory_broadcast_focus_admission(
            self.memory, {"kind": "memory"}, 70, threads=[], messages=messages, config=self.config
        )
        self.assertTrue(decision["admit"])
        self.assertEqual("message:m1", decision["corroborated_by"])


class BudgetedSynthesisTests(unittest.TestCase):
    def setUp(self):
        self.config = dict(eve.DEFAULT_CONFIG)
        self.payload = {"current_focus": "fly organ thread", "next_step": "check organ status", "lanes": {"grounding": "g"}, "grounding_notes": ["d"]}
        self.packets = [{"lane_name": "observer", "lane": "Organ signals are calm."}]

    def synth(self, response, snapshot, critic=None):
        with patch.object(eve, "model_chat", return_value=response) as chat, patch.object(
            eve,
            "evaluate_mind_stream_packets_grounding",
            return_value=critic if critic is not None else {"synthesis": {"ok": True, "reason": "entailed", "unsupported_claims": []}},
        ) as critic_call, patch.object(eve, "append_mind_stream_packet", return_value={}):
            result = eve.budgeted_mind_stream_model_synthesis(
                self.config,
                self.packets,
                deterministic_payload=dict(self.payload),
                current_evidence_context="ctx",
                lane_models={"planner": "eve-fast"},
                turn_id="turn",
                source="test",
                system_snapshot=snapshot,
            )
        return result, chat, critic_call

    def test_not_attempted_when_lanes_are_not_measurably_ready(self):
        result, chat, _ = self.synth("{}", {})
        self.assertFalse(result["attempted"])
        chat.assert_not_called()

    def test_admitted_overlay_keeps_executive_authority(self):
        good = json.dumps(
            {
                "summary": "The fly organ thread remains the live concern; no new action has started.",
                "lanes": {"observer": "Organ signals are calm.", "planner": "The next check is a candidate, not started."},
                "live_concerns": ["fly organ health"],
                "grounding_notes": ["Packets agree on the organ thread."],
            }
        )
        result, _, critic = self.synth(good, fresh_probe_snapshot())
        self.assertTrue(result["admitted"])
        critic.assert_called_once()
        overlay = result["overlay"]
        self.assertNotIn("current_focus", overlay)
        self.assertNotIn("next_step", overlay)
        self.assertNotIn("live_threads", overlay)
        self.assertEqual("g", overlay["lanes"]["grounding"])
        self.assertTrue(overlay["model"].startswith("deterministic-grounded-executive-fusion+"))

    def test_prose_boundary_rejects_before_the_critic_runs(self):
        bad = json.dumps({"summary": "I am monitoring the organ right now and I ran the cleanup.", "lanes": {}})
        result, _, critic = self.synth(bad, fresh_probe_snapshot())
        self.assertFalse(result["admitted"])
        critic.assert_not_called()
        self.assertIn("current activity", result["reason"])

    def test_critic_rejection_leaves_deterministic_payload(self):
        good = json.dumps({"summary": "The organ thread is the live concern.", "lanes": {}})
        result, _, _ = self.synth(good, fresh_probe_snapshot(), critic={"synthesis": {"ok": False, "reason": "not entailed", "unsupported_claims": ["x"]}})
        self.assertFalse(result["admitted"])
        self.assertEqual({}, result["overlay"])

    def test_disabled_by_config(self):
        self.config["mind_stream_model_synthesis_enabled"] = False
        result, chat, _ = self.synth("{}", fresh_probe_snapshot())
        self.assertFalse(result["attempted"])
        chat.assert_not_called()


if __name__ == "__main__":
    unittest.main()
