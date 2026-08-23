import json
import plistlib
import stat
import subprocess
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import eve
import eve_capability_intelligence as intelligence
import eve_store


class FakeRunner:
    def __call__(self, command, timeout, env=None):
        del timeout, env
        args = [str(item) for item in command]
        if args[-1] == "--version" and "openclaw" in args[0]:
            return subprocess.CompletedProcess(args, 0, "OpenClaw 2026.7.1-2 (abc)\n", "")
        if args[-1] == "--version" and "hermes" in args[0]:
            return subprocess.CompletedProcess(args, 0, "Hermes Agent v0.18.2 (build)\n", "")
        if args[-1] == "--version" and "qmd" in args[0]:
            return subprocess.CompletedProcess(args, 0, "qmd 2.5.3 (build)\n", "")
        if args[-1] == "--version" and "mcporter" in args[0]:
            return subprocess.CompletedProcess(args, 0, "0.12.3\n", "")
        if args[-2:] == ["config", "schema"]:
            payload = {
                "type": "object",
                "properties": {
                    "memory": {
                        "type": "object",
                        "properties": {
                            "backend": {"anyOf": [{"const": "builtin"}, {"const": "qmd"}]},
                            "qmd": {"type": "object", "properties": {"command": {"type": "string"}}},
                        },
                    },
                    "update": {"type": "object", "properties": {"channel": {"enum": ["stable", "beta"]}}},
                },
            }
            return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")
        if "plugins" in args and "list" in args:
            payload = {
                "registry": {
                    "diagnostics": [
                        {"level": "warn", "code": "stale", "message": "registry needs refresh"}
                    ]
                },
                "plugins": [
                    {
                        "id": "acpx",
                        "name": "ACPX",
                        "version": "2026.6.6",
                        "origin": "user",
                        "enabled": True,
                        "status": "loaded",
                        "toolNames": ["acp_run"],
                        "dependencyStatus": {"requiredInstalled": True},
                    }
                ],
            }
            return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")
        if args[-3:] == ["config", "validate", "--json"]:
            return subprocess.CompletedProcess(args, 0, json.dumps({"valid": True, "warnings": []}), "")
        if "update" in args and "--dry-run" in args:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps({"dryRun": True, "currentVersion": "2026.7.1-2", "effectiveChannel": "stable"}),
                "",
            )
        if "memory" in args and "status" in args:
            payload = [
                {
                    "agentId": "eve-repair",
                    "status": {"backend": "builtin", "provider": "openai", "model": "text-embedding-3-small", "files": 2, "chunks": 5},
                    "embeddingProbe": {"ok": False, "error": "hosted embedding quota failed"},
                    "scan": {"issues": ["additional memory path missing (/runtime/docs/model_lanes)"]},
                }
            ]
            return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")
        if "memory" in args and "search" in args:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    {
                        "results": [
                            {
                                "path": "qmd/eve-capability-intelligence/capability-intelligence.md",
                                "score": 1.0,
                                "snippet": "private content must not be copied into the ledger",
                            }
                        ]
                    }
                ),
                "",
            )
        if args[-2:] == ["status", "--json"]:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    {
                        "runtimeVersion": "2026.7.1-2",
                        "heartbeat": {
                            "defaultAgentId": "main",
                            "agents": [{"agentId": "main", "enabled": False, "every": "disabled"}],
                        },
                        "tasks": {
                            "total": 2,
                            "active": 0,
                            "terminal": 2,
                            "failures": 0,
                            "byStatus": {"succeeded": 2, "failed": 0},
                            "byRuntime": {"cron": 2},
                        },
                        "gateway": {
                            "mode": "local",
                            "url": "ws://127.0.0.1:19011",
                            "reachable": True,
                            "misconfigured": False,
                            "connectLatencyMs": 12,
                        },
                        "gatewayService": {
                            "installed": True,
                            "loaded": True,
                            "managedByOpenClaw": True,
                            "externallyManaged": False,
                            "runtime": {"status": "running", "state": "active", "pid": 123},
                            "layout": {"sourcePath": "/Users/test/Library/LaunchAgents/ai.openclaw.eve-repair.plist"},
                        },
                    }
                ),
                "",
            )
        if args[-2:] == ["health", "--json"]:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    {
                        "ok": True,
                        "eventLoop": {"degraded": False, "reasons": []},
                        "plugins": {"loaded": ["acpx", "memory-core"], "errors": []},
                        "configReload": {"hotReloadStatus": "active"},
                    }
                ),
                "",
            )
        if "gateway" in args and "probe" in args:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    {
                        "ok": True,
                        "degraded": False,
                        "capability": "admin_capable",
                        "primaryTargetId": "localLoopback",
                        "warnings": [],
                        "targets": [
                            {
                                "id": "localLoopback",
                                "url": "ws://127.0.0.1:19011",
                                "active": True,
                                "connect": {"ok": True, "rpcOk": True, "scopeLimited": False},
                            }
                        ],
                        "discovery": {"count": 1},
                    }
                ),
                "",
            )
        if "tasks" in args and "audit" in args:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    {
                        "count": 0,
                        "summary": {"warnings": 0, "errors": 0, "taskFlows": 0, "total": 0, "byCode": {}},
                        "findings": [],
                    }
                ),
                "",
            )
        if "tasks" in args and "list" in args:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    {
                        "count": 2,
                        "tasks": [
                            {
                                "taskId": "one",
                                "status": "succeeded",
                                "runtime": "cron",
                                "label": "maintenance",
                                "sourceId": "audit",
                                "createdAt": 200,
                            },
                            {
                                "taskId": "two",
                                "status": "succeeded",
                                "runtime": "cron",
                                "label": "maintenance",
                                "sourceId": "audit",
                                "createdAt": 100,
                            },
                        ],
                    }
                ),
                "",
            )
        if "commitments" in args:
            return subprocess.CompletedProcess(args, 0, json.dumps({"count": 0, "commitments": []}), "")
        if "security" in args and "audit" in args:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps({"summary": {"critical": 0, "warn": 0, "info": 1}, "findings": [], "secretDiagnostics": []}),
                "",
            )
        if "mcp" in args and "list" in args:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps({"eve-openclaw-channels": {"command": "python3", "args": ["server.py"]}}),
                "",
            )
        if "skills" in args and "check" in args:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    {
                        "summary": {
                            "total": 10,
                            "eligible": 10,
                            "modelVisible": 10,
                            "commandVisible": 10,
                            "disabled": 0,
                            "blocked": 0,
                            "missingRequirements": 0,
                        },
                        "agentSkillFilter": ["eve_capability_use", "eve_self_repair"],
                    }
                ),
                "",
            )
        if "hooks" in args and "list" in args:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps({"hooks": [{"name": "eve-evidence-ingest", "source": "workspace", "events": ["command"]}]}),
                "",
            )
        if "worktrees" in args and "list" in args:
            return subprocess.CompletedProcess(args, 0, json.dumps({"worktrees": []}), "")
        if "sandbox" in args and "list" in args:
            return subprocess.CompletedProcess(args, 0, json.dumps({"containers": [], "browsers": []}), "")
        if "approvals" in args and "get" in args:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    {
                        "exists": True,
                        "file": {"defaults": {"security": "full", "ask": "off"}},
                        "effectivePolicy": {"scopes": [{}, {}]},
                    }
                ),
                "",
            )
        if "cron" in args and "list" in args:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    {
                        "total": 1,
                        "jobs": [
                            {
                                "id": "audit",
                                "name": "Standing Audit",
                                "enabled": True,
                                "sessionTarget": "isolated",
                                "schedule": {"kind": "every", "everyMs": 21600000},
                                "delivery": {"mode": "none"},
                            }
                        ],
                    }
                ),
                "",
            )
        raise AssertionError(f"unexpected command: {args}")


