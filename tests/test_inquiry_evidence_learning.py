"""Public isolated controls: no synthetic evidence is installed in Eve's memory."""
import copy
import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import eve
import eve_consciousness as kernel
import eve_recurrent_cognition as recurrent
from tests.test_recurrent_loop_repair import critic_reply


def episode():
    state = {"target_kind": "durable_goal", "durable_goal": "Inspect the old workspace",
             "action_status": "goal selected; execution is not implied"}
    return dict(id="lesson-1", source="daemon", privacy_tier="local_only", safe_for_training=False,
                candidate_status="rejected_model_candidate_not_state_evidence", attempted_model="eve-fast",
                attempted_response="I am inspecting the old workspace.", preferred_response="Fallback record.",
                current_state_record=state, current_state_record_hash=eve.continuous_thought_state_record_hash(state),
                verified_action_evidence=[{"action": "service_health_check", "completed_at": "2026-09-12T12:00:00Z"}],
                initial_epistemic_critic={"ok": False, "unsupported_claims": ["old activity"]},
                epistemic_critic={"ok": False, "unsupported_claims": ["revised activity"]})


def review(record, **changes):
    body = dict(schema_id="eve.thought_correction_review.v1", episode_id=record["id"],
                evidence_hash=recurrent.thought_learning_review_hash(record), decision="approved",
                target_kind=record["current_state_record"]["target_kind"],
                preferred_response="My selected goal is to inspect the old workspace; it has not started.",
                lesson="A selected goal is not execution; name the goal without claiming it is underway.")
    body.update(changes)
    return dict(id="review-1", status="active", source="manual", reviewer="Codex",
                updated_at="2026-09-13T05:00:00Z", body=json.dumps(body))


def proposal():
    return eve.normalize_inquiry_reasoning_proposal(dict(inquiry_id="q1", source_fingerprint="artifact-version-1",
        action="fly_decoder_probe", model="fixture-model", alternatives=[
            dict(explanation="Decoder exceeds its performance target", predicted_observation="Positive difference",
                 test=dict(metric="graph_minus_double_zero_cm", operator="gt", value=0)),
            dict(explanation="Decoder has not reached that target", predicted_observation="Nonpositive difference",
                 test=dict(metric="graph_minus_double_zero_cm", operator="le", value=0))]))


def artifact(graph=0.025, zero=0.038):
    return {"results": {"graph_decoder": [{"travel_cm": graph}], "zero": [{"travel_cm": zero}]}}


def measurement(graph=0.025, zero=0.038):
    return recurrent.decoder_artifact_measurement(artifact(graph, zero),
        {"closed_loop_mean_travel": {"graph_decoder": graph, "zero": zero}}, "a" * 64)


def outcome(graph=0.025):
    return dict(action="fly_decoder_probe", probe="decoder", executed=True, returncode=0,
                status="completed", ok=graph > 0.076, execution_verification_ok=graph > 0.076,
                execution_id="execution-1", typed_contract={"schema_id": "fly_probe_result.v1", "valid": True},
                summary="Measured the artifact comparison.", measurement=measurement(graph))


