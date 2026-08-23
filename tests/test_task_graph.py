import unittest
from unittest import mock
import copy

import eve


class TaskGraphTests(unittest.TestCase):
    def test_manual_task_commands_delegate_to_live_runtime(self):
        cases = [
            (
                eve.cmd_task_list,
                mock.Mock(limit=10, days=7, status="planned", lane="cpu", kind="retrieval", full=True),
                ["task", "list", "--limit", "10", "--days", "7", "--status", "planned", "--lane", "cpu", "--kind", "retrieval", "--full"],
            ),
            (
                eve.cmd_task_refresh,
                mock.Mock(run_cpu=True, cpu_limit=2),
                ["task", "refresh", "--run-cpu", "--cpu-limit", "2"],
            ),
            (
                eve.cmd_task_run,
                mock.Mock(limit=3),
                ["task", "run", "--limit", "3"],
            ),
            (
                eve.cmd_task_update,
                mock.Mock(id="task-1", status="blocked", blocked_reason="wait", result_summary=None),
                ["task", "update", "task-1", "--status", "blocked", "--blocked-reason", "wait"],
            ),
            (
                eve.cmd_task_graph,
                mock.Mock(days=2, status=None, lane=None, kind=None, include_archived=True, full=True),
                ["task", "graph", "--days", "2", "--include-archived", "--full"],
            ),
        ]

        for command, args, expected in cases:
            with self.subTest(command=command.__name__):
                with mock.patch.object(eve, "delegate_cli_to_runtime", return_value=17) as delegate:
                    self.assertEqual(17, command(args))
                delegate.assert_called_once()
                self.assertEqual(expected, delegate.call_args.args[0])

    def test_live_task_ledgers_are_runtime_authoritative_during_sync(self):
        self.assertEqual(
            {eve.SYSTEM_TASKS_PATH, eve.MAINTENANCE_ACTIONS_PATH},
            eve.runtime_live_owned_data_files(),
        )

    def test_manual_maintenance_commands_delegate_to_live_runtime(self):
        cases = [
            (
                eve.cmd_maintenance_list,
                mock.Mock(limit=10, days=7, status="planned", kind="cleanup", full=True),
                ["maintenance", "list", "--limit", "10", "--days", "7", "--status", "planned", "--kind", "cleanup", "--full"],
            ),
            (
                eve.cmd_maintenance_update,
                mock.Mock(id="action-1", status="approved", blocked_reason=None, result_summary="ready"),
                ["maintenance", "update", "action-1", "--status", "approved", "--result-summary", "ready"],
            ),
            (
                eve.cmd_maintenance_run,
                mock.Mock(limit=2),
                ["maintenance", "run", "--limit", "2"],
            ),
        ]

        for command, args, expected in cases:
            with self.subTest(command=command.__name__):
                with mock.patch.object(eve, "delegate_cli_to_runtime", return_value=19) as delegate:
                    self.assertEqual(19, command(args))
                delegate.assert_called_once()
                self.assertEqual(expected, delegate.call_args.args[0])

    def test_completed_dependency_makes_planned_child_ready(self):
        graph = eve.build_system_task_graph(
            [
                {
                    "id": "parent",
                    "title": "Parent",
                    "status": "completed",
                    "priority": 3,
                },
                {
                    "id": "child",
                    "title": "Child",
                    "status": "planned",
                    "priority": 5,
                    "depends_on": ["parent"],
                },
            ],
            generated_at="2026-04-27T00:00:00+00:00",
        )

        self.assertEqual("ready", graph["status"])
        self.assertEqual(1, graph["summary"]["ready"])
        self.assertEqual("child", graph["ready_queue"][0]["id"])
        child = next(node for node in graph["nodes"] if node["id"] == "child")
        self.assertTrue(child["ready"])
        self.assertEqual("ready", child["dependency_state"])

    def test_missing_dependency_degrades_graph_and_blocks_node(self):
        graph = eve.build_system_task_graph(
            [
                {
                    "id": "child",
                    "title": "Child",
                    "status": "planned",
                    "depends_on": ["missing-parent"],
                }
            ],
            generated_at="2026-04-27T00:00:00+00:00",
        )

        self.assertEqual("degraded", graph["status"])
        self.assertEqual(1, graph["summary"]["missing_dependencies"])
        self.assertEqual([], graph["ready_queue"])
        self.assertEqual("missing_dependency", graph["blocked_nodes"][0]["dependency_state"])
        self.assertEqual("missing-parent", graph["missing_dependencies"][0]["dependency_id"])

    def test_dependency_cycle_is_detected_and_not_ready(self):
        graph = eve.build_system_task_graph(
            [
                {"id": "a", "title": "A", "status": "planned", "depends_on": ["b"]},
                {"id": "b", "title": "B", "status": "planned", "depends_on": ["a"]},
            ],
            generated_at="2026-04-27T00:00:00+00:00",
        )

        self.assertEqual("degraded", graph["status"])
        self.assertEqual(1, graph["summary"]["cycles"])
        self.assertEqual([], graph["ready_queue"])
        cycle_states = {node["id"]: node["dependency_state"] for node in graph["nodes"]}
        self.assertEqual("cycle", cycle_states["a"])
        self.assertEqual("cycle", cycle_states["b"])

    def test_dependency_chain_projects_a_stable_multistep_plan(self):
        graph = eve.build_system_task_graph(
            [
                {"id": "observe", "title": "Observe evidence", "status": "planned", "priority": 3},
                {
                    "id": "repair",
                    "title": "Repair from evidence",
                    "status": "planned",
                    "priority": 5,
                    "depends_on": ["observe"],
                },
            ],
            generated_at="2026-07-19T00:00:00+00:00",
        )

        self.assertEqual(1, graph["summary"]["plans"])
        self.assertEqual(1, graph["summary"]["active_plans"])
        plan = graph["plans"][0]
        self.assertEqual("active", plan["status"])
        self.assertEqual("observe", plan["next_step"]["id"])
        self.assertEqual(0, plan["completed_count"])
        self.assertEqual(2, plan["task_count"])
        self.assertEqual(plan["id"], graph["ready_queue"][0]["plan_id"])

    def test_blocked_plan_preserves_the_real_step_and_reason(self):
        model = eve.build_conscious_plan_model(
            [
                {"id": "observe", "title": "Observe evidence", "status": "completed"},
                {
                    "id": "reflect",
                    "title": "Run the deeper reflection",
                    "kind": "gpu_followup_reflection",
                    "lane": "hybrid",
                    "status": "blocked",
                    "blocked_reason": "System load is hot.",
                    "depends_on": ["observe"],
                },
            ]
        )

        self.assertTrue(model["available"])
        self.assertEqual({}, model["ready_step"])
        blocked = model["selected_plan"]["blocked_steps"][0]
        self.assertEqual("reflect", blocked["id"])
        self.assertEqual("Run the deeper reflection", blocked["title"])
        self.assertEqual("System load is hot.", blocked["blocked_reason"])

    def test_plan_does_not_offer_a_step_without_an_admitted_executor(self):
        model = eve.build_conscious_plan_model(
            [
                {"id": "done", "title": "Done", "status": "completed"},
                {
                    "id": "unsupported",
                    "title": "Unsupported GPU mutation",
                    "kind": "unknown_gpu_mutation",
                    "lane": "gpu",
                    "status": "planned",
                    "depends_on": ["done"],
                },
            ]
        )

        self.assertTrue(model["available"])
        self.assertEqual({}, model["ready_step"])
        self.assertEqual("unsupported", model["dependency_ready_step"]["id"])
        self.assertFalse(model["dependency_ready_step"]["execution_ready"])
        self.assertIn("no admitted Eve executor", model["dependency_ready_step"]["execution_blocked_reason"])

    def test_cpu_executor_uses_graph_ready_set_and_delays_dependent_step(self):
        tasks = [
            eve.normalize_system_task(
                {
                    "id": "parent",
                    "title": "Collect prerequisite",
                    "kind": "retrieval_prep_pack",
                    "status": "planned",
                    "lane": "cpu",
                    "priority": 1,
                }
            ),
            eve.normalize_system_task(
                {
                    "id": "child",
                    "title": "Use prerequisite",
                    "kind": "component_balance_review",
                    "status": "planned",
                    "lane": "cpu",
                    "priority": 5,
                    "depends_on": ["parent"],
                }
            ),
        ]

        def read_tasks(*args, **kwargs):
            return copy.deepcopy(tasks)

        def update_task(task_id, **changes):
            index = next(index for index, task in enumerate(tasks) if task["id"] == task_id)
            merged = dict(tasks[index])
            merged.update(changes)
            tasks[index] = eve.normalize_system_task(merged)
            return copy.deepcopy(tasks[index])

        def execute(task, config, snapshot, state):
            return f"verified {task['id']}", {f"result_{task['id']}": True}

        state = {}
        patches = [
            mock.patch.object(eve, "read_system_tasks", side_effect=read_tasks),
            mock.patch.object(eve, "update_system_task_record", side_effect=update_task),
            mock.patch.object(eve, "execute_cpu_system_task", side_effect=execute),
            mock.patch.object(eve, "append_entry"),
            mock.patch.object(eve, "create_cpu_followup_actions"),
            mock.patch.object(eve, "recompute_task_queue_summary"),
        ]
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            first = eve.run_pending_cpu_system_tasks(
                {}, state, {}, source="test", limit=3, conscious_attribution=False
            )
            second = eve.run_pending_cpu_system_tasks(
                {}, state, {}, source="test", limit=3, conscious_attribution=False
            )

        self.assertEqual(["parent"], [task["id"] for task in first])
        self.assertEqual(["child"], [task["id"] for task in second])
        self.assertEqual("completed", tasks[0]["status"])
        self.assertEqual("completed", tasks[1]["status"])
        self.assertTrue(tasks[0]["metadata"]["ready_at_start"])
        self.assertTrue(tasks[1]["metadata"]["ready_at_start"])
        self.assertEqual(tasks[0]["metadata"]["plan_id"], tasks[1]["metadata"]["plan_id"])

    def test_cpu_executor_closes_the_exact_opened_conscious_cycle(self):
        tasks = [
            eve.normalize_system_task(
                {
                    "id": "ready-step",
                    "title": "Inspect current evidence",
                    "kind": "retrieval_prep_pack",
                    "status": "planned",
                    "lane": "cpu",
                    "priority": 4,
                }
            )
        ]

        def read_tasks(*args, **kwargs):
            return copy.deepcopy(tasks)

        def update_task(task_id, **changes):
            merged = dict(tasks[0])
            merged.update(changes)
            tasks[0] = eve.normalize_system_task(merged)
            return copy.deepcopy(tasks[0])

        opened = {"cycle_id": "opened-cycle", "predictions": {}}
        completed_cycle = {"cycle_id": "opened-cycle", "cycle_outcome": {"outcome_observed": True}}
        with (
            mock.patch.object(eve, "read_system_tasks", side_effect=read_tasks),
            mock.patch.object(eve, "update_system_task_record", side_effect=update_task),
            mock.patch.object(
                eve,
                "execute_cpu_system_task",
                return_value=("verified current evidence", {"retrieval_prep_summary": "verified"}),
            ),
            mock.patch.object(eve, "append_entry"),
            mock.patch.object(eve, "create_cpu_followup_actions"),
            mock.patch.object(eve, "recompute_task_queue_summary"),
            mock.patch.object(eve, "build_recurrent_conscious_state", return_value=opened),
            mock.patch.object(
                eve,
                "record_operational_action_execution",
                side_effect=lambda record: record,
            ) as record_action,
            mock.patch.object(
                eve,
                "complete_recurrent_conscious_cycle",
                return_value=completed_cycle,
            ) as complete_cycle,
        ):
            completed = eve.run_pending_cpu_system_tasks(
                {}, {}, {}, source="daemon", limit=1
            )

        self.assertEqual(["ready-step"], [task["id"] for task in completed])
        self.assertEqual("opened-cycle", completed[0]["metadata"]["source_cycle_id"])
        self.assertTrue(completed[0]["metadata"]["verification_ok"])
        self.assertTrue(completed[0]["metadata"]["action_execution_id"])
        self.assertEqual("system_tasks", record_action.call_args.args[0]["action"])
        self.assertIs(opened, complete_cycle.call_args.kwargs["opened_state"])
        self.assertEqual(
            "system_tasks",
            complete_cycle.call_args.kwargs["actual_process"]["action_id"],
        )
        self.assertTrue(complete_cycle.call_args.kwargs["outcome"]["observed"])

    def test_shared_graph_snapshot_delays_cross_executor_dependent_step(self):
        tasks = [
            eve.normalize_system_task(
                {
                    "id": "cpu-parent",
                    "title": "Collect maintenance evidence",
                    "kind": "retrieval_prep_pack",
                    "status": "planned",
                    "lane": "cpu",
                    "priority": 1,
                }
            ),
            eve.normalize_system_task(
                {
                    "id": "maintenance-child",
                    "title": "Apply bounded maintenance",
                    "kind": "service_repair_followup",
                    "status": "planned",
                    "lane": "hybrid",
                    "priority": 5,
                    "depends_on": ["cpu-parent"],
                }
            ),
        ]

        def read_tasks(*args, **kwargs):
            return copy.deepcopy(tasks)

        def update_task(task_id, **changes):
            index = next(index for index, task in enumerate(tasks) if task["id"] == task_id)
            merged = dict(tasks[index])
            merged.update(changes)
            tasks[index] = eve.normalize_system_task(merged)
            return copy.deepcopy(tasks[index])

        initial_records = copy.deepcopy(tasks)
        initial_graph = eve.build_system_task_graph(initial_records)
        safe_outcome = {
            "status": "completed",
            "result_summary": "maintenance verified",
            "blocked_reason": "",
            "state_updates": {"maintenance_verified": True},
            "metadata_updates": {"verification_ok": True},
        }
        with (
            mock.patch.object(eve, "read_system_tasks", side_effect=read_tasks),
            mock.patch.object(eve, "update_system_task_record", side_effect=update_task),
            mock.patch.object(
                eve,
                "execute_cpu_system_task",
                return_value=("evidence verified", {"evidence_verified": True}),
            ),
            mock.patch.object(eve, "execute_safe_maintenance_task", return_value=safe_outcome),
            mock.patch.object(eve, "append_entry"),
            mock.patch.object(eve, "create_cpu_followup_actions"),
            mock.patch.object(eve, "recompute_task_queue_summary"),
            mock.patch.object(eve, "rerun_post_maintenance_audits"),
        ):
            first = eve.run_pending_cpu_system_tasks(
                {},
                {},
                {},
                source="daemon",
                limit=2,
                conscious_attribution=False,
                task_records=initial_records,
                execution_graph=initial_graph,
            )
            same_cycle_maintenance = eve.run_pending_safe_maintenance_tasks(
                {},
                {},
                {},
                source="daemon",
                limit=2,
                task_records=initial_records,
                execution_graph=initial_graph,
            )
            next_records = read_tasks()
            next_cycle_maintenance = eve.run_pending_safe_maintenance_tasks(
                {},
                {},
                {},
                source="daemon",
                limit=2,
                task_records=next_records,
                execution_graph=eve.build_system_task_graph(next_records),
            )

        self.assertEqual(["cpu-parent"], [task["id"] for task in first])
        self.assertEqual([], same_cycle_maintenance)
        self.assertEqual(
            ["maintenance-child"],
            [task["id"] for task in next_cycle_maintenance],
        )


if __name__ == "__main__":
    unittest.main()
