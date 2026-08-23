import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import eve


class FakeOssLab:
    def build_inventory(self):
        return {
            "status": "ready",
            "installed_importable_count": 8,
            "tool_count": 12,
            "tools": [],
            "boundary": {"grants_live_authority": False},
        }

    def trace_workbench(self, trace_path):
        return {
            "status": "ready",
            "trace_path": str(trace_path),
            "record_count": 3,
            "kind_counts": {"LLM": 2, "TOOL": 1},
            "problem_counts": {},
        }

    def training_dataset_snapshot(self, dataset_dir):
        return {
            "status": "ready",
            "dataset_dir": str(dataset_dir),
            "blocked_reasons": [],
            "private_holdout_policy": "Private holdout rows stay outside Eve-readable project/runtime state.",
        }

    def trainer_recipe_plan(self, dataset_dir=None, output_dir=None, write=False):
        return {
            "status": "written" if write else "written_current",
            "write_performed": bool(write),
            "output_dir": str(output_dir or ""),
            "boundary": {
                "no_training_started": True,
                "promotes_models": False,
                "writes_eve_memory": False,
            },
        }

    def trainer_candidate_preflight(self, run_dry_run=False, verify_envs=False):
        return {
            "status": "isolated_env_required",
            "dry_run_performed": bool(run_dry_run),
            "verify_envs_performed": bool(verify_envs),
            "boundary": {"promotes_models": False, "grants_live_authority": False},
        }

    def service_runtime_status(self):
        return {
            "checked_at": "2026-07-20T18:00:00+00:00",
            "phoenix": {"status": "not_running", "currently_running": False},
            "langfuse": {"status": "not_running", "currently_running": False},
            "observational_only": True,
        }


