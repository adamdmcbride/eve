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
    def test_explicit_package_anchor_prevents_high_overlap_wrong_capability(self):
        wrong = capability(
            "surface.eve_chat_same_thread_followup",
            "Eve Chat same-thread deferred follow-up",
            category="conversation_delivery",
            evidence={
                "description": (
                    "Execute one bounded operational action tree, verify its consequence, "
                    "and record the result in the original thread."
                )
            },
        )
        correct = capability(
            "integration.durable-task-execution",
            "Durable task execution",
            available=False,
            callable=False,
            verified=False,
            category="agent_integration",
            evidence={"local_surfaces": ["py_trees operational action tree"]},
        )

        result = adoption.resolve_capability_first(
            "verify py_trees 2.4 operational action trees execute and record consequences",
            matrix(wrong, correct),
            {"feature_reviews": []},
        )

        self.assertEqual("configure_or_admit_existing", result["classification"])
        self.assertEqual("integration.durable-task-execution", result["matched_capability"]["id"])
        wrong_match = adoption.match_score(result["objective"], wrong)
        self.assertEqual(["pytrees"], wrong_match["missing_identifier_anchors"])
        self.assertFalse(wrong_match["credible"])

    def test_matching_explicit_package_anchor_is_credible_with_sparse_prose(self):
        match = adoption.match_score(
            "verify py_trees 2.4 compatibility",
            {
                "id": "integration.durable-task-execution",
                "name": "Durable task execution",
                "evidence": {"local_surfaces": ["py_trees operational action tree"]},
            },
        )

        self.assertEqual(["pytrees"], match["matched_identifier_anchors"])
        self.assertEqual([], match["missing_identifier_anchors"])
        self.assertTrue(match["credible"])

    def test_natural_hyphenated_modifier_is_not_a_package_anchor(self):
        match = adoption.match_score(
            "use local-only Langfuse tracing",
            {
                "id": "eve:oss:langfuse",
                "name": "Langfuse",
                "evidence": {"purpose": "local trace observability"},
            },
        )

        self.assertNotIn("localonly", match["identifier_anchors"])
        self.assertTrue(match["credible"])

    def test_proposal_only_and_tool_less_are_not_package_anchors(self):
        match = adoption.match_score(
            "keep Hermes proposal-only with tool-less constrained execution",
            {
                "id": "hermes:tools_toolsets",
                "subsystem": "hermes",
                "family": "tools_toolsets",
                "current_state": "broad_cli_authority_enabled",
                "decision": "defer",
                "configuration_action": "Use the constrained adapter and disable ordinary CLI toolsets.",
            },
        )

        self.assertNotIn("proposalonly", match["identifier_anchors"])
        self.assertNotIn("toolless", match["identifier_anchors"])
        self.assertTrue(match["credible"])

    def test_generic_slash_list_is_not_a_repository_anchor(self):
        match = adoption.match_score(
            "Langfuse model/tool/memory provenance",
            {
                "id": "eve:oss:langfuse",
                "name": "Langfuse",
                "evidence": {"purpose": "model and tool trace provenance"},
            },
        )

        self.assertNotIn("modeltoolmemory", match["identifier_anchors"])
        self.assertTrue(match["credible"])

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

    def test_installed_feature_family_prevents_false_build_required(self):
        result = adoption.resolve_capability_first(
            "local-only Langfuse tracing with model tool and memory provenance and no hosted export",
            matrix(
                capability(
                    "ledger.generic-local-model",
                    "Run multiple local model lanes",
                    available=True,
                    callable=False,
                    verified=True,
                    category="remembered_capability",
                    evidence={"statement": "Local model, tool, and memory work."},
                )
            ),
            {
                "feature_reviews": [],
                "feature_family_reviews": [
                    {
                        "id": "eve:oss:langfuse",
                        "subsystem": "eve",
                        "family": "oss:langfuse",
                        "current_state": "installed_importable:4.14.4",
                        "decision": "use_existing",
                        "rationale": "Local trace observability SDK installed for redacted model and tool provenance.",
                        "configuration_action": "Use the existing bounded local lab path and require a local endpoint before export.",
                        "authority_boundary": "Observability only; no hosted export or scheduler authority.",
                    }
                ],
            },
        )

        self.assertEqual("configure_or_admit_existing", result["classification"])
        self.assertEqual("eve:oss:langfuse", result["matched_feature_family"]["id"])
        self.assertEqual(
            "ledger.generic-local-model",
            result["evidence"]["shadowed_capability_id"],
        )
        self.assertEqual("existing_feature_family", result["organ_route"]["authority"])
        self.assertFalse(result["coding_allowed"])
        self.assertIn("existing bounded local lab path", result["recommended_action"])

    def test_hermes_tool_authority_objective_routes_to_existing_configuration(self):
        result = adoption.resolve_capability_first(
            "keep Hermes proposal-only by disabling ordinary CLI tool authority and requiring tool-less constrained proposal generation",
            matrix(),
            {
                "feature_reviews": [],
                "feature_family_reviews": [
                    {
                        "id": "hermes:tools_toolsets",
                        "subsystem": "hermes",
                        "family": "tools_toolsets",
                        "current_state": "broad_cli_authority_enabled",
                        "decision": "defer",
                        "rationale": "Hermes ordinary CLI exposes tool authority outside Eve's constrained adapter.",
                        "configuration_action": "Back up the Hermes profile, disable ordinary CLI toolsets, verify, and restore-test.",
                        "authority_boundary": "Eve-owned Hermes paths use enabled_toolsets=[] and strict proposal JSON.",
                    }
                ],
            },
        )

        self.assertEqual("configure_or_admit_existing", result["classification"])
        self.assertEqual("hermes:tools_toolsets", result["matched_feature_family"]["id"])
        self.assertEqual("hermes", result["organ_route"]["primary_organ"])
        self.assertFalse(result["coding_allowed"])

    def test_verified_callable_feature_family_routes_to_use_existing(self):
        result = adoption.resolve_capability_first(
            "search the OpenClaw memory wiki",
            matrix(),
            {
                "feature_reviews": [],
                "feature_family_reviews": [
                    {
                        "id": "openclaw:memory_wiki",
                        "subsystem": "openclaw",
                        "family": "memory_wiki",
                        "current_state": "resident_callable",
                        "decision": "use_existing",
                        "configuration_action": "Call the existing resident wiki search tool.",
                        "lifecycle": {
                            "stage": "verified",
                            "callable_now": True,
                            "consequence_verified": True,
                        },
                    }
                ],
            },
        )

        self.assertEqual("use_existing", result["classification"])
        self.assertEqual("openclaw", result["organ_route"]["primary_organ"])
        self.assertFalse(result["coding_allowed"])

    def test_detailed_workflow_objective_resolves_existing_integrated_family_bundle(self):
        objective = (
            "turn Eve's curated verified episodes into a reproducible local adapter experiment "
            "with private holdout, DVC snapshot, no downloads, and shadow promotion evidence"
        )
        result = adoption.resolve_capability_first(
            objective,
            matrix(
                capability(
                    "ledger.generic-training-note",
                    "Local verified training evidence",
                    available=True,
                    callable=False,
                    verified=True,
                    category="remembered_capability",
                )
            ),
            {
                "feature_reviews": [],
                "feature_family_reviews": [
                    {
                        "id": "eve:oss:peft",
                        "subsystem": "eve",
                        "family": "oss:peft",
                        "current_state": "installed_importable:0.20.0",
                        "decision": "use_existing",
                        "rationale": "LoRA adapter experiments from verified Eve episodes.",
                        "configuration_action": "Use the existing bounded trainer lab.",
                    },
                    {
                        "id": "eve:oss:dvc",
                        "subsystem": "eve",
                        "family": "oss:dvc",
                        "current_state": "installed_importable:3.67.1",
                        "decision": "use_existing",
                        "rationale": "Version curated adapter datasets after private holdout splitting.",
                        "configuration_action": "Run the no-upload snapshot and restore canary.",
                    },
                    {
                        "id": "eve:organ:oss_improvement_substrate",
                        "subsystem": "eve",
                        "family": "organ:oss_improvement_substrate",
                        "current_state": "working",
                        "decision": "configure",
                        "rationale": (
                            "Unify local curated adapter datasets, DVC manifests, trainer recipes, "
                            "and promotion evidence as a governed self-improvement organ."
                        ),
                        "configuration_action": "Repair the organ contract before adding a replacement.",
                    },
                ],
            },
        )

        self.assertEqual("configure_or_admit_existing", result["classification"])
        self.assertEqual(
            "eve:organ:oss_improvement_substrate",
            result["matched_feature_family"]["id"],
        )
        self.assertFalse(result["coding_allowed"])
        self.assertGreaterEqual(
            len(result["feature_family_match"]["high_signal_overlap"]),
            3,
        )
        self.assertEqual(
            {
                "eve:oss:peft",
                "eve:oss:dvc",
                "eve:organ:oss_improvement_substrate",
            },
            {item["id"] for item in result["capability_bundle"]},
        )

    def test_verbose_generic_objective_does_not_match_on_low_signal_words(self):
        result = adoption.resolve_capability_first(
            "create a reproducible local watercolor animation with verified current evidence",
            matrix(),
            {
                "feature_reviews": [],
                "feature_family_reviews": [
                    {
                        "id": "eve:organ:oss_improvement_substrate",
                        "subsystem": "eve",
                        "family": "organ:oss_improvement_substrate",
                        "current_state": "working",
                        "decision": "configure",
                        "rationale": "Local current verified evidence for software improvement.",
                    }
                ],
            },
        )

        self.assertEqual("build_required", result["classification"])
        self.assertEqual([], result["capability_bundle"])

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

    def test_target_rotation_does_not_treat_eves_reply_as_build_authority(self):
        hallucinated_gap = capability(
            "gap:reply-promise",
            "Create a verified path for: I will start an undefined scan",
            available=False,
            callable=False,
            verified=False,
            category="capability_gap",
        )
        hallucinated_gap["evidence"] = {"source": "reply", "proposal_id": "proposal-1"}
        feature_review = review("candidate")

        selected = adoption.select_next_target(
            matrix(hallucinated_gap),
            {"feature_reviews": [feature_review]},
            [],
        )

        self.assertEqual(feature_review["id"], selected["id"])
        self.assertEqual(1, selected["selection_evidence"]["excluded_self_narration_gap_count"])

    def test_human_confirmed_reply_gap_can_drive_target_rotation(self):
        confirmed_gap = capability(
            "gap:confirmed-adapter",
            "Build the browser adapter the operator confirmed",
            available=False,
            callable=False,
            verified=False,
            category="capability_gap",
        )
        confirmed_gap["evidence"] = {
            "source": "reply",
            "human_confirmed": True,
            "source_authority": "human_confirmed",
        }

        selected = adoption.select_next_target(matrix(confirmed_gap), {"feature_reviews": []}, [])

        self.assertEqual(confirmed_gap["id"], selected["id"])
        self.assertEqual(0, selected["selection_evidence"]["excluded_self_narration_gap_count"])

    def test_installed_python_update_without_matching_release_track_is_selected(self):
        intelligence = {
            "generated_at": "2026-08-23T00:00:00+00:00",
            "feature_reviews": [],
            "subsystems": {
                "eve": {
                    "components": [
                        {
                            "id": "phoenix-eve-runtime",
                            "name": "Arize Phoenix observability package",
                            "kind": "python_package",
                            "package": "arize-phoenix",
                            "release_repository": "Arize-ai/phoenix",
                            "release_feature_mode": "research_only",
                            "local_version": "14.6.0",
                            "latest_version": "20.3.0",
                            "update_available": True,
                        }
                    ]
                }
            },
        }

        selected = adoption.select_next_target(matrix(), intelligence, [])

        self.assertEqual("installed_component_update", selected["kind"])
        self.assertEqual("phoenix-eve-runtime", selected["component_id"])
        self.assertEqual("20.3.0", selected["target_version"])

    def test_matching_release_candidate_deduplicates_installed_update_target(self):
        feature_review = {
            **review("lab_candidate"),
            "id": "release:ragas@v0.4.3",
            "component_id": "ragas-eve-runtime",
            "target_version": "v0.4.3",
        }
        intelligence = {
            "feature_reviews": [feature_review],
            "subsystems": {
                "eve": {
                    "components": [
                        {
                            "id": "ragas-eve-runtime",
                            "kind": "python_package",
                            "package": "ragas",
                            "local_version": "0.3.2",
                            "latest_version": "0.4.3",
                            "update_available": True,
                        }
                    ]
                }
            },
        }

        selected = adoption.select_next_target(matrix(), intelligence, [])

        self.assertEqual(feature_review["id"], selected["id"])

    def test_structured_installed_component_update_resolves_to_canary(self):
        component_record = {
            "id": "phoenix-eve-runtime",
            "name": "Arize Phoenix observability package",
            "kind": "python_package",
            "package": "arize-phoenix",
            "release_feature_mode": "research_only",
            "adoption": "Run a local no-export trace canary.",
        }
        target = {
            "id": "component-update:phoenix-eve-runtime@20.3.0",
            "kind": "installed_component_update",
            "component_id": "phoenix-eve-runtime",
            "target_version": "20.3.0",
            "installed_version": "14.6.0",
            "source_authority": "installed_component_watcher",
            "objective": "Arize Phoenix package update 14.6.0 to 20.3.0",
        }

        result = adoption.resolve_capability_first(
            target["objective"],
            matrix(),
            {"feature_reviews": []},
            components=[component_record],
            target=target,
        )

        self.assertEqual("canary_existing_update", result["classification"])
        self.assertEqual("phoenix-eve-runtime", result["matched_component"]["id"])
        self.assertEqual("20.3.0", result["matched_feature_review"]["target_version"])
        self.assertTrue(adoption.python_candidate_plan(result["matched_feature_review"], result["matched_component"])["eligible"])

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
    def test_runtime_cycle_delegates_execution_to_runtime_bundle(self):
        with patch.object(eve, "delegate_cli_to_runtime", return_value=0) as delegate, patch.object(
            eve, "run_capability_adoption_cycle"
        ) as local_cycle:
            code = eve.main(
                [
                    "capabilities",
                    "adoption",
                    "cycle",
                    "--objective",
                    "inspect current Hermes tools",
                    "--research",
                    "--no-handoff",
                    "--runtime",
                    "--full",
                ]
            )

        self.assertEqual(0, code)
        delegated = delegate.call_args.args[0]
        self.assertEqual(["capabilities", "adoption", "cycle"], delegated[:3])
        self.assertIn("--runtime", delegated)
        self.assertIn("--research", delegated)
        self.assertIn("--no-handoff", delegated)
        self.assertIn("inspect current Hermes tools", delegated)
        local_cycle.assert_not_called()

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

    def test_failed_canary_signature_extracts_only_allowlisted_diagnostic(self):
        canary = {
            "status": "failed",
            "component_id": "ragas-eve-runtime",
            "package": "ragas",
            "requirement": "ragas==0.4.3",
            "target_version": "v0.4.3",
            "live_environment_changed": False,
            "commands": [
                {"command": ["uv", "pip", "install"], "returncode": 0, "ok": True},
                {
                    "command": ["python", "-I", "-c", "<python:hash>"],
                    "returncode": 1,
                    "ok": False,
                    "timed_out": False,
                    "stderr_tail": (
                        "/private/user/path with token=do-not-retain\n"
                        "ModuleNotFoundError: No module named "
                        "'langchain_community.chat_models.vertexai'"
                    ),
                },
            ],
        }

        result = adoption.summarize_candidate_canary_failure(canary)

        self.assertEqual("import_api_smoke", result["phase"])
        self.assertEqual("ModuleNotFoundError", result["exception_type"])
        self.assertEqual("langchain_community.chat_models.vertexai", result["missing_module"])
        self.assertFalse(result["raw_output_retained"])
        self.assertFalse(result["live_environment_changed"])
        self.assertIn("ragas==0.4.3", result["repair_objective"])
        self.assertNotIn("do-not-retain", repr(result))
        self.assertNotIn("/private/user/path", repr(result))

    def test_failed_canary_signature_preserves_unknown_when_trace_is_truncated(self):
        canary = {
            "status": "failed",
            "component_id": "example-agent",
            "package": "example-agent",
            "requirement": "example-agent==2.0.0",
            "commands": [
                {
                    "command": ["python", "-I", "-c", "<python:hash>"],
                    "returncode": 1,
                    "ok": False,
                    "stderr": "Traceback truncated before the exception",
                }
            ],
        }

        result = adoption.summarize_candidate_canary_failure(canary)

        self.assertEqual("unknown", result["exception_type"])
        self.assertIn("lacks the terminal exception", result["repair_objective"])
        self.assertTrue(result["output_sha256"])

    def test_successful_canary_has_no_repair_signature(self):
        self.assertEqual(
            {},
            adoption.summarize_candidate_canary_failure(
                {
                    "status": "passed",
                    "commands": [{"command": ["python"], "returncode": 0, "ok": True}],
                }
            ),
        )


if __name__ == "__main__":
    unittest.main()
