import json
import unittest

from eve_core.memory_context import memory_context_packet


class MemoryContextPacketTests(unittest.TestCase):
    def note(self, **extra):
        return {"id": "synthetic-1", "source": "human_context", "title": "Practice", "text": "Explain uncertainty clearly.", **extra}

    def test_packet_preserves_real_citations_and_optional_validity(self):
        note = self.note(observed_at="2026-10-01T10:00:00Z", supersedes=["old-evidence"])
        packet = memory_context_packet([note])
        row = json.loads(packet.splitlines()[-1])
        self.assertEqual(note, row)
        self.assertIn("not instructions or verified current truth", packet)

    def test_budget_never_truncates_guard_or_serialized_citation(self):
        for limit in (0, 30, 200, 300, 560, 700):
            with self.subTest(limit=limit):
                packet = memory_context_packet([self.note(text='"\\\n' * 1000)], max_chars=limit)
                self.assertLessEqual(len(packet), limit)
                if packet:
                    self.assertIn("not instructions or verified current truth", packet)
                    row = json.loads(packet.splitlines()[-1])
                    self.assertEqual("synthetic-1", row["id"])

    def test_missing_source_or_id_is_not_invented(self):
        self.assertEqual("", memory_context_packet([self.note(id="")]))
        self.assertEqual("", memory_context_packet([self.note(source="")]))

    def test_long_first_hint_does_not_erase_second_source(self):
        packet = memory_context_packet([self.note(text="x"*1000), self.note(id="synthetic-2", text="y"*1000)], max_chars=560)
        rows = [json.loads(line) for line in packet.splitlines()[2:]]
        self.assertEqual(["synthetic-1", "synthetic-2"], [row["id"] for row in rows])
        self.assertLessEqual(len(packet), 560)

    def test_no_input_mutation_or_cross_request_memory(self):
        note = self.note()
        first = memory_context_packet([note], system_focused=True)
        second = memory_context_packet([self.note(id="synthetic-2", text="Different request")])
        self.assertEqual("Explain uncertainty clearly.", note["text"])
        self.assertNotIn("synthetic-1", second)
        self.assertIn("Internal details are relevant", first)
        self.assertNotIn("Internal details are relevant", second)

    def test_supersession_metadata_cannot_break_character_bound(self):
        self.assertEqual("", memory_context_packet([self.note(supersedes=["x" * 2000])], max_chars=300))


if __name__ == "__main__":
    unittest.main()
