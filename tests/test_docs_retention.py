import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("eve_docs_retention", ROOT / "bin" / "eve_docs_retention.py")
eve_docs_retention = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = eve_docs_retention
SPEC.loader.exec_module(eve_docs_retention)


class DocsRetentionTests(unittest.TestCase):
    def test_hermes_profile_skills_plan_and_apply_archives_old_copies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "eve.py").write_text("# stub\n", encoding="utf-8")
            (root / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
            canonical = root / "canonical" / "skills"
            canonical.mkdir(parents=True)
            (canonical / "SKILL.md").write_text("# canonical\n", encoding="utf-8")
            profiles = root / ".eve" / "hermes_runs" / "profiles"
            old = profiles / "old-run"
            newest = profiles / "new-run"
            for profile in (old, newest):
                skills = profile / "skills" / "research"
                skills.mkdir(parents=True)
                (skills / "SKILL.md").write_text(f"# {profile.name}\n", encoding="utf-8")
            (root / ".eve" / "hermes_runs" / "latest.json").write_text(
                '{"temp_profile_home":"%s"}' % newest,
                encoding="utf-8",
            )

            plan = eve_docs_retention.build_hermes_skill_archive_plan(root, keep_latest=0, canonical_skills_dir=canonical)
            self.assertEqual(1, plan["totals"]["candidate_profiles"])
            self.assertEqual("old-run", plan["candidates"][0]["profile"])
            self.assertEqual("new-run", plan["protected"][0]["profile"])

            result = eve_docs_retention.apply_hermes_skill_archive_plan(plan)

            self.assertEqual(1, result["changed"])
            self.assertTrue((old / "skills").is_symlink())
            self.assertEqual(canonical.resolve(), (old / "skills").resolve())
            self.assertTrue(Path(plan["candidates"][0]["archive_path"]).exists())
            self.assertTrue(Path(plan["candidates"][0]["manifest_path"]).exists())
            self.assertFalse((newest / "skills").is_symlink())

    def test_latest_protection_ignores_already_symlinked_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "eve.py").write_text("# stub\n", encoding="utf-8")
            (root / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
            canonical = root / "canonical" / "skills"
            canonical.mkdir(parents=True)
            profiles = root / ".eve" / "hermes_runs" / "profiles"
            for name in ("older-real", "latest-real", "already-symlinked"):
                skills = profiles / name / "skills"
                skills.mkdir(parents=True)
                (skills / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
            symlinked = profiles / "already-symlinked" / "skills"
            shutil_target = canonical
            import shutil
            shutil.rmtree(symlinked)
            symlinked.symlink_to(shutil_target, target_is_directory=True)

            plan = eve_docs_retention.build_hermes_skill_archive_plan(root, keep_latest=1, canonical_skills_dir=canonical)

            self.assertEqual(["older-real"], [item["profile"] for item in plan["candidates"]])
            self.assertEqual(["latest-real"], [item["profile"] for item in plan["protected"]])
            self.assertIn("skills_already_symlink", [item["reason"] for item in plan["skipped"]])

    def test_latest_profile_can_be_archived_when_explicitly_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "eve.py").write_text("# stub\n", encoding="utf-8")
            (root / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
            canonical = root / "canonical" / "skills"
            canonical.mkdir(parents=True)
            (canonical / "SKILL.md").write_text("# canonical\n", encoding="utf-8")
            latest = root / ".eve" / "hermes_runs" / "profiles" / "latest-run"
            skills = latest / "skills" / "research"
            skills.mkdir(parents=True)
            (skills / "SKILL.md").write_text("# copied latest\n", encoding="utf-8")
            (root / ".eve" / "hermes_runs" / "latest.json").write_text(
                '{"temp_profile_home":"%s"}' % latest,
                encoding="utf-8",
            )

            protected_plan = eve_docs_retention.build_hermes_skill_archive_plan(
                root,
                keep_latest=0,
                canonical_skills_dir=canonical,
            )
            archive_plan = eve_docs_retention.build_hermes_skill_archive_plan(
                root,
                keep_latest=0,
                canonical_skills_dir=canonical,
                protect_latest_profile=False,
            )

            self.assertEqual(["latest-run"], [item["profile"] for item in protected_plan["protected"]])
            self.assertEqual([], protected_plan["candidates"])
            self.assertEqual(["latest-run"], [item["profile"] for item in archive_plan["candidates"]])
            self.assertEqual([], archive_plan["protected"])

            result = eve_docs_retention.apply_hermes_skill_archive_plan(archive_plan)

            self.assertEqual(1, result["changed"])
            self.assertTrue((latest / "skills").is_symlink())
            self.assertEqual(canonical.resolve(), (latest / "skills").resolve())



if __name__ == "__main__":
    unittest.main()
