import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE_CONFIG = json.loads((ROOT / "public_release.json").read_text(encoding="utf-8"))
OWNER_IDENTIFIERS = tuple(RELEASE_CONFIG["owner_identifiers"])
PERSONAL_MAC_HOME = re.compile(r"/Users/(?!example(?:/|$)|test(?:/|$)|user(?:/|$)|runner(?:/|$))[^/]+/")


class PublicPortabilityTests(unittest.TestCase):
    def test_public_gitignore_defaults_private_runtime_material_to_local_only(self):
        ignored = {
            line.strip()
            for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        self.assertTrue(
            {
                ".env",
                ".eve/",
                ".openclaw/",
                ".venv/",
                "coordination/",
                "data/eve_training/",
                "memory/",
                "models/",
                "openclaw/context/",
                "openclaw/memory/",
                "openclaw/wiki/",
                "wiki/",
                "*.gguf",
                "*.safetensors",
            }.issubset(ignored)
        )
        for root_scaffold in ("HEARTBEAT.md", "IDENTITY.md", "SOUL.md", "TOOLS.md", "USER.md"):
            self.assertIn(f"/{root_scaffold}", ignored)
            self.assertNotIn(root_scaffold, ignored)

    def test_operator_scripts_do_not_embed_a_personal_home_or_contact(self):
        paths = [
            "bin/ensure_eve_models_warm.sh",
            "bin/eve_deadman.sh",
            "bin/eve_openai_compat_lab_server.sh",
            "bin/eve_openclaw_repair.py",
            "bin/eve_openclaw_sync.py",
            "bin/eve_openwebui_lab.sh",
            "bin/eve_system_observer.py",
            "bin/install_eve_openclaw.sh",
            "bin/start_llama_cpp_server.sh",
        ]
        for relative in paths:
            text = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                self.assertIsNone(PERSONAL_MAC_HOME.search(text))
                self.assertNotIn("@gmail.com", text.lower())
                for identifier in OWNER_IDENTIFIERS:
                    self.assertNotIn(identifier.lower(), text.lower())

    def test_public_behavior_assets_do_not_embed_the_repository_owner(self):
        paths = [
            "openclaw/AGENTS.md",
            "openclaw/BOOTSTRAP.md",
            "openclaw/HEARTBEAT.md",
            *[
                str(path.relative_to(ROOT))
                for path in sorted((ROOT / "openclaw" / "skills").glob("*/SKILL.md"))
            ],
            "prompts/core_identity.md",
            "prompts/human_analog_self_awareness_test.md",
            "prompts/mind_stream_relationship.md",
            "prompts/proactive_outreach.md",
            "prompts/stream_fast.md",
            "prompts/stream_relationship.md",
        ]
        for relative in paths:
            text = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                self.assertIsNone(PERSONAL_MAC_HOME.search(text))
                for identifier in OWNER_IDENTIFIERS:
                    self.assertNotIn(identifier.lower(), text.lower())

    def test_openclaw_helpers_allow_explicit_project_root(self):
        for relative in ("bin/eve_openclaw_repair.py", "bin/eve_openclaw_sync.py"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                self.assertIn('os.environ.get("EVE_PROJECT_ROOT"', text)
                self.assertIn("Path(__file__).resolve().parents[1]", text)

    def test_legacy_ui_launchers_use_only_relative_candidates(self):
        for relative in ("bin/eve_openai_compat_lab_server.sh", "bin/eve_openwebui_lab.sh"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                self.assertIn('SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"', text)
                self.assertNotIn("Documents/Finances/Eve", text)


if __name__ == "__main__":
    unittest.main()
