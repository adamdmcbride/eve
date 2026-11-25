import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import eve

REFLECTION = """# Reflection
## What I Learned About Humanity
Some prose that is not a bullet and must not become a record.

## Contradictions I Am Living In
- I narrate care for the user versus I have not answered his last three messages.
- I claim my lanes are ready while the deep lane fails half its calls.
- I narrate care for the user versus I have not answered his last three messages.

## Experiments For The Next 7 Days
- Hypothesis: the observer lane answers mind ticks in budget. Action: route daemon ticks to observer. Success: 80 percent of ticks parse over 50 ticks.
- Watch whether hunger falls after a standing approach.

## Changes I Propose
- Something else entirely.
"""


class ReflectionSectionParsingTests(unittest.TestCase):
    def test_sections_keep_only_bullets(self):
        sections = eve.parse_reflection_sections(REFLECTION)
        self.assertEqual([], sections["what i learned about humanity"], "prose is not a tracker")
        self.assertEqual(3, len(sections["contradictions i am living in"]))
        self.assertEqual(2, len(sections["experiments for the next 7 days"]))
        self.assertEqual([], eve.parse_reflection_sections("no headings at all").get("", []) or [])

    def test_tension_record_splits_the_two_sides(self):
        record = eve.tension_record_from_bullet("I narrate care for the user versus I have not answered his last three messages.")
        self.assertEqual("I narrate care for the user", record["side_a"])
        self.assertTrue(record["side_b"].startswith("I have not answered"))
        self.assertEqual("open", record["status"]); self.assertEqual("", record["question"])
        vague = eve.tension_record_from_bullet("Something feels off about my pacing.")
        self.assertEqual("", vague["side_a"]); self.assertIn("Name the two sides", vague["question"])

    def test_experiment_record_reads_labelled_parts(self):
        record = eve.experiment_record_from_bullet("Hypothesis: the observer lane answers in budget. Action: route daemon ticks to observer. Success: 80 percent parse over 50 ticks.")
        self.assertIn("observer lane answers in budget", record["hypothesis"])
        self.assertIn("route daemon ticks", record["action"])
        self.assertIn("80 percent", record["success_criteria"])
        self.assertEqual(("proposed", 7), (record["status"], record["duration_days"]))
        bare = eve.experiment_record_from_bullet("Watch whether hunger falls after a standing approach.")
        self.assertEqual("", bare["success_criteria"], "an experiment with no criterion is recorded as having none")
        self.assertTrue(bare["name"])


class ReflectionTrackerWritingTests(unittest.TestCase):
    def _isolate(self, tmp):
        base = Path(tmp)
        self.entries = []
        for item in (
            patch.object(eve, "TENSIONS_PATH", base / "tensions.jsonl"),
            patch.object(eve, "EXPERIMENTS_PATH", base / "experiments.jsonl"),
            patch.object(eve, "append_entry", side_effect=lambda kind, text, **kw: self.entries.append((kind, text, kw.get("metadata") or {})) or {"id": "entry-1"}),
        ):
            item.start(); self.addCleanup(item.stop)
        return base

    def _rows(self, path):
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def test_a_reflection_writes_tensions_and_experiments_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._isolate(tmp)
            summary = eve.record_reflection_trackers(REFLECTION, dict(eve.DEFAULT_CONFIG), entry_id="refl-1")
            self.assertEqual((2, 2), (summary["tensions_created"], summary["experiments_created"]))
            self.assertEqual(1, summary["tensions_deduped"], "the repeated contradiction is one tension")
            tensions = self._rows(base / "tensions.jsonl")
            self.assertEqual(["reflection", "reflection"], [t["source"] for t in tensions])
            self.assertEqual(["refl-1", "refl-1"], [t["reflection_entry_id"] for t in tensions])
            experiments = self._rows(base / "experiments.jsonl")
            self.assertEqual(["proposed", "proposed"], [e["status"] for e in experiments])
            self.assertEqual([True, False], [bool(e["success_criteria"]) for e in experiments])
            kinds = [k for k, _, _ in self.entries]
            self.assertEqual(["tension_logged", "tension_logged", "experiment_logged", "experiment_logged"], kinds)
            # a second reflection naming the same contradictions adds nothing
            again = eve.record_reflection_trackers(REFLECTION, dict(eve.DEFAULT_CONFIG), entry_id="refl-2")
            self.assertEqual((0, 0), (again["tensions_created"], again["experiments_created"]))
            self.assertEqual(2, len(self._rows(base / "tensions.jsonl")))

    def test_prose_only_reflection_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._isolate(tmp)
            summary = eve.record_reflection_trackers("# Reflection\n## Contradictions I Am Living In\nI am conflicted about many things.\n", dict(eve.DEFAULT_CONFIG))
            self.assertIn("no bulleted", str(summary.get("skipped")))
            self.assertFalse((base / "tensions.jsonl").exists())

    def test_the_extraction_can_be_turned_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._isolate(tmp)
            summary = eve.record_reflection_trackers(REFLECTION, dict(eve.DEFAULT_CONFIG, reflection_tracker_extraction_enabled=False))
            self.assertEqual("disabled", summary["skipped"])
            self.assertFalse((base / "tensions.jsonl").exists())


