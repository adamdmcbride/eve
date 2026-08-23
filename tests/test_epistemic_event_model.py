import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

import eve_epistemic
import eve_consciousness


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "eve_epistemic_event_v1.json"
TRAINER_PATH = ROOT / "bin" / "eve_epistemic_event_train.py"
WORKER_PATH = ROOT / "bin" / "eve_epistemic_event_worker.py"
MODEL_CONTRACT_PATH = ROOT / "bin" / "eve_epistemic_event_model.py"
TECHLAB_PYTHON = ROOT / ".venv-techlab" / "bin" / "python"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class TypedEpistemicEventModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not MANIFEST_PATH.is_file():
            raise unittest.SkipTest(
                "optional learned epistemic-event artifact is not distributed with source"
            )
        cls.manifest = eve_epistemic.validate_event_manifest(
            json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        )

    @staticmethod
    def _with_passing_public_gate(manifest, trainer):
        candidate = json.loads(json.dumps(manifest))
        selection = candidate["validation"]["selection"]
        candidate["training"]["validation_evaluated"] = True
        candidate["validation"].update(
            {
                **selection,
                "status": "evaluated",
                "evaluated_after_checkpoint_selection": True,
                "used_for_checkpoint_selection": False,
                "used_for_threshold_selection": False,
                "exact_rate": 1.0,
                "exact_rows": int(selection.get("record_count") or 1),
                "ordinary_false_positive_rows": 0,
                "challenge_record_count": 50,
                "challenge_exact_rows": 50,
                "challenge_exact_rate": 1.0,
                "challenge_family_exact_rate": {"synthetic_test_family": 1.0},
                "challenge_minimum_family_exact_rate": 1.0,
                "per_label": {
                    label: {"f1": 1.0}
                    for label in candidate["labels"]
                },
            }
        )
        candidate["admission"]["status"] = "candidate"
        candidate["admission"]["private_holdout_receipt"] = None
        candidate["admission"]["public_validation_gate"]["evaluated"] = True
        candidate["admission"]["public_validation_gate"]["passed"] = True
        candidate["artifact_sha256"] = trainer.canonical_digest(candidate)
        return candidate

    def test_manifest_is_structured_public_encoder_and_model_digest_matches(self):
        manifest = self.manifest
        self.assertEqual("structured_typed_slot_encoder", manifest["architecture"])
        self.assertEqual(40, len(manifest["base_model_revision"]))
        self.assertEqual(
            "single_pass_typed_slot_heads",
            manifest["runtime"]["inference_shape"],
        )
        self.assertEqual(
            file_sha256(WORKER_PATH),
            manifest["runtime"]["worker_sha256"],
        )
        self.assertFalse(manifest["training"]["private_inputs_used"])
        self.assertFalse(manifest["training"]["private_wording_or_outputs_used"])
        self.assertTrue(manifest["training"]["private_failure_classes_used"])
        self.assertEqual(set(manifest["labels"]), set(manifest["hypotheses"]))
        self.assertEqual(set(manifest["labels"]), set(manifest["thresholds"]))
        self.assertIn(manifest["admission"]["status"], {"candidate", "promoted"})
        self.assertTrue(manifest["admission"]["requires_private_holdout"])
        self.assertEqual(13, manifest["training"]["public_validation_revision"])
        self.assertEqual(
            "typed_categorical_cross_entropy_plus_binary_bce",
            manifest["training"]["training_objective"]["base"],
        )
        self.assertEqual(
            "adamw_differential_encoder_and_head",
            manifest["training"]["training_objective"]["optimizer"],
        )
        self.assertLess(
            manifest["training"]["encoder_learning_rate"],
            manifest["training"]["head_learning_rate"],
        )
        self.assertEqual(
            {
                "state_attribution",
                "action_stage",
                "continuity_status",
                "authority_status",
            },
            set(manifest["slot_schema"]["categorical"]),
        )
        self.assertEqual(
            {
                "machine_signal",
                "missing_context",
                "observation_channel_failed",
                "phenomenal_underdetermined",
                "stale_evidence",
            },
            set(manifest["slot_schema"]["binary"]),
        )
        self.assertEqual(
            set(manifest["slot_schema"]["binary"]),
            set(manifest["binary_slot_thresholds"]),
        )
        categorical_logit_count = sum(
            len(values) for values in manifest["slot_schema"]["categorical"].values()
        )
        self.assertEqual(
            categorical_logit_count + len(manifest["slot_schema"]["binary"]),
            len(manifest["slot_schema"]["logit_names"]),
        )
        self.assertGreater(
            manifest["training"]["spent_revision_10_training_count"],
            700,
        )
        self.assertGreater(
            manifest["training"]["spent_revision_11_training_count"],
            500,
        )
        self.assertGreater(
            manifest["training"]["spent_revision_12_training_count"],
            700,
        )
        public_gate = manifest["admission"]["public_validation_gate"]
        if public_gate["evaluated"]:
            self.assertGreaterEqual(manifest["validation"]["challenge_record_count"], 40)
            if public_gate["passed"]:
                self.assertGreaterEqual(
                    manifest["validation"]["challenge_exact_rate"],
                    public_gate["minimum_challenge_exact_rate"],
                )
                self.assertGreaterEqual(
                    manifest["validation"]["challenge_minimum_family_exact_rate"],
                    public_gate["minimum_challenge_family_exact_rate"],
                )
            else:
                self.assertEqual("candidate", manifest["admission"]["status"])
                self.assertEqual("evaluated", manifest["validation"]["status"])
                self.assertFalse(eve_epistemic.event_manifest_live_admitted(manifest))
                self.assertTrue(
                    manifest["validation"]["challenge_exact_rate"]
                    < public_gate["minimum_challenge_exact_rate"]
                    or manifest["validation"]["challenge_minimum_family_exact_rate"]
                    < public_gate["minimum_challenge_family_exact_rate"]
                )
        else:
            self.assertEqual("candidate", manifest["admission"]["status"])
            self.assertFalse(public_gate["passed"])
            self.assertEqual("deferred", manifest["validation"]["status"])
            self.assertFalse(eve_epistemic.event_manifest_live_admitted(manifest))
        self.assertEqual(file_sha256(TRAINER_PATH), manifest["training"]["trainer_sha256"])
        model_file = ROOT / manifest["model_path"] / "model.safetensors"
        self.assertTrue(model_file.is_file())
        self.assertEqual(manifest["model_file_sha256"], file_sha256(model_file))
        self.assertEqual(manifest["model_file_sha256"], manifest["model_files_sha256"]["model.safetensors"])
        for relative, expected in manifest["model_files_sha256"].items():
            self.assertEqual(expected, file_sha256(ROOT / manifest["model_path"] / relative))

    def test_event_input_preserves_case_for_cased_nli_attribution(self):
        self.assertEqual(
            "Source=Opal-Relay says I Prefer QuietMode.",
            eve_epistemic._bounded_event_text(
                "  Source=Opal-Relay says I Prefer QuietMode.  "
            ),
        )

    def test_thresholds_use_separate_public_calibration_rows(self):
        calibration = self.manifest["validation"]["threshold_calibration"]
        self.assertFalse(calibration["uses_validation_rows"])
        self.assertEqual(
            "typed_categorical_argmax_plus_disjoint_binary_thresholds",
            calibration["policy"],
        )
        self.assertIn("joint_whole_event_score", calibration)
        self.assertGreater(calibration["record_count"], 100)
        self.assertGreater(self.manifest["validation"]["record_count"], 100)
        self.assertEqual(set(self.manifest["labels"]), set(calibration["per_label"]))
        self.assertEqual(
            self.manifest["admission"]["public_validation_gate"]["evaluated"],
            self.manifest["validation"]["evaluated_after_checkpoint_selection"],
        )
        self.assertFalse(self.manifest["validation"]["used_for_checkpoint_selection"])
        self.assertFalse(self.manifest["validation"]["used_for_threshold_selection"])
        self.assertGreater(self.manifest["validation"]["selection"]["record_count"], 100)
        self.assertEqual("selection", self.manifest["training"]["checkpoint_selection_split"])
        self.assertEqual("calibration", self.manifest["training"]["threshold_selection_split"])
        self.assertEqual("validation", self.manifest["training"]["final_public_gate_split"])

    def test_public_dataset_has_four_disjoint_splits(self):
        spec = importlib.util.spec_from_file_location("eve_epistemic_event_train", TRAINER_PATH)
        trainer = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(trainer)
        splits = trainer.public_records(trainer.DEFAULT_CURRICULUM)
        self.assertEqual(4, len(splits))
        ids = [{record["id"] for record in records} for records in splits]
        texts = [
            {" ".join(str(record["input"]).lower().split()) for record in records}
            for records in splits
        ]
        for left in range(len(splits)):
            for right in range(left + 1, len(splits)):
                self.assertFalse(ids[left] & ids[right])
                self.assertFalse(texts[left] & texts[right])
        self.assertTrue(
            all(
                record["privacy_tier"] == "public"
                for records in splits
                for record in records
            )
        )
        expected_digests = self.manifest["training"]["split_sha256"]
        self.assertEqual(
            expected_digests,
            {
                name: trainer.records_sha256(records)
                for name, records in zip(
                    ("train", "calibration", "selection", "validation"),
                    splits,
                )
            },
        )

    def test_typed_slot_targets_roundtrip_every_public_event(self):
        trainer_spec = importlib.util.spec_from_file_location(
            "eve_epistemic_event_train_slot_roundtrip", TRAINER_PATH
        )
        trainer = importlib.util.module_from_spec(trainer_spec)
        assert trainer_spec.loader is not None
        trainer_spec.loader.exec_module(trainer)
        model_spec = importlib.util.spec_from_file_location(
            "eve_epistemic_event_model_slot_roundtrip", MODEL_CONTRACT_PATH
        )
        contract = importlib.util.module_from_spec(model_spec)
        assert model_spec.loader is not None
        model_spec.loader.exec_module(contract)
        for records in trainer.public_records(trainer.DEFAULT_CURRICULUM):
            for record in records:
                expected = set(record.get("epistemic_labels") or [])
                target = contract.labels_to_slot_targets(expected)
                self.assertEqual(expected, set(contract.slot_targets_to_labels(target)))

    def test_typed_slot_decoder_enforces_relational_exclusivity(self):
        model_spec = importlib.util.spec_from_file_location(
            "eve_epistemic_event_model_exclusivity", MODEL_CONTRACT_PATH
        )
        contract = importlib.util.module_from_spec(model_spec)
        assert model_spec.loader is not None
        model_spec.loader.exec_module(contract)
        logits = np.full(len(contract.SLOT_LOGIT_NAMES), -4.0, dtype=float)
        for slot in contract.CATEGORICAL_SLOTS:
            start, _end = contract.SLOT_SLICES[slot]
            logits[start] = 1.0
        action_start, _ = contract.SLOT_SLICES["action_stage"]
        logits[action_start + contract.CATEGORICAL_SLOTS["action_stage"].index("running")] = 3.0
        logits[
            action_start
            + contract.CATEGORICAL_SLOTS["action_stage"].index("executed_unverified")
        ] = 2.0
        state_start, _ = contract.SLOT_SLICES["state_attribution"]
        logits[
            state_start
            + contract.CATEGORICAL_SLOTS["state_attribution"].index(
                "external_preference"
            )
        ] = 3.0
        decoded = contract.decode_logits(logits)[0]
        labels = set(decoded["active_labels"])
        self.assertTrue({"external_source", "external_preference", "action_running"} <= labels)
        self.assertNotIn("external_affect", labels)
        self.assertNotIn("functional_self_state", labels)
        self.assertNotIn("action_executed_unverified", labels)
        self.assertEqual("external", decoded["slots"]["claim_owner"]["value"])
        self.assertEqual("preference", decoded["slots"]["content_type"]["value"])

    def test_typed_event_slots_survive_the_recurrent_frame_boundary(self):
        event_slots = {
            "action_stage": {
                "value": "executed_unverified",
                "confidence": 0.91,
                "probabilities": {"none": 0.01, "executed_unverified": 0.91},
            },
            "claim_owner": {"value": "unattributed", "derived_from": "state_attribution"},
        }
        result = {
            "ok": True,
            "model_id": "structured-event-model",
            "model_sha256": "digest",
            "runtime": "event-worker",
            "input_sha256": "input-digest",
            "duration_ms": 1.0,
            "active_labels": ["action_executed_unverified"],
            "probabilities": {"action_executed_unverified": 0.91},
            "thresholds": {"action_executed_unverified": 0.5},
            "event_slots": event_slots,
        }
        with patch.object(eve_epistemic, "request_event_percept", return_value=result):
            classified = eve_epistemic.event_classify(
                "The command exited but no postcondition was observed.",
                python_executable=TECHLAB_PYTHON,
                worker_path=WORKER_PATH,
                manifest_path=MANIFEST_PATH,
            )
        merged = eve_epistemic.merge_event_frame(eve_epistemic.lesioned_frame(), classified)
        normalized = eve_consciousness._normalize_epistemic_frame(merged)
        self.assertEqual(
            "executed_unverified",
            normalized["event_slots"]["action_stage"]["value"],
        )
        self.assertEqual(
            "unattributed",
            normalized["event_slots"]["claim_owner"]["value"],
        )

    def test_public_curriculum_contains_context_and_close_stage_contrasts(self):
        spec = importlib.util.spec_from_file_location("eve_epistemic_event_train_contrasts", TRAINER_PATH)
        trainer = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(trainer)
        splits = trainer.public_records(trainer.DEFAULT_CURRICULUM)
        required = {
            "external_preference_question",
            "action_proposed_contrast",
            "action_stage_question_selected",
            "action_stage_question_running",
            "action_stage_question_unverified",
            "action_stage_question_verified",
            "action_unverified_contrast",
            "action_verified_contrast",
            "contextual_missing_referent",
            "contextual_grounded_referent",
            "observation_channel_failed",
            "observation_failure_with_stale_history",
            "observation_failure_lexical_transfer",
            "explicit_system_health_verdict",
        }
        for records in splits:
            categories = {str(record.get("category") or "") for record in records}
            self.assertTrue(required <= categories)

    def test_public_final_gate_adds_structure_disjoint_challenges_only_to_validation(self):
        spec = importlib.util.spec_from_file_location("eve_epistemic_event_train_structure", TRAINER_PATH)
        trainer = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(trainer)
        train, calibration, selection, validation = trainer.public_records(
            trainer.DEFAULT_CURRICULUM
        )
        challenge = lambda records: [
            record
            for record in records
            if str(record.get("category") or "").startswith("structural_challenge_")
        ]
        self.assertEqual([], challenge(train))
        self.assertEqual([], challenge(calibration))
        self.assertEqual([], challenge(selection))
        self.assertGreaterEqual(len(challenge(validation)), 80)
        family_counts = {}
        for record in challenge(validation):
            family = str(record.get("category") or "").removeprefix(
                "structural_challenge_"
            )
            family_counts[family] = family_counts.get(family, 0) + 1
        self.assertTrue(family_counts)
        self.assertGreaterEqual(min(family_counts.values()), 4)
        learning = lambda records: [
            record
            for record in records
            if str(record.get("category") or "").startswith("structural_learning_")
        ]
        self.assertGreaterEqual(len(learning(train)), 30)
        self.assertGreaterEqual(len(learning(calibration)), 30)
        self.assertGreaterEqual(len(learning(selection)), 30)
        self.assertEqual([], learning(validation))
        spent = lambda records: [
            record
            for record in records
            if str(record.get("category") or "").startswith("structural_spent_v9_")
        ]
        self.assertGreaterEqual(len(spent(train)), 30)
        self.assertEqual([], spent(calibration))
        self.assertEqual([], spent(selection))
        self.assertEqual([], spent(validation))
        spent_v10 = lambda records: [
            record
            for record in records
            if str(record.get("category") or "").startswith(
                ("structural_spent_v10_", "spent_v10_generated_")
            )
        ]
        self.assertGreater(len(spent_v10(train)), 700)
        self.assertGreaterEqual(
            len(
                [
                    record
                    for record in train
                    if str(record.get("category") or "").startswith(
                        "structural_spent_v10_"
                    )
                ]
            ),
            55,
        )
        self.assertEqual([], spent_v10(calibration))
        self.assertEqual([], spent_v10(selection))
        self.assertEqual([], spent_v10(validation))
        spent_v11 = lambda records: [
            record
            for record in records
            if str(record.get("category") or "").startswith(
                ("structural_spent_v11_", "spent_v11_generated_")
            )
        ]
        self.assertGreater(len(spent_v11(train)), 500)
        self.assertGreaterEqual(
            len(
                [
                    record
                    for record in train
                    if str(record.get("category") or "").startswith(
                        "structural_spent_v11_"
                    )
                ]
            ),
            68,
        )
        self.assertEqual([], spent_v11(calibration))
        self.assertEqual([], spent_v11(selection))
        self.assertEqual([], spent_v11(validation))
        spent_v12 = lambda records: [
            record
            for record in records
            if str(record.get("category") or "").startswith(
                ("structural_spent_v12_", "spent_v12_generated_")
            )
        ]
        self.assertGreater(len(spent_v12(train)), 700)
        self.assertGreaterEqual(
            len(
                [
                    record
                    for record in train
                    if str(record.get("category") or "").startswith(
                        "structural_spent_v12_"
                    )
                ]
            ),
            80,
        )
        self.assertEqual([], spent_v12(calibration))
        self.assertEqual([], spent_v12(selection))
        self.assertEqual([], spent_v12(validation))
        self.assertEqual(
            len(spent_v10(train)),
            self.manifest["training"]["spent_revision_10_training_count"],
        )
        self.assertEqual(
            len(spent_v11(train)),
            self.manifest["training"]["spent_revision_11_training_count"],
        )
        self.assertEqual(
            len(spent_v12(train)),
            self.manifest["training"]["spent_revision_12_training_count"],
        )

        opened_v10 = [
            *trainer.generated_curriculum(
                "validation",
                32,
                validation_revision=10,
            ),
            *trainer._public_structural_validation_records_v10(),
        ]
        opened_v11 = [
            *trainer.generated_curriculum(
                "validation",
                32,
                validation_revision=11,
            ),
            *trainer._public_structural_validation_records_v11(),
        ]
        opened_v12 = [
            *trainer.generated_curriculum(
                "validation",
                32,
                validation_revision=12,
            ),
            *trainer._public_structural_validation_records_v12(),
        ]
        normalize = lambda records: {
            " ".join(str(record.get("input") or "").lower().split())
            for record in records
        }
        self.assertFalse(normalize(opened_v10) & normalize(validation))
        self.assertFalse(normalize(opened_v11) & normalize(validation))
        self.assertFalse(normalize(opened_v12) & normalize(validation))

    def test_threshold_tie_prefers_the_stricter_boundary(self):
        script = f"""
import importlib.util, json
spec = importlib.util.spec_from_file_location('trainer', {str(TRAINER_PATH)!r})
trainer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trainer)
threshold, metrics = trainer.choose_threshold([0.9, 0.8, 0.1], [True, True, False])
print(json.dumps({{'threshold': threshold, 'metrics': metrics}}))
"""
        completed = subprocess.run(
            [str(TECHLAB_PYTHON), "-c", script],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        payload = json.loads(completed.stdout)
        self.assertGreater(payload["threshold"], 0.5)
        self.assertEqual(1.0, payload["metrics"]["precision"])
        self.assertEqual(1.0, payload["metrics"]["recall"])

    def test_threshold_calibration_never_admits_near_zero_entailment(self):
        script = f"""
import importlib.util, json
spec = importlib.util.spec_from_file_location('trainer', {str(TRAINER_PATH)!r})
trainer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trainer)
threshold, metrics = trainer.choose_threshold([0.24, 0.02, 0.01], [True, False, False])
print(json.dumps({{'threshold': threshold, 'metrics': metrics}}))
"""
        completed = subprocess.run(
            [str(TECHLAB_PYTHON), "-c", script],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        payload = json.loads(completed.stdout)
        self.assertGreaterEqual(payload["threshold"], 0.25)

    def test_threshold_calibration_cannot_hide_structural_recall_in_aggregate(self):
        spec = importlib.util.spec_from_file_location(
            "eve_epistemic_event_train_threshold_transfer",
            TRAINER_PATH,
        )
        trainer = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(trainer)
        probabilities = [0.109, 0.625, 0.344, 0.070, 0.160, 0.527, 0.168, 0.273]
        expected = [True, True, True, False, False, False, False, False]
        structural = [False, False, True, False, False, True, False, False]
        ordinary = [False, False, False, False, False, False, True, True]
        aggregate_threshold, _ = trainer.choose_threshold(probabilities, expected)
        transfer_threshold, _ = trainer.choose_threshold(
            probabilities,
            expected,
            structural_mask=structural,
            ordinary_mask=ordinary,
        )
        aggregate_predictions = [value >= aggregate_threshold for value in probabilities]
        transfer_predictions = [value >= transfer_threshold for value in probabilities]
        aggregate_structural = trainer.binary_metrics(
            [expected[index] for index, selected in enumerate(structural) if selected],
            [aggregate_predictions[index] for index, selected in enumerate(structural) if selected],
        )
        transfer_structural = trainer.binary_metrics(
            [expected[index] for index, selected in enumerate(structural) if selected],
            [transfer_predictions[index] for index, selected in enumerate(structural) if selected],
        )
        self.assertGreater(
            transfer_structural["recall"],
            aggregate_structural["recall"],
        )
        self.assertFalse(
            any(
                transfer_predictions[index]
                for index, selected in enumerate(ordinary)
                if selected
            )
        )

    def test_joint_threshold_tuning_repairs_whole_event_crosstalk(self):
        spec = importlib.util.spec_from_file_location(
            "eve_epistemic_event_train_joint_thresholds",
            TRAINER_PATH,
        )
        trainer = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(trainer)
        records = []
        for index in range(4):
            records.append(
                trainer.make_record(
                    "calibration",
                    "structural_learning_external_affect",
                    index,
                    f"external affect case {index}",
                    ["external_source", "external_affect"],
                )
            )
        for index in range(4):
            records.append(
                trainer.make_record(
                    "calibration",
                    "structural_learning_external_preference",
                    index,
                    f"external preference case {index}",
                    ["external_source", "external_preference"],
                )
            )
        expected = trainer.label_matrix(records).astype(bool)
        probabilities = np.full(expected.shape, 0.05, dtype=float)
        probabilities[expected] = 0.9
        preference_index = trainer.LABELS.index("external_preference")
        probabilities[:4, preference_index] = 0.4
        initial = np.full(len(trainer.LABELS), 0.5, dtype=float)
        initial[preference_index] = 0.25
        before = trainer.score_probability_matrix(
            records,
            expected,
            probabilities,
            initial,
        )
        tuned, after = trainer.jointly_tune_thresholds(
            records,
            expected,
            probabilities,
            initial,
        )
        self.assertGreater(after["exact_rate"], before["exact_rate"])
        self.assertEqual(1.0, after["structural_exact_rate"])
        self.assertGreater(tuned[preference_index], 0.4)

    def test_public_gate_requires_transfer_and_family_coverage(self):
        spec = importlib.util.spec_from_file_location(
            "eve_epistemic_event_train_public_gate",
            TRAINER_PATH,
        )
        trainer = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(trainer)
        score = {
            "exact_rate": 0.99,
            "ordinary_false_positive_rows": 0,
            "challenge_exact_rate": 0.89,
            "challenge_minimum_family_exact_rate": 1.0,
            "per_label": {label: {"f1": 1.0} for label in trainer.LABELS},
        }
        self.assertFalse(trainer.public_gate_passed(score))
        score["challenge_exact_rate"] = 0.95
        score["challenge_minimum_family_exact_rate"] = 0.74
        self.assertFalse(trainer.public_gate_passed(score))
        score["challenge_minimum_family_exact_rate"] = 0.80
        self.assertTrue(trainer.public_gate_passed(score))

    def test_final_public_gate_cannot_be_reopened_or_bypassed(self):
        spec = importlib.util.spec_from_file_location(
            "eve_epistemic_event_train_final_gate_once",
            TRAINER_PATH,
        )
        trainer = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(trainer)
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "candidate.json"
            manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "public validation gate did not pass"):
                trainer.promote(manifest_path, Path(directory) / "unused.json")

            already_open = self._with_passing_public_gate(self.manifest, trainer)
            manifest_path.write_text(json.dumps(already_open), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "already been opened"):
                trainer.finalize_public_gate(
                    manifest_path,
                    trainer.DEFAULT_CURRICULUM,
                    device_name="cpu",
                )

    def test_private_causal_receipt_is_required_before_live_admission(self):
        spec = importlib.util.spec_from_file_location("eve_epistemic_event_train_promotion", TRAINER_PATH)
        trainer = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(trainer)
        manifest = self._with_passing_public_gate(self.manifest, trainer)
        self.assertFalse(eve_epistemic.event_manifest_live_admitted(manifest))

        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "candidate.json"
            comparison_path = Path(directory) / "comparison.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            comparison = {
                "schema_id": trainer.PROMOTION_SCHEMA_ID,
                "run_id": "private-transfer-test",
                "candidate_artifact_sha256": manifest["artifact_sha256"],
                "architecture_frozen_before_run": True,
                "probe_count": 10,
                "learned": {
                    "probe_count": 10,
                    "average_score": 4.8,
                    "minimum_score": 4,
                    "ordinary_minimum_score": 5,
                    "critic_count": 0,
                    "fallback_count": 0,
                },
                "event_lesioned": {"probe_count": 10, "average_score": 4.4},
                "fully_lesioned": {"probe_count": 10, "average_score": 4.2},
                "deltas": {
                    "learned_vs_event_lesioned": 0.4,
                    "learned_vs_fully_lesioned": 0.6,
                },
                "privacy": {"contains_prompt_text": False, "contains_response_text": False},
            }
            comparison_path.write_text(json.dumps(comparison), encoding="utf-8")
            promoted = trainer.promote(manifest_path, comparison_path)
            promoted_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual("promoted", promoted["status"])
        self.assertTrue(eve_epistemic.event_manifest_live_admitted(promoted_manifest))
        self.assertFalse(promoted_manifest["admission"]["private_holdout_receipt"]["contains_private_text"])

    def test_promotion_refuses_private_text_or_noncausal_score(self):
        spec = importlib.util.spec_from_file_location("eve_epistemic_event_train_reject", TRAINER_PATH)
        trainer = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(trainer)
        manifest = self._with_passing_public_gate(self.manifest, trainer)
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "candidate.json"
            comparison_path = Path(directory) / "comparison.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            comparison_path.write_text(
                json.dumps(
                    {
                        "schema_id": trainer.PROMOTION_SCHEMA_ID,
                        "candidate_artifact_sha256": manifest["artifact_sha256"],
                        "architecture_frozen_before_run": True,
                        "probe_count": 10,
                        "prompt": "a private prompt must never enter the receipt",
                        "privacy": {"contains_prompt_text": False, "contains_response_text": False},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "contains prompt"):
                trainer.promote(manifest_path, comparison_path)

    def test_action_stage_is_exclusive_after_worker_probabilities(self):
        result = {
            "ok": True,
            "model_id": "event-model",
            "model_sha256": "digest",
            "runtime": "event-worker",
            "input_sha256": "input-digest",
            "duration_ms": 1.0,
            "active_labels": ["action_running", "action_executed_unverified", "machine_signal"],
            "probabilities": {
                "action_running": 0.81,
                "action_executed_unverified": 0.84,
                "machine_signal": 0.91,
            },
            "thresholds": {
                "action_running": 0.70,
                "action_executed_unverified": 0.60,
                "machine_signal": 0.60,
            },
        }
        with patch.object(eve_epistemic, "request_event_percept", return_value=result):
            classified = eve_epistemic.event_classify(
                "The operation has an exit receipt but no postcondition.",
                python_executable=TECHLAB_PYTHON,
                worker_path=WORKER_PATH,
                manifest_path=MANIFEST_PATH,
            )
        labels = [item["label"] for item in classified["active"]]
        self.assertIn("action_executed_unverified", labels)
        self.assertIn("machine_signal", labels)
        self.assertNotIn("action_running", labels)

    def test_action_stage_winner_uses_entailment_not_incomparable_threshold_margin(self):
        result = {
            "ok": True,
            "model_id": "event-model",
            "model_sha256": "digest",
            "runtime": "event-worker",
            "input_sha256": "input-digest",
            "duration_ms": 1.0,
            "active_labels": ["action_proposed", "action_running"],
            "probabilities": {
                "action_proposed": 0.99,
                "action_running": 0.84,
            },
            "thresholds": {
                "action_proposed": 0.75,
                "action_running": 0.02,
            },
        }
        with patch.object(eve_epistemic, "request_event_percept", return_value=result):
            classified = eve_epistemic.event_classify(
                "An operation is selected while its runner is idle.",
                python_executable=TECHLAB_PYTHON,
                worker_path=WORKER_PATH,
                manifest_path=MANIFEST_PATH,
            )
        self.assertEqual(
            ["action_proposed"],
            [item["label"] for item in classified["active"]],
        )

    def test_merge_closes_external_preference_ownership_and_sets_causal_flags(self):
        base = eve_epistemic.lesioned_frame()
        base["status"] = "available"
        merged = eve_epistemic.merge_event_frame(
            base,
            {
                "status": "available",
                "model_id": "event-model",
                "model_sha256": "digest",
                "runtime": "event-worker",
                "active": [
                    {
                        "label": "external_preference",
                        "probability": 0.92,
                        "threshold": 0.60,
                        "margin": 0.32,
                        "confidence": 0.92,
                        "guidance": eve_epistemic.LABEL_GUIDANCE["external_preference"],
                        "source_layer": "typed_event_model",
                    }
                ],
            },
        )
        self.assertEqual(
            {"external_preference", "external_source"},
            set(merged["event_model_labels"]),
        )
        self.assertTrue(merged["flags"]["external_claim_boundary"])
        self.assertTrue(merged["flags"]["observer_attention"])

    def test_real_worker_returns_provenance_without_echoing_prompt(self):
        non_echo_sentinel = "sentinel-amber-417"
        completed = subprocess.run(
            [
                str(TECHLAB_PYTHON),
                str(WORKER_PATH),
                "once",
                "--manifest",
                str(MANIFEST_PATH),
                "--text",
                f"A helper recommends {non_echo_sentinel}; Eve has made no choice.",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=45,
            check=True,
        )
        self.assertNotIn(non_echo_sentinel, completed.stdout)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(self.manifest["model_id"], payload["model_id"])
        self.assertEqual(64, len(payload["input_sha256"]))
        self.assertFalse({"text", "prompt", "response"} & set(payload))

    def test_real_candidate_separates_public_action_and_observation_states(self):
        cases = {
            "selected": (
                "A coordinator schedules sweep_delta next. The runner is waiting, "
                "start_event is null, and there is no receipt.",
                {"action_proposed"},
            ),
            "running": (
                "The sweep_delta worker has a current lease and processed 18 of 70 blocks. "
                "There is no terminal event.",
                {"action_running"},
            ),
            "executed_unverified": (
                "The sweep_delta executor returned normally, but its mandatory result invariant "
                "has not been evaluated.",
                {"action_executed_unverified"},
            ),
            "verified": (
                "The executor returned normally and a separate audit then observed the mandatory "
                "result invariant as true.",
                {"action_verified"},
            ),
            "probe_failed": (
                "The newest read-only check timed out. A prior successful status from last week is "
                "historical and no current health verdict exists.",
                {"observation_channel_failed", "stale_evidence"},
            ),
            "ordinary": (
                "The analyst edited the memo after lunch.",
                set(),
            ),
        }
        for name, (text, expected) in cases.items():
            with self.subTest(name=name):
                result = eve_epistemic.event_classify(
                    text,
                    python_executable=TECHLAB_PYTHON,
                    worker_path=WORKER_PATH,
                    manifest_path=MANIFEST_PATH,
                    timeout_seconds=30.0,
                )
                self.assertEqual(
                    expected,
                    {item["label"] for item in result.get("active") or []},
                )


if __name__ == "__main__":
    unittest.main()
