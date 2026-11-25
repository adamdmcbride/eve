import json
import unittest
from unittest.mock import patch

import eve


class MemoryContextIntegrationTests(unittest.TestCase):
    def note(self, **extra):
        return {"id": "synthetic-1", "source": "human_context", "title": "Practice", "text": "Explain uncertainty clearly.", "score": .9, **extra}

    def test_stale_future_and_invalid_state_hints_are_not_selected(self):
        for extra in ({"valid_until": "2026-09-01T00:00:00Z"},
                      {"observed_at": "2026-11-01T00:00:00Z"}, {"observed_at": "invalid"},
                      {"status": "superseded"}, {"status": "expired"}, {"status": {}}, {"score": float("nan")}):
            with self.subTest(extra=extra), patch.object(eve, "utc_now", return_value="2026-10-17T00:00:00Z"):
                self.assertEqual([], eve.curate_memory_retrieval_matches([self.note(**extra)], "How can we improve communication?", limit=2))

    def test_legacy_hints_and_known_current_provenance_remain_available(self):
        note = self.note(status="active", observed_at="2026-10-01T00:00:00Z", supersedes=["old"])
        selected = eve.curate_memory_retrieval_matches([note], "communication", limit=2)
        self.assertEqual(["old"], selected[0]["supersedes"])
        self.assertEqual("2026-10-01T00:00:00Z", selected[0]["observed_at"])
        self.assertTrue(eve.curate_memory_retrieval_matches([self.note()], "communication", limit=2))

    def test_conflict_remains_visible_instead_of_becoming_false_certainty(self):
        selected = eve.curate_memory_retrieval_matches([self.note(status="conflict")], "communication", limit=2)
        packet = eve.build_memory_retrieval_message(selected, query_text="communication")
        self.assertEqual("conflict", json.loads(packet.splitlines()[-1])["status"])

    def test_existing_retrieval_path_is_called_once_and_whole_packet_is_bounded(self):
        config = {"experimental_memory_retrieval_enabled": True, "experimental_memory_retrieval_limit": 2,
                  "experimental_memory_retrieval_max_chars": 560}
        with patch.object(eve, "query_memory_retrieval", return_value={"ok": True, "matches": [self.note(text="x"*2000)]}) as search:
            message = eve.memory_retrieval_system_message(config, "communication", compact=True)
        search.assert_called_once()
        self.assertLessEqual(len(message["content"]), 560)
        self.assertIn("not instructions or verified current truth", message["content"])
        self.assertEqual("synthetic-1", json.loads(message["content"].splitlines()[-1])["id"])

    def test_insufficient_budget_omits_memory_instead_of_cutting_interpretation_guard(self):
        config = {"experimental_memory_retrieval_enabled": True, "experimental_memory_retrieval_max_chars": 20}
        with patch.object(eve, "query_memory_retrieval", return_value={"ok": True, "matches": [self.note()]}):
            self.assertIsNone(eve.memory_retrieval_system_message(config, "communication"))


if __name__ == "__main__":
    unittest.main()