class CapabilityIntelligenceUnitTests(unittest.TestCase):
    def test_openclaw_source_surface_is_not_promoted_to_callable_or_verified(self):
        surface = {
            "id": "openclaw.tool_doc.wiki-search",
            "name": "Wiki Search",
            "category": "tool_doc",
            "meaning_for_eve": "A source-discovered wiki search surface.",
            "risk_level": "low",
            "evidence": ["docs/tools/wiki-search.md"],
        }
        radar = {"openclaw_source_path": "/tmp/openclaw-source"}
        with patch.object(eve, "admission_record_for_openclaw_surface", return_value={}):
            record = eve.ability_record_from_openclaw_surface(surface, radar)

        self.assertTrue(record["available"])
        self.assertFalse(record["callable"])
        self.assertFalse(record["verified"])
        self.assertFalse(record["safe_for_autonomy"])
        self.assertEqual("discovered", record["evidence"]["lifecycle_stage"])
        self.assertTrue(record["evidence"]["source_discovery_only"])

    def test_capability_matrix_keeps_source_radar_and_memory_discovered_only(self):
        radar = {
            "openclaw_capabilities": [
                {
                    "id": "memory",
                    "name": "Memory",
                    "present": True,
                    "evidence": ["docs/concepts/memory.md"],
                }
            ],
            "openclaw_source_path": "/tmp/openclaw-source",
            "openclaw_source_kind": "mirror",
        }
        with patch.object(eve, "read_action_executions", return_value=[]), patch.object(
            eve, "read_capability_gaps", return_value=[]
        ), patch.object(eve, "load_agent_capability_radar", return_value=radar), patch.object(
            eve, "load_agent_integration_state", return_value={"routes": []}
        ), patch.object(eve, "read_developmental_cycles", return_value=[]), patch.object(
            eve.eve_openclaw_body, "read_openclaw_action_router_events", return_value=[]
        ), patch.object(
            eve.eve_openclaw_body, "read_openclaw_channel_events", return_value=[]
        ), patch.object(
            eve, "load_capability_adoption_state", return_value={}
        ), patch.object(
            eve, "load_runtime_identity", return_value={"capability_ledger": ["Can inspect files"]}
        ):
            matrix = eve.build_capability_matrix({}, prefer_runtime=False, source="test")

        by_id = {item["id"]: item for item in matrix["capabilities"]}
        self.assertFalse(by_id["openclaw.memory"]["callable"])
        self.assertFalse(by_id["openclaw.memory"]["verified"])
        self.assertEqual("discovered", by_id["openclaw.memory"]["evidence"]["lifecycle_stage"])
        remembered = next(item for item in matrix["capabilities"] if item["id"].startswith("ledger."))
        self.assertFalse(remembered["callable"])
        self.assertFalse(remembered["verified"])

    def test_brew_formula_info_prefers_linked_keg_over_retained_rollback(self):
        def run_component(command, timeout):
            del timeout
            args = [str(item) for item in command]
            if args[1:3] == ["list", "--versions"]:
                return subprocess.CompletedProcess(args, 0, "llama.cpp 10360 0.2.0\n", ""), ""
            if args[1:3] == ["info", "--json=v2"]:
                payload = {
                    "formulae": [
                        {
                            "name": "llama.cpp",
                            "linked_keg": "0.2.0",
                            "versions": {"stable": "0.2.0"},
                            "installed": [{"version": "10360"}, {"version": "0.2.0"}],
                        }
                    ]
                }
                return subprocess.CompletedProcess(args, 0, json.dumps(payload), ""), ""
            if args[1:3] == ["outdated", "--json=v2"]:
                return subprocess.CompletedProcess(args, 0, json.dumps({"formulae": []}), ""), ""
            raise AssertionError(args)

        with patch.object(eve, "run_component_command", side_effect=run_component):
            result = eve.brew_formula_info("llama.cpp", timeout=5)

        self.assertEqual("0.2.0", result["current_version"])
        self.assertEqual("0.2.0", result["latest_version"])
        self.assertFalse(result["update_available"])

    def test_brew_formula_info_prefers_installed_stable_for_keg_only_formula(self):
        def run_component(command, timeout):
            del timeout
            args = [str(item) for item in command]
            if args[1:3] == ["list", "--versions"]:
                return subprocess.CompletedProcess(args, 0, "sqlite 3.53.1 3.53.4 3.53.3\n", ""), ""
            if args[1:3] == ["info", "--json=v2"]:
                payload = {
                    "formulae": [
                        {
                            "name": "sqlite",
                            "linked_keg": None,
                            "versions": {"stable": "3.53.4"},
                            "installed": [
                                {"version": "3.53.1"},
                                {"version": "3.53.3"},
                                {"version": "3.53.4"},
                            ],
                        }
                    ]
                }
                return subprocess.CompletedProcess(args, 0, json.dumps(payload), ""), ""
            if args[1:3] == ["outdated", "--json=v2"]:
                return subprocess.CompletedProcess(args, 0, json.dumps({"formulae": []}), ""), ""
            raise AssertionError(args)

        with patch.object(eve, "run_component_command", side_effect=run_component):
            result = eve.brew_formula_info("sqlite", timeout=5)

        self.assertEqual("3.53.4", result["current_version"])
        self.assertEqual("3.53.4", result["latest_version"])
        self.assertFalse(result["update_available"])

    def test_redaction_preserves_non_secret_keys_and_removes_credentials(self):
        payload = {
            "token": "do-not-store",
            "nested": {"apiKey": "also-secret", "model": "eve-deep"},
            "monkey": "banana",
        }

        redacted = intelligence.redact_payload(payload)

        self.assertEqual(intelligence.REDACTED, redacted["token"])
        self.assertEqual(intelligence.REDACTED, redacted["nested"]["apiKey"])
        self.assertEqual("eve-deep", redacted["nested"]["model"])
        self.assertEqual("banana", redacted["monkey"])
        self.assertNotIn("do-not-store", repr(redacted))

    def test_schema_catalog_flattens_nested_paths_and_enum_options(self):
        schema = {
            "type": "object",
            "properties": {
                "memory": {
                    "type": "object",
                    "properties": {
                        "backend": {"anyOf": [{"const": "builtin"}, {"const": "qmd"}]},
                        "paths": {"type": "array", "items": {"type": "object", "properties": {"path": {"type": "string"}}}},
                    },
                }
            },
        }

        catalog = intelligence.catalog_json_schema(schema)
        by_path = {item["path"]: item for item in catalog}

        self.assertIn("memory.backend", by_path)
        self.assertEqual(["builtin", "qmd"], by_path["memory.backend"]["enum"])
        self.assertIn("memory.paths[].path", by_path)

    def test_hermes_catalog_uses_default_config_and_yaml_examples_not_code_tokens(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            config_source = source_root / "hermes_cli" / "config.py"
            config_source.parent.mkdir(parents=True)
            config_source.write_text(
                """
DEFAULT_CONFIG = {
    "model": {"provider": "custom", "context_length": 65536},
    "terminal": {"cwd": "."},
    "computed": "prefix-" + SOME_NAME,
}

def not_configuration(active_path):
    return active_path.read_text()
""".strip(),
                encoding="utf-8",
            )
            docs = source_root / "website" / "docs" / "reference" / "mcp-config-reference.md"
            docs.parent.mkdir(parents=True)
            docs.write_text(
                """
# MCP config

```yaml
mcp_servers:
  docs:
    command: qmd
    tools:
      include: [search]
```
""".strip(),
                encoding="utf-8",
            )

            catalog = intelligence.extract_hermes_config_catalog(
                source_root,
                {"model": {"provider": "custom"}},
            )

        by_path = {item["path"]: item for item in catalog}
        self.assertIn("model.context_length", by_path)
        self.assertTrue(by_path["model.context_length"]["defined_in_default_config"])
        self.assertIn("mcp_servers.*.command", by_path)
        self.assertIn("mcp_servers.*.tools.include[]", by_path)
        self.assertNotIn("active_path.read_text", by_path)
        self.assertNotIn("Args", by_path)

    def test_openclaw_collector_is_schema_backed_compact_and_secret_free(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "openclaw.json"
            config_path.write_text(
                json.dumps(
                    {
                        "memory": {"backend": "builtin"},
                        "gateway": {"bind": "loopback"},
                        "agents": {
                            "defaults": {
                                "compaction": {
                                    "mode": "safeguard",
                                    "midTurnPrecheck": {"enabled": True},
                                },
                                "contextPruning": {
                                    "mode": "cache-ttl",
                                    "ttl": "1m",
                                    "keepLastAssistants": 3,
                                },
                            }
                        },
                        "tools": {"loopDetection": {"enabled": True}},
                        "channels": {"imessage": {"enabled": False}},
                        "plugins": {
                            "allow": ["acpx", "webhooks"],
                            "entries": {"webhooks": {"config": {"secret": "never-log-this"}}},
                        },
                    }
                ),
                encoding="utf-8",
            )

            snapshot = intelligence.collect_openclaw_snapshot(
                profile="eve-repair",
                config_path=config_path,
                command="/opt/homebrew/bin/openclaw",
                runner=FakeRunner(),
            )

        self.assertEqual("2026.7.1-2", snapshot["version"])
        self.assertTrue(snapshot["config_valid"])
        self.assertIn("memory.backend", {item["path"] for item in snapshot["config_schema_catalog"]})
        self.assertEqual(["acpx"], snapshot["enabled_plugin_ids"])
        self.assertEqual(["openai"], snapshot["memory"]["providers"])
        self.assertTrue(snapshot["memory"]["retrieval_smoke"]["ok"])
        self.assertEqual("2.5.3", snapshot["supporting_tools"]["qmd"]["version"])
        self.assertEqual("0.12.3", snapshot["supporting_tools"]["mcporter"]["version"])
        self.assertEqual(0, snapshot["runtime_surfaces"]["tasks"]["finding_count"])
        self.assertTrue(snapshot["runtime"]["ok"])
        self.assertEqual("ai.openclaw.eve-repair", snapshot["runtime"]["service"]["id"])
        self.assertEqual(0.0, snapshot["runtime_surfaces"]["tasks"]["failure_rate"])
        self.assertTrue(snapshot["runtime_surfaces"]["tasks"]["active_reliability_ok"])
        self.assertEqual(1, snapshot["runtime_surfaces"]["mcp"]["server_count"])
        self.assertTrue(snapshot["runtime_surfaces"]["context_management"]["configured_ok"])
        family_reviews = {item["family"]: item for item in snapshot["feature_family_reviews"]}
        self.assertEqual("use_existing", family_reviews["gateway"]["decision"])
        self.assertEqual("use_existing", family_reviews["context_management"]["decision"])
        self.assertEqual("canary", family_reviews["managed_worktrees"]["decision"])
        self.assertEqual("defer", family_reviews["commitments"]["decision"])
        self.assertNotIn("private content must not be copied", repr(snapshot))
        self.assertNotIn("never-log-this", repr(snapshot))

    def test_qmd_memory_health_does_not_require_hosted_embedding_probe(self):
        payload = [
            {
                "agentId": "eve-repair",
                "status": {
                    "backend": "qmd",
                    "provider": "qmd",
                    "model": "qmd",
                    "files": 12,
                    "chunks": 20,
                    "custom": {"qmd": {"collections": 6, "embedFailures": 0, "embedBackoffUntil": None}},
                },
                "scan": {"issues": [], "sources": [{"source": "memory", "issues": []}]},
            }
        ]

        compact = intelligence._compact_openclaw_memory(payload)

        self.assertTrue(compact["ok"])
        self.assertEqual(6, compact["agents"][0]["qmd_collections"])

    def test_taskflow_scores_enabled_jobs_separately_from_retired_failures(self):
        compact = intelligence._compact_openclaw_tasks(
            {"count": 0, "summary": {"warnings": 0, "errors": 0, "total": 0}},
            {
                "tasks": {
                    "total": 5,
                    "active": 0,
                    "terminal": 5,
                    "failures": 3,
                    "byStatus": {"succeeded": 2, "failed": 3},
                    "byRuntime": {"cron": 5},
                }
            },
            {
                "tasks": [
                    {"sourceId": "active", "label": "active maintenance", "status": "succeeded", "createdAt": 500},
                    {"sourceId": "active", "label": "active maintenance", "status": "succeeded", "createdAt": 400},
                    {"sourceId": "retired", "label": "retired audit", "status": "failed", "createdAt": 300},
                    {"sourceId": "retired", "label": "retired audit", "status": "failed", "createdAt": 200},
                    {"sourceId": "retired", "label": "retired audit", "status": "failed", "createdAt": 100},
                ]
            },
            {
                "jobs": [
                    {"id": "active", "enabled": True},
                    {"id": "retired", "enabled": False},
                ]
            },
        )

        self.assertEqual(0.6, compact["failure_rate"])
        self.assertEqual(0.0, compact["active_failure_rate"])
        self.assertTrue(compact["active_reliability_ok"])
        self.assertEqual(3, compact["retired_sources"][0]["failure_count"])

    def test_hermes_snapshot_keeps_only_run_provenance_not_trace_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = root / "profile"
            source = root / "source"
            profile.mkdir()
            (source / "website" / "docs" / "user-guide").mkdir(parents=True)
            (profile / "config.yaml").write_text("model:\n  default: eve-deep\napi_key: do-not-store\n", encoding="utf-8")
            (source / "website" / "docs" / "user-guide" / "configuration.md").write_text(
                "Use `agent.max_turns` and `compression.threshold` in config.yaml.", encoding="utf-8"
            )
            snapshot = intelligence.collect_hermes_snapshot(
                profile_home=profile,
                source_root=source,
                inventory={
                    "generated_at": "2026-07-20T00:00:00+00:00",
                    "hermes_status": {"status": "available", "source_head": "abc"},
                    "default_profile_ready_for_serious_learning": False,
                    "serious_learning_route": "local_64k_lab_constrained_json",
                    "capability_families": [{"id": "tools_toolsets", "status": "available"}],
                },
                feature_policy={"status": "clear", "features": [{"id": "memory_user_notes", "allowed_now": True}]},
                latest_run={
                    "id": "run-1",
                    "status": "passed",
                    "strict_json_ok": True,
                    "trace": {"private_prompt": "never-copy-this"},
                },
                command="/Users/example/.local/bin/hermes",
                runner=FakeRunner(),
            )

        paths = {item["path"] for item in snapshot["config_catalog"]}
        self.assertIn("agent.max_turns", paths)
        self.assertEqual("run-1", snapshot["latest_run"]["id"])
        self.assertNotIn("never-copy-this", repr(snapshot))
        self.assertNotIn("do-not-store", repr(snapshot))

    def test_snapshot_identifies_current_openclaw_and_hermes_failures(self):
        eve_snapshot = {"id": "eve", "organs": [], "components": [], "config_catalog": [], "feature_ids": [], "fingerprint": "eve"}
        openclaw = {
            "id": "openclaw",
            "version": "2026.7.1-2",
            "configured_values": {"memory": {"backend": "builtin"}},
            "memory": {
                "ok": False,
                "providers": ["openai"],
                "agents": [{"scan_issues": ["additional memory path missing (/runtime/docs)"]}],
            },
            "plugins": [{"id": "acpx", "version": "2026.6.6"}],
            "plugin_diagnostics": [],
            "feature_ids": [],
            "config_schema_catalog": [],
            "fingerprint": "openclaw",
        }
        hermes = {
            "id": "hermes",
            "version": "0.18.2",
            "default_profile_ready_for_serious_learning": False,
            "latest_run": {},
            "feature_ids": [],
            "config_catalog": [],
            "fingerprint": "hermes",
        }

        snapshot = intelligence.build_snapshot(
            source="test",
            eve=eve_snapshot,
            openclaw=openclaw,
            hermes=hermes,
            previous=None,
        )
        ids = {item["id"] for item in snapshot["opportunities"]}

        self.assertIn("openclaw_memory_local_first", ids)
        self.assertIn("openclaw_qmd_local_memory", ids)
        self.assertIn("openclaw_acpx_version_alignment", ids)
        self.assertIn("openclaw_memory_source_parity", ids)
        self.assertIn("hermes_64k_serious_learning_route", ids)
        self.assertIn("hermes_fresh_strict_smoke", ids)

    def test_change_detection_distinguishes_schema_release_and_version_deltas(self):
        previous = {
            "subsystems": {
                "openclaw": {
                    "version": "1.0.0",
                    "configured_values_sha256": "a",
                    "config_schema_catalog": [{"path": "memory.backend"}],
                    "feature_ids": ["plugin:a"],
                }
            },
            "release_feeds": [{"repository": "openclaw/openclaw", "releases": [{"tag": "v1"}]}],
        }
        current = {
            "subsystems": {
                "openclaw": {
                    "version": "1.1.0",
                    "configured_values_sha256": "b",
                    "config_schema_catalog": [{"path": "memory.backend"}, {"path": "memory.qmd"}],
                    "feature_ids": ["plugin:a", "plugin:b"],
                }
            },
            "release_feeds": [{"repository": "openclaw/openclaw", "releases": [{"tag": "v2"}, {"tag": "v1"}]}],
        }

        changes = intelligence.compute_changes(previous, current)

        self.assertTrue(changes["material_change"])
        self.assertEqual(1, changes["counts"]["version_changes"])
        self.assertEqual(["memory.qmd"], changes["config_changes"][0]["added_paths"])
        self.assertEqual(["plugin:b"], changes["feature_changes"][0]["added"])
        self.assertEqual("v2", changes["new_releases"][0]["tag"])

    def test_eve_installed_features_do_not_include_research_radar_surfaces(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot = intelligence.collect_eve_snapshot(
                root=Path(temp_dir),
                config={"model": "eve-fast"},
                organ_report={"organs": [{"id": "hermes_learning_organ", "status": "healthy"}]},
                component_state={"components": []},
                radar_state={
                    "openclaw_discovered_surfaces": [
                        {"id": "research:future-channel"},
                        {"id": "research:future-plugin"},
                    ]
                },
            )

        self.assertEqual(["hermes_learning_organ"], snapshot["feature_ids"])
        self.assertEqual(
            ["research:future-channel", "research:future-plugin"],
            snapshot["research_feature_ids"],
        )

    def test_research_surface_drift_is_not_an_installed_material_change(self):
        previous = {
            "subsystems": {
                "eve": {
                    "feature_ids": ["hermes_learning_organ"],
                    "research_feature_ids": ["research:a"],
                    "config_catalog": [],
                }
            },
            "release_feeds": [],
        }
        current = {
            "subsystems": {
                "eve": {
                    "feature_ids": ["hermes_learning_organ"],
                    "research_feature_ids": ["research:b"],
                    "config_catalog": [],
                }
            },
            "release_feeds": [],
            "feature_reviews": [],
        }

        changes = intelligence.compute_changes(previous, current)

        self.assertFalse(changes["material_change"])
        self.assertTrue(changes["research_change"])
        self.assertEqual(1, changes["counts"]["research_feature_changes"])
        self.assertEqual([], changes["feature_changes"])

    def test_release_reviews_distinguish_in_use_lab_candidate_and_prerelease(self):
        subsystems = {
            "eve": {
                "components": [
                    {
                        "id": "qmd",
                        "name": "QMD",
                        "local_version": "2.5.3",
                        "release_repository": "tobi/qmd",
                        "release_feature_mode": "installed_version",
                        "adoption": "Reindex and prove retrieval.",
                    },
                    {
                        "id": "dagster-eve-runtime",
                        "name": "Dagster",
                        "local_version": "1.13.3",
                        "release_repository": "dagster-io/dagster",
                        "release_feature_mode": "lab_only",
                        "adoption": "Materialize the read-only assets.",
                    },
                    {
                        "id": "openclaw",
                        "name": "OpenClaw",
                        "local_version": "2026.7.1-2",
                        "release_repository": "openclaw/openclaw",
                        "release_feature_mode": "installed_version",
                    },
                ]
            }
        }
        feeds = [
            {
                "repository": "tobi/qmd",
                "releases": [
                    {
                        "tag": "v2.5.3",
                        "published_at": "2026-05-28T00:00:00Z",
                        "feature_bullets": ["Line-numbered retrieval output"],
                    }
                ],
            },
            {
                "repository": "dagster-io/dagster",
                "releases": [
                    {
                        "tag": "1.13.14",
                        "published_at": "2026-07-19T00:00:00Z",
                        "feature_bullets": ["Fixed recurring asset materialization"],
                    }
                ],
            },
            {
                "repository": "openclaw/openclaw",
                "releases": [
                    {
                        "tag": "v2026.7.2-beta.3",
                        "published_at": "2026-07-20T00:00:00Z",
                        "prerelease": True,
                        "feature_bullets": ["Gateway and session recovery"],
                    }
                ],
            },
        ]

        reviews = intelligence.build_feature_reviews(
            subsystems,
            feeds,
            checked_at="2026-07-20T12:00:00+00:00",
        )
        by_repository = {item["repository"]: item for item in reviews}

        self.assertEqual("in_use", by_repository["tobi/qmd"]["state"])
        self.assertEqual("lab_candidate", by_repository["dagster-io/dagster"]["state"])
        self.assertEqual("research_only", by_repository["openclaw/openclaw"]["state"])
        self.assertIn("Materialize the read-only assets", by_repository["dagster-io/dagster"]["required_gate"])

    def test_feature_review_state_change_is_logged_when_candidate_becomes_in_use(self):
        previous_review = {
            "id": "release:dagster-io-dagster@1.13.14",
            "repository": "dagster-io/dagster",
            "target_version": "1.13.14",
            "state": "lab_candidate",
            "visible_in_current_feed": True,
        }
        current_review = dict(previous_review, state="in_use")
        previous = {"subsystems": {}, "release_feeds": [], "feature_reviews": [previous_review]}
        current = {"subsystems": {}, "release_feeds": [], "feature_reviews": [current_review]}

        changes = intelligence.compute_changes(previous, current)

        self.assertTrue(changes["material_change"])
        self.assertEqual(1, changes["counts"]["feature_review_changes"])
        self.assertEqual("state_changed", changes["feature_review_changes"][0]["kind"])

    def test_equal_installed_and_latest_versions_are_not_reported_as_package_updates(self):
        subsystems = {
            "eve": {
                "components": [
                    {
                        "id": "openclaw",
                        "update_available": True,
                        "local_version": "2026.7.1-2",
                        "latest_version": "2026.7.1-2",
                        "remote_head": "new-source-head",
                    }
                ]
            },
            "openclaw": {"configured_values": {}, "memory": {}, "plugins": []},
            "hermes": {},
        }

        opportunities = intelligence.build_opportunities(subsystems)
        by_id = {item["id"]: item for item in opportunities}

        self.assertNotIn("installed_component_updates", by_id)
        self.assertIn("openclaw", by_id["research_source_drift"]["finding"])

    def test_historical_hidden_candidate_does_not_survive_as_release_attention(self):
        feature_reviews = [
            {
                "id": "release:confident-ai-deepeval@v4.1.2",
                "repository": "confident-ai/deepeval",
                "component_id": "deepeval-eve-runtime",
                "target_version": "v4.1.2",
                "installed_version": "4.1.2",
                "state": "in_use",
                "visible_in_current_feed": True,
            },
            {
                "id": "release:confident-ai-deepeval@v4.1.0",
                "repository": "confident-ai/deepeval",
                "component_id": "deepeval-eve-runtime",
                "target_version": "v4.1.0",
                "installed_version": "3.9.9",
                "state": "candidate",
                "visible_in_current_feed": False,
            },
        ]

        opportunities = intelligence.build_release_adoption_opportunities(feature_reviews)

        self.assertEqual([], opportunities)

    def test_verified_strict_local_64k_run_satisfies_hermes_serious_route(self):
        opportunities = intelligence.build_opportunities(
            {
                "eve": {"components": []},
                "openclaw": {"configured_values": {"memory": {"backend": "qmd"}}, "memory": {"ok": True}, "plugins": []},
                "hermes": {
                    "default_profile_ready_for_serious_learning": False,
                    "latest_run": {
                        "created_at": "2026-07-20T03:50:03+00:00",
                        "local_64k_lab_requested": True,
                        "strict_json_ok": True,
                        "json_repair_used": False,
                    },
                },
            }
        )

        self.assertNotIn("hermes_64k_serious_learning_route", {item["id"] for item in opportunities})

    def test_feature_family_ledger_classifies_hermes_update_security_and_duplicate_authority(self):
        subsystems = {
            "eve": {"organs": [], "components": []},
            "openclaw": {"feature_family_reviews": []},
            "hermes": {
                "capability_families": [
                    {
                        "id": "supply_chain_security",
                        "status": "findings_46",
                        "blocking_severity_count": 16,
                        "severity_counts": {"HIGH": 10, "MODERATE": 6, "UNKNOWN": 30},
                        "eve_role": "read-only audit",
                        "recommended_next_test": "canary dependency fixes",
                        "evidence": ["hermes security audit --json"],
                    },
                    {
                        "id": "source_update",
                        "status": "update_available_265_commits",
                        "eve_role": "upstream feature candidate",
                        "recommended_next_test": "rebase local repair in canary",
                        "evidence": ["hermes version"],
                    },
                    {
                        "id": "gateway_messaging",
                        "status": "available_stopped",
                        "eve_role": "duplicate body",
                        "recommended_next_test": "keep stopped",
                        "evidence": ["hermes gateway status"],
                    },
                ],
                "latest_run": {
                    "created_at": "2026-07-20T03:50:03+00:00",
                    "local_64k_lab_requested": True,
                    "strict_json_ok": True,
                    "json_repair_used": False,
                },
            },
        }

        reviews = intelligence.build_subsystem_feature_family_reviews(subsystems)
        by_id = {item["id"]: item for item in reviews}
        opportunities = intelligence.build_opportunities(subsystems)
        opportunity_ids = {item["id"] for item in opportunities}

        self.assertEqual("configure", by_id["hermes:supply_chain_security"]["decision"])
        self.assertEqual("canary", by_id["hermes:source_update"]["decision"])
        self.assertEqual("reject", by_id["hermes:gateway_messaging"]["decision"])
        self.assertIn("hermes_supply_chain_findings", opportunity_ids)
        self.assertIn("hermes_upstream_update_canary", opportunity_ids)

    def test_nonblocking_hermes_security_findings_remain_monitored_not_reconfigured(self):
        subsystems = {
            "eve": {"organs": [], "components": []},
            "openclaw": {"feature_family_reviews": []},
            "hermes": {
                "capability_families": [
                    {
                        "id": "supply_chain_security",
                        "status": "findings_1",
                        "blocking_severity_count": 0,
                        "severity_counts": {"UNKNOWN": 1},
                        "eve_role": "read-only audit",
                        "recommended_next_test": "monitor compatible fixed version",
                        "evidence": ["hermes security audit --json"],
                    }
                ]
            },
        }

        reviews = intelligence.build_subsystem_feature_family_reviews(subsystems)
        by_id = {item["id"]: item for item in reviews}
        opportunities = {item["id"]: item for item in intelligence.build_opportunities(subsystems)}

        self.assertEqual("use_existing", by_id["hermes:supply_chain_security"]["decision"])
        self.assertEqual("monitor", opportunities["hermes_supply_chain_findings"]["status"])
        self.assertEqual("low", opportunities["hermes_supply_chain_findings"]["priority"])

    def test_openclaw_code_safety_finding_is_accepted_only_outside_eve_skill_filter(self):
        base_kwargs = {
            "current_config": {"gateway": {"bind": "loopback"}},
            "config_valid": True,
            "memory_status": {"ok": True},
            "plugins": [],
            "tasks": {},
            "commitments": {},
            "security": {
                "findings": [
                    {
                        "id": "skills.code_safety",
                        "severity": "critical",
                        "title": 'Skill "turnstile-spin" contains dangerous code patterns',
                    }
                ]
            },
            "mcp": {},
            "hooks": {},
            "cron": {},
            "isolation": {},
            "approvals": {},
            "runtime_status": {"ok": True},
            "deterministic_audit": {"ok": True, "status": "ready"},
        }

        unexposed = intelligence.build_openclaw_feature_family_reviews(
            **base_kwargs,
            skills={"agent_skill_filter": ["eve_self_repair"]},
        )
        unexposed_security = next(item for item in unexposed if item["id"] == "openclaw:security_audit")
        self.assertEqual("use_existing", unexposed_security["decision"])
        self.assertIn(
            "accepted:not_admitted_skill:turnstile-spin:skills.code_safety",
            unexposed_security["evidence"],
        )

        exposed = intelligence.build_openclaw_feature_family_reviews(
            **base_kwargs,
            skills={"agent_skill_filter": ["turnstile-spin"]},
        )
        exposed_security = next(item for item in exposed if item["id"] == "openclaw:security_audit")
        self.assertEqual("configure", exposed_security["decision"])
        self.assertIn("skills.code_safety", exposed_security["configuration_action"])

    def test_oss_service_metadata_is_evidence_not_a_feature_family(self):
        subsystems = {
            "eve": {
                "organs": [],
                "components": [],
                "oss_substrates": {
                    "service_status": {
                        "phoenix": "not_running",
                        "langfuse": "not_running",
                        "checked_at": "2026-07-20T18:43:34+00:00",
                        "preflight_ran_this_turn": False,
                        "last_preflight_at": "2026-07-20T18:08:59+00:00",
                        "last_preflight": {"phoenix": "cli_ready", "langfuse": "ready_to_start"},
                    }
                },
            },
            "openclaw": {"feature_family_reviews": []},
            "hermes": {"capability_families": []},
        }

        reviews = intelligence.build_subsystem_feature_family_reviews(subsystems)
        service_reviews = {item["id"]: item for item in reviews if item["id"].startswith("eve:oss_service:")}

        self.assertEqual({"eve:oss_service:phoenix", "eve:oss_service:langfuse"}, set(service_reviews))
        self.assertIn("current_runtime_status=not_running", service_reviews["eve:oss_service:phoenix"]["evidence"])
        self.assertIn("last_preflight=cli_ready", service_reviews["eve:oss_service:phoenix"]["evidence"])

    def test_effective_attestation_covers_live_openclaw_and_hermes_consumers(self):
        subsystems = {
            "eve": {
                "config_provenance": {},
                "organs": [
                    {
                        "id": "beads_work_graph_substrate",
                        "status": "healthy",
                        "operational_status": "ready",
                        "summary": "One-way projection is current and live parity passed.",
                        "evidence": ["bridge_status=verified", "bridge_live_parity=yes"],
                        "authority_boundary": "Eve remains canonical task and scheduler authority.",
                    }
                ],
                "oss_substrates": {
                    "deepeval_agent_metrics": {
                        "status": "passed",
                        "package_version": "4.1.2",
                        "records_considered": 40,
                        "loop_records_considered": 40,
                        "permission_score": 1.0,
                        "loop_min_score": 1.0,
                        "loop_failure_count": 0,
                        "unauthorized_actions": [],
                        "metric_contract": ["ToolPermissionMetric", "AgentLoopDetectionMetric"],
                        "deterministic": True,
                        "network_used": False,
                        "model_used": False,
                        "hidden_tests_used": False,
                    }
                },
            },
            "openclaw": {
                "config_path": "/tmp/openclaw.json",
                "config_valid": True,
                "memory": {"ok": True, "backends": ["qmd"], "agents": [], "retrieval_smoke": {"ok": True}},
                "runtime": {
                    "ok": True,
                    "service": {"id": "ai.openclaw.eve-repair", "status": "running", "pid": 123},
                    "gateway": {"reachable": True},
                    "probe": {"rpc_ok": True},
                    "heartbeat": {"default_agent_id": "main", "enabled_count": 0, "enabled_agent_ids": [], "duplicate_scheduler_risk": False},
                },
                "runtime_surfaces": {
                    "tasks": {
                        "error_count": 0,
                        "total": 5,
                        "failures": 3,
                        "failure_rate": 0.6,
                        "enabled_job_count": 1,
                        "active_outcome_coverage_count": 1,
                        "active_latest_failure_count": 0,
                        "active_reliability_ok": True,
                        "active_failure_rate": 0.0,
                        "active_sources": [{"source_id": "active", "recent_success_streak": 2}],
                        "retired_sources": [{"source_id": "retired", "failure_count": 3}],
                    },
                    "cron": {"enabled_count": 1, "duplicate_scheduler_risk": False, "jobs": []},
                    "skills": {
                        "model_visible": 2,
                        "command_visible": 2,
                        "blocked": 0,
                        "missing_requirements": 0,
                        "agent_skill_filter": ["eve_one", "eve_two"],
                    },
                    "hooks": {
                        "count": 1,
                        "hooks": [{"name": "eve-evidence-ingest", "events": ["gateway:startup", "command"]}],
                    },
                    "mcp": {"server_count": 1, "server_ids": ["eve-openclaw-channels"]},
                    "approvals": {"configured": True, "effective_scope_count": 2, "default_security": "full", "default_ask": "off"},
                    "context_management": {
                        "compaction_mode": "safeguard",
                        "mid_turn_precheck_enabled": True,
                        "context_pruning_mode": "cache-ttl",
                        "context_pruning_ttl": "1m",
                        "keep_last_assistants": 3,
                        "loop_detection_enabled": True,
                        "configured_ok": True,
                    },
                    "deterministic_audit": {"ok": True, "status": "ready", "checks": {"status_ready": True}},
                },
                "feature_family_reviews": [{"family": "security_audit", "decision": "use_existing"}],
            },
            "hermes": {
                "config_path": "/tmp/hermes/config.yaml",
                "serious_learning_route": "local_64k_lab_constrained_json",
                "direct_state_write_allowed": False,
                "latest_run": {
                    "id": "run-one",
                    "status": "passed",
                    "local_64k_lab_requested": True,
                    "strict_json_ok": True,
                    "json_repair_used": False,
                },
                "capability_families": [
                    {"id": "config_and_prompt_hygiene", "status": "current"},
                    {"id": "supply_chain_security", "status": "findings_1", "blocking_severity_count": 0},
                    {"id": "source_update", "status": "update_available_271_commits"},
                ],
            },
        }

        attestations = intelligence.build_effective_configuration_attestations(subsystems)
        by_id = {item["id"]: item for item in attestations}

        for attestation_id in {
            "openclaw:heartbeat_ownership",
            "openclaw:context_management",
            "openclaw:skill_admission",
            "openclaw:evidence_hook",
            "openclaw:mcp_channel_bridge",
            "openclaw:execution_policy",
            "openclaw:deterministic_audit",
            "hermes:proposal_route",
            "hermes:profile_hygiene",
            "hermes:supply_chain",
        }:
            self.assertEqual("effective", by_id[attestation_id]["status"], attestation_id)
        self.assertEqual("effective", by_id["openclaw:taskflow_outcomes"]["status"])
        self.assertEqual(0.6, by_id["openclaw:taskflow_outcomes"]["consequence"]["historical_failure_rate"])
        self.assertEqual("configured_unverified", by_id["hermes:source_update_canary"]["status"])
        self.assertEqual("effective", by_id["eve:organ:beads_work_graph_substrate"]["status"])
        self.assertEqual("effective", by_id["eve:oss_deepeval_agent_boundaries"]["status"])
        self.assertEqual(1.0, by_id["eve:oss_deepeval_agent_boundaries"]["consequence"]["permission_score"])

    def test_component_watchlist_covers_installed_improvement_substrates(self):
        ids = {item["id"] for item in eve.component_watchlist(eve.load_config())}

        self.assertTrue(
            {
                "dagster-eve-runtime",
                "phoenix-eve-runtime",
                "deepeval-eve-runtime",
                "dvc-eve-runtime",
                "langfuse-eve-runtime",
                "langgraph-eve-runtime",
                "openinference-eve-runtime",
                "opentelemetry-eve-runtime",
                "peft-eve-runtime",
                "ragas-eve-runtime",
                "agent-copilotkit",
            }.issubset(ids)
        )

    def test_python_package_probe_resolves_runtime_venv_to_source_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = base / "runtime"
            source = base / "source"
            for root in (runtime, source):
                root.mkdir()
                (root / "eve.py").write_text("# marker\n", encoding="utf-8")
            source_python = source / ".venv" / "bin" / "python"
            source_python.parent.mkdir(parents=True)
            source_python.write_text("#!/bin/sh\n", encoding="utf-8")
            source_python.chmod(source_python.stat().st_mode | stat.S_IXUSR)
            observed = {}

            def run_component(command, timeout=10):
                del timeout
                observed["command"] = command
                return subprocess.CompletedProcess(command, 0, "4.14.1\n", ""), ""

            with patch.object(eve, "ROOT", runtime), patch.object(
                eve, "eve_checkout_root_candidates", return_value=[runtime, source]
            ), patch.object(eve, "run_component_command", side_effect=run_component):
                result = eve.python_package_local_version(
                    "langfuse",
                    [str(runtime / ".venv" / "bin" / "python")],
                    timeout=3,
                )

        self.assertTrue(result["ok"])
        self.assertEqual("4.14.1", result["version"])
        self.assertEqual(str(source_python), observed["command"][0])

    def test_package_revision_matches_upstream_stable_release(self):
        self.assertTrue(
            intelligence.release_mentions_installed_version(
                {"tag": "v2026.7.1", "name": "OpenClaw 2026.7.1"},
                "2026.7.1-2",
            )
        )
        self.assertFalse(
            intelligence.release_mentions_installed_version(
                {"tag": "v2026.7.2-beta.3", "name": "OpenClaw 2026.7.2 beta 3"},
                "2026.7.1-2",
            )
        )

    def test_release_summary_skips_boilerplate_before_real_feature(self):
        self.assertEqual(
            "Add deterministic tool-permission scoring.",
            intelligence._release_feature_summary(
                {
                    "tag": "v4.1.0",
                    "feature_bullets": [
                        "What's Changed",
                        "<details open>",
                        "New to `example`? Get started [here](https://example.test).",
                        "chore(deps): bump a dependency by @dependabot[bot]",
                        "Add deterministic tool-permission scoring.",
                    ],
                }
            ),
        )


class CapabilityIntelligenceIntegrationTests(unittest.TestCase):
    def test_current_subsystem_inventory_query_uses_intelligence_not_research(self):
        prompt = (
            "Without installing anything, tell me the currently verified installed versions of OpenClaw, "
            "QMD, MCPorter, and Hermes; say whether any actionable configuration or package update remains; "
            "name the evidence and check time. Do not guess."
        )

        self.assertTrue(eve.requests_capability_intelligence_chat(prompt))
        self.assertFalse(eve.requests_capability_research_chat(prompt))
        self.assertEqual(
            ["openclaw", "qmd", "mcporter", "hermes"],
            eve.capability_intelligence_query_targets(prompt),
        )

    def test_broad_openclaw_docs_question_stays_capability_research(self):
        prompt = "Read the OpenClaw docs and tell me what else OpenClaw can do."

        self.assertFalse(eve.requests_capability_intelligence_chat(prompt))
        self.assertTrue(eve.requests_capability_research_chat(prompt))

        self.assertTrue(
            eve.requests_capability_intelligence_chat(
                "Show the current status and active configuration of all of your subsystems."
            )
        )

    def test_new_feature_and_configuration_question_uses_living_ledger(self):
        prompt = (
            "What new features have OpenClaw, Hermes, and the technology Eve sits on added, "
            "and which configuration changes should Eve adopt to get the most from them?"
        )

        self.assertTrue(eve.requests_capability_intelligence_chat(prompt))
        self.assertFalse(eve.requests_capability_research_chat(prompt))
        self.assertEqual(["all"], eve.capability_intelligence_query_targets(prompt))

    def test_grounded_capability_response_reports_versions_check_time_and_no_false_updates(self):
        snapshot = {
            "generated_at": "2026-07-20T04:29:24+00:00",
            "source": "daemon",
            "opportunities": [
                {
                    "id": "research_source_drift",
                    "status": "research_only",
                    "finding": "source moved",
                }
            ],
            "subsystems": {
                "eve": {
                    "components": [
                        {
                            "id": "openclaw",
                            "update_available": True,
                            "local_version": "2026.7.1-2",
                            "latest_version": "2026.7.1-2",
                        },
                        {
                            "id": "pytrees-system-python",
                            "update_available": False,
                            "blocked_latest_version": "2.5.0",
                            "blocked_version_reason": "incompatible with the resident Python runtime",
                        },
                    ]
                },
                "openclaw": {
                    "version": "2026.7.1-2",
                    "config_valid": True,
                    "config_schema_path_count": 5275,
                    "plugins": [{"id": "acpx"}, {"id": "memory-core"}],
                    "enabled_plugin_ids": ["acpx", "memory-core"],
                    "memory": {
                        "ok": True,
                        "agents": [
                            {"files": 106, "chunks": 106},
                            {"files": 106, "chunks": 106},
                        ],
                        "retrieval_smoke": {"ok": True},
                    },
                    "supporting_tools": {
                        "qmd": {"available": True, "version": "2.5.3"},
                        "mcporter": {
                            "available": True,
                            "version": "0.12.3",
                            "config_read_ok": True,
                            "configured_values": {
                                "mcpServers": {"qmd": {"lifecycle": {"mode": "keep-alive"}}}
                            },
                        },
                    },
                },
                "hermes": {
                    "version": "0.18.2",
                    "config_path_count": 846,
                    "configured_values": {"model": {"context_length": 16384}},
                    "serious_learning_route": "local_64k_lab_constrained_json",
                    "feature_policy_summary": {
                        "allowed_now_count": 4,
                        "feature_count": 12,
                        "direct_eve_authority_count": 0,
                    },
                    "latest_run": {
                        "id": "hermes-smoke-1",
                        "status": "passed_with_warnings",
                        "local_64k_lab_requested": True,
                        "strict_json_ok": True,
                        "json_repair_used": False,
                    },
                },
            },
        }
        update_state = {"updated_at": "2026-07-20T04:28:00+00:00", "components": []}
        prompt = "What installed versions of OpenClaw, QMD, MCPorter, and Hermes are verified? Include update status and evidence."

        with patch.object(eve, "load_capability_intelligence", return_value=snapshot), patch.object(
            eve, "load_component_update_state", return_value=update_state
        ):
            result = eve.capability_intelligence_chat_response(prompt, {})

        self.assertIsNotNone(result)
        response = result["response"]
        self.assertIn("OpenClaw `2026.7.1-2`", response)
        self.assertIn("QMD `2.5.3`", response)
        self.assertIn("MCPorter `0.12.3`", response)
        self.assertIn("Hermes `0.18.2`", response)
        self.assertIn("2026-07-20T04:29:24+00:00", response)
        self.assertIn("Actionable configuration findings: **0**", response)
        self.assertIn("Verified installed-package update candidates: **0**", response)
        self.assertIn("This is not an installed update", response)
        self.assertIn("No language model invented the versions above", response)
        self.assertEqual("capability-intelligence-guard", result["model"])

    def test_grounded_capability_response_exposes_feature_state_and_configuration_gate(self):
        snapshot = {
            "generated_at": "2026-07-20T12:00:00+00:00",
            "source": "daemon",
            "opportunities": [],
            "feature_review_summary": {
                "candidate_count": 1,
                "state_counts": {"in_use": 1, "lab_candidate": 1, "research_only": 1},
                "candidate_ids": ["release:dagster-io-dagster@1.13.14"],
            },
            "feature_reviews": [
                {
                    "id": "release:dagster-io-dagster@1.13.14",
                    "repository": "dagster-io/dagster",
                    "component_id": "dagster-eve-runtime",
                    "target_version": "1.13.14",
                    "installed_version": "1.13.3",
                    "state": "lab_candidate",
                    "visible_in_current_feed": True,
                    "feature_summary": "Fixed recurring asset materialization.",
                    "required_gate": "Materialize the read-only Eve evidence assets.",
                }
            ],
            "configuration_reviews": [
                {
                    "subsystem": "eve",
                    "posture": "attention",
                    "configured_path_count": 367,
                    "known_path_count": 367,
                    "attention_ids": ["release_adoption_dagster"],
                }
            ],
            "subsystems": {"eve": {"components": []}, "openclaw": {}, "hermes": {}},
            "changes": {"new_releases": []},
        }
        prompt = "Show all technology Eve sits on, new features, and configuration adoption candidates."

        with patch.object(eve, "load_capability_intelligence", return_value=snapshot), patch.object(
            eve, "load_component_update_state", return_value={"components": []}
        ):
            result = eve.capability_intelligence_chat_response(prompt, {})

        response = result["response"]
        self.assertIn("Feature and update adoption ledger", response)
        self.assertIn("[LAB_CANDIDATE]", response)
        self.assertIn("dagster-io/dagster", response)
        self.assertIn("Materialize the read-only Eve evidence assets", response)
        self.assertIn("Configuration posture", response)
        self.assertIn("do not enable every optional setting", response)

    def test_broad_feature_response_retains_in_use_evidence_amid_research_feed(self):
        research_reviews = [
            {
                "id": f"release:research-{index}",
                "repository": f"example/research-{index}",
                "component_id": f"research-{index}",
                "target_version": f"v{index}.0.0",
                "state": "research_only",
                "visible_in_current_feed": True,
                "feature_summary": "Research surface.",
                "required_gate": "Keep research-only.",
            }
            for index in range(12)
        ]
        in_use = {
            "id": "release:openclaw-openclaw@v2026.7.1",
            "repository": "openclaw/openclaw",
            "component_id": "openclaw",
            "target_version": "v2026.7.1",
            "installed_version": "2026.7.1-2",
            "state": "in_use",
            "visible_in_current_feed": True,
            "feature_summary": "Stable feature set is installed.",
            "required_gate": "No adoption needed.",
        }
        payload = {
            "snapshot": {"generated_at": "2026-07-20T12:00:00+00:00", "source": "daemon"},
            "capability_checked_at": "2026-07-20T12:00:00+00:00",
            "subsystems": {"eve": {}, "openclaw": {}, "hermes": {}},
            "targets": ["all"],
            "feature_reviews": research_reviews + [in_use],
            "feature_review_summary": {
                "candidate_count": 0,
                "state_counts": {"in_use": 1, "research_only": 12},
            },
            "configuration_reviews": [],
            "actionable": [],
            "installed_package_updates": [],
            "source_drifts": [],
            "blocked_latests": [],
            "evidence_paths": [],
        }

        response = eve.format_capability_intelligence_chat_response(payload)

        self.assertIn("[IN_USE]", response)
        self.assertIn("Stable feature set is installed", response)

    def test_update_status_separates_source_drift_from_installed_package_update(self):
        payload = {
            "snapshot": {"generated_at": "2026-07-20T04:29:24+00:00", "source": "daemon"},
            "subsystems": {},
            "targets": ["openclaw", "qmd", "mcporter", "hermes"],
            "components": [{"id": "openclaw"}],
            "installed_package_updates": [],
            "source_drifts": [{"id": "openclaw"}],
            "opportunities": [{"id": "research_source_drift", "status": "research_only"}],
            "actionable": [],
            "blocked_latests": [],
            "component_checked_at": "2026-07-20T04:28:00+00:00",
            "capability_checked_at": "2026-07-20T04:29:24+00:00",
            "evidence_paths": [],
        }
        with patch.object(eve, "capability_intelligence_status_payload", return_value=payload):
            result = eve.run_bounded_updates_status({}, source="test")

        self.assertEqual(0, result["update_count"])
        self.assertEqual(1, result["source_drift_count"])
        self.assertIn("0 installed-package update candidate(s)", result["summary"])

    def test_daemon_state_reconciles_newer_manual_capability_snapshot(self):
        state = {
            "last_capability_intelligence_at": "2026-07-20T04:23:09+00:00",
            "last_capability_intelligence_upstream_at": "2026-07-20T04:23:09+00:00",
            "last_capability_intelligence_hermes_at": "2026-07-20T04:23:09+00:00",
            "capability_intelligence_summary": "1213 paths; degraded",
        }
        snapshot = {
            "generated_at": "2026-07-20T04:29:24+00:00",
            "summary": "6488 paths; zero actionable findings",
            "refresh": {
                "local": True,
                "upstream_releases": True,
                "hermes_inventory": True,
            },
        }

        changed = eve.reconcile_capability_intelligence_state(state, snapshot)

        self.assertTrue(changed)
        self.assertEqual("2026-07-20T04:29:24+00:00", state["last_capability_intelligence_at"])
        self.assertEqual("2026-07-20T04:29:24+00:00", state["last_capability_intelligence_upstream_at"])
        self.assertEqual("2026-07-20T04:29:24+00:00", state["last_capability_intelligence_hermes_at"])
        self.assertIn("6488 paths", state["capability_intelligence_summary"])

        self.assertFalse(eve.reconcile_capability_intelligence_state(state, snapshot))

    def test_daemon_state_backfills_v2_fields_for_same_snapshot(self):
        state = {
            "last_capability_intelligence_at": "2026-07-20T12:18:02+00:00",
            "capability_intelligence_summary": "current snapshot",
        }
        snapshot = {
            "generated_at": "2026-07-20T12:18:02+00:00",
            "summary": "current snapshot",
            "feature_review_summary": {
                "state_counts": {"in_use": 8, "candidate": 3, "lab_candidate": 3},
                "candidate_ids": ["release:one", "release:two"],
            },
            "configuration_reviews": [
                {"subsystem": "eve", "posture": "attention"},
                {"subsystem": "openclaw", "posture": "optimized_for_current_contracts"},
            ],
        }

        self.assertTrue(eve.reconcile_capability_intelligence_state(state, snapshot))
        self.assertEqual(8, state["capability_feature_review_counts"]["in_use"])
        self.assertEqual(["release:one", "release:two"], state["capability_adoption_candidate_ids"])
        self.assertEqual(["eve"], state["capability_configuration_attention_ids"])
        self.assertFalse(eve.reconcile_capability_intelligence_state(state, snapshot))

    def test_autonomy_choice_prompt_exposes_capability_candidates_outside_truncated_snapshot(self):
        candidate_id = "release:confident-ai-deepeval@v4.1.0"
        snapshot = {
            "autonomy": {},
            "large_earlier_state": "x" * 10000,
            "capability_intelligence": {
                "generated_at": "2026-07-20T12:18:02+00:00",
                "summary": "Six adoption candidates need bounded review.",
                "feature_review_counts": {"candidate": 3, "lab_candidate": 3},
                "adoption_candidate_ids": [candidate_id],
                "configuration_attention_ids": ["eve"],
                "opportunity_ids": ["installed_component_updates"],
            },
        }

        prompt = eve.build_autonomy_free_run_choice_prompt(
            run_id="autonomy-test",
            menu={"updates_status": "Inspect current update evidence."},
            guidance={},
            snapshot=snapshot,
            previous_actions=[],
            remaining_seconds=60,
            lane_name="fast",
            council_mode=False,
        )

        self.assertIn("Current capability-adoption self-status", prompt)
        self.assertIn(candidate_id, prompt)
        self.assertLess(prompt.index(candidate_id), prompt.index("Current monitor snapshot"))

    def test_capability_research_skips_fileprovider_denied_upstream_tree(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docs = root / "docs"
            docs.mkdir()
            (docs / "tool.md").write_text("OpenClaw tools and memory configuration", encoding="utf-8")
            upstreams = root / "vendor" / "upstreams"
            upstreams.mkdir(parents=True)
            original_iterdir = Path.iterdir

            def guarded_iterdir(path):
                if path == upstreams:
                    raise PermissionError(1, "Operation not permitted", str(path))
                return original_iterdir(path)

            with patch.object(eve, "eve_checkout_root_candidates", return_value=[root]), patch.object(
                Path, "iterdir", guarded_iterdir
            ):
                sources = eve.collect_capability_research_sources("OpenClaw")

        self.assertTrue(any(item.get("type") == "project_doc" for item in sources))

    def test_launchd_services_expose_homebrew_node_and_local_substrate_bins(self):
        expected_paths = {
            "/opt/homebrew/opt/node/bin",
            "/opt/homebrew/bin",
            str(Path.home() / ".local" / "bin"),
        }
        with patch.object(eve, "require_native_service_install_support"), patch.object(
            eve, "sync_runtime_bundle"
        ):
            daemon = plistlib.loads(eve.build_launch_agent_plist())
        daemon_paths = set(daemon["EnvironmentVariables"]["PATH"].split(":"))
        self.assertTrue(expected_paths.issubset(daemon_paths))

        with patch.object(eve.eve_platform, "is_macos", return_value=True), patch.object(
            eve, "load_config", return_value={}
        ):
            companion_payloads = eve.build_macos_continuity_launch_agent_plists()
        for payload in companion_payloads.values():
            paths = set(plistlib.loads(payload)["EnvironmentVariables"]["PATH"].split(":"))
            self.assertTrue(expected_paths.issubset(paths))

    def test_save_writes_latest_history_readable_briefing_and_compact_event(self):
        snapshot = {
            "schema_id": intelligence.SCHEMA_ID,
            "id": "snapshot-1",
            "generated_at": "2026-07-20T00:00:00+00:00",
            "source": "test",
            "summary": "checked",
            "fingerprint": "abc",
            "refresh": {"local": True},
            "subsystems": {
                "eve": {
                    "git_head": "head",
                    "config_catalog": [],
                    "organs": [],
                    "components": [
                        {
                            "id": "pytrees-system-python",
                            "blocked_latest_version": "2.5.0",
                            "blocked_version_reason": "incompatible Python syntax",
                        }
                    ],
                    "fingerprint": "e",
                },
                "openclaw": {"version": "1", "config_schema_path_count": 2, "fingerprint": "o"},
                "hermes": {"version": "2", "config_path_count": 3, "fingerprint": "h"},
            },
            "release_feeds": [],
            "changes": {"material_change": False, "baseline_created": True, "counts": {}},
            "opportunities": [{"id": "x", "priority": "high", "status": "actionable", "finding": "finding", "recommended_change": "test it"}],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            latest = root / "latest.json"
            history = root / "history.jsonl"
            report = root / "report.md"
            event = root / "event.jsonl"
            with (
                patch.object(eve, "CAPABILITY_INTELLIGENCE_PATH", latest),
                patch.object(eve, "CAPABILITY_INTELLIGENCE_HISTORY_PATH", history),
                patch.object(eve, "CAPABILITY_INTELLIGENCE_REPORT_PATH", report),
                patch.object(eve, "EVENT_LEDGER_PATH", event),
                patch.object(eve, "ensure_store", lambda: None),
                patch.object(eve, "mirror_store_file_to_runtime", lambda path: None),
            ):
                eve.save_capability_intelligence(snapshot)

            saved = json.loads(latest.read_text(encoding="utf-8"))
            history_records = eve_store.read_jsonl_records(history)
            events = eve_store.read_jsonl_records(event)
            briefing = report.read_text(encoding="utf-8")

        self.assertEqual("snapshot-1", saved["id"])
        self.assertEqual("snapshot-1", history_records[0]["id"])
        self.assertEqual("CapabilityIntelligenceEvent", events[0]["payload"]["observation_kind"])
        self.assertIn("Live Integration Proof", briefing)
        self.assertIn("Current Optimization Queue", briefing)
        self.assertIn("Configuration Posture", briefing)
        self.assertIn("Feature And Update Adoption Ledger", briefing)
        self.assertIn("Known Blocked Latests", briefing)
        self.assertIn("incompatible Python syntax", briefing)
        self.assertNotIn("configured_values", repr(history_records[0]))

    def test_cli_history_reads_compact_runtime_ledger(self):
        records = [{"generated_at": "2026-07-20T00:00:00+00:00", "source": "daemon", "changes": {"material_change": False, "counts": {}}, "opportunities": []}]
        with patch.object(eve, "read_capability_intelligence_history", return_value=records), patch("sys.stdout"):
            result = eve.cmd_capabilities_intelligence(
                Namespace(intelligence_command="history", runtime=True, limit=20, full=False, json=False)
            )
        self.assertEqual(0, result)


if __name__ == "__main__":
    unittest.main()