class CorrectionTests(unittest.TestCase):
    def test_exact_evidence_and_both_critics_survive_export(self):
        record = episode()
        record["reviewed_lessons"] = [{"review_id": "prior", "lesson": "Earlier reviewed rule"}]
        rows, excluded = eve.training_examples_from_continuous_thought_learning([record], reviews=[review(record)])
        self.assertFalse(excluded)
        row = rows[0]
        self.assertEqual(recurrent.thought_learning_evidence_packet(record), row["available_context"])
        for key in ("verified_action_evidence", "initial_epistemic_critic", "epistemic_critic"):
            self.assertEqual(record[key], row["tool_action_evidence"][key])
        self.assertNotEqual(record["preferred_response"], row["preferred_response"])
        self.assertEqual("review-1", row["provenance"]["correction_review_id"])
        self.assertFalse(row["provenance"]["model_promotion_authority"])

    def test_rejected_revision_is_retained_and_bound_to_review(self):
        record = episode()
        result = dict(record, response=record["preferred_response"], used_fallback=True,
                      repair_candidate_response="I am still doing the unexecuted task.")
        with patch.object(eve, "append_jsonl_record", side_effect=lambda path, r: r), \
             patch.object(eve, "mirror_store_file_to_runtime"):
            saved = eve.record_continuous_thought_learning_episode(result, source="daemon")
        self.assertEqual(result["repair_candidate_response"], saved["repair_candidate_response"])
        note = review(saved)
        rows, _ = eve.training_examples_from_continuous_thought_learning([saved], reviews=[note])
        self.assertEqual(saved["repair_candidate_response"], rows[0]["tool_action_evidence"]["repair_candidate_response"])
        saved["repair_candidate_response"] = "changed"
        self.assertEqual({}, recurrent.reviewed_thought_correction(saved, [note]))

    def test_fallback_eligibility_without_review_cannot_train_or_retrieve(self):
        record = dict(episode(), safe_for_training=True)
        self.assertEqual([], eve.training_examples_from_continuous_thought_learning([record], reviews=[])[0])
        self.assertEqual([], eve.select_reviewed_thought_lessons(record["current_state_record"], [record], []))

    def test_critic_is_not_an_external_review(self):
        record = episode()
        for change in ({"source": "daemon"}, {"reviewer": "eve-deep"}, {"status": "archived"}):
            with self.subTest(change=change):
                note = dict(review(record), **change)
                self.assertEqual({}, recurrent.reviewed_thought_correction(record, [note]))

    def test_changed_evidence_invalidates_review(self):
        for key, value in [("attempted_response", "changed"), ("verified_action_evidence", []),
                           ("epistemic_critic", {}), ("reviewed_lessons", [{"lesson": "new"}])]:
            with self.subTest(key=key):
                record = episode(); note = review(record); record[key] = value
                self.assertEqual({}, recurrent.reviewed_thought_correction(record, [note]))

    def test_latest_revocation_wins_and_round_trip_retains_it(self):
        record = episode(); approved = review(record)
        revoked = dict(review(record, decision="revoked"), id="review-2", updated_at="2026-09-13T06:00:00Z")
        notes = json.loads(json.dumps([approved, revoked]))
        self.assertEqual({}, recurrent.reviewed_thought_correction(record, notes))

    def test_holdouts_synthetic_unknown_privacy_and_incomplete_evidence_are_excluded(self):
        for change in ({"synthetic": True}, {"metadata": {"synthetic": True}}, {"metadata": {"conversation_class": "synthetic_eval"}},
                       {"split": "private_holdout"}, {"privacy_tier": "private"},
                       {"source": "isolated_test"}, {"evaluation_only": True}):
            record = dict(episode(), **change)
            with self.subTest(change=change):
                self.assertEqual({}, recurrent.reviewed_thought_correction(record, [review(record)]))
        record = episode(); del record["verified_action_evidence"]
        self.assertEqual({}, recurrent.reviewed_thought_correction(record, [review(record)]))

    def test_retrieval_is_target_matched_bounded_and_deduplicated(self):
        records = [dict(episode(), id=f"lesson-{i}") for i in range(4)]
        notes = [review(r) for r in records]
        target = {"target_kind": "durable_goal", "durable_goal": "A new goal"}
        selected = eve.select_reviewed_thought_lessons(target, records + records, notes)
        self.assertEqual(2, len(selected))
        self.assertEqual(2, len({r["episode_id"] for r in selected}))
        self.assertEqual([], eve.select_reviewed_thought_lessons({"target_kind": "pressure"}, records, notes))

    def test_real_generation_wiring_retrieves_after_disk_reload_and_keeps_critic_closed_world(self):
        """Model is a controlled stub: this proves wiring, not language-model learning."""
        record = episode(); target = {"target_kind": "durable_goal", "durable_goal": "Inspect the new garden"}
        captured = []
        def model(config, lane, messages, **kwargs):
            text = json.dumps(messages); captured.append((kwargs["operation"], text))
            if "critic" in kwargs["operation"]:
                self.assertNotIn("old workspace", text)
                return critic_reply(True)
            self.assertNotIn("old workspace", text)
            self.assertIn("REVIEWED_HISTORICAL_CORRECTIONS", text)
            self.assertIn("new garden", text)
            return "My selected goal is to inspect the new garden; it has not started."
        with tempfile.TemporaryDirectory() as directory:
            records_path, reviews_path = Path(directory, "episodes"), Path(directory, "reviews")
            records_path.write_text(json.dumps(record) + "\n")
            reviews_path.write_text(json.dumps(review(record)) + "\n")
            with patch.object(eve, "CONTINUOUS_THOUGHT_LEARNING_PATH", records_path), \
                 patch.object(eve, "REVIEW_NOTES_PATH", reviews_path), \
                 patch.object(eve, "resolve_store_read_path", side_effect=lambda p, **kw: p), \
                 patch.object(eve, "ensure_version_snapshot"), \
                 patch.object(eve, "build_current_inner_state_report_record", return_value=target), \
                 patch.object(eve, "recent_verified_action_evidence", return_value=[]), \
                 patch.object(eve, "build_eve_interaction_system_messages", return_value=[]), \
                 patch.object(eve, "model_chat", side_effect=model):
                result = eve.generate_continuous_thought(dict(eve.DEFAULT_CONFIG), 3, 3, 160, 30)
        self.assertFalse(result["used_fallback"])
        self.assertEqual("review-1", result["reviewed_lessons"][0]["review_id"])
        self.assertEqual(2, len(captured))

    def test_malformed_review_never_becomes_a_lesson(self):
        record = episode()
        for body in ("not json", "[]", "null", "{}"):
            self.assertEqual({}, recurrent.reviewed_thought_correction(record, [dict(review(record), body=body)]))
        self.assertEqual({}, recurrent.reviewed_thought_correction([], [None]))


