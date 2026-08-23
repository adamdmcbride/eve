import base64
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import eve
import eve_capability_adoption as adoption


def matrix(*records):
    return {"updated_at": "2026-07-20T00:00:00+00:00", "capabilities": list(records)}


def capability(
    capability_id,
    name,
    *,
    available=True,
    callable=True,
    verified=True,
    needs_permission=False,
    category="tool",
    evidence=None,
):
    return {
        "id": capability_id,
        "name": name,
        "category": category,
        "available": available,
        "callable": callable,
        "verified": verified,
        "needs_permission": needs_permission,
        "next_acquisition_step": "Use the existing typed path and verify it.",
        "evidence": evidence or {},
    }


def review(state="candidate", *, visible=True):
    return {
        "id": "release:example-agent@v2.0.0",
        "repository": "example/agent",
        "component_id": "example-agent",
        "component_name": "Example Agent",
        "target_version": "v2.0.0",
        "installed_version": "1.0.0",
        "state": state,
        "visible_in_current_feed": visible,
        "classification_reason": "A newer release exists for the installed component.",
        "feature_summary": "Adds durable task recovery and tool tracing.",
        "required_gate": "Stage it and run the component contract.",
        "first_seen_at": "2026-07-20T00:00:00+00:00",
    }


class CapabilityAdoptionPureTests(unittest.TestCase):
    def test_generic_adoption_verbs_do_not_make_ledger_observation_credible(self):
        match = adoption.match_score(
            "Evaluate and adopt Langfuse v4.14.1",
            {
                "id": "ledger.release-observation",
                "name": "Review and adopt component updates",
                "category": "remembered_capability",
            },
        )
        self.assertFalse(match["credible"])

    def test_callable_existing_capability_wins_over_build(self):
        result = adoption.resolve_capability_first(
            "search the public web",
            matrix(capability("tool.web_search", "web search", evidence={"description": "Search public web pages"})),
            {"feature_reviews": []},
        )
        self.assertEqual("use_existing", result["classification"])
        self.assertEqual("tool.web_search", result["matched_capability"]["id"])
        self.assertFalse(result["coding_allowed"])

    def test_permissioned_existing_capability_is_not_rebuilt(self):
        result = adoption.resolve_capability_first(
            "send an iMessage",
            matrix(
                capability(
                    "router.openclaw_channel_gateway",
                    "OpenClaw channel gateway",
                    needs_permission=True,
                    category="operational_router",
                    evidence={"description": "Send through an admitted channel such as iMessage"},
                )
            ),
            {"feature_reviews": []},
        )
        self.assertEqual("use_existing_with_permission", result["classification"])
        self.assertEqual("openclaw", result["organ_route"]["primary_organ"])

    def test_visible_but_noncallable_surface_routes_to_admission(self):
        result = adoption.resolve_capability_first(
            "use the browser automation tool",
            matrix(
                capability(
                    "openclaw.browser",
                    "OpenClaw browser automation",
                    available=True,
                    callable=False,
                    verified=True,
                    category="openclaw_native",
                )
            ),
            {"feature_reviews": []},
        )
        self.assertEqual("configure_or_admit_existing", result["classification"])
        self.assertEqual("openclaw", result["organ_route"]["primary_organ"])

    def test_exact_candidate_target_routes_to_isolated_canary(self):
        feature_review = review("candidate")
        result = adoption.resolve_capability_first(
            "Example Agent durable recovery",
            matrix(),
            {"feature_reviews": [feature_review]},
            components=[
                {
                    "id": "example-agent",
                    "name": "Example Agent",
                    "kind": "python_package",
                    "package": "example-agent",
                }
            ],
            target={
                "id": feature_review["id"],
                "feature_review_id": feature_review["id"],
                "component_id": "example-agent",
                "target_version": "v2.0.0",
            },
        )
        self.assertEqual("canary_existing_update", result["classification"])
        self.assertEqual("example-agent", result["matched_component"]["id"])
        self.assertFalse(result["coding_allowed"])

    def test_named_candidate_resolves_without_structured_target(self):
        feature_review = review("candidate")
        result = adoption.resolve_capability_first(
            "Evaluate Example Agent v2.0.0 through Eve",
            matrix(
                capability(
                    "ledger.example-agent",
                    "Example Agent release observation",
                    available=True,
                    callable=False,
                    verified=True,
                    category="event_ledger",
                )
            ),
            {"feature_reviews": [feature_review]},
            components=[
                {
                    "id": "example-agent",
                    "name": "Example Agent",
                    "kind": "python_package",
                    "package": "example-agent",
                }
            ],
        )
        self.assertEqual("canary_existing_update", result["classification"])
        self.assertEqual("example-agent", result["matched_component"]["id"])

    def test_research_only_target_stays_research_only(self):
        feature_review = review("research_only")
        result = adoption.resolve_capability_first(
            "Example Agent durable recovery",
            matrix(),
            {"feature_reviews": [feature_review]},
            target={"id": feature_review["id"], "feature_review_id": feature_review["id"]},
        )
        self.assertEqual("research_existing_upstream", result["classification"])
        self.assertEqual("research_only", result["organ_route"]["authority"])
        self.assertEqual("eve_runtime", result["organ_route"]["primary_organ"])

    def test_historical_release_does_not_suppress_a_real_gap(self):
        historical = review("historical")
        result = adoption.resolve_capability_first(
            "durable task recovery",
            matrix(),
            {"feature_reviews": [historical]},
        )
        self.assertEqual("build_required", result["classification"])
        self.assertEqual({}, result["matched_feature_review"])

    def test_missing_learning_skill_routes_to_hermes(self):
        result = adoption.resolve_capability_first(
            "learn a new preference reflection habit",
            matrix(),
            {"feature_reviews": []},
        )
        self.assertEqual("build_required", result["classification"])
        self.assertEqual("hermes", result["organ_route"]["primary_organ"])

    def test_target_rotation_prioritizes_unattempted_gap_then_candidate(self):
        gap = capability(
            "gap:missing-browser-adapter",
            "Missing browser adapter",
            available=False,
            callable=False,
            verified=False,
            category="capability_gap",
        )
        feature_review = review("candidate")
        first = adoption.select_next_target(matrix(gap), {"feature_reviews": [feature_review]}, [])
        self.assertEqual("capability_gap", first["kind"])
        prior = [{"completed_at": "2026-07-20T01:00:00+00:00", "target": {"id": gap["id"]}}]
        second = adoption.select_next_target(matrix(gap), {"feature_reviews": [feature_review]}, prior)
        self.assertEqual(feature_review["id"], second["id"])

    def test_python_candidate_plan_accepts_normal_semver_only(self):
        plan = adoption.python_candidate_plan(
            review("candidate"),
            {"id": "example-agent", "kind": "python_package", "package": "example-agent"},
        )
        self.assertTrue(plan["eligible"])
        self.assertEqual("example-agent==2.0.0", plan["requirement"])
        invalid = adoption.python_candidate_plan(
            {**review("candidate"), "target_version": "release-latest"},
            {"id": "example-agent", "kind": "python_package", "package": "example-agent"},
        )
        self.assertFalse(invalid["eligible"])


