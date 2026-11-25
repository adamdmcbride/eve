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
        self.assertEqual(16, result["direct_dependency_count"])
        self.assertEqual(0, result["warning_count"])
        project = audit_module.tomllib.loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]
        declared = audit_module.declared_dependencies(project)
        self.assertNotIn("dvc", declared)
        self.assertNotIn("ragas", declared)
        self.assertNotIn("peft", declared)

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

    def test_transitive_sbom_blocks_unresolved_and_non_permissive_licenses(self):
        payload = {
            "sbom": {
                "packages": [
                    {
                        "name": "safe",
                        "versionInfo": "1.0",
                        "licenseConcluded": "MIT AND Apache-2.0",
                        "externalRefs": [
                            {"referenceType": "purl", "referenceLocator": "pkg:pypi/safe@1.0"}
                        ],
                    },
                    {
                        "name": "unknown",
                        "versionInfo": "1.0",
                        "licenseConcluded": "NOASSERTION",
                        "externalRefs": [
                            {"referenceType": "purl", "referenceLocator": "pkg:pypi/unknown@1.0"}
                        ],
                    },
                    {
                        "name": "copyleft",
                        "versionInfo": "1.0",
                        "licenseConcluded": "GPL-3.0-only",
                        "externalRefs": [
                            {"referenceType": "purl", "referenceLocator": "pkg:pypi/copyleft@1.0"}
                        ],
                    },
                ]
            }
        }
        findings, summary = audit_module.transitive_license_findings(
            payload,
            {
                "permissive_transitive_license_ids": ["MIT", "Apache-2.0"],
                "permissive_transitive_license_refs": [],
                "transitive_license_overrides": {},
            },
        )

        self.assertEqual(3, summary["package_count"])
        self.assertEqual(1, summary["reviewed_package_count"])
        self.assertEqual(
            {
                "dependency.sbom_license_unresolved",
                "dependency.sbom_license_not_permissive",
            },
            {item["id"] for item in findings},
        )

    def test_transitive_override_requires_exact_evidence_and_is_pin_specific(self):
        purl = "pkg:pypi/example@1.0"
        payload = {
            "packages": [
                {
                    "name": "example",
                    "versionInfo": "1.0",
                    "licenseConcluded": "NOASSERTION",
                    "externalRefs": [
                        {"referenceType": "purl", "referenceLocator": purl}
                    ],
                }
            ]
        }
        findings, summary = audit_module.transitive_license_findings(
            payload,
            {
                "permissive_transitive_license_ids": ["PSF-2.0"],
                "permissive_transitive_license_refs": [],
                "transitive_license_overrides": {
                    purl: {
                        "effective_license": "PSF-2.0",
                        "evidence_url": "https://example.invalid/metadata.json",
                        "evidence_sha256": "a" * 64,
                    }
                },
            },
        )

        self.assertEqual([], findings)
        self.assertEqual(1, summary["reviewed_package_count"])
        self.assertEqual(1, summary["overridden_package_count"])

    def test_transitive_override_rejects_placeholder_evidence(self):
        purl = "pkg:pypi/example@1.0"
        findings, summary = audit_module.transitive_license_findings(
            {
                "packages": [
                    {
                        "name": "example",
                        "versionInfo": "1.0",
                        "licenseConcluded": "NOASSERTION",
                        "externalRefs": [
                            {"referenceType": "purl", "referenceLocator": purl}
                        ],
                    }
                ]
            },
            {
                "permissive_transitive_license_ids": ["MIT"],
                "permissive_transitive_license_refs": [],
                "transitive_license_overrides": {
                    purl: {
                        "effective_license": "MIT",
                        "evidence_url": "http://example.invalid/LICENSE",
                        "evidence_sha256": "not-a-digest",
                    }
                },
            },
        )

        self.assertEqual(
            ["dependency.sbom_override_invalid"],
            [item["id"] for item in findings],
        )
        self.assertEqual(0, summary["reviewed_package_count"])
        self.assertEqual(0, summary["overridden_package_count"])

    def test_python_sbom_inventory_must_exactly_match_lock_and_project(self):
        lock = {
            "package": [
                {
                    "name": "sample_dependency",
                    "version": "1.0.0",
                    "source": {"registry": "https://pypi.org/simple"},
                },
                {
                    "name": "eve-local-runtime",
                    "version": "0.1.0",
                    "source": {"virtual": "."},
                },
            ]
        }
        project = {"name": "eve-local-runtime", "version": "0.1.0"}
        payload = {
            "packages": [
                {
                    "externalRefs": [
                        {
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/sample-dependency@1.0.0",
                        }
                    ]
                },
                {
                    "externalRefs": [
                        {
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/eve-local-runtime@0.1.0",
                        }
                    ]
                },
                {
                    "externalRefs": [
                        {
                            "referenceType": "purl",
                            "referenceLocator": "pkg:githubactions/actions/checkout@abc123",
                        }
                    ]
                },
            ]
        }

        findings, summary = audit_module.python_package_inventory_findings(
            payload,
            lock,
            project,
        )
        self.assertEqual([], findings)
        self.assertEqual(2, summary["expected_python_package_count"])
        self.assertEqual(2, summary["observed_python_package_count"])

        payload["packages"][0]["externalRefs"][0][
            "referenceLocator"
        ] = "pkg:pypi/stale-dependency@9.0.0"
        findings, summary = audit_module.python_package_inventory_findings(
            payload,
            lock,
            project,
        )

        self.assertEqual(
            ["dependency.sbom_lock_inventory_mismatch"],
            [item["id"] for item in findings],
        )
        self.assertEqual(1, summary["python_inventory_missing_count"])
        self.assertEqual(1, summary["python_inventory_extra_count"])
        self.assertEqual(
            ["pkg:pypi/sample-dependency@1.0.0"],
            findings[0]["missing_python_packages"],
        )
        self.assertEqual(
            ["pkg:pypi/stale-dependency@9.0.0"],
            findings[0]["extra_python_packages"],
        )

    def test_full_audit_rejects_a_license_clean_but_stale_sbom(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text(
                """[project]\nname='eve-local-runtime'\nversion='0.1.0'\ndependencies=['sample==1.0.0']\n""",
                encoding="utf-8",
            )
            (root / "uv.lock").write_text(
                """version=1
[[package]]
name='eve-local-runtime'
version='0.1.0'
source={ virtual='.' }
[[package]]
name='sample'
version='1.0.0'
source={ registry='https://pypi.org/simple' }
""",
                encoding="utf-8",
            )
            (root / "THIRD_PARTY_NOTICES.md").write_text(
                """## Declared direct dependencies

| Dependency | Locked version | Install group | License reviewed |
| --- | ---: | --- | --- |
| sample | 1.0.0 | core | MIT |
""",
                encoding="utf-8",
            )
            (root / "public_release.json").write_text(
                json.dumps(
                    {
                        "forbidden_declared_dependencies": [],
                        "permissive_transitive_license_ids": ["MIT"],
                        "permissive_transitive_license_refs": [],
                        "transitive_license_overrides": {},
                    }
                ),
                encoding="utf-8",
            )
            packages = []
            for purl in (
                "pkg:pypi/eve-local-runtime@0.1.0",
                "pkg:pypi/sample@1.0.0",
                "pkg:pypi/stale@9.0.0",
            ):
                packages.append(
                    {
                        "name": purl,
                        "versionInfo": purl.rsplit("@", 1)[1],
                        "licenseConcluded": "MIT",
                        "externalRefs": [
                            {"referenceType": "purl", "referenceLocator": purl}
                        ],
                    }
                )
            sbom_path = root / "sbom.json"
            sbom_path.write_text(json.dumps({"packages": packages}), encoding="utf-8")

            result = audit_module.audit(
                root,
                sbom_path=sbom_path,
                source_revision="a" * 40,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(
            ["dependency.sbom_lock_inventory_mismatch"],
            [item["id"] for item in result["findings"]],
        )
        self.assertEqual(1, result["sbom"]["python_inventory_extra_count"])
        self.assertRegex(result["sbom"]["uv_lock_sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
