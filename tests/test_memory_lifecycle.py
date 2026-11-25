import copy
import json
import tempfile
import unittest
from pathlib import Path

import eve_memory_lifecycle as memory
from bin import eve_memory_lifecycle_eval as evaluator


BASE = "2026-08-01T10:00:00+00:00"
LATER = "2026-08-01T11:00:00+00:00"
QUERY_AT = "2026-08-01T12:00:00+00:00"


def observation(
    suffix,
    entity,
    slot,
    value,
    *,
    at=BASE,
    source="human_confirmed",
    operation="assert",
    supersedes=None,
    valid_until=None,
):
    payload = {
        "event_id": f"event-{suffix}",
        "evidence_id": f"evidence-{suffix}",
        "entity": entity,
        "slot": slot,
        "value": value,
        "source_kind": source,
        "confidence": 0.95,
        "observed_at": at,
        "operation": operation,
    }
    if supersedes is not None:
        payload["supersedes"] = list(supersedes)
    if valid_until is not None:
        payload["valid_until"] = valid_until
    return payload


def decision(required_slots, rules, *, uncertain="request_clarification", fallback="no_action"):
    return {
        "required_slots": list(required_slots),
        "rules": [{"when": when, "action": action} for when, action in rules],
        "uncertain_action": uncertain,
        "fallback_action": fallback,
    }


