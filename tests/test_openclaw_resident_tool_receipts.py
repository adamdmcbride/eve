import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import eve_capability_intelligence as intelligence


class OpenClawResidentToolReceiptTests(unittest.TestCase):
    def _trajectory_path(self, root: Path) -> Path:
        path = root / "agents" / "main" / "sessions" / "receipt.trajectory.jsonl"
        path.parent.mkdir(parents=True)
        return path

    def _write_successful_trajectory(self, path: Path) -> None:
        run_id = "run-resident-wiki"
        call_id = "call-wiki-search"
        base = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=4)
        events = [
            {
                "type": "context.compiled",
                "runId": run_id,
                "ts": base.isoformat(),
                "data": {
                    "systemPrompt": "private prompt must not be persisted",
                    "prompt": "private user text must not be persisted",
                    "tools": [{"name": "wiki_search", "description": "search"}],
                },
            },
            {
                "type": "model.completed",
                "runId": run_id,
                "ts": (base + timedelta(seconds=2)).isoformat(),
                "data": {
                    "timedOut": False,
                    "idleTimedOut": False,
                    "promptError": None,
                    "messagesSnapshot": [
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "toolCall",
                                    "id": call_id,
                                    "name": "wiki_search",
                                    "arguments": {"query": "private memory query"},
                                }
                            ],
                        },
                        {
                            "role": "toolResult",
                            "toolCallId": call_id,
                            "toolName": "wiki_search",
                            "isError": False,
                            "details": {"results": [{"private": "memory content"}]},
                            "content": [
                                {"type": "text", "text": "private memory result"}
                            ],
                        },
                    ],
                },
            },
            {
                "type": "session.ended",
                "runId": run_id,
                "ts": (base + timedelta(seconds=3)).isoformat(),
                "data": {"status": "success"},
            },
        ]
        path.write_text("\n".join(json.dumps(event) for event in events) + "\n")

    def test_extracts_content_free_success_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            path = self._trajectory_path(state_dir)
            self._write_successful_trajectory(path)

            receipts = intelligence.collect_openclaw_resident_tool_receipts(
                state_dir,
                tool_names=["wiki_search"],
            )

        self.assertEqual(1, len(receipts))
        receipt = receipts[0]
        self.assertEqual("wiki_search", receipt["tool"])
        self.assertEqual(64, len(receipt["run_id_sha256"]))
        self.assertNotIn("run_id", receipt)
        self.assertTrue(receipt["catalog_admitted"])
        self.assertTrue(receipt["tool_call_observed"])
        self.assertTrue(receipt["tool_result_ok"])
        self.assertTrue(receipt["run_success"])
        self.assertEqual(1, receipt["result_count"])
        self.assertTrue(receipt["consequence_verified"])
        self.assertEqual(64, len(receipt["consequence_shape_sha256"]))
        self.assertNotIn("result_sha256", receipt)
        self.assertNotIn("result_shape", receipt)
        self.assertFalse(receipt["content_persisted"])
        serialized = json.dumps(receipt)
        self.assertNotIn("private prompt", serialized)
        self.assertNotIn("private user", serialized)
        self.assertNotIn("private memory", serialized)

    def test_rejects_stale_or_incomplete_trajectory(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            path = self._trajectory_path(state_dir)
            self._write_successful_trajectory(path)
            old = time.time() - (7 * 60 * 60)
            os.utime(path, (old, old))
            stale = intelligence.collect_openclaw_resident_tool_receipts(
                state_dir,
                tool_names=["wiki_search"],
                max_age_seconds=6 * 60 * 60,
            )
            self.assertEqual([], stale)

            self._write_successful_trajectory(path)
            records = [json.loads(line) for line in path.read_text().splitlines()]
            stale_time = datetime.now(timezone.utc) - timedelta(hours=7)
            for index, record in enumerate(records):
                record["ts"] = (stale_time + timedelta(seconds=index)).isoformat()
            path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
            stale_event_with_fresh_file = intelligence.collect_openclaw_resident_tool_receipts(
                state_dir,
                tool_names=["wiki_search"],
                max_age_seconds=6 * 60 * 60,
            )
            self.assertEqual([], stale_event_with_fresh_file)

            self._write_successful_trajectory(path)
            records = [json.loads(line) for line in path.read_text().splitlines()]
            records[0]["data"]["tools"] = []
            path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
            incomplete = intelligence.collect_openclaw_resident_tool_receipts(
                state_dir,
                tool_names=["wiki_search"],
            )
            self.assertEqual([], incomplete)

    def test_rejects_mismatched_result_and_does_not_verify_empty_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            path = self._trajectory_path(state_dir)
            self._write_successful_trajectory(path)
            records = [json.loads(line) for line in path.read_text().splitlines()]
            tool_result = records[1]["data"]["messagesSnapshot"][1]
            tool_result["toolName"] = "wiki_status"
            path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
            self.assertEqual(
                [],
                intelligence.collect_openclaw_resident_tool_receipts(
                    state_dir, tool_names=["wiki_search", "wiki_status"]
                ),
            )

            self._write_successful_trajectory(path)
            records = [json.loads(line) for line in path.read_text().splitlines()]
            records[1]["data"]["messagesSnapshot"][1]["details"]["results"] = []
            path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
            receipts = intelligence.collect_openclaw_resident_tool_receipts(
                state_dir, tool_names=["wiki_search"]
            )
            self.assertEqual(1, len(receipts))
            self.assertFalse(receipts[0]["consequence_verified"])

            self._write_successful_trajectory(path)
            records = [json.loads(line) for line in path.read_text().splitlines()]
            messages = records[1]["data"]["messagesSnapshot"]
            records[1]["data"]["messagesSnapshot"] = [messages[1], messages[0]]
            path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
            self.assertEqual(
                [],
                intelligence.collect_openclaw_resident_tool_receipts(
                    state_dir, tool_names=["wiki_search"]
                ),
            )

    def test_does_not_join_failed_attempt_receipt_to_successful_continuation(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            path = self._trajectory_path(state_dir)
            self._write_successful_trajectory(path)
            records = [json.loads(line) for line in path.read_text().splitlines()]
            records[1]["data"]["timedOut"] = True
            records[1]["data"]["promptError"] = "request timed out"
            records.insert(
                2,
                {
                    "type": "model.completed",
                    "runId": "run-resident-wiki",
                    "ts": "2026-08-23T17:20:02.500000+00:00",
                    "data": {
                        "timedOut": False,
                        "idleTimedOut": False,
                        "promptError": None,
                        "messagesSnapshot": [],
                    },
                },
            )
            path.write_text("\n".join(json.dumps(record) for record in records) + "\n")

            receipts = intelligence.collect_openclaw_resident_tool_receipts(
                state_dir,
                tool_names=["wiki_search"],
            )

        self.assertEqual([], receipts)

    def test_verified_receipt_advances_memory_wiki_lifecycle(self):
        expected_tools = [
            "wiki_apply",
            "wiki_get",
            "wiki_lint",
            "wiki_search",
            "wiki_status",
        ]
        reviews = intelligence.build_openclaw_feature_family_reviews(
            current_config={
                "gateway": {"bind": "loopback"},
                "tools": {"alsoAllow": expected_tools},
                "agents": {"defaults": {"heartbeat": {"every": "0m"}}},
            },
            config_valid=True,
            memory_status={},
            plugins=[{"id": "memory-wiki", "enabled": True}],
            tasks={},
            commitments={},
            security={},
            mcp={},
            skills={},
            hooks={},
            cron={},
            isolation={},
            approvals={},
            runtime_status={},
            deterministic_audit={},
            wiki_status={"status_ok": True, "cli_callable": True},
            resident_tool_receipts=[
                {
                    "tool": "wiki_search",
                    "catalog_admitted": True,
                    "tool_call_observed": True,
                    "tool_result_ok": True,
                    "run_success": True,
                    "consequence_verified": True,
                }
            ],
        )
        wiki = next(item for item in reviews if item["family"] == "memory_wiki")
        self.assertEqual("use_existing", wiki["decision"])
        self.assertEqual("verified", wiki["lifecycle"]["stage"])
        self.assertTrue(wiki["lifecycle"]["consequence_verified"])
        self.assertTrue(wiki["lifecycle"]["interfaces"]["resident_callable"])
        self.assertEqual(1, wiki["lifecycle"]["interfaces"]["receipt_count"])
        self.assertEqual(
            ["wiki_search"],
            wiki["lifecycle"]["interfaces"]["resident_callable_tools"],
        )
        self.assertEqual(
            ["wiki_search"],
            wiki["lifecycle"]["interfaces"]["consequence_verified_tools"],
        )

    def test_callable_empty_search_does_not_self_promote_to_verified(self):
        expected_tools = [
            "wiki_apply",
            "wiki_get",
            "wiki_lint",
            "wiki_search",
            "wiki_status",
        ]
        reviews = intelligence.build_openclaw_feature_family_reviews(
            current_config={
                "gateway": {"bind": "loopback"},
                "tools": {"alsoAllow": expected_tools},
                "agents": {"defaults": {"heartbeat": {"every": "0m"}}},
            },
            config_valid=True,
            memory_status={},
            plugins=[{"id": "memory-wiki", "enabled": True}],
            tasks={},
            commitments={},
            security={},
            mcp={},
            skills={},
            hooks={},
            cron={},
            isolation={},
            approvals={},
            runtime_status={},
            deterministic_audit={},
            wiki_status={"status_ok": True, "cli_callable": True},
            resident_tool_receipts=[
                {
                    "tool": "wiki_search",
                    "catalog_admitted": True,
                    "tool_call_observed": True,
                    "tool_result_ok": True,
                    "run_success": True,
                    "consequence_verified": False,
                }
            ],
        )
        wiki = next(item for item in reviews if item["family"] == "memory_wiki")
        self.assertEqual("callable", wiki["lifecycle"]["stage"])
        self.assertTrue(wiki["lifecycle"]["interfaces"]["resident_callable"])
        self.assertFalse(
            wiki["lifecycle"]["interfaces"]["resident_consequence_verified"]
        )
        self.assertEqual(
            [], wiki["lifecycle"]["interfaces"]["consequence_verified_tools"]
        )

    def test_model_context_capacity_detects_parallel_slot_overstatement(self):
        calls = []

        def fetcher(url, _timeout):
            calls.append(url)
            if url.endswith("/props"):
                context = 8192 if ":8080/" in url else 16384
                return {
                    "ok": True,
                    "payload": {"default_generation_settings": {"n_ctx": context}},
                }
            if url.endswith("/slots"):
                count = 2 if ":8080/" in url else 1
                context = 8192 if ":8080/" in url else 16384
                return {
                    "ok": True,
                    "payload": [{"id": index, "n_ctx": context} for index in range(count)],
                }
            self.fail(f"unexpected URL {url}")

        capacity = intelligence._compact_openclaw_model_context_capacity(
            {
                "models": {
                    "providers": {
                        "llamacpp": {
                            "baseUrl": "http://127.0.0.1:8080/v1",
                            "models": [{"id": "eve-fast", "contextWindow": 16384}],
                        },
                        "llamacpp-relationship": {
                            "baseUrl": "http://127.0.0.1:8080/v1",
                            "models": [{"id": "eve-fast", "contextWindow": 16384}],
                        },
                        "llamacpp-observer": {
                            "baseUrl": "http://127.0.0.1:8082/v1",
                            "models": [{"id": "eve-observer", "contextWindow": 16384}],
                        },
                    }
                }
            },
            fetcher=fetcher,
        )

        self.assertFalse(capacity["ok"])
        self.assertEqual(3, capacity["configured_local_model_count"])
        self.assertEqual(1, capacity["verified_count"])
        self.assertEqual(2, capacity["attention_count"])
        self.assertEqual(
            ["llamacpp/eve-fast", "llamacpp-relationship/eve-fast"],
            capacity["overdeclared_ids"],
        )
        self.assertEqual(4, len(calls), "shared endpoints should be probed once")
        serialized = json.dumps(capacity)
        self.assertNotIn("baseUrl", serialized)
        self.assertFalse(capacity["content_persisted"])

        reviews = intelligence.build_openclaw_feature_family_reviews(
            current_config={"gateway": {"bind": "loopback"}},
            config_valid=True,
            memory_status={},
            plugins=[],
            tasks={},
            commitments={},
            security={},
            mcp={},
            skills={},
            hooks={},
            cron={},
            isolation={},
            approvals={},
            runtime_status={},
            deterministic_audit={},
            model_context_capacity=capacity,
        )
        context_review = next(
            item for item in reviews if item["family"] == "model_context_capacity"
        )
        self.assertEqual("configure", context_review["decision"])
        self.assertEqual("enabled", context_review["lifecycle"]["stage"])

    def test_model_context_capacity_attestation_fails_closed_on_overstatement(self):
        capacity = {
            "configured_local_model_count": 1,
            "endpoint_count": 1,
            "verified_count": 0,
            "exact_count": 0,
            "attention_count": 1,
            "ok": False,
            "records": [
                {
                    "provider": "llamacpp",
                    "model": "eve-fast",
                    "declared_context_tokens": 16384,
                    "effective_context_tokens": 8192,
                    "slot_count": 2,
                    "status": "overdeclared",
                }
            ],
        }
        attestations = intelligence.build_effective_configuration_attestations(
            {
                "eve": {},
                "openclaw": {
                    "profile": "eve-repair",
                    "config_path": "/tmp/openclaw.json",
                    "config_valid": True,
                    "runtime": {"ok": True, "service": {}, "probe": {}},
                    "runtime_surfaces": {
                        "context_management": {
                            "configured_ok": True,
                            "compaction_mode": "safeguard",
                        },
                        "model_context_capacity": capacity,
                    },
                    "feature_family_reviews": [],
                },
                "hermes": {},
            }
        )
        attestation = next(
            item
            for item in attestations
            if item["id"] == "openclaw:model_context_capacity"
        )
        self.assertEqual("degraded", attestation["status"])
        self.assertFalse(attestation["consequence"]["verified"])
        self.assertIn("declared=16384 effective=8192", attestation["blockers"][0])


if __name__ == "__main__":
    unittest.main()
