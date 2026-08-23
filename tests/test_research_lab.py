import subprocess
import unittest
from unittest.mock import patch

import eve


class ResearchLabTests(unittest.TestCase):
    def test_kind_specs_are_allowlisted_and_non_shell(self):
        specs = eve.research_lab_kind_specs()

        self.assertEqual(set(eve.RESEARCH_LAB_KIND_CHOICES), set(specs))
        for spec in specs.values():
            for phase in ["baseline_commands", "action_commands", "after_commands"]:
                for command in spec.get(phase, []):
                    self.assertIsInstance(command.get("argv"), list)
                    self.assertNotIn(";", " ".join(command.get("argv") or []))

    def test_autoresearch_is_tracked_as_learning_source(self):
        watchlist = eve.component_watchlist({})
        autoresearch = next((item for item in watchlist if item.get("id") == "karpathy-autoresearch"), None)

        self.assertIsNotNone(autoresearch)
        self.assertEqual("https://github.com/karpathy/autoresearch.git", autoresearch["repository"])
        self.assertIn("bounded_research_loop", autoresearch["capability_domains"])

    def test_hermes_agent_is_tracked_as_learning_organ_source(self):
        watchlist = eve.component_watchlist({})
        hermes = next((item for item in watchlist if item.get("id") == "hermes-agent"), None)

        self.assertIsNotNone(hermes)
        self.assertEqual("https://github.com/NousResearch/hermes-agent.git", hermes["repository"])
        self.assertIn("proposal_generation", hermes["capability_domains"])

    def test_llama_cpp_component_probe_uses_configured_binary_path(self):
        calls = []

        def fake_run(command, timeout):
            calls.append(command)
            return (
                subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="version: 8946 (0f1bb602d)\n",
                    stderr="",
                ),
                "",
            )

        with patch.object(eve, "model_lane_records", return_value=[]), patch.object(
            eve,
            "run_component_command",
            side_effect=fake_run,
        ):
            info = eve.llama_cpp_component_local_version(
                {"llama_cpp_binary_path": "/tmp/eve-pinned/llama-server"},
                timeout=5,
            )

        self.assertEqual("8946 (0f1bb602d)", info["version"])
        self.assertEqual("/tmp/eve-pinned/llama-server", info["path"])
        self.assertEqual([["/tmp/eve-pinned/llama-server", "--version"]], calls)

    def test_decision_observes_measurement_only_run(self):
        decision = eve.decide_research_lab_result(
            {"score": 4.2, "issue_count": 2, "status": "degraded"},
            {"score": 4.2, "issue_count": 2, "status": "degraded"},
            command_failures=[],
            action_count=0,
        )

        self.assertEqual(decision["decision"], "observe")

    def test_decision_discards_regression(self):
        decision = eve.decide_research_lab_result(
            {"score": 4.2, "issue_count": 2, "status": "degraded"},
            {"score": 4.0, "issue_count": 3, "status": "degraded"},
            command_failures=[],
            action_count=1,
        )

        self.assertEqual(decision["decision"], "discard")

    def test_format_record_shows_before_after_and_artifact(self):
        text = eve.format_research_lab_record(
            {
                "id": "lab-1",
                "kind": "whole_system_baseline",
                "decision": "observe",
                "decision_reason": "Measurement-only run completed.",
                "metric": "whole_system",
                "before": {"status": "degraded", "score": 4.2, "issue_count": 2},
                "after": {"status": "degraded", "score": 4.2, "issue_count": 2},
                "score_delta": 0,
                "issue_delta": 0,
                "artifacts": {"history": ".eve/research_lab/runs/lab-1.json"},
            }
        )

        self.assertIn("decision: observe", text)
        self.assertIn("before: degraded score=4.2 issues=2", text)
        self.assertIn(".eve/research_lab/runs/lab-1.json", text)

    def test_tracker_item_marks_blocked_lab_run_as_fix_needed(self):
        items = eve.tracker_items_from_research_lab_runs(
            [
                {
                    "id": "lab-1",
                    "kind": "capability_refresh",
                    "decision": "blocked",
                    "decision_reason": "A command timed out.",
                    "finished_at": "2026-04-27T00:00:00+00:00",
                }
            ]
        )

        self.assertEqual(items[0]["priority"], "P2")
        self.assertEqual(items[0]["status"], "needs_fix")

    def test_tracker_item_suppresses_recovered_blocked_lab_run(self):
        items = eve.tracker_items_from_research_lab_runs(
            [
                {
                    "id": "lab-1",
                    "kind": "whole_system_baseline",
                    "decision": "blocked",
                    "finished_at": "2026-04-27T00:00:00+00:00",
                },
                {
                    "id": "lab-2",
                    "kind": "whole_system_baseline",
                    "decision": "observe",
                    "finished_at": "2026-04-27T00:01:00+00:00",
                },
            ]
        )

        self.assertEqual(1, len(items))
        self.assertEqual("lab-2", items[0]["source_id"])

    def test_command_runner_preserves_cli_flags(self):
        completed = eve.subprocess.CompletedProcess(["python3"], 0, stdout="", stderr="")

        with patch.object(eve.subprocess, "run", return_value=completed) as run_mock:
            result = eve.run_research_lab_command(
                {"argv": ["eval", "whole-system", "--full"], "ok_returncodes": [0]},
                timeout=5,
            )

        command = run_mock.call_args.args[0]
        self.assertIn("--full", command)
        self.assertTrue(result["ok"])

    def test_run_experiment_uses_bounded_protocol_without_shelling_in_unit_test(self):
        before = {"metric": "whole_system", "status": "degraded", "score": 4.2, "issue_count": 2}
        after = {"metric": "whole_system", "status": "degraded", "score": 4.2, "issue_count": 2}

        with patch.object(eve, "ensure_store"), patch.object(
            eve, "run_research_lab_command_group", return_value=[]
        ), patch.object(eve, "research_lab_metric_snapshot", side_effect=[before, after]), patch.object(
            eve, "save_research_lab_record", return_value={"history": ".eve/research_lab/runs/lab-1.json"}
        ), patch.object(
            eve, "append_research_lab_experiment_record"
        ), patch.object(
            eve, "record_evidence", return_value={"id": "ev-1"}
        ), patch.object(
            eve, "record_experience_event"
        ):
            record = eve.run_research_lab_experiment(
                kind="whole_system_baseline",
                hypothesis="A baseline can be refreshed with evidence.",
                budget_minutes=1,
                run_id="lab-1",
            )

        self.assertEqual(record["decision"], "observe")
        self.assertEqual(record["artifacts"]["history"], ".eve/research_lab/runs/lab-1.json")
        self.assertEqual(record["budget_minutes"], 1)


if __name__ == "__main__":
    unittest.main()