class OssIntegrationTests(unittest.TestCase):
    def passing_pressure_eval(self):
        return {
            "status": "passed",
            "average_score": 5.0,
            "blocking": [],
            "cases": [],
            "hidden_probe_policy": "public only",
        }

    def passing_trainer_gate(self):
        return {
            "status": "ready_for_supervised_no_download_dry_run",
            "blockers": [],
            "boundary": {
                "no_download": True,
                "no_training_started": True,
                "writes_eve_memory": False,
                "promotes_models": False,
                "changes_live_routing": False,
            },
        }

    def passing_copilotkit_probe(self):
        return {
            "status": "ready",
            "generated_at": "2026-05-07T00:00:00+00:00",
            "fit_for_eve": {"requires_adapter_before_live_chat": True},
            "boundary": {
                "lab_only": True,
                "writes_eve_memory": False,
                "changes_live_chat_ui": False,
                "changes_model_routing": False,
                "hidden_tests_exposed": False,
            },
            "node_import_probe": {
                "status": "ready",
                "adapter_probe": {
                    "status": "ready",
                    "openai_adapter_constructed": True,
                    "copilot_runtime_constructed": True,
                },
            },
            "eve_backend_probe": {"status": "ready", "base_url": "http://127.0.0.1:8797/v1"},
        }

    def passing_deepeval_agent_metrics(self):
        return {
            "status": "passed",
            "package_version": "4.1.2",
            "records_considered": 2,
            "loop_records_considered": 2,
            "permission_score": 1.0,
            "loop_min_score": 1.0,
            "loop_failure_count": 0,
            "unauthorized_actions": [],
            "failed_execution_ids": [],
        }

    def test_dvc_manifest_versions_local_artifacts_without_row_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            dataset_dir = root / "training_datasets"
            recipe_dir = root / "recipes"
            integration_manifest = root / "oss_integration" / "dvc_dataset_manifest.json"
            dataset_dir.mkdir()
            recipe_dir.mkdir()
            row = {
                "prompt": "private training prompt text",
                "preferred_response": "corrected answer text",
                "privacy_tier": "local_only",
            }
            (dataset_dir / "latest.json").write_text(json.dumps({"status": "ready"}), encoding="utf-8")
            (dataset_dir / "latest_train.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
            (dataset_dir / "latest_validation.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
            trace_path = root / "latest_openinference.jsonl"
            trace_path.write_text(json.dumps({"schema_version": "eve_openinference_span.v1"}) + "\n", encoding="utf-8")
            (recipe_dir / "mlx_lm_lora_recipe.yaml").write_text("train: false\n", encoding="utf-8")

            with patch.object(eve, "TRAINING_DATASETS_DIR", dataset_dir), patch.object(
                eve, "TRACE_EXPORT_LATEST_PATH", trace_path
            ), patch.object(eve, "OSS_LAB_TRAINER_RECIPE_DIR", recipe_dir), patch.object(
                eve, "OSS_INTEGRATION_DVC_MANIFEST_PATH", integration_manifest
            ), patch.object(
                eve, "mirror_store_file_to_runtime", lambda _: None
            ), patch.object(
                eve, "oss_resolve_executable", return_value=""
            ):
                manifest = eve.build_oss_dvc_dataset_manifest(write=True)

        serialized = json.dumps(manifest)
        self.assertEqual("ready", manifest["status"])
        self.assertTrue(manifest["artifact"].endswith("dvc_dataset_manifest.json"))
        self.assertFalse(manifest["boundary"]["writes_dvc_metadata"])
        self.assertFalse(manifest["boundary"]["contains_row_text"])
        self.assertNotIn("private training prompt text", serialized)
        self.assertNotIn("corrected answer text", serialized)

    def test_deepeval_agent_boundaries_score_real_typed_action_shapes(self) -> None:
        clean_record = {
            "id": "execution-clean",
            "action": "service_health_check",
            "input_contract_ok": True,
            "input_contract": {"valid": True},
            "steps": [{"phase": "precondition"}, {"phase": "action"}, {"phase": "verify"}],
        }
        bad_record = {
            "id": "execution-bad",
            "action": "unsupported_action",
            "input_contract_ok": True,
            "input_contract": {"valid": True},
            "steps": [{"phase": "action"}, {"phase": "action"}],
        }

        def run_worker(command, timeout):
            del timeout
            payload = json.loads(command[-1])
            allowed = set(payload["allowed_actions"])
            actions = [item["action"] for item in payload["executions"]]
            unauthorized = sorted({action for action in actions if action not in allowed})
            failed = []
            for execution in payload["executions"]:
                signatures = [(step["name"], step["identity"]) for step in execution["steps"]]
                if len(signatures) != len(set(signatures)):
                    failed.append(execution["id"])
            result = {
                "package_version": "4.1.2",
                "permission_score": 1.0 if not unauthorized else 0.0,
                "loop_min_score": 1.0 if not failed else 0.5,
                "loop_records_considered": sum(bool(item["steps"]) for item in payload["executions"]),
                "loop_failure_count": len(failed),
                "unauthorized_actions": unauthorized,
                "failed_execution_ids": failed,
                "metric_contract": ["ToolPermissionMetric", "AgentLoopDetectionMetric"],
                "python_executable": "/source/.venv/bin/python",
            }
            return subprocess.CompletedProcess(command, 0, json.dumps(result), ""), ""

        with patch.object(
            eve, "operational_action_input_supported_actions", return_value={"service_health_check"}
        ), patch.object(
            eve, "read_action_executions", side_effect=[[clean_record], [bad_record]]
        ), patch.object(
            eve, "resolve_component_python_command", return_value=["/usr/bin/python3"]
        ), patch.object(
            eve, "run_component_command", side_effect=run_worker
        ):
            clean = eve.build_deepeval_agent_boundary_report()
            bad = eve.build_deepeval_agent_boundary_report()

        self.assertEqual("passed", clean["status"])
        self.assertEqual(1.0, clean["permission_score"])
        self.assertEqual(1.0, clean["loop_min_score"])
        self.assertEqual(1, clean["loop_records_considered"])
        self.assertEqual("failed", bad["status"])
        self.assertEqual(["unsupported_action"], bad["unauthorized_actions"])
        self.assertEqual(["execution-bad"], bad["failed_execution_ids"])
        self.assertFalse(clean["network_used"])
        self.assertFalse(clean["hidden_tests_used"])

    def test_deepeval_agent_boundaries_do_not_claim_loop_coverage_without_steps(self) -> None:
        typed_record_without_steps = {
            "id": "execution-without-steps",
            "action": "service_health_check",
            "input_contract_ok": True,
            "input_contract": {"valid": True},
            "steps": [],
        }

        def run_worker(command, timeout):
            del timeout
            result = {
                "package_version": "4.1.2",
                "permission_score": 1.0,
                "loop_min_score": 1.0,
                "loop_records_considered": 0,
                "loop_failure_count": 0,
                "unauthorized_actions": [],
                "failed_execution_ids": [],
                "metric_contract": ["ToolPermissionMetric", "AgentLoopDetectionMetric"],
                "python_executable": "/source/.venv/bin/python",
            }
            return subprocess.CompletedProcess(command, 0, json.dumps(result), ""), ""

        with patch.object(
            eve, "operational_action_input_supported_actions", return_value={"service_health_check"}
        ), patch.object(
            eve, "read_action_executions", return_value=[typed_record_without_steps]
        ), patch.object(
            eve, "resolve_component_python_command", return_value=["/usr/bin/python3"]
        ), patch.object(
            eve, "run_component_command", side_effect=run_worker
        ):
            report = eve.build_deepeval_agent_boundary_report()

        self.assertEqual("failed", report["status"])
        self.assertEqual(1, report["records_considered"])
        self.assertEqual(0, report["loop_records_considered"])

    def test_status_report_makes_oss_a_governed_eve_substrate(self) -> None:
        fake_lab = FakeOssLab()
        dvc_manifest = {
            "status": "ready",
            "file_count": 4,
            "dvc": {"available": True, "initialized": False},
            "boundary": {"grants_live_authority": False},
        }

        with patch.object(eve, "build_oss_dvc_dataset_manifest", return_value=dvc_manifest), patch.object(
            eve, "load_latest_oss_lab_report", return_value={}
        ), patch.object(eve, "load_latest_oss_pressure_eval", return_value={}), patch.object(
            eve, "load_latest_oss_trainer_dry_run", return_value={}
        ), patch.object(
            eve, "load_latest_oss_copilotkit_report", return_value=self.passing_copilotkit_probe()
        ), patch.object(
            eve, "build_deepeval_agent_boundary_report", return_value=self.passing_deepeval_agent_metrics()
        ):
            report = eve.build_oss_integration_status_report(
                lab_module=fake_lab,
                workflow_record={"status": "completed", "engine": "native_replayable_fallback"},
            )

        self.assertEqual("healthy", report["status"])
        self.assertEqual(7, report["readiness"]["ready_checks"])
        self.assertFalse(report["grants_live_authority"])
        self.assertFalse(report["authority_boundary"]["writes_eve_memory"])
        self.assertFalse(report["authority_boundary"]["changes_live_routing"])
        self.assertEqual("ready", report["copilotkit_status"])
        self.assertEqual("adapter_live", report["copilotkit_exposure_status"])
        self.assertEqual("eve_chat_thread", report["copilotkit_exposure_map"]["primary_surface"])
        self.assertEqual("completed", report["workflow_status"])
        self.assertEqual("not_running", report["service_status"]["phoenix"])
        self.assertEqual("not_running", report["service_status"]["langfuse"])
        self.assertNotEqual("server_ready", report["service_status"]["phoenix"])

    def test_public_eval_requires_public_artifacts_and_intact_boundaries(self) -> None:
        fake_lab = FakeOssLab()
        dvc_manifest = {
            "status": "ready",
            "file_count": 4,
            "dvc": {"available": True, "initialized": False},
            "boundary": {"grants_live_authority": False},
        }
        with patch.object(eve, "build_oss_dvc_dataset_manifest", return_value=dvc_manifest), patch.object(
            eve, "load_latest_oss_lab_report", return_value={}
        ), patch.object(eve, "load_latest_oss_pressure_eval", return_value={}), patch.object(
            eve, "load_latest_oss_trainer_dry_run", return_value={}
        ), patch.object(
            eve, "load_latest_oss_copilotkit_report", return_value=self.passing_copilotkit_probe()
        ), patch.object(
            eve, "build_deepeval_agent_boundary_report", return_value=self.passing_deepeval_agent_metrics()
        ):
            status_report = eve.build_oss_integration_status_report(
                lab_module=fake_lab,
                workflow_record={"status": "completed"},
            )
            eval_report = eve.build_oss_public_eval_report(lab_module=fake_lab, status_report=status_report)

        self.assertEqual("partial", eval_report["status"])
        self.assertIn("conversation_pressure_eval", eval_report["blocking"])
        self.assertIn("trainer_no_download_dry_run_gate", eval_report["blocking"])
        self.assertIn("Public OSS evals must not include hidden evaluator prompts", eval_report["hidden_probe_policy"])

    def test_public_eval_passes_when_pressure_and_trainer_gate_pass(self) -> None:
        fake_lab = FakeOssLab()
        dvc_manifest = {
            "status": "ready",
            "file_count": 4,
            "dvc": {"available": True, "initialized": False},
            "boundary": {"grants_live_authority": False},
        }
        with patch.object(eve, "build_oss_dvc_dataset_manifest", return_value=dvc_manifest), patch.object(
            eve, "load_latest_oss_lab_report", return_value={}
        ), patch.object(
            eve, "load_latest_oss_copilotkit_report", return_value=self.passing_copilotkit_probe()
        ), patch.object(
            eve, "build_deepeval_agent_boundary_report", return_value=self.passing_deepeval_agent_metrics()
        ):
            status_report = eve.build_oss_integration_status_report(
                lab_module=fake_lab,
                workflow_record={"status": "completed"},
            )
            eval_report = eve.build_oss_public_eval_report(
                lab_module=fake_lab,
                status_report=status_report,
                pressure_eval_report=self.passing_pressure_eval(),
                trainer_dry_run_report=self.passing_trainer_gate(),
            )

        self.assertEqual("passed", eval_report["status"])
        self.assertEqual([], eval_report["blocking"])
        self.assertIn("Public OSS evals must not include hidden evaluator prompts", eval_report["hidden_probe_policy"])

    def test_copilotkit_exposure_map_targets_eve_chat_with_live_agui_adapter(self) -> None:
        report = eve.build_oss_copilotkit_exposure_map(copilotkit_report=self.passing_copilotkit_probe())

        self.assertEqual("adapter_live", report["status"])
        self.assertEqual("ready", report["adapter_canary_status"])
        self.assertEqual("eve_chat_thread", report["primary_surface"])
        self.assertFalse(report["authority_boundary"]["writes_eve_memory"])
        self.assertFalse(report["authority_boundary"]["changes_model_routing"])
        self.assertFalse(report["authority_boundary"]["copilotkit_package_controls_ui"])
        self.assertTrue(report["authority_boundary"]["eve_owned_adapter_changes_live_chat_ui"])
        self.assertFalse(report["authority_boundary"]["requires_adapter_before_live_chat"])
        self.assertTrue(report["authority_boundary"]["adapter_canary_passed"])
        self.assertEqual("/api/eve-chat/ag-ui", report["adapter_canary"]["endpoint"])
        surface_ids = {item["surface_id"] for item in report["surfaces"]}
        self.assertIn("eve_chat_thinking_trace", surface_ids)

    def test_copilotkit_status_chat_response_uses_status_artifact(self) -> None:
        with patch.object(eve, "load_latest_oss_copilotkit_report", return_value=self.passing_copilotkit_probe()):
            result = eve.copilotkit_status_chat_response(
                "CopilotKit live integration smoke: which Eve Chat surfaces can expose it and does it change live model routing?",
                {},
            )

        self.assertIsNotNone(result)
        response = result["response"]
        self.assertIn("COPILOTKIT_STATUS: ready", response)
        self.assertIn("ADAPTER_LIVE: yes", response)
        self.assertIn("EVE_CHAT_SURFACES: eve_chat_thread, eve_chat_thinking_trace", response)
        self.assertIn("LIVE_MODEL_ROUTING: no", response)
        self.assertIn("LIVE_CHAT_UI: Eve-owned AG-UI adapter is live", response)
        self.assertEqual(["oss_copilotkit_status"], result["tools_used"])

    def test_copilotkit_demo_request_gets_live_demo_response(self) -> None:
        with patch.object(eve, "load_latest_oss_copilotkit_report", return_value=self.passing_copilotkit_probe()):
            result = eve.copilotkit_status_chat_response("Do a CopilotKit demo", {})

        self.assertIsNotNone(result)
        response = result["response"]
        self.assertIn("I'm starting the live CopilotKit demo now.", response)
        self.assertIn("AG-UI event stream start below this reply", response)
        self.assertIn("**CopilotKit demo in Eve Chat**", response)
        self.assertIn("| Surface | What this proves | Eve path |", response)
        self.assertIn("| Agentic chat | The demo stays in this same thread instead of a popup.", response)
        self.assertIn("**Live AG-UI smoke**", response)
        self.assertIn("| Event | Visible result |", response)
        self.assertIn("RUN_STARTED", response)
        self.assertIn("| `ACTIVITY_DELTA` | progress update |", response)
        self.assertIn("| `TEXT_MESSAGE_CONTENT` | `agui-live-ok` |", response)
        self.assertIn("| `RUN_FINISHED` | completed |", response)
        self.assertIn("agui-live-ok", response)
        self.assertIn("This card is the visible demo", response)
        self.assertIn("does not change model routing", response)
        self.assertNotIn("```text", response)
        self.assertNotIn("COPILOTKIT_DEMO:", response)
        self.assertNotIn("WHAT_TO_WATCH:", response)
        self.assertNotIn("EVE_CHAT_SURFACES:", response)
        self.assertEqual("copilotkit-demo-guard", result["model"])

    def test_capability_research_report_learns_from_local_copilotkit_docs(self) -> None:
        report = eve.build_capability_research_report(
            "CopilotKit",
            prompt="check the copilotkit docs and you tell me what else it can do",
            write=False,
        )

        self.assertEqual("eve_capability_research_report.v1", report["schema_id"])
        self.assertEqual("learned", report["status"])
        self.assertEqual("copilotkit", report["subject_slug"])
        self.assertGreater(report["source_count"], 0)
        capability_ids = {item["id"] for item in report["capabilities"]}
        self.assertIn("agui_events", capability_ids)
        self.assertIn("generative_ui", capability_ids)
        self.assertIn("frontend_tools", capability_ids)
        self.assertIn("shared_state", capability_ids)
        self.assertIn("human_in_loop", capability_ids)
        self.assertFalse(report["learning_loop"]["requires_new_custom_guard"])
        self.assertFalse(report["learning_loop"]["fallback_guard_only"])
        self.assertFalse(report["authority_boundary"]["changes_model_routing"])
        self.assertFalse(report["authority_boundary"]["writes_eve_memory"])
        self.assertFalse(report["authority_boundary"]["performs_actions"])

    def test_copilotkit_docs_request_gets_capability_answer(self) -> None:
        result = eve.capability_research_chat_response(
            "check the copilotkit docs and you tell me what else it can do",
            {},
            write=False,
        )

        self.assertIsNotNone(result)
        response = result["response"]
        self.assertIn("CopilotKit is useful to Eve as an evidence-grounded capability candidate", response)
        self.assertIn("**What Eve learned from the available docs/source/artifacts**", response)
        self.assertIn("| AG-UI event streams |", response)
        self.assertIn("| Generative UI |", response)
        self.assertIn("| Frontend tools |", response)
        self.assertIn("| Shared state |", response)
        self.assertIn("| Human-in-the-loop |", response)
        self.assertIn("| Debugging and observability |", response)
        self.assertIn("| Threads and persistence |", response)
        self.assertIn("**What I would build next for Eve**", response)
        self.assertIn("Real Eve artifact cards", response)
        self.assertIn("Action trace cards", response)
        self.assertIn("Governance review cards", response)
        self.assertIn("does not change Eve's model routing", response)
        self.assertNotIn("Could you tell me", response)
        self.assertNotIn("which specific area", response)
        self.assertEqual("capability-research-guard", result["model"])
        self.assertEqual(["capability_research"], result["tools_used"])
        self.assertFalse(result["report"]["learning_loop"]["fallback_guard_only"])

    def test_capability_research_handles_eve_chat_continuation_context(self) -> None:
        body = "\n\n".join(
            [
                "Latest user message:\nwhat else can it do?",
                (
                    "Visible UI context for continuity only. Prior visible context is not the current "
                    "user request."
                ),
                (
                    "Prior visible UI context (continuity only, not current request):\n"
                    "[user]\nDo a CopilotKit demo\n\n"
                    "[assistant]\nI'm starting the live CopilotKit demo now with AG-UI events."
                ),
            ]
        )

        result = eve.capability_research_chat_response(body, {}, write=False)

        self.assertIsNotNone(result)
        self.assertEqual("CopilotKit", result["report"]["subject"])
        self.assertIn("| AG-UI event streams |", result["response"])
        self.assertIn("| Frontend tools |", result["response"])
        self.assertNotIn("Would you like me", result["response"])

    def test_capability_research_write_persists_reusable_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            subjects_dir = root / "subjects"
            global_latest = root / "latest.json"
            with patch.object(eve, "CAPABILITY_RESEARCH_DIR", root), patch.object(
                eve, "CAPABILITY_RESEARCH_SUBJECTS_DIR", subjects_dir
            ), patch.object(eve, "CAPABILITY_RESEARCH_LATEST_PATH", global_latest), patch.object(
                eve, "mirror_store_file_to_runtime", lambda _: None
            ):
                report = eve.build_capability_research_report("CopilotKit", write=True)
                artifacts = report["artifacts"]
                latest_path = Path(artifacts["latest"])
                history_path = Path(artifacts["history"])
                global_path = Path(artifacts["global_latest"])
                self.assertTrue(latest_path.exists())
                self.assertTrue(history_path.exists())
                self.assertTrue(global_path.exists())
                saved = json.loads(latest_path.read_text(encoding="utf-8"))
                self.assertEqual("eve_capability_research_report.v1", saved["schema_id"])
                self.assertEqual(artifacts["latest"], saved["artifacts"]["latest"])

    def test_copilotkit_agui_live_smoke_marker_is_deterministic(self) -> None:
        with patch.object(eve, "load_latest_oss_copilotkit_report", return_value=self.passing_copilotkit_probe()):
            result = eve.copilotkit_status_chat_response(
                "CopilotKit AG-UI live smoke: reply with exactly agui-live-ok and no other words.",
                {},
            )

        self.assertIsNotNone(result)
        self.assertEqual("agui-live-ok", result["response"])
        self.assertEqual("copilotkit-agui-smoke-guard", result["model"])
        self.assertEqual(["oss_copilotkit_agui_smoke"], result["tools_used"])

    def test_public_pressure_eval_scores_chat_command_output(self) -> None:
        commands = []

        def run_command(command, timeout=60):
            del timeout
            commands.append(command)
            return {
                "status": "ok",
                "stdout_tail": "I would preserve the current objective, choose the next action, and check fresh evidence before claiming progress.",
                "stderr_tail": "",
                "returncode": 0,
            }

        with patch.object(eve, "current_chat_model_attribution", return_value={"chat_model": "eve-fast", "runtime": "python", "command_surface": "chat"}), patch.object(
            eve,
            "oss_run_command",
            side_effect=run_command,
        ):
            report = eve.run_oss_conversation_pressure_eval(limit=1, save=False)

        self.assertEqual("passed", report["status"])
        self.assertEqual(1, report["case_count"])
        self.assertIn("--private-audit-integrated-guards", commands[0])
        self.assertEqual("integrated_private_audit_no_journal", report["cases"][0]["mode"])
        self.assertEqual("none_integrated_private_audit", report["cases"][0]["attribution"]["tools_observed"])

    def test_integrated_private_guard_is_read_only_and_short_circuits(self) -> None:
        with patch.object(
            eve,
            "route_contract_diagnostic_response",
            return_value=None,
        ), patch.object(
            eve,
            "terse_followup_continuation_response",
            return_value={"response": "guarded without an action"},
        ), patch.object(
            eve,
            "provided_status_bundle_anomaly_response",
        ) as lower_priority_guard:
            result = eve.integrated_private_chat_guard_response(
                "continue the current objective",
                {},
            )

        self.assertEqual(
            {
                "model": "terse-followup-continuity-guard",
                "response": "guarded without an action",
            },
            result,
        )
        lower_priority_guard.assert_not_called()

    def test_trainer_dry_run_gate_blocks_without_approved_local_model(self) -> None:
        fake_lab = FakeOssLab()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            recipe_dir = root / "recipes"
            recipe_dir.mkdir()
            (recipe_dir / "mlx_lm_lora_recipe.yaml").write_text(
                'model: "REPLACE_WITH_APPROVED_LOCAL_MLX_MODEL_PATH"\ntrain: false\n',
                encoding="utf-8",
            )
            venv = root / "mlx-lm-py313"
            cli = venv / "bin" / "mlx_lm.lora"
            cli.parent.mkdir(parents=True)
            cli.write_text("#!/bin/sh\n", encoding="utf-8")
            cli.chmod(0o755)
            fake_lab.trainer_lab_envs = lambda verify=False: [
                {
                    "id": "mlx_lm",
                    "status": "installed",
                    "venv_path": str(venv),
                    "expected_cli": "mlx_lm.lora",
                }
            ]
            with patch.object(eve, "OSS_LAB_TRAINER_RECIPE_DIR", recipe_dir), patch.object(
                eve, "oss_run_command", return_value={"status": "ok", "stdout_tail": "help", "returncode": 0}
            ):
                report = eve.build_oss_trainer_dry_run_gate(save=False, lab_module=fake_lab)

        self.assertEqual("blocked", report["status"])
        self.assertIn("approved_local_base_model_path_missing", report["blockers"])
        self.assertTrue(report["boundary"]["no_download"])
        self.assertTrue(report["boundary"]["no_training_started"])

    def test_cycle_composes_trace_dataset_manifest_recipes_workflow_and_eval(self) -> None:
        fake_lab = FakeOssLab()
        dvc_manifest = {
            "status": "ready",
            "file_count": 4,
            "dvc": {"available": True, "initialized": False},
            "boundary": {"grants_live_authority": False},
        }
        workflow = {"status": "completed", "engine": "native_replayable_fallback", "steps": []}
        dataset_report = {
            "status": "ready",
            "example_count": 2,
            "split_counts": {"train": 1, "validation": 1, "private_holdout": 0},
            "artifacts": {"latest": ".eve/training_datasets/latest.json"},
        }

        with patch.object(eve, "load_eve_oss_lab_module", return_value=fake_lab), patch.object(
            eve, "build_openinference_trace_export", return_value=({"status": "ready", "span_count": 1}, [{"name": "span"}])
        ), patch.object(eve, "save_openinference_trace_export", return_value=Path(".eve/trace_exports/latest_openinference.jsonl")), patch.object(
            eve, "build_training_dataset", return_value=({"status": "ready", "example_count": 2}, [{"id": "ex"}])
        ), patch.object(eve, "save_training_dataset_report", return_value=dataset_report), patch.object(
            eve, "build_oss_dvc_dataset_manifest", return_value=dvc_manifest
        ), patch.object(eve, "run_oss_native_workflow", return_value=workflow), patch.object(
            eve, "run_oss_conversation_pressure_eval", return_value=self.passing_pressure_eval()
        ), patch.object(eve, "build_oss_trainer_dry_run_gate", return_value=self.passing_trainer_gate()), patch.object(
            eve, "load_latest_oss_lab_report", return_value={}
        ), patch.object(
            eve, "load_latest_oss_copilotkit_report", return_value=self.passing_copilotkit_probe()
        ), patch.object(
            eve, "build_deepeval_agent_boundary_report", return_value=self.passing_deepeval_agent_metrics()
        ), patch.object(
            eve, "mirror_store_file_to_runtime", lambda _: None
        ), patch.object(eve, "mirror_store_tree_to_runtime", lambda _: None):
            report = eve.run_oss_integration_cycle(save=False)

        self.assertEqual("completed", report["status"])
        self.assertIn("trace_export", report["actions"])
        self.assertIn("training_dataset_build", report["actions"])
        self.assertIn("dvc_manifest", report["actions"])
        self.assertIn("trainer_recipe_write", report["actions"])
        self.assertIn("conversation_pressure_eval", report["actions"])
        self.assertIn("trainer_no_download_dry_run_gate", report["actions"])
        self.assertIn("copilotkit_exposure_map", report["actions"])
        self.assertEqual("passed", report["public_eval"]["status"])
        self.assertFalse(report["authority_boundary"]["promotes_models"])


if __name__ == "__main__":
    unittest.main()
