import unittest

import eve_capability_intelligence as intelligence


class CapabilityLifecycleTruthTests(unittest.TestCase):
    def test_wiki_cli_probe_requires_one_absolute_populated_vault_and_search_result(self) -> None:
        status = intelligence._compact_openclaw_wiki(
            {
                "vaultMode": "bridge",
                "vaultPath": "/Users/example/.eve_runtime/openclaw/wiki/eve-memory-wiki",
                "vaultExists": True,
                "bridge": {"enabled": True},
                "pageCounts": {"source": 98},
                "warnings": [],
            },
            [{"path": "sources/eve-project-memory.md", "score": 100}],
        )

        self.assertTrue(status["status_ok"])
        self.assertTrue(status["cli_callable"])
        self.assertEqual(98, status["source_page_count"])

    def test_source_discovery_cannot_skip_to_verified(self) -> None:
        lifecycle = intelligence.build_capability_lifecycle(
            discovered=True,
            consequence_verified=True,
        )

        self.assertEqual("discovered", lifecycle["stage"])
        self.assertTrue(lifecycle["discovered"])
        self.assertFalse(lifecycle["configured"])
        self.assertFalse(lifecycle["callable"])
        self.assertFalse(lifecycle["consequence_verified"])

    def test_callable_requires_configured_and_enabled_chain(self) -> None:
        lifecycle = intelligence.build_capability_lifecycle(
            discovered=True,
            configured=False,
            enabled=True,
            callable_now=True,
            consequence_verified=True,
        )

        self.assertEqual("discovered", lifecycle["stage"])
        self.assertFalse(lifecycle["enabled"])
        self.assertFalse(lifecycle["callable"])
        self.assertFalse(lifecycle["consequence_verified"])

    def test_openclaw_reviews_separate_live_proof_from_installed_surfaces(self) -> None:
        reviews = intelligence.build_openclaw_feature_family_reviews(
            current_config={
                "gateway": {"bind": "loopback"},
                "channels": {"imessage": {"enabled": False}},
                "agents": {
                    "defaults": {
                        "compaction": {
                            "mode": "safeguard",
                            "midTurnPrecheck": {"enabled": True},
                        },
                        "contextPruning": {
                            "mode": "cache-ttl",
                            "ttl": "5m",
                        },
                        "heartbeat": {"every": "0m"},
                    }
                },
                "tools": {
                    "loopDetection": {"enabled": True},
                    "alsoAllow": [
                        "wiki_apply",
                        "wiki_get",
                        "wiki_lint",
                        "wiki_search",
                        "wiki_status",
                    ],
                },
            },
            config_valid=True,
            memory_status={
                "ok": True,
                "backends": ["qmd"],
                "agents": [{"agent_id": "main", "health_ok": True}],
                "retrieval_smoke": {"ok": True, "result_count": 1},
            },
            plugins=[
                {"id": "acpx", "enabled": False},
                {"id": "memory-wiki", "enabled": True},
            ],
            tasks={
                "enabled_job_count": 0,
                "taskflow_count": 0,
                "active_outcome_coverage_count": 0,
                "active_reliability_ok": False,
            },
            commitments={"count": 0},
            security={"probe_observed": True, "findings": []},
            mcp={"server_count": 1, "server_ids": ["eve-openclaw-channels"]},
            skills={
                "agent_skill_filter": ["eve_self_repair"],
                "model_visible": 1,
                "command_visible": 1,
                "blocked": 0,
                "missing_requirements": 0,
            },
            hooks={
                "count": 1,
                "hooks": [
                    {
                        "name": "eve-evidence-ingest",
                        "events": ["gateway:startup", "command"],
                    }
                ],
            },
            cron={
                "count": 0,
                "enabled_count": 0,
                "duplicate_scheduler_risk": False,
            },
            isolation={
                "managed_worktree_count": 0,
                "sandbox_container_count": 0,
                "browser_container_count": 0,
            },
            approvals={"configured": True, "effective_scope_count": 1},
            runtime_status={
                "ok": True,
                "service": {"loaded": True, "status": "running"},
                "probe": {"connect_ok": True, "rpc_ok": True},
                "heartbeat": {"enabled_count": 0, "enabled_agent_ids": []},
            },
            deterministic_audit={"ok": True, "status": "ready"},
            wiki_status={
                "status_ok": True,
                "cli_callable": True,
                "vault_path": "/Users/example/.eve_runtime/openclaw/wiki/eve-memory-wiki",
            },
        )
        by_family = {item["family"]: item for item in reviews}

        self.assertEqual("verified", by_family["gateway"]["lifecycle"]["stage"])
        self.assertEqual("verified", by_family["memory_qmd"]["lifecycle"]["stage"])
        self.assertEqual("enabled", by_family["memory_wiki"]["lifecycle"]["stage"])
        self.assertTrue(by_family["memory_wiki"]["lifecycle"]["interfaces"]["cli_callable"])
        self.assertTrue(
            by_family["memory_wiki"]["lifecycle"]["interfaces"]["resident_config_admitted"]
        )
        self.assertFalse(
            by_family["memory_wiki"]["lifecycle"]["interfaces"]["resident_callable"]
        )
        self.assertFalse(
            by_family["memory_wiki"]["lifecycle"]["consequence_verified"]
        )
        self.assertEqual("verified", by_family["skills"]["lifecycle"]["stage"])
        self.assertEqual("callable", by_family["context_management"]["lifecycle"]["stage"])
        self.assertFalse(
            by_family["context_management"]["lifecycle"]["consequence_verified"]
        )
        self.assertEqual("configured", by_family["acp"]["lifecycle"]["stage"])
        self.assertEqual("enabled", by_family["mcp"]["lifecycle"]["stage"])
        self.assertEqual("discovered", by_family["channels"]["lifecycle"]["stage"])
        self.assertEqual("discovered", by_family["commitments"]["lifecycle"]["stage"])

        summary = intelligence.summarize_feature_family_reviews(reviews)
        self.assertGreaterEqual(summary["lifecycle_stage_counts"]["discovered"], 2)
        self.assertIn(
            "openclaw:context_management",
            summary["callable_unverified_ids"],
        )
        self.assertIn("openclaw:channels", summary["discovered_only_ids"])


if __name__ == "__main__":
    unittest.main()
