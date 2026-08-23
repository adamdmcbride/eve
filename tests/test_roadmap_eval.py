import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import eve
import eve_store


class RoadmapEvalTests(unittest.TestCase):
    def test_calendar_capability_gaps_share_duplicate_key(self):
        first = {
            "goal": "Find or create a local tool path for the requested action.",
            "commitment_text": "I'll give myself the ability to control the calendar app directly.",
        }
        second = {
            "goal": "Create a verified capability path for: I'll teach myself to control Calendar from Eve.",
        }

        self.assertEqual(eve.roadmap_capability_gap_key(first), "calendar_control")
        self.assertEqual(eve.roadmap_capability_gap_key(second), "calendar_control")

    def test_calendar_read_gap_is_inactive_after_supported_action_exists(self):
        gap = {
            "status": "planned",
            "goal": "Create a verified capability path for: I will check your Calendar now.",
            "commitment_text": "I will check your Calendar now.",
        }

        self.assertFalse(eve.capability_gap_is_active(gap))

    def test_system_observation_commitment_maps_to_service_health_check(self):
        response = (
            "I’ll focus on observing the systems themselves. Let’s start with a quick scan "
            "of the core components — the five lanes. Would you like me to run a diagnostic sweep?"
        )

        self.assertEqual(eve.classify_supported_reply_commitment(response), "service_health_check")

    def test_system_observation_gap_is_inactive_after_supported_action_exists(self):
        gap = {
            "status": "planned",
            "goal": (
                "Create a verified capability path for: Given that, and considering our ongoing effort "
                "to build a more grounded understanding of myself, I’ll focus on observing the systems themselves."
            ),
            "commitment_text": (
                "Given that, and considering our ongoing effort to build a more grounded understanding of myself, "
                "I’ll focus on observing the systems themselves."
            ),
            "draft_response": (
                "Let’s start with a quick scan of the core components – the five lanes. "
                "Are there any particular areas of concern, or would you like me to just run a diagnostic sweep?"
            ),
        }

        self.assertFalse(eve.capability_gap_is_active(gap))

    def test_eval_gap_is_superseded_by_newer_passing_whole_system_check(self):
        gap = {
            "id": "gap-1",
            "test_id": "runtime.daemon",
            "created_at": "2026-04-24T00:00:00+00:00",
        }
        latest = {
            "passed_test_ids": ["runtime.daemon"],
            "finished_at": "2026-04-24T00:01:00+00:00",
        }

        self.assertTrue(eve.eval_gap_superseded_by_latest_whole_system(gap, latest))

    def test_eval_gap_newer_than_latest_check_stays_active(self):
        gap = {
            "id": "gap-1",
            "test_id": "runtime.daemon",
            "created_at": "2026-04-24T00:02:00+00:00",
        }
        latest = {
            "passed_test_ids": ["runtime.daemon"],
            "finished_at": "2026-04-24T00:01:00+00:00",
        }

        self.assertFalse(eve.eval_gap_superseded_by_latest_whole_system(gap, latest))

    def test_format_roadmap_eval_report_names_first_priority(self):
        report = {
            "status": "degraded",
            "generated_at": "2026-04-26T00:00:00+00:00",
            "recommended_first_priority": {
                "priority": 0,
                "title": "Roadmap, backlog, and evidence hygiene",
            },
            "whole_system": {"status": "degraded", "average_score": 4.47, "failing_check_count": 5},
            "backlog": {"active_proposals": 2, "open_system_tasks": 1, "open_capability_gaps": 1, "latest_eval_gaps": 1},
            "warnings": ["duplicate proposal group"],
            "priority_queue": [],
        }

        formatted = eve.format_roadmap_eval_report(report)

        self.assertIn("first_priority: P0 Roadmap, backlog, and evidence hygiene", formatted)
        self.assertIn("duplicate proposal group", formatted)

    def test_cleanup_duplicate_groups_keep_latest_record(self):
        groups = eve.roadmap_cleanup_duplicate_groups(
            [
                {"id": "old", "status": "draft", "title": "Repair duplicated work", "updated_at": "2026-04-25T00:00:00+00:00"},
                {"id": "new", "status": "draft", "title": "Repair duplicated work", "updated_at": "2026-04-26T00:00:00+00:00"},
                {"id": "archived", "status": "archived", "title": "Repair duplicated work", "updated_at": "2026-04-27T00:00:00+00:00"},
            ],
            fields=["title"],
            inactive_statuses={"archived"},
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["canonical_id"], "new")
        self.assertEqual(groups[0]["archive_ids"], ["old"])

    def test_superseded_eval_gap_candidates_skip_marked_records(self):
        candidates = eve.roadmap_superseded_eval_gap_candidates(
            [
                {
                    "id": "already-marked",
                    "test_id": "memory.retrieval_index",
                    "created_at": "2026-04-25T00:00:00+00:00",
                    "superseded_at": "2026-04-26T00:00:00+00:00",
                }
            ],
            {
                "passed_test_ids": ["memory.retrieval_index"],
                "finished_at": "2026-04-26T01:00:00+00:00",
            },
        )

        self.assertEqual(candidates, [])

    def test_superseded_eval_gap_candidates_follow_canonical_predicate(self):
        candidates = eve.roadmap_superseded_eval_gap_candidates(
            [
                {
                    "id": "old-passed",
                    "test_id": "memory.retrieval_index",
                    "layer": "memory_continuity",
                    "created_at": "2026-04-25T00:00:00+00:00",
                },
                {
                    "id": "newer-than-latest",
                    "test_id": "runtime.daemon",
                    "layer": "runtime_infrastructure",
                    "created_at": "2026-04-26T02:00:00+00:00",
                },
                {
                    "id": "still-failing",
                    "test_id": "self_world.user_manual_probe",
                    "layer": "self_world_boundary",
                    "created_at": "2026-04-25T00:00:00+00:00",
                },
            ],
            {
                "passed_test_ids": ["memory.retrieval_index", "runtime.daemon"],
                "finished_at": "2026-04-26T01:00:00+00:00",
            },
        )

        self.assertEqual([candidate["id"] for candidate in candidates], ["old-passed"])
        self.assertEqual(candidates[0]["reason"], "latest whole-system check now passes this test_id")

    def test_roadmap_cleanup_prefers_live_runtime_backlog_without_dropping_runtime_only_records(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_app = root / "source" / ".eve"
            runtime_app = root / "runtime" / ".eve"
            source_app.mkdir(parents=True)
            runtime_app.mkdir(parents=True)
            source_tasks = source_app / "system_tasks.jsonl"
            runtime_tasks = runtime_app / "system_tasks.jsonl"
            proposals = source_app / "proposals.jsonl"
            capability_gaps = source_app / "capability_gaps.jsonl"
            eval_gaps = source_app / "eval_gaps.jsonl"
            cleanup_audit = source_app / "roadmap_cleanup_audit.jsonl"
            runtime_cleanup_audit = runtime_app / "roadmap_cleanup_audit.jsonl"

            eve_store.write_jsonl_records(
                source_tasks,
                [
                    {
                        "id": "source-stale-duplicate",
                        "status": "planned",
                        "title": "Escalate only unresolved work from CPU to GPU",
                        "updated_at": "2026-05-01T00:00:00+00:00",
                    }
                ],
            )
            eve_store.write_jsonl_records(
                runtime_tasks,
                [
                    {
                        "id": "runtime-duplicate",
                        "status": "planned",
                        "title": "Escalate only unresolved work from CPU to GPU",
                        "updated_at": "2026-05-20T00:00:00+00:00",
                    },
                    {
                        "id": "runtime-canonical",
                        "status": "planned",
                        "title": "Escalate only unresolved work from CPU to GPU",
                        "updated_at": "2026-05-21T00:00:00+00:00",
                    },
                    {
                        "id": "runtime-only",
                        "status": "planned",
                        "title": "Keep newer runtime-only work",
                        "updated_at": "2026-05-22T00:00:00+00:00",
                    },
                ],
            )
            for path in (proposals, capability_gaps, eval_gaps):
                eve_store.write_jsonl_records(path, [])
            eve_store.write_jsonl_records(runtime_cleanup_audit, [{"id": "runtime-existing-audit"}])

            with patch.object(eve, "APP_DIR", source_app), patch.object(
                eve, "RUNTIME_APP_DIR", runtime_app
            ), patch.object(eve, "SYSTEM_TASKS_PATH", source_tasks), patch.object(
                eve, "PROPOSALS_PATH", proposals
            ), patch.object(
                eve, "CAPABILITY_GAPS_PATH", capability_gaps
            ), patch.object(
                eve, "EVAL_GAPS_PATH", eval_gaps
            ), patch.object(
                eve, "ROADMAP_CLEANUP_AUDIT_LOG_PATH", cleanup_audit
            ), patch.object(
                eve, "daemon_runtime_running", return_value=True
            ), patch.object(
                eve, "running_from_runtime_bundle", return_value=False
            ), patch.object(
                eve,
                "summarize_latest_whole_system_for_roadmap",
                return_value={"passed_test_ids": [], "finished_at": "2026-05-23T00:00:00+00:00"},
            ):
                plan = eve.build_roadmap_cleanup_plan(prefer_runtime=True)

                self.assertEqual(plan["system_task_duplicate_groups"][0]["canonical_id"], "runtime-canonical")

                applied = eve.apply_roadmap_cleanup_plan(plan, prefer_runtime=True)

            self.assertEqual(applied["system_tasks_archived"], 1)
            runtime_records = eve_store.read_jsonl_records(runtime_tasks)
            source_records = eve_store.read_jsonl_records(source_tasks)
            self.assertEqual([record["id"] for record in runtime_records], ["runtime-duplicate", "runtime-canonical", "runtime-only"])
            self.assertEqual([record["id"] for record in source_records], ["runtime-duplicate", "runtime-canonical", "runtime-only"])
            self.assertEqual(runtime_records[0]["status"], "archived")
            self.assertEqual(runtime_records[0]["merged_into"], "runtime-canonical")
            self.assertEqual(runtime_records[2]["status"], "planned")
            runtime_audit = eve_store.read_jsonl_records(runtime_cleanup_audit)
            source_audit = eve_store.read_jsonl_records(cleanup_audit)
            self.assertEqual(runtime_audit[0]["id"], "runtime-existing-audit")
            self.assertEqual([record["id"] for record in source_audit], [record["id"] for record in runtime_audit])
            self.assertEqual(len(runtime_audit), 2)


if __name__ == "__main__":
    unittest.main()
