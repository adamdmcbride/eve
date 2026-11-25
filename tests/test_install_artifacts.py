import ast
import io
import tarfile
import unittest
import zipfile
from pathlib import Path

import eve_install_artifacts
import eve_web


ROOT = Path(__file__).resolve().parents[1]
EXPORTED_NAMES = (
    "trusted_installer_endpoint",
    "advertised_endpoint_query",
    "customized_windows_script",
    "customized_windows_launcher",
    "build_unix_installer_script",
    "build_macos_installer_bundle",
    "build_macos_installer_app_bundle",
    "build_linux_installer_bundle",
    "stage_windows_installer_payload",
    "build_windows_installer_script",
    "build_windows_installer_exe",
    "build_windows_app_package_archive",
    "render_windows_install_page",
    "render_install_page",
)


class InstallArtifactModuleTests(unittest.TestCase):
    def test_eve_web_is_a_compatibility_facade_for_installer_artifacts(self):
        web_source = (ROOT / "eve_web.py").read_text(encoding="utf-8")

        for name in EXPORTED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(eve_install_artifacts, name),
                    getattr(eve_web, name),
                )
                self.assertNotIn(f"def {name}(", web_source)

        self.assertEqual(
            eve_install_artifacts.MAC_INSTALLER_VERSION,
            eve_web.MAC_INSTALLER_VERSION,
        )

    def test_artifact_module_does_not_import_the_http_service(self):
        tree = ast.parse((ROOT / "eve_install_artifacts.py").read_text(encoding="utf-8"))
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

        self.assertNotIn("eve_web", imported_modules)

    def test_install_pages_use_only_the_validated_advertised_endpoint(self):
        for renderer in (
            eve_install_artifacts.render_install_page,
            eve_install_artifacts.render_windows_install_page,
        ):
            with self.subTest(renderer=renderer.__name__):
                page = renderer(
                    "http://attacker.example:9999",
                    "eve-main.local",
                    8787,
                ).decode("utf-8")

                self.assertIn("http://eve-main.local:8787", page)
                self.assertNotIn("attacker.example", page)

    def test_portable_installer_archives_keep_the_existing_entry_contract(self):
        macos = eve_install_artifacts.build_macos_installer_bundle(
            "eve-main.local",
            8787,
        )
        linux = eve_install_artifacts.build_linux_installer_bundle(
            "eve-main.local",
            8787,
        )

        with zipfile.ZipFile(io.BytesIO(macos), "r") as archive:
            self.assertEqual(
                {"Install Eve.command", "README.txt"},
                set(archive.namelist()),
            )
            self.assertIn(
                'PRIMARY_HOST="eve-main.local"',
                archive.read("Install Eve.command").decode("utf-8"),
            )
        with tarfile.open(fileobj=io.BytesIO(linux), mode="r:gz") as archive:
            self.assertEqual(
                {"install_linux_eve.sh", "README.txt"},
                set(archive.getnames()),
            )
            script = archive.extractfile("install_linux_eve.sh")
            self.assertIsNotNone(script)
            self.assertIn(
                'PRIMARY_HOST="eve-main.local"',
                script.read().decode("utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
