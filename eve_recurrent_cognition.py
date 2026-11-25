"""Typed result-to-query recurrence and selective action-memory shadowing.

This module is deliberately pure.  It converts a verified tool/action result
into a bounded module result, derives the next internal query from that exact
result, and asks Eve's evidence-bound memory-attention policy whether repeating
the selected action would need a reminder.  The resident runtime decides what
to persist or execute.

These mechanisms make causal recurrence and selective memory testable.  They
do not establish phenomenal consciousness.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import eve_memory_attention as memory_attention
import eve_memory_lifecycle as memory_lifecycle


MODULE_RESULT_SCHEMA = "eve.recurrent_module_result.v1"
MODULE_QUERY_SCHEMA = "eve.recurrent_module_query.v1"
MEMORY_SHADOW_SCHEMA = "eve.recurrent_memory_attention_shadow.v1"


def finite_measurement(value: object) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def normalize_observation_prediction(value: object) -> Dict[str, object]:
    """A bounded numeric test, never executable model-authored code."""
    if not isinstance(value, dict):
        return {}
    metric = value.get("metric")
    if (not isinstance(metric, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", metric)
            or value.get("operator") not in {"gt", "ge", "lt", "le", "eq"}
            or not finite_measurement(value.get("value"))):
        return {}
    return {"metric": metric, "operator": value["operator"], "value": value["value"]}


def decoder_artifact_measurement(artifact: object, returned_evidence: object, digest: str) -> Dict[str, object]:
    """Verify the existing decoder's aggregate against its exact artifact snapshot."""
    invalid = {"schema_id": "eve.decoder_measurement.v1", "valid": False, "metrics": {}}
    if not isinstance(artifact, dict) or not isinstance(returned_evidence, dict):
        return invalid
    results = artifact.get("results")
    means = returned_evidence.get("closed_loop_mean_travel")
    if not isinstance(results, dict) or not isinstance(means, dict):
        return invalid
    measured = {}
    for key in ("graph_decoder", "zero"):
        rows = results.get(key)
        if not isinstance(rows, list) or not rows or len(rows) > 10000:
            return invalid
        values = [row.get("travel_cm") if isinstance(row, dict) else None for row in rows]
        if any(not finite_measurement(value) or value < 0 for value in values):
            return invalid
        mean = round(sum(values) / len(values), 3)
        if not finite_measurement(mean) or not finite_measurement(means.get(key)) or means[key] != mean:
            return invalid
        measured[key] = mean
    return {"schema_id": "eve.decoder_measurement.v1", "valid": True,
            "scope": "artifact_snapshot_not_current_live_body", "artifact_sha256": digest,
            "metrics": {"graph_travel_cm": measured["graph_decoder"], "zero_travel_cm": measured["zero"],
                        "graph_minus_double_zero_cm": round(measured["graph_decoder"] - 2 * measured["zero"], 3)}}


def normalize_inquiry_measurement(value: object) -> Dict[str, object]:
    if not isinstance(value, dict) or value.get("schema_id") != "eve.decoder_measurement.v1":
        return {}
    invalid = {"schema_id": "eve.decoder_measurement.v1", "valid": False, "metrics": {}}
    metrics = value.get("metrics")
    if (value.get("valid") is not True or not isinstance(metrics, dict)
            or not re.fullmatch(r"[0-9a-f]{64}", str(value.get("artifact_sha256") or ""))
            or value.get("scope") != "artifact_snapshot_not_current_live_body"
            or any(not finite_measurement(metrics.get(key)) for key in
                   ("graph_travel_cm", "zero_travel_cm", "graph_minus_double_zero_cm"))):
        return invalid
    if (metrics["graph_travel_cm"] < 0 or metrics["zero_travel_cm"] < 0
            or metrics["graph_minus_double_zero_cm"] != round(metrics["graph_travel_cm"] - 2 * metrics["zero_travel_cm"], 3)):
        return invalid
    return {**invalid, "valid": True, "scope": value["scope"], "artifact_sha256": value["artifact_sha256"],
            "metrics": {key: metrics[key] for key in ("graph_travel_cm", "zero_travel_cm", "graph_minus_double_zero_cm")}}