class CapabilityOnlineResearchTests(unittest.TestCase):
    def test_official_repository_research_reads_primary_sources(self):
        readme = "# Agent\n\n## Features\n\n## Configuration\n"

        def fetch_json(url, _timeout):
            if url.endswith("/readme"):
                return {
                    "name": "README.md",
                    "sha": "abc",
                    "html_url": "https://github.com/example/agent/blob/main/README.md",
                    "content": base64.b64encode(readme.encode()).decode(),
                }
            if url.endswith("/contents/docs"):
                return [{"name": "config.md", "type": "file", "path": "docs/config.md", "sha": "def"}]
            if "/commits?" in url:
                return [
                    {
                        "sha": "1234567890abcdef",
                        "html_url": "https://github.com/example/agent/commit/123",
                        "commit": {"message": "feat: add recovery", "author": {"date": "2026-07-20T00:00:00Z"}},
                    }
                ]
            return {
                "full_name": "example/agent",
                "description": "An agent runtime",
                "html_url": "https://github.com/example/agent",
                "default_branch": "main",
                "topics": ["agent"],
                "license": {"spdx_id": "MIT"},
            }

        record = adoption.research_repository(
            "example/agent",
            fetch_json=fetch_json,
            fetch_text=lambda _url, _timeout: "",
            researched_at="2026-07-20T00:00:00+00:00",
        )
        self.assertEqual("complete", record["status"])
        self.assertEqual("official_primary_source", record["authority"])
        self.assertEqual(["Agent", "Features", "Configuration"], record["readme"]["headings"])
        self.assertEqual("feat: add recovery", record["recent_commits"][0]["message"])

    def test_repository_discovery_never_becomes_adopted(self):
        record = adoption.discover_repositories(
            "local agent",
            fetch_json=lambda _url, _timeout: {
                "items": [
                    {
                        "full_name": "new/project",
                        "description": "New runtime",
                        "html_url": "https://github.com/new/project",
                        "topics": ["agent"],
                    }
                ]
            },
        )
        self.assertEqual("unverified_discovery_signal", record["authority"])
        self.assertEqual("research_only", record["results"][0]["adoption_state"])


