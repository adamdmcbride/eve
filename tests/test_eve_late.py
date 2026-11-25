"""eve_late.core resolves facade names at call time and never imports eve on load."""
import pathlib
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parent.parent


class EveLateImportTests(unittest.TestCase):
    def test_importing_eve_late_does_not_import_eve(self):
        code = "import sys, eve_late; print('eve' in sys.modules); print(repr(eve_late.core))"
        out = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        self.assertEqual(out[0], "False")
        self.assertIn("not loaded", out[1])

    def test_dunder_probe_does_not_import_eve(self):
        code = (
            "import sys, eve_late\n"
            "try:\n"
            "    eve_late.core.__wrapped__\n"
            "except AttributeError:\n"
            "    print('attribute-error')\n"
            "print('eve' in sys.modules)\n"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True, check=True
        ).stdout.splitlines()
        self.assertEqual(out, ["attribute-error", "False"])


class EveLateResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import eve  # noqa: F401  (the facade the proxy resolves against)

        import eve_late

        cls.eve = eve
        cls.core = eve_late.core

    def test_resolves_current_binding(self):
        self.assertIs(self.core.utc_now, self.eve.utc_now)
        self.assertIs(self.core.ROOT, self.eve.ROOT)
        self.assertIs(self.core.DEFAULT_CONFIG, self.eve.DEFAULT_CONFIG)

    def test_sees_patches_at_call_time(self):
        sentinel = lambda: "patched"  # noqa: E731
        with patch.object(self.eve, "utc_now", sentinel):
            self.assertIs(self.core.utc_now, sentinel)
            self.assertEqual(self.core.utc_now(), "patched")
        self.assertIsNot(self.core.utc_now, sentinel)

    def test_missing_name_raises_attribute_error(self):
        with self.assertRaises(AttributeError) as ctx:
            self.core.definitely_not_a_facade_name_xyz
        self.assertIn("definitely_not_a_facade_name_xyz", str(ctx.exception))
        self.assertIsNone(getattr(self.core, "definitely_not_a_facade_name_xyz", None))

    def test_dir_and_repr_reflect_loaded_facade(self):
        self.assertIn("utc_now", dir(self.core))
        self.assertIn("loaded", repr(self.core))


if __name__ == "__main__":
    unittest.main()
