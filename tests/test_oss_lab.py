import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "bin" / "eve_oss_lab.py"
SPEC = importlib.util.spec_from_file_location("eve_oss_lab", SCRIPT_PATH)
oss_lab = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(oss_lab)


class OssLabTests(unittest.TestCase):
    @staticmethod
    def langfuse_environment(version: str = "4.14.1", importable: bool = True):
        return {
            "status": "ok",
            "controller_python": "/usr/bin/python3",
            "requested_python": "/repo/.venv/bin/python",
            "python_executable": "/repo/.venv/bin/python",
            "python_version": "3.14.2",
            "tools": {
                "langfuse": {
                    "version": version,
                    "installed": bool(version),
                    "importable": importable,
                }
            },
        }

    def test_langfuse_default_does_not_share_eve_chat_port(self) -> None:
        self.assertEqual("http://127.0.0.1:3001", oss_lab.DEFAULT_LANGFUSE_URL)

    def test_langfuse_preflight_rejects_unrelated_http_service_on_port_3000(self) -> None:
        def fake_status(url: str, timeout: float = 1.0):
            if "/api/public/health" in url or url.endswith("/api/public/ready"):
                return {
                    "reachable": False,
                    "responded": True,
                    "status_code": 404,
                    "content_type": "application/json",
                    "body_json": {"ok": False, "error": "Not found"},
                    "body_preview": '{"ok": false}',
                    "error": "HTTP 404: Not Found",
                }
            return {
                "reachable": True,
                "responded": True,
                "status_code": 200,
                "content_type": "text/html",
                "body_json": None,
                "body_preview": "<title>Eve Chat</title>",
                "error": "",
            }

        command_ok = {"status": "ok", "command": [], "returncode": 0, "stdout_tail": "", "stderr_tail": ""}
        with patch.object(oss_lab, "url_status", side_effect=fake_status), patch.object(
            oss_lab, "run_command", return_value=command_ok
        ), patch.object(
            oss_lab, "probe_inventory_environment", return_value=self.langfuse_environment()
        ):
            report = oss_lab.langfuse_preflight("http://127.0.0.1:3000")

        self.assertEqual("port_conflict", report["status"])
        self.assertEqual("other_http_service", report["server_identity"])
        self.assertFalse(report["server_identity_verified"])

    def test_langfuse_preflight_requires_health_and_readiness_identity(self) -> None:
        def fake_status(url: str, timeout: float = 1.0):
            if "/api/public/health" in url:
                return {
                    "reachable": True,
                    "responded": True,
                    "status_code": 200,
                    "content_type": "application/json",
                    "body_json": {"status": "OK"},
                    "body_preview": '{"status": "OK"}',
                    "error": "",
                }
            if url.endswith("/api/public/ready"):
                return {
                    "reachable": True,
                    "responded": True,
                    "status_code": 200,
                    "content_type": "application/json",
                    "body_json": {"status": "OK"},
                    "body_preview": '{"status": "OK"}',
                    "error": "",
                }
            return {
                "reachable": True,
                "responded": True,
                "status_code": 200,
                "content_type": "text/html",
                "body_json": None,
                "body_preview": "Langfuse",
                "error": "",
            }

        command_ok = {"status": "ok", "command": [], "returncode": 0, "stdout_tail": "", "stderr_tail": ""}
        with patch.object(oss_lab, "url_status", side_effect=fake_status), patch.object(
            oss_lab, "run_command", return_value=command_ok
        ), patch.object(
            oss_lab, "probe_inventory_environment", return_value=self.langfuse_environment()
        ):
            report = oss_lab.langfuse_preflight()

        self.assertEqual("server_ready", report["status"])
        self.assertEqual("langfuse", report["server_identity"])
        self.assertTrue(report["server_identity_verified"])

    def test_current_service_status_does_not_reuse_historical_preflight(self) -> None:
        unavailable = {
            "reachable": False,
            "responded": False,
            "status_code": None,
            "content_type": "",
            "body_json": None,
            "body_preview": "",
            "error": "connection refused",
        }
        with patch.object(oss_lab, "url_status", return_value=unavailable):
            report = oss_lab.service_runtime_status()

        self.assertEqual("not_running", report["phoenix"]["status"])
        self.assertEqual("not_running", report["langfuse"]["status"])
        self.assertFalse(report["phoenix"]["currently_running"])
        self.assertFalse(report["langfuse"]["currently_running"])
        self.assertFalse(report["starts_services"])

    def test_phoenix_runtime_requires_health_and_database_readiness(self) -> None:
        def fake_status(url: str, timeout: float = 1.0):
            del timeout
            if url.endswith("/healthz"):
                return {
                    "reachable": True,
                    "responded": True,
                    "status_code": 200,
                    "content_type": "text/plain",
                    "body_json": None,
                    "body_preview": "OK",
                    "error": "",
                }
            return {
                "reachable": True,
                "responded": True,
                "status_code": 200,
                "content_type": "application/json" if url.endswith("/readyz") else "text/html",
                "body_json": {} if url.endswith("/readyz") else None,
                "body_preview": "{}" if url.endswith("/readyz") else "Phoenix",
                "error": "",
            }

        with patch.object(oss_lab, "url_status", side_effect=fake_status):
            report = oss_lab.phoenix_runtime_status()

        self.assertEqual("running", report["status"])
        self.assertEqual("phoenix", report["server_identity"])
        self.assertTrue(report["currently_running"])

    def test_importable_treats_missing_parent_package_as_absent(self) -> None:
        self.assertFalse(oss_lab.importable("definitely_missing_parent_for_eve.submodule"))

    def test_inventory_keeps_tools_lab_only(self) -> None:
        fake_tools = {
            tool["id"]: {
                "version": "1.0.0" if index < 8 else "",
                "installed": index < 8,
                "importable": index < 8,
            }
            for index, tool in enumerate(oss_lab.TOOL_REGISTRY)
        }
        environment = {
            "status": "ok",
            "controller_python": "/usr/bin/python3",
            "requested_python": "/repo/.venv/bin/python",
            "python_executable": "/repo/.venv/bin/python",
            "python_version": "3.14.2",
            "tools": fake_tools,
        }
        with patch.object(oss_lab, "probe_inventory_environment", return_value=environment):
            inventory = oss_lab.build_inventory()

        tool_ids = {tool["id"] for tool in inventory["tools"]}
        self.assertIn("phoenix", tool_ids)
        self.assertIn("dvc", tool_ids)
        self.assertIn("mlx_lm", tool_ids)
        self.assertTrue(inventory["boundary"]["lab_only"])
        self.assertFalse(inventory["boundary"]["grants_live_authority"])
        self.assertTrue(all(tool["live_authority"] is False for tool in inventory["tools"]))
        self.assertEqual("/repo/.venv/bin/python", inventory["environment"]["probe_python"])
        self.assertEqual("/usr/bin/python3", inventory["environment"]["controller_python"])
        self.assertEqual(8, inventory["installed_importable_count"])

    def test_inventory_python_skips_runtime_bundle_without_project_venv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = base / "runtime"
            source = base / "source"
            runtime.mkdir()
            project_python = source / ".venv" / "bin" / "python"
            project_python.parent.mkdir(parents=True)
            project_python.write_text("#!/bin/sh\n", encoding="utf-8")
            project_python.chmod(0o755)

            with patch.object(oss_lab, "eve_project_root_candidates", return_value=[runtime, source]), patch.dict(
                oss_lab.os.environ, {"EVE_OSS_INVENTORY_PYTHON": ""}
            ):
                selected = oss_lab.resolve_inventory_python()

        self.assertEqual(str(project_python), selected)

    def test_trace_workbench_validates_openinference_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = Path(tmp) / "latest_openinference.jsonl"
            trace_path.write_text(
                json.dumps(
                    {
                        "schema_version": "eve_openinference_span.v1",
                        "name": "reply.synthesize",
                        "context": {"trace_id": "a" * 32, "span_id": "b" * 16},
                        "status_code": "OK",
                        "attributes": {"openinference.span.kind": "LLM"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            report = oss_lab.trace_workbench(trace_path)

        self.assertEqual("ready", report["status"])
        self.assertEqual(1, report["record_count"])
        self.assertEqual({"LLM": 1}, report["kind_counts"])
        self.assertEqual({}, report["problem_counts"])

    def test_trace_workbench_reports_cleanup_needed_for_bad_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = Path(tmp) / "bad_openinference.jsonl"
            trace_path.write_text('{"name": ""}\nnot-json\n', encoding="utf-8")

            report = oss_lab.trace_workbench(trace_path)

        self.assertEqual("needs_cleanup", report["status"])
        self.assertEqual(2, report["record_count"])
        self.assertGreaterEqual(report["problem_counts"]["schema_version"], 1)
        self.assertGreaterEqual(report["problem_counts"]["invalid_json"], 1)

    def test_trainer_candidate_preflight_keeps_heavy_trainers_isolated(self) -> None:
        report = oss_lab.trainer_candidate_preflight(run_dry_run=False)
        candidates = {candidate["id"]: candidate for candidate in report["candidates"]}

        self.assertEqual("isolated_env_required", report["status"])
        self.assertTrue(candidates["peft"]["main_venv_safe"])
        self.assertFalse(candidates["axolotl"]["main_venv_safe"])
        self.assertFalse(candidates["llamafactory"]["main_venv_safe"])
        self.assertFalse(candidates["unsloth"]["main_venv_safe"])
        self.assertFalse(candidates["mlx_lm"]["main_venv_safe"])
        self.assertTrue(report["boundary"]["lab_only"])
        self.assertFalse(report["boundary"]["promotes_models"])
        self.assertIn("isolated_envs", report)
        self.assertFalse(report["verify_envs_performed"])

    def test_parse_uv_dry_run_counts_dependency_rewrites(self) -> None:
        output = """Resolved 4 packages in 1ms
Would download 2 packages
Would uninstall 1 package
Would install 2 packages
 - peft==0.19.1
 + peft==0.17.1
 + llamafactory==0.9.4
"""

        parsed = oss_lab.parse_uv_dry_run(output)

        self.assertEqual(2, parsed["would_download_count"])
        self.assertEqual(2, parsed["would_install_count"])
        self.assertEqual(1, parsed["would_uninstall_count"])
        self.assertIn("llamafactory==0.9.4", parsed["would_install"])
        self.assertIn("peft==0.19.1", parsed["would_uninstall"])

    def test_phoenix_cleanup_only_removes_new_sqlite_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            existing = workdir / "phoenix.db"
            generated = workdir / "phoenix.db-wal"
            existing.write_text("keep", encoding="utf-8")
            before = {str(existing.resolve())}
            generated.write_text("remove", encoding="utf-8")

            removed = oss_lab.cleanup_new_phoenix_sqlite_artifacts(workdir, before)

            self.assertEqual([str(generated)], removed)
            self.assertTrue(existing.exists())
            self.assertFalse(generated.exists())

    def test_trainer_lab_envs_reports_missing_known_envs_without_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            envs = oss_lab.trainer_lab_envs(Path(tmp), verify=False)

        self.assertGreaterEqual(len(envs), 2)
        env_by_id = {env["id"]: env for env in envs}
        self.assertEqual("missing", env_by_id["llamafactory"]["status"])
        self.assertEqual("missing", env_by_id["unsloth"]["status"])
        self.assertEqual("missing", env_by_id["mlx_lm"]["status"])
        self.assertFalse(env_by_id["llamafactory"]["python_exists"])
        self.assertFalse(env_by_id["unsloth"]["cli_exists"])
        self.assertFalse(env_by_id["mlx_lm"]["cli_exists"])

    def test_trainer_lab_envs_prefers_working_py314_mlx_over_stale_py313(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "trainer-venvs"
            stale = root / "mlx-lm-py313" / "bin"
            current = root / "mlx-lm-py314" / "bin"
            stale.mkdir(parents=True)
            current.mkdir(parents=True)
            (stale / "mlx_lm.lora").write_text("stale", encoding="utf-8")
            (current / "python").write_text("python", encoding="utf-8")
            (current / "mlx_lm.lora").write_text("cli", encoding="utf-8")

            envs = oss_lab.trainer_lab_envs(Path(tmp), verify=False)

        mlx_env = next(env for env in envs if env["id"] == "mlx_lm")
        self.assertEqual("installed", mlx_env["status"])
        self.assertEqual("mlx-lm-py314", mlx_env["name"])
        self.assertEqual(["mlx-lm-py314", "mlx-lm-py313"], mlx_env["candidate_names"])

    def test_trainer_recipe_plan_writes_no_training_recipes_without_row_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset_dir = root / "training_datasets"
            output_dir = root / "recipes"
            dataset_dir.mkdir()
            row = {
                "prompt": "private row text should stay out of recipes",
                "preferred_response": "corrected answer should stay out of recipes",
                "privacy_tier": "local",
                "source": "public_eval",
            }
            for filename in ("latest_train.jsonl", "latest_validation.jsonl"):
                (dataset_dir / filename).write_text(json.dumps(row) + "\n", encoding="utf-8")

            plan = oss_lab.trainer_recipe_plan(dataset_dir=dataset_dir, output_dir=output_dir, write=True)
            recipe_text = Path(plan["recipe_files"]["llamafactory_recipe"]).read_text(encoding="utf-8")
            unsloth_text = Path(plan["recipe_files"]["unsloth_recipe"]).read_text(encoding="utf-8")
            mlx_text = Path(plan["recipe_files"]["mlx_lm_recipe"]).read_text(encoding="utf-8")
            mlx_data_plan = Path(plan["recipe_files"]["mlx_lm_data_plan"]).read_text(encoding="utf-8")

        self.assertEqual("written", plan["status"])
        self.assertTrue(plan["write_performed"])
        self.assertTrue(plan["boundary"]["no_training_started"])
        self.assertIn("do_train: false", recipe_text)
        self.assertIn("train: false", mlx_text)
        self.assertIn("OPENBLAS_NUM_THREADS=1", mlx_text)
        self.assertNotIn("private row text", recipe_text)
        self.assertNotIn("corrected answer", unsloth_text)
        self.assertNotIn("private row text", mlx_data_plan)
        self.assertFalse(plan["boundary"]["contains_row_text"])

    def test_trainer_recipe_plan_recognizes_current_existing_recipes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset_dir = root / "training_datasets"
            output_dir = root / "recipes"
            dataset_dir.mkdir()
            row = {
                "prompt": "verified prompt",
                "preferred_response": "verified response",
                "privacy_tier": "local",
                "source": "public_eval",
            }
            for filename in ("latest_train.jsonl", "latest_validation.jsonl"):
                (dataset_dir / filename).write_text(json.dumps(row) + "\n", encoding="utf-8")

            oss_lab.trainer_recipe_plan(dataset_dir=dataset_dir, output_dir=output_dir, write=True)
            current = oss_lab.trainer_recipe_plan(dataset_dir=dataset_dir, output_dir=output_dir, write=False)
            (output_dir / "mlx_lm_lora_recipe.yaml").write_text("train: true\n", encoding="utf-8")
            stale = oss_lab.trainer_recipe_plan(dataset_dir=dataset_dir, output_dir=output_dir, write=False)

        self.assertEqual("written_current", current["status"])
        self.assertEqual(6, current["existing_recipe_count"])
        self.assertEqual([], current["stale_recipe_ids"])
        self.assertEqual("stale_or_incomplete", stale["status"])
        self.assertIn("mlx_lm_recipe", stale["stale_recipe_ids"])

    def test_trainer_recipe_plan_treats_source_and_runtime_mirror_paths_as_equivalent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dataset = root / "source" / ".eve" / "training_datasets"
            source_output = root / "source" / ".eve" / "oss_lab" / "trainer_recipes"
            runtime_dataset = root / "runtime" / ".eve" / "training_datasets"
            runtime_output = root / "runtime" / ".eve" / "oss_lab" / "trainer_recipes"
            source_dataset.mkdir(parents=True)
            runtime_dataset.mkdir(parents=True)
            runtime_output.mkdir(parents=True)
            row = {
                "prompt": "verified prompt",
                "preferred_response": "verified response",
                "privacy_tier": "local",
                "source": "public_eval",
            }
            for filename in ("latest_train.jsonl", "latest_validation.jsonl"):
                text = json.dumps(row) + "\n"
                (source_dataset / filename).write_text(text, encoding="utf-8")
                (runtime_dataset / filename).write_text(text, encoding="utf-8")

            written = oss_lab.trainer_recipe_plan(
                dataset_dir=source_dataset,
                output_dir=source_output,
                write=True,
            )
            for recipe_path in source_output.iterdir():
                (runtime_output / recipe_path.name).write_text(recipe_path.read_text(encoding="utf-8"), encoding="utf-8")
            with patch.object(oss_lab, "DEFAULT_TRAINING_DATASET_DIR", source_dataset), patch.object(
                oss_lab, "DEFAULT_TRAINER_RECIPE_DIR", source_output
            ), patch.object(Path, "home", return_value=root / "runtime-home"):
                # The explicit runtime paths are enough to exercise the
                # absolute output-path normalization even outside the user's home.
                current = oss_lab.trainer_recipe_plan(
                    dataset_dir=runtime_dataset,
                    output_dir=runtime_output,
                    write=False,
                )

        self.assertEqual("written", written["status"])
        self.assertEqual("written_current", current["status"])
        self.assertEqual([], current["stale_recipe_ids"])

    def test_trainer_recipe_plan_blocks_disallowed_privacy_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset_dir = root / "training_datasets"
            output_dir = root / "recipes"
            dataset_dir.mkdir()
            row = {
                "prompt": "secret",
                "preferred_response": "secret",
                "privacy_tier": "private_holdout",
                "source": "holdout",
            }
            for filename in ("latest_train.jsonl", "latest_validation.jsonl"):
                (dataset_dir / filename).write_text(json.dumps(row) + "\n", encoding="utf-8")

            plan = oss_lab.trainer_recipe_plan(dataset_dir=dataset_dir, output_dir=output_dir, write=True)

        self.assertEqual("blocked", plan["status"])
        self.assertFalse(plan["write_performed"])
        self.assertEqual({}, plan["recipe_files"])
        self.assertIn("train_disallowed_privacy_rows", plan["dataset_snapshot"]["blocked_reasons"])


if __name__ == "__main__":
    unittest.main()
