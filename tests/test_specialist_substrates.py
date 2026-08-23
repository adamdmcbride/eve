import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import eve


class SpecialistSubstrateTests(unittest.TestCase):
    def test_registry_defines_only_non_lane_support_surfaces(self) -> None:
        self.assertEqual(
            {
                "memory_retrieval_service",
                "beads_work_graph_substrate",
                "hermes_learning_organ",
                "coding_self_repair_specialist",
                "model_inference_acceleration_lab",
                "dagster_evidence_orchestration_lab",
                "oss_improvement_substrate",
                "frontier_api_lab",
                "openclaw_body_action_nervous_system",
            },
            set(eve.SPECIALIST_SUBSTRATE_REGISTRY),
        )
        for substrate_id, spec in eve.SPECIALIST_SUBSTRATE_REGISTRY.items():
            self.assertFalse(spec["adds_chat_lane"], substrate_id)
            self.assertIn("purpose", spec)
            self.assertIn("guardrail", spec)
            self.assertIn("commands", spec)
            self.assertTrue(spec["commands"], substrate_id)

    def test_status_report_keeps_resident_lane_delta_zero(self) -> None:
        config = {
            "experimental_memory_retrieval_enabled": True,
            "experimental_memory_retrieval_backend": "lancedb",
            "experimental_memory_retrieval_query_mode": "hybrid",
            "experimental_memory_retrieval_model": "mlx-community/embeddinggemma-300m-6bit",
        }
        report = eve.build_specialist_substrate_report(config, prefer_runtime=False)

        self.assertEqual(0, report["resident_chat_lane_delta"])
        self.assertIn("Refine the five logical faculties", report["principle"])
        self.assertEqual(set(eve.SPECIALIST_SUBSTRATE_REGISTRY), {item["id"] for item in report["substrates"]})
        self.assertTrue(all(item["adds_chat_lane"] is False for item in report["substrates"]))

    def test_project_docs_preserve_specialist_boundaries(self) -> None:
        root = Path(eve.ROOT)
        docs = [
            root / "docs" / "EVE_CORE.md",
            root / "docs" / "model_lanes" / "README.md",
        ]
        docs.extend(
            path
            for path in (
                root / "docs" / "SPECIALIST_SUBSTRATES.md",
                root / "PROJECT_MEMORY.md",
                root / "COORDINATION.md",
            )
            if path.is_file()
        )
        for path in docs:
            text = path.read_text(encoding="utf-8").lower()
            self.assertIn("specialist", text, str(path))
            self.assertIn("memory", text, str(path))
            self.assertIn("coding", text, str(path))
            self.assertIn("frontier", text, str(path))
            self.assertIn("sixth", text, str(path))

    def test_identity_surfaces_name_hermes_and_openclaw_as_organs(self) -> None:
        identity = eve.default_runtime_identity()
        organ_text = " ".join(identity["organ_system"])

        self.assertIn("OpenClaw is Eve's body/action nervous system", organ_text)
        self.assertIn("Hermes is Eve's learning organ", organ_text)
        self.assertIn("Beads is Eve's staged work-graph substrate", organ_text)
        self.assertIn("Dagster is Eve's candidate recurring-evidence orchestrator", organ_text)
        self.assertIn("Speculative decoding drafters are inference accelerators", organ_text)
        self.assertIn("executive scheduler allocates cognition", organ_text)
        self.assertIn("autonomy governor decides", organ_text)

        root = Path(eve.ROOT)
        for path in [
            root / "prompts" / "core_identity.md",
            root / "docs" / "EVE_CORE.md",
            *[
                path
                for path in (
                    root / "docs" / "SPECIALIST_SUBSTRATES.md",
                    root / "PROJECT_MEMORY.md",
                    root / "COORDINATION.md",
                )
                if path.is_file()
            ],
        ]:
            text = path.read_text(encoding="utf-8")
            self.assertIn("OpenClaw", text, str(path))
            self.assertIn("body/action nervous system", text, str(path))
            self.assertIn("Hermes", text, str(path))
            self.assertIn("learning organ", text, str(path))

    def test_beads_and_dagster_are_substrates_not_authorities(self) -> None:
        beads = eve.SPECIALIST_SUBSTRATE_REGISTRY["beads_work_graph_substrate"]
        dagster = eve.SPECIALIST_SUBSTRATE_REGISTRY["dagster_evidence_orchestration_lab"]

        self.assertFalse(beads["adds_chat_lane"])
        self.assertFalse(dagster["adds_chat_lane"])
        self.assertIn("not Eve identity", beads["guardrail"])
        self.assertIn("Eve still decides", dagster["guardrail"])

        candidates = {item["id"]: item for item in eve.DEFAULT_AGENT_CAPABILITY_CANDIDATES}
        self.assertIn("beads-work-graph", candidates)
        self.assertIn("dagster-evidence-orchestrator", candidates)
        routes = {route["id"]: route for route in eve.DEFAULT_AGENT_INTEGRATION_ROUTES}
        self.assertIn("beads-work-graph", routes["agent-work-graph-ledger"]["candidate_ids"])
        self.assertIn("dagster-evidence-orchestrator", routes["recurring-evidence-orchestration"]["candidate_ids"])

    def test_beads_projection_keeps_active_dependency_closure_and_ready_parity(self) -> None:
        graph = eve.build_system_task_graph(
            [
                {
                    "id": "dependency",
                    "title": "Verified prerequisite",
                    "status": "completed",
                    "lane": "cpu",
                    "kind": "test",
                    "priority": 40,
                },
                {
                    "id": "active",
                    "title": "Current action",
                    "status": "planned",
                    "lane": "cpu",
                    "kind": "test",
                    "priority": 80,
                    "depends_on": ["dependency"],
                },
                {
                    "id": "unrelated-complete",
                    "title": "Old completed work",
                    "status": "completed",
                    "lane": "cpu",
                    "kind": "test",
                    "priority": 20,
                },
            ],
            generated_at="2026-07-20T00:00:00+00:00",
        )

        projection = eve.build_beads_task_projection(graph, max_tasks=10)
        projected_ids = {item["id"] for item in projection["nodes"]}
        parity = eve.compare_beads_task_projection(
            projection,
            {
                "dependency": {"id": "bead-dependency", "status": "closed"},
                "active": {"id": "bead-active", "status": "open"},
            },
            {"active"},
            {"dependency": set(), "active": {"dependency"}},
        )

        self.assertEqual("ready", projection["status"])
        self.assertEqual({"dependency", "active"}, projected_ids)
        self.assertEqual([{"from": "dependency", "to": "active"}], projection["edges"])
        self.assertTrue(parity["ok"])
        self.assertEqual(1, parity["expected_ready_count"])

    def test_beads_projection_fails_closed_when_active_set_exceeds_limit(self) -> None:
        graph = eve.build_system_task_graph(
            [
                {"id": "one", "title": "One", "status": "planned", "lane": "cpu", "kind": "test"},
                {"id": "two", "title": "Two", "status": "blocked", "lane": "cpu", "kind": "test"},
            ]
        )

        projection = eve.build_beads_task_projection(graph, max_tasks=1)

        self.assertEqual("blocked_limit", projection["status"])
        self.assertEqual(2, projection["active_task_count"])
        self.assertIn("active Eve task count", projection["blockers"][0])

    @unittest.skipUnless(eve.shutil.which("bd"), "Beads CLI is required for the isolated integration test")
    def test_beads_bridge_is_idempotent_and_detector_rechecks_live_parity(self) -> None:
        tasks = [
            {
                "id": "dependency",
                "title": "Verified prerequisite",
                "status": "completed",
                "lane": "cpu",
                "kind": "test",
                "priority": 40,
            },
            {
                "id": "active",
                "title": "Current action",
                "status": "planned",
                "lane": "cpu",
                "kind": "test",
                "priority": 80,
                "depends_on": ["dependency"],
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(
                [str(eve.shutil.which("bd")), "init", "--skip-agents", "--skip-hooks"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            artifact = root / "beads_bridge.json"
            patches = (
                patch.object(eve, "BEADS_BRIDGE_PATH", artifact),
                patch.object(eve, "read_system_tasks", return_value=tasks),
                patch.object(eve, "mirror_store_file_to_runtime"),
                patch.object(eve, "eve_checkout_root_for_marker", return_value=root),
            )
            with patches[0], patches[1], patches[2], patches[3]:
                with eve.concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                    results = list(
                        executor.map(
                            lambda _: eve.run_beads_task_bridge(apply=True, workspace_root=root, timeout=10),
                            range(2),
                        )
                    )
                first = next(item for item in results if item["operations"]["created"] == 2)
                second = next(item for item in results if item["operations"]["created"] == 0)
                healthy = eve.detect_beads_work_graph(timeout=10)

                issues = json.loads(
                    subprocess.run(
                        [
                            str(eve.shutil.which("bd")),
                            "list",
                            "--all",
                            "--label",
                            eve.BEADS_TASK_PROJECTION_LABEL,
                            "--limit",
                            "0",
                            "--json",
                        ],
                        cwd=root,
                        check=True,
                        capture_output=True,
                        text=True,
                    ).stdout
                )
                active_issue = next(item for item in issues if item.get("external_ref") == "eve-system-task:active")
                subprocess.run(
                    [
                        str(eve.shutil.which("bd")),
                        "update",
                        str(active_issue["id"]),
                        "--status",
                        "blocked",
                        "--json",
                    ],
                    cwd=root,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                drifted = eve.detect_beads_work_graph(timeout=10)

        self.assertEqual("verified", first["status"])
        self.assertTrue(first["parity"]["ok"])
        self.assertEqual(2, first["operations"]["created"])
        self.assertEqual(1, first["operations"]["dependencies_added"])
        self.assertEqual("verified", second["status"])
        self.assertEqual(
            {"created": 0, "updated": 0, "retired": 0, "dependencies_added": 0, "dependencies_removed": 0},
            second["operations"],
        )
        self.assertEqual("healthy", healthy["status"])
        self.assertTrue(healthy["bridge_live_parity"])
        self.assertEqual("staged_live", drifted["status"])
        self.assertFalse(drifted["bridge_live_parity"])

    def test_dagster_detector_selects_working_environment_and_fresh_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_bin = root / ".venv" / "bin"
            isolated_bin = root / ".eve" / "oss_integration" / "dagster_venv_py311" / "bin"
            definition = root / "dagster_lab" / "eve_evidence_defs.py"
            artifact = root / ".eve" / "dagster_lab" / "latest_eve_evidence_summary.json"
            project_bin.mkdir(parents=True)
            isolated_bin.mkdir(parents=True)
            definition.parent.mkdir(parents=True)
            artifact.parent.mkdir(parents=True)
            definition.write_text("# read-only test definition\n", encoding="utf-8")
            artifact.write_text(json.dumps({"generated_at": eve.utc_now()}), encoding="utf-8")
            for path in (
                project_bin / "python",
                project_bin / "dagster",
                isolated_bin / "python",
                isolated_bin / "dagster",
            ):
                path.write_text("#!/bin/sh\n", encoding="utf-8")
                path.chmod(path.stat().st_mode | stat.S_IXUSR)

            def run_component(command, timeout=10):
                del timeout
                executable = str(command[0])
                if executable == str(project_bin / "python"):
                    return subprocess.CompletedProcess(command, 0, "1.13.3\n", ""), ""
                if executable == str(isolated_bin / "python"):
                    return None, "command timed out"
                if executable == str(project_bin / "dagster") and "definitions" in command:
                    return subprocess.CompletedProcess(command, 0, "Definitions loaded successfully\n", ""), ""
                return None, "unexpected probe"

            with patch.object(eve, "dagster_lab_workspace_root", return_value=root), patch.object(
                eve, "RUNTIME_DIR", root / "runtime"
            ), patch.object(eve, "run_component_command", side_effect=run_component), patch.object(
                eve.shutil, "which", return_value=None
            ):
                status = eve.detect_dagster_evidence_orchestrator(timeout=3)

        self.assertEqual("lab_verified", status["status"])
        self.assertEqual("project", status["selected_environment"])
        self.assertTrue(status["command_probe_ok"])
        self.assertTrue(status["definition_validation_ok"])
        self.assertTrue(status["materialization_fresh"])
        probes = {item["environment"]: item for item in status["candidate_probes"]}
        self.assertTrue(probes["project"]["ok"])
        self.assertFalse(probes["isolated_py311"]["ok"])

    def test_dagster_detector_prefers_compatible_isolated_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_bin = root / ".venv" / "bin"
            isolated_bin = root / ".eve" / "oss_integration" / "dagster_venv_py311" / "bin"
            definition = root / "dagster_lab" / "eve_evidence_defs.py"
            artifact = root / ".eve" / "dagster_lab" / "latest_eve_evidence_summary.json"
            project_bin.mkdir(parents=True)
            isolated_bin.mkdir(parents=True)
            definition.parent.mkdir(parents=True)
            artifact.parent.mkdir(parents=True)
            definition.write_text("# read-only test definition\n", encoding="utf-8")
            artifact.write_text(json.dumps({"generated_at": eve.utc_now()}), encoding="utf-8")
            for path in (
                project_bin / "python",
                project_bin / "dagster",
                isolated_bin / "python",
                isolated_bin / "dagster",
            ):
                path.write_text("#!/bin/sh\n", encoding="utf-8")
                path.chmod(path.stat().st_mode | stat.S_IXUSR)

            def run_component(command, timeout=10):
                del timeout
                executable = str(command[0])
                if executable == str(isolated_bin / "python"):
                    return subprocess.CompletedProcess(command, 0, "1.13.19\n", ""), ""
                if executable == str(project_bin / "python"):
                    return subprocess.CompletedProcess(command, 0, "1.13.19\n", ""), ""
                if executable == str(isolated_bin / "dagster") and "definitions" in command:
                    return subprocess.CompletedProcess(command, 0, "Definitions loaded successfully\n", ""), ""
                return None, "unexpected probe"

            with patch.object(eve, "dagster_lab_workspace_root", return_value=root), patch.object(
                eve, "RUNTIME_DIR", root / "runtime"
            ), patch.object(eve, "run_component_command", side_effect=run_component), patch.object(
                eve.shutil, "which", return_value=None
            ):
                status = eve.detect_dagster_evidence_orchestrator(timeout=3)

        self.assertEqual("lab_verified", status["status"])
        self.assertEqual("isolated_py311", status["selected_environment"])
        self.assertEqual("1.13.19", status["version"])
        self.assertTrue(status["definition_validation_ok"])

    def test_dagster_detector_falls_back_when_source_materialization_is_inaccessible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime"
            project_bin = root / ".venv" / "bin"
            definition = root / "dagster_lab" / "eve_evidence_defs.py"
            source_artifact = root / ".eve" / "dagster_lab" / "latest_eve_evidence_summary.json"
            runtime_artifact = runtime / ".eve" / "dagster_lab" / "latest_eve_evidence_summary.json"
            project_bin.mkdir(parents=True)
            definition.parent.mkdir(parents=True)
            source_artifact.parent.mkdir(parents=True)
            runtime_artifact.parent.mkdir(parents=True)
            definition.write_text("# read-only test definition\n", encoding="utf-8")
            source_artifact.write_text("{}\n", encoding="utf-8")
            runtime_artifact.write_text(json.dumps({"generated_at": eve.utc_now()}), encoding="utf-8")
            for path in (project_bin / "python", project_bin / "dagster"):
                path.write_text("#!/bin/sh\n", encoding="utf-8")
                path.chmod(path.stat().st_mode | stat.S_IXUSR)

            def run_component(command, timeout=10):
                del timeout
                if str(command[0]) == str(project_bin / "python"):
                    return subprocess.CompletedProcess(command, 0, "1.13.3\n", ""), ""
                if str(command[0]) == str(project_bin / "dagster") and "definitions" in command:
                    return subprocess.CompletedProcess(command, 0, "Definitions loaded successfully\n", ""), ""
                return None, "unexpected probe"

            real_load = eve.eve_store.load_json_dict

            def load_materialization(path, default=None):
                if Path(path) == source_artifact:
                    raise PermissionError(1, "Operation not permitted", str(path))
                return real_load(path, default=default)

            with patch.object(eve, "dagster_lab_workspace_root", return_value=root), patch.object(
                eve, "RUNTIME_DIR", runtime
            ), patch.object(eve, "run_component_command", side_effect=run_component), patch.object(
                eve.shutil, "which", return_value=None
            ), patch.object(eve.eve_store, "load_json_dict", side_effect=load_materialization):
                status = eve.detect_dagster_evidence_orchestrator(timeout=3)

        self.assertEqual("lab_verified", status["status"])
        self.assertEqual(str(runtime_artifact), status["materialization_path"])
        self.assertTrue(status["materialization_fresh"])
        self.assertEqual(1, len(status["materialization_read_errors"]))
        self.assertIn("Operation not permitted", status["materialization_read_errors"][0])

    def test_dagster_workspace_root_skips_definition_only_runtime_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = base / "runtime"
            source = base / "source"
            for root in (runtime, source):
                definition = root / "dagster_lab" / "eve_evidence_defs.py"
                definition.parent.mkdir(parents=True)
                definition.write_text("# definition\n", encoding="utf-8")
                (root / "eve.py").write_text("# marker\n", encoding="utf-8")
            dagster = source / ".venv" / "bin" / "dagster"
            dagster.parent.mkdir(parents=True)
            dagster.write_text("#!/bin/sh\n", encoding="utf-8")

            with patch.object(eve, "eve_checkout_root_candidates", return_value=[runtime, source]):
                selected = eve.dagster_lab_workspace_root()

        self.assertEqual(source, selected)

    def test_dagster_workspace_root_prefers_source_project_env_over_runtime_isolated_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = base / "runtime"
            source = base / "source"
            for root in (runtime, source):
                definition = root / "dagster_lab" / "eve_evidence_defs.py"
                definition.parent.mkdir(parents=True)
                definition.write_text("# definition\n", encoding="utf-8")
                (root / "eve.py").write_text("# marker\n", encoding="utf-8")
            runtime_isolated = runtime / ".eve" / "oss_integration" / "dagster_venv_py311" / "bin" / "dagster"
            runtime_isolated.parent.mkdir(parents=True)
            runtime_isolated.write_text("#!/bin/sh\n", encoding="utf-8")
            source_project = source / ".venv" / "bin" / "dagster"
            source_project.parent.mkdir(parents=True)
            source_project.write_text("#!/bin/sh\n", encoding="utf-8")

            with patch.object(eve, "eve_checkout_root_candidates", return_value=[runtime, source]):
                selected = eve.dagster_lab_workspace_root()

        self.assertEqual(source, selected)

    def test_beads_preview_uses_the_writer_lock(self) -> None:
        expected = {"status": "preview"}
        with patch.object(eve, "daemon_runtime_running", return_value=False), patch.object(
            eve, "_run_beads_task_bridge_unlocked", return_value=expected
        ) as runner, patch.object(eve, "store_lock") as lock:
            lock.return_value.__enter__.return_value = None
            lock.return_value.__exit__.return_value = False
            report = eve.run_beads_task_bridge(apply=False, max_tasks=4, timeout=2)

        self.assertEqual(expected, report)
        lock.assert_called_once_with(eve.BEADS_BRIDGE_PATH)
        runner.assert_called_once_with(
            apply=False,
            max_tasks=4,
            timeout=2,
            workspace_root=None,
            prefer_runtime=True,
        )

    def test_beads_refresh_is_change_triggered_before_the_hourly_deadline(self) -> None:
        tasks = [
            {
                "id": "active",
                "title": "Current action",
                "status": "planned",
                "lane": "cpu",
                "kind": "test",
                "priority": 40,
            }
        ]
        plan = eve.build_beads_task_projection(eve.build_system_task_graph(tasks), max_tasks=8)
        current = {
            "status": "verified",
            "source_graph_fingerprint": plan["fingerprint"],
            "projection": {"max_tasks": 8},
            "parity": {"ok": True},
        }
        changed_tasks = [dict(tasks[0], status="blocked")]
        with patch.object(eve.eve_store, "load_json_dict", return_value=current), patch.object(
            eve, "read_system_tasks", return_value=tasks
        ) as task_reader:
            self.assertFalse(eve.beads_task_bridge_needs_refresh(max_tasks=8))
            task_reader.assert_called_once_with(limit=None, prefer_runtime=True)
        with patch.object(eve.eve_store, "load_json_dict", return_value=current), patch.object(
            eve, "read_system_tasks", return_value=changed_tasks
        ):
            self.assertTrue(eve.beads_task_bridge_needs_refresh(max_tasks=8))

    def test_lab_verified_status_survives_organ_normalization(self) -> None:
        signal = eve.organ_signal_from_substrate(
            "dagster_evidence_orchestration_lab",
            {
                "status": "lab_verified",
                "purpose": "Read-only recurring evidence assets.",
                "evidence": ["definition_validation_ok=yes", "materialization_fresh=yes"],
            },
        )

        self.assertEqual("lab_verified", signal["status"])
        self.assertEqual("lab_ready", signal["operational_status"])

    def test_model_inference_acceleration_lab_is_not_a_lane(self) -> None:
        substrate = eve.SPECIALIST_SUBSTRATE_REGISTRY["model_inference_acceleration_lab"]
        self.assertFalse(substrate["adds_chat_lane"])
        self.assertIn("Drafters accelerate a target model", substrate["guardrail"])

        report = eve.build_specialist_substrate_report(
            {"deep_llama_cpp_draft_hf_repo": "google/gemma-4-26B-A4B-it-assistant"},
            prefer_runtime=False,
        )
        acceleration = next(item for item in report["substrates"] if item["id"] == "model_inference_acceleration_lab")
        self.assertEqual("configured_lab_candidate", acceleration["status"])
        self.assertIn("configured_lanes=1", acceleration["evidence"])
        self.assertIn("official_gemma4_mtp_candidates=4", acceleration["evidence"])

    def test_model_inference_acceleration_lab_surfaces_latest_mtp_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            latest_path = Path(tmp) / "latest.json"
            latest_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-05-07T15:10:52+00:00",
                        "status": "passed",
                        "mode": "transformers-smoke",
                        "candidate_id": "e4b-local-gguf",
                        "transformers_smoke": {
                            "status": "passed",
                            "target": "google/gemma-4-E2B-it",
                            "assistant": "google/gemma-4-E2B-it-assistant",
                            "device": "mps:0",
                            "generated_tokens": 35,
                        },
                    }
                ),
                encoding="utf-8",
            )

            with patch("eve.GEMMA4_MTP_LAB_LATEST_PATH", latest_path):
                status = eve.detect_model_inference_acceleration_lab({}, prefer_runtime=False)
                report = eve.build_specialist_substrate_report({}, prefer_runtime=False)

        self.assertEqual("passed", status["latest_lab"]["status"])
        self.assertEqual("google/gemma-4-E2B-it-assistant", status["latest_lab"]["transformers_assistant"])
        acceleration = next(item for item in report["substrates"] if item["id"] == "model_inference_acceleration_lab")
        self.assertIn("latest_lab_status=passed", acceleration["evidence"])
        self.assertIn("latest_lab_mode=transformers-smoke", acceleration["evidence"])

    def test_model_inference_acceleration_lab_surfaces_llama_mtp_trace_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            latest_path = Path(tmp) / "latest.json"
            latest_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-05-07T15:55:00+00:00",
                        "status": "passed",
                        "mode": "llama-smoke",
                        "candidate_id": "e4b-local-gguf",
                        "llama_smoke": {
                            "status": "passed",
                            "flavor": "gemma4-mtp",
                            "trace_events": 122,
                            "trace_has_mtp": True,
                        },
                    }
                ),
                encoding="utf-8",
            )

            with patch("eve.GEMMA4_MTP_LAB_LATEST_PATH", latest_path):
                status = eve.detect_model_inference_acceleration_lab({}, prefer_runtime=False)
                report = eve.build_specialist_substrate_report({}, prefer_runtime=False)

        self.assertEqual("passed", status["latest_lab"]["llama_status"])
        self.assertEqual("gemma4-mtp", status["latest_lab"]["llama_flavor"])
        self.assertTrue(status["latest_lab"]["llama_trace_has_mtp"])
        acceleration = next(item for item in report["substrates"] if item["id"] == "model_inference_acceleration_lab")
        self.assertIn("latest_lab_mode=llama-smoke", acceleration["evidence"])
        self.assertIn("latest_llama=passed/gemma4-mtp", acceleration["evidence"])
        self.assertIn("latest_llama_trace=mtp", acceleration["evidence"])

    def test_hermes_smoke_blocks_context_below_minimum(self) -> None:
        status = {
            "version_ok": True,
            "profile_exists": True,
            "config_exists": True,
            "soul_guardrail_ok": True,
            "model_context_length": 16384,
            "hermes_minimum_context_length": 64000,
            "model_endpoint_checked": True,
            "model_endpoint_reachable": True,
            "model_base_url": "http://127.0.0.1:8081/v1",
            "status": "available_proposal_only_context_below_hermes_minimum",
        }

        self.assertIn("model_context_below_hermes_minimum", eve.hermes_smoke_gate_reasons(status))

    def test_hermes_smoke_prompt_keeps_proposal_only_boundary(self) -> None:
        prompt = eve.build_hermes_smoke_prompt(eve.default_hermes_smoke_trace())

        self.assertIn("Return only valid JSON", prompt)
        self.assertIn("governance ingest-hermes", prompt)
        self.assertIn("Propose learning only", prompt)
        self.assertIn("Do not propose capability grants", prompt)

    def test_hermes_command_uses_source_venv_python_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "hermes-agent"
            bin_dir = source / "venv" / "bin"
            bin_dir.mkdir(parents=True)
            python = bin_dir / "python3"
            hermes = bin_dir / "hermes"
            python.write_text("#!/bin/sh\n", encoding="utf-8")
            hermes.write_text("#!/bin/sh\n", encoding="utf-8")

            with patch("eve.HERMES_SOURCE_DIR", source), patch("eve.HERMES_DEFAULT_COMMAND", Path(tmp) / "missing-hermes"):
                command = eve.hermes_command_args("--version")

        self.assertEqual([str(python), str(hermes), "--version"], command)

    def test_hermes_json_repair_strips_single_markdown_fence(self) -> None:
        repaired = eve.extract_repairable_json_object('```json\\n{"memory_patches": []}\\n```')

        self.assertEqual('{"memory_patches": []}', repaired)

    def test_hermes_eval_summary_requires_strict_for_routine_ingest(self) -> None:
        summary = eve.hermes_eval_summary(
            [
                {
                    "status": "passed_with_json_repair_warnings",
                    "strict_json_ok": False,
                    "json_repair_used": True,
                    "proposal_count": 3,
                    "watchers": {"total_warnings": 1, "blocking_warnings": 0},
                }
            ]
        )

        self.assertEqual("repaired_pass", summary["verdict"])
        self.assertFalse(summary["can_ingest_routinely"])
        self.assertTrue(summary["can_ingest_with_explicit_repair"])

    def test_hermes_smoke_blocks_repaired_json_ingest_without_exception(self) -> None:
        hermes_payload = {
            "memory_patches": [
                {
                    "claim": "Hermes can propose supported low-risk learning.",
                    "evidence": ["trace:test"],
                    "confidence": 0.8,
                    "sensitivity": "low",
                    "scope": "project_architecture",
                    "needs_user_confirmation": False,
                }
            ]
        }
        hermes_status = {
            "version_ok": True,
            "profile_exists": True,
            "config_exists": True,
            "soul_guardrail_ok": True,
            "model_context_length": 65536,
            "hermes_minimum_context_length": 64000,
            "model_endpoint_checked": True,
            "model_endpoint_reachable": True,
            "model_base_url": "http://127.0.0.1:8095/v1",
            "command": "/usr/bin/hermes",
            "profile_home": "/tmp/hermes-evelearning",
            "status": "available_proposal_only",
        }
        completed = SimpleNamespace(
            returncode=0,
            stdout=f"```json\n{json.dumps(hermes_payload)}\n```",
            stderr="",
        )

        with patch("eve.detect_hermes_learning_organ", return_value=hermes_status), patch(
            "eve.subprocess.run",
            return_value=completed,
        ), patch("eve.write_hermes_run_record", side_effect=lambda record: record), patch(
            "eve.append_governance_proposal",
            side_effect=AssertionError("repaired JSON must not be ingested without an explicit exception"),
        ):
            record = eve.run_hermes_smoke(
                trace_payload=eve.default_hermes_smoke_trace(),
                ingest=True,
                repair_json=True,
                allow_repaired_ingest=False,
            )

        self.assertEqual("blocked_repaired_ingest", record["status"])
        self.assertTrue(record["json_repair_used"])
        self.assertFalse(record["strict_json_ok"])
        self.assertFalse(record["stored_governance_proposals"])
        self.assertEqual(1, record["proposal_count"])

    def test_hermes_smoke_can_use_constrained_json_runner(self) -> None:
        hermes_payload = {
            "memory_patches": [
                {
                    "claim": "Hermes can emit strict governed proposal JSON.",
                    "evidence": ["trace:test"],
                    "confidence": 0.8,
                    "sensitivity": "low",
                    "scope": "project_architecture",
                    "needs_user_confirmation": False,
                }
            ]
        }
        hermes_status = {
            "version_ok": True,
            "profile_exists": True,
            "config_exists": True,
            "soul_guardrail_ok": True,
            "model_context_length": 65536,
            "hermes_minimum_context_length": 64000,
            "model_endpoint_checked": True,
            "model_endpoint_reachable": True,
            "model_base_url": "http://127.0.0.1:8095/v1",
            "command": "/usr/bin/hermes",
            "profile_home": "/tmp/hermes-evelearning",
            "status": "available_proposal_only",
        }
        completed = SimpleNamespace(returncode=0, stdout=json.dumps(hermes_payload), stderr="")

        with patch("eve.detect_hermes_learning_organ", return_value=hermes_status), patch(
            "eve.run_hermes_constrained_json_chat",
            return_value=completed,
        ), patch("eve.write_hermes_run_record", side_effect=lambda record: record):
            record = eve.run_hermes_smoke(
                trace_payload=eve.default_hermes_smoke_trace(),
                repair_json=False,
                constrained_json=True,
            )

        self.assertEqual("passed_with_warnings", record["status"])
        self.assertTrue(record["constrained_json"])
        self.assertTrue(record["strict_json_ok"])
        self.assertFalse(record["json_repair_used"])
        self.assertEqual(1, record["proposal_count"])

    def test_hermes_constrained_json_budget_fits_one_governed_envelope(self) -> None:
        model_config = eve.hermes_local_lab_model_config()

        self.assertEqual("1200", model_config["max_tokens"])
        self.assertGreaterEqual(int(model_config["max_tokens"]), 1024)

    def test_hermes_constrained_smoke_rejects_concatenated_objects(self) -> None:
        payload = {
            "memory_patches": [
                {
                    "claim": "One bounded claim.",
                    "evidence": ["trace:test"],
                    "confidence": 0.8,
                    "sensitivity": "low",
                    "scope": "project_architecture",
                    "needs_user_confirmation": False,
                }
            ]
        }
        hermes_status = {
            "version_ok": True,
            "profile_exists": True,
            "config_exists": True,
            "soul_guardrail_ok": True,
            "model_context_length": 65536,
            "hermes_minimum_context_length": 64000,
            "model_endpoint_checked": True,
            "model_endpoint_reachable": True,
            "model_base_url": "http://127.0.0.1:8095/v1",
            "command": "/usr/bin/hermes",
            "profile_home": "/tmp/hermes-evelearning",
            "status": "available_proposal_only",
        }
        serialized = json.dumps(payload)
        completed = SimpleNamespace(returncode=0, stdout=serialized + serialized, stderr="")

        with patch("eve.detect_hermes_learning_organ", return_value=hermes_status), patch(
            "eve.run_hermes_constrained_json_chat",
            return_value=completed,
        ), patch("eve.write_hermes_run_record", side_effect=lambda record: record):
            record = eve.run_hermes_smoke(
                trace_payload=eve.default_hermes_smoke_trace(),
                repair_json=False,
                constrained_json=True,
            )

        self.assertEqual("failed_invalid_json", record["status"])
        self.assertFalse(record["strict_json_ok"])
        self.assertFalse(record["stored_governance_proposals"])

    def test_hermes_post_task_trace_uses_recent_evidence(self) -> None:
        with patch(
            "eve.read_action_executions",
            return_value=[
                {
                    "id": "act-1",
                    "action": "model_exercise",
                    "tree_status": "SUCCESS",
                    "verification_ok": True,
                    "summary": "All five lanes responded.",
                }
            ],
        ), patch(
            "eve.read_experience_events",
            return_value=[
                {
                    "id": "exp-1",
                    "event_type": "consolidation",
                    "summary": "Hermes strict JSON now works through the constrained adapter.",
                    "learning": "Use constrained JSON for routine proposal intake.",
                }
            ],
        ), patch(
            "eve.read_evidence_ledger",
            return_value=[
                {
                    "id": "ev-1",
                    "kind": "test_result",
                    "claim": "Governance tests passed.",
                    "confidence": 0.9,
                }
            ],
        ), patch("eve.read_governance_events", return_value=[]), patch(
            "eve.read_governance_proposals",
            return_value=[
                {
                    "id": "prop-1",
                    "type": "MemoryPatchProposal",
                    "source": "hermes",
                    "review": {"decision": "accept"},
                    "approval": {"status": "unreviewed"},
                }
            ],
        ):
            trace = eve.build_hermes_post_task_trace(task_id="task-test", limit=3)

        self.assertEqual("task-test", trace["task_id"])
        rendered = json.dumps(trace)
        self.assertIn("model_exercise", rendered)
        self.assertIn("Governance tests passed", rendered)
        self.assertIn("prop-1", rendered)
        self.assertIn("Do not write Eve memory directly", rendered)

    def test_hermes_trace_propose_uses_post_task_trace_runner(self) -> None:
        trace = eve.build_hermes_post_task_trace(task_id="task-test", limit=1)
        smoke_record = {
            "status": "passed",
            "id": "hermes-smoke-test",
            "stored_governance_proposals": False,
            "strict_json_ok": True,
            "json_repair_used": False,
            "constrained_json": True,
            "summary": "ok",
        }

        with patch("eve.build_hermes_post_task_trace", return_value=trace) as build_trace, patch(
            "eve.run_hermes_smoke",
            return_value=smoke_record,
        ) as run_smoke, patch("sys.stdout"):
            code = eve.main(["hermes", "trace-propose", "--task-id", "task-test", "--no-local-64k-lab"])

        self.assertEqual(0, code)
        build_trace.assert_called_once()
        self.assertEqual(trace, run_smoke.call_args.kwargs["trace_payload"])
        self.assertTrue(run_smoke.call_args.kwargs["constrained_json"])

    def test_hermes_inventory_marks_default_profile_blocked_and_lab_route(self) -> None:
        hermes_status = {
            "status": "available_proposal_only_context_below_hermes_minimum",
            "model_endpoint_reachable": True,
            "model_context_length": 16384,
            "hermes_minimum_context_length": 64000,
            "skills_count": 83,
        }

        def fake_command(args, **kwargs):
            command = " ".join(args)
            stdout = "No MCP servers configured." if command == "mcp list" else ""
            if command == "gateway status":
                stdout = "Gateway is not running"
            if command == "cron list":
                stdout = "No scheduled jobs."
            return {"ok": True, "returncode": 0, "stdout": stdout, "stderr": "", "stdout_preview": stdout, "stderr_preview": ""}

        with patch("eve.detect_hermes_learning_organ", return_value=hermes_status), patch(
            "eve.hermes_local_lab_status",
            return_value={"ok": False, "context_length": 65536},
        ), patch("eve.run_hermes_profile_command", side_effect=fake_command):
            inventory = eve.build_hermes_capability_inventory(save=False)

        self.assertFalse(inventory["default_profile_ready_for_serious_learning"])
        self.assertEqual("local_64k_lab_constrained_json", inventory["serious_learning_route"])
        families = {item["id"]: item for item in inventory["capability_families"]}
        self.assertEqual("default_blocked_use_local_64k_lab", families["model_route"]["status"])
        self.assertTrue(families["skills"]["admission_required_before_use"])

    def test_hermes_inventory_classifies_current_extended_feature_surfaces(self) -> None:
        def command(stdout="", *, ok=True):
            return {
                "ok": ok,
                "returncode": 0 if ok else 1,
                "stdout": stdout,
                "stderr": "",
                "stdout_preview": stdout,
                "stderr_preview": "",
            }

        commands = {
            "version_detail": command("Hermes Agent v0.18.2\nUpdate available: 265 commits"),
            "config_check": command("Config version: 33\nCurrent version: 33\nConfiguration is current"),
            "security_audit": command(
                json.dumps(
                    {
                        "finding_count": 46,
                        "findings": [
                            {"severity": "HIGH"},
                            {"severity": "MODERATE"},
                        ]
                        + [{"severity": "UNKNOWN"}] * 44,
                    }
                )
            ),
            "tools_summary": command("tools available"),
            "skills_list_enabled": command("skills enabled"),
            "curator_status": command("Curator: enabled\nRuns: 0"),
            "curator_usage": command("Agent-created: 17"),
            "plugins_list": command("No plugins enabled"),
            "memory_status": command("Memory available"),
            "insights": command("No sessions found"),
            "journey": command(json.dumps({"stats": {"nodes": 0}})),
            "checkpoints_status": command("0 B"),
            "mcp_list": command("No MCP servers configured."),
            "acp_check": command("ACP dependencies OK"),
            "moa_list": command("Active in config: (off)"),
            "fallback_list": command("No fallback providers configured"),
            "project_list": command("No projects yet"),
            "kanban_boards": command("default (empty)"),
            "profile_list": command("evelearning"),
            "computer_use_status": command("Computer-use driver not installed"),
            "prompt_size": command("context length 16384", ok=False),
            "hooks_list": command("No shell hooks configured"),
            "cron_list": command("No scheduled jobs."),
            "gateway_status": command("Gateway is not running"),
            "sessions_list": command("No sessions"),
        }
        status = {
            "status": "available_proposal_only_context_below_hermes_minimum",
            "model_endpoint_reachable": True,
            "model_context_length": 16384,
            "hermes_minimum_context_length": 64000,
            "soul_guardrail_ok": True,
            "model_provider": "custom",
            "model_default": "eve-deep",
            "model_base_url": "http://127.0.0.1:8081/v1",
        }

        families = eve.build_hermes_capability_families(commands, status)
        by_id = {item["id"]: item for item in families}
        policy = eve.build_hermes_feature_policy(
            status=status,
            inventory={
                "capability_families": families,
                "security_summary": {
                    "finding_count": 46,
                    "severity_counts": {"HIGH": 1, "MODERATE": 1, "UNKNOWN": 44},
                    "blocking_severity_count": 2,
                },
            },
            save=False,
        )

        self.assertEqual("current_prompt_blocked_by_default_context", by_id["config_and_prompt_hygiene"]["status"])
        self.assertEqual("findings_46", by_id["supply_chain_security"]["status"])
        self.assertEqual(2, by_id["supply_chain_security"]["blocking_severity_count"])
        self.assertEqual(
            {"HIGH": 1, "MODERATE": 1, "UNKNOWN": 44},
            by_id["supply_chain_security"]["severity_counts"],
        )
        self.assertEqual("update_available_265_commits", by_id["source_update"]["status"])
        self.assertEqual("enabled_runs_0", by_id["skill_curator"]["status"])
        self.assertEqual("available_ready", by_id["acp_editor_bridge"]["status"])
        self.assertEqual("available_inactive", by_id["model_orchestration"]["status"])
        self.assertEqual("available_driver_missing", by_id["computer_use"]["status"])
        self.assertEqual("watch", policy["status"])
        self.assertIn("46 known vulnerability", "\n".join(policy["watch_items"]))
        self.assertIn("blocking=2", "\n".join(policy["watch_items"]))
        self.assertIn("265 upstream commits", "\n".join(policy["watch_items"]))

    def test_hermes_feature_policy_keeps_shiny_features_proposal_only(self) -> None:
        status = {
            "status": "available_proposal_only_context_below_hermes_minimum",
            "soul_guardrail_ok": True,
            "model_provider": "custom",
            "model_default": "eve-deep",
            "model_base_url": "http://127.0.0.1:8081/v1",
            "model_context_length": 16384,
        }
        inventory = {
            "capability_families": [
                {"id": "model_route", "status": "default_blocked_use_local_64k_lab"},
                {"id": "skills", "status": "available"},
                {"id": "plugins", "status": "available_none_enabled"},
                {"id": "mcp", "status": "available_not_configured"},
                {"id": "gateway_messaging", "status": "available_stopped"},
                {"id": "cron_hooks", "status": "available_not_configured"},
                {"id": "browser_voice_media_code_rl", "status": "available_with_credentials_or_tools"},
                {"id": "memory_and_session_search", "status": "available_builtin_only"},
            ]
        }

        policy = eve.build_hermes_feature_policy(status=status, inventory=inventory, save=False)
        features = {item["id"]: item for item in policy["features"]}

        self.assertEqual("clear", policy["status"])
        self.assertEqual(0, policy["summary"]["direct_eve_authority_count"])
        self.assertTrue(features["identity_profile_soul"]["allowed_now"])
        self.assertFalse(features["approval_bypass_modes"]["allowed_now"])
        self.assertFalse(features["skills_slash_commands"]["allowed_now"])
        self.assertFalse(features["gateway_messaging"]["allowed_now"])
        self.assertFalse(features["cron_webhooks"]["allowed_now"])
        self.assertFalse(features["voice_mode"]["allowed_now"])
        self.assertEqual("admission_required", features["skills_slash_commands"]["posture"])

    def test_hermes_feature_policy_flags_gateway_cron_provider_drift(self) -> None:
        status = {
            "status": "available_proposal_only",
            "soul_guardrail_ok": False,
            "model_provider": "openrouter",
            "model_default": "remote-model",
            "model_base_url": "https://openrouter.ai/api/v1",
            "model_context_length": 128000,
        }
        inventory = {
            "capability_families": [
                {"id": "model_route", "status": "default_ready"},
                {"id": "skills", "status": "available"},
                {"id": "plugins", "status": "enabled"},
                {"id": "mcp", "status": "configured"},
                {"id": "gateway_messaging", "status": "running"},
                {"id": "cron_hooks", "status": "configured"},
                {"id": "browser_voice_media_code_rl", "status": "available_with_credentials_or_tools"},
                {"id": "memory_and_session_search", "status": "available_builtin_only"},
            ]
        }

        policy = eve.build_hermes_feature_policy(status=status, inventory=inventory, save=False)
        rendered_watches = "\n".join(policy["watch_items"])

        self.assertEqual("watch", policy["status"])
        self.assertIn("SOUL guardrail", rendered_watches)
        self.assertIn("non-local provider", rendered_watches)
        self.assertIn("gateway is running", rendered_watches)
        self.assertIn("cron jobs are configured", rendered_watches)
        self.assertIn("MCP servers are configured", rendered_watches)
        self.assertIn("plugins appear enabled", rendered_watches)


    def test_hermes_temp_profile_symlinks_static_skills_to_avoid_docs_noise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source_profile"
            runs = root / "runs"
            skills = source / "skills" / "research"
            skills.mkdir(parents=True)
            (skills / "SKILL.md").write_text("# Skill\n", encoding="utf-8")
            (source / "SOUL.md").write_text("# Soul\n", encoding="utf-8")
            (source / "config.yaml").write_text("model: old\n", encoding="utf-8")
            (source / "sessions").mkdir()

            with patch.object(eve, "HERMES_EVE_PROFILE_HOME", source), patch.object(eve, "HERMES_RUNS_DIR", runs):
                profile = eve.prepare_hermes_temp_profile("run-1", {"default": "local", "provider": "custom"})

            self.assertTrue((profile / "SOUL.md").exists())
            self.assertTrue((profile / "config.yaml").exists())
            self.assertTrue((profile / "skills").is_symlink())
            self.assertEqual((source / "skills").resolve(), (profile / "skills").resolve())
            self.assertTrue((profile / "skills" / "research" / "SKILL.md").exists())

    def test_hermes_skill_admission_builds_reviewed_skill_patch_without_enablement(self) -> None:
        report = eve.evaluate_hermes_skill_admission_request(
            skill_name="research/arxiv",
            purpose="Let Hermes propose research-summary skill updates for Eve's lab traces.",
            tests=["python3 eve.py hermes smoke --local-64k-lab --constrained-json --full"],
            evidence=["docs/operating/HERMES_LEARNING_ORGAN_INTEGRATION_2026_04_29.md"],
            permission_class="read_only",
        )

        self.assertEqual("ready_for_governance_queue", report["status"])
        self.assertFalse(report["enabled_for_eve"])
        proposal = report["proposal"]
        self.assertEqual("SkillPatchProposal", proposal["type"])
        self.assertEqual("accept", proposal["review"]["decision"])
        self.assertIn("tests", proposal["payload"])

    def test_hermes_skill_admission_blocks_missing_tests(self) -> None:
        report = eve.evaluate_hermes_skill_admission_request(
            skill_name="spotify",
            purpose="Control media playback.",
            tests=[],
            evidence=["hermes plugins list"],
            permission_class="credentialed",
        )

        self.assertEqual("blocked_missing_admission_requirements", report["status"])
        self.assertIn("tests_required", report["blockers"])
        self.assertFalse(report["enabled_for_eve"])


if __name__ == "__main__":
    unittest.main()
