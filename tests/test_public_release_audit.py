import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


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
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_public_root(tmp)
            secret = "gh" + "p_" + "abcdefghijklmnopqrstuvwxyz1234567890"
            (root / "app.py").write_text("TOKEN = %r\n" % secret, encoding="utf-8")
            report = eve_public_release_audit.audit_repository(
                root,
                config(),
                known_paths={"README.md", "LICENSE", "pyproject.toml", "app.py"},
                include_git_posture=False,
            )

        serialized = json.dumps(report)
        self.assertFalse(report["ok"])
        self.assertIn("secret.github_token", {item["id"] for item in report["findings"]})
        self.assertNotIn(secret, serialized)

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
            exported_readme = (destination / "README.md").is_file()

        self.assertTrue(report["ok"])
        self.assertTrue(exported_readme)
        self.assertEqual(64, len(manifest["files"][0]["sha256"]))

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
