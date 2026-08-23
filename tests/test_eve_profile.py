import os
import plistlib
import tempfile
import unittest
import contextlib
import io
from pathlib import Path
from unittest.mock import patch

import eve_profile


class EveProfileTests(unittest.TestCase):
    def test_fresh_install_uses_generic_service_namespace(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                "local.eve-model-watchdog",
                eve_profile.service_label(
                    "model-watchdog",
                    namespace=eve_profile.service_namespace(discover_installed=False),
                ),
            )

    def test_environment_can_configure_user_and_service_namespace(self) -> None:
        with patch.dict(
            os.environ,
            {"EVE_USER_NAME": "Example Person", "EVE_SERVICE_NAMESPACE": "org.example.eve"},
            clear=True,
        ):
            self.assertEqual("Example Person", eve_profile.user_display_name())
            self.assertEqual("example-person", eve_profile.user_slug())
            self.assertEqual("org.example.eve.chat", eve_profile.service_label(".chat"))

    @unittest.skipUnless(eve_profile.eve_platform.is_macos(), "launchd discovery is macOS-only")
    def test_existing_daemon_label_is_discovered_without_hard_coding_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {
                "Label": "org.example.eve",
                "ProgramArguments": ["/usr/bin/python3", "/tmp/eve.py", "daemon", "run"],
            }
            with (root / "org.example.eve.plist").open("wb") as handle:
                plistlib.dump(payload, handle)
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual("org.example.eve", eve_profile.service_namespace(service_dir=root))

    def test_bundle_identifier_is_generic_and_versioned(self) -> None:
        self.assertEqual("local.eve.installer.1-2-0", eve_profile.app_bundle_identifier("Installer", "1.2.0"))

    def test_cli_prints_fresh_namespace(self) -> None:
        with patch("sys.argv", ["eve_profile.py", "namespace", "--fresh"]), contextlib.redirect_stdout(
            io.StringIO()
        ) as output:
            self.assertEqual(0, eve_profile.main())
        self.assertEqual("local.eve", output.getvalue().strip())


if __name__ == "__main__":
    unittest.main()
