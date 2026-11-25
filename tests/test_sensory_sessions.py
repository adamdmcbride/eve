import ast
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import eve_sensory_sessions
import eve_web


ROOT = Path(__file__).resolve().parents[1]


class SensorySessionServiceBoundaryTests(unittest.TestCase):
    def test_runtime_service_composes_one_session_owner(self):
        service = eve_web.EveRuntimeService()

        self.assertIsInstance(
            service._sensory_session_service,
            eve_sensory_sessions.SensorySessionService,
        )
        self.assertIs(
            service._sensory_sessions,
            service._sensory_session_service._sensory_sessions,
        )
        self.assertIs(
            service._sensory_sessions_lock,
            service._sensory_session_service._sensory_sessions_lock,
        )

    def test_sensory_module_does_not_import_http_service(self):
        tree = ast.parse((ROOT / "eve_sensory_sessions.py").read_text(encoding="utf-8"))
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

        self.assertNotIn("eve_web", imported_modules)
        self.assertFalse(
            any(module.startswith("http") for module in imported_modules),
            imported_modules,
        )

    def test_composition_policy_preserves_legacy_patch_seam(self):
        with (
            patch.object(eve_web, "SENSORY_SESSION_MIN_SECONDS", 11),
            patch.object(eve_web, "SENSORY_SESSION_MAX_SECONDS", 22),
            patch.object(eve_web, "SENSORY_SESSION_MAX_BATCHES_PER_10_SECONDS", 3),
            patch.object(eve_web, "SENSORY_SESSION_MAX_EVENTS", 4),
            patch.object(eve_web, "SENSORY_SESSION_MAX_ACTIVE", 1),
            patch.object(eve_web, "SENSORY_SESSION_MODALITIES", {"visual"}),
        ):
            policy = eve_web._sensory_session_policy()

        self.assertEqual(11, policy.min_seconds)
        self.assertEqual(22, policy.max_seconds)
        self.assertEqual(3, policy.max_batches_per_10_seconds)
        self.assertEqual(4, policy.max_events)
        self.assertEqual(1, policy.max_active)
        self.assertEqual(frozenset({"visual"}), policy.modalities)

    def test_policy_snapshot_is_immutable(self):
        policy = eve_web._sensory_session_policy()

        with self.assertRaises(FrozenInstanceError):
            policy.max_events = 1

    def test_public_projection_excludes_session_secret_material(self):
        public = eve_sensory_sessions.SensorySessionService._public_sensory_session(
            {
                "session_id": "sensory-1",
                "token_hash": "private-hash",
                "session_token": "private-token",
                "created_at": "2026-08-24T00:00:00+00:00",
                "expires_at": "2026-08-24T00:01:00+00:00",
                "status": "active",
                "modalities": ["auditory"],
                "purpose": "bounded sensing",
                "accepted_events": 0,
            }
        )

        self.assertNotIn("token_hash", public)
        self.assertNotIn("session_token", public)
        self.assertEqual("features_only", public["privacy"]["persistence"])
        self.assertEqual("observation_only", public["authority"])


if __name__ == "__main__":
    unittest.main()