def assess_inquiry_predictions(proposal: object, measurement: object) -> Dict[str, object]:
    """Score predicted observations, not the truth of a causal explanation."""
    alternatives = proposal.get("alternatives", []) if isinstance(proposal, dict) else []
    if not isinstance(alternatives, list):
        alternatives = []
    valid = isinstance(measurement, dict) and measurement.get("valid") is True
    metrics = measurement.get("metrics", {}) if valid else {}
    if not isinstance(metrics, dict):
        metrics = {}
    assessed = []
    for index, alternative in enumerate(alternatives[:2]):
        test = normalize_observation_prediction(alternative.get("test")) if isinstance(alternative, dict) else {}
        value = metrics.get(test.get("metric"))
        supported = None
        if test and finite_measurement(value):
            threshold = test["value"]
            supported = {"gt": value > threshold, "ge": value >= threshold,
                         "lt": value < threshold, "le": value <= threshold,
                         "eq": value == threshold}[test["operator"]]
        assessed.append({"alternative_index": index, "test": test,
                         "observed_value": value if finite_measurement(value) else None,
                         "prediction_supported": supported,
                         "explanation_status": "unverified_hypothesis"})
    discriminated = len(assessed) == 2 and {row["prediction_supported"] for row in assessed} == {True, False}
    return {"schema_id": "eve.inquiry_prediction_assessment.v1", "measurement_valid": bool(valid),
            "predictions_discriminated": discriminated, "alternatives": assessed,
            "causal_explanation_established": False}


def inquiry_observation_resolved(criterion: object, assessment: Mapping[str, object]) -> bool:
    """Require the precommitted question predicate, not arbitrary model thresholds."""
    test = normalize_observation_prediction(criterion)
    rows = assessment.get("alternatives", [])
    if not test or not assessment.get("predictions_discriminated") or len(rows) != 2:
        return False
    tests = [row.get("test", {}) for row in rows]
    if test not in tests or any(t.get("metric") != test["metric"] or t.get("value") != test["value"] for t in tests):
        return False
    return {t.get("operator") for t in tests} in ({"gt", "le"}, {"ge", "lt"})


def thought_learning_evidence_packet(record: Mapping[str, object]) -> Dict[str, object]:
    return {"current_state_record": record.get("current_state_record") or {},
            "current_state_record_hash": record.get("current_state_record_hash") or "",
            "verified_action_evidence": record.get("verified_action_evidence") or [],
            "reviewed_lessons": record.get("reviewed_lessons") or [],
            "closed_world": True, "phenomenal_status": "unknown"}


def thought_learning_review_hash(record: Mapping[str, object]) -> str:
    return _canonical_sha256({"episode_id": record.get("id"),
        "available_context": thought_learning_evidence_packet(record),
        "attempted_model": record.get("attempted_model"), "attempted_response": record.get("attempted_response"),
        "preferred_response": record.get("preferred_response"),
        "initial_epistemic_critic": record.get("initial_epistemic_critic") or {},
        "epistemic_critic": record.get("epistemic_critic") or {},
        **({"repair_candidate_response": record["repair_candidate_response"]}
           if "repair_candidate_response" in record else {})})


