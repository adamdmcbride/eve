import json
import tempfile
import unittest
from pathlib import Path

import eve_openclaw


class OpenClawWikiPathHealthTests(unittest.TestCase):
    def write_profile(self, state_dir: Path, vault_path: str, *, enabled: bool = True) -> dict:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "openclaw.json").write_text(
            json.dumps(
                {
                    "plugins": {
                        "entries": {
                            "memory-wiki": {
                                "enabled": enabled,
                                "config": {"vault": {"path": vault_path}},
                            }
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        return {"openclaw_state_dir": str(state_dir)}

    def test_enabled_relative_vault_is_rejected_as_split_vault_risk(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self.write_profile(Path(temp_dir) / "state", "wiki/eve-memory-wiki")

            fields = eve_openclaw.openclaw_memory_wiki_fields(config)

        self.assertTrue(fields["memory_wiki_enabled"])
        self.assertTrue(fields["memory_wiki_vault_path_explicit"])
        self.assertFalse(fields["memory_wiki_vault_path_absolute"])
        self.assertFalse(fields["memory_wiki_vault_config_ok"])
        self.assertIn("split the vault", fields["memory_wiki_vault_error"])

    def test_enabled_existing_absolute_vault_is_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            vault = root / "runtime" / "openclaw" / "wiki" / "eve-memory-wiki"
            vault.mkdir(parents=True)
            config = self.write_profile(root / "state", str(vault))

            fields = eve_openclaw.openclaw_memory_wiki_fields(config)

        self.assertTrue(fields["memory_wiki_enabled"])
        self.assertTrue(fields["memory_wiki_vault_path_absolute"])
        self.assertTrue(fields["memory_wiki_vault_exists"])
        self.assertTrue(fields["memory_wiki_vault_config_ok"])
        self.assertEqual("", fields["memory_wiki_vault_error"])

    def test_disabled_plugin_does_not_turn_optional_relative_path_into_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self.write_profile(
                Path(temp_dir) / "state",
                "wiki/eve-memory-wiki",
                enabled=False,
            )

            fields = eve_openclaw.openclaw_memory_wiki_fields(config)

        self.assertFalse(fields["memory_wiki_enabled"])
        self.assertTrue(fields["memory_wiki_vault_config_ok"])

    def test_summary_prioritizes_enabled_split_vault_over_stale_success(self) -> None:
        status = dict(eve_openclaw.DEFAULT_OPENCLAW_STATUS)
        status.update(
            {
                "enabled": True,
                "command_available": True,
                "installed": True,
                "config_valid": True,
                "memory_wiki_enabled": True,
                "memory_wiki_vault_config_ok": False,
                "memory_wiki_vault_error": "vault.path must be absolute",
                "gateway_reachable": True,
                "memory_status_ok": True,
                "last_sync_ok": True,
                "last_sync_summary": "sync completed",
            }
        )

        summary = eve_openclaw.build_openclaw_summary(status)

        self.assertIn("memory-wiki vault is misconfigured", summary)
        self.assertIn("must be absolute", summary)
        self.assertNotIn("recovered cleanly", summary)


if __name__ == "__main__":
    unittest.main()
