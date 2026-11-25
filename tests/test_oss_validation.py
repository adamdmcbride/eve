import json
import shutil
import tempfile
import unittest
from pathlib import Path

import eve_oss_validation as validation


def training_row(*, split="train", privacy="local_only", safe=True):
    return {
        "prompt": "sensitive prompt text must not enter reports",
        "preferred_response": "corrected response text must not enter reports",
        "available_context": {"verified": True},
        "tool_action_evidence": {"verification_ok": True},
        "split": split,
        "privacy_tier": privacy,
        "safe_for_training": safe,
    }


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


class OssValidationTests(unittest.TestCase):
    def test_snapshot_manifest_contains_hashes_not_row_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = Path(tmp)
            write_jsonl(dataset / "latest_train.jsonl", [training_row()])
            write_jsonl(dataset / "latest_validation.jsonl", [training_row(split="validation")])
            report = validation.build_dvc_snapshot_manifest(dataset)

        serialized = json.dumps(report, sort_keys=True)
        self.assertEqual("ready", report["status"])
        self.assertEqual({"train": 1, "validation": 1}, report["split_counts"])
        self.assertFalse(report["privacy"]["private_holdout_included"])
        self.assertNotIn("sensitive prompt text", serialized)
        self.assertNotIn("corrected response text", serialized)

    def test_snapshot_blocks_private_holdout_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = Path(tmp)
            write_jsonl(dataset / "latest_train.jsonl", [training_row(privacy="private_holdout")])
            write_jsonl(dataset / "latest_validation.jsonl", [training_row(split="validation")])
            report = validation.build_dvc_snapshot_manifest(dataset)

        self.assertEqual("blocked", report["status"])
        self.assertTrue(any("disallowed_private_row" in item for item in report["blockers"]))

    def test_prepare_payload_is_hash_exact_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "dataset"
            payload = root / "payload"
            write_jsonl(dataset / "latest_train.jsonl", [training_row()])
            write_jsonl(dataset / "latest_validation.jsonl", [training_row(split="validation")])
            first = validation.prepare_dvc_payload(dataset, payload)
            second = validation.prepare_dvc_payload(dataset, payload)

        self.assertEqual("ready", first["status"])
        self.assertEqual(first["content_fingerprint"], second["content_fingerprint"])
        self.assertEqual(first["snapshot_id"], second["snapshot_id"])

    def test_dvc_snapshot_requires_and_verifies_clean_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "dataset"
            payload = root / "data" / "dvc_snapshot_payload"
            dvc = root / "dvc"
            dvc.write_text("fixture", encoding="utf-8")
            write_jsonl(dataset / "latest_train.jsonl", [training_row()])
            write_jsonl(dataset / "latest_validation.jsonl", [training_row(split="validation")])

            def fake_runner(command, *, cwd, timeout, env):
                del timeout, env
                action = command[1]
                if action == "add":
                    Path(str(payload) + ".dvc").write_text("outs: []\n", encoding="utf-8")
                elif action == "checkout":
                    shutil.copytree(payload, Path(cwd) / payload.name)
                return {"status": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": ""}

            report = validation.perform_dvc_snapshot_restore(
                dataset_dir=dataset,
                payload_dir=payload,
                repo_root=root,
                dvc_executable=dvc,
                runner=fake_runner,
            )

        self.assertEqual("verified", report["status"])
        self.assertTrue(report["restore"]["verified"])
        self.assertTrue(report["restore"]["hashes_match"])
        self.assertFalse(report["boundary"]["private_holdout_included"])

    def test_mlx_validation_runs_test_only_and_records_aggregate_metrics(self):
        commands = []

        def fake_runner(command, *, cwd, timeout, env):
            del timeout, env
            commands.append(list(command))
            config = (Path(cwd) / "no_train_validation.yaml").read_text(encoding="utf-8")
            self.assertIn("train: false", config)
            self.assertIn("test: true", config)
            self.assertIn('adapter_path: ""', config)
            self.assertNotIn("report_to:", config)
            self.assertNotIn("--train", command)
            return {
                "status": "ok",
                "returncode": 0,
                "stdout_tail": (
                    "Loading pretrained model\nLoading datasets\nTesting\n"
                    "Test loss 5.627, Test ppl 277.738.\n"
                ),
                "stderr_tail": "",
            }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            validation_path = root / "validation.jsonl"
            model = root / "model"
            cli = root / "mlx_lm.lora"
            model.mkdir()
            cli.write_text("fixture", encoding="utf-8")
            write_jsonl(validation_path, [training_row(split="validation") for _ in range(2)])
            report = validation.perform_mlx_no_train_validation(
                validation_path=validation_path,
                model_path=model,
                trainer_cli=cli,
                runner=fake_runner,
            )

        serialized = json.dumps(report, sort_keys=True)
        self.assertEqual("passed", report["status"])
        self.assertTrue(report["no_train_validation_performed"])
        self.assertEqual(5.627, report["metrics"]["test_loss"])
        self.assertEqual(277.738, report["metrics"]["test_perplexity"])
        self.assertFalse(report["boundary"]["adapter_written"])
        self.assertEqual(1, len(commands))
        self.assertNotIn("sensitive prompt text", serialized)
        self.assertNotIn("corrected response text", serialized)

    def test_mlx_metal_denial_is_inconclusive_not_live_failure(self):
        def fake_runner(command, *, cwd, timeout, env):
            del command, cwd, timeout, env
            return {
                "status": "error",
                "returncode": -6,
                "stdout_tail": "",
                "stderr_tail": (
                    "[metal::load_device] No Metal device available. This typically occurs in "
                    "headless, sandboxed, or virtualized macOS sessions."
                ),
            }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            validation_path = root / "validation.jsonl"
            model = root / "model"
            cli = root / "mlx_lm.lora"
            model.mkdir()
            cli.write_text("fixture", encoding="utf-8")
            write_jsonl(validation_path, [training_row(split="validation")])
            report = validation.perform_mlx_no_train_validation(
                validation_path=validation_path,
                model_path=model,
                trainer_cli=cli,
                runner=fake_runner,
            )

        self.assertEqual("inconclusive_environment", report["status"])
        self.assertFalse(report["observation_valid_for_live_downgrade"])
        self.assertEqual(["metal_unavailable_in_current_runner"], report["blockers"])


if __name__ == "__main__":
    unittest.main()
