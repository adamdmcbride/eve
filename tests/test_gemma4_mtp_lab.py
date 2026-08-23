import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "eve_gemma4_mtp_lab.py"


spec = importlib.util.spec_from_file_location("eve_gemma4_mtp_lab", SCRIPT)
lab = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(lab)


class Gemma4MTPLabTests(unittest.TestCase):
    def test_registry_keeps_mtp_as_existing_lane_accelerator(self):
        candidate = lab.CANDIDATES["e4b-local-gguf"]
        self.assertEqual("fast", candidate["lane"])
        self.assertEqual("google/gemma-4-E4B-it", candidate["target_repo"])
        self.assertEqual("google/gemma-4-E4B-it-assistant", candidate["assistant_repo"])
        self.assertIn("lab compatibility smoke", candidate["note"])

    def test_llama_command_uses_matching_target_and_drafter_flags(self):
        command = lab.build_llama_command(
            lab.CANDIDATES["e4b-local-gguf"],
            server_bin=Path("/tmp/llama-server"),
            target_path=Path("/tmp/target.gguf"),
            assistant_path=Path("/tmp/draft.gguf"),
            port=8096,
            alias="eve-gemma4-e4b-mtp-lab",
            ctx_size=4096,
            draft_tokens=8,
        )
        self.assertIn("--model", command)
        self.assertIn("/tmp/target.gguf", command)
        self.assertIn("--model-draft", command)
        self.assertIn("/tmp/draft.gguf", command)
        self.assertIn("--draft", command)
        self.assertIn("8", command)
        self.assertIn("--alias", command)
        self.assertIn("eve-gemma4-e4b-mtp-lab", command)

    def test_llama_command_can_use_gemma4_mtp_head_flags(self):
        command = lab.build_llama_command(
            lab.CANDIDATES["e4b-local-gguf"],
            server_bin=Path("/tmp/llama-server"),
            target_path=Path("/tmp/target.gguf"),
            assistant_path=Path("/tmp/assistant.gguf"),
            port=8097,
            alias="eve-gemma4-e4b-mtp-atomic",
            ctx_size=4096,
            draft_tokens=6,
            llama_flavor="gemma4-mtp",
            draft_block_size=2,
        )
        self.assertIn("--mtp-head", command)
        self.assertIn("/tmp/assistant.gguf", command)
        self.assertIn("--spec-type", command)
        self.assertIn("mtp", command)
        self.assertIn("--draft-block-size", command)
        self.assertIn("2", command)
        self.assertNotIn("--model-draft", command)

    def test_download_refuses_network_without_explicit_allow(self):
        result = lab.download_file(
            "https://example.invalid/model.gguf",
            Path("/tmp/eve-test-missing-gemma4-mtp-model.gguf"),
            123,
            allow_download=False,
        )
        self.assertEqual("missing_download_not_allowed", result["status"])
        self.assertIn("--allow-download", result["next"])


if __name__ == "__main__":
    unittest.main()