def reviewed_thought_correction(record: Mapping[str, object], notes: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    """Join an explicit operator review in the existing review-note store.

    This is an admission contract, not an OS security boundary. Labels alone
    never turn a resident critic, synthetic test, or stale review into a lesson.
    """
    if not isinstance(record, dict):
        return {}
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    source = str(record.get("source") or "")
    if (source not in {"daemon", "manual", "think", "manual_think", "autonomy_free_run", "daemon_autonomy"}
            and not source.startswith("autonomy_free_run:")):
        return {}
    if (record.get("privacy_tier") not in {"local_only", "public"}
            or record.get("synthetic") or metadata.get("synthetic")
            or record.get("evaluation_only") or metadata.get("evaluation_only")
            or metadata.get("conversation_class") in {"synthetic_eval", "private_holdout"}
            or record.get("split") in {"private_holdout", "holdout", "validation"}
            or record.get("candidate_status") != "rejected_model_candidate_not_state_evidence"
            or "verified_action_evidence" not in record):
        return {}
    for note in sorted((n for n in notes if isinstance(n, dict)),
                       key=lambda n: str(n.get("updated_at") or n.get("created_at") or ""), reverse=True):
        if (note.get("source") != "manual" or not note.get("id") or not note.get("reviewer")
                or str(note["reviewer"]).lower() in {"eve", "eve-fast", "eve-deep", "eve-observer", "eve-planner", "eve-relationship"}):
            continue
        try:
            review = json.loads(str(note.get("body") or ""))
        except (ValueError, TypeError):
            continue
        if (not isinstance(review, dict) or review.get("schema_id") != "eve.thought_correction_review.v1"
                or review.get("episode_id") != record.get("id")):
            continue
        # The latest matching review can revoke an older approval. A changed
        # evidence packet also invalidates the review rather than finding an older one.
        if (note.get("status") != "active" or review.get("decision") != "approved"
                or review.get("evidence_hash") != thought_learning_review_hash(record)):
            return {}
        state = record.get("current_state_record") or {}
        response, lesson = review.get("preferred_response"), review.get("lesson")
        if (not isinstance(state, dict) or review.get("target_kind") != state.get("target_kind")
                or not state.get("target_kind") or not isinstance(response, str) or not response.strip()
                or len(response) > 1200 or not isinstance(lesson, str) or not lesson.strip() or len(lesson) > 400):
            return {}
        return {"review_id": note["id"], "reviewer": note["reviewer"], "episode_id": record["id"],
                "evidence_hash": review["evidence_hash"], "target_kind": review["target_kind"],
                "preferred_response": response, "lesson": lesson,
                "source_role": "reviewed_historical_example_not_current_evidence"}
    return {}


def _text(value: object, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_time(value: object) -> Optional[datetime]:
    text = _text(value, 80)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalized_time(value: object) -> str:
    parsed = _parse_time(value)
    if parsed is None:
        raise ValueError("a timezone-aware timestamp is required")
    return parsed.isoformat()


def _explicit_bool(value: object) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    text = _text(value, 20).lower()
    if text in {"true", "1", "yes", "on", "ok", "verified", "success", "passed"}:
        return True
    if text in {"false", "0", "no", "off", "unverified", "failure", "failed"}:
        return False
    return None


def _verification(result: Mapping[str, object]) -> Optional[bool]:
    for key in ("execution_verification_ok", "verification_ok"):
        if key not in result:
            continue
        parsed = _explicit_bool(result.get(key))
        if parsed is not None:
            return parsed
    return None


def _unique_texts(values: object, *, limit: int = 20, width: int = 160) -> List[str]:
    source = values if isinstance(values, (list, tuple, set, frozenset)) else []
    output: List[str] = []
    seen = set()
    for value in source:
        text = _text(value, width)
        if text and text not in seen:
            seen.add(text)
            output.append(text)
        if len(output) >= limit:
            break
    return output


def action_result_consistency(result: Mapping[str, object]) -> Optional[bool]:
    """Check negative/invalid execution evidence, independently of verification.

    True means no contradiction, not success. A verifier, a terminal process
    result, or an execution receipt is still needed by the owning consumer.
    False evidence vetoes optimistic fields; malformed flags remain unknown.
    """
    status = _text(result.get("status"), 40).lower()
    tree_status = _text(result.get("execution_tree_status") or result.get("tree_status"), 40).lower()
    if status in {"blocked", "error", "failed", "failure", "skipped"} or tree_status in {
        "blocked", "error", "failed", "failure",
    }:
        return False
    flags = [
        _explicit_bool(result[key]) for key in ("executed", "ok", "result_ok", "typed_contract_ok")
        if key in result and result[key] is not None
    ]
    if "typed_contract" in result:
        contract = result["typed_contract"]
        flags.append(_explicit_bool(contract.get("valid")) if isinstance(contract, Mapping) else None)
    if False in flags:
        return False
    if None in flags:
        return None
    return True


def _result_state(result: Mapping[str, object]) -> str:
    verification = _verification(result)
    consistency = action_result_consistency(result)
    executed = _explicit_bool(result.get("executed")) if "executed" in result else None
    status = _text(result.get("status"), 40).lower()
    tree_status = _text(
        result.get("execution_tree_status") or result.get("tree_status"),
        40,
    ).lower()
    if executed is False or status in {"blocked", "error", "failed", "skipped"} or tree_status in {
        "blocked",
        "error",
        "failed",
        "failure",
    }:
        return "blocked_or_failed"
    if verification is False or consistency is False:
        return "verified_failure"
    if verification is True and consistency is True:
        return "verified_success"
    return "unverified"


def _bounded_facts(result: Mapping[str, object]) -> Dict[str, object]:
    """Keep compact typed facts without copying arbitrary tool payloads."""

    allowed = (
        "status",
        "gateway_state",
        "gateway_reachable",
        "process_running",
        "event_created",
        "event_count",
        "created_count",
        "completed_count",
        "maintenance_count",
        "variant",
        "feature",
        "scope",
    )
    facts: Dict[str, object] = {}
    for key in allowed:
        value = result.get(key)
        if value is None or isinstance(value, (str, int, float, bool)):
            if value not in {None, ""}:
                facts[key] = _text(value, 160) if isinstance(value, str) else value
    return facts


def build_typed_module_result(
    action: object,
    result: Mapping[str, object],
    *,
    source_cycle_id: object,
    observed_at: object,
) -> Dict[str, object]:
    """Bind one actual action result to the exact recurrent source cycle."""

    action_id = _text(action, 100)
    cycle_id = _text(source_cycle_id, 100)
    if not action_id or not cycle_id or not isinstance(result, Mapping):
        raise ValueError("action, source_cycle_id, and a result mapping are required")
    timestamp = _normalized_time(observed_at)
    execution_id = _text(result.get("execution_id") or result.get("id"), 160)
    typed_contract = result.get("typed_contract") if isinstance(result.get("typed_contract"), Mapping) else {}
    evidence_ids = _unique_texts(
        [
            execution_id,
            *(
                typed_contract.get("evidence_ids")
                if isinstance(typed_contract.get("evidence_ids"), list)
                else []
            ),
        ],
        limit=20,
    )
    payload: Dict[str, object] = {
        "schema_id": MODULE_RESULT_SCHEMA,
        "module_id": action_id,
        "source_cycle_id": cycle_id,
        "execution_id": execution_id,
        "observed_at": timestamp,
        "outcome_state": _result_state(result),
        "executed": _explicit_bool(result.get("executed")) if "executed" in result else None,
        "verification_ok": _verification(result),
        "result_ok": _explicit_bool(result.get("ok")) if "ok" in result else None,
        "typed_contract_schema": _text(typed_contract.get("schema_id"), 120),
        "typed_contract_valid": (
            _explicit_bool(typed_contract.get("valid")) if "valid" in typed_contract else None
        ),
        "summary": _text(
            result.get("execution_summary") or result.get("summary") or result.get("response"),
            320,
        ),
        "facts": _bounded_facts(result),
        "evidence_ids": evidence_ids,
        "grounded": bool(
            execution_id and _verification(result) is not None
            and (action_result_consistency(result) is not None or _verification(result) is False)
        ),
    }
    payload["result_sha256"] = _canonical_sha256(payload)
    return payload


def _action_counts(recent_actions: Sequence[Mapping[str, object]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in recent_actions:
        if not isinstance(row, Mapping):
            continue
        action = _text(row.get("action"), 100)
        if action:
            counts[action] = counts.get(action, 0) + 1
    return counts


def action_retry_inhibition(
    records: Sequence[Mapping[str, object]], *, now: object,
) -> Dict[str, Dict[str, object]]:
    """Suppress a repeated identical failed observation, not the whole agent.

    The existing execution ledger owns persistence. A changed result, verified
    recovery, or a fifteen-minute retry boundary reopens the action. Execution
    ids deduplicate receipts; they are never part of the fault identity.
    """
    moment = _parse_time(now)
    if moment is None:
        return {}
    grouped: Dict[str, List[Tuple[datetime, Mapping[str, object]]]] = {}
    seen = set()
    for row in records:
        if not isinstance(row, Mapping):
            continue
        action = _text(row.get("action"), 100)
        when = _parse_time(row.get("finished_at") or row.get("updated_at") or row.get("created_at") or row.get("timestamp"))
        identity = _text(row.get("execution_id") or row.get("id"), 100) or _canonical_sha256(row)
        if not action or when is None or identity in seen or not 0 <= (moment - when).total_seconds() < 900:
            continue
        seen.add(identity)
        grouped.setdefault(action, []).append((when, row))
    inhibited = {}
    for action, rows in grouped.items():
        rows.sort(key=lambda item: item[0], reverse=True)
        latest = rows[0][1]
        fault = (_result_state(latest), _text(latest.get("summary"), 260))
        if fault[0] not in {"blocked_or_failed", "verified_failure"}:
            continue
        repeated = []
        for when, row in rows:
            if (_result_state(row), _text(row.get("summary"), 260)) != fault:
                break
            repeated.append(when)
        if len(repeated) < 2:
            continue
        retry_at = max(repeated) + timedelta(minutes=15)
        inhibited[action] = {
            "fault_fingerprint": _canonical_sha256([action, *fault])[:24],
            "attempt_count": len(repeated), "retry_after": retry_at.isoformat(),
            "reason": "Repeated unchanged failure; await new evidence or the bounded retry time.",
        }
    return inhibited


def choose_query_target_action(
    module_result: Mapping[str, object],
    *,
    admitted_actions: Iterable[str],
    recent_actions: Sequence[Mapping[str, object]] = (),
) -> str:
    """Choose a bounded next module using outcome-sensitive deterministic policy."""

    admitted = _unique_texts(list(admitted_actions), limit=40, width=100)
    source_action = _text(module_result.get("module_id"), 100)
    inhibited = action_retry_inhibition(recent_actions, now=module_result.get("observed_at"))
    candidates = [item for item in admitted if item != source_action and item not in inhibited]

    failure_transitions = {
        "openclaw_sync_check": "openclaw_log_check",
        "openclaw_self_test": "openclaw_log_check",
        "openclaw_log_check": "service_health_check",
        "service_health_check": "system_tasks",
        "cleanup_candidate_check": "service_health_check",
        "updates_status": "service_health_check",
        "agent_capability_scout": "agent_capability_integration",
        "agent_capability_integration": "system_tasks",
        "system_tasks": "service_health_check",
    }
    outcome = _text(module_result.get("outcome_state"), 40)
    if outcome != "verified_success":
        preferred = failure_transitions.get(source_action, "")
        if preferred in candidates:
            return preferred
        # Menu order is not a causal repair relationship. In particular a fly
        # feeding experiment cannot diagnose an OpenClaw plugin failure.
        return ""

    if not candidates:
        return ""

    counts = _action_counts(recent_actions)
    order = {action: index for index, action in enumerate(admitted)}
    return min(candidates, key=lambda item: (counts.get(item, 0), order.get(item, 999), item))


def derive_next_module_query(
    module_result: Mapping[str, object],
    *,
    admitted_actions: Iterable[str],
    recent_actions: Sequence[Mapping[str, object]] = (),
) -> Dict[str, object]:
    """Derive the next internal query from the exact typed result."""

    if not module_result_is_valid(module_result):
        raise ValueError("unsupported module-result schema")
    source_sha = _text(module_result.get("result_sha256"), 80)
    source_action = _text(module_result.get("module_id"), 100)
    if not source_sha or not source_action:
        raise ValueError("module result is missing causal identity")
    target_action = choose_query_target_action(
        module_result,
        admitted_actions=admitted_actions,
        recent_actions=recent_actions,
    )
    outcome = _text(module_result.get("outcome_state"), 40)
    grounded = bool(module_result.get("grounded"))
    if not target_action:
        kind = "await_evidence"
        question = (
            f"`{source_action}` has no admitted, relevant next probe. Preserve the unresolved "
            "observation and resume other goals until new evidence or a repair changes it."
        )
    elif not grounded:
        kind = "verification_gap"
        question = (
            f"The `{source_action}` result was not independently grounded. "
            f"Use `{target_action or source_action}` to obtain the missing typed verification before relying on it."
        )
    elif outcome == "verified_success":
        kind = "consequence_and_novelty"
        question = (
            f"`{source_action}` produced a verified consequence. Test whether "
            f"`{target_action or source_action}` now adds distinct evidence instead of repeating the same check."
        )
    else:
        kind = "repair_or_alternative"
        question = (
            f"`{source_action}` ended as `{outcome}`. Use `{target_action or source_action}` "
            "to resolve the failure or evidence gap before retrying the same action."
        )
    payload: Dict[str, object] = {
        "schema_id": MODULE_QUERY_SCHEMA,
        "query_kind": kind,
        "question": _text(question, 420),
        "source_module": source_action,
        "target_module": target_action,
        "target_action": target_action,
        "source_result_sha256": source_sha,
        "source_cycle_id": _text(module_result.get("source_cycle_id"), 100),
        "created_at": _text(module_result.get("observed_at"), 80),
        "evidence_ids": _unique_texts(module_result.get("evidence_ids"), limit=20),
        "grounded": grounded,
    }
    payload["id"] = "module-query-" + _canonical_sha256(payload)[:20]
    payload["query_sha256"] = _canonical_sha256(payload)
    return payload


def _record_outcome(row: Mapping[str, object]) -> str:
    # The shared classifier accepts both ledger and executor fields. Projecting
    # aliases first can discard contradictions or turn an optional ledger null
    # into a fabricated malformed typed contract.
    return _result_state(row)


def _action_observations(
    recent_actions: Sequence[Mapping[str, object]],
    *,
    candidate_action: str,
) -> List[Dict[str, object]]:
    rows: List[Tuple[datetime, str, Mapping[str, object]]] = []
    for row in recent_actions:
        if not isinstance(row, Mapping) or _text(row.get("action"), 100) != candidate_action:
            continue
        observed_at = _parse_time(row.get("created_at") or row.get("updated_at") or row.get("timestamp"))
        evidence_id = _text(row.get("execution_id") or row.get("id"), 120)
        if observed_at is None or not evidence_id:
            continue
        rows.append((observed_at, evidence_id, row))
    rows.sort(key=lambda item: (item[0], item[1]))
    observations: List[Dict[str, object]] = []
    previous_evidence = ""
    for index, (observed_at, evidence_id, row) in enumerate(rows):
        operation = "assert" if index == 0 else "revise"
        observation: Dict[str, object] = {
            "event_id": f"action-outcome:{candidate_action}:{evidence_id}",
            "evidence_id": evidence_id,
            "entity": f"action:{candidate_action}",
            "slot": "last_outcome",
            "value": _record_outcome(row),
            "source_kind": "tool_receipt",
            "confidence": 1.0 if _verification(row) is not None else 0.85,
            "observed_at": observed_at.isoformat(),
            "operation": operation,
        }
        if operation == "revise":
            observation["supersedes"] = [previous_evidence]
        observations.append(observation)
        previous_evidence = evidence_id
    return observations


def evaluate_action_memory_shadow(
    recent_actions: Sequence[Mapping[str, object]],
    candidate_action: object,
    *,
    now: object,
) -> Dict[str, object]:
    """Evaluate, but never apply, memory pressure on the selected action."""

    candidate = _text(candidate_action, 100)
    timestamp = _normalized_time(now)
    observations = _action_observations(recent_actions, candidate_action=candidate)
    if not candidate:
        raise ValueError("candidate_action is required")

    if not observations:
        assessment = memory_attention.silence_control(
            "explore_novel_action",
            arm="no_prior_action_evidence",
        )
        consumed = memory_attention.consume_memory_intervention(
            "explore_novel_action",
            assessment,
        )
    else:
        state = memory_lifecycle.new_memory_state()
        for observation in observations:
            state, _ = memory_lifecycle.write_observation(state, observation)
        state = memory_lifecycle.maintain_memory(state, now=timestamp)
        policy = {
            "required_slots": ["last_outcome"],
            "rules": [
                {"when": {"last_outcome": "verified_success"}, "action": "repeat_candidate"},
                {"when": {"last_outcome": "verified_failure"}, "action": "choose_alternative"},
                {"when": {"last_outcome": "blocked_or_failed"}, "action": "choose_alternative"},
                {"when": {"last_outcome": "unverified"}, "action": "seek_verification"},
            ],
            "uncertain_action": "seek_verification",
            "fallback_action": "seek_verification",
        }
        assessment = memory_attention.select_memory_intervention(
            state,
            {"entity": f"action:{candidate}", "slots": ["last_outcome"]},
            policy,
            candidate_action="repeat_candidate",
            now=timestamp,
        )
        consumed = memory_attention.consume_memory_intervention(
            "repeat_candidate",
            assessment,
        )

    intervention = assessment.get("intervention") if isinstance(assessment.get("intervention"), Mapping) else {}
    evidence_ids = _unique_texts(
        [
            *(intervention.get("evidence_ids") if isinstance(intervention.get("evidence_ids"), list) else []),
            *[item.get("evidence_id") for item in observations],
        ],
        limit=20,
    )
    payload: Dict[str, object] = {
        "schema_id": MEMORY_SHADOW_SCHEMA,
        "mode": "shadow",
        "candidate_action": candidate,
        "history_count": len(observations),
        "decision": assessment.get("decision"),
        "reason": assessment.get("reason"),
        "recommended_policy_action": consumed.get("action"),
        "would_intervene": assessment.get("decision") == "intervene",
        "would_change_policy_action": bool(consumed.get("changed")),
        "accepted": bool(consumed.get("accepted")),
        "evidence_ids": evidence_ids,
        "assessment_sha256": assessment.get("assessment_sha256"),
        "action_change_applied": False,
    }
    payload["shadow_sha256"] = _canonical_sha256(payload)
    return payload


def module_query_is_valid(value: object) -> bool:
    payload = value if isinstance(value, Mapping) else {}
    query_sha = _text(payload.get("query_sha256"), 80)
    canonical = dict(payload)
    canonical.pop("query_sha256", None)
    return bool(
        payload.get("schema_id") == MODULE_QUERY_SCHEMA
        and _text(payload.get("id"), 100)
        and _text(payload.get("question"), 420)
        and _text(payload.get("source_result_sha256"), 80)
        and (
            _text(payload.get("target_module"), 100)
            or (payload.get("query_kind") == "await_evidence" and not payload.get("target_action"))
        )
        and query_sha
        and query_sha == _canonical_sha256(canonical)
    )


def module_result_is_valid(value: object) -> bool:
    payload = value if isinstance(value, Mapping) else {}
    result_sha = _text(payload.get("result_sha256"), 80)
    canonical = dict(payload)
    canonical.pop("result_sha256", None)
    return bool(
        payload.get("schema_id") == MODULE_RESULT_SCHEMA
        and _text(payload.get("module_id"), 100)
        and _text(payload.get("source_cycle_id"), 100)
        and _text(payload.get("observed_at"), 80)
        and result_sha
        and result_sha == _canonical_sha256(canonical)
    )
