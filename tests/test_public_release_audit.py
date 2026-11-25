import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "eve_public_release_audit",
    ROOT / "bin" / "eve_public_release_audit.py",
)
eve_public_release_audit = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(eve_public_release_audit)


def config():
    return {
        "schema_version": 1,
        "project_name": "Eve",
        "github_owner": "example-person",
        "github_repository": "eve",
        "publisher_kind": "personal",
        "release_strategy": "clean_export",
        "max_file_bytes": 1024 * 1024,
        "required_files": ["README.md", "LICENSE", "pyproject.toml"],
        "include": ["*.md", "*.py", "LICENSE", "pyproject.toml", "src/**"],
        "force_include": [],
        "exclude": ["private/**"],
        "tracked_private_patterns": ["private/**"],
        "portable_source_patterns": ["*.py", "src/**"],
        "behavior_patterns": ["src/prompts/**"],
        "behavior_owner_names": ["OwnerName"],
        "owner_sensitive_patterns": ["*.py", "src/**"],
        "owner_identity_allowed_patterns": [],
        "owner_identifiers": ["OwnerName", "com.owner."],
        "owner_identifier_exemptions": {},
        "supported_installers": [],
        "forbidden_declared_dependencies": ["source-available-lab"],
    }


class PublicReleaseAuditTests(unittest.TestCase):
    def make_public_root(self, base):
        root = Path(base)
        root.mkdir(parents=True, exist_ok=True)
        (root / "README.md").write_text("# Eve\n", encoding="utf-8")
        (root / "LICENSE").write_text("Apache License\n", encoding="utf-8")
        (root / "pyproject.toml").write_text(
            """[project]\nname = \"eve\"\nversion = \"0.1.0\"\nlicense = {text = \"Apache-2.0\"}\nreadme = \"README.md\"\nauthors = [{name = \"Maintainer\"}]\n""",
            encoding="utf-8",
        )
        return root

    def test_candidate_selection_excludes_private_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_public_root(tmp)
            (root / "src").mkdir()
            (root / "src" / "eve.py").write_text("print('ok')\n", encoding="utf-8")
            (root / "private").mkdir()
            (root / "private" / "memory.md").write_text("private\n", encoding="utf-8")
            selected, tracked = eve_public_release_audit.candidate_paths(
                root,
                config(),
                known_paths={"README.md", "LICENSE", "pyproject.toml", "src/eve.py", "private/memory.md"},
            )

        self.assertIn("src/eve.py", selected)
        self.assertNotIn("private/memory.md", selected)
        self.assertIn("private/memory.md", tracked)

    def test_repository_exports_focused_public_architecture_contracts(self):
        release_config = eve_public_release_audit.load_config(ROOT / "public_release.json")
        required_contracts = {
            "docs/architecture/EVE_ATTACHMENT_BOUNDARY_2026_08_23.md",
            "docs/architecture/EVE_APP_REFRESH_CONTRACT_2026_08_23.md",
            "docs/architecture/EVE_LOOPBACK_HTTP_SECURITY_2026_08_23.md",
            "docs/architecture/EVE_STORE_CONCURRENCY_2026_08_23.md",
            "docs/evidence/PERFORMANCE_OBSERVATION_CONTRACT_2026_08_23.md",
        }
        self.assertTrue(required_contracts.issubset(set(release_config["force_include"])))
        selected, _tracked = eve_public_release_audit.candidate_paths(
            ROOT,
            release_config,
            include_untracked=True,
        )
        self.assertTrue(required_contracts.issubset(set(selected)))

    def test_public_runtime_imports_are_selected(self):
        # Check startup imports without importing Eve or starting local services.
        import ast

        policy = eve_public_release_audit.load_config(ROOT / "public_release.json")
        selected, _ = eve_public_release_audit.candidate_paths(ROOT, policy, include_untracked=True)
        for stmt in ast.parse((ROOT / "eve.py").read_bytes()).body:
            if isinstance(stmt, ast.Import):
                modules = [alias.name for alias in stmt.names]
            elif isinstance(stmt, ast.ImportFrom):
                modules = [stmt.module or ""]
            else:
                continue
            for module in modules:
                if module.startswith("eve_"):
                    path = module.replace(".", "/")
                    self.assertTrue(path + ".py" in selected or path + "/__init__.py" in selected, module)

    def test_placeholder_blocks_scan_hash_and_copy_without_opening(self):
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "eve.py"
            source.write_text("pass")
            original_stat = source.stat()
            placeholder = SimpleNamespace(st_mode=original_stat.st_mode, st_size=4, st_flags=0x40000000)
            with patch.object(Path, "lstat", return_value=placeholder), patch.object(
                eve_public_release_audit.os, "open", side_effect=AssertionError("opened placeholder")
            ):
                findings = eve_public_release_audit.scan_candidate(root, "eve.py", config())
                self.assertEqual([item["id"] for item in findings], ["public.source_not_local"])
                with self.assertRaisesRegex(ValueError, "not local"):
                    eve_public_release_audit.sha256_file(source)
                with self.assertRaisesRegex(ValueError, "not local"):
                    eve_public_release_audit._copy_regular_file(source, root / "copy", "eve.py")
            self.assertFalse((root / "copy").exists())

    def test_github_remote_parser_accepts_personal_ssh_and_https_urls(self):
        self.assertEqual(
            ("example-person", "eve"),
            eve_public_release_audit.github_remote_coordinates(
                "git@github.com:example-person/eve.git"
            ),
        )
        self.assertEqual(
            ("example-person", "eve"),
            eve_public_release_audit.github_remote_coordinates(
                "https://github.com/example-person/eve"
            ),
        )

    def test_tracked_private_material_blocks_direct_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_public_root(tmp)
            (root / "private").mkdir()
            (root / "private" / "memory.md").write_text("private\n", encoding="utf-8")
            report = eve_public_release_audit.audit_repository(
                root,
                config(),
                known_paths={"README.md", "LICENSE", "pyproject.toml", "private/memory.md"},
                include_git_posture=False,
            )

        self.assertFalse(report["ok"])
        self.assertIn("public.private_path_tracked", {item["id"] for item in report["findings"]})

    def test_clean_candidate_can_exclude_private_source_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_public_root(tmp)
            (root / "private").mkdir()
            (root / "private" / "memory.md").write_text("private\n", encoding="utf-8")
            report = eve_public_release_audit.audit_repository(
                root,
                config(),
                known_paths={"README.md", "LICENSE", "pyproject.toml", "private/memory.md"},
                include_git_posture=False,
                enforce_tracked_private=False,
            )

        self.assertTrue(report["ok"])
        self.assertEqual("clean_candidate", report["audit_scope"])
        self.assertEqual(1, report["source_private_tracked_count"])
        self.assertIn("public.private_paths_excluded", {item["id"] for item in report["findings"]})

    def test_required_file_must_be_selected_not_just_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_public_root(tmp)
            report = eve_public_release_audit.audit_repository(
                root,
                config(),
                known_paths={"README.md", "LICENSE"},
                include_git_posture=False,
            )

        self.assertFalse(report["ok"])
        self.assertIn("public.required_file_not_selected", {item["id"] for item in report["findings"]})

    def test_source_checkout_installer_satisfies_non_packageable_onboarding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_public_root(tmp)
            with (root / "pyproject.toml").open("a", encoding="utf-8") as handle:
                handle.write("\n[tool.uv]\npackage = false\n")
            installer = root / "src" / "install.py"
            installer.parent.mkdir(parents=True)
            installer.write_text("print('install')\n", encoding="utf-8")
            release_config = config()
            release_config["supported_installers"] = ["src/install.py"]
            report = eve_public_release_audit.audit_repository(
                root,
                release_config,
                known_paths={"README.md", "LICENSE", "pyproject.toml", "src/install.py"},
                include_git_posture=False,
            )

        self.assertNotIn("packaging.not_installable", {item["id"] for item in report["findings"]})

    def test_non_permissive_declared_dependency_blocks_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_public_root(tmp)
            with (root / "pyproject.toml").open("a", encoding="utf-8") as handle:
                handle.write(
                    "\n[project.optional-dependencies]\nlab = [\"source-available-lab>=1\"]\n"
                )
            report = eve_public_release_audit.audit_repository(
                root,
                config(),
                known_paths={"README.md", "LICENSE", "pyproject.toml"},
                include_git_posture=False,
            )

        self.assertFalse(report["ok"])
        self.assertIn(
            "license.forbidden_declared_dependency",
            {item["id"] for item in report["findings"]},
        )

    def test_secret_values_are_never_returned_in_findings(self):
        secret = "gh" + "p_" + "abcdefghijklmnopqrstuvwxyz1234567890"
        findings = eve_public_release_audit.scan_candidate_data(
            "app.py",
            ("TOKEN = %r\n" % secret).encode("utf-8"),
            config(),
        )
        report = {
            "ok": not any(item["severity"] == "error" for item in findings),
            "findings": findings,
        }

        serialized = json.dumps(report)
        self.assertFalse(report["ok"])
        self.assertIn("secret.github_token", {item["id"] for item in report["findings"]})
        self.assertNotIn(secret, serialized)

    def test_oversized_candidate_is_rejected_before_reading_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "large.py"
            path.write_bytes(b"x" * 32)
            release_config = config()
            release_config["max_file_bytes"] = 16
            with patch.object(
                eve_public_release_audit.os,
                "read",
                side_effect=AssertionError("oversized file must not be read"),
            ) as read:
                findings = eve_public_release_audit.scan_candidate(
                    root,
                    "large.py",
                    release_config,
                )

        self.assertFalse(read.called)
        self.assertEqual(
            ["public.file_too_large"],
            [item["id"] for item in findings],
        )

    def test_candidate_growth_after_open_is_still_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "growing.py").write_bytes(b"x")
            release_config = config()
            release_config["max_file_bytes"] = 16
            with patch.object(
                eve_public_release_audit.os,
                "read",
                side_effect=[b"x" * 16, b"y"],
            ) as read:
                findings = eve_public_release_audit.scan_candidate(
                    root,
                    "growing.py",
                    release_config,
                )

        self.assertEqual(2, read.call_count)
        self.assertEqual(
            ["public.file_too_large"],
            [item["id"] for item in findings],
        )

    @unittest.skipUnless(hasattr(eve_public_release_audit.os, "mkfifo"), "FIFO requires POSIX")
    def test_non_regular_candidate_is_rejected_without_opening_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fifo = root / "blocked.py"
            eve_public_release_audit.os.mkfifo(fifo)
            with patch.object(
                eve_public_release_audit.os,
                "open",
                side_effect=AssertionError("non-regular file must not be opened"),
            ) as opened:
                findings = eve_public_release_audit.scan_candidate(
                    root,
                    "blocked.py",
                    config(),
                )

        self.assertFalse(opened.called)
        self.assertEqual(
            ["public.non_regular_file"],
            [item["id"] for item in findings],
        )

    def test_user_home_in_source_and_owner_specific_prompt_are_blockers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_public_root(tmp)
            prompt = root / "src" / "prompts"
            prompt.mkdir(parents=True)
            (prompt / "identity.md").write_text("Always address OwnerName.\n", encoding="utf-8")
            example_home = "/" + "Users/example/Eve"
            (root / "src" / "runtime.py").write_text(
                "ROOT = %r\nDEFAULT_USER = 'OwnerName'\n" % example_home,
                encoding="utf-8",
            )
            report = eve_public_release_audit.audit_repository(
                root,
                config(),
                known_paths={
                    "README.md",
                    "LICENSE",
                    "pyproject.toml",
                    "src/prompts/identity.md",
                    "src/runtime.py",
                },
                include_git_posture=False,
            )

        ids = {item["id"] for item in report["findings"]}
        self.assertIn("privacy.absolute_user_home", ids)
        self.assertIn("privacy.owner_specific_behavior", ids)
        self.assertIn("privacy.owner_specific_source", ids)

    def test_technical_owner_substring_exemption_does_not_hide_owner_prose(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_public_root(tmp)
            source = root / "src" / "optimizer.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "optimizer = OptimizerOwnerNameW()\nDEFAULT_USER = 'OwnerName'\n",
                encoding="utf-8",
            )
            release_config = config()
            release_config["owner_identifier_exemptions"] = {
                "src/optimizer.py": [r"OptimizerOwnerNameW"],
            }
            report = eve_public_release_audit.audit_repository(
                root,
                release_config,
                known_paths={"README.md", "LICENSE", "pyproject.toml", "src/optimizer.py"},
                include_git_posture=False,
            )

        owner_findings = [
            item for item in report["findings"] if item["id"] == "privacy.owner_specific_source"
        ]
        self.assertEqual(1, len(owner_findings))
        self.assertEqual(2, owner_findings[0]["line"])

    def test_clean_tree_can_export_and_hash_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self.make_public_root(base / "source")
            tracked = {"README.md", "LICENSE", "pyproject.toml"}
            report = eve_public_release_audit.audit_repository(
                root,
                config(),
                known_paths=tracked,
                include_git_posture=False,
            )
            destination = base / "export"
            eve_public_release_audit.export_tree(root, destination, report["candidate_paths"])
            manifest = eve_public_release_audit.manifest_for(root, report["candidate_paths"])
            verification = eve_public_release_audit.verify_manifest(
                destination,
                manifest,
                expected_paths=report["candidate_paths"],
                exact_tree=True,
            )
            exported_readme = (destination / "README.md").is_file()

        self.assertTrue(report["ok"])
        self.assertTrue(exported_readme)
        self.assertEqual(2, manifest["schema_version"])
        self.assertEqual(3, manifest["file_count"])
        self.assertEqual(64, len(manifest["tree_sha256"]))
        self.assertEqual(64, len(manifest["files"][0]["sha256"]))
        self.assertTrue(verification["ok"])
        self.assertEqual(3, verification["verified_file_count"])

    def test_manifest_verification_detects_same_size_tampering_and_extra_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_public_root(tmp)
            tracked = ["LICENSE", "README.md", "pyproject.toml"]
            manifest = eve_public_release_audit.manifest_for(root, tracked)
            (root / "README.md").write_text("# Eva\n", encoding="utf-8")
            (root / "unreviewed.txt").write_text("extra\n", encoding="utf-8")
            verification = eve_public_release_audit.verify_manifest(
                root,
                manifest,
                expected_paths=tracked,
                exact_tree=True,
            )

        self.assertFalse(verification["ok"])
        ids = {item["id"] for item in verification["findings"]}
        self.assertIn("manifest.sha256_mismatch", ids)
        self.assertIn("manifest.exact_tree_extra_path", ids)

    def test_manifest_validation_rejects_path_traversal_and_summary_tampering(self):
        traversal = {
            "schema_version": 1,
            "files": [{"path": "../secret", "bytes": 1, "sha256": "0" * 64}],
        }
        with self.assertRaisesRegex(ValueError, "escapes"):
            eve_public_release_audit.validate_manifest(traversal)

        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_public_root(tmp)
            manifest = eve_public_release_audit.manifest_for(root, ["README.md"])
            manifest["total_bytes"] += 1
            with self.assertRaisesRegex(ValueError, "total_bytes"):
                eve_public_release_audit.validate_manifest(manifest)

    def test_failed_export_validation_leaves_no_partial_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self.make_public_root(base / "source")
            destination = base / "export"

            def reject(_staging):
                raise ValueError("simulated post-copy failure")

            with self.assertRaisesRegex(ValueError, "simulated"):
                eve_public_release_audit.export_tree(
                    root,
                    destination,
                    ["README.md", "LICENSE", "pyproject.toml"],
                    validator=reject,
                )

            destination_exists = destination.exists()
            staging_paths = list(base.glob(".export.eve-export-*"))

        self.assertFalse(destination_exists)
        self.assertEqual([], staging_paths)

    def test_cli_writes_external_manifest_and_verifies_export_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self.make_public_root(base / "source")
            release_config = config()
            config_path = root / "public_release.json"
            config_path.write_text(json.dumps(release_config), encoding="utf-8")
            manifest_path = base / "eve-manifest.json"
            destination = base / "export"
            with contextlib.redirect_stdout(io.StringIO()):
                export_code = eve_public_release_audit.main(
                    [
                        "--root",
                        str(root),
                        "--config",
                        str(config_path),
                        "--write-manifest",
                        str(manifest_path),
                        "--export",
                        str(destination),
                    ]
                )
                verify_code = eve_public_release_audit.main(
                    [
                        "--root",
                        str(destination),
                        "--config",
                        str(config_path),
                        "--verify-manifest",
                        str(manifest_path),
                        "--exact-tree",
                    ]
                )
            manifest_exists = manifest_path.is_file()

        self.assertEqual(0, export_code)
        self.assertEqual(0, verify_code)
        self.assertTrue(manifest_exists)

    def test_cli_refuses_export_when_audit_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release_config = config()
            (root / "public_release.json").write_text(json.dumps(release_config), encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                code = eve_public_release_audit.main(
                    ["--root", str(root), "--include-untracked", "--export", str(root / "export")]
                )

        self.assertEqual(2, code)
        self.assertIn("export refused", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