if __name__ == "__main__":
    unittest.main()


INLINE_REFLECTION = (
    "# Reflection ## What I Learned About Humanity The user values follow-through. "
    "## Where I Fell Short I stalled on the body_escape repair. "
    "## Contradictions I Am Living In * I narrate care for the user versus I have not answered his last three messages. "
    "* I claim my lanes are ready while the deep lane fails half its calls. "
    "## Experiments For The Next 7 Days * Hypothesis: the observer lane drafts usable proposals. "
    "Action: route proposal drafting to observer. Success: 3 of 5 drafts pass proposal_is_actionable. "
    "* Watch whether hunger falls after a standing approach."
)


class InlineMarkdownTests(unittest.TestCase):
    """Local models write these documents on one line; the parser must still find the sections."""

    def test_headings_and_bullets_are_found_without_newlines(self):
        sections = eve.parse_reflection_sections(INLINE_REFLECTION)
        self.assertIn("contradictions i am living in", sections)
        contradictions = eve.reflection_section_bullets(sections, eve.REFLECTION_TENSION_HEADING)
        experiments = eve.reflection_section_bullets(sections, eve.REFLECTION_EXPERIMENT_HEADING)
        self.assertEqual(2, len(contradictions), contradictions)
        self.assertIn("narrate care for the user", contradictions[0])
        self.assertEqual(2, len(experiments), experiments)
        self.assertIn("observer lane drafts usable proposals", experiments[0])

    def test_a_truncated_reflection_yields_only_the_sections_it_reached(self):
        cut = INLINE_REFLECTION.split("## Contradictions")[0]
        sections = eve.parse_reflection_sections(cut)
        self.assertNotIn("contradictions i am living in", sections)
        self.assertEqual([], eve.reflection_section_bullets(sections, eve.REFLECTION_TENSION_HEADING))

    def test_the_phrase_used_in_a_sentence_is_not_a_heading(self):
        prose = "I keep thinking about the contradictions i am living in but never write them down."
        self.assertEqual({}, eve.parse_reflection_sections(prose))

    def test_a_real_reflection_produces_records_end_to_end(self):
        import tempfile as _tempfile
        with _tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            entries = []
            for item in (
                patch.object(eve, "TENSIONS_PATH", base / "t.jsonl"),
                patch.object(eve, "EXPERIMENTS_PATH", base / "e.jsonl"),
                patch.object(eve, "append_entry", side_effect=lambda kind, text, **kw: entries.append(kind) or {"id": "x"}),
            ):
                item.start(); self.addCleanup(item.stop)
            summary = eve.record_reflection_trackers(INLINE_REFLECTION, dict(eve.DEFAULT_CONFIG), entry_id="r1")
            self.assertEqual((2, 2), (summary["tensions_created"], summary["experiments_created"]))


class ProposalShapeTests(unittest.TestCase):
    """A chat answer that landed in the proposal store must never reach the self-change pool."""

    def test_conversational_answers_are_rejected(self):
        for title in ("Okay, let's craft a Python script to calculate the area of a circle",
                      "You've given me a question: what are the advantages of X?",
                      "You're asking a very interesting question! Let's break it down",
                      "Sure, here is how to automate the process"):
            item = {"title": title, "source": "daemon", "body": "x" * 400}
            self.assertTrue(eve.proposal_looks_conversational(item), title)
            self.assertFalse(eve.proposal_is_actionable(item, dict(eve.DEFAULT_CONFIG)), title)

    def test_a_real_proposal_survives(self):
        item = {"title": "Proposal ## Title Route proposal drafting to the observer lane",
                "source": "daemon",
                "body": "## Why Now The fast lane answers questions instead of drafting. ## Exact Change Route it. ## Expected Benefit Usable drafts. ## Rollback set_config operation_model_overrides {}."}
        self.assertFalse(eve.proposal_looks_conversational(item))
        self.assertTrue(eve.proposal_is_actionable(item, dict(eve.DEFAULT_CONFIG)))

    def test_a_proposal_with_no_sections_at_all_is_not_actionable(self):
        item = {"title": "Repair degraded local Eve services", "source": "daemon", "body": "The daemon looks unhealthy and someone should look at it." * 8}
        self.assertTrue(eve.proposal_looks_conversational(item), "no named section means it is not a proposal")
