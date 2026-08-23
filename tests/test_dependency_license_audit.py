import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "eve_dependency_license_audit.py"
SPEC = importlib.util.spec_from_file_location("eve_dependency_license_audit", SCRIPT)
audit_module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(audit_module)


class DependencyLicenseAuditTests(unittest.TestCase):
    def test_repository_direct_dependency_inventory_is_complete(self):
        result = audit_module.audit(ROOT)
        self.assertTrue(result["ok"], result["findings"])
        self.assertEqual(19, result["direct_dependency_count"])
        self.assertEqual(0, result["warning_count"])

    def test_missing_notice_and_forbidden_dependency_block_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text(
                """[project]\nname='eve'\nversion='0.1.0'\ndependencies=['bad-package>=1']\n""",
                encoding="utf-8",
            )
            (root / "uv.lock").write_text(
                """version=1\n[[package]]\nname='bad-package'\nversion='1.0.0'\n""",
                encoding="utf-8",
            )
            (root / "THIRD_PARTY_NOTICES.md").write_text(
                "## Declared direct dependencies\n", encoding="utf-8"
            )
            (root / "public_release.json").write_text(
                json.dumps({"forbidden_declared_dependencies": ["bad-package"]}),
                encoding="utf-8",
            )
            result = audit_module.audit(root)
        self.assertFalse(result["ok"])
        ids = {item["id"] for item in result["findings"]}
        self.assertIn("dependency.forbidden_declared", ids)
        self.assertIn("dependency.notice_missing", ids)

    def test_non_permissive_reviewed_direct_license_blocks_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text(
                """[project]\nname='eve'\nversion='0.1.0'\ndependencies=['sample>=1']\n""",
                encoding="utf-8",
            )
            (root / "uv.lock").write_text(
                """version=1\n[[package]]\nname='sample'\nversion='1.0.0'\n""",
                encoding="utf-8",
            )
            (root / "THIRD_PARTY_NOTICES.md").write_text(
                """## Declared direct dependencies\n\n| Dependency | Locked version | Install group | License reviewed |\n| --- | ---: | --- | --- |\n| sample | 1.0.0 | core | GPL-3.0 |\n""",
                encoding="utf-8",
            )
            (root / "public_release.json").write_text(
                json.dumps({"forbidden_declared_dependencies": []}), encoding="utf-8"
            )
            result = audit_module.audit(root)
        self.assertFalse(result["ok"])
        self.assertIn(
            "dependency.non_permissive_direct_license",
            {item["id"] for item in result["findings"]},
        )


if __name__ == "__main__":
    unittest.main()
