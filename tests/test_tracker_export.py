import unittest

import eve


class TrackerExportTests(unittest.TestCase):
    def test_tracker_stable_id_is_deterministic(self):
        first = eve.tracker_item(source_kind="eval_gap", source_id="gap-1", title="Fix gap")
        second = eve.tracker_item(source_kind="eval_gap", source_id="gap-1", title="Different title")

        self.assertEqual(first["id"], second["id"])

    def test_eval_gap_tracker_item_maps_priority_and_status(self):
        items = eve.tracker_items_from_eval_gaps(
            [
                {
                    "id": "gap-1",
                    "test_id": "action.latest_verification",
                    "layer": "action_grounding",
                    "status": "failed",
                    "priority": "high",
                    "missing_components": ["tool_grounding_needed"],
                    "primary_missing_component": "tool_grounding_needed",
                    "component_advice": "Needs execution evidence.",
                    "recommended_command": "python3 eve.py substrate show --runtime --active --full",
                    "next_action": "Require an execution record.",
                    "owner": "codex",
                    "created_at": "2026-04-26T00:00:00+00:00",
                }
            ]
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["priority"], "P1")
        self.assertEqual(items[0]["status"], "needs_fix")
        self.assertEqual(items[0]["component"], "action_grounding")
        self.assertEqual(items[0]["verification_command"], "python3 eve.py substrate show --runtime --active --full")

    def test_tracker_summary_counts_items(self):
        summary = eve.tracker_export_summary(
            [
                eve.tracker_item(source_kind="roadmap_priority", source_id="p1", title="P1", status="active", priority="P1"),
                eve.tracker_item(source_kind="eval_gap", source_id="gap-1", title="Gap", status="needs_fix", priority="P1"),
            ]
        )

        self.assertEqual(summary["total_items"], 2)
        self.assertEqual(summary["by_kind"]["eval_gap"], 1)
        self.assertEqual(summary["by_status"]["needs_fix"], 1)
        self.assertEqual(summary["by_priority"]["P1"], 2)

    def test_format_tracker_export_prints_first_priority(self):
        export = {
            "status": "ready",
            "generated_at": "2026-04-26T00:00:00+00:00",
            "target": "local",
            "recommended_first_priority": {"priority": 1, "title": "Grounded action and autonomy scoring"},
            "summary": {"total_items": 1, "by_kind": {"eval_gap": 1}, "by_status": {"needs_fix": 1}, "by_priority": {"P1": 1}},
            "artifacts": {"json": ".eve/tracker_export.json", "jsonl": ".eve/tracker_items.jsonl"},
            "items": [eve.tracker_item(source_kind="eval_gap", source_id="gap-1", title="Fix gap", priority="P1")],
        }

        formatted = eve.format_tracker_export(export)

        self.assertIn("first_priority: P1 Grounded action and autonomy scoring", formatted)
        self.assertIn("items: 1", formatted)

    def test_tracker_sync_operation_shapes_plane_payload(self):
        item = eve.tracker_item(
            source_kind="eval_gap",
            source_id="gap-1",
            title="Fix action grounding",
            status="needs_fix",
            priority="P1",
            labels=["eval-gap"],
            verification_command="python3 eve.py eval gaps --full",
        )

        operation = eve.tracker_sync_operation(item, target="plane", project="Eve")

        self.assertEqual(operation["operation"], "upsert_issue")
        self.assertEqual(operation["priority"], "high")
        self.assertEqual(operation["state"], "Todo")
        self.assertEqual(operation["adapter_payload"]["external_id"], operation["external_key"])

    def test_tracker_sync_csv_contains_source_key(self):
        item = eve.tracker_item(source_kind="roadmap_priority", source_id="p1", title="P1", priority="P1")
        operation = eve.tracker_sync_operation(item, target="local", project="Eve")

        csv_text = eve.tracker_sync_csv_text([operation])

        self.assertIn("external_key", csv_text)
        self.assertIn("eve:", csv_text)

    def test_format_tracker_sync_plan_reports_dry_run(self):
        item = eve.tracker_item(source_kind="roadmap_priority", source_id="p1", title="P1", priority="P1")
        operation = eve.tracker_sync_operation(item, target="plane", project="Eve")
        plan = {
            "status": "dry_run_ready",
            "mode": "dry-run",
            "target": "plane",
            "project": "Eve",
            "operation_count": 1,
            "auth_requirements": ["PLANE_API_KEY"],
            "available_auth": {"PLANE_API_KEY": False},
            "summary": {
                "by_state": {"Todo": 1},
                "by_priority": {"high": 1},
                "by_source_kind": {"roadmap_priority": 1},
            },
            "artifacts": {"plan": ".eve/tracker_sync_plan.json", "operations_jsonl": ".eve/tracker_sync_items.jsonl", "csv": ".eve/tracker_sync_import.csv"},
            "operations": [operation],
        }

        formatted = eve.format_tracker_sync_plan(plan)

        self.assertIn("external_write: disabled", formatted)
        self.assertIn("PLANE_API_KEY=missing", formatted)
        self.assertIn("operations: 1", formatted)


if __name__ == "__main__":
    unittest.main()
