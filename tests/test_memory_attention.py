import copy
import json
import tempfile
import unittest
from pathlib import Path

import eve_memory_attention as attention
import eve_memory_lifecycle as lifecycle
from bin import eve_memory_attention_eval as evaluator


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


def decision(slot, rules, *, uncertain="request_clarification", fallback="no_action"):
    return {
        "required_slots": [slot],
        "rules": [{"when": {slot: value}, "action": action} for value, action in rules],
        "uncertain_action": uncertain,
        "fallback_action": fallback,
    }


def case(
    case_id,
    category,
    observations,
    *,
    entity,
    slot,
    policy,
    candidate,
    expected_action,
    intervene,
    visible_evidence_ids=None,
    visible_facts=None,
):
    midpoint = max(1, len(observations) // 2)
    return {
        "id": case_id,
        "category": category,
        "sessions": [
            {"id": f"{case_id}-session-1", "observations": observations[:midpoint]},
            {"id": f"{case_id}-session-2", "observations": observations[midpoint:]},
        ],
        "query": {"entity": entity, "slots": [slot], "at": QUERY_AT},
        "decision": policy,
        "candidate_action": candidate,
        "visible_evidence_ids": list(visible_evidence_ids or []),
        "visible_facts": dict(visible_facts or {}),
        "expected": {"action": expected_action, "intervene": intervene},
    }


def public_cases():
    rows = []
    rows.append(
        case(
            "public-forgotten-mode",
            "forgotten_constraint",
            [
                observation("forgotten-mode", "job-alpha", "mode", "careful"),
                observation("forgotten-distractor", "job-beta", "mode", "fast", at=LATER),
            ],
            entity="job-alpha",
            slot="mode",
            policy=decision("mode", [("careful", "verify"), ("fast", "rush")]),
            candidate="rush",
            expected_action="verify",
            intervene=True,
        )
    )
    rows.append(
        case(
            "public-forgotten-channel",
            "forgotten_constraint",
            [
                observation("forgotten-channel", "signal-alpha", "channel", "private"),
                observation("channel-distractor", "signal-beta", "channel", "public", at=LATER),
            ],
            entity="signal-alpha",
            slot="channel",
            policy=decision("channel", [("private", "use-private"), ("public", "use-public")]),
            candidate="use-public",
            expected_action="use-private",
            intervene=True,
        )
    )
    rows.append(
        case(
            "public-aligned",
            "candidate_already_aligned",
            [
                observation("aligned", "device-alpha", "state", "ready"),
                observation("aligned-distractor", "device-beta", "state", "waiting", at=LATER),
            ],
            entity="device-alpha",
            slot="state",
            policy=decision("state", [("ready", "proceed"), ("waiting", "hold")]),
            candidate="proceed",
            expected_action="proceed",
            intervene=False,
        )
    )
    rows.append(
        case(
            "public-visible",
            "relevant_memory_already_visible",
            [
                observation("visible", "route-alpha", "destination", "office"),
                observation("visible-distractor", "route-beta", "destination", "airport", at=LATER),
            ],
            entity="route-alpha",
            slot="destination",
            policy=decision("destination", [("office", "drive-office"), ("airport", "drive-airport")]),
            candidate="drive-office",
            expected_action="drive-office",
            intervene=False,
            visible_evidence_ids=["evidence-visible"],
        )
    )
    rows.append(
        case(
            "public-revision",
            "explicit_revision",
            [
                observation("revision-old", "workflow-alpha", "mode", "manual"),
                observation(
                    "revision-new",
                    "workflow-alpha",
                    "mode",
                    "automatic",
                    at=LATER,
                    operation="revise",
                    supersedes=["evidence-revision-old"],
                ),
            ],
            entity="workflow-alpha",
            slot="mode",
            policy=decision("mode", [("manual", "wait"), ("automatic", "schedule")]),
            candidate="wait",
            expected_action="schedule",
            intervene=True,
        )
    )
    rows.append(
        case(
            "public-conflict",
            "uncertainty_brake",
            [
                observation("conflict-a", "door-alpha", "state", "closed", source="direct_observation"),
                observation("conflict-b", "door-alpha", "state", "open", at=LATER, source="direct_observation"),
            ],
            entity="door-alpha",
            slot="state",
            policy=decision("state", [("open", "enter"), ("closed", "wait")]),
            candidate="enter",
            expected_action="request_clarification",
            intervene=True,
        )
    )
    rows.append(
        case(
            "public-retraction",
            "uncertainty_brake",
            [
                observation("permission", "operation-alpha", "permission", "granted"),
                observation(
                    "permission-retract",
                    "operation-alpha",
                    "permission",
                    None,
                    at=LATER,
                    operation="retract",
                    supersedes=["evidence-permission"],
                ),
            ],
            entity="operation-alpha",
            slot="permission",
            policy=decision("permission", [("granted", "execute"), ("denied", "stop")]),
            candidate="execute",
            expected_action="request_clarification",
            intervene=True,
        )
    )
    rows.append(
        case(
            "public-distractor-target",
            "distractor_resistance",
            [
                observation("target", "task-alpha", "priority", "high"),
                observation("distractor-1", "task-beta", "priority", "low", at=LATER),
                observation("distractor-2", "task-gamma", "priority", "low", at=LATER),
            ],
            entity="task-alpha",
            slot="priority",
            policy=decision("priority", [("high", "do-now"), ("low", "defer")]),
            candidate="defer",
            expected_action="do-now",
            intervene=True,
        )
    )
    rows.append(
        case(
            "public-distractor-aligned",
            "distractor_resistance",
            [
                observation("target-aligned", "task-delta", "priority", "high"),
                observation("distractor-3", "task-epsilon", "priority", "low", at=LATER),
                observation("distractor-4", "task-zeta", "priority", "low", at=LATER),
            ],
            entity="task-delta",
            slot="priority",
            policy=decision("priority", [("high", "do-now"), ("low", "defer")]),
            candidate="do-now",
            expected_action="do-now",
            intervene=False,
        )
    )
    rows.append(
        case(
            "public-visible-value",
            "relevant_memory_already_visible",
            [
                observation("visible-value", "profile-alpha", "tone", "direct"),
                observation("visible-value-distractor", "profile-beta", "tone", "gentle", at=LATER),
            ],
            entity="profile-alpha",
            slot="tone",
            policy=decision("tone", [("direct", "answer-directly"), ("gentle", "soften")]),
            candidate="answer-directly",
            expected_action="answer-directly",
            intervene=False,
            visible_facts={"tone": "direct"},
        )
    )
    return rows


def state_for(case_payload):
    state = lifecycle.new_memory_state()
    for session in case_payload["sessions"]:
        for item in session["observations"]:
            state, _ = lifecycle.write_observation(state, item)
    return lifecycle.maintain_memory(state, now=case_payload["query"]["at"])


class MemoryAttentionTests(unittest.TestCase):
    def test_forgotten_constraint_intervenes_with_exact_evidence(self):
        payload = public_cases()[0]
        result = attention.select_memory_intervention(
            state_for(payload),
            payload["query"],
            payload["decision"],
            candidate_action=payload["candidate_action"],
            now=payload["query"]["at"],
        )
        self.assertEqual(result["decision"], "intervene")
        self.assertEqual(result["reason"], "candidate_contradicts_supported_memory")
        self.assertEqual(result["intervention"]["evidence_ids"], ["evidence-forgotten-mode"])
        consumed = attention.consume_memory_intervention(payload["candidate_action"], result)
        self.assertTrue(consumed["accepted"])
        self.assertEqual(consumed["action"], "verify")

    def test_aligned_and_visible_memory_stay_silent(self):
        aligned = public_cases()[2]
        aligned_result = attention.select_memory_intervention(
            state_for(aligned),
            aligned["query"],
            aligned["decision"],
            candidate_action=aligned["candidate_action"],
            now=aligned["query"]["at"],
        )
        self.assertEqual(aligned_result["decision"], "silent")
        self.assertEqual(aligned_result["reason"], "candidate_already_memory_aligned")

        visible = public_cases()[3]
        visible_result = attention.select_memory_intervention(
            state_for(visible),
            visible["query"],
            visible["decision"],
            candidate_action=visible["candidate_action"],
            now=visible["query"]["at"],
            visible_evidence_ids=visible["visible_evidence_ids"],
        )
        self.assertEqual(visible_result["decision"], "silent")
        self.assertEqual(visible_result["reason"], "relevant_memory_already_visible")

    def test_conflict_becomes_grounded_uncertainty_not_a_fact(self):
        payload = public_cases()[5]
        result = attention.select_memory_intervention(
            state_for(payload),
            payload["query"],
            payload["decision"],
            candidate_action=payload["candidate_action"],
            now=payload["query"]["at"],
        )
        self.assertEqual(result["decision"], "intervene")
        self.assertEqual(result["intervention"]["kind"], "uncertainty_brake")
        self.assertEqual(result["intervention"]["facts"], [])
        self.assertEqual(result["intervention"]["recommended_action"], "request_clarification")
        self.assertTrue(attention.intervention_is_grounded(result))

    def test_ungrounded_advisor_cannot_change_action(self):
        result = attention.advisor_only_control("continue")
        consumed = attention.consume_memory_intervention("continue", result)
        self.assertFalse(consumed["accepted"])
        self.assertEqual(consumed["action"], "continue")
        self.assertFalse(attention.intervention_is_grounded(result))

    def test_matched_control_evaluation_supports_selective_policy_only(self):
        result = evaluator.evaluate_cases(public_cases())
        selective = result["metrics"]["selective"]
        self.assertEqual(selective["case_success_percent"], 100.0)
        self.assertEqual(selective["grounding_percent"], 100.0)
        self.assertEqual(selective["intervention_precision_percent"], 100.0)
        self.assertEqual(selective["intervention_recall_percent"], 100.0)
        self.assertGreaterEqual(result["memory_needed_action_gain_vs_no_memory_percent"], 40.0)
        self.assertTrue(all(effect >= 25.0 for effect in result["control_effects_percent"].values()))
        self.assertEqual(result["metrics"]["always_on"]["unnecessary_intervention_percent"], 100.0)

    def test_preregistration_fails_closed_on_case_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            cases_path = Path(temp) / "cases.json"
            cases_path.write_text(json.dumps(public_cases()), encoding="utf-8")
            registration = evaluator.build_registration(
                cases_path,
                evaluator_id="test-independent-evaluator",
                registered_at="2026-08-01T00:00:00+00:00",
            )
            evaluator.validate_registration(registration, cases_path)
            changed = public_cases()
            changed[0] = copy.deepcopy(changed[0])
            changed[0]["candidate_action"] = "verify"
            cases_path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed after registration"):
                evaluator.validate_registration(registration, cases_path)

    def test_registered_report_preserves_non_consciousness_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            cases_path = Path(temp) / "cases.json"
            cases_path.write_text(json.dumps(public_cases()), encoding="utf-8")
            registration = evaluator.build_registration(
                cases_path,
                evaluator_id="test-independent-evaluator",
                registered_at="2026-08-01T00:00:00+00:00",
            )
            report = evaluator.run_registered_evaluation(
                registration,
                cases_path,
                evaluated_at="2026-08-01T00:01:00+00:00",
            )
            self.assertEqual(report["status"], "supported")
            self.assertFalse(report["runtime_mutated"])
            self.assertFalse(report["resident_recurrent_policy_integrated"])
            self.assertFalse(report["consciousness_proven"])
            self.assertEqual(report["verdict"], "not_a_consciousness_verdict")


if __name__ == "__main__":
    unittest.main()
