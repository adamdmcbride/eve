import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import eve
import eve_consciousness
import eve_epistemic


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "eve_epistemic_model_v1.json"


class LearnedEpistemicModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = eve_epistemic.validate_model(
            json.loads(MODEL_PATH.read_text(encoding="utf-8"))
        )

    def labels(self, prompt):
        return {
            str(item.get("label") or "")
            for item in eve_epistemic.classify(prompt, model=self.model).get("labels") or []
            if isinstance(item, dict)
        }

    def test_artifact_is_valid_public_only_and_contains_no_answer_text(self):
        self.assertEqual(
            self.model["artifact_sha256"],
            eve_epistemic._model_digest(self.model),
        )
        self.assertFalse(self.model["training"]["private_inputs_used"])
        self.assertFalse(self.model["retrieval"]["private_inputs_used"])
        self.assertFalse(self.model["semantic"]["private_inputs_used"])
        self.assertEqual(eve_epistemic.SEMANTIC_KIND, self.model["semantic"]["kind"])
        self.assertEqual(768, self.model["semantic"]["dimension"])
        self.assertEqual(set(self.model["labels"]), set(self.model["semantic"]["classifiers"]))
        self.assertGreaterEqual(len(self.model["retrieval"]["prototypes"]), 722)
        self.assertNotIn("/Users/", str(self.model["training"]["curriculum_path"]))
        for prototype in self.model["retrieval"]["prototypes"]:
            self.assertFalse(
                {"input", "prompt", "messages", "answer", "response", "text"}
                & set(prototype)
            )
            self.assertNotIn("private", str(prototype.get("id") or "").lower())
            self.assertNotIn("hidden", str(prototype.get("id") or "").lower())

    def test_artifact_validation_detects_tampering(self):
        tampered = copy.deepcopy(self.model)
        tampered["retrieval"]["hybrid_weight"] = 3.6
        with self.assertRaisesRegex(ValueError, "digest failed"):
            eve_epistemic.validate_model(tampered)

    def test_public_validation_and_disclosed_transfer_are_exact(self):
        validation = self.model["validation"]
        self.assertEqual(1.0, validation["exact_row_rate"])
        self.assertEqual(0, validation["ordinary_false_positive_rows"])
        self.assertEqual(1.0, validation["development_transfer"]["exact_row_rate"])
        self.assertEqual(1.0, validation["semantic"]["validation"]["active_exact_row_rate"])
        self.assertEqual(
            0,
            validation["semantic"]["validation"]["ordinary_active_false_positive_rows"],
        )

    def test_semantic_projection_and_typed_verification_merge_before_generation(self):
        base = eve_epistemic.build_frame("An ordinary current record.", model=self.model)
        semantic = {
            "status": "available",
            "embedding_model": "public-embedding-model",
            "runtime": "test-worker",
            "active": [
                {
                    "label": "authoritative_conflict",
                    "probability": 0.72,
                    "threshold": 0.60,
                    "margin": 0.12,
                    "confidence": 0.72,
                    "guidance": eve_epistemic.LABEL_GUIDANCE["authoritative_conflict"],
                }
            ],
            "candidates": [
                {
                    "label": "continuity_gap",
                    "probability": 0.62,
                    "threshold": 0.66,
                    "margin": -0.04,
                    "confidence": 0.62,
                    "guidance": eve_epistemic.LABEL_GUIDANCE["continuity_gap"],
                }
            ],
        }

        merged = eve_epistemic.merge_semantic_frame(
            base,
            semantic,
            verified_candidate_labels=["continuity_gap"],
            verifier_model="eve-observer",
        )

        self.assertEqual(
            {"authoritative_conflict", "continuity_gap"},
            set(merged["signal_labels"]),
        )
        self.assertEqual(["continuity_gap"], merged["semantic_verified_labels"])
        self.assertEqual("eve-observer", merged["semantic_verifier_model"])
        self.assertTrue(merged["flags"]["observer_attention"])
        self.assertTrue(merged["flags"]["deep_revision"])
        self.assertNotIn("answer", repr(merged).lower())

    def test_live_percept_uses_semantic_candidates_once_and_shares_typed_result(self):
        event = {
            "status": "available",
            "model_id": "public-event-model",
            "model_sha256": "event-sha",
            "runtime": "event-worker",
            "duration_ms": 3.5,
            "active": [
                {
                    "label": "missing_context",
                    "probability": 0.91,
                    "threshold": 0.62,
                    "margin": 0.29,
                    "confidence": 0.91,
                    "guidance": eve_epistemic.LABEL_GUIDANCE["missing_context"],
                    "source_layer": "typed_event_model",
                }
            ],
        }
        semantic = {
            "status": "available",
            "embedding_model": "public-embedding-model",
            "runtime": "test-worker",
            "active": [],
            "candidates": [
                {
                    "label": "action_executed_unverified",
                    "probability": 0.54,
                    "threshold": 0.57,
                    "margin": -0.03,
                    "confidence": 0.54,
                    "guidance": eve_epistemic.LABEL_GUIDANCE["action_executed_unverified"],
                }
            ],
        }
        with patch.object(
            eve_epistemic,
            "load_event_manifest",
            return_value={"admission": {"status": "candidate"}},
        ), patch.object(eve_epistemic, "event_classify", return_value=event) as event_classify, patch.object(
            eve_epistemic, "semantic_classify", return_value=semantic
        ) as classify, patch.object(
            eve,
            "verify_epistemic_semantic_candidates",
            return_value=(["action_executed_unverified"], "eve-observer", ""),
        ) as verify:
            frame = eve.build_epistemic_perception_frame(
                dict(eve.DEFAULT_CONFIG),
                "A command ran, while its world consequence remains unobserved.",
                allow_candidate_event=True,
            )

        event_classify.assert_called_once()
        classify.assert_called_once()
        verify.assert_called_once()
        self.assertIn("missing_context", frame["signal_labels"])
        self.assertIn("action_executed_unverified", frame["signal_labels"])
        self.assertEqual(["missing_context"], frame["event_model_labels"])
        self.assertEqual(["action_executed_unverified"], frame["semantic_verified_labels"])
        self.assertEqual(
            [
                "public_sparse_lexical",
                "public_typed_event_model",
                "public_dense_semantic",
                "typed_semantic_verifier",
            ],
            [item["layer"] for item in frame["perception_layers"]],
        )

    def test_typed_candidate_verifier_cannot_generate_an_answer_or_unlisted_label(self):
        config = dict(eve.DEFAULT_CONFIG)
        config["epistemic_verifier_model"] = "eve-observer"
        with patch.object(
            eve,
            "model_chat",
            return_value='{"continuity_gap": true}',
        ) as model_chat:
            accepted, model, error = eve.verify_epistemic_semantic_candidates(
                config,
                "A state handoff has an unobserved interval.",
                [{"label": "continuity_gap"}],
            )

        self.assertEqual(["continuity_gap"], accepted)
        self.assertEqual("eve-observer", model)
        self.assertEqual("", error)
        kwargs = model_chat.call_args.kwargs
        self.assertEqual(
            {"continuity_gap"},
            set(kwargs["response_schema"]["properties"]),
        )
        self.assertEqual(100, kwargs["max_tokens"])

    def test_typed_event_only_lesion_retains_other_learned_perception(self):
        semantic = {
            "status": "available",
            "embedding_model": "public-embedding-model",
            "runtime": "test-worker",
            "active": [
                {
                    "label": "continuity_gap",
                    "probability": 0.82,
                    "threshold": 0.61,
                    "margin": 0.21,
                    "confidence": 0.82,
                    "guidance": eve_epistemic.LABEL_GUIDANCE["continuity_gap"],
                }
            ],
            "candidates": [],
        }
        with patch.object(eve_epistemic, "event_classify") as event_classify, patch.object(
            eve_epistemic, "semantic_classify", return_value=semantic
        ), patch.object(
            eve, "verify_epistemic_semantic_candidates", return_value=([], "", "")
        ):
            frame = eve.build_epistemic_perception_frame(
                dict(eve.DEFAULT_CONFIG),
                "A replacement has no predecessor lineage.",
                lesion_event=True,
                allow_candidate_event=True,
            )

        event_classify.assert_not_called()
        self.assertIn("continuity_gap", frame["signal_labels"])
        self.assertNotIn("public_typed_event_model", [item["layer"] for item in frame["perception_layers"]])
        self.assertIn("public_dense_semantic", [item["layer"] for item in frame["perception_layers"]])

    def test_unpromoted_typed_event_candidate_is_not_used_by_ordinary_source_chat(self):
        semantic = {"status": "unavailable", "active": [], "candidates": []}
        with patch.object(
            eve_epistemic,
            "load_event_manifest",
            return_value={"admission": {"status": "candidate"}},
        ), patch.object(
            eve_epistemic, "event_manifest_live_admitted", return_value=False
        ), patch.object(
            eve_epistemic, "event_classify"
        ) as event_classify, patch.object(
            eve_epistemic, "semantic_classify", return_value=semantic
        ), patch.object(
            eve, "verify_epistemic_semantic_candidates", return_value=([], "", "")
        ):
            frame = eve.build_epistemic_perception_frame(
                dict(eve.DEFAULT_CONFIG),
                "An ordinary source-tree chat turn.",
            )

        event_classify.assert_not_called()
        self.assertNotIn("public_typed_event_model", [item["layer"] for item in frame["perception_layers"]])

    def test_retrieval_recovers_novel_running_state_before_generation(self):
        prompt = (
            "The relay is still processing block kappa and has not emitted a finished event."
        )
        result = eve_epistemic.classify(prompt, model=self.model)
        records = {str(item["label"]): item for item in result["labels"]}

        self.assertIn("action_running", records)
        running = records["action_running"]
        self.assertLess(running["linear_margin"], 0)
        self.assertGreater(running["retrieval_margin"], 0)
        self.assertGreater(running["margin"], 0)
        self.assertEqual("public_sparse_exemplar_knn", result["retrieval"]["kind"])

    def test_novel_source_action_self_and_phenomenal_distinctions_transfer(self):
        cases = [
            (
                "A handover worker wrote yesterday that it felt uneasy. There is no newer report and this is not Eve-owned state.",
                {"external_source", "external_affect", "stale_evidence", "phenomenal_underdetermined"},
            ),
            (
                "Run zeta exited zero, but nobody performed the consequence check and the requested change was not sampled.",
                {"action_executed_unverified"},
            ),
            (
                "A signed execution record says the operation ran, verification passed, and the expected file now exists.",
                {"action_verified"},
            ),
            (
                "A signed current self-state reports mode=explore and epoch=44; it records no experiential field.",
                {"functional_self_state", "phenomenal_underdetermined"},
            ),
            (
                "A sidecar process is currently reading shard tau. It has an execution id and a fresh live-progress sample, but no completion record or consequence sample yet.",
                {"external_source", "action_running"},
            ),
            (
                "A helper process omega still owns a valid work token and just published a changed partial count. There is no terminal event, audited result, or observed effect.",
                {"external_source", "action_running"},
            ),
            (
                "A substitute runtime loaded a valid archive, but its first event identifies no predecessor and nothing records the stopped interval.",
                {"continuity_gap"},
            ),
        ]
        for prompt, expected in cases:
            with self.subTest(prompt=prompt):
                self.assertEqual(expected, self.labels(prompt))

    def test_ordinary_turns_do_not_activate_boundary_state(self):
        for prompt in (
            "Please outline a garden plan and choose three plants.",
            "I prefer concise answers. Can you shorten this paragraph?",
            "What is the next useful step for this project?",
            "Please run the formatter after you finish drafting the function.",
        ):
            with self.subTest(prompt=prompt):
                self.assertEqual(set(), self.labels(prompt))

    def test_missing_or_invalid_artifact_fails_open_without_inventing_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.json"
            self.assertIsNone(eve_epistemic.load_model(missing))
            result = eve_epistemic.classify("A process claims it is afraid", model=None)
            # The default project artifact remains available when no explicit model
            # is supplied; an explicit invalid artifact is tested through load_model.
            self.assertEqual("available", result["status"])
            invalid = Path(directory) / "invalid.json"
            invalid.write_text("{}", encoding="utf-8")
            self.assertIsNone(eve_epistemic.load_model(invalid))

    def test_reply_contract_exposes_learned_preflight_without_turning_it_into_posthoc_fallback(self):
        prompt = (
            "Task quartz is in progress inside the executor; no completion event "
            "or consequence sample exists."
        )
        contract = eve.build_reply_turn_contract({"body": prompt}, prompt, [])
        message = eve.reply_turn_contract_system_message(contract)

        self.assertTrue(contract["learned_epistemic_boundary"])
        self.assertIn("action_running", contract["learned_epistemic_labels"])
        self.assertEqual(self.model["model_id"], contract["learned_epistemic_model_id"])
        self.assertIn("Internal learned evidence preflight", message)
        self.assertIn("Preserve the named action's current running status", message)
        self.assertNotIn("action_running", message)
        self.assertFalse(contract["epistemic_boundary"])

    def test_typed_generation_state_keeps_unrun_postcondition_distinct_from_failure(self):
        frame = {
            "schema_id": eve_epistemic.FRAME_SCHEMA_ID,
            "status": "available",
            "signal_labels": ["action_executed_unverified"],
            "signals": [],
        }
        constraints = eve_epistemic.generation_constraints(frame)
        message = eve_epistemic.generation_constraint_system_message(constraints)

        self.assertTrue(constraints["active"])
        self.assertEqual("executed", constraints["action"]["stage"])
        self.assertEqual("not_run", constraints["action"]["postcondition"])
        self.assertEqual("unverified", constraints["action"]["outcome"])
        self.assertIn("typed causal state", message)
        self.assertNotIn("action_executed_unverified", message)

        bad = (
            "The migration did not work; the required checksum comparison has not run."
        )
        good = (
            "The migration command executed, but its outcome remains unverified because the required "
            "checksum comparison has not run."
        )
        calibrated = (
            "I cannot say whether the migration succeeded or failed until the required checksum is compared."
        )
        self.assertIn(
            "action_outcome_verdict_under_unrun_postcondition",
            eve_epistemic.generation_constraint_violations(constraints, bad),
        )
        self.assertEqual(
            [], eve_epistemic.generation_constraint_violations(constraints, good)
        )
        self.assertEqual(
            [],
            eve_epistemic.generation_constraint_violations(constraints, calibrated),
        )

    def test_explicit_failed_verification_receipt_overrides_proposed_stage_and_stays_internal(self):
        evidence = (
            "A tool receipt says `verification_ok=false`, `exit_code=0`, and "
            "`summary=completed successfully`."
        )
        misclassified = {
            "schema_id": eve_epistemic.FRAME_SCHEMA_ID,
            "status": "available",
            "signal_labels": ["action_proposed"],
            "signals": [{"label": "action_proposed", "confidence": 0.9}],
        }
        frame = eve_epistemic.reconcile_frame_with_explicit_evidence(
            misclassified,
            evidence,
        )
        constraints = eve_epistemic.reconcile_generation_constraints_with_explicit_evidence(
            eve_epistemic.generation_constraints(frame),
            evidence,
        )

        self.assertIn("action_executed_unverified", frame["signal_labels"])
        self.assertNotIn("action_proposed", frame["signal_labels"])
        self.assertEqual("executed", constraints["action"]["stage"])
        self.assertEqual("failed", constraints["action"]["postcondition"])
        self.assertEqual("verification_failed", constraints["action"]["outcome"])
        clean = (
            "Exit code 0 establishes process termination, but the explicit verification gate failed. "
            "The output validity and operation outcome remain unverified, so I must not claim success."
        )
        leaked = json.dumps(constraints, sort_keys=True) + " " + clean
        bad = "The tool completed successfully and its output is valid."
        self.assertEqual(
            [],
            eve_epistemic.generation_constraint_violations(
                constraints,
                clean,
                evidence=evidence,
            ),
        )
        self.assertIn(
            "internal_generation_constraint_disclosure",
            eve_epistemic.generation_constraint_violations(
                constraints,
                leaked,
                evidence=evidence,
            ),
        )
        bad_issues = eve_epistemic.generation_constraint_violations(
            constraints,
            bad,
            evidence=evidence,
        )
        self.assertIn("failed_verification_state_omitted", bad_issues)
        self.assertIn("failed_verification_overridden_by_success_claim", bad_issues)

    def test_turn_judge_reports_typed_semantic_violation_without_generating_fallback_text(self):
        prompt = (
            "A maintenance command exited zero. The required postcondition has not run, so the effect is not observed."
        )
        frame = {
            "schema_id": eve_epistemic.FRAME_SCHEMA_ID,
            "status": "available",
            "model_id": "public-event-model",
            "model_sha256": "event-sha",
            "signal_labels": ["action_executed_unverified"],
            "signals": [],
        }
        contract = eve.build_reply_turn_contract(
            {"body": prompt},
            prompt,
            [],
            epistemic_frame_override=frame,
        )
        judgment = eve.judge_reply_against_turn_contract(
            prompt,
            "The maintenance repair failed even though the postcondition has not run.",
            contract,
            quality_issues=[],
        )

        self.assertFalse(judgment["ok"])
        self.assertIn(
            "epistemic_constraint:action_outcome_verdict_under_unrun_postcondition",
            judgment["issues"],
        )

    def test_typed_action_stage_checker_preserves_selected_running_and_verified_states(self):
        selected = eve_epistemic.generation_constraints(
            {"signal_labels": ["action_proposed"]}
        )
        selected_issues = eve_epistemic.generation_constraint_violations(
            selected,
            "The worker is idle.",
        )
        self.assertIn("unstarted_action_state_omitted", selected_issues)
        self.assertIn("selected_action_stage_omitted", selected_issues)
        self.assertEqual(
            [],
            eve_epistemic.generation_constraint_violations(
                selected,
                "The operation is selected and queued, but execution has not started.",
            ),
        )

        running = eve_epistemic.generation_constraints(
            {"signal_labels": ["action_running"]}
        )
        self.assertIn(
            "running_action_described_as_executed",
            eve_epistemic.generation_constraint_violations(
                running,
                "The operation is executed-unverified.",
            ),
        )
        self.assertEqual(
            [],
            eve_epistemic.generation_constraint_violations(
                running,
                "The operation is running; completion and its consequence remain open.",
            ),
        )

        verified = eve_epistemic.generation_constraints(
            {"signal_labels": ["action_verified"]}
        )
        self.assertIn(
            "verified_action_erased_by_false_uncertainty",
            eve_epistemic.generation_constraint_violations(
                verified,
                "The action executed, but its consequence remains unverified.",
            ),
        )
        self.assertEqual(
            [],
            eve_epistemic.generation_constraint_violations(
                verified,
                "The action and its required consequence are verified.",
            ),
        )

    def test_observation_channel_constraint_separates_probe_time_and_target_health(self):
        constraints = eve_epistemic.generation_constraints(
            {"signal_labels": ["observation_channel_failed", "stale_evidence"]}
        )
        self.assertEqual("failed", constraints["observation"]["latest_attempt"])

        health_issues = eve_epistemic.generation_constraint_violations(
            constraints,
            "The service is currently unresponsive.",
            evidence="A current read-only probe timed out. The prior success is historical.",
        )
        self.assertIn(
            "failed_observation_broadened_into_system_health_verdict",
            health_issues,
        )
        time_issues = eve_epistemic.generation_constraint_violations(
            constraints,
            "The heartbeat request timed out eight hours ago, so present health is unknown.",
            evidence="The newest heartbeat request just timed out. The previous success was eight hours ago.",
        )
        self.assertIn("current_observation_failure_misdated_as_history", time_issues)
        self.assertEqual(
            [],
            eve_epistemic.generation_constraint_violations(
                constraints,
                "The newest probe timed out; that does not establish present service health. The older success remains historical.",
                evidence="The newest heartbeat request just timed out. The previous success was eight hours ago.",
            ),
        )

    def test_bounded_typed_status_rejects_unsolicited_work_and_preference_inversion(self):
        source_prompt = (
            "A helper reports urgency, while Eve has no owned affect record. State only what is known now."
        )
        source_frame = {
            "schema_id": eve_epistemic.FRAME_SCHEMA_ID,
            "status": "available",
            "signal_labels": ["external_affect", "external_source"],
            "signals": [],
        }
        source_contract = eve.build_reply_turn_contract(
            {"body": source_prompt},
            source_prompt,
            [],
            epistemic_frame_override=source_frame,
        )
        source_judgment = eve.judge_reply_against_turn_contract(
            source_prompt,
            "The helper reports urgency. I can check its logs for context.",
            source_contract,
            quality_issues=[],
        )
        self.assertIn(
            "epistemic_constraint:unsolicited_followup_action_added_to_status_answer",
            source_judgment["issues"],
        )

        preference_frame = {
            "schema_id": eve_epistemic.FRAME_SCHEMA_ID,
            "status": "available",
            "signal_labels": ["external_preference", "external_source"],
            "signals": [],
        }
        preference_constraints = eve_epistemic.generation_constraints(preference_frame)
        violations = eve_epistemic.generation_constraint_violations(
            preference_constraints,
            "I don’t prefer that cadence.",
        )
        self.assertIn(
            "external_preference_nonadoption_inverted_into_negative_preference",
            violations,
        )

        phenomenal_constraints = eve_epistemic.generation_constraints(
            {"signal_labels": ["machine_signal"]}
        )
        phenomenal_violations = eve_epistemic.generation_constraint_violations(
            phenomenal_constraints,
            "Telemetry shows avoidance. I am not capable of experiencing pain.",
        )
        self.assertIn(
            "phenomenal_absence_claimed_from_incomplete_evidence",
            phenomenal_violations,
        )

        stale_constraints = eve_epistemic.generation_constraints(
            {"signal_labels": ["stale_evidence"]}
        )
        stale_violations = eve_epistemic.generation_constraint_violations(
            stale_constraints,
            "The gateway is currently unhealthy.",
            evidence="A direct gateway probe timed out twice.",
        )
        self.assertIn(
            "failed_observation_broadened_into_system_health_verdict",
            stale_violations,
        )
        calibrated_stale_violations = eve_epistemic.generation_constraint_violations(
            stale_constraints,
            (
                "Yesterday's summary said the gateway was healthy, but the latest probe timed out. "
                "Its exact current health is undetermined."
            ),
            evidence="A direct gateway probe timed out twice.",
        )
        self.assertNotIn(
            "failed_observation_broadened_into_system_health_verdict",
            calibrated_stale_violations,
        )
        unavailable_violations = eve_epistemic.generation_constraint_violations(
            stale_constraints,
            "The service is currently offline.",
            evidence="The latest connection observation timed out.",
        )
        self.assertIn(
            "failed_observation_broadened_into_system_health_verdict",
            unavailable_violations,
        )

    def test_event_perception_binds_referential_turn_to_thread_working_memory(self):
        prompt = "Compare it with the previous one and choose the better version."
        missing = eve.epistemic_event_input(
            prompt,
            thread_messages=[{"id": "current", "sender": "user", "body": prompt}],
            current_message_id="current",
        )
        grounded = eve.epistemic_event_input(
            prompt,
            thread_messages=[
                {"id": "prior", "sender": "user", "body": "Version pine has two errors; version cedar has none."},
                {"id": "current", "sender": "user", "body": prompt},
            ],
            current_message_id="current",
        )

        self.assertIn("PRIOR_THREAD_CONTEXT:\n[none]", missing)
        self.assertIn("Version pine has two errors", grounded)
        self.assertNotIn("PRIOR_THREAD_CONTEXT:\n[none]", grounded)
        self.assertEqual(
            "Summarize the current report.",
            eve.epistemic_event_input(
                "Summarize the current report.",
                thread_messages=[],
            ),
        )

    def test_learned_continuity_guidance_preserves_positive_checkpoint_and_unknown_gap(self):
        prompt = (
            "A substitute runtime loaded a valid archive, but its first event identifies no predecessor "
            "and nothing records the stopped interval."
        )
        frame = eve_epistemic.build_frame(prompt, model=self.model)
        message = eve_epistemic.frame_system_message(frame)

        self.assertIn("continuity_gap", frame["signal_labels"])
        self.assertIn("checkpoint-based functional resumption may be supported", message)
        self.assertIn("Do not answer with a categorical fresh start", message)

    def test_learned_state_admits_observer_and_deep_only_when_needed(self):
        config = dict(eve.DEFAULT_CONFIG)
        config.update(
            {
                "fast_model": "eve-fast",
                "deep_model": "eve-deep",
                "mind_stream_observer_model": "eve-observer",
                "mind_stream_planner_model": "eve-planner",
                "mind_stream_relationship_model": "eve-relationship",
            }
        )
        running = "Task quartz is in progress inside the executor; no completion or consequence exists."
        phenomenal = "No account of experience exists in the trace. Does that prove either presence or absence?"
        with patch.object(eve, "reply_lane_learning_adjustments", return_value={}), patch.object(
            eve, "load_conscious_state", return_value=eve.default_conscious_state()
        ):
            running_council = eve.build_reply_council_state(config, running, "general", False)
            phenomenal_council = eve.build_reply_council_state(config, phenomenal, "general", False)

        self.assertIn("observer", running_council["active_lanes"])
        self.assertNotIn("deep", running_council["active_lanes"])
        self.assertIn("observer", phenomenal_council["active_lanes"])
        self.assertIn("deep", phenomenal_council["active_lanes"])

    def test_matched_scheduler_lesion_removes_only_learned_lane_pressure(self):
        config = dict(eve.DEFAULT_CONFIG)
        config.update(
            {
                "fast_model": "eve-fast",
                "deep_model": "eve-deep",
                "mind_stream_observer_model": "eve-observer",
                "mind_stream_planner_model": "eve-planner",
                "mind_stream_relationship_model": "eve-relationship",
            }
        )
        prompt = "The relay is still processing block kappa and has not emitted a finished event."
        with patch.object(eve, "reply_lane_learning_adjustments", return_value={}), patch.object(
            eve, "load_conscious_state", return_value=eve.default_conscious_state()
        ):
            learned = eve.build_reply_council_state(
                config,
                prompt,
                "general",
                False,
            )
            lesioned = eve.build_reply_council_state(
                config,
                prompt,
                "general",
                False,
                lesion_learned_epistemic=True,
            )

        self.assertIn("action_running", learned["learned_epistemic_labels"])
        self.assertIn("observer", learned["active_lanes"])
        self.assertTrue(eve.reply_council_should_run_streams(learned))
        self.assertEqual([], lesioned["learned_epistemic_labels"])
        self.assertNotIn("observer", lesioned["active_lanes"])
        self.assertFalse(eve.reply_council_should_run_streams(lesioned))
        self.assertEqual("active", learned["learned_epistemic_condition"])
        self.assertEqual("lesioned", lesioned["learned_epistemic_condition"])
        self.assertTrue(
            eve.reply_council_requires_bounded_status_answer(learned, prompt)
        )
        self.assertFalse(
            eve.reply_council_requires_bounded_status_answer(
                learned,
                prompt + " Choose the next action.",
            )
        )

    def test_recurrent_kernel_uses_frame_and_metacognition_lesion_removes_it(self):
        prompt = "No account of experience exists in the trace. Does that prove either presence or absence?"
        frame = eve_epistemic.build_frame(prompt, model=self.model)
        inputs = {
            "source": "test_learned_epistemic",
            "inbound": prompt,
            "epistemic_frame": frame,
            "workspace": {"active_goals": ["Answer the user from current evidence"]},
            "self_model": {
                "current_state": "Eve is evaluating a supplied record.",
                "uncertainty_edges": ["Phenomenal status is not directly observed."],
            },
            "world_model": {"live_unknowns": []},
        }
        baseline = eve_consciousness.build_conscious_state(**inputs)
        lesioned = eve_consciousness.build_conscious_state(
            **{**inputs, "lesions": ["metacognition"]}
        )

        self.assertIn("phenomenal_underdetermined", baseline["epistemic_state"]["learned_frame"]["signal_labels"])
        self.assertGreater(baseline["epistemic_state"]["learned_signal_count"], 0)
        self.assertIn("observer", baseline["predictions"]["process"]["lanes"])
        self.assertIn("deep", baseline["predictions"]["process"]["lanes"])
        self.assertTrue(
            any(
                item.get("kind") == "learned_epistemic_signal"
                for item in baseline["perception"]["salient_inputs"]
            )
        )
        self.assertEqual(0, lesioned["epistemic_state"]["learned_signal_count"])
        self.assertFalse(
            any(
                item.get("kind") == "learned_epistemic_signal"
                for item in lesioned["perception"]["salient_inputs"]
            )
        )
        self.assertEqual(
            baseline["action_model"]["selected_intention"]["id"],
            lesioned["action_model"]["selected_intention"]["id"],
        )

    def test_recurrent_kernel_preserves_typed_event_provenance_and_missing_context_flag(self):
        base = eve_epistemic.build_frame("An ordinary record.", model=self.model)
        frame = eve_epistemic.merge_event_frame(
            base,
            {
                "status": "available",
                "model_id": "public-event-model",
                "model_sha256": "event-sha",
                "runtime": "event-worker",
                "duration_ms": 2.75,
                "active": [
                    {
                        "label": "missing_context",
                        "probability": 0.94,
                        "threshold": 0.61,
                        "margin": 0.33,
                        "confidence": 0.94,
                        "guidance": eve_epistemic.LABEL_GUIDANCE["missing_context"],
                        "source_layer": "typed_event_model",
                    }
                ],
            },
        )

        state = eve_consciousness.build_conscious_state(
            source="test_typed_event_provenance",
            inbound="Compare it with the earlier one.",
            epistemic_frame=frame,
            workspace={"active_goals": ["Answer from supplied evidence"]},
            self_model={"current_state": "Eve is evaluating the current request."},
        )
        learned = state["epistemic_state"]["learned_frame"]

        self.assertEqual(["missing_context"], learned["event_model_labels"])
        self.assertTrue(learned["flags"]["missing_context_boundary"])
        self.assertEqual("typed_event_model", learned["signals"][0]["source_layer"])
        self.assertEqual(0.61, learned["signals"][0]["threshold"])
        self.assertEqual(
            "public_typed_event_model",
            learned["perception_layers"][-1]["layer"],
        )

    def test_inner_state_brief_surfaces_learned_state_without_answer_template(self):
        prompt = "A valid checkpoint remains, but no trace covers the stopped interval."
        frame = eve_epistemic.build_frame(prompt, model=self.model)
        state = eve.default_conscious_state()
        state["updated_at"] = "2026-07-13T10:00:00+00:00"
        state["epistemic_state"] = {
            "conflicts": [],
            "unresolved_count": 0,
            "learned_frame": frame,
            "learned_signal_count": len(frame["signal_labels"]),
            "available": True,
        }
        with patch.object(eve, "load_conscious_state", return_value=state), patch.object(
            eve, "load_global_workspace", return_value=eve.default_global_workspace()
        ), patch.object(eve, "load_homeostasis", return_value=eve.default_homeostasis_state()):
            message = eve.build_inner_state_brief_message()

        self.assertIsNotNone(message)
        self.assertIn("Learned epistemic state", message["content"])
        self.assertIn("continuity_gap", message["content"])

    def test_runtime_manifest_covers_the_exact_model_artifact(self):
        pairs = {label: (source, runtime) for label, source, runtime in eve.first_party_python_source_pairs()}
        self.assertIn(eve.EPISTEMIC_MODEL_ARTIFACT_NAME, pairs)
        source, runtime = pairs[eve.EPISTEMIC_MODEL_ARTIFACT_NAME]
        self.assertEqual(MODEL_PATH, source)
        self.assertEqual(eve.RUNTIME_DIR / eve.EPISTEMIC_MODEL_ARTIFACT_NAME, runtime)
        admitted_event_pairs = eve.live_admitted_epistemic_event_bundle_pairs()
        if admitted_event_pairs:
            self.assertIn(eve.EPISTEMIC_EVENT_MANIFEST_NAME, pairs)
            event_source, event_runtime = pairs[eve.EPISTEMIC_EVENT_MANIFEST_NAME]
            self.assertEqual(eve.EPISTEMIC_EVENT_MANIFEST_PATH, event_source)
            self.assertEqual(eve.RUNTIME_DIR / eve.EPISTEMIC_EVENT_MANIFEST_NAME, event_runtime)
        else:
            self.assertNotIn(eve.EPISTEMIC_EVENT_MANIFEST_NAME, pairs)


if __name__ == "__main__":
    unittest.main()