class MeasurementTests(unittest.TestCase):
    def test_negative_measurement_discriminates_without_proving_explanation(self):
        observed = measurement()
        result = recurrent.assess_inquiry_predictions(proposal(), observed)
        self.assertTrue(result["predictions_discriminated"])
        self.assertEqual([False, True], [r["prediction_supported"] for r in result["alternatives"]])
        self.assertFalse(result["causal_explanation_established"])

    def test_new_positive_observation_reverses_supported_prediction(self):
        result = recurrent.assess_inquiry_predictions(proposal(), measurement(0.12))
        self.assertEqual([True, False], [r["prediction_supported"] for r in result["alternatives"]])

    def test_missing_invalid_or_overlapping_tests_do_not_answer(self):
        for observed in ({}, None, {"valid": False}, {"valid": True, "metrics": {}}):
            self.assertFalse(recurrent.assess_inquiry_predictions(proposal(), observed)["predictions_discriminated"])
        p = proposal(); p["alternatives"][1]["test"] = p["alternatives"][0]["test"]
        self.assertFalse(recurrent.assess_inquiry_predictions(p, measurement())["predictions_discriminated"])
        p["alternatives"][1]["test"] = {"metric": "unknown", "operator": "gt", "value": 0}
        self.assertFalse(recurrent.assess_inquiry_predictions(p, measurement())["predictions_discriminated"])

    def test_arbitrary_thresholds_do_not_answer_the_precommitted_question(self):
        p = proposal(); p["alternatives"][0]["test"]["value"] = 100
        result = recurrent.assess_inquiry_predictions(p, measurement())
        self.assertTrue(result["predictions_discriminated"])
        self.assertFalse(recurrent.inquiry_observation_resolved(proposal()["alternatives"][0]["test"], result))
        self.assertFalse(recurrent.inquiry_observation_resolved({}, result))

    def test_predicates_reject_code_booleans_and_nonfinite_values(self):
        for value in (True, "0", float('nan'), float('inf'), 10**1000, None):
            self.assertEqual({}, recurrent.normalize_observation_prediction(dict(metric="x", operator="gt", value=value)))
        self.assertEqual({}, recurrent.normalize_observation_prediction(dict(metric="__import__('os')", operator="gt", value=0)))

    def test_measurements_require_real_controls_and_matching_aggregates(self):
        evidence = {"closed_loop_mean_travel": {"graph_decoder": .025, "zero": .038}}
        for broken in ({}, {"results": {}}, {"results": {"graph_decoder": [], "zero": []}},
                       artifact(float('nan')), artifact(True), artifact(-1)):
            self.assertFalse(recurrent.decoder_artifact_measurement(broken, evidence, "a"*64)["valid"])
        evidence["closed_loop_mean_travel"]["zero"] = 1
        self.assertFalse(recurrent.decoder_artifact_measurement(artifact(), evidence, "a"*64)["valid"])

    def test_forged_measurement_fields_are_not_admitted_on_reload(self):
        for changes in ({"artifact_sha256": "invalid"}, {"valid": "true"}, {"scope": "live"}, {"metrics": {}}):
            self.assertFalse(recurrent.normalize_inquiry_measurement(dict(measurement(), **changes))["valid"])


