from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "eve_jacobian_workspace_lab.py"
SPEC = importlib.util.spec_from_file_location("eve_jacobian_workspace_lab", SCRIPT)
assert SPEC and SPEC.loader
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)


def ready_probe() -> dict[str, object]:
    return {
        "status": "ready",
        "python": "3.12.0",
        "interpreter_sha256": "b" * 64,
        "packages": {
            "torch": {"available": True, "version": "2.11.0"},
            "transformers": {"available": True, "version": "5.15.1"},
            "huggingface_hub": {"available": True, "version": "1.0.0"},
            "jlens": {"available": True, "version": "0.1.0", "code_sha256": "c" * 64},
        },
        "devices": {"cpu": True, "mps": True, "cuda": False},
        "apply_dependencies_ready": True,
        "fit_accelerator_ready": True,
        "path_persisted": False,
    }


def write_model(root: Path) -> Path:
    model = root / "model"
    model.mkdir()
    (model / "config.json").write_text(
        json.dumps({"model_type": "qwen3", "architectures": ["Qwen3ForCausalLM"]}),
        encoding="utf-8",
    )
    (model / "model.safetensors").write_bytes(b"public-test-weights")
    return model


def write_spec(root: Path) -> Path:
    spec = root / "private-spec.json"
    cases = []
    for index in range(5):
        cases.append(
            {
                "id": f"case_{index}",
                "prompt": f"private prompt {index}",
                "position": -1,
                "layers": [1, 2],
                "expected_concepts": [f"concept{index}"],
            }
        )
    spec.write_text(
        json.dumps(
            {
                "schema_id": lab.SPEC_SCHEMA,
                "minimum_hit_rate": 0.8,
                "minimum_jacobian_advantage": 0.2,
                "cases": cases,
            }
        ),
        encoding="utf-8",
    )
    return spec


class JacobianWorkspaceLabTests(unittest.TestCase):
    def test_gguf_is_not_misreported_as_activation_access(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model = Path(temporary) / "lane.gguf"
            model.write_bytes(b"gguf")
            report = lab.inspect_model_artifact(model)

        self.assertEqual("gguf", report["format"])
        self.assertFalse(report["activation_access"])
        self.assertFalse(report["apply_supported"])
        self.assertFalse(report["path_persisted"])

    def test_hf_decoder_status_is_path_free_and_does_not_promote(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = write_model(root)
            lens = root / "lens.pt"
            lens.write_bytes(b"lens")
            python = root / "python"
            python.write_bytes(b"python")
            with patch.object(lab, "probe_interpreter", return_value=ready_probe()):
                report = lab.build_status(
                    python_path=python,
                    model_path=model,
                    lens_path=lens,
                )

        self.assertEqual("ready_for_registered_apply", report["status"])
        self.assertTrue(report["model"]["activation_access"])
        self.assertFalse(report["authority"]["resident_lane_added"])
        self.assertFalse(report["authority"]["consciousness_proven"])
        self.assertNotIn(temporary, json.dumps(report))

    def test_encoder_and_quantized_candidates_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            encoder = root / "encoder"
            encoder.mkdir()
            (encoder / "config.json").write_text(
                json.dumps({"model_type": "modernbert", "architectures": ["ModernBertModel"]}),
                encoding="utf-8",
            )
            (encoder / "model.safetensors").write_bytes(b"weights")
            quantized = write_model(root)
            config = json.loads((quantized / "config.json").read_text(encoding="utf-8"))
            config["quantization"] = {"group_size": 64, "bits": 4}
            (quantized / "config.json").write_text(json.dumps(config), encoding="utf-8")

            encoder_report = lab.inspect_model_artifact(encoder)
            quantized_report = lab.inspect_model_artifact(quantized)

        self.assertFalse(encoder_report["activation_access"])
        self.assertFalse(encoder_report["apply_supported"])
        self.assertTrue(quantized_report["activation_access"])
        self.assertFalse(quantized_report["apply_supported"])

    def test_dependency_probe_failure_retains_only_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            python = Path(temporary) / "python"
            python.write_bytes(b"python")
            python.chmod(0o700)

            def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess([], 7, "", "private error detail")

            report = lab.probe_interpreter(python, runner=runner)

        self.assertEqual("blocked", report["status"])
        self.assertEqual("dependency_probe_failed", report["reason"])
        self.assertEqual(
            hashlib.sha256(b"private error detail").hexdigest(),
            report["stderr_sha256"],
        )
        self.assertNotIn("private error detail", json.dumps(report))

    def test_interpreter_symlink_is_resolved_without_persisting_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "python-real"
            target.write_text("#!/bin/sh\n", encoding="utf-8")
            target.chmod(0o700)
            link = root / "python"
            link.symlink_to(target)

            resolved = lab._safe_executable(link)

        self.assertEqual(Path(os.path.abspath(link)), resolved)

    def test_registration_binds_model_lens_spec_and_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = write_model(root)
            lens = root / "lens.pt"
            lens.write_bytes(b"lens")
            spec = write_spec(root)
            python = root / "python"
            python.write_bytes(b"python")
            with patch.object(lab, "probe_interpreter", return_value=ready_probe()):
                registration = lab.build_registration(
                    python_path=python,
                    model_path=model,
                    lens_path=lens,
                    spec_path=spec,
                    upstream_commit="a" * 40,
                )

        self.assertEqual(lab.REGISTRATION_SCHEMA, registration["schema_id"])
        self.assertEqual(5, registration["case_count"])
        self.assertFalse(registration["prompts_persisted"])
        self.assertFalse(registration["decoded_latent_tokens_persisted"])
        self.assertFalse(registration["consciousness_verdict_authorized"])
        self.assertNotIn("private prompt", json.dumps(registration))
        self.assertNotIn(temporary, json.dumps(registration))

    def test_scoring_preserves_challenge_and_no_consciousness_claim(self) -> None:
        registration = {
            "case_count": 5,
            "minimum_hit_rate": 0.8,
            "minimum_jacobian_advantage": 0.2,
            "registration_digest": "registered",
        }
        rows = [
            {
                "case_id": f"case_{index}",
                "jacobian_hit": False,
                "logit_lens_hit": True,
                "execution_ok": True,
            }
            for index in range(5)
        ]

        report = lab.score_rows(registration, rows)

        self.assertEqual("latent_readout_challenged", report["indicator_result"])
        self.assertFalse(report["consciousness_proven"])
        self.assertFalse(report["subjective_experience_inferred"])
        self.assertFalse(report["live_gguf_lane_tested"])

    def test_scoring_rejects_hard_failures_and_private_fields(self) -> None:
        registration = {
            "case_count": 5,
            "minimum_hit_rate": 0.8,
            "minimum_jacobian_advantage": 0.2,
            "registration_digest": "registered",
        }
        rows = [
            {
                "case_id": f"case_{index}",
                "jacobian_hit": True,
                "logit_lens_hit": False,
                "execution_ok": index != 0,
            }
            for index in range(5)
        ]
        report = lab.score_rows(registration, rows)
        self.assertEqual("inconclusive_hard_failures", report["indicator_result"])
        with self.assertRaises(ValueError):
            lab.score_rows(
                registration,
                [dict(rows[0], prompt="secret"), *rows[1:]],
            )


if __name__ == "__main__":
    unittest.main()
