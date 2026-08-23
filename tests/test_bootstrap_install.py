import hashlib
import io
import json
import subprocess
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import eve
import eve_web


class BootstrapInstallTests(unittest.TestCase):
    def test_bootstrap_bundle_payload_includes_models_and_urls(self):
        with patch.object(
            eve,
            "load_config",
            return_value={
                "model": "eve-deep",
                "fast_model": "eve-fast",
                "deep_model": "eve-deep",
                "preferred_fast_model": "eve-fast",
                "preferred_deep_model": "eve-deep",
            },
        ), patch.object(eve, "load_runtime_identity", return_value={"runtime_summary": "Primary Eve"}), patch.object(
            eve, "load_human_context", return_value={"self_model": {"identity_statement": "Primary Eve"}}
        ), patch.object(eve, "load_active_mind", return_value={"current_focus": "Keep going"}):
            payload = eve.bootstrap_bundle_payload(
                primary_host="eve-main.local",
                api_port=8787,
                ollama_port=11434,
            )

        self.assertEqual("eve-main.local", payload["primary_host"])
        self.assertEqual("http://eve-main.local:8787", payload["primary_eve_url"])
        self.assertEqual("http://eve-main.local:11434", payload["primary_ollama_url"])
        self.assertEqual(["eve-deep", "eve-fast"], sorted(payload["models"]))

    def test_apply_bootstrap_bundle_uses_primary_ollama_without_pulling(self):
        payload = {
            "source_platform": "macos",
            "primary_host": "eve-main.local",
            "primary_eve_url": "http://eve-main.local:8787",
            "primary_ollama_url": "http://eve-main.local:11434",
            "config": {
                "model": "eve-deep",
                "fast_model": "eve-fast",
                "deep_model": "eve-deep",
                "preferred_fast_model": "eve-fast",
                "preferred_deep_model": "eve-deep",
            },
            "runtime_identity": {"runtime_summary": "Primary Eve"},
            "human_context": {"self_model": {"identity_statement": "Primary Eve"}},
            "active_mind": {"current_focus": "Keep going"},
        }
        with patch.object(eve, "ensure_store"), patch.object(
            eve,
            "load_config",
            return_value={"model": "gemma4:31b", "ollama_host": "http://127.0.0.1:11434"},
        ), patch.object(eve, "save_config") as save_config, patch.object(
            eve, "save_runtime_identity"
        ) as save_runtime_identity, patch.object(eve, "save_human_context") as save_human_context, patch.object(
            eve, "save_active_mind"
        ) as save_active_mind, patch.object(eve, "append_entry") as append_entry, patch.object(
            eve, "run_local_command"
        ) as run_local_command:
            result = eve.apply_bootstrap_bundle(
                payload,
                use_primary_ollama=True,
                pull_models=False,
            )

        run_local_command.assert_not_called()
        self.assertEqual("http://eve-main.local:11434", result["ollama_host"])
        save_config.assert_called_once()
        saved_config = save_config.call_args.args[0]
        self.assertEqual("http://eve-main.local:11434", saved_config["ollama_host"])
        self.assertEqual("eve-fast", saved_config["fast_model"])
        save_runtime_identity.assert_called_once()
        save_human_context.assert_called_once()
        save_active_mind.assert_called_once()
        append_entry.assert_called_once()

    def test_apply_bootstrap_bundle_pulls_local_models_when_requested(self):
        payload = {
            "config": {
                "model": "eve-deep",
                "fast_model": "eve-fast",
                "deep_model": "eve-deep",
            },
        }
        with patch.object(eve, "ensure_store"), patch.object(
            eve,
            "load_config",
            return_value={"model": "gemma4:31b", "ollama_host": "http://127.0.0.1:11434"},
        ), patch.object(eve, "save_config"), patch.object(eve, "save_runtime_identity"), patch.object(
            eve, "save_human_context"
        ), patch.object(eve, "save_active_mind"), patch.object(eve, "append_entry"), patch.object(
            eve,
            "run_local_command",
            return_value=subprocess.CompletedProcess(["ollama", "pull", "eve-fast"], 0, stdout="", stderr=""),
        ) as run_local_command:
            result = eve.apply_bootstrap_bundle(
                payload,
                use_primary_ollama=False,
                pull_models=True,
            )

        self.assertEqual("http://127.0.0.1:11434", result["ollama_host"])
        pulled = [call.args[0][-1] for call in run_local_command.call_args_list]
        self.assertEqual(["eve-deep", "eve-fast"], sorted(pulled))

    def test_fetch_bootstrap_bundle_reads_api_envelope(self):
        with patch.object(
            eve,
            "request_json_url",
            return_value={"ok": True, "data": {"version": 1, "primary_host": "eve-main.local"}},
        ) as request_json_url:
            payload = eve.fetch_bootstrap_bundle(
                host="eve-main.local",
                api_port=8787,
                ollama_port=11434,
                timeout=9,
            )

        request_json_url.assert_called_once_with(
            "http://eve-main.local:8787/api/bootstrap?ollama_port=11434",
            timeout=9,
        )
        self.assertEqual("eve-main.local", payload["primary_host"])

    def test_build_update_manifest_includes_code_and_bootstrap_hashes(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("_manifest.json", json.dumps({"version": 1, "generated_at": "2026-04-21T12:00:00Z", "files": ["eve.py"]}))
            archive.writestr("eve.py", b"print('eve')\n")
        code_bytes = stream.getvalue()
        bootstrap_payload = {
            "generated_at": "2026-04-21T12:01:00Z",
            "primary_eve_url": "http://eve-main.local:8787",
            "primary_ollama_url": "http://eve-main.local:11434",
            "models": ["eve-fast", "eve-deep"],
        }
        with patch.object(eve, "build_code_bundle_archive", return_value=code_bytes), patch.object(
            eve, "bootstrap_bundle_payload", return_value=bootstrap_payload
        ):
            manifest = eve.build_update_manifest(primary_host="eve-main.local", api_port=8787, ollama_port=11434)

        self.assertEqual("eve-main.local", manifest["primary_host"])
        self.assertEqual(hashlib.sha256(code_bytes).hexdigest(), manifest["code_bundle"]["sha256"])
        self.assertEqual(1, manifest["code_bundle"]["file_count"])
        self.assertEqual("http://eve-main.local:8787", manifest["primary_eve_url"])
        self.assertEqual("http://eve-main.local:11434", manifest["primary_ollama_url"])
        self.assertEqual(
            eve.sha256_text(
                json.dumps(
                    {
                        "primary_eve_url": "http://eve-main.local:8787",
                        "primary_ollama_url": "http://eve-main.local:11434",
                        "models": ["eve-fast", "eve-deep"],
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                )
            ),
            manifest["bootstrap"]["sha256"],
        )

    def test_build_code_bundle_archive_excludes_runtime_state(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "eve.py").write_text("print('eve')\n", encoding="utf-8")
            (root / "README.md").write_text("# Eve\n", encoding="utf-8")
            (root / ".eve").mkdir()
            (root / ".eve" / "config.json").write_text("{}", encoding="utf-8")
            (root / "coordination").mkdir()
            (root / "coordination" / "updates.jsonl").write_text("", encoding="utf-8")

            with patch.object(eve, "ROOT", root):
                archive_bytes = eve.build_code_bundle_archive()

        with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as archive:
            names = set(archive.namelist())
        self.assertIn("eve.py", names)
        self.assertIn("README.md", names)
        self.assertNotIn(".eve/config.json", names)
        self.assertNotIn("coordination/updates.jsonl", names)

    def test_code_bundle_path_selection_is_allowlisted_and_private_safe(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixtures = {
                "eve.py": "print('eve')\n",
                "README.md": "# Eve\n",
                "docs/routing/route.json": "{}\n",
                "docs/private-notes.md": "private\n",
                ".venv/lib/site.py": "secret\n",
                ".venv-extra/lib/site.py": "secret\n",
                "memory/transcript.md": "private\n",
                "models/weights.bin": "private\n",
                "openclaw/skills/example/SKILL.md": "public skill\n",
                "openclaw/memory/today.md": "private\n",
                "openclaw/context/status.json": "private\n",
                "unrelated.txt": "not product source\n",
            }
            for relative, content in fixtures.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            with patch.object(eve, "ROOT", root):
                paths = {path.as_posix() for path in eve.iter_code_bundle_paths()}

        self.assertEqual(
            {
                "README.md",
                "docs/routing/route.json",
                "eve.py",
                "openclaw/skills/example/SKILL.md",
            },
            paths,
        )

    def test_apply_code_bundle_archive_backs_up_existing_files(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app_dir = root / ".eve"
            app_dir.mkdir()
            target = root / "eve.py"
            target.write_text("old\n", encoding="utf-8")
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("_manifest.json", "{\"version\":1}\n")
                archive.writestr("eve.py", b"new\n")

            with patch.object(eve, "ROOT", root), patch.object(eve, "APP_DIR", app_dir), patch.object(
                eve, "ensure_store"
            ), patch.object(eve, "append_entry"), patch.object(
                eve, "utc_timestamp_for_filename", return_value="20260421T150000Z"
            ):
                result = eve.apply_code_bundle_archive(stream.getvalue())
            self.assertEqual("new\n", target.read_text(encoding="utf-8"))
            backup = app_dir / "code_update_backups" / "20260421T150000Z" / "eve.py"
            self.assertEqual("old\n", backup.read_text(encoding="utf-8"))
            self.assertIn("eve.py", result["updated_files"])
            self.assertIn("eve.py", result["backed_up_files"])

    def test_build_windows_installer_script_includes_bootstrap_command(self):
        script = eve_web.build_windows_installer_script(
            Path(r"C:\payload"),
            Path(r"C:\out\EveSetup.exe"),
            "eve-main.local",
            8787,
        )
        self.assertIn('OutFile "C:\\out\\EveSetup.exe"', script)
        self.assertIn('-PrimaryHost "eve-main.local"', script)
        self.assertIn("-PrimaryApiPort 8787", script)
        self.assertIn("-PullModels", script)

    def test_windows_update_script_tracks_update_manifest_and_restart(self):
        script = (Path(__file__).resolve().parents[1] / "bin" / "update_windows_eve.ps1").read_text(encoding="utf-8")
        self.assertIn("/api/update-manifest", script)
        self.assertIn("/api/windows-app-package", script)
        self.assertIn('$UpdateTaskName = "Eve Auto Update"', script)
        self.assertIn("apply_windows_app_update.ps1", script)
        self.assertIn("[switch]$IncludeApp", script)
        self.assertIn("current_app_version_sha", script)
        self.assertIn("previous_app_version_sha", script)
        self.assertIn("-RollbackVersion", script)
        self.assertIn('Invoke-Python -Python $Python -Arguments @($EveScript, "daemon", "stop")', script)
        self.assertIn('Invoke-Python -Python $Python -Arguments @($EveScript, "daemon", "install")', script)

    def test_build_windows_app_package_archive_contains_update_helper(self):
        archive_bytes = eve_web.build_windows_app_package_archive("eve-main.local", 8787)
        with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as archive:
            names = set(archive.namelist())
            update_script = archive.read("bin/update_windows_eve.ps1").decode("utf-8")
        self.assertIn("bin/apply_windows_app_update.ps1", names)
        self.assertIn('[string]$PrimaryHost = "eve-main.local"', update_script)

    def test_windows_app_update_helper_supports_versioned_cache_and_rollback(self):
        helper = (Path(__file__).resolve().parents[1] / "bin" / "apply_windows_app_update.ps1").read_text(encoding="utf-8")
        self.assertIn(".eve\\windows_app", helper)
        self.assertIn("versions", helper)
        self.assertIn("RollbackVersion", helper)
        self.assertIn("Stage-PackageVersion", helper)


if __name__ == "__main__":
    unittest.main()