class CapabilityAdoptionEveIntegrationTests(unittest.TestCase):
    def test_dagster_candidate_contract_loads_eves_real_definition(self):
        code = eve.capability_python_candidate_smoke_code(
            "dagster-eve-runtime",
            "dagster",
            "dagster",
        )

        self.assertIn("dagster_lab.eve_evidence_defs", code)
        self.assertIn("eve_definition_load", code)

    def test_deepeval_candidate_contract_exercises_agent_metrics_without_a_model(self):
        code = eve.capability_python_candidate_smoke_code(
            "deepeval-eve-runtime",
            "deepeval",
            "deepeval",
        )

        self.assertIn("AgentLoopDetectionMetric", code)
        self.assertIn("ToolPermissionMetric", code)
        self.assertIn("deterministic_agent_loop_detection", code)
        self.assertIn("deterministic_tool_permission", code)
        self.assertIn("inspect.signature(loop_metric.measure)", code)
        self.assertIn('loop_measure_kwargs["_log_metric_to_confident"] = False', code)

    def test_candidate_canary_rebuilds_when_prior_python_provenance_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_python = root / "source" / ".venv" / "bin" / "python"
            source_python.parent.mkdir(parents=True)
            source_python.write_text("#!/bin/sh\n", encoding="utf-8")
            source_python.chmod(0o755)
            stage_dir = root / "stage"
            stale_python = stage_dir / ".venv" / "bin" / "python"
            stale_python.parent.mkdir(parents=True)
            stale_python.write_text("#!/bin/sh\n", encoding="utf-8")
            stale_python.chmod(0o755)
            commands = []

            def run_component(command, timeout=10):
                del timeout
                commands.append(command)
                if command[1:3] == ["venv", "--python"]:
                    rebuilt_python = stage_dir / ".venv" / "bin" / "python"
                    rebuilt_python.parent.mkdir(parents=True, exist_ok=True)
                    rebuilt_python.write_text("#!/bin/sh\n", encoding="utf-8")
                    rebuilt_python.chmod(0o755)
                    return subprocess.CompletedProcess(command, 0, "", ""), ""
                if command[1:3] == ["pip", "install"]:
                    return subprocess.CompletedProcess(command, 0, "", ""), ""
                return subprocess.CompletedProcess(
                    command,
                    0,
                    json.dumps(
                        {
                            "package": "ragas",
                            "version": "0.4.3",
                            "module": "ragas",
                            "checks": ["import", "evaluation_dataset_api"],
                            "python_executable": str(stage_dir / ".venv" / "bin" / "python"),
                            "python_version": [3, 14, 0],
                        }
                    ),
                    "",
                ), ""

            resolution = {
                "matched_feature_review": {
                    "component_id": "ragas-eve-runtime",
                    "target_version": "0.4.3",
                    "installed_version": "0.3.2",
                },
                "matched_component": {
                    "id": "ragas-eve-runtime",
                    "kind": "python_package",
                    "package": "ragas",
                    "python_command": [str(root / "runtime" / ".venv" / "bin" / "python")],
                },
            }
            prior_without_interpreter_provenance = {
                "status": "passed",
                "requirement": "ragas==0.4.3",
            }
            with patch.object(eve, "resolve_component_python_command", return_value=[str(source_python)]), patch.object(
                eve, "capability_candidate_stage_dir", return_value=stage_dir
            ), patch.object(eve.eve_store, "load_json_dict", return_value=prior_without_interpreter_provenance), patch.object(
                eve.eve_store, "write_json_dict"
            ), patch.object(eve.shutil, "which", return_value="/usr/bin/uv"), patch.object(
                eve, "run_component_command", side_effect=run_component
            ):
                result = eve.run_capability_candidate_canary(
                    dict(eve.DEFAULT_CONFIG),
                    resolution,
                    timeout=120,
                    source="test",
                )

        self.assertEqual("passed", result["status"])
        self.assertEqual(str(source_python), result["base_python"])
        self.assertTrue(result["canary_contract_hash"])
        self.assertFalse(result.get("reused", False))
        self.assertEqual(str(source_python), commands[0][3])

    def test_codex_handoff_contains_capability_first_preflight(self):
        config = dict(eve.DEFAULT_CONFIG)
        config["_codex_handoff_objective"] = "Implement a missing teleport adapter"
        preflight = {
            "schema_id": adoption.RESOLUTION_SCHEMA_ID,
            "id": "resolution-1",
            "objective": config["_codex_handoff_objective"],
            "classification": "build_required",
            "confidence": 0.9,
            "reason": "No existing path.",
            "recommended_action": "Build the bounded adapter.",
            "coding_allowed": True,
            "existing_path_found": False,
            "organ_route": {"owner": "eve", "primary_organ": "codex", "supporting_organs": []},
        }
        config["_codex_handoff_capability_resolution"] = preflight
        body = eve.build_codex_independent_handoff_body(config, source="test")
        self.assertIn("Capability-first preflight", body["body"])
        self.assertIn("build_required", body["body"])
        self.assertIn("Write implementation code only when", body["body"])
        self.assertEqual("build_required", body["capability_preflight"]["classification"])

    def test_cycle_resolves_without_side_effects_when_canary_and_handoff_disabled(self):
        fake_matrix = matrix()
        with patch.object(eve, "ensure_store"), patch.object(
            eve, "read_capability_adoption_history", return_value=[]
        ), patch.object(eve, "build_capability_matrix", return_value=fake_matrix), patch.object(
            eve, "load_capability_intelligence", return_value={"feature_reviews": []}
        ), patch.object(eve, "component_watchlist", return_value=[]), patch.object(
            eve, "load_agent_capability_radar", return_value={}
        ), patch.object(
            eve, "save_capability_adoption_cycle", return_value={"counts": {"cycles": 1}}
        ):
            cycle = eve.run_capability_adoption_cycle(
                dict(eve.DEFAULT_CONFIG),
                objective="teleport the Mac",
                source="test",
                include_online_research=False,
                run_canary=False,
                create_build_handoff=False,
            )
        self.assertEqual("build_required", cycle["resolution"]["classification"])
        self.assertEqual({}, cycle["build_handoff"])
        self.assertFalse(cycle["live_environment_changed"])

    def test_passed_isolated_candidate_queues_owned_promotion_work(self):
        feature_review = review("candidate")
        components = [
            {
                "id": "example-agent",
                "name": "Example Agent",
                "kind": "python_package",
                "package": "example-agent",
            }
        ]
        passed_canary = {
            "status": "passed",
            "executed": True,
            "verification_ok": True,
            "summary": "isolated candidate passed",
            "permissions_used": ["public_package_download"],
        }
        handoff = {"status": "created", "message_id": "message-1", "thread_id": "thread-1"}
        with patch.object(eve, "ensure_store"), patch.object(
            eve, "read_capability_adoption_history", return_value=[]
        ), patch.object(eve, "build_capability_matrix", return_value=matrix()), patch.object(
            eve, "load_capability_intelligence", return_value={"feature_reviews": [feature_review]}
        ), patch.object(eve, "component_watchlist", return_value=components), patch.object(
            eve, "load_agent_capability_radar", return_value={}
        ), patch.object(eve, "run_capability_candidate_canary", return_value=passed_canary), patch.object(
            eve, "create_capability_build_handoff", return_value=handoff
        ) as create_handoff, patch.object(
            eve, "create_system_task", return_value={"id": "task-1"}
        ) as create_task, patch.object(eve, "mirror_store_file_to_runtime"), patch.object(
            eve, "save_capability_adoption_cycle", return_value={"counts": {"cycles": 1}}
        ):
            cycle = eve.run_capability_adoption_cycle(
                dict(eve.DEFAULT_CONFIG),
                objective="Example Agent durable recovery",
                source="test",
                include_online_research=False,
                run_canary=True,
                create_build_handoff=True,
            )
        self.assertEqual("canary_existing_update", cycle["resolution"]["classification"])
        self.assertEqual("eve_runtime", cycle["organ_assignment"]["primary_organ"])
        self.assertEqual("task-1", cycle["build_handoff"]["system_task_id"])
        self.assertFalse(cycle["live_environment_changed"])
        self.assertTrue(create_handoff.call_args.kwargs["promotion"])
        self.assertEqual("capability_runtime_integration", create_task.call_args.args[0]["kind"])

    def test_capability_matrix_exposes_self_development_surface(self):
        state = {
            "updated_at": "2026-07-20T00:00:00+00:00",
            "summary": "One cycle completed.",
            "counts": {"cycles": 1},
            "latest_cycle": {
                "id": "cycle-1",
                "completed_at": "2026-07-20T00:00:00+00:00",
                "resolution": {"classification": "use_existing"},
            },
        }
        with patch.object(eve, "read_action_executions", return_value=[]), patch.object(
            eve, "read_capability_gaps", return_value=[]
        ), patch.object(eve, "load_agent_capability_radar", return_value={}), patch.object(
            eve, "load_agent_integration_state", return_value={}
        ), patch.object(eve, "read_developmental_cycles", return_value=[]), patch.object(
            eve, "load_capability_adoption_state", return_value=state
        ), patch.object(eve, "load_runtime_identity", return_value={}), patch.object(
            eve.eve_openclaw_body, "read_openclaw_action_router_events", return_value=[]
        ), patch.object(eve.eve_openclaw_body, "read_openclaw_channel_events", return_value=[]):
            result = eve.build_capability_matrix(dict(eve.DEFAULT_CONFIG), prefer_runtime=False)
        record = next(
            item
            for item in result["capabilities"]
            if item["id"] == "system.capability_first_self_development"
        )
        self.assertTrue(record["available"])
        self.assertTrue(record["callable"])
        self.assertTrue(record["verified"])


if __name__ == "__main__":
    unittest.main()
