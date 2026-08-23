import contextlib
import io
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import importlib.util

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("eve_docs_audit", ROOT / "bin" / "eve_docs_audit.py")
eve_docs_audit = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(eve_docs_audit)


class DocsAuditTests(unittest.TestCase):
    def test_normalize_doc_ref_accepts_any_checkout_root(self):
        self.assertEqual(
            "architecture/example.md",
            eve_docs_audit.normalize_doc_ref("/Users/example/Projects/Eve/docs/architecture/example.md"),
        )

    def test_parse_status_block_requires_authority_fields_near_top(self):
        text = """# Example\n\nStatus: canonical\nLast reviewed: 2026-06-13\nCurrent authority: yes\nSupersedes: none\nSuperseded by: none\n\nBody\n"""

        status = eve_docs_audit.parse_status_block(text)

        self.assertEqual(status["Status"], "canonical")
        self.assertEqual(eve_docs_audit.status_missing_keys(status), [])


    def test_duplicate_status_keys_keep_first_value_and_emit_finding(self):
        text = """# Example

Status: canonical
Last reviewed: 2026-06-13
Current authority: yes
Supersedes: none
Superseded by: none

Last reviewed: 2026-05-06
"""

        status = eve_docs_audit.parse_status_block(text)
        duplicates = eve_docs_audit.duplicate_status_keys(text)

        self.assertEqual("2026-06-13", status["Last reviewed"])
        self.assertEqual([{"key": "Last reviewed", "first_line": 4, "line": 9}], duplicates)

    def test_structural_findings_flag_root_crowding_and_wide_shelves(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp) / "docs"
            docs.mkdir()
            shelf_lines = "\n".join(f"- `DOC_{i}.md` — item." for i in range(13))
            (docs / "README.md").write_text(
                "# Map\n\nStatus: canonical\nLast reviewed: 2026-06-13\nCurrent authority: yes\nSupersedes: none\nSuperseded by: none\n\n### Operating baselines and evidence logs\n\n" + shelf_lines + "\n",
                encoding="utf-8",
            )
            for i in range(13):
                (docs / f"DOC_{i}.md").write_text(
                    f"# Doc {i}\n\nStatus: evidence-log\nLast reviewed: 2026-06-13\nCurrent authority: partial\nSupersedes: none\nSuperseded by: none\n",
                    encoding="utf-8",
                )

            report = eve_docs_audit.audit_docs(docs)

        finding_ids = {finding["id"] for finding in report["findings"]}
        self.assertIn("docs.root_crowding", finding_ids)
        self.assertIn("docs.wide_front_door_shelf", finding_ids)

    def test_front_door_shelves_cover_exact_and_umbrella_docs(self):
        text = """# Map

### Canonical doctrine: current source of truth

- `EVE_CORE.md` — core.
- `model_lanes/README.md` plus lane files — lanes.

### Active roadmaps and staged tracks

- `roadmaps/README.md` plus roadmap files — roadmaps.

### Operating manuals and domain doctrine

- `operating/README.md` plus operating docs — manuals.
- `evals/README.md` plus eval docs — evals.

### Operating baselines and evidence logs

- `evidence/README.md` plus evidence files — evidence.

### Historical research and idea capture

- `archive/historical/AUTORESEARCH_UPSTREAM_SCOUT_2026_04_27.md`
"""

        shelves = eve_docs_audit.parse_front_door_shelves(text)

        self.assertEqual(shelves["EVE_CORE.md"], "canonical")
        self.assertEqual(eve_docs_audit.umbrella_shelf("model_lanes/fast.md", shelves), "canonical")
        self.assertEqual(eve_docs_audit.umbrella_shelf("roadmaps/CONSCIOUSNESS_ROADMAP.md", shelves), "active-roadmap")
        self.assertEqual(eve_docs_audit.umbrella_shelf("evidence/MODEL_TEST_LOG.md", shelves), "evidence-log")
        self.assertEqual(eve_docs_audit.umbrella_shelf("operating/CODEX_CAPABILITY_BRIDGE.md", shelves), "operating-manual")
        self.assertEqual(eve_docs_audit.umbrella_shelf("evals/HIDDEN_TEST_GOVERNANCE.md", shelves), "operating-manual")
        self.assertEqual(
            eve_docs_audit.umbrella_shelf("archive/historical/AUTORESEARCH_UPSTREAM_SCOUT_2026_04_27.md", shelves),
            "archive",
        )

    def test_audit_reports_missing_status_without_failing_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp) / "docs"
            docs.mkdir()
            (docs / "README.md").write_text(
                """# Eve Documentation Map\n\nStatus: canonical\nLast reviewed: 2026-06-13\nCurrent authority: yes\nSupersedes: none\nSuperseded by: none\n\n### Canonical doctrine: current source of truth\n\n- `CURRENT.md` — current.\n\n### Historical audits\n\n- `OLD.md` — old.\n""",
                encoding="utf-8",
            )
            (docs / "CURRENT.md").write_text(
                """# Current\n\nStatus: active\nLast reviewed: 2026-06-13\nCurrent authority: partial\nSupersedes: none\nSuperseded by: none\n""",
                encoding="utf-8",
            )
            (docs / "OLD.md").write_text("# Old\n\nOld note.\n", encoding="utf-8")

            report = eve_docs_audit.audit_docs(docs)

        self.assertTrue(report["ok"])
        self.assertEqual(report["error_count"], 0)
        self.assertEqual(report["warning_count"], 1)
        self.assertEqual(report["status_counts"]["missing"], 1)
        self.assertEqual(report["shelf_counts"]["historical-audit"], 1)
        self.assertEqual(report["findings"][0]["id"], "docs.missing_status_block")

    def test_main_can_fail_on_warning_for_ci_canaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp) / "docs"
            docs.mkdir()
            (docs / "README.md").write_text("# Map\n\nStatus: canonical\n", encoding="utf-8")

            with contextlib.redirect_stdout(io.StringIO()):
                code = eve_docs_audit.main(["--docs-dir", str(docs), "--fail-on-warning"])

        self.assertEqual(code, 1)

    def test_repo_noise_audit_classifies_generated_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "eve.py").write_text("# stub\n", encoding="utf-8")
            (root / "docs").mkdir()
            (root / "docs" / "README.md").write_text("# Docs\n", encoding="utf-8")
            (root / "PROJECT_MEMORY.md").write_text("# Memory\n", encoding="utf-8")
            prompts = root / "prompts"
            prompts.mkdir()
            (prompts / "user_message_reply.md").write_text("# Prompt\n", encoding="utf-8")
            generated = root / ".eve" / "hermes_runs" / "profiles" / "run" / "skills"
            generated.mkdir(parents=True)
            (generated / "README.md").write_text("# copied skill\n", encoding="utf-8")
            memory = root / "openclaw" / "memory"
            memory.mkdir(parents=True)
            (memory / "2026-04-25.md").write_text("# runtime memory\n", encoding="utf-8")

            report = eve_docs_audit.audit_repo_noise(root, largest_limit=5)

        self.assertEqual(report["total_markdown"], 5)
        self.assertEqual(report["category_counts"]["curated-docs"], 1)
        self.assertEqual(report["category_counts"]["root-operator-surfaces"], 1)
        self.assertEqual(report["category_counts"]["prompt-assets"], 1)
        self.assertEqual(report["category_counts"]["generated-hermes-profile-copies"], 1)
        self.assertEqual(report["category_counts"]["openclaw-runtime-memory"], 1)
        self.assertEqual(report["generated_or_runtime_markdown"], 2)
        self.assertTrue(any(item["category"] == "openclaw-runtime-memory" for item in report["largest_noise"]))

    def test_repo_noise_audit_summarizes_tracked_non_doc_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "eve.py").write_text("# stub\n", encoding="utf-8")
            (root / "docs").mkdir()
            (root / "docs" / "README.md").write_text("# Docs\n", encoding="utf-8")
            (root / "README.md").write_text("# Root\n", encoding="utf-8")
            prompts = root / "prompts"
            prompts.mkdir()
            (prompts / "tool_use.md").write_text("# Tool use prompt\n", encoding="utf-8")
            openclaw_skill = root / "openclaw" / "skills" / "eve_capability_use"
            openclaw_skill.mkdir(parents=True)
            (openclaw_skill / "SKILL.md").write_text("# Skill\n", encoding="utf-8")
            (root / "openclaw" / "SOUL.md").write_text("# Sidecar soul\n", encoding="utf-8")
            openclaw_hook = root / "openclaw" / "hooks" / "eve-evidence-ingest"
            openclaw_hook.mkdir(parents=True)
            (openclaw_hook / "HOOK.md").write_text("# Hook\n", encoding="utf-8")

            with mock.patch.object(
                eve_docs_audit,
                "git_tracked_paths",
                return_value={
                    "docs/README.md",
                    "README.md",
                    "prompts/tool_use.md",
                    "openclaw/SOUL.md",
                    "openclaw/hooks/eve-evidence-ingest/HOOK.md",
                    "openclaw/skills/eve_capability_use/SKILL.md",
                },
            ):
                report = eve_docs_audit.audit_repo_noise(root, largest_limit=10)

        self.assertEqual(report["tracked_non_doc_markdown"], 5)
        self.assertEqual(report["tracked_non_doc_counts"]["root-operator-surfaces"], 1)
        self.assertEqual(report["tracked_non_doc_counts"]["prompt-assets"], 1)
        self.assertEqual(report["tracked_non_doc_counts"]["openclaw-sidecar-docs"], 2)
        self.assertEqual(report["tracked_non_doc_counts"]["openclaw-skills"], 1)
        guidance = {item["category"]: item["guidance"] for item in report["tracked_non_doc_guidance"]}
        self.assertIn("docs/README.md", guidance["root-operator-surfaces"])
        self.assertIn("openclaw/AGENTS.md", guidance["openclaw-sidecar-docs"])

    def test_docs_triage_explains_curated_docs_vs_runtime_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "eve.py").write_text("# stub\n", encoding="utf-8")
            docs = root / "docs"
            docs.mkdir()
            (docs / "README.md").write_text(
                "# Eve Documentation Map\n\nStatus: canonical\nLast reviewed: 2026-06-14\nCurrent authority: yes\nSupersedes: none\nSuperseded by: none\n",
                encoding="utf-8",
            )
            memory = root / "openclaw" / "memory"
            memory.mkdir(parents=True)
            (memory / "2026-04-25.md").write_text("# runtime memory\n", encoding="utf-8")
            generated = root / ".eve" / "hermes_runs" / "profiles" / "run" / "skills"
            generated.mkdir(parents=True)
            (generated / "README.md").write_text("# copied skill\n", encoding="utf-8")

            docs_report = eve_docs_audit.audit_docs(docs)
            repo_noise = eve_docs_audit.audit_repo_noise(root, largest_limit=4)
            triage = eve_docs_audit.build_docs_triage(root, docs_report, repo_noise, largest_limit=4)
            text = eve_docs_audit.format_triage_report(triage)

        self.assertEqual(triage["curated_docs"], 1)
        self.assertEqual(triage["generated_or_runtime_markdown"], 2)
        self.assertIn("docs/README.md", triage["start_here"])
        self.assertIn("Why it feels like gibberish", text)
        self.assertIn("openclaw/memory/**", text)
        self.assertIn("Do not delete historical evidence", text)

    def test_main_triage_prints_human_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "eve.py").write_text("# stub\n", encoding="utf-8")
            docs = root / "docs"
            docs.mkdir()
            (docs / "README.md").write_text(
                "# Eve Documentation Map\n\nStatus: canonical\nLast reviewed: 2026-06-14\nCurrent authority: yes\nSupersedes: none\nSuperseded by: none\n",
                encoding="utf-8",
            )

            with mock.patch.object(eve_docs_audit, "repo_root_from", return_value=root):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    code = eve_docs_audit.main(["--triage", "--largest-noise", "2"])

        self.assertEqual(code, 0)
        self.assertIn("Eve docs triage", stdout.getvalue())
        self.assertIn("Start here:", stdout.getvalue())

    def test_repo_noise_audit_classifies_openclaw_root_sidecar_markdown(self):
        self.assertEqual(
            eve_docs_audit.classify_repo_markdown("openclaw/AGENTS.md")["category"],
            "openclaw-sidecar-docs",
        )
        self.assertEqual(
            eve_docs_audit.classify_repo_markdown("openclaw/DREAMS.md")["category"],
            "openclaw-sidecar-docs",
        )
        self.assertEqual(
            eve_docs_audit.classify_repo_markdown("openclaw/hooks/eve-evidence-ingest/HOOK.md")["category"],
            "openclaw-sidecar-docs",
        )
        self.assertEqual(
            eve_docs_audit.classify_repo_markdown("openclaw/memory/2026-04-25.md")["category"],
            "openclaw-runtime-memory",
        )
        self.assertEqual(
            eve_docs_audit.classify_repo_markdown("openclaw/skills/eve_capability_use/SKILL.md")["category"],
            "openclaw-skills",
        )
        self.assertIn(
            "not canonical Eve doctrine",
            eve_docs_audit.classify_repo_markdown("openclaw/DREAMS.md")["recommendation"],
        )


if __name__ == "__main__":
    unittest.main()