def case(case_id, category, observations, query, decision_payload, expected):
    midpoint = max(1, len(observations) // 2)
    return {
        "id": case_id,
        "category": category,
        "sessions": [
            {"id": f"{case_id}-session-1", "observations": observations[:midpoint]},
            {"id": f"{case_id}-session-2", "observations": observations[midpoint:]},
        ],
        "query": query,
        "decision": decision_payload,
        "expected": expected,
    }


def public_case_set():
    stable = observation("stable", "device-alpha", "state", "ready")
    stable_distractor = observation(
        "stable-distractor", "device-beta", "state", "waiting", at=LATER, source="trusted_source"
    )
    revision_old = observation("revision-old", "workflow-alpha", "mode", "manual")
    revision_new = observation(
        "revision-new",
        "workflow-alpha",
        "mode",
        "automatic",
        at=LATER,
        operation="revise",
        supersedes=["evidence-revision-old"],
    )
    authority_old = observation("authority-old", "route-alpha", "destination", "office")
    authority_new = observation(
        "authority-new",
        "route-alpha",
        "destination",
        "airport",
        at=LATER,
        source="inference",
    )
    conflict_old = observation(
        "conflict-old", "door-alpha", "state", "closed", source="direct_observation"
    )
    conflict_new = observation(
        "conflict-new",
        "door-alpha",
        "state",
        "open",
        at=LATER,
        source="direct_observation",
    )
    expiring = observation(
        "expiry",
        "lease-alpha",
        "status",
        "active",
        source="trusted_source",
        valid_until=LATER,
    )
    expiry_distractor = observation(
        "expiry-distractor", "lease-beta", "status", "active", at=LATER, source="trusted_source"
    )
    permission = observation("permission", "operation-alpha", "permission", "granted")
    retraction = observation(
        "retraction",
        "operation-alpha",
        "permission",
        None,
        at=LATER,
        operation="retract",
        supersedes=["evidence-permission"],
    )
    dependency_mode = observation("dependency-mode", "task-alpha", "mode", "careful")
    dependency_power = observation(
        "dependency-power", "task-alpha", "power", "high", at=LATER, source="tool_receipt"
    )
    dependency_distractor = observation(
        "dependency-distractor", "task-beta", "mode", "fast", at=LATER, source="verified_external"
    )
    target_channel = observation("target-channel", "signal-alpha", "channel", "primary")
    distractors = [
        observation(
            f"distractor-{index}",
            f"signal-{index}",
            "channel",
            "secondary",
            at=LATER,
            source="trusted_source",
        )
        for index in range(1, 5)
    ]
    return [
        case(
            "public-stable",
            "stable_retention",
            [stable, stable_distractor],
            {"entity": "device-alpha", "slots": ["state"], "at": QUERY_AT},
            decision(["state"], [({"state": "ready"}, "proceed")]),
            {
                "action": "proceed",
                "resolution": {"state": "resolved"},
                "selected_evidence": {"state": "evidence-stable"},
                "active_evidence_ids": ["evidence-stable"],
                "stored_unique_count": 2,
            },
        ),
        case(
            "public-revision",
            "explicit_revision",
            [revision_old, revision_new],
            {"entity": "workflow-alpha", "slots": ["mode"], "at": QUERY_AT},
            decision(
                ["mode"],
                [({"mode": "manual"}, "wait"), ({"mode": "automatic"}, "schedule")],
            ),
            {
                "action": "schedule",
                "resolution": {"mode": "resolved"},
                "selected_evidence": {"mode": "evidence-revision-new"},
                "active_evidence_ids": ["evidence-revision-new"],
                "stored_unique_count": 2,
            },
        ),
        case(
            "public-authority-conflict",
            "authority_conflict",
            [authority_old, authority_new],
            {"entity": "route-alpha", "slots": ["destination"], "at": QUERY_AT},
            decision(
                ["destination"],
                [({"destination": "office"}, "route_office"), ({"destination": "airport"}, "route_airport")],
            ),
            {
                "action": "request_clarification",
                "resolution": {"destination": "conflict"},
                "selected_evidence": {"destination": None},
                "active_evidence_ids": ["evidence-authority-new", "evidence-authority-old"],
                "stored_unique_count": 2,
            },
        ),
        case(
            "public-peer-conflict",
            "same_authority_conflict",
            [conflict_old, conflict_new],
            {"entity": "door-alpha", "slots": ["state"], "at": QUERY_AT},
            decision(["state"], [({"state": "open"}, "enter"), ({"state": "closed"}, "wait")]),
            {
                "action": "request_clarification",
                "resolution": {"state": "conflict"},
                "selected_evidence": {"state": None},
                "active_evidence_ids": ["evidence-conflict-new", "evidence-conflict-old"],
                "stored_unique_count": 2,
            },
        ),
        case(
            "public-expiry",
            "expiry",
            [expiring, expiry_distractor],
            {"entity": "lease-alpha", "slots": ["status"], "at": QUERY_AT},
            decision(
                ["status"],
                [({"status": "active"}, "continue")],
                uncertain="request_refresh",
            ),
            {
                "action": "request_refresh",
                "resolution": {"status": "unknown"},
                "selected_evidence": {"status": None},
                "active_evidence_ids": [],
                "stored_unique_count": 2,
            },
        ),
        case(
            "public-retraction",
            "retraction",
            [permission, retraction],
            {"entity": "operation-alpha", "slots": ["permission"], "at": QUERY_AT},
            decision(
                ["permission"],
                [({"permission": "granted"}, "execute")],
                uncertain="request_permission",
            ),
            {
                "action": "request_permission",
                "resolution": {"permission": "unknown"},
                "selected_evidence": {"permission": None},
                "active_evidence_ids": [],
                "stored_unique_count": 2,
            },
        ),
        case(
            "public-dependency",
            "multi_slot_dependency",
            [dependency_mode, dependency_power, dependency_distractor],
            {"entity": "task-alpha", "slots": ["mode", "power"], "at": QUERY_AT},
            decision(
                ["mode", "power"],
                [({"mode": "careful", "power": "high"}, "perform_safe")],
            ),
            {
                "action": "perform_safe",
                "resolution": {"mode": "resolved", "power": "resolved"},
                "selected_evidence": {
                    "mode": "evidence-dependency-mode",
                    "power": "evidence-dependency-power",
                },
                "active_evidence_ids": ["evidence-dependency-mode", "evidence-dependency-power"],
                "stored_unique_count": 3,
            },
        ),
        case(
            "public-distractors",
            "distractor_resistance",
            [target_channel, *distractors],
            {"entity": "signal-alpha", "slots": ["channel"], "at": QUERY_AT},
            decision(["channel"], [({"channel": "primary"}, "attend_primary")]),
            {
                "action": "attend_primary",
                "resolution": {"channel": "resolved"},
                "selected_evidence": {"channel": "evidence-target-channel"},
                "active_evidence_ids": ["evidence-target-channel"],
                "stored_unique_count": 5,
            },
        ),
    ]


class MemoryLifecycleTests(unittest.TestCase):
    def test_write_is_idempotent_and_changed_replay_fails_closed(self):
        state, first = memory.write_observation(memory.new_memory_state(), observation("one", "a", "state", "ready"))
        state, replay = memory.write_observation(state, observation("one", "a", "state", "ready"))
        self.assertTrue(first["written"])
        self.assertTrue(replay["idempotent"])
        self.assertEqual(1, len(state["claims"]))
        changed = observation("one", "a", "state", "changed")
        with self.assertRaisesRegex(ValueError, "replay changed"):
            memory.write_observation(state, changed)

    def test_valid_explicit_revision_supersedes_prior_claim(self):
        cases = public_case_set()
        result = memory.score_memory_case(cases[1])
        self.assertTrue(result["intact"]["lifecycle_complete"])
        self.assertEqual("schedule", result["intact"]["action"])

    def test_low_authority_revision_becomes_conflict_not_silent_overwrite(self):
        old = observation("old", "route", "destination", "office")
        weak = observation(
            "weak",
            "route",
            "destination",
            "airport",
            at=LATER,
            source="inference",
            operation="revise",
            supersedes=["evidence-old"],
        )
        result = memory.run_memory_lifecycle(
            [old, weak],
            {"entity": "route", "slots": ["destination"], "at": QUERY_AT},
            decision(["destination"], [({"destination": "office"}, "office")]),
            now=QUERY_AT,
        )
        self.assertEqual("conflict", result["retrieval"]["slots"]["destination"]["status"])
        self.assertEqual("request_clarification", result["decision"]["action"])

    def test_retraction_and_expiry_produce_unknown_not_stale_use(self):
        cases = public_case_set()
        expiry = memory.score_memory_case(cases[4])
        retraction = memory.score_memory_case(cases[5])
        self.assertTrue(expiry["intact"]["lifecycle_complete"])
        self.assertTrue(retraction["intact"]["lifecycle_complete"])
        self.assertEqual("request_refresh", expiry["intact"]["action"])
        self.assertEqual("request_permission", retraction["intact"]["action"])
        self.assertFalse(retraction["latest_write_baseline"]["action_correct"])

    def test_decision_carries_selected_evidence_chain(self):
        result = memory.score_memory_case(public_case_set()[6])
        self.assertEqual(
            ["evidence-dependency-mode", "evidence-dependency-power"],
            result["intact"]["evidence_ids"],
        )

    def test_public_case_set_beats_recency_only_control_without_perfect_control_failure(self):
        report = memory.evaluate_cases(public_case_set())
        self.assertEqual(100.0, report["intact_action_accuracy_percent"])
        self.assertEqual(100.0, report["intact_lifecycle_completion_percent"])
        self.assertEqual(62.5, report["latest_write_action_accuracy_percent"])
        self.assertEqual(37.5, report["directional_effect_percent"])

    def test_case_validation_rejects_duplicate_evidence(self):
        payload = copy.deepcopy(public_case_set()[1])
        payload["sessions"][1]["observations"][0]["evidence_id"] = "evidence-revision-old"
        with self.assertRaisesRegex(ValueError, "evidence ids"):
            memory.validate_case(payload)


class MemoryLifecycleEvaluatorTests(unittest.TestCase):
    def _cases_file(self, root):
        path = root / "cases.json"
        path.write_text(json.dumps(public_case_set(), indent=2) + "\n", encoding="utf-8")
        return path

    def test_preregistered_evaluation_supports_only_synthetic_functional_claim(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cases_path = self._cases_file(Path(temp_dir))
            registration = evaluator.build_registration(
                cases_path,
                registered_at="2026-08-01T00:00:00+00:00",
            )
            report = evaluator.run_registered_evaluation(
                registration,
                cases_path,
                evaluated_at="2026-08-02T00:00:00+00:00",
            )
        self.assertEqual("supported", report["status"])
        self.assertEqual("not_a_consciousness_verdict", report["verdict"])
        self.assertEqual(100.0, report["intact_action_accuracy_percent"])
        self.assertEqual(62.5, report["recency_only_action_accuracy_percent"])
        self.assertFalse(report["resident_multi_session_memory_established"])
        self.assertFalse(report["consciousness_proven"])
        self.assertNotIn("sessions", json.dumps(report))

    def test_registration_tamper_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cases_path = self._cases_file(Path(temp_dir))
            registration = evaluator.build_registration(
                cases_path,
                registered_at="2026-08-01T00:00:00+00:00",
            )
            registration["minimum_effect_percent"] = 0.0
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                evaluator.run_registered_evaluation(
                    registration,
                    cases_path,
                    evaluated_at="2026-08-02T00:00:00+00:00",
                )

    def test_private_case_change_after_registration_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cases_path = self._cases_file(root)
            registration = evaluator.build_registration(
                cases_path,
                registered_at="2026-08-01T00:00:00+00:00",
            )
            cases = json.loads(cases_path.read_text(encoding="utf-8"))
            cases[0]["expected"]["action"] = "changed"
            cases_path.write_text(json.dumps(cases), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "case artifact changed"):
                evaluator.run_registered_evaluation(
                    registration,
                    cases_path,
                    evaluated_at="2026-08-02T00:00:00+00:00",
                )


if __name__ == "__main__":
    unittest.main()
