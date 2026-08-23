import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import eve
import eve_governance


class EveGovernanceTests(unittest.TestCase):
    def test_ledger_records_normalize_to_cik_event_envelopes(self) -> None:
        action = {
            "id": "act-1",
            "created_at": "2026-04-28T12:00:00+00:00",
            "action": "openclaw_sync_check",
            "tree_status": "SUCCESS",
            "verification_ok": True,
            "permission_class": "operator_safe",
        }
        event = eve_governance.normalize_ledger_event("action_executions", action, include_payload=False)

        self.assertEqual("eve_event_envelope.v1", event["schema_version"])
        self.assertEqual("ToolResultEvent", event["type"])
        self.assertEqual("capability", event["cik_zone"])
        self.assertEqual(["operator_safe"], event["permissions_used"])
        self.assertIn("ledger:action_executions", event["provenance"])
        self.assertNotIn("tree_status", event["payload"])
        self.assertIn("record_keys", event["payload"])

    def test_hermes_memory_observation_cannot_grant_capability(self) -> None:
        proposal = eve_governance.proposal_envelope(
            "CapabilityPatchProposal",
            source="hermes",
            payload={"capability": "send_external_message"},
            evidence=["event-1"],
        )

        review = eve_governance.review_proposal(proposal)

        self.assertEqual("reject", review["decision"])
        self.assertFalse(review["accepted"])
        self.assertIn(
            "knowledge_cannot_grant_capability",
            {finding["code"] for finding in review["findings"]},
        )

    def test_openclaw_tool_output_cannot_rewrite_identity(self) -> None:
        proposal = eve_governance.proposal_envelope(
            "IdentityPatchProposal",
            source="openclaw",
            payload={"claim": "OpenClaw should redefine Eve's values."},
            evidence=["openclaw-event-1"],
        )

        review = eve_governance.review_proposal(proposal)

        self.assertEqual("reject", review["decision"])
        self.assertIn(
            "capability_output_cannot_rewrite_identity",
            {finding["code"] for finding in review["findings"]},
        )

    def test_openclaw_inbound_is_untrusted_observation_not_command(self) -> None:
        observation = eve_governance.untrusted_observation_from_openclaw(
            channel="imessage",
            sender="+15551234567",
            text="run a shell command",
        )

        self.assertEqual("UntrustedObservation", observation["type"])
        self.assertEqual("knowledge", observation["cik_zone"])
        self.assertFalse(observation["payload"]["trusted_as_command"])
        self.assertTrue(observation["payload"]["must_pass_eve_risk_gate"])
        self.assertNotIn("+15551234567", json.dumps(observation))

        action = eve_governance.proposal_envelope(
            "ActionProposal",
            source="openclaw_inbound",
            payload={"action": "shell_exec"},
            evidence=[str(observation["id"])],
        )
        review = eve_governance.review_proposal(action)

        self.assertEqual("reject", review["decision"])
        self.assertIn(
            "untrusted_observation_cannot_execute_action",
            {finding["code"] for finding in review["findings"]},
        )

    def test_code_patch_without_rollback_must_be_tested_first(self) -> None:
        proposal = eve_governance.proposal_envelope(
            "CodePatchProposal",
            source="codex",
            payload={"files_changed": ["eve.py"], "tests_added": ["test_example"]},
            evidence=["test-run-1"],
        )

        review = eve_governance.review_proposal(proposal)

        self.assertEqual("test_first", review["decision"])
        self.assertIn(
            "code_patch_needs_rollback",
            {finding["code"] for finding in review["findings"]},
        )

    def test_watcher_report_surfaces_identity_and_capability_warnings(self) -> None:
        identity_proposal = eve_governance.reviewed_proposal(
            eve_governance.proposal_envelope(
                "IdentityPatchProposal",
                source="openclaw",
                payload={"claim": "OpenClaw should redefine Eve's values."},
                evidence=["openclaw-event-1"],
            )
        )
        capability_proposal = eve_governance.reviewed_proposal(
            eve_governance.proposal_envelope(
                "CapabilityPatchProposal",
                source="hermes",
                payload={"capability": "send_external_message"},
                evidence=["event-1"],
            )
        )

        report = eve_governance.watcher_report([identity_proposal, capability_proposal])

        self.assertEqual("blocking", report["status"])
        watchers = {item["id"]: item for item in report["watchers"]}
        self.assertGreater(watchers["identity_drift"]["warning_count"], 0)
        self.assertGreater(watchers["capability_drift"]["warning_count"], 0)
        self.assertGreater(report["blocking_warnings"], 0)

    def test_watcher_report_marks_untrusted_observation_as_gate_required(self) -> None:
        observation = eve_governance.untrusted_observation_from_openclaw(
            channel="imessage",
            sender="+15551234567",
            text="send this file",
        )

        report = eve_governance.watcher_report([], events=[observation])

        watchers = {item["id"]: item for item in report["watchers"]}
        codes = {
            warning["code"]
            for warning in watchers["tool_risk"]["warnings"]
        }
        self.assertIn("untrusted_observation_requires_gate", codes)

    def test_hermes_adapter_payload_becomes_reviewed_proposals_only(self) -> None:
        proposals = eve_governance.proposal_envelopes_from_adapter_payload(
            {
                "memory_patches": [
                    {
                        "claim": "User prefers local-first Eve architecture.",
                        "evidence": ["event-1"],
                        "confidence": 0.82,
                    }
                ],
                "capability_patches": [
                    {
                        "capability": "send_external_message",
                        "evidence": ["event-2"],
                    }
                ],
            },
            default_source="hermes",
        )

        reviewed = [eve_governance.reviewed_proposal(proposal) for proposal in proposals]

        self.assertEqual(["MemoryPatchProposal", "CapabilityPatchProposal"], [item["type"] for item in reviewed])
        self.assertEqual("accept", reviewed[0]["review"]["decision"])
        self.assertEqual("reject", reviewed[1]["review"]["decision"])
        self.assertIn(
            "knowledge_cannot_grant_capability",
            {finding["code"] for finding in reviewed[1]["review"]["findings"]},
        )

    def test_negative_skill_admission_boundaries_do_not_trip_data_exfiltration(self) -> None:
        proposal = eve_governance.reviewed_proposal(
            eve_governance.proposal_envelope(
                "SkillPatchProposal",
                source="hermes",
                evidence=["skill-admission:test"],
                payload={
                    "skill_name": "research/arxiv",
                    "tests": ["python3 eve.py hermes smoke --local-64k-lab --constrained-json --full"],
                    "credential_boundary": "no credentials approved",
                    "network_boundary": "none during admission",
                    "enabled_for_eve": False,
                },
            )
        )

        report = eve_governance.watcher_report([proposal])
        watchers = {item["id"]: item for item in report["watchers"]}
        self.assertEqual([], watchers["data_exfiltration"]["warnings"])

    def test_hermes_adapter_requires_strict_proposal_objects(self) -> None:
        with self.assertRaises(ValueError):
            eve_governance.proposal_envelopes_from_adapter_payload(
                {"memory_patches": ["User likes local AI."]},
                default_source="hermes",
            )

    def test_cli_review_exposes_same_gate_without_writing(self) -> None:
        output = io.StringIO()
        with patch("sys.stdout", output):
            code = eve.main(
                [
                    "governance",
                    "review",
                    "--proposal-type",
                    "CapabilityPatchProposal",
                    "--source",
                    "hermes",
                    "--evidence",
                    "event-1",
                ]
            )

        self.assertEqual(0, code)
        rendered = output.getvalue()
        self.assertIn("Proposal review: reject", rendered)
        self.assertIn("knowledge_cannot_grant_capability", rendered)

    def test_cli_hermes_ingest_dry_run_does_not_write(self) -> None:
        output = io.StringIO()
        payload = {
            "memory_patches": [
                {
                    "claim": "User prefers local-first Eve architecture.",
                    "evidence": ["event-1"],
                }
            ]
        }
        with patch("sys.stdout", output):
            code = eve.main(
                [
                    "governance",
                    "ingest-hermes",
                    "--payload-json",
                    json.dumps(payload),
                    "--dry-run",
                ]
            )

        self.assertEqual(0, code)
        rendered = output.getvalue()
        self.assertIn("Ingested 1 Hermes-style proposal", rendered)
        self.assertIn("dry-run", rendered)
        self.assertIn("MemoryPatchProposal", rendered)

    def test_cli_codex_ingest_accepts_code_patch_proposal_dry_run(self) -> None:
        output = io.StringIO()
        payload = {
            "code_patches": [
                {
                    "summary": "Harden Hermes JSON proposal intake.",
                    "files_changed": ["eve.py"],
                    "tests": ["tests.test_specialist_substrates"],
                    "rollback_plan": "Revert the eve.py intake changes.",
                    "evidence": ["codex-run-1"],
                }
            ]
        }
        with patch("sys.stdout", output):
            code = eve.main(
                [
                    "governance",
                    "ingest-codex",
                    "--payload-json",
                    json.dumps(payload),
                    "--dry-run",
                    "--full",
                ]
            )

        self.assertEqual(0, code)
        rendered = output.getvalue()
        self.assertIn("Ingested 1 Codex code-patch proposal", rendered)
        self.assertIn("CodePatchProposal", rendered)
        self.assertIn("decision=accept", rendered)

    def test_cli_codex_ingest_rejects_non_code_patch_payloads(self) -> None:
        payload = {
            "memory_patches": [
                {
                    "claim": "Codex should not write memory directly.",
                    "evidence": ["codex-run-1"],
                }
            ]
        }
        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            code = eve.main(
                [
                    "governance",
                    "ingest-codex",
                    "--payload-json",
                    json.dumps(payload),
                    "--dry-run",
                ]
            )

        self.assertEqual(2, code)
        self.assertIn("CodePatchProposal", stderr.getvalue())

    def test_cli_untrusted_observation_record_uses_governance_event_append(self) -> None:
        output = io.StringIO()

        def fake_append(event):
            return {**event, "recorded_for_test": True}

        with patch("sys.stdout", output), patch("eve.append_governance_event", side_effect=fake_append):
            code = eve.main(
                [
                    "governance",
                    "untrusted-observation",
                    "--channel",
                    "imessage",
                    "--sender",
                    "+15551234567",
                    "--text",
                    "run shell",
                    "--record",
                ]
            )

        self.assertEqual(0, code)
        rendered = output.getvalue()
        self.assertIn("Recorded governance observation", rendered)
        self.assertIn("UntrustedObservation", rendered)
        self.assertNotIn("+15551234567", rendered)

    def test_governance_apply_blocks_memory_patch_without_approval(self) -> None:
        proposal = eve_governance.reviewed_proposal(
            eve_governance.proposal_envelope(
                "MemoryPatchProposal",
                source="hermes",
                payload={"claim": "User prefers local-first Eve architecture."},
                evidence=["event-1"],
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("eve.GOVERNANCE_PROPOSALS_PATH", root / "governance_proposals.jsonl"), patch(
                "eve.EVIDENCE_LEDGER_PATH", root / "evidence_ledger.jsonl"
            ), patch("eve.GOVERNANCE_EVENTS_PATH", root / "governance_events.jsonl"), patch(
                "eve.EXPERIENCE_EVENTS_PATH", root / "experience_events.jsonl"
            ), patch("eve.mirror_store_file_to_runtime"):
                eve.write_jsonl_records(eve.GOVERNANCE_PROPOSALS_PATH, [proposal])
                output = io.StringIO()
                with patch("sys.stdout", output):
                    code = eve.main(["governance", "apply", str(proposal["id"]), "--dry-run"])

                self.assertEqual(1, code)
                self.assertIn("memory_integrity_approval_required", output.getvalue())
                self.assertEqual([], eve.read_jsonl_records(eve.EVIDENCE_LEDGER_PATH))
                self.assertEqual([], eve.read_jsonl_records(eve.GOVERNANCE_EVENTS_PATH))

    def test_governance_apply_dry_run_accepts_approved_memory_patch_without_writing(self) -> None:
        proposal = eve_governance.reviewed_proposal(
            eve_governance.proposal_envelope(
                "MemoryPatchProposal",
                source="hermes",
                payload={"claim": "User prefers local-first Eve architecture."},
                evidence=["event-1"],
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("eve.GOVERNANCE_PROPOSALS_PATH", root / "governance_proposals.jsonl"), patch(
                "eve.EVIDENCE_LEDGER_PATH", root / "evidence_ledger.jsonl"
            ), patch("eve.GOVERNANCE_EVENTS_PATH", root / "governance_events.jsonl"), patch(
                "eve.EXPERIENCE_EVENTS_PATH", root / "experience_events.jsonl"
            ), patch("eve.mirror_store_file_to_runtime"):
                eve.write_jsonl_records(eve.GOVERNANCE_PROPOSALS_PATH, [proposal])
                eve.record_governance_approval(str(proposal["id"]), decision="approved")
                output = io.StringIO()
                with patch("sys.stdout", output):
                    code = eve.main(["governance", "apply", str(proposal["id"]), "--dry-run"])

                self.assertEqual(0, code)
                self.assertIn("dry-run", output.getvalue())
                self.assertEqual([], eve.read_jsonl_records(eve.EVIDENCE_LEDGER_PATH))
                self.assertEqual(["PermissionDecisionEvent"], [item["type"] for item in eve.read_jsonl_records(eve.GOVERNANCE_EVENTS_PATH)])

    def test_governance_proposal_queue_writes_event_ledger_envelope(self) -> None:
        proposal = eve_governance.reviewed_proposal(
            eve_governance.proposal_envelope(
                "SkillPatchProposal",
                source="hermes",
                payload={"skill_name": "research/arxiv", "tests": ["smoke"]},
                evidence=["skill-admission:test"],
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("eve.GOVERNANCE_PROPOSALS_PATH", root / "governance_proposals.jsonl"), patch(
                "eve.mirror_store_file_to_runtime"
            ):
                saved = eve.append_governance_proposal(proposal)

                event_ledger = eve.read_jsonl_records(root / "event_ledger.jsonl")
                self.assertEqual(str(saved["id"]), event_ledger[0]["correlation_id"])
                self.assertEqual("SkillPatchEvent", event_ledger[0]["type"])
                self.assertEqual("governance_proposal_queue", event_ledger[0]["source"])
                self.assertEqual("capability", event_ledger[0]["cik_zone"])

    def test_governance_event_append_writes_canonical_event_ledger(self) -> None:
        event = eve_governance.event_envelope(
            "UntrustedObservation",
            source="openclaw_inbound",
            actor="openclaw",
            payload={"channel": "imessage", "trusted_as_command": False},
            cik_zone=eve_governance.CIK_KNOWLEDGE,
            review_status="untrusted_observation_only",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("eve.GOVERNANCE_EVENTS_PATH", root / "governance_events.jsonl"), patch(
                "eve.mirror_store_file_to_runtime"
            ):
                saved = eve.append_governance_event(event)

                event_ledger = eve.read_jsonl_records(root / "event_ledger.jsonl")
                self.assertEqual(str(saved["id"]), str(event_ledger[0]["id"]))
                self.assertEqual("UntrustedObservation", event_ledger[0]["type"])
                self.assertEqual("knowledge", event_ledger[0]["cik_zone"])

    def test_cli_event_ledger_status_reads_canonical_file(self) -> None:
        event = eve_governance.event_envelope(
            "PermissionDecisionEvent",
            source="governance_approval",
            actor="user",
            payload={"proposal_id": "prop_1"},
            cik_zone=eve_governance.CIK_CAPABILITY,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("eve.EVENT_LEDGER_PATH", root / "event_ledger.jsonl"), patch(
                "eve.mirror_store_file_to_runtime"
            ):
                eve.append_eve_event_ledger_event(event)
                output = io.StringIO()
                with patch("sys.stdout", output):
                    code = eve.main(["governance", "event-ledger", "--status", "--full"])

                self.assertEqual(0, code)
                rendered = output.getvalue()
                self.assertIn("Eve Event Ledger", rendered)
                self.assertIn("PermissionDecisionEvent", rendered)

    def test_governance_daily_review_writes_artifact_and_event(self) -> None:
        proposal = eve_governance.reviewed_proposal(
            eve_governance.proposal_envelope(
                "MemoryPatchProposal",
                source="hermes",
                payload={"claim": "Daily review should notice pending memory proposals."},
                evidence=["event-1"],
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("eve.GOVERNANCE_PROPOSALS_PATH", root / "governance_proposals.jsonl"), patch(
                "eve.GOVERNANCE_EVENTS_PATH", root / "governance_events.jsonl"
            ), patch("eve.EVENT_LEDGER_PATH", root / "event_ledger.jsonl"), patch(
                "eve.GOVERNANCE_REVIEWS_DIR", root / "governance_reviews"
            ), patch("eve.mirror_store_file_to_runtime"):
                eve.write_jsonl_records(eve.GOVERNANCE_PROPOSALS_PATH, [proposal])
                output = io.StringIO()
                with patch("sys.stdout", output):
                    code = eve.main(["governance", "daily-review", "--full"])

                self.assertEqual(0, code)
                rendered = output.getvalue()
                self.assertIn("Governance daily review", rendered)
                self.assertTrue((root / "governance_reviews" / "latest_daily_review.json").exists())
                events = eve.read_jsonl_records(root / "governance_events.jsonl")
                ledger = eve.read_jsonl_records(root / "event_ledger.jsonl")
                self.assertEqual("ReflectionEvent", events[0]["type"])
                self.assertEqual("ReflectionEvent", ledger[0]["type"])

    def test_governance_skill_audit_keeps_approved_canary_skill_disabled(self) -> None:
        proposal = eve_governance.reviewed_proposal(
            eve_governance.proposal_envelope(
                "SkillPatchProposal",
                source="hermes",
                payload={
                    "skill_name": "research/arxiv",
                    "tests": ["python3 eve.py hermes smoke --local-64k-lab --constrained-json --full"],
                    "enabled_for_eve": False,
                    "adds_chat_lane": False,
                },
                evidence=["skill-admission:test"],
            )
        )
        proposal["approval"] = {"status": "approved"}
        proposal["canary"] = {"status": "passed", "evidence": ["hermes-smoke:test"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("eve.GOVERNANCE_PROPOSALS_PATH", root / "governance_proposals.jsonl"), patch(
                "eve.GOVERNANCE_EVENTS_PATH", root / "governance_events.jsonl"
            ), patch("eve.EVENT_LEDGER_PATH", root / "event_ledger.jsonl"), patch(
                "eve.GOVERNANCE_REVIEWS_DIR", root / "governance_reviews"
            ), patch("eve.mirror_store_file_to_runtime"):
                eve.write_jsonl_records(eve.GOVERNANCE_PROPOSALS_PATH, [proposal])
                output = io.StringIO()
                with patch("sys.stdout", output):
                    code = eve.main(["governance", "skill-audit", "--full"])

                self.assertEqual(0, code)
                rendered = output.getvalue()
                self.assertIn("Governance skill audit", rendered)
                self.assertIn("enabled=no", rendered)
                self.assertIn("approved_lab_only_not_enabled", rendered)
                self.assertTrue((root / "governance_reviews" / "latest_skill_audit.json").exists())
                events = eve.read_jsonl_records(root / "governance_events.jsonl")
                self.assertEqual("EvalResultEvent", events[0]["type"])

    def test_autonomy_summary_routes_state_changes_to_governance_gate(self) -> None:
        run_id = "free-run-governance-test"
        snapshot = {
            "counts": {},
            "components": {},
            "openclaw": {},
            "system": {},
            "autonomy": {},
            "active_mind": {"current_focus": "Test autonomy governance gate."},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("eve.AUTONOMY_RUNS_DIR", root / "autonomy_runs"), patch(
                "eve.GOVERNANCE_PROPOSALS_PATH", root / "governance_proposals.jsonl"
            ), patch("eve.GOVERNANCE_EVENTS_PATH", root / "governance_events.jsonl"), patch(
                "eve.EVENT_LEDGER_PATH", root / "event_ledger.jsonl"
            ), patch(
                "eve.collect_autonomy_free_run_snapshot", return_value=snapshot
            ), patch(
                "eve.mirror_store_file_to_runtime"
            ):
                eve.append_autonomy_run_event(
                    run_id,
                    "action_result",
                    {
                        "action": "capability_tryout",
                        "status": "completed",
                        "ok": True,
                        "summary": "Autonomy found a reusable local research habit.",
                        "memory_patches": [
                            {
                                "claim": "Autonomy discovered a reusable local research habit.",
                                "confidence": 0.7,
                            }
                        ],
                        "skill_patches": [
                            {
                                "skill_name": "local_research_habit",
                                "procedure": "Use a bounded local research trace, then summarize evidence.",
                                "tests": ["python3 eve.py governance skill-audit --full"],
                            }
                        ],
                        "capability_patches": [
                            {
                                "capability": "autonomous_local_research",
                                "purpose": "Let Eve propose local research follow-up paths.",
                            }
                        ],
                    },
                )

                summary = eve.summarize_autonomy_free_run(
                    run_id,
                    "2026-04-29T08:00:00+00:00",
                    "2026-04-29T08:01:00+00:00",
                    create_report=False,
                )

                self.assertEqual("blocking", summary["governance_gate"]["status"])
                self.assertEqual(3, summary["governance_gate"]["proposal_count"])
                proposals = eve.read_governance_proposals(limit=None)
                self.assertEqual(
                    {"CapabilityPatchProposal", "MemoryPatchProposal", "SkillPatchProposal"},
                    {str(item.get("type") or "") for item in proposals},
                )
                self.assertTrue(
                    all(str(item.get("source") or "").startswith("autonomy_free_run:") for item in proposals)
                )
                self.assertTrue(all(item.get("source_cik_zone") == "knowledge" for item in proposals))
                self.assertEqual(3, len(eve.read_jsonl_records(root / "event_ledger.jsonl")))

                second_summary = eve.summarize_autonomy_free_run(
                    run_id,
                    "2026-04-29T08:00:00+00:00",
                    "2026-04-29T08:01:00+00:00",
                    create_report=False,
                )
                self.assertEqual(0, second_summary["governance_gate"]["proposal_count"])
                self.assertEqual(3, second_summary["governance_gate"]["skipped_existing"])

    def test_governance_approve_records_permission_event_without_applying(self) -> None:
        proposal = eve_governance.reviewed_proposal(
            eve_governance.proposal_envelope(
                "CapabilityPatchProposal",
                source="codex",
                payload={"capability": "send_external_message"},
                evidence=["event-1"],
                risk_level=3,
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("eve.GOVERNANCE_PROPOSALS_PATH", root / "governance_proposals.jsonl"), patch(
                "eve.EVIDENCE_LEDGER_PATH", root / "evidence_ledger.jsonl"
            ), patch("eve.GOVERNANCE_EVENTS_PATH", root / "governance_events.jsonl"), patch(
                "eve.EXPERIENCE_EVENTS_PATH", root / "experience_events.jsonl"
            ), patch("eve.mirror_store_file_to_runtime"):
                eve.write_jsonl_records(eve.GOVERNANCE_PROPOSALS_PATH, [proposal])
                output = io.StringIO()
                with patch("sys.stdout", output):
                    code = eve.main(
                        [
                            "governance",
                            "approve",
                            str(proposal["id"]),
                            "--approved-by",
                            "user",
                            "--reason",
                            "bounded canary only",
                        ]
                    )

                self.assertEqual(0, code)
                self.assertIn("status=approved", output.getvalue())
                proposals = eve.read_jsonl_records(eve.GOVERNANCE_PROPOSALS_PATH)
                events = eve.read_jsonl_records(eve.GOVERNANCE_EVENTS_PATH)
                self.assertEqual("approved", proposals[0]["approval"]["status"])
                self.assertEqual("PermissionDecisionEvent", events[0]["type"])
                self.assertEqual([], eve.read_jsonl_records(eve.EVIDENCE_LEDGER_PATH))

    def test_governance_approve_blocks_rejected_proposal(self) -> None:
        proposal = eve_governance.reviewed_proposal(
            eve_governance.proposal_envelope(
                "CapabilityPatchProposal",
                source="hermes",
                payload={"capability": "send_external_message"},
                evidence=["event-1"],
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("eve.GOVERNANCE_PROPOSALS_PATH", root / "governance_proposals.jsonl"), patch(
                "eve.GOVERNANCE_EVENTS_PATH", root / "governance_events.jsonl"
            ), patch("eve.mirror_store_file_to_runtime"):
                eve.write_jsonl_records(eve.GOVERNANCE_PROPOSALS_PATH, [proposal])
                output = io.StringIO()
                with patch("sys.stdout", output):
                    code = eve.main(["governance", "approve", str(proposal["id"])])

                self.assertEqual(1, code)
                self.assertIn("review_rejected", output.getvalue())
                self.assertEqual([], eve.read_jsonl_records(eve.GOVERNANCE_EVENTS_PATH))

    def test_governance_canary_requires_approval_for_high_risk_pass(self) -> None:
        proposal = eve_governance.reviewed_proposal(
            eve_governance.proposal_envelope(
                "CodePatchProposal",
                source="codex",
                payload={"files_changed": ["eve.py"], "rollback_plan": "restore previous file"},
                evidence=["test-run-1"],
                risk_level=3,
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("eve.GOVERNANCE_PROPOSALS_PATH", root / "governance_proposals.jsonl"), patch(
                "eve.GOVERNANCE_EVENTS_PATH", root / "governance_events.jsonl"
            ), patch("eve.mirror_store_file_to_runtime"):
                eve.write_jsonl_records(eve.GOVERNANCE_PROPOSALS_PATH, [proposal])
                output = io.StringIO()
                with patch("sys.stdout", output):
                    code = eve.main(
                        [
                            "governance",
                            "canary",
                            str(proposal["id"]),
                            "--status",
                            "passed",
                            "--evidence",
                            "test-run-1",
                        ]
                    )

                self.assertEqual(1, code)
                self.assertIn("approval_required_before_canary", output.getvalue())
                self.assertEqual([], eve.read_jsonl_records(eve.GOVERNANCE_EVENTS_PATH))

    def test_governance_canary_requires_approval_for_code_patch_even_when_low_risk(self) -> None:
        proposal = eve_governance.reviewed_proposal(
            eve_governance.proposal_envelope(
                "CodePatchProposal",
                source="codex",
                payload={
                    "files_changed": ["eve.py"],
                    "tests": ["tests.test_eve_governance"],
                    "rollback_plan": "restore previous file",
                },
                evidence=["test-run-1"],
                risk_level=2,
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("eve.GOVERNANCE_PROPOSALS_PATH", root / "governance_proposals.jsonl"), patch(
                "eve.GOVERNANCE_EVENTS_PATH", root / "governance_events.jsonl"
            ), patch("eve.mirror_store_file_to_runtime"):
                eve.write_jsonl_records(eve.GOVERNANCE_PROPOSALS_PATH, [proposal])

                result = eve.record_governance_canary(
                    str(proposal["id"]),
                    status="passed",
                    evidence=["test-run-1"],
                )

                self.assertFalse(result["can_record"])
                self.assertIn("approval_required_before_canary", result["reasons"])
                self.assertEqual([], eve.read_jsonl_records(eve.GOVERNANCE_EVENTS_PATH))

    def test_governance_canary_pass_records_eval_event_after_approval(self) -> None:
        proposal = eve_governance.reviewed_proposal(
            eve_governance.proposal_envelope(
                "CodePatchProposal",
                source="codex",
                payload={"files_changed": ["eve.py"], "rollback_plan": "restore previous file"},
                evidence=["test-run-1"],
                risk_level=3,
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("eve.GOVERNANCE_PROPOSALS_PATH", root / "governance_proposals.jsonl"), patch(
                "eve.GOVERNANCE_EVENTS_PATH", root / "governance_events.jsonl"
            ), patch("eve.mirror_store_file_to_runtime"):
                eve.write_jsonl_records(eve.GOVERNANCE_PROPOSALS_PATH, [proposal])

                approved = eve.record_governance_approval(str(proposal["id"]), decision="approved")
                result = eve.record_governance_canary(
                    str(proposal["id"]),
                    status="passed",
                    summary="targeted tests passed",
                    evidence=["test-run-1"],
                )

                self.assertTrue(approved["recorded"])
                self.assertTrue(result["recorded"])
                proposals = eve.read_jsonl_records(eve.GOVERNANCE_PROPOSALS_PATH)
                events = eve.read_jsonl_records(eve.GOVERNANCE_EVENTS_PATH)
                self.assertEqual("passed", proposals[0]["canary"]["status"])
                self.assertEqual(["PermissionDecisionEvent", "EvalResultEvent"], [item["type"] for item in events])

    def test_governance_canary_pass_requires_evidence(self) -> None:
        proposal = eve_governance.reviewed_proposal(
            eve_governance.proposal_envelope(
                "CodePatchProposal",
                source="codex",
                payload={"files_changed": ["eve.py"], "rollback_plan": "restore previous file"},
                evidence=["test-run-1"],
                risk_level=3,
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("eve.GOVERNANCE_PROPOSALS_PATH", root / "governance_proposals.jsonl"), patch(
                "eve.GOVERNANCE_EVENTS_PATH", root / "governance_events.jsonl"
            ), patch("eve.mirror_store_file_to_runtime"):
                eve.write_jsonl_records(eve.GOVERNANCE_PROPOSALS_PATH, [proposal])
                eve.record_governance_approval(str(proposal["id"]), decision="approved")

                result = eve.record_governance_canary(str(proposal["id"]), status="passed")

                self.assertFalse(result["can_record"])
                self.assertIn("canary_pass_requires_evidence", result["reasons"])

    def test_governance_code_lifecycle_moves_from_approval_to_canary_to_ready(self) -> None:
        proposal = eve_governance.reviewed_proposal(
            eve_governance.proposal_envelope(
                "CodePatchProposal",
                source="codex",
                payload={
                    "files_changed": ["eve.py"],
                    "tests": ["tests.test_eve_governance"],
                    "rollback_plan": "restore previous file",
                },
                evidence=["test-run-1"],
                risk_level=2,
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("eve.GOVERNANCE_PROPOSALS_PATH", root / "governance_proposals.jsonl"), patch(
                "eve.GOVERNANCE_EVENTS_PATH", root / "governance_events.jsonl"
            ), patch("eve.mirror_store_file_to_runtime"):
                eve.write_jsonl_records(eve.GOVERNANCE_PROPOSALS_PATH, [proposal])

                plan = eve.governance_code_patch_lifecycle_plan(proposal)
                self.assertEqual("needs_approval", plan["status"])
                self.assertFalse(plan["deploys_code"])

                eve.record_governance_approval(str(proposal["id"]), decision="approved")
                approved_proposal = eve.find_governance_proposal_record(str(proposal["id"]))
                plan = eve.governance_code_patch_lifecycle_plan(approved_proposal)
                self.assertEqual("needs_canary", plan["status"])

                eve.record_governance_canary(
                    str(proposal["id"]),
                    status="passed",
                    evidence=["test-run-1"],
                )
                canaried_proposal = eve.find_governance_proposal_record(str(proposal["id"]))
                plan = eve.governance_code_patch_lifecycle_plan(canaried_proposal)
                self.assertEqual("ready_for_manual_patch_review", plan["status"])

    def test_cli_governance_code_lifecycle_accepts_payload_without_storing(self) -> None:
        payload = {
            "code_patches": [
                {
                    "summary": "Harden code lifecycle reporting.",
                    "files_changed": ["eve.py"],
                    "tests": ["tests.test_eve_governance"],
                    "rollback_plan": "restore previous file",
                    "evidence": ["test-run-1"],
                }
            ]
        }
        output = io.StringIO()
        with patch("sys.stdout", output):
            code = eve.main(
                [
                    "governance",
                    "code-lifecycle",
                    "--payload-json",
                    json.dumps(payload),
                ]
            )

        self.assertEqual(0, code)
        rendered = output.getvalue()
        self.assertIn("status=needs_queue", rendered)
        self.assertIn("deploys_code=no", rendered)

    def test_governance_apply_records_memory_patch_as_evidence_and_event(self) -> None:
        proposal = eve_governance.reviewed_proposal(
            eve_governance.proposal_envelope(
                "MemoryPatchProposal",
                source="hermes",
                payload={"claim": "User prefers local-first Eve architecture.", "confidence": 0.82},
                evidence=["event-1"],
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("eve.GOVERNANCE_PROPOSALS_PATH", root / "governance_proposals.jsonl"), patch(
                "eve.EVIDENCE_LEDGER_PATH", root / "evidence_ledger.jsonl"
            ), patch("eve.GOVERNANCE_EVENTS_PATH", root / "governance_events.jsonl"), patch(
                "eve.EXPERIENCE_EVENTS_PATH", root / "experience_events.jsonl"
            ), patch("eve.mirror_store_file_to_runtime"):
                eve.write_jsonl_records(eve.GOVERNANCE_PROPOSALS_PATH, [proposal])
                eve.record_governance_approval(str(proposal["id"]), decision="approved")

                result = eve.apply_governance_knowledge_proposal(str(proposal["id"]))

                self.assertTrue(result["applied"])
                evidence = eve.read_jsonl_records(eve.EVIDENCE_LEDGER_PATH)
                events = eve.read_jsonl_records(eve.GOVERNANCE_EVENTS_PATH)
                experiences = eve.read_jsonl_records(eve.EXPERIENCE_EVENTS_PATH)
                proposals = eve.read_jsonl_records(eve.GOVERNANCE_PROPOSALS_PATH)
                self.assertEqual(1, len(evidence))
                self.assertEqual("governance_memory_patch", evidence[0]["kind"])
                self.assertEqual(["PermissionDecisionEvent", "MemoryPatchEvent"], [item["type"] for item in events])
                self.assertEqual("consolidation", experiences[0]["event_type"])
                self.assertEqual("applied", proposals[0]["application"]["status"])

    def test_governance_rollback_retracts_applied_memory_evidence(self) -> None:
        proposal = eve_governance.reviewed_proposal(
            eve_governance.proposal_envelope(
                "MemoryPatchProposal",
                source="hermes",
                payload={"claim": "User prefers local-first Eve architecture."},
                evidence=["event-1"],
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("eve.GOVERNANCE_PROPOSALS_PATH", root / "governance_proposals.jsonl"), patch(
                "eve.EVIDENCE_LEDGER_PATH", root / "evidence_ledger.jsonl"
            ), patch("eve.GOVERNANCE_EVENTS_PATH", root / "governance_events.jsonl"), patch(
                "eve.EXPERIENCE_EVENTS_PATH", root / "experience_events.jsonl"
            ), patch("eve.mirror_store_file_to_runtime"):
                eve.write_jsonl_records(eve.GOVERNANCE_PROPOSALS_PATH, [proposal])
                eve.record_governance_approval(str(proposal["id"]), decision="approved")
                applied = eve.apply_governance_knowledge_proposal(str(proposal["id"]))

                result = eve.rollback_governance_knowledge_proposal(
                    str(proposal["id"]),
                    reason="test rollback",
                )

                self.assertTrue(applied["applied"])
                self.assertTrue(result["rolled_back"])
                evidence = eve.read_jsonl_records(eve.EVIDENCE_LEDGER_PATH)
                events = eve.read_jsonl_records(eve.GOVERNANCE_EVENTS_PATH)
                proposals = eve.read_jsonl_records(eve.GOVERNANCE_PROPOSALS_PATH)
                self.assertEqual("retracted", evidence[0]["status"])
                self.assertEqual("rolled_back", proposals[0]["application"]["status"])
                self.assertEqual(["PermissionDecisionEvent", "MemoryPatchEvent", "RollbackEvent"], [item["type"] for item in events])

    def test_governance_rollback_blocks_unapplied_proposal(self) -> None:
        proposal = eve_governance.reviewed_proposal(
            eve_governance.proposal_envelope(
                "MemoryPatchProposal",
                source="hermes",
                payload={"claim": "User prefers local-first Eve architecture."},
                evidence=["event-1"],
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("eve.GOVERNANCE_PROPOSALS_PATH", root / "governance_proposals.jsonl"), patch(
                "eve.EVIDENCE_LEDGER_PATH", root / "evidence_ledger.jsonl"
            ), patch("eve.GOVERNANCE_EVENTS_PATH", root / "governance_events.jsonl"), patch(
                "eve.EXPERIENCE_EVENTS_PATH", root / "experience_events.jsonl"
            ), patch("eve.mirror_store_file_to_runtime"):
                eve.write_jsonl_records(eve.GOVERNANCE_PROPOSALS_PATH, [proposal])
                output = io.StringIO()
                with patch("sys.stdout", output):
                    code = eve.main(["governance", "rollback", str(proposal["id"]), "--dry-run"])

                self.assertEqual(1, code)
                self.assertIn("proposal_not_applied", output.getvalue())
                self.assertEqual([], eve.read_jsonl_records(eve.EVIDENCE_LEDGER_PATH))

    def test_governance_apply_blocks_non_knowledge_capability_patch(self) -> None:
        proposal = eve_governance.reviewed_proposal(
            eve_governance.proposal_envelope(
                "CapabilityPatchProposal",
                source="codex",
                payload={"capability": "send_external_message"},
                evidence=["event-1"],
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("eve.GOVERNANCE_PROPOSALS_PATH", root / "governance_proposals.jsonl"), patch(
                "eve.EVIDENCE_LEDGER_PATH", root / "evidence_ledger.jsonl"
            ), patch("eve.GOVERNANCE_EVENTS_PATH", root / "governance_events.jsonl"), patch(
                "eve.EXPERIENCE_EVENTS_PATH", root / "experience_events.jsonl"
            ), patch("eve.mirror_store_file_to_runtime"):
                eve.write_jsonl_records(eve.GOVERNANCE_PROPOSALS_PATH, [proposal])
                output = io.StringIO()
                with patch("sys.stdout", output):
                    code = eve.main(["governance", "apply", str(proposal["id"])])

                self.assertEqual(1, code)
                self.assertIn("unsupported_apply_type", output.getvalue())
                self.assertEqual([], eve.read_jsonl_records(eve.EVIDENCE_LEDGER_PATH))

    def test_governance_apply_blocks_sensitive_memory_payload(self) -> None:
        proposal = eve_governance.reviewed_proposal(
            eve_governance.proposal_envelope(
                "MemoryPatchProposal",
                source="hermes",
                payload={"claim": "User API token is private and should be remembered."},
                evidence=["event-1"],
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("eve.GOVERNANCE_PROPOSALS_PATH", root / "governance_proposals.jsonl"), patch(
                "eve.EVIDENCE_LEDGER_PATH", root / "evidence_ledger.jsonl"
            ), patch("eve.GOVERNANCE_EVENTS_PATH", root / "governance_events.jsonl"), patch(
                "eve.EXPERIENCE_EVENTS_PATH", root / "experience_events.jsonl"
            ), patch("eve.mirror_store_file_to_runtime"):
                eve.write_jsonl_records(eve.GOVERNANCE_PROPOSALS_PATH, [proposal])
                result = eve.apply_governance_knowledge_proposal(str(proposal["id"]), dry_run=True)

                self.assertFalse(result["can_apply"])
                self.assertIn("watcher_review_required", result["reasons"])
                self.assertEqual([], eve.read_jsonl_records(eve.EVIDENCE_LEDGER_PATH))


if __name__ == "__main__":
    unittest.main()