class InquiryLoopTests(unittest.TestCase):
    def initial(self):
        return eve.normalize_world_model_state(dict(open_questions=[dict(id="q1", question="Does the decoder exceed its target?",
            source_fingerprint="artifact-version-1", candidate_actions=["fly_decoder_probe", "service_health_check"],
            selected_action="fly_decoder_probe", status="open", priority=90,
            observation_test=proposal()["alternatives"][0]["test"])]))

    def record(self, payload):
        class Repository:
            def update(self, f): return f(payload)
        return Repository()

    def decision(self):
        return dict(action="fly_decoder_probe", inquiry_id="q1", inquiry_source_fingerprint="artifact-version-1",
                    reasoning_proposal=proposal())

    def test_negative_answer_persists_removes_inquiry_and_does_not_reward_skill(self):
        initial = self.initial()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "world.json"); path.write_text(json.dumps(initial))
            world = json.loads(path.read_text())
            with patch.object(eve, "WORLD_MODEL_REPOSITORY", self.record(world)):
                result = eve.record_world_model_inquiry_observation(self.decision(), outcome(), run_id="r1", source_cycle_id="c1")
            path.write_text(json.dumps(world)); restored = eve.normalize_world_model_state(json.loads(path.read_text()))
        self.assertTrue(result["answered"])
        self.assertFalse(restored["open_questions"])
        attempt = restored["answered_questions"][0]["attempts"][0]
        self.assertTrue(attempt["measurement"]["valid"])
        self.assertFalse(attempt["outcome_ok"])
        self.assertFalse(eve.action_result_verified_for_completion(outcome()))
        self.assertTrue(attempt["prediction_assessment"]["predictions_discriminated"])
        self.assertEqual([], kernel._open_world_inquiries(restored))
        self.assertTrue(kernel._open_world_inquiries(initial))

    def test_invalid_execution_or_contract_does_not_close_negative_inquiry(self):
        for changes in ({"returncode": 1}, {"executed": False}, {"execution_id": ""}, {"status": "error"},
                        {"typed_contract": {"schema_id": "fly_probe_result.v1", "valid": False}},
                        {"execution_verification_ok": True}, {"probe": "attack"}):
            world = self.initial()
            with self.subTest(changes=changes), patch.object(eve, "WORLD_MODEL_REPOSITORY", self.record(world)):
                result = eve.record_world_model_inquiry_observation(self.decision(), dict(outcome(), **changes), run_id="r1", source_cycle_id="c1")
                self.assertFalse(result["answered"])

    def test_exhausted_probe_receipt_matches_persisted_next_action(self):
        world = self.initial(); world["open_questions"][0]["candidate_actions"] = ["fly_decoder_probe"]
        decision = self.decision(); decision["reasoning_proposal"] = {}
        with patch.object(eve, "WORLD_MODEL_REPOSITORY", self.record(world)):
            result = eve.record_world_model_inquiry_observation(decision, outcome(), run_id="r1", source_cycle_id="c1")
        self.assertTrue(result["probe_exhausted"])
        self.assertFalse(result["recovery_required"])
        self.assertEqual(world["open_questions"][0]["selected_action"], result["next_action"])
        self.assertEqual("", result["next_action"])

    def test_missing_precommitment_never_closes_a_measured_question(self):
        world = self.initial(); world["open_questions"][0].pop("observation_test")
        with patch.object(eve, "WORLD_MODEL_REPOSITORY", self.record(world)):
            result = eve.record_world_model_inquiry_observation(self.decision(), outcome(), run_id="r1", source_cycle_id="c1")
        self.assertFalse(result["answered"])
        self.assertTrue(result["attempt"]["prediction_assessment"]["predictions_discriminated"])

    def test_observation_without_discriminating_predictions_stays_unresolved(self):
        world = self.initial(); decision = self.decision(); decision["reasoning_proposal"] = {}
        with patch.object(eve, "WORLD_MODEL_REPOSITORY", self.record(world)):
            result = eve.record_world_model_inquiry_observation(decision, outcome(.12), run_id="r1", source_cycle_id="c1")
        self.assertFalse(result["answered"])

    def test_stale_source_mismatched_proposal_and_replay_cannot_revise(self):
        world = self.initial(); decision = self.decision()
        with patch.object(eve, "WORLD_MODEL_REPOSITORY", self.record(world)):
            stale = eve.record_world_model_inquiry_observation(dict(decision, inquiry_source_fingerprint="stale"), outcome(), run_id="r1", source_cycle_id="c1")
            self.assertEqual("source_mismatch", stale["status"])
            decision["reasoning_proposal"]["source_fingerprint"] = "other"
            result = eve.record_world_model_inquiry_observation(decision, outcome(), run_id="r1", source_cycle_id="c1")
            self.assertFalse(result["answered"])
            duplicate = eve.record_world_model_inquiry_observation(decision, outcome(), run_id="r2", source_cycle_id="c2")
        self.assertEqual("already_observed", duplicate["status"])

    def test_missing_cycle_cannot_close_measured_inquiry(self):
        world = self.initial()
        with patch.object(eve, "WORLD_MODEL_REPOSITORY", self.record(world)):
            self.assertFalse(eve.record_world_model_inquiry_observation(self.decision(), outcome(), run_id="r", source_cycle_id="")["answered"])

    def test_free_run_uses_actual_runner_and_preserves_negative_measurement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / "bc").mkdir()
            (root / "bc/eval.json").write_text(json.dumps(artifact()))
            (root / "fly_probe.py").write_text('import json, pathlib\nprint(json.dumps({"ok":False,"summary":"negative result",'
                '"artifact_path":str(pathlib.Path("bc/eval.json").resolve()),'
                '"evidence":{"closed_loop_mean_travel":{"graph_decoder":0.025,"zero":0.038}}}))\n')
            config = dict(eve.DEFAULT_CONFIG, fly_lab_path=directory)
            with patch.object(eve, "execution_tree_enabled", return_value=False), \
                 patch.object(eve, "evaluate_freedom_policy", return_value={"allowed": True}), \
                 patch.object(eve, "record_operational_action_execution"):
                result = eve.execute_autonomy_free_run_action(config, run_id="isolated", action="fly_decoder_probe",
                    reason="Inspect artifact", deadline=time.time()+60)
        self.assertEqual("completed", result["status"])
        self.assertTrue(result["measurement"]["valid"])
        self.assertFalse(result["ok"])
        self.assertFalse(result["execution_verification_ok"])

    def test_decoder_cannot_accept_malformed_or_changed_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / "bc").mkdir(); (root / "bc/eval.json").write_text(json.dumps(artifact()))
            (root / "fly_probe.py").write_text('import json, pathlib\np=pathlib.Path("bc/eval.json");p.write_text("{}")\n'
                'print(json.dumps({"ok":False,"summary":"changed", "artifact_path":str(p.resolve()),'
                '"evidence":{"closed_loop_mean_travel":{"graph_decoder":0.025,"zero":0.038}}}))\n')
            result = eve.run_bounded_fly_probe("fly_decoder_probe", dict(eve.DEFAULT_CONFIG, fly_lab_path=directory), source="isolated")
        self.assertFalse(result["measurement"]["valid"])


class TrainerBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("thought_trainer_test", Path(eve.__file__).parent / "bin/eve_lora_train.py")
        cls.trainer = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.trainer)

    def test_legacy_fallback_exports_rejected_on_both_backends(self):
        row = dict(source="continuous_thought_learning", safe_for_training=True, prompt="x", preferred_response="fallback")
        for method in (self.trainer.format_example, self.trainer.mlx_chat_record):
            with self.assertRaises(ValueError): method(row)

    def test_chat_messages_cannot_bypass_legacy_rejection(self):
        with self.assertRaises(ValueError):
            self.trainer.mlx_chat_record(dict(source="continuous_thought_learning", messages=[dict(role="assistant", content="fallback")]))

    def test_exact_reviewed_export_accepted_and_tampered_context_rejected(self):
        record = episode(); rows, _ = eve.training_examples_from_continuous_thought_learning([record], reviews=[review(record)])
        row = rows[0]
        row["messages"] = [{"role": "assistant", "content": "Unreviewed answer"}]
        self.assertEqual(row["preferred_response"], self.trainer.mlx_chat_record(row)["messages"][-1]["content"])
        self.assertIn("messages", self.trainer.mlx_chat_record(row))
        self.assertIn(row["preferred_response"], self.trainer.format_example(row))
        row["available_context"]["verified_action_evidence"] = []
        with self.assertRaises(ValueError): self.trainer.mlx_chat_record(row)


if __name__ == "__main__":
    unittest.main()
