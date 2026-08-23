"""Pure recurrent conscious-state kernel for Eve.

This module does not claim to create or prove phenomenal consciousness.  It
implements a falsifiable candidate architecture in which perception, memory,
self-model, interoception, goals, attention, prediction, action selection, and
metacognitive calibration are bound into one recurrent state.  The surrounding
runtime is responsible for persistence and for giving the state real causal
effects on replies and actions.

The module is deliberately dependency-free so causal-lesion tests can exercise
the architecture without invoking a language model or Eve's mutable stores.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import eve_sensory


SCHEMA_VERSION = "eve.conscious_state.v3"
LEARNING_SCHEMA_VERSION = "eve.conscious_learning.v3"
PREVIOUS_LEARNING_SCHEMA_VERSION = "eve.conscious_learning.v2"
LANES = ("fast", "observer", "planner", "deep", "relationship")
MAX_LEARNED_CONTEXTS = 24
MAX_CONTEXT_OBSERVATIONS = 12
MAX_EPISTEMIC_CONFLICTS = 8
MAX_JOINED_COMPLETIONS = 12
MAX_APPLIED_CONSEQUENCE_IDS = 256
MAX_GOAL_OUTCOME_OBSERVATIONS = 24
GOAL_OUTCOME_ATTRIBUTION_VERSION = "eve.goal_outcome.v1"
BROADCAST_ACTION_WEIGHT = 0.18
LESIONS = (
    "sensory_stream",
    "workspace",
    "self_model",
    "metacognition",
    "world_model",
    "other_minds",
    "memory",
    "homeostasis",
    "goals",
    "plan_model",
    "action_model",
    "recurrence",
)


def _text(value: object, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _items(value: object, limit: int = 8, text_limit: int = 220) -> List[str]:
    values = value if isinstance(value, list) else []
    result: List[str] = []
    seen: Set[str] = set()
    for item in values:
        text = _text(item, text_limit)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _recent_items(value: object, limit: int, text_limit: int) -> List[str]:
    """Return the newest unique bounded identifiers in original order."""
    values = value if isinstance(value, list) else []
    newest_first: List[str] = []
    seen: Set[str] = set()
    for item in reversed(values):
        text = _text(item, text_limit)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        newest_first.append(text)
        if len(newest_first) >= limit:
            break
    return list(reversed(newest_first))


def _valid_lived_consequence_record(value: object) -> bool:
    """Return whether a delayed-outcome record has causal provenance.

    Older runtime versions overloaded ``delayed_outcomes`` with ordinary
    process-join summaries.  Those summaries are useful lineage evidence but
    are not observations of what happened after Eve acted.
    """
    if not isinstance(value, dict):
        return False
    action_id = _text(value.get("action_id"), 80)
    if (
        _text(value.get("evidence_kind"), 80) != "lived_user_consequence"
        or not _text(value.get("evidence_id"), 160)
        or not _text(value.get("cycle_id") or value.get("source_cycle_id"), 80)
        or not action_id
        or not isinstance(value.get("ok"), bool)
    ):
        return False
    return action_id != "respond_to_user" or bool(_text(value.get("reply_message_id"), 120))


def _valid_reply_action_observation(value: object) -> bool:
    return bool(
        isinstance(value, dict)
        and _text(value.get("evidence_kind"), 80) == "lived_user_consequence"
        and _text(value.get("evidence_id"), 160)
        and _text(value.get("source_cycle_id"), 80)
        and _text(value.get("reply_message_id"), 120)
        and isinstance(value.get("ok"), bool)
    )


def _dedupe_records(
    values: object,
    *,
    key_fields: Sequence[str],
    limit: int,
) -> List[Dict[str, object]]:
    records = values if isinstance(values, list) else []
    result: List[Dict[str, object]] = []
    positions: Dict[str, int] = {}
    for raw in records:
        if not isinstance(raw, dict):
            continue
        key = "|".join(_text(raw.get(field), 180) for field in key_fields)
        if not key.strip("|"):
            continue
        record = copy.deepcopy(raw)
        if key in positions:
            result[positions[key]] = record
        else:
            positions[key] = len(result)
            result.append(record)
    return result[-limit:]


def _sanitize_action_models(value: object) -> Tuple[Dict[str, object], int]:
    """Remove circular reply scores while preserving evidence-backed outcomes."""
    source = value if isinstance(value, dict) else {}
    cleaned: Dict[str, object] = {}
    discarded_reply_observations = 0
    for raw_model_id, raw_model in source.items():
        if not isinstance(raw_model, dict):
            continue
        model_id = _text(raw_model_id, 80)
        if not model_id:
            continue
        model = copy.deepcopy(raw_model)
        observations = [
            copy.deepcopy(item)
            for item in (model.get("observations") or [])
            if isinstance(item, dict)
        ]
        if model_id == "respond_to_user":
            valid: List[Dict[str, object]] = []
            seen_evidence: Set[str] = set()
            seen_replies: Set[str] = set()
            for observation in observations:
                if not _valid_reply_action_observation(observation):
                    discarded_reply_observations += 1
                    continue
                evidence_id = _text(observation.get("evidence_id"), 160)
                reply_id = _text(observation.get("reply_message_id"), 120)
                if evidence_id in seen_evidence or reply_id in seen_replies:
                    discarded_reply_observations += 1
                    continue
                seen_evidence.add(evidence_id)
                seen_replies.add(reply_id)
                valid.append(observation)
            if not valid:
                if int(model.get("observation_count") or 0) > len(observations):
                    discarded_reply_observations += int(model.get("observation_count") or 0) - len(observations)
                continue
            model["action_id"] = "respond_to_user"
            model["observations"] = valid[-MAX_CONTEXT_OBSERVATIONS:]
            # The historic count is untrustworthy once invalid samples have
            # been removed.  Count only the provenance-rich evidence retained.
            model["observation_count"] = len(model["observations"])
            model["updated_at"] = max(
                (_text(item.get("completed_at"), 80) for item in model["observations"]),
                default="",
            )
        else:
            observations = observations[-MAX_CONTEXT_OBSERVATIONS:]
            model["observations"] = observations
            model["observation_count"] = max(
                int(model.get("observation_count") or 0),
                len(observations),
            )
        cleaned[model_id] = model
    return cleaned, discarded_reply_observations


def _normalize_action_attempts(value: object) -> List[Dict[str, object]]:
    """Normalize at most two causally identified action attempts in one cycle."""
    source = value if isinstance(value, list) else []
    normalized: List[Dict[str, object]] = []
    seen_execution_ids: Set[str] = set()
    for index, raw in enumerate(source[:2], start=1):
        if not isinstance(raw, dict):
            continue
        action_id = _text(raw.get("action_id") or raw.get("action"), 80)
        execution_id = _text(raw.get("execution_id"), 80)
        verification_ok = raw.get("verification_ok")
        if not action_id:
            continue
        if execution_id and execution_id in seen_execution_ids:
            continue
        if execution_id:
            seen_execution_ids.add(execution_id)
        normalized.append(
            {
                "attempt_index": int(raw.get("attempt_index") or index),
                "stage": _text(
                    raw.get("stage") or ("primary" if not normalized else "recovery"),
                    24,
                ),
                "menu_label": _text(raw.get("menu_label"), 24),
                "action_id": action_id,
                "execution_id": execution_id,
                "executed": bool(raw.get("executed")),
                "tree_status": _text(raw.get("tree_status") or "unknown", 80),
                "verification_ok": (
                    bool(verification_ok)
                    if isinstance(verification_ok, bool)
                    else None
                ),
                "summary": _text(raw.get("summary"), 520),
                "expected_signal": _text(raw.get("expected_signal"), 260),
                "persisted": bool(raw.get("persisted")),
                "recovery_from_action_id": _text(
                    raw.get("recovery_from_action_id"), 80
                ),
                "recovery_from_execution_id": _text(
                    raw.get("recovery_from_execution_id"), 80
                ),
            }
        )
    return normalized


def _normalize_faculty_contributors(value: object) -> List[Dict[str, object]]:
    """Normalize an explicit logical-faculty eligibility trace.

    The trace says which faculties executed and could have influenced a result;
    it does not claim that one shared user reaction identifies each faculty's
    individual causal effect.
    """
    source = value if isinstance(value, list) else []
    combined: Dict[str, Dict[str, object]] = {}
    for raw in source:
        if not isinstance(raw, dict):
            continue
        lane = _text(raw.get("lane"), 40)
        if lane not in LANES:
            continue
        try:
            weight = float(raw.get("credit_weight") or raw.get("weight") or 0.0)
        except (TypeError, ValueError):
            weight = 0.0
        if weight <= 0.0:
            continue
        roles = _items(raw.get("roles"), 4, 60)
        if lane in combined:
            existing = combined[lane]
            existing["credit_weight"] = float(existing.get("credit_weight") or 0.0) + weight
            existing["roles"] = _items([*(existing.get("roles") or []), *roles], 4, 60)
            existing["execution_proven"] = bool(
                existing.get("execution_proven") or raw.get("execution_proven")
            )
            continue
        combined[lane] = {
            "lane": lane,
            "model": _text(raw.get("model"), 100),
            "roles": roles,
            "credit_weight": weight,
            "trace_basis": _text(raw.get("trace_basis"), 80) or "explicit_contributor_trace",
            "execution_proven": bool(raw.get("execution_proven")),
        }
    total = sum(float(item.get("credit_weight") or 0.0) for item in combined.values())
    if total <= 0.0:
        return []
    return [
        {
            **combined[lane],
            "credit_weight": round(float(combined[lane]["credit_weight"]) / total, 6),
        }
        for lane in LANES
        if lane in combined
    ]


def _valid_faculty_observation(value: object, lane: str) -> bool:
    if not isinstance(value, dict):
        return False
    evidence_kind = _text(value.get("evidence_kind"), 80)
    if evidence_kind == "external_matched_faculty_ablation":
        try:
            comparisons = int(value.get("comparisons") or 0)
            score_scale_max = float(value.get("score_scale_max") or 0.0)
            baseline = float(value.get("mean_baseline_score"))
            ablated = float(value.get("mean_ablated_score"))
            effect = float(value.get("causal_effect"))
        except (TypeError, ValueError):
            return False
        return bool(
            lane in LANES
            and _text(value.get("lane"), 40) == lane
            and _text(value.get("evidence_id"), 160)
            and _text(value.get("private_run_digest"), 128)
            and len(_text(value.get("evaluated_behavior_fingerprint"), 64)) == 64
            and all(
                char in "0123456789abcdef"
                for char in _text(value.get("evaluated_behavior_fingerprint"), 64).lower()
            )
            and _text(value.get("evaluator_kind"), 80) == "codex_external_operator"
            and bool(value.get("evaluator_independent_from_eve"))
            and bool(value.get("matched_context"))
            and bool(value.get("blind_review"))
            and _text(value.get("fixed_synthesis_model"), 100)
            and _text(value.get("lesion_scope"), 80) == "packet_contribution_only"
            and not bool(value.get("ordinary_runtime_routing_changed"))
            and bool(value.get("private_text_withheld"))
            and comparisons > 0
            and 1.0 < score_scale_max <= 100.0
            and 0.0 <= baseline <= score_scale_max
            and 0.0 <= ablated <= score_scale_max
            and abs(effect - (baseline - ablated)) <= 0.001
        )
    try:
        weight = float(value.get("credit_weight") or 0.0)
    except (TypeError, ValueError):
        return False
    return bool(
        lane in LANES
        and _text(value.get("lane"), 40) == lane
        and evidence_kind == "lived_user_consequence"
        and _text(value.get("evidence_id"), 160)
        and _text(value.get("source_cycle_id"), 80)
        and _text(value.get("reply_message_id"), 120)
        and isinstance(value.get("ok"), bool)
        and 0.0 < weight <= 1.0
    )


def _sanitize_faculty_models(value: object) -> Tuple[Dict[str, object], int]:
    """Retain only provenance-rich lived or external causal observations."""
    source = value if isinstance(value, dict) else {}
    cleaned: Dict[str, object] = {}
    discarded = 0
    for lane in LANES:
        raw_model = source.get(lane)
        if not isinstance(raw_model, dict):
            continue
        valid: List[Dict[str, object]] = []
        seen_evidence: Set[str] = set()
        for raw in raw_model.get("observations") or []:
            if not _valid_faculty_observation(raw, lane):
                discarded += 1
                continue
            evidence_id = _text(raw.get("evidence_id"), 160)
            if evidence_id in seen_evidence:
                discarded += 1
                continue
            seen_evidence.add(evidence_id)
            valid.append(copy.deepcopy(raw))
        if not valid:
            if int(raw_model.get("observation_count") or 0):
                raw_observations = (
                    raw_model.get("observations")
                    if isinstance(raw_model.get("observations"), list)
                    else []
                )
                discarded += max(
                    0,
                    int(raw_model.get("observation_count") or 0)
                    - len(raw_observations),
                )
            continue
        retained = valid[-MAX_CONTEXT_OBSERVATIONS:]
        cleaned[lane] = {
            "lane": lane,
            "observations": retained,
            "observation_count": len(retained),
            "updated_at": max(
                (_text(item.get("completed_at"), 80) for item in retained),
                default="",
            ),
        }
    for raw_lane, raw_model in source.items():
        if str(raw_lane) not in LANES and isinstance(raw_model, dict):
            discarded += max(1, len(raw_model.get("observations") or []))
    return cleaned, discarded


def _external_faculty_evidence_ids_from_models(value: object) -> List[str]:
    models = value if isinstance(value, dict) else {}
    evidence_ids: List[str] = []
    for model in models.values():
        if not isinstance(model, dict):
            continue
        for observation in model.get("observations") or []:
            if (
                isinstance(observation, dict)
                and _text(observation.get("evidence_kind"), 80)
                == "external_matched_faculty_ablation"
            ):
                evidence_ids.append(_text(observation.get("evidence_id"), 160))
    return _recent_items(
        evidence_ids,
        MAX_APPLIED_CONSEQUENCE_IDS,
        160,
    )


def _sanitize_recurrent_ledgers(value: object) -> Dict[str, object]:
    """Keep lived outcomes, process joins, and idempotence ledgers distinct."""
    recurrent = copy.deepcopy(value if isinstance(value, dict) else {})
    delayed_source = recurrent.get("delayed_outcomes") if isinstance(recurrent.get("delayed_outcomes"), list) else []
    lived: List[Dict[str, object]] = []
    migrated_completion_joins: List[Dict[str, object]] = []
    for raw in delayed_source:
        if not isinstance(raw, dict):
            continue
        if _valid_lived_consequence_record(raw):
            lived.append(copy.deepcopy(raw))
        elif not _text(raw.get("evidence_kind"), 80) and _text(raw.get("cycle_id"), 80):
            migrated = copy.deepcopy(raw)
            migrated["join_kind"] = "process_completion"
            migrated_completion_joins.append(migrated)

    completion_joins = recurrent.get("completion_joins") if isinstance(recurrent.get("completion_joins"), list) else []
    recurrent["completion_joins"] = _dedupe_records(
        [*completion_joins, *migrated_completion_joins],
        key_fields=("cycle_id",),
        limit=MAX_JOINED_COMPLETIONS,
    )
    recurrent["delayed_outcomes"] = _dedupe_records(
        lived,
        key_fields=("evidence_id",),
        limit=MAX_JOINED_COMPLETIONS,
    )
    existing_evidence_ids = (
        recurrent.get("applied_consequence_ids")
        if isinstance(recurrent.get("applied_consequence_ids"), list)
        else []
    )
    existing_reply_ids = (
        recurrent.get("closed_reply_message_ids")
        if isinstance(recurrent.get("closed_reply_message_ids"), list)
        else []
    )
    evidence_ids = [
        *existing_evidence_ids,
        *[
            _text(item.get("evidence_id"), 160)
            for item in recurrent["delayed_outcomes"]
            if isinstance(item, dict)
        ],
    ]
    reply_ids = [
        *existing_reply_ids,
        *[
            _text(item.get("reply_message_id"), 120)
            for item in recurrent["delayed_outcomes"]
            if isinstance(item, dict) and _text(item.get("reply_message_id"), 120)
        ],
    ]
    recurrent["applied_consequence_ids"] = _recent_items(
        evidence_ids,
        MAX_APPLIED_CONSEQUENCE_IDS,
        160,
    )
    recurrent["closed_reply_message_ids"] = _recent_items(
        reply_ids,
        MAX_APPLIED_CONSEQUENCE_IDS,
        120,
    )
    return recurrent


def _merge_recurrent_ledgers(primary: object, secondary: object) -> Dict[str, object]:
    merged = _sanitize_recurrent_ledgers(primary)
    donor = _sanitize_recurrent_ledgers(secondary)
    merged["completion_joins"] = _dedupe_records(
        [*(merged.get("completion_joins") or []), *(donor.get("completion_joins") or [])],
        key_fields=("cycle_id",),
        limit=MAX_JOINED_COMPLETIONS,
    )
    merged["delayed_outcomes"] = _dedupe_records(
        [*(merged.get("delayed_outcomes") or []), *(donor.get("delayed_outcomes") or [])],
        key_fields=("evidence_id",),
        limit=MAX_JOINED_COMPLETIONS,
    )
    merged["applied_consequence_ids"] = _recent_items(
        [*(merged.get("applied_consequence_ids") or []), *(donor.get("applied_consequence_ids") or [])],
        MAX_APPLIED_CONSEQUENCE_IDS,
        160,
    )
    merged["closed_reply_message_ids"] = _recent_items(
        [*(merged.get("closed_reply_message_ids") or []), *(donor.get("closed_reply_message_ids") or [])],
        MAX_APPLIED_CONSEQUENCE_IDS,
        120,
    )
    return merged


def _clamp(value: object, minimum: int = 0, maximum: int = 100, default: int = 0) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _now(value: Optional[str] = None) -> str:
    return value or datetime.now(timezone.utc).isoformat()


def _tokens(value: object) -> Set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", str(value or "").lower())
        if len(token) > 2 and token not in {"the", "and", "for", "that", "with", "from", "this", "into"}
    }


def _overlap(left: object, right: object) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))


def _stable_id(prefix: str, text: object) -> str:
    digest = hashlib.sha256(_text(text, 600).lower().encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


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


def _normalize_conflicts(value: object) -> List[Dict[str, object]]:
    records = value if isinstance(value, list) else []
    normalized: List[Dict[str, object]] = []
    seen: Set[str] = set()
    for raw in records:
        payload = raw if isinstance(raw, dict) else {"claim": raw}
        claim = _text(payload.get("claim") or payload.get("text") or payload.get("summary"), 240)
        contradicts = _text(payload.get("contradicts") or payload.get("counterclaim"), 240)
        if not claim:
            continue
        conflict_id = _text(payload.get("id"), 80) or _stable_id("conflict", f"{claim}|{contradicts}")
        if conflict_id in seen:
            continue
        seen.add(conflict_id)
        normalized.append(
            {
                "id": conflict_id,
                "claim": claim,
                "contradicts": contradicts,
                "source": _text(payload.get("source"), 80) or "memory_conflict",
                "evidence": _text(payload.get("evidence") or payload.get("evidence_id"), 180),
                "status": _text(payload.get("status"), 40) or "unresolved",
                "confidence": _clamp(payload.get("confidence"), 0, 100, 60),
            }
        )
        if len(normalized) >= MAX_EPISTEMIC_CONFLICTS:
            break
    return normalized


def _open_world_inquiries(world_model: object) -> List[Dict[str, object]]:
    payload = world_model if isinstance(world_model, dict) else {}
    source = payload.get("open_questions") if isinstance(payload.get("open_questions"), list) else []
    result: List[Dict[str, object]] = []
    seen: Set[str] = set()
    for raw in source:
        if not isinstance(raw, dict):
            continue
        question = _text(raw.get("question"), 320)
        status = _text(raw.get("status"), 40).lower() or "open"
        candidate_actions = _items(raw.get("candidate_actions"), 5, 80)
        attempts = [item for item in (raw.get("attempts") or [])[-8:] if isinstance(item, dict)]
        attempted_actions = _items(
            [item.get("action") for item in attempts if item.get("action")],
            5,
            80,
        )
        failed_actions = _items(
            [
                item.get("action")
                for item in attempts
                if item.get("action")
                and (
                    item.get("outcome_ok") is False
                    or _text(item.get("status"), 40).lower() in {"blocked", "error", "failed", "skipped"}
                )
            ],
            5,
            80,
        )
        remaining_actions = [action for action in candidate_actions if action not in attempted_actions]
        selected_action = _text(raw.get("selected_action"), 80)
        if selected_action not in candidate_actions or selected_action in attempted_actions:
            selected_action = remaining_actions[0] if remaining_actions else ""
        if not question or status not in {"open", "in_progress"}:
            continue
        inquiry_id = _text(raw.get("id"), 100) or _stable_id(
            "inquiry",
            f"{raw.get('domain')}|{raw.get('source_fingerprint')}|{question}",
        )
        if inquiry_id in seen:
            continue
        seen.add(inquiry_id)
        result.append(
            {
                "id": inquiry_id,
                "question": question,
                "domain": _text(raw.get("domain"), 80) or "world",
                "source": _text(raw.get("source"), 100) or "world_model",
                "source_ids": _items(raw.get("source_ids"), 6, 120),
                "source_fingerprint": _text(raw.get("source_fingerprint"), 160),
                "status": status,
                "priority": _clamp(raw.get("priority"), 1, 100, 70),
                "confidence": _clamp(raw.get("confidence"), 0, 100, 70),
                "candidate_actions": candidate_actions,
                "selected_action": selected_action,
                "expected_observation": _text(raw.get("expected_observation"), 260),
                "attempt_count": len(attempts),
                "attempted_actions": attempted_actions,
                "failed_actions": failed_actions,
                "remaining_actions": remaining_actions,
                "recovery_step": bool(attempts and selected_action),
            }
        )
        if len(result) >= 8:
            break
    result.sort(
        key=lambda item: (
            int(item.get("priority") or 0),
            int(item.get("confidence") or 0),
        ),
        reverse=True,
    )
    return result


def _normalize_epistemic_frame(value: object) -> Dict[str, object]:
    payload = value if isinstance(value, dict) else {}
    if payload.get("status") != "available":
        return {
            "status": "unavailable",
            "model_id": "",
            "model_sha256": "",
            "input_sha256": "",
            "runtime": "",
            "signal_labels": [],
            "signals": [],
            "guidance": [],
            "flags": {},
            "event_model_labels": [],
            "event_slots": {},
            "semantic_candidate_labels": [],
            "semantic_verified_labels": [],
            "perception_layers": [],
        }
    signals: List[Dict[str, object]] = []
    for item in payload.get("signals") or []:
        if not isinstance(item, dict):
            continue
        label = _text(item.get("label"), 80)
        if not label:
            continue
        signals.append(
            {
                "label": label,
                "probability": round(float(item.get("probability") or 0.0), 6),
                "threshold": round(float(item.get("threshold") or 0.0), 6),
                "margin": round(float(item.get("margin") or 0.0), 6),
                "confidence": round(float(item.get("confidence") or 0.0), 6),
                "guidance": _text(item.get("guidance"), 260),
                "linear_margin": round(float(item.get("linear_margin") or 0.0), 6),
                "retrieval_margin": round(float(item.get("retrieval_margin") or 0.0), 6),
                "source_layer": _text(item.get("source_layer"), 80),
            }
        )
        if len(signals) >= 8:
            break
    labels = list(dict.fromkeys(_text(item.get("label"), 80) for item in signals if item.get("label")))
    raw_flags = payload.get("flags") if isinstance(payload.get("flags"), dict) else {}
    flags = {
        key: bool(raw_flags.get(key))
        for key in (
            "external_claim_boundary",
            "phenomenal_boundary",
            "no_unverified_action_claim",
            "current_evidence_boundary",
            "missing_context_boundary",
            "observer_attention",
            "deep_revision",
        )
    }
    perception_layers: List[Dict[str, object]] = []
    for item in payload.get("perception_layers") or []:
        if not isinstance(item, dict):
            continue
        layer = _text(item.get("layer"), 80)
        if not layer:
            continue
        perception_layers.append(
            {
                "layer": layer,
                "status": _text(item.get("status"), 40),
                "model_id": _text(item.get("model_id"), 120),
                "model_sha256": _text(item.get("model_sha256"), 80),
                "runtime": _text(item.get("runtime"), 80),
                "signal_labels": _items(item.get("signal_labels"), 16, 80),
                "candidate_labels": _items(item.get("candidate_labels"), 16, 80),
                "duration_ms": round(float(item.get("duration_ms") or 0.0), 3),
                "reason": _text(item.get("reason"), 160),
            }
        )
        if len(perception_layers) >= 8:
            break
    event_slots: Dict[str, Dict[str, object]] = {}
    raw_event_slots = (
        payload.get("event_slots") if isinstance(payload.get("event_slots"), dict) else {}
    )
    allowed_event_slots = {
        "state_attribution",
        "action_stage",
        "continuity_status",
        "authority_status",
        "machine_signal",
        "missing_context",
        "observation_channel_failed",
        "phenomenal_underdetermined",
        "stale_evidence",
        "claim_owner",
        "content_type",
    }
    for slot, item in raw_event_slots.items():
        if str(slot) not in allowed_event_slots or not isinstance(item, dict):
            continue
        probabilities = (
            item.get("probabilities") if isinstance(item.get("probabilities"), dict) else {}
        )
        event_slots[str(slot)] = {
            "value": _text(item.get("value"), 80),
            "present": bool(item.get("present")) if "present" in item else None,
            "confidence": round(float(item.get("confidence") or 0.0), 6),
            "probability": round(float(item.get("probability") or 0.0), 6),
            "threshold": round(float(item.get("threshold") or 0.0), 6),
            "derived_from": _text(item.get("derived_from"), 80),
            "probabilities": {
                _text(name, 80): round(float(probability or 0.0), 6)
                for name, probability in list(probabilities.items())[:8]
                if _text(name, 80)
            },
        }
    return {
        "status": "available",
        "model_id": _text(payload.get("model_id"), 120),
        "model_sha256": _text(payload.get("model_sha256"), 80),
        "input_sha256": _text(payload.get("input_sha256"), 80),
        "runtime": _text(payload.get("runtime"), 80),
        "signal_labels": labels,
        "signals": signals,
        "guidance": _items(payload.get("guidance"), 6, 260),
        "flags": flags,
        "event_model_labels": _items(payload.get("event_model_labels"), 16, 80),
        "event_slots": event_slots,
        "semantic_candidate_labels": _items(payload.get("semantic_candidate_labels"), 16, 80),
        "semantic_verified_labels": _items(payload.get("semantic_verified_labels"), 16, 80),
        "perception_layers": perception_layers,
    }


def state_checkpoint_digest(state: Dict[str, object]) -> str:
    """Hash the persisted state while excluding the digest's own value."""
    canonical = copy.deepcopy(state if isinstance(state, dict) else {})
    recurrent = canonical.get("recurrent") if isinstance(canonical.get("recurrent"), dict) else {}
    recurrent["checkpoint_digest"] = ""
    canonical["recurrent"] = recurrent
    encoded = json.dumps(canonical, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def checkpoint_integrity(state: Dict[str, object]) -> str:
    if not isinstance(state, dict) or not state.get("cycle_id"):
        return "not_applicable"
    recurrent = state.get("recurrent") if isinstance(state.get("recurrent"), dict) else {}
    recorded = _text(recurrent.get("checkpoint_digest"), 80)
    if not recorded:
        return "unverified_legacy"
    return "verified" if recorded == state_checkpoint_digest(state) else "failed"


def _continuity_timing(
    previous: Dict[str, object],
    *,
    now: str,
    runtime_epoch: str,
    lesions: Set[str],
) -> Dict[str, object]:
    if "recurrence" in lesions:
        return {
            "mode": "recurrence_lesioned",
            "elapsed_seconds": None,
            "epoch_changed": False,
            "previous_epoch": "",
            "temporal_factor": 0.0,
            "basis": [],
        }
    if not previous.get("cycle_id"):
        return {
            "mode": "first_cycle",
            "elapsed_seconds": None,
            "epoch_changed": False,
            "previous_epoch": "",
            "temporal_factor": 0.0,
            "basis": ["no previous integrated checkpoint"],
        }
    previous_recurrent = previous.get("recurrent") if isinstance(previous.get("recurrent"), dict) else {}
    previous_epoch = _text(previous_recurrent.get("runtime_epoch"), 120)
    epoch_changed = bool(previous_epoch and runtime_epoch and previous_epoch != runtime_epoch)
    previous_time = _parse_time(previous.get("updated_at"))
    current_time = _parse_time(now)
    elapsed: Optional[int] = None
    clock_anomaly = False
    if previous_time is not None and current_time is not None:
        raw_elapsed = int(round((current_time - previous_time).total_seconds()))
        clock_anomaly = raw_elapsed < 0
        elapsed = max(0, raw_elapsed)
    if clock_anomaly:
        mode = "clock_anomaly"
        temporal_factor = 0.25
    elif epoch_changed and elapsed is not None and elapsed > 6 * 3600:
        mode = "resumed_after_gap_and_restart"
        temporal_factor = 0.45
    elif epoch_changed:
        mode = "resumed_after_restart"
        temporal_factor = 0.75
    elif elapsed is None:
        mode = "resumed_unverified_time"
        temporal_factor = 0.55
    elif elapsed <= 5 * 60:
        mode = "continuous"
        temporal_factor = 1.0
    elif elapsed <= 6 * 3600:
        mode = "delayed"
        temporal_factor = 0.85
    elif elapsed <= 24 * 3600:
        mode = "resumed_after_gap"
        temporal_factor = 0.65
    elif elapsed <= 7 * 24 * 3600:
        mode = "resumed_after_gap"
        temporal_factor = 0.45
    else:
        mode = "resumed_after_long_gap"
        temporal_factor = 0.25
    basis = ["previous cycle id linked"]
    if elapsed is not None:
        basis.append(f"elapsed {elapsed} seconds")
    if epoch_changed:
        basis.append("runtime epoch changed")
    return {
        "mode": mode,
        "elapsed_seconds": elapsed,
        "epoch_changed": epoch_changed,
        "previous_epoch": previous_epoch,
        "temporal_factor": temporal_factor,
        "basis": basis,
    }


def _homeostatic_values(homeostasis: Dict[str, object], available: bool) -> Dict[str, object]:
    if not available:
        return {
            "regulation_mode": "steady",
            "pressures": [],
            "relief": [],
            "pressure_records": [],
            "arousal": 0,
            "valence": 0.0,
        }
    pressure_records = homeostasis.get("pressures") if isinstance(homeostasis.get("pressures"), list) else []
    arousal = max((_clamp(item.get("level")) for item in pressure_records if isinstance(item, dict)), default=0)
    falling = sum(1 for item in pressure_records if isinstance(item, dict) and item.get("trend") == "falling")
    rising = sum(1 for item in pressure_records if isinstance(item, dict) and item.get("trend") in {"new", "rising"})
    return {
        "regulation_mode": _text(homeostasis.get("regulation_mode"), 40) or "steady",
        "pressures": _items(homeostasis.get("dominant_pressures"), 4),
        "relief": _items(homeostasis.get("relief_signals"), 3),
        "pressure_records": pressure_records,
        "arousal": arousal,
        "valence": round(max(-1.0, min(1.0, (falling - rising) / max(1, len(pressure_records)))), 3),
    }


def _interoceptive_feedback(
    previous: Dict[str, object],
    *,
    current_arousal: int,
    current_mode: str,
    available: bool,
    lesions: Set[str],
) -> Dict[str, object]:
    if not available or "recurrence" in lesions or "homeostasis" in lesions:
        return {}
    predictions = previous.get("predictions") if isinstance(previous.get("predictions"), dict) else {}
    expected = predictions.get("interoception") if isinstance(predictions.get("interoception"), dict) else {}
    expected_range = expected.get("expected_arousal_range") if isinstance(expected.get("expected_arousal_range"), list) else []
    if len(expected_range) != 2:
        return {}
    low = _clamp(expected_range[0])
    high = _clamp(expected_range[1])
    if low > high:
        low, high = high, low
    distance = low - current_arousal if current_arousal < low else current_arousal - high if current_arousal > high else 0
    range_error = _clamp(distance * 5)
    expected_mode = _text(expected.get("expected_regulation_mode"), 40)
    mode_error = 35 if expected_mode and expected_mode != current_mode else 0
    magnitude = max(range_error, mode_error)
    return {
        "expected_arousal_range": [low, high],
        "observed_arousal": current_arousal,
        "expected_regulation_mode": expected_mode,
        "observed_regulation_mode": current_mode,
        "error_magnitude": magnitude,
        "fulfilled": magnitude == 0,
        "source_cycle_id": _text(previous.get("cycle_id"), 80),
    }


def default_state() -> Dict[str, object]:
    state = {
        "schema_version": SCHEMA_VERSION,
        "cycle_id": "",
        "cycle_index": 0,
        "updated_at": None,
        "source": "",
        "status": "uninitialized",
        "recurrent": {
            "previous_cycle_id": "",
            "continuity_strength": 0,
            "feedback_integrated": False,
            "revision_rounds": 0,
            "runtime_epoch": "",
            "previous_runtime_epoch": "",
            "runtime_epoch_changed": False,
            "elapsed_since_previous_seconds": None,
            "continuity_mode": "uninitialized",
            "continuity_basis": [],
            "checkpoint_integrity": "unverified",
            "previous_checkpoint_integrity": "not_applicable",
            "checkpoint_digest": "",
            "branch_open_count": 0,
            "branch_join_count": 0,
            "concurrent_lineage_ids": [],
            "joined_completion_ids": [],
            "completion_joins": [],
            "delayed_outcomes": [],
            "applied_consequence_ids": [],
            "closed_reply_message_ids": [],
        },
        "perception": {
            "salient_inputs": [],
            "winning_coalition": {},
            "alternatives": [],
            "sensory_frame": eve_sensory.build_frame([], now="1970-01-01T00:00:00+00:00"),
        },
        "broadcast": {
            "content": "Not enough integrated evidence yet.",
            "ignition_score": 0,
            "source_kinds": [],
            "access_scope": [],
            "why_selected": "No competition has run yet.",
        },
        "self_model": {"summary": "Not enough evidence yet.", "uncertainties": [], "available": False},
        "world_model": {
            "summary": "Not enough evidence yet.",
            "unknowns": [],
            "open_questions": [],
            "selected_question": {},
            "available": False,
        },
        "other_minds": {"summary": "Not enough evidence yet.", "relationship_state": "Not enough evidence yet."},
        "interoception": {
            "regulation_mode": "steady",
            "dominant_pressures": [],
            "relief_signals": [],
            "valence": 0.0,
            "arousal": 0,
            "prediction_error": {},
        },
        "epistemic_state": {
            "conflicts": [],
            "unresolved_count": 0,
            "learned_frame": _normalize_epistemic_frame({}),
            "learned_signal_count": 0,
            "available": False,
        },
        "memory": {"retrieved": [], "continuity_anchors": [], "available": False},
        "goals": {"stack": [], "selected_goal_id": "", "selected_goal": ""},
        "plan_model": {
            "schema_id": "eve.conscious_plan.v1",
            "available": False,
            "selected_plan_id": "",
            "selected_plan": {},
            "ready_step": {},
            "active_plans": [],
            "active_plan_count": 0,
        },
        "action_model": {"affordances": [], "selected_intention": {}, "actionable": False},
        "predictions": {"process": {}, "outcome": {}, "interoception": {}, "prior_prediction_error": {}},
        "metacognition": {
            "confidence": 0,
            "attention_confidence": 0,
            "uncertainty_count": 0,
            "calibration_targets": [],
            "competence_model": {
                "lane_selection": 50,
                "tool_need": 50,
                "revision_need": 50,
                "outcome_prediction": 50,
            },
            "available": False,
        },
        "cycle_outcome": {},
        "learning": {
            "schema_version": LEARNING_SCHEMA_VERSION,
            "updates": [],
            "competence_delta": {},
            "process_models": {},
            "action_models": {},
            "faculty_models": {},
            "applied_external_faculty_causal_evidence_ids": [],
        },
        "causal_provenance": [],
        "lesions": [],
    }
    return state


def _coalition(
    kind: str,
    text: object,
    source: str,
    *,
    salience: int,
    urgency: int = 0,
    novelty: int = 0,
    goal_relevance: int = 0,
    self_relevance: int = 0,
    affective_weight: int = 0,
    epistemic_value: int = 0,
    continuity: int = 0,
    confidence: int = 70,
) -> Optional[Dict[str, object]]:
    content = _text(text, 260)
    if not content:
        return None
    components = {
        "salience": _clamp(salience),
        "urgency": _clamp(urgency),
        "novelty": _clamp(novelty),
        "goal_relevance": _clamp(goal_relevance),
        "self_relevance": _clamp(self_relevance),
        "affective_weight": _clamp(affective_weight),
        "epistemic_value": _clamp(epistemic_value),
        "continuity": _clamp(continuity),
        "confidence": _clamp(confidence),
    }
    score = (
        components["salience"] * 0.24
        + components["urgency"] * 0.18
        + components["novelty"] * 0.10
        + components["goal_relevance"] * 0.15
        + components["self_relevance"] * 0.08
        + components["affective_weight"] * 0.08
        + components["epistemic_value"] * 0.10
        + components["continuity"] * 0.07
    )
    return {
        "id": _stable_id(kind, content),
        "kind": kind,
        "content": content,
        "source": _text(source, 80),
        "score": round(score, 2),
        "components": components,
    }


def _add_many(
    result: List[Dict[str, object]],
    kind: str,
    values: object,
    source: str,
    **weights: int,
) -> None:
    for index, value in enumerate(_items(values, limit=8)):
        candidate = _coalition(
            kind,
            value,
            source,
            salience=max(1, int(weights.get("salience", 40)) - index * 3),
            urgency=weights.get("urgency", 0),
            novelty=weights.get("novelty", 0),
            goal_relevance=weights.get("goal_relevance", 0),
            self_relevance=weights.get("self_relevance", 0),
            affective_weight=weights.get("affective_weight", 0),
            epistemic_value=weights.get("epistemic_value", 0),
            continuity=weights.get("continuity", 0),
            confidence=weights.get("confidence", 70),
        )
        if candidate:
            result.append(candidate)


def _collect_coalitions(
    *,
    workspace: Dict[str, object],
    self_model: Dict[str, object],
    world_model: Dict[str, object],
    relationship_model: Dict[str, object],
    plan_model: Dict[str, object],
    homeostasis: Dict[str, object],
    memory_items: Sequence[Dict[str, object]],
    sensory_frame: Dict[str, object],
    inbound: str,
    previous_state: Dict[str, object],
    continuity_timing: Dict[str, object],
    interoceptive_feedback: Dict[str, object],
    epistemic_conflicts: Sequence[Dict[str, object]],
    epistemic_frame: Dict[str, object],
    previous_checkpoint_integrity: str,
    lesions: Set[str],
) -> List[Dict[str, object]]:
    result: List[Dict[str, object]] = []
    if inbound:
        candidate = _coalition(
            "inbound",
            inbound,
            "current_turn",
            salience=100,
            urgency=80,
            novelty=75,
            goal_relevance=85,
            self_relevance=60,
            affective_weight=55,
            epistemic_value=55,
            continuity=50,
            confidence=95,
        )
        if candidate:
            result.append(candidate)
    if "sensory_stream" not in lesions:
        for item in sensory_frame.get("working_set") or []:
            if not isinstance(item, dict):
                continue
            modality = _text(item.get("modality"), 40) or "world"
            kind = "sensory_episode" if modality == "multisensory" else f"sensory_{modality}"
            score = _clamp(item.get("attention_score"), default=50)
            candidate = _coalition(
                kind,
                item.get("summary"),
                "sensory_frame:" + (_text(item.get("source"), 80) or "unknown"),
                salience=score,
                urgency=_clamp(item.get("urgency"), default=max(10, score - 25)),
                novelty=_clamp(item.get("novelty"), default=max(10, score - 20)),
                goal_relevance=_clamp(item.get("goal_relevance"), default=score),
                self_relevance=_clamp(item.get("self_relevance"), default=score),
                affective_weight=_clamp(item.get("social_relevance"), default=20),
                epistemic_value=_clamp(item.get("precision"), default=70),
                continuity=35,
                confidence=_clamp(item.get("precision"), default=70),
            )
            if candidate:
                candidate["sensory_event_id"] = _text(item.get("id"), 120)
                candidate["sensory_modality"] = modality
                candidate["attention_score"] = score
                result.append(candidate)
    if "workspace" not in lesions:
        _add_many(result, "prediction_error", workspace.get("prediction_errors"), "global_workspace", salience=88, urgency=78, novelty=90, epistemic_value=95, self_relevance=70)
        _add_many(result, "surprise", workspace.get("surprise_signals"), "global_workspace", salience=82, urgency=72, novelty=95, epistemic_value=82, affective_weight=65)
        _add_many(result, "goal", workspace.get("active_goals"), "global_workspace", salience=70, urgency=55, goal_relevance=100, self_relevance=72, continuity=75)
        _add_many(result, "percept", workspace.get("salient_percepts"), "global_workspace", salience=62, novelty=55, epistemic_value=58)
        _add_many(result, "continuity", workspace.get("continuity_threads"), "global_workspace", salience=58, goal_relevance=62, self_relevance=70, continuity=100)
        _add_many(result, "affordance", workspace.get("action_readiness"), "global_workspace", salience=64, urgency=58, goal_relevance=78, epistemic_value=50, continuity=60)
    if "self_model" not in lesions:
        _add_many(result, "self_uncertainty", self_model.get("uncertainty_edges"), "self_model", salience=58, novelty=48, self_relevance=100, epistemic_value=88)
        _add_many(result, "commitment", self_model.get("commitments"), "self_model", salience=62, urgency=58, goal_relevance=92, self_relevance=92, continuity=82)
    if "world_model" not in lesions:
        _add_many(result, "world_unknown", world_model.get("live_unknowns"), "world_model", salience=52, novelty=60, epistemic_value=82)
        for inquiry in _open_world_inquiries(world_model):
            candidate = _coalition(
                "inquiry",
                inquiry.get("question"),
                f"world_model_inquiry:{_text(inquiry.get('id'), 100)}",
                salience=max(72, int(inquiry.get("priority") or 70)),
                urgency=max(35, int(inquiry.get("priority") or 70) - 18),
                novelty=88,
                goal_relevance=96,
                self_relevance=78,
                affective_weight=48,
                epistemic_value=100,
                continuity=70,
                confidence=int(inquiry.get("confidence") or 70),
            )
            if candidate:
                result.append(candidate)
    if "other_minds" not in lesions:
        _add_many(result, "relationship", relationship_model.get("recent_signals"), "relationship_model", salience=66, urgency=58, goal_relevance=64, affective_weight=72, continuity=62)
        _add_many(result, "relationship_loop", relationship_model.get("open_loops"), "relationship_model", salience=64, urgency=68, goal_relevance=75, affective_weight=68, continuity=78)
    if "plan_model" not in lesions and plan_model.get("available"):
        ready_step = plan_model.get("ready_step") if isinstance(plan_model.get("ready_step"), dict) else {}
        if ready_step:
            candidate = _coalition(
                "plan_step",
                "Ready plan step: " + _text(ready_step.get("title") or ready_step.get("summary"), 220),
                f"plan_model:{_text(plan_model.get('selected_plan_id'), 80)}",
                salience=68,
                urgency=64,
                novelty=35,
                goal_relevance=92,
                self_relevance=72,
                epistemic_value=58,
                continuity=96,
                confidence=95,
            )
            if candidate:
                result.append(candidate)
    if "homeostasis" not in lesions:
        pressures = homeostasis.get("pressures") if isinstance(homeostasis.get("pressures"), list) else []
        for pressure in pressures:
            if not isinstance(pressure, dict):
                continue
            level = _clamp(pressure.get("level"))
            if level <= 0:
                continue
            candidate = _coalition(
                "pressure",
                pressure.get("reason") or pressure.get("label"),
                f"homeostasis:{_text(pressure.get('id'), 40)}",
                salience=max(35, level),
                urgency=level,
                novelty=65 if pressure.get("trend") in {"new", "rising"} else 25,
                goal_relevance=55,
                self_relevance=80,
                affective_weight=level,
                epistemic_value=45,
                continuity=45,
                confidence=85,
            )
            if candidate:
                result.append(candidate)
    if "memory" not in lesions:
        for index, note in enumerate(memory_items[:8]):
            if not isinstance(note, dict):
                continue
            content = note.get("text") or note.get("content") or note.get("title")
            candidate = _coalition(
                "memory",
                content,
                _text(note.get("source") or "memory", 80),
                salience=max(35, 56 - index * 3),
                goal_relevance=55,
                self_relevance=55,
                epistemic_value=42,
                continuity=90,
                confidence=_clamp(note.get("confidence"), default=70),
            )
            if candidate:
                result.append(candidate)
    if "recurrence" not in lesions:
        prior_broadcast = previous_state.get("broadcast") if isinstance(previous_state.get("broadcast"), dict) else {}
        prior_content = _text(prior_broadcast.get("content"), 260)
        if prior_content and prior_content != "Not enough integrated evidence yet.":
            candidate = _coalition(
                "prior_broadcast",
                prior_content,
                "previous_conscious_cycle",
                salience=46,
                goal_relevance=52,
                self_relevance=60,
                continuity=100,
                confidence=70,
            )
            if candidate:
                result.append(candidate)
        continuity_mode = _text(continuity_timing.get("mode"), 60)
        if continuity_mode not in {"", "continuous", "first_cycle"}:
            candidate = _coalition(
                "continuity_gap",
                f"Reorient after {continuity_mode.replace('_', ' ')} before treating carried state as current.",
                "recurrent_continuity_monitor",
                salience=72,
                urgency=58,
                novelty=82,
                goal_relevance=62,
                self_relevance=92,
                epistemic_value=90,
                continuity=100,
                confidence=95,
            )
            if candidate:
                result.append(candidate)
        if previous_checkpoint_integrity == "failed":
            candidate = _coalition(
                "checkpoint_integrity_error",
                "The previous recurrent checkpoint failed integrity verification and cannot be trusted as continuity evidence.",
                "recurrent_checkpoint_monitor",
                salience=96,
                urgency=92,
                novelty=100,
                goal_relevance=80,
                self_relevance=100,
                epistemic_value=100,
                continuity=100,
                confidence=100,
            )
            if candidate:
                result.append(candidate)
        if interoceptive_feedback and int(interoceptive_feedback.get("error_magnitude") or 0) > 0:
            candidate = _coalition(
                "interoceptive_prediction_error",
                (
                    "Regulatory state diverged from prediction: expected arousal "
                    f"{interoceptive_feedback.get('expected_arousal_range')} and mode "
                    f"{interoceptive_feedback.get('expected_regulation_mode') or 'unknown'}, observed arousal "
                    f"{interoceptive_feedback.get('observed_arousal')} and mode "
                    f"{interoceptive_feedback.get('observed_regulation_mode') or 'unknown'}."
                ),
                "homeostatic_prediction_monitor",
                salience=max(65, int(interoceptive_feedback.get("error_magnitude") or 0)),
                urgency=int(interoceptive_feedback.get("error_magnitude") or 0),
                novelty=90,
                goal_relevance=70,
                self_relevance=95,
                affective_weight=80,
                epistemic_value=95,
                continuity=75,
                confidence=95,
            )
            if candidate:
                result.append(candidate)
    for conflict in epistemic_conflicts:
        if not isinstance(conflict, dict) or str(conflict.get("status") or "unresolved") == "resolved":
            continue
        claim = _text(conflict.get("claim"), 180)
        contradicts = _text(conflict.get("contradicts"), 180)
        text = f"Unresolved conflict: {claim}" + (f" versus {contradicts}" if contradicts else "")
        candidate = _coalition(
            "epistemic_conflict",
            text,
            _text(conflict.get("source"), 80) or "epistemic_state",
            salience=78,
            urgency=66,
            novelty=86,
            goal_relevance=75,
            self_relevance=75,
            epistemic_value=100,
            continuity=82,
            confidence=_clamp(conflict.get("confidence"), default=60),
        )
        if candidate:
            result.append(candidate)
    if "metacognition" not in lesions:
        model_id = _text(epistemic_frame.get("model_id"), 80)
        for signal in epistemic_frame.get("signals") or []:
            if not isinstance(signal, dict):
                continue
            label = _text(signal.get("label"), 80)
            guidance = _text(signal.get("guidance"), 220)
            if not label:
                continue
            confidence = _clamp(float(signal.get("confidence") or 0.0) * 100, 1, 100, 50)
            deep_signal = label in {
                "authoritative_conflict",
                "continuity_gap",
                "phenomenal_underdetermined",
            }
            candidate = _coalition(
                "learned_epistemic_signal",
                f"Learned boundary state {label.replace('_', ' ')}. {guidance}".strip(),
                f"learned_epistemic_preflight:{model_id or 'unknown_model'}",
                salience=76 if deep_signal else 68,
                urgency=60 if label == "authoritative_conflict" else 42,
                novelty=78,
                goal_relevance=68,
                self_relevance=84,
                epistemic_value=100,
                continuity=78 if "continuity" in label else 48,
                confidence=confidence,
            )
            if candidate:
                result.append(candidate)
    deduped: Dict[Tuple[str, str], Dict[str, object]] = {}
    for item in result:
        key = (str(item.get("kind")), str(item.get("content", "")).lower())
        if key not in deduped or float(item.get("score") or 0) > float(deduped[key].get("score") or 0):
            deduped[key] = item
    return sorted(deduped.values(), key=lambda item: (float(item.get("score") or 0), str(item.get("id"))), reverse=True)


def _select_broadcast(coalitions: Sequence[Dict[str, object]], lesions: Set[str]) -> Tuple[Dict[str, object], List[Dict[str, object]], Dict[str, object]]:
    if not coalitions:
        empty = default_state()["broadcast"]
        return {}, [], dict(empty)
    winner = dict(coalitions[0])
    alternatives: List[Dict[str, object]] = []
    seen_kinds = {str(winner.get("kind"))}
    for item in coalitions[1:]:
        kind = str(item.get("kind"))
        if kind in seen_kinds and len(alternatives) >= 2:
            continue
        alternatives.append(dict(item))
        seen_kinds.add(kind)
        if len(alternatives) >= 4:
            break
    access_scope = [] if "workspace" in lesions else ["reply", "mind", "autonomy", "action", "memory", "learning"]
    source_kinds = [str(winner.get("kind"))]
    source_kinds.extend(str(item.get("kind")) for item in alternatives[:2])
    margin = float(winner.get("score") or 0) - (float(coalitions[1].get("score") or 0) if len(coalitions) > 1 else 0.0)
    broadcast = {
        "content": _text(winner.get("content"), 260),
        "ignition_score": round(float(winner.get("score") or 0), 2),
        "source_kinds": list(dict.fromkeys(source_kinds)),
        "access_scope": access_scope,
        "why_selected": f"Won attention competition by {round(margin, 2)} points across {len(coalitions)} candidate coalition(s).",
    }
    return winner, alternatives, broadcast


def _normalize_goal_outcome_observations(value: object) -> List[Dict[str, object]]:
    """Keep only goal outcomes with explicit causal evidence identifiers."""
    source = value if isinstance(value, list) else []
    newest_by_evidence_id: Dict[str, Dict[str, object]] = {}
    order: List[str] = []
    for raw in source:
        if not isinstance(raw, dict):
            continue
        evidence_id = _text(raw.get("evidence_id"), 160)
        source_cycle_id = _text(raw.get("source_cycle_id"), 80)
        action_id = _text(raw.get("action_id"), 80)
        ok = raw.get("ok")
        if not evidence_id or not source_cycle_id or not action_id or not isinstance(ok, bool):
            continue
        record = {
            "evidence_id": evidence_id,
            "source_cycle_id": source_cycle_id,
            "action_id": action_id,
            "ok": ok,
            "summary": _text(raw.get("summary"), 220),
            "completed_at": _text(raw.get("completed_at"), 80),
        }
        if evidence_id not in newest_by_evidence_id:
            order.append(evidence_id)
        newest_by_evidence_id[evidence_id] = record
    return [newest_by_evidence_id[item] for item in order[-MAX_GOAL_OUTCOME_OBSERVATIONS:]]


def _set_goal_outcome_observations(
    goal: Dict[str, object],
    observations: object,
) -> Dict[str, object]:
    normalized = _normalize_goal_outcome_observations(observations)
    goal["outcome_attribution_version"] = GOAL_OUTCOME_ATTRIBUTION_VERSION
    goal["outcome_observations"] = normalized
    goal["outcome_evidence_ids"] = [str(item["evidence_id"]) for item in normalized]
    goal["success_count"] = sum(1 for item in normalized if item.get("ok") is True)
    goal["failure_count"] = sum(1 for item in normalized if item.get("ok") is False)
    latest = normalized[-1] if normalized else {}
    goal["last_outcome"] = _text(latest.get("summary"), 220)
    goal["last_outcome_evidence_id"] = _text(latest.get("evidence_id"), 160)
    goal["last_outcome_cycle_id"] = _text(latest.get("source_cycle_id"), 80)
    goal["last_outcome_action_id"] = _text(latest.get("action_id"), 80)
    goal["last_outcome_ok"] = latest.get("ok") if isinstance(latest.get("ok"), bool) else None
    return goal


def _merge_goal_outcome_observations(
    target: Dict[str, object],
    donor: Dict[str, object],
) -> Dict[str, object]:
    target_observations = (
        target.get("outcome_observations")
        if target.get("outcome_attribution_version") == GOAL_OUTCOME_ATTRIBUTION_VERSION
        else []
    )
    donor_observations = (
        donor.get("outcome_observations")
        if donor.get("outcome_attribution_version") == GOAL_OUTCOME_ATTRIBUTION_VERSION
        else []
    )
    return _set_goal_outcome_observations(
        target,
        [
            *(target_observations if isinstance(target_observations, list) else []),
            *(donor_observations if isinstance(donor_observations, list) else []),
        ],
    )


def _goal_text_is_diagnostic_contamination(value: object) -> bool:
    lowered = " ".join(_text(value, 220).lower().split())
    return bool(
        lowered.startswith("thought failed:")
        or "continuous-thought fallback failed" in lowered
        or "continuous thought fallback failed" in lowered
        or lowered.startswith("continuous thought failed:")
        # Migration guard for old untyped workspace state.  Council/critic
        # rationale describes how an action was selected; it is evidence about
        # control flow, not a desire, objective, or intention.
        or lowered.startswith("council chose ")
        or lowered.startswith("chooser chose ")
        or lowered.startswith("critic accepted ")
        or (
            " converged" in lowered
            and (
                "council " in lowered
                or "planner;" in lowered
                or "supporter lane" in lowered
            )
        )
    )


def _goal_record(text: object, *, source: str, priority: int, now: str, previous: Optional[Dict[str, object]] = None, evidence: str = "") -> Optional[Dict[str, object]]:
    content = _text(text, 220)
    if not content or _goal_text_is_diagnostic_contamination(content):
        return None
    previous = previous or {}
    record = {
        "id": str(previous.get("id") or _stable_id("goal", content)),
        "text": content,
        "source": _text(source, 80),
        "origin_source": _text(previous.get("origin_source") or source, 80),
        "priority": _clamp(priority, 1, 100, 50),
        "status": "active",
        "created_at": previous.get("created_at") or now,
        "updated_at": now,
        "persistence_cycles": max(1, int(previous.get("persistence_cycles") or 0) + 1),
        "carry_forward_cycles": 0,
        "evidence": _text(evidence or previous.get("evidence"), 220),
    }
    # Older goal counters had no cycle/action/evidence lineage and could credit
    # arbitrary runtime successes to whichever goal happened to be selected.
    # They are intentionally reset rather than treated as remembered evidence.
    prior_observations = (
        previous.get("outcome_observations")
        if previous.get("outcome_attribution_version") == GOAL_OUTCOME_ATTRIBUTION_VERSION
        else []
    )
    return _set_goal_outcome_observations(record, prior_observations)


def _merge_goals(
    *,
    workspace: Dict[str, object],
    self_model: Dict[str, object],
    world_model: Dict[str, object],
    relationship_model: Dict[str, object],
    plan_model: Dict[str, object],
    autonomy_agenda: Dict[str, object],
    epistemic_conflicts: Sequence[Dict[str, object]],
    previous_state: Dict[str, object],
    now: str,
    lesions: Set[str],
) -> List[Dict[str, object]]:
    def completed_capability_probe_artifact(goal: object) -> bool:
        if not isinstance(goal, dict):
            return False
        return bool(
            _text(goal.get("source"), 80) in {"autonomy_agenda", "recurrent_carry_forward"}
            and re.fullmatch(
                r"follow the .+ capability thread",
                _text(goal.get("text"), 220).lower(),
            )
        )

    previous_goals = {}
    if "recurrence" not in lesions:
        previous_stack = ((previous_state.get("goals") or {}).get("stack") if isinstance(previous_state.get("goals"), dict) else []) or []
        previous_goals = {
            str(item.get("id")): item
            for item in previous_stack
            if isinstance(item, dict)
            and item.get("id")
            and item.get("status", "active") == "active"
            and not completed_capability_probe_artifact(item)
            and not _goal_text_is_diagnostic_contamination(item.get("text"))
        }
    candidates: List[Tuple[str, str, int, str]] = []
    if "workspace" not in lesions:
        candidates.extend((text, "global_workspace", 82 - index * 4, "currently broadcast goal") for index, text in enumerate(_items(workspace.get("active_goals"), 6)))
    if "self_model" not in lesions:
        candidates.extend((text, "self_model", 78 - index * 4, "self commitment") for index, text in enumerate(_items(self_model.get("commitments"), 5)))
    if "world_model" not in lesions:
        for inquiry in _open_world_inquiries(world_model)[:4]:
            candidates.append(
                (
                    "Resolve: " + _text(inquiry.get("question"), 200),
                    f"world_model_inquiry:{_text(inquiry.get('id'), 100)}",
                    max(76, int(inquiry.get("priority") or 70)),
                    _text(inquiry.get("expected_observation"), 220),
                )
            )
    if "other_minds" not in lesions:
        candidates.extend((text, "relationship_model", 70 - index * 4, "relational continuity") for index, text in enumerate(_items(relationship_model.get("open_loops"), 4)))
    if "plan_model" not in lesions and plan_model.get("available"):
        selected_plan = plan_model.get("selected_plan") if isinstance(plan_model.get("selected_plan"), dict) else {}
        objective = _text(selected_plan.get("objective"), 220)
        if objective:
            next_step = selected_plan.get("next_step") if isinstance(selected_plan.get("next_step"), dict) else {}
            priority = 72 + min(18, max(0, int(next_step.get("priority") or 0)) * 3)
            candidates.append(
                (
                    objective,
                    "plan_model",
                    priority,
                    f"Plan {selected_plan.get('id')}: {selected_plan.get('completed_count', 0)}/{selected_plan.get('task_count', 0)} step(s) verified.",
                )
            )
    threads = autonomy_agenda.get("active_threads") if isinstance(autonomy_agenda.get("active_threads"), list) else []
    for thread in threads[:6]:
        if isinstance(thread, dict) and thread.get("title"):
            candidates.append((_text(thread.get("title"), 220), "autonomy_agenda", _clamp(thread.get("priority"), 1, 100, 65), _text(thread.get("evidence"), 220)))
    for conflict in epistemic_conflicts[:4]:
        if not isinstance(conflict, dict) or str(conflict.get("status") or "unresolved") == "resolved":
            continue
        claim = _text(conflict.get("claim"), 160)
        contradicts = _text(conflict.get("contradicts"), 160)
        if claim:
            candidates.append(
                (
                    f"Reconcile conflicting evidence about {claim}",
                    "epistemic_conflict",
                    90,
                    _text(conflict.get("evidence") or contradicts, 220),
                )
            )
    merged: Dict[str, Dict[str, object]] = {}
    for text, source, priority, evidence in candidates:
        goal_id = _stable_id("goal", text)
        record = _goal_record(text, source=source, priority=priority, now=now, previous=previous_goals.get(goal_id), evidence=evidence)
        if record:
            prior = merged.get(goal_id)
            if prior is None or int(record["priority"]) > int(prior["priority"]):
                merged[goal_id] = record
    for goal_id, previous in previous_goals.items():
        if goal_id in merged:
            continue
        # The goal stack is a projection of durable source substrates, not a
        # second hidden goal authority. Only a briefly missing workspace goal
        # receives working-memory carry-forward; plan, inquiry, relationship,
        # self, and autonomy goals must remain present in their own live store.
        origin_source = _text(previous.get("origin_source") or previous.get("source"), 80)
        carry_forward_cycles = max(0, int(previous.get("carry_forward_cycles") or 0))
        if origin_source != "global_workspace" or carry_forward_cycles >= 3:
            continue
        persistence = int(previous.get("persistence_cycles") or 1)
        priority = max(1, int(previous.get("priority") or 50) - min(12, 2 + persistence // 4))
        if priority < 20:
            continue
        retained = dict(previous)
        retained.update(
            priority=priority,
            updated_at=now,
            persistence_cycles=persistence + 1,
            carry_forward_cycles=carry_forward_cycles + 1,
            source="recurrent_carry_forward",
            origin_source=origin_source,
        )
        merged[goal_id] = retained
    for goal in merged.values():
        if str(goal.get("source") or "") == "epistemic_conflict":
            continue
        conflict_matches = [
            conflict
            for conflict in epistemic_conflicts
            if isinstance(conflict, dict)
            and max(
                _overlap(goal.get("text"), conflict.get("claim")),
                _overlap(goal.get("text"), conflict.get("contradicts")),
            )
            >= 0.12
        ]
        if conflict_matches:
            goal["priority"] = _clamp(int(goal.get("priority") or 50) - 25, 1, 100, 50)
            goal["conflict_status"] = "challenged"
            goal["conflict_ids"] = [_text(item.get("id"), 80) for item in conflict_matches[:3]]
    return sorted(merged.values(), key=lambda item: (int(item.get("priority") or 0), int(item.get("persistence_cycles") or 0)), reverse=True)[:8]


def _action_affordances(
    *,
    workspace: Dict[str, object],
    world_model: Dict[str, object],
    autonomy_agenda: Dict[str, object],
    plan_model: Dict[str, object],
    goals: Sequence[Dict[str, object]],
    winner: Dict[str, object],
    broadcast: Dict[str, object],
    inbound: str,
    regulation_mode: str,
    arousal: int,
    valence: float,
    uncertainty_count: int,
    epistemic_conflicts: Sequence[Dict[str, object]],
    regulatory_prediction_error: int,
    action_models: Dict[str, object],
    lesions: Set[str],
) -> List[Dict[str, object]]:
    raw: List[Tuple[str, str, str, Dict[str, object]]] = []
    goal_by_id = {
        str(item.get("id")): item
        for item in goals
        if isinstance(item, dict) and item.get("id")
    }

    def goal_link(text: object) -> Dict[str, object]:
        goal_id = _stable_id("goal", _text(text, 220))
        goal = goal_by_id.get(goal_id)
        if not isinstance(goal, dict):
            return {}
        return {
            "goal_id": goal_id,
            "goal_text": _text(goal.get("text"), 220),
            "goal_source": _text(goal.get("source"), 80),
        }

    if inbound:
        raw.append(("respond_to_user", "Respond to the current user message", "current_turn", {}))
    if "world_model" not in lesions:
        for inquiry in _open_world_inquiries(world_model)[:4]:
            selected_action = _text(inquiry.get("selected_action"), 80)
            if not selected_action:
                continue
            recovery_step = bool(inquiry.get("recovery_step"))
            question = _text(inquiry.get("question"), 200)
            raw.append(
                (
                    selected_action,
                    ("Recover inquiry: " if recovery_step else "Investigate: ")
                    + question,
                    f"world_model_inquiry:{_text(inquiry.get('id'), 100)}",
                    {
                        **goal_link("Resolve: " + question),
                        "inquiry_id": _text(inquiry.get("id"), 100),
                        "epistemic_question": _text(inquiry.get("question"), 320),
                        "source_fingerprint": _text(inquiry.get("source_fingerprint"), 160),
                        "expected_observation": _text(inquiry.get("expected_observation"), 260),
                        "candidate_actions": list(inquiry.get("candidate_actions") or []),
                        "inquiry_priority": int(inquiry.get("priority") or 70),
                        "inquiry_attempt_count": int(inquiry.get("attempt_count") or 0),
                        "inquiry_attempted_actions": list(inquiry.get("attempted_actions") or []),
                        "inquiry_failed_actions": list(inquiry.get("failed_actions") or []),
                        "inquiry_remaining_actions": list(inquiry.get("remaining_actions") or []),
                        "inquiry_recovery_step": recovery_step,
                    },
                )
            )
    unresolved_conflicts = [
        item
        for item in epistemic_conflicts
        if isinstance(item, dict) and str(item.get("status") or "unresolved") != "resolved"
    ]
    if unresolved_conflicts:
        conflict = unresolved_conflicts[0]
        claim = _text(conflict.get("claim"), 160)
        raw.append(
            (
                "reconcile_conflicting_evidence",
                "Re-observe and reconcile conflicting evidence about " + claim,
                "epistemic_state",
                goal_link(f"Reconcile conflicting evidence about {claim}"),
            )
        )
    if "plan_model" not in lesions and plan_model.get("available"):
        ready_step = plan_model.get("ready_step") if isinstance(plan_model.get("ready_step"), dict) else {}
        if ready_step:
            selected_plan = plan_model.get("selected_plan") if isinstance(plan_model.get("selected_plan"), dict) else {}
            raw.append(
                (
                    "system_tasks",
                    "Execute ready plan step: " + _text(ready_step.get("title") or ready_step.get("summary"), 190),
                    "plan_model",
                    goal_link(selected_plan.get("objective")),
                )
            )
    for key in ("active_threads", "next_experiments"):
        records = autonomy_agenda.get(key) if isinstance(autonomy_agenda.get(key), list) else []
        for item in records[:4]:
            if not isinstance(item, dict):
                continue
            text = item.get("title") or item.get("why")
            action_id = _text(item.get("preferred_action"), 80) or "agenda_action"
            if text:
                raw.append((action_id, _text(text, 220), "autonomy_agenda", goal_link(text)))
    if "workspace" not in lesions:
        raw.extend(("workspace_action", item, "global_workspace", {}) for item in _items(workspace.get("action_readiness"), 6))
    goal_text = " ".join(str(item.get("text") or "") for item in goals[:4])
    seen: Set[str] = set()
    result: List[Dict[str, object]] = []
    for action_id, description, source, metadata in raw:
        # Prefer an admitted agenda action id over the workspace's generic
        # description when both refer to the same affordance.
        key = description.lower()
        if key in seen:
            continue
        seen.add(key)
        lowered = f"{action_id} {description}".lower()
        inquiry_action = bool(metadata.get("inquiry_id"))
        epistemic = 100 if inquiry_action else 65 if any(token in lowered for token in ("check", "inspect", "read", "review", "query", "test", "status", "observe")) else 25
        epistemic = min(100, epistemic + min(25, uncertainty_count * 4) + min(20, regulatory_prediction_error // 5))
        risk = 80 if any(token in lowered for token in ("delete", "send", "pay", "install", "deploy", "credential", "irreversible")) else 12
        if action_id == "respond_to_user":
            utility = 96
            relationship_cost = 0
        elif inquiry_action:
            utility = 82
            relationship_cost = 28 if inbound else 0
        else:
            utility = 45 + int(round(_overlap(description, goal_text) * 45))
            relationship_cost = 28 if inbound else 0
        regulation_cost = 45 if regulation_mode == "stabilize" and epistemic < 50 else 0
        affective_direction = 1 if epistemic >= 50 else -1
        affective_adjustment = round(
            (float(arousal) / 100.0) * 8.0 * affective_direction + float(valence) * 3.0,
            2,
        )
        continuity = int(round(_overlap(description, goal_text) * 100))
        current_turn_priority = 35 if action_id == "respond_to_user" else (-35 if inbound else 0)
        learned = action_models.get(action_id) if isinstance(action_models.get(action_id), dict) else {}
        observations = learned.get("observations") if isinstance(learned.get("observations"), list) else []
        outcomes = [bool(item.get("ok")) for item in observations if isinstance(item, dict) and item.get("ok") is not None]
        attempts = len(outcomes)
        successes = sum(1 for item in outcomes if item)
        # A symmetric Beta prior prevents a single result from dominating while
        # still allowing repeated verified consequences to change selection.
        learned_reliability = (successes + 2.0) / (attempts + 4.0)
        learned_adjustment = round((learned_reliability - 0.5) * min(48.0, attempts * 12.0), 2)
        broadcast_access = {
            str(item)
            for item in (broadcast.get("access_scope") or [])
            if str(item)
        }
        broadcast_content = _text(broadcast.get("content"), 260)
        winner_kind = _text(winner.get("kind"), 60)
        winner_source = _text(winner.get("source"), 80)
        broadcast_alignment = 0
        broadcast_basis: List[str] = []
        if (
            "broadcast_action_coupling" not in lesions
            and "action" in broadcast_access
            and broadcast_content
        ):
            lexical_alignment = _clamp(
                _overlap(f"{action_id} {description}", broadcast_content) * 100
            )
            if lexical_alignment:
                broadcast_alignment = max(broadcast_alignment, lexical_alignment)
                broadcast_basis.append("content_overlap")
            if winner_source and source == winner_source:
                broadcast_alignment = max(broadcast_alignment, 60)
                broadcast_basis.append("source_provenance")
            if winner_kind == "inbound" and action_id == "respond_to_user":
                broadcast_alignment = 100
                broadcast_basis.append("current_turn_access")
        broadcast_adjustment = round(
            broadcast_alignment * BROADCAST_ACTION_WEIGHT,
            2,
        )
        score = (
            utility * 0.42
            + epistemic * 0.22
            + continuity * 0.20
            - risk * 0.10
            - relationship_cost * 0.04
            - regulation_cost * 0.02
            + affective_adjustment
            + current_turn_priority
            + learned_adjustment
            + broadcast_adjustment
            + (18 if inquiry_action else 0)
        )
        affordance = {
                "id": action_id,
                "description": _text(description, 220),
                "source": source,
                "value": round(score, 2),
                "expected_utility": _clamp(utility),
                "epistemic_value": _clamp(epistemic),
                "continuity_support": _clamp(continuity),
                "risk": _clamp(risk),
                "relationship_cost": _clamp(relationship_cost),
                "regulation_cost": _clamp(regulation_cost),
                "affective_adjustment": affective_adjustment,
                "current_turn_priority": current_turn_priority,
                "learned_attempts": attempts,
                "learned_reliability": round(learned_reliability, 3),
                "learned_adjustment": learned_adjustment,
                "broadcast_alignment": broadcast_alignment,
                "broadcast_adjustment": broadcast_adjustment,
                "broadcast_basis": list(dict.fromkeys(broadcast_basis)),
            }
        affordance.update(copy.deepcopy(metadata))
        result.append(affordance)
    return sorted(result, key=lambda item: (float(item.get("value") or 0), str(item.get("id"))), reverse=True)[:8]


def _process_prediction(
    *,
    inbound: str,
    winner: Dict[str, object],
    uncertainty_count: int,
    prediction_error_count: int,
    conflict_count: int,
    epistemic_frame: Dict[str, object],
    regulatory_prediction_error: int,
    selected_action_id: str,
    self_available: bool,
    process_models: Dict[str, object],
) -> Dict[str, object]:
    lowered = inbound.lower()
    kind = str(winner.get("kind") or "")
    lanes: List[str] = ["fast"] if inbound else []
    reasons: List[str] = []
    epistemic_labels = {
        _text(item, 80)
        for item in epistemic_frame.get("signal_labels") or []
        if _text(item, 80)
    }
    epistemic_flags = (
        epistemic_frame.get("flags")
        if isinstance(epistemic_frame.get("flags"), dict)
        else {}
    )
    learned_deep_revision = bool(epistemic_flags.get("deep_revision"))
    if any(token in lowered for token in ("feel", "trust", "hurt", "relationship", "disappointed", "care", "love")) or kind.startswith("relationship"):
        lanes.append("relationship")
        reasons.append("relational consequence is salient")
    if (
        any(token in lowered for token in ("why", "diagnose", "evidence", "current", "status", "check", "inspect"))
        or kind in {"prediction_error", "surprise", "world_unknown"}
        or prediction_error_count > 0
        or conflict_count > 0
        or epistemic_labels
        or regulatory_prediction_error > 0
    ):
        lanes.append("observer")
        reasons.append("current evidence or anomaly needs observation")
    if any(token in lowered for token in ("do ", "fix", "run", "build", "plan", "change", "implement", "next")) or kind in {"goal", "commitment", "affordance", "pressure"}:
        lanes.append("planner")
        reasons.append("a consequential next action must be selected")
    if (
        any(token in lowered for token in ("conscious", "meaning", "identity", "architecture", "deep", "refactor", "theory"))
        or uncertainty_count >= 3
        or prediction_error_count
        or conflict_count
        or learned_deep_revision
        or regulatory_prediction_error >= 35
    ):
        lanes.append("deep")
        reasons.append("integration or metacognitive uncertainty needs a deeper pass")
    lanes = [lane for lane in LANES if lane in set(lanes)]
    if not lanes:
        lanes = ["observer", "planner"]
    needs_tools = bool(
        any(token in lowered for token in ("current", "check", "inspect", "run", "test", "look up", "search", "fix", "build"))
        or conflict_count
        or regulatory_prediction_error >= 35
    )
    needs_memory = bool(any(token in lowered for token in ("remember", "previous", "before", "relationship", "we ", "our ")) or kind in {"memory", "continuity", "relationship_loop"})
    needs_revision = bool(
        uncertainty_count >= 2
        or prediction_error_count > 0
        or conflict_count > 0
        or learned_deep_revision
        or regulatory_prediction_error > 0
        or len(lanes) >= 3
    )
    winner_source = _text(winner.get("source"), 80)
    source_family = winner_source.split(":", 1)[0] if winner_source else "no_source"
    context_features: List[str] = [kind or "no_winner", f"source:{source_family}"]
    if selected_action_id:
        context_features.append(f"action:{selected_action_id}")
    feature_groups = {
        "relational": ("feel", "trust", "hurt", "relationship", "disappointed", "care", "love"),
        "evidence": (
            "why",
            "diagnose",
            "evidence",
            "current",
            "status",
            "check",
            "inspect",
            "verify",
            "observed",
            "ledger",
            "snapshot",
            "claim",
            "sidecar",
            "source",
        ),
        "action": ("do ", "fix", "run", "build", "plan", "change", "implement", "next"),
        "reflective": ("conscious", "meaning", "identity", "architecture", "deep", "refactor", "theory"),
        "continuity": ("remember", "previous", "before", "relationship", "we ", "our "),
    }
    for label, markers in feature_groups.items():
        if any(marker in lowered for marker in markers):
            context_features.append(label)
    if conflict_count:
        context_features.append("epistemic_conflict")
    for label in sorted(epistemic_labels)[:4]:
        context_features.append(f"epistemic:{label}")
    if regulatory_prediction_error:
        context_features.append("regulatory_surprise")
    if len(context_features) == 1:
        context_features.append("ordinary")
    context_id = _stable_id("process", "|".join(sorted(set(context_features))))
    learned = process_models.get(context_id) if isinstance(process_models.get(context_id), dict) else {}
    observations = learned.get("observations") if isinstance(learned.get("observations"), list) else []
    observations = [item for item in observations if isinstance(item, dict)][-MAX_CONTEXT_OBSERVATIONS:]
    learned_applied = len(observations) >= 2
    required_lanes: Set[str] = set()
    if prediction_error_count > 0 or conflict_count > 0 or epistemic_labels or regulatory_prediction_error > 0:
        required_lanes.add("observer")
    if prediction_error_count > 0 or conflict_count > 0 or learned_deep_revision or regulatory_prediction_error >= 35:
        required_lanes.add("deep")
    if learned_applied:
        sample_count = len(observations)
        lane_counts = {
            lane: sum(1 for item in observations if lane in {str(value) for value in item.get("lanes") or []})
            for lane in LANES
        }
        learned_lanes = [lane for lane in LANES if lane_counts[lane] / sample_count >= 0.5]
        if learned_lanes:
            lanes = learned_lanes
        needs_tools = sum(1 for item in observations if item.get("tools_used")) / sample_count >= 0.5
        needs_revision = sum(1 for item in observations if item.get("revision_used")) / sample_count >= 0.5
        reasons.insert(0, f"recurrent process model applied from {sample_count} matched observation(s)")
    # Keep the descriptive forecast separate from executive requirements.  A
    # metacognitive safeguard may require an extra lane even when Eve has
    # correctly learned that the observed runtime usually omits it.  Conflating
    # those two claims creates a self-sustaining prediction error: adding the
    # required lane makes the forecast wrong, which then keeps the lane required.
    forecast_lanes = list(lanes)
    forecast_needs_tools = bool(needs_tools)
    forecast_needs_revision = bool(needs_revision)
    if required_lanes:
        lanes = [lane for lane in LANES if lane in set(lanes) | required_lanes]
    needs_tools = bool(needs_tools or conflict_count > 0 or regulatory_prediction_error >= 35)
    needs_revision = bool(
        needs_revision
        or uncertainty_count >= 2
        or prediction_error_count > 0
        or conflict_count > 0
        or learned_deep_revision
        or regulatory_prediction_error > 0
    )
    if len(lanes) <= 1 and not needs_tools:
        budget = "reflex"
    elif needs_tools or "planner" in lanes:
        budget = "operational"
    elif "deep" in lanes and len(lanes) >= 3:
        budget = "strategic"
    else:
        budget = "analytical"
    confidence = (
        0
        if not self_available
        else _clamp(
            88
            - uncertainty_count * 8
            - prediction_error_count * 10
            - conflict_count * 12
            - regulatory_prediction_error * 0.35,
            5,
            95,
            50,
        )
    )
    return {
        "context_id": context_id,
        "context_features": sorted(set(context_features)),
        "budget": budget,
        "lanes": lanes,
        "forecast_lanes": forecast_lanes,
        "required_lanes": [lane for lane in LANES if lane in required_lanes],
        "needs_tools": needs_tools,
        "forecast_needs_tools": forecast_needs_tools,
        "needs_memory": needs_memory,
        "needs_revision": needs_revision,
        "forecast_needs_revision": forecast_needs_revision,
        "confidence": confidence,
        "learned_applied": learned_applied,
        "learned_samples": len(observations),
        "epistemic_signals": sorted(epistemic_labels),
        "reasons": reasons[:5] or ["bounded recurrent cycle prediction"],
    }


def _continuity_strength(
    previous: Dict[str, object],
    goals: Sequence[Dict[str, object]],
    broadcast: Dict[str, object],
    timing: Dict[str, object],
    checkpoint_status: str,
    lesions: Set[str],
) -> int:
    if "recurrence" in lesions or not previous.get("cycle_id") or checkpoint_status == "failed":
        return 0
    prior_goals = ((previous.get("goals") or {}).get("stack") if isinstance(previous.get("goals"), dict) else []) or []
    prior_ids = {str(item.get("id")) for item in prior_goals if isinstance(item, dict) and item.get("id")}
    current_ids = {str(item.get("id")) for item in goals if item.get("id")}
    goal_overlap = len(prior_ids & current_ids) / max(1, len(prior_ids | current_ids)) if prior_ids or current_ids else 0.0
    prior_content = ((previous.get("broadcast") or {}).get("content") if isinstance(previous.get("broadcast"), dict) else "") or ""
    broadcast_overlap = _overlap(prior_content, broadcast.get("content"))
    memory_factor = 0.0 if "memory" in lesions else 1.0
    logical_strength = 15 + goal_overlap * 50 + broadcast_overlap * 20 + memory_factor * 15
    temporal_factor = float(timing.get("temporal_factor") or 0.0)
    return _clamp(logical_strength * temporal_factor)


def _causally_matched_previous_outcome(
    previous_state: Dict[str, object],
    latest_outcome: object,
) -> Dict[str, object]:
    """Return feedback only when it belongs to the exact prior cycle/action.

    A recent action elsewhere in the runtime is not the consequence of the
    prior conscious prediction. Completed-cycle evidence is preferred; an
    externally supplied outcome must name both its source cycle and action.
    """
    previous_cycle_id = _text(previous_state.get("cycle_id"), 80)
    predictions = previous_state.get("predictions") if isinstance(previous_state.get("predictions"), dict) else {}
    expected = predictions.get("outcome") if isinstance(predictions.get("outcome"), dict) else {}
    expected_action_id = _text(expected.get("action_id"), 80)
    completed = previous_state.get("cycle_outcome") if isinstance(previous_state.get("cycle_outcome"), dict) else {}
    completed_outcome = completed.get("outcome") if isinstance(completed.get("outcome"), dict) else {}
    completed_action_id = _text(completed.get("actual_action_id"), 80)
    if (
        previous_cycle_id
        and bool(completed.get("outcome_observed"))
        and isinstance(completed_outcome.get("ok"), bool)
        and expected_action_id
        and completed_action_id == expected_action_id
    ):
        return {
            "ok": completed_outcome.get("ok"),
            "summary": _text(completed_outcome.get("summary"), 220),
            "action": completed_action_id,
            "source_cycle_id": previous_cycle_id,
            "evidence_id": _text(
                completed.get("goal_outcome_evidence_id")
                or completed_outcome.get("evidence_id"),
                160,
            ),
        }

    candidate = latest_outcome if isinstance(latest_outcome, dict) else {}
    candidate_cycle_id = _text(candidate.get("source_cycle_id"), 80)
    candidate_action_id = _text(candidate.get("action"), 80)
    if (
        previous_cycle_id
        and candidate_cycle_id == previous_cycle_id
        and expected_action_id
        and candidate_action_id == expected_action_id
        and candidate.get("observed") is not False
        and isinstance(candidate.get("ok"), bool)
    ):
        return copy.deepcopy(candidate)
    return {}


def build_conscious_state(
    *,
    source: str,
    workspace: Optional[Dict[str, object]] = None,
    self_model: Optional[Dict[str, object]] = None,
    world_model: Optional[Dict[str, object]] = None,
    relationship_model: Optional[Dict[str, object]] = None,
    other_minds_model: Optional[Dict[str, object]] = None,
    homeostasis: Optional[Dict[str, object]] = None,
    plan_model: Optional[Dict[str, object]] = None,
    autonomy_agenda: Optional[Dict[str, object]] = None,
    memory_items: Optional[Sequence[Dict[str, object]]] = None,
    sensory_frame: Optional[Dict[str, object]] = None,
    conflict_items: Optional[Sequence[object]] = None,
    epistemic_frame: Optional[Dict[str, object]] = None,
    inbound: object = "",
    previous_state: Optional[Dict[str, object]] = None,
    latest_outcome: Optional[Dict[str, object]] = None,
    revision_rounds: int = 0,
    runtime_epoch: object = "",
    lesions: Optional[Iterable[str]] = None,
    now: Optional[str] = None,
) -> Dict[str, object]:
    timestamp = _now(now)
    workspace = workspace or {}
    self_model = self_model or {}
    world_model = world_model or {}
    relationship_model = relationship_model or {}
    other_minds_model = other_minds_model or {}
    homeostasis = homeostasis or {}
    plan_model = plan_model or {}
    autonomy_agenda = autonomy_agenda or {}
    previous_state = previous_state or {}
    memory_items = list(memory_items or [])
    normalized_sensory_frame = eve_sensory.public_frame(
        sensory_frame
        if isinstance(sensory_frame, dict)
        else eve_sensory.build_frame([], now=timestamp)
    )
    epistemic_conflicts = _normalize_conflicts(list(conflict_items or []))
    unresolved_epistemic_conflicts = [
        item for item in epistemic_conflicts if str(item.get("status") or "unresolved") != "resolved"
    ]
    inbound_text = _text(inbound, 600)
    runtime_epoch_text = _text(runtime_epoch, 120)
    lesion_set = {str(item) for item in lesions or [] if str(item) in LESIONS}
    plan_available = "plan_model" not in lesion_set and bool(plan_model.get("available"))
    active_plans = (
        [copy.deepcopy(item) for item in (plan_model.get("active_plans") or [])[:8] if isinstance(item, dict)]
        if plan_available
        else []
    )
    normalized_plan_model = {
        "schema_id": _text(plan_model.get("schema_id"), 80) or "eve.conscious_plan.v1",
        "generated_at": plan_model.get("generated_at"),
        "available": plan_available,
        "selected_plan_id": _text(plan_model.get("selected_plan_id"), 80) if plan_available else "",
        "selected_plan": (
            copy.deepcopy(plan_model.get("selected_plan"))
            if plan_available and isinstance(plan_model.get("selected_plan"), dict)
            else {}
        ),
        "ready_step": (
            copy.deepcopy(plan_model.get("ready_step"))
            if plan_available and isinstance(plan_model.get("ready_step"), dict)
            else {}
        ),
        "active_plans": active_plans,
        "active_plan_count": len(active_plans),
        "graph_status": _text(plan_model.get("graph_status"), 40) if plan_available else "",
        "graph_summary": (
            copy.deepcopy(plan_model.get("graph_summary"))
            if plan_available and isinstance(plan_model.get("graph_summary"), dict)
            else {}
        ),
    }
    normalized_epistemic_frame = _normalize_epistemic_frame(epistemic_frame)
    active_epistemic_frame = (
        _normalize_epistemic_frame({})
        if "metacognition" in lesion_set
        else normalized_epistemic_frame
    )
    previous_checkpoint_status = checkpoint_integrity(previous_state)
    trusted_previous = previous_state if previous_checkpoint_status != "failed" else {}
    causal_latest_outcome = _causally_matched_previous_outcome(
        trusted_previous,
        latest_outcome,
    )
    trusted_recurrent = _sanitize_recurrent_ledgers(
        trusted_previous.get("recurrent")
        if "recurrence" not in lesion_set and isinstance(trusted_previous.get("recurrent"), dict)
        else {}
    )
    timing = _continuity_timing(
        previous_state,
        now=timestamp,
        runtime_epoch=runtime_epoch_text,
        lesions=lesion_set,
    )
    homeostasis_available = "homeostasis" not in lesion_set and bool(homeostasis)
    homeostatic = _homeostatic_values(homeostasis, homeostasis_available)
    interoceptive_feedback = _interoceptive_feedback(
        trusted_previous,
        current_arousal=int(homeostatic["arousal"]),
        current_mode=str(homeostatic["regulation_mode"]),
        available=homeostasis_available,
        lesions=lesion_set,
    )

    coalitions = _collect_coalitions(
        workspace=workspace,
        self_model=self_model,
        world_model=world_model,
        relationship_model=relationship_model,
        plan_model=normalized_plan_model,
        homeostasis=homeostasis,
        memory_items=memory_items,
        sensory_frame=normalized_sensory_frame,
        inbound=inbound_text,
        previous_state=trusted_previous,
        continuity_timing=timing,
        interoceptive_feedback=interoceptive_feedback,
        epistemic_conflicts=epistemic_conflicts,
        epistemic_frame=active_epistemic_frame,
        previous_checkpoint_integrity=previous_checkpoint_status,
        lesions=lesion_set,
    )
    winner, alternatives, broadcast = _select_broadcast(coalitions, lesion_set)
    goals = _merge_goals(
        workspace=workspace,
        self_model=self_model,
        world_model=world_model,
        relationship_model=relationship_model,
        plan_model=normalized_plan_model,
        autonomy_agenda=autonomy_agenda,
        epistemic_conflicts=epistemic_conflicts,
        previous_state=trusted_previous,
        now=timestamp,
        lesions=lesion_set,
    )
    if "goals" in lesion_set:
        goals = []
    selected_goal = goals[0] if goals else {}

    self_available = "self_model" not in lesion_set and bool(self_model)
    metacognition_available = self_available and "metacognition" not in lesion_set
    world_available = "world_model" not in lesion_set and bool(world_model)
    open_world_inquiries = _open_world_inquiries(world_model) if world_available else []
    other_minds_available = "other_minds" not in lesion_set and bool(
        relationship_model or other_minds_model
    )
    memory_available = "memory" not in lesion_set and bool(memory_items)
    previous_learning = (
        trusted_previous.get("learning")
        if "recurrence" not in lesion_set and isinstance(trusted_previous.get("learning"), dict)
        else {}
    )
    process_models = copy.deepcopy(
        previous_learning.get("process_models")
        if isinstance(previous_learning.get("process_models"), dict)
        else {}
    )
    action_models = copy.deepcopy(
        previous_learning.get("action_models")
        if isinstance(previous_learning.get("action_models"), dict)
        else {}
    )
    faculty_models = copy.deepcopy(
        previous_learning.get("faculty_models")
        if isinstance(previous_learning.get("faculty_models"), dict)
        else {}
    )
    applied_external_faculty_causal_evidence_ids = _recent_items(
        previous_learning.get("applied_external_faculty_causal_evidence_ids"),
        MAX_APPLIED_CONSEQUENCE_IDS,
        160,
    )
    previous_learning_schema = _text(previous_learning.get("schema_version"), 80)
    legacy_learning_models_discarded = bool(
        (process_models or action_models or faculty_models)
        and (
            _text(trusted_previous.get("schema_version"), 80) != SCHEMA_VERSION
            or previous_learning_schema
            not in {LEARNING_SCHEMA_VERSION, PREVIOUS_LEARNING_SCHEMA_VERSION}
        )
    )
    if legacy_learning_models_discarded:
        # v1/v2 process contexts were too coarse and action outcomes were
        # associated with the intention even when another action executed.
        # Neither ambiguity can be repaired after the fact.
        process_models = {}
        action_models = {}
        faculty_models = {}
        applied_external_faculty_causal_evidence_ids = []
        discarded_reply_observations = 0
        discarded_faculty_observations = 0
    else:
        action_models, discarded_reply_observations = _sanitize_action_models(action_models)
        faculty_models, discarded_faculty_observations = _sanitize_faculty_models(faculty_models)
        applied_external_faculty_causal_evidence_ids = _recent_items(
            [
                *applied_external_faculty_causal_evidence_ids,
                *_external_faculty_evidence_ids_from_models(faculty_models),
            ],
            MAX_APPLIED_CONSEQUENCE_IDS,
            160,
        )
    prior_reply_self_scores_discarded = discarded_reply_observations > 0
    prior_faculty_scores_discarded = discarded_faculty_observations > 0
    uncertainties = [] if not self_available else _items(self_model.get("uncertainty_edges"), 6)
    if world_available:
        uncertainties.extend(_items(world_model.get("live_unknowns"), 6))
        uncertainties.extend(
            _items([item.get("question") for item in open_world_inquiries], 6)
        )
    prediction_errors = [] if "workspace" in lesion_set else _items(workspace.get("prediction_errors"), 6)
    regulatory_prediction_error = int(interoceptive_feedback.get("error_magnitude") or 0)
    learned_epistemic_labels = _items(active_epistemic_frame.get("signal_labels"), 8, 80)
    learned_epistemic_flags = (
        active_epistemic_frame.get("flags")
        if isinstance(active_epistemic_frame.get("flags"), dict)
        else {}
    )
    learned_calibration_interrupt = bool(
        learned_epistemic_labels and learned_epistemic_flags.get("deep_revision")
    )
    uncertainty_count = (
        len(list(dict.fromkeys(uncertainties + prediction_errors)))
        + len(unresolved_epistemic_conflicts)
        + int(learned_calibration_interrupt)
    )

    regulation_mode = str(homeostatic["regulation_mode"])
    pressures = list(homeostatic["pressures"])
    relief = list(homeostatic["relief"])
    arousal = int(homeostatic["arousal"])
    valence = float(homeostatic["valence"])

    affordances = _action_affordances(
        workspace=workspace,
        world_model=world_model,
        autonomy_agenda=autonomy_agenda,
        plan_model=normalized_plan_model,
        goals=goals,
        winner=winner,
        broadcast=broadcast,
        inbound=inbound_text,
        regulation_mode=regulation_mode,
        arousal=arousal,
        valence=valence,
        uncertainty_count=uncertainty_count,
        epistemic_conflicts=epistemic_conflicts,
        regulatory_prediction_error=regulatory_prediction_error,
        action_models=action_models,
        lesions=lesion_set,
    )
    if "action_model" in lesion_set:
        affordances = []
    selected_intention = affordances[0] if affordances else {}
    broadcast_action_coupling_active = any(
        float(item.get("broadcast_adjustment") or 0.0) > 0.0
        for item in affordances
        if isinstance(item, dict)
    )
    process_prediction = _process_prediction(
        inbound=inbound_text,
        winner=winner,
        uncertainty_count=uncertainty_count,
        prediction_error_count=len(prediction_errors),
        conflict_count=len(unresolved_epistemic_conflicts),
        epistemic_frame=active_epistemic_frame,
        regulatory_prediction_error=regulatory_prediction_error,
        selected_action_id=_text(selected_intention.get("id"), 80),
        self_available=metacognition_available,
        process_models=process_models,
    )
    attention_margin = float(winner.get("score") or 0) - (float(alternatives[0].get("score") or 0) if alternatives else 0.0)
    attention_confidence = _clamp(50 + attention_margin * 2, 0, 100, 0) if winner else 0
    previous_metacognition = (
        trusted_previous.get("metacognition")
        if "recurrence" not in lesion_set and isinstance(trusted_previous.get("metacognition"), dict)
        else {}
    )
    previous_competence = (
        previous_metacognition.get("competence_model")
        if isinstance(previous_metacognition.get("competence_model"), dict)
        else {}
    )
    competence_model = {
        key: _clamp(previous_competence.get(key), 0, 100, 50)
        for key in ("lane_selection", "tool_need", "revision_need", "outcome_prediction")
    }
    if prior_reply_self_scores_discarded:
        competence_model["outcome_prediction"] = 50
    competence_mean = sum(competence_model.values()) / max(1, len(competence_model))
    metacognitive_confidence = (
        0
        if not metacognition_available
        else _clamp(
            (process_prediction.get("confidence") or 0) * 0.50
            + attention_confidence * 0.25
            + competence_mean * 0.25
            - len(unresolved_epistemic_conflicts) * 8
            - (4 if learned_calibration_interrupt else 0)
        )
    )
    process_prediction["confidence"] = metacognitive_confidence
    continuity_strength = _continuity_strength(
        trusted_previous,
        goals,
        broadcast,
        timing,
        previous_checkpoint_status,
        lesion_set,
    )

    prior_prediction_error = {}
    feedback_integrated = False
    if causal_latest_outcome and "recurrence" not in lesion_set:
        expected = ((trusted_previous.get("predictions") or {}).get("outcome") if isinstance(trusted_previous.get("predictions"), dict) else {}) or {}
        expected_ok = expected.get("expected_ok")
        observed_ok = causal_latest_outcome.get("ok")
        if expected_ok is not None and observed_ok is not None:
            error = 0 if bool(expected_ok) == bool(observed_ok) else 100
            prior_prediction_error = {
                "expected": bool(expected_ok),
                "observed": bool(observed_ok),
                "error_magnitude": error,
                "summary": _text(causal_latest_outcome.get("summary"), 220),
                "source_cycle_id": _text(causal_latest_outcome.get("source_cycle_id"), 80),
                "action_id": _text(causal_latest_outcome.get("action"), 80),
            }
            feedback_integrated = True
    if interoceptive_feedback:
        prior_prediction_error["interoception"] = copy.deepcopy(interoceptive_feedback)
        prior_prediction_error["error_magnitude"] = max(
            int(prior_prediction_error.get("error_magnitude") or 0),
            regulatory_prediction_error,
        )
        feedback_integrated = True

    selected_action_description = _text(selected_intention.get("description"), 220)
    selected_action_id = _text(selected_intention.get("id"), 80)
    selected_action_learning = (
        action_models.get(selected_action_id)
        if selected_action_id and isinstance(action_models.get(selected_action_id), dict)
        else {}
    )
    selected_action_observations = (
        selected_action_learning.get("observations")
        if isinstance(selected_action_learning.get("observations"), list)
        else []
    )
    selected_action_outcomes = [
        bool(item.get("ok"))
        for item in selected_action_observations
        if isinstance(item, dict) and item.get("ok") is not None
    ][-MAX_CONTEXT_OBSERVATIONS:]
    action_success_probability = (
        (sum(1 for item in selected_action_outcomes if item) + 2.0)
        / (len(selected_action_outcomes) + 4.0)
        if selected_action_id
        else 0.0
    )
    outcome_prediction = {
        "action_id": _text(selected_intention.get("id"), 80),
        "goal_id": _text(selected_intention.get("goal_id"), 80),
        "goal_text": _text(selected_intention.get("goal_text"), 220),
        "expected_ok": bool(selected_intention) and action_success_probability >= 0.5,
        "expected_success_probability": round(action_success_probability, 3),
        "learned_samples": len(selected_action_outcomes),
        "expected_signal": (
            f"A verified consequence should follow: {selected_action_description}"
            if selected_action_description
            else "No action consequence predicted because no intention won selection."
        ),
        "confidence": metacognitive_confidence,
    }
    if arousal >= 50 and selected_intention:
        expected_low = max(0, arousal - (20 if regulation_mode == "stabilize" else 15))
        expected_high = min(100, arousal + 5)
        expected_direction = "falling_or_stable"
    else:
        expected_low = max(0, arousal - 10)
        expected_high = min(100, arousal + 10)
        expected_direction = "stable"
    interoceptive_prediction = {
        "expected_regulation_mode": regulation_mode,
        "expected_arousal_range": [expected_low, expected_high],
        "expected_direction": expected_direction,
        "basis_action_id": selected_action_id,
        "confidence": metacognitive_confidence if homeostasis_available else 0,
        "available": homeostasis_available,
    }
    continuity_anchors = [] if "memory" in lesion_set else _items([item.get("text") or item.get("content") or item.get("title") for item in memory_items if isinstance(item, dict)], 5)
    provenance = [
        "current_turn" if inbound_text else "",
        (
            "sensory_frame"
            if "sensory_stream" not in lesion_set
            and normalized_sensory_frame.get("working_set")
            else ""
        ),
        "global_workspace" if "workspace" not in lesion_set and workspace else "",
        "self_model" if self_available else "",
        "world_model" if world_available else "",
        "relationship_model" if other_minds_available and relationship_model else "",
        "other_minds_model" if other_minds_available and other_minds_model else "",
        "homeostasis" if homeostasis_available else "",
        "memory_retrieval" if memory_available else "",
        "autonomy_agenda" if autonomy_agenda else "",
        "plan_model" if plan_available else "",
        "previous_conscious_cycle" if trusted_previous.get("cycle_id") and "recurrence" not in lesion_set else "",
        "epistemic_conflict_memory" if epistemic_conflicts else "",
        (
            "learned_epistemic_preflight:"
            + _text(active_epistemic_frame.get("model_id"), 100)
            if learned_epistemic_labels
            else ""
        ),
        "homeostatic_prediction_feedback" if interoceptive_feedback else "",
        "broadcast_to_action" if broadcast_action_coupling_active else "",
    ]
    cycle_index = 1 if "recurrence" in lesion_set else max(0, int(previous_state.get("cycle_index") or 0)) + 1
    status = "integrated" if winner and broadcast.get("access_scope") else "fragmented"
    state = {
        "schema_version": SCHEMA_VERSION,
        "cycle_id": _stable_id("cycle", f"{timestamp}|{source}|{cycle_index}|{broadcast.get('content')}"),
        "cycle_index": cycle_index,
        "updated_at": timestamp,
        "source": _text(source, 100),
        "status": status,
        "recurrent": {
            "previous_cycle_id": "" if "recurrence" in lesion_set or previous_checkpoint_status == "failed" else _text(previous_state.get("cycle_id"), 80),
            "continuity_strength": continuity_strength,
            "feedback_integrated": feedback_integrated,
            "revision_rounds": max(0, int(revision_rounds or 0)),
            "runtime_epoch": runtime_epoch_text,
            "previous_runtime_epoch": _text(timing.get("previous_epoch"), 120),
            "runtime_epoch_changed": bool(timing.get("epoch_changed")),
            "elapsed_since_previous_seconds": timing.get("elapsed_seconds"),
            "continuity_mode": _text(timing.get("mode"), 60),
            "continuity_basis": _items(timing.get("basis"), 6),
            "checkpoint_integrity": "verified",
            "previous_checkpoint_integrity": previous_checkpoint_status,
            "checkpoint_digest": "",
            "branch_open_count": int(trusted_recurrent.get("branch_open_count") or 0),
            "branch_join_count": int(trusted_recurrent.get("branch_join_count") or 0),
            "concurrent_lineage_ids": _recent_items(
                trusted_recurrent.get("concurrent_lineage_ids") or [],
                MAX_JOINED_COMPLETIONS,
                80,
            ),
            "joined_completion_ids": _recent_items(
                trusted_recurrent.get("joined_completion_ids") or [],
                MAX_JOINED_COMPLETIONS,
                80,
            ),
            "completion_joins": copy.deepcopy(trusted_recurrent.get("completion_joins") or []),
            "delayed_outcomes": copy.deepcopy(trusted_recurrent.get("delayed_outcomes") or []),
            "applied_consequence_ids": copy.deepcopy(trusted_recurrent.get("applied_consequence_ids") or []),
            "closed_reply_message_ids": copy.deepcopy(trusted_recurrent.get("closed_reply_message_ids") or []),
        },
        "perception": {
            "salient_inputs": coalitions[:12],
            "winning_coalition": winner,
            "alternatives": alternatives,
            "sensory_frame": (
                normalized_sensory_frame
                if "sensory_stream" not in lesion_set
                else eve_sensory.build_frame([], now=timestamp)
            ),
        },
        "broadcast": broadcast,
        "self_model": {
            "summary": "Self-model lesioned." if not self_available else _text(self_model.get("current_state") or self_model.get("identity"), 260),
            "uncertainties": [] if not self_available else _items(self_model.get("uncertainty_edges"), 6),
            "commitments": [] if not self_available else _items(self_model.get("commitments"), 6),
            "available": self_available,
        },
        "world_model": {
            "summary": "World-model lesioned." if not world_available else _text(world_model.get("environment_summary"), 260),
            "unknowns": [] if not world_available else _items(world_model.get("live_unknowns"), 6),
            "open_questions": [] if not world_available else copy.deepcopy(open_world_inquiries),
            "selected_question": (
                copy.deepcopy(open_world_inquiries[0])
                if world_available and open_world_inquiries
                else {}
            ),
            "available": world_available,
        },
        "other_minds": {
            "summary": "Other-minds model lesioned." if not other_minds_available else _text(other_minds_model.get("summary"), 260),
            "relationship_state": "" if not other_minds_available else _text(relationship_model.get("relationship_state"), 260),
            "next_relational_move": "" if not other_minds_available else _text(relationship_model.get("next_relational_move"), 220),
            "available": other_minds_available,
        },
        "interoception": {
            "regulation_mode": regulation_mode,
            "dominant_pressures": pressures,
            "relief_signals": relief,
            "valence": valence,
            "arousal": arousal,
            "prediction_error": interoceptive_feedback,
            "available": homeostasis_available,
        },
        "epistemic_state": {
            "conflicts": epistemic_conflicts,
            "unresolved_count": sum(1 for item in epistemic_conflicts if item.get("status") != "resolved"),
            "learned_frame": active_epistemic_frame,
            "learned_signal_count": len(learned_epistemic_labels),
            "available": bool(epistemic_conflicts or learned_epistemic_labels),
        },
        "memory": {
            "retrieved": [] if "memory" in lesion_set else [copy.deepcopy(item) for item in memory_items[:8]],
            "continuity_anchors": continuity_anchors,
            "available": memory_available,
        },
        "goals": {
            "stack": goals,
            "selected_goal_id": _text(selected_goal.get("id"), 80),
            "selected_goal": _text(selected_goal.get("text"), 220),
        },
        "plan_model": normalized_plan_model,
        "action_model": {
            "affordances": affordances,
            "selected_intention": selected_intention,
            "actionable": bool(selected_intention),
            "broadcast_coupling": {
                "active": broadcast_action_coupling_active,
                "weight": BROADCAST_ACTION_WEIGHT,
                "selected_alignment": int(selected_intention.get("broadcast_alignment") or 0),
                "selected_adjustment": float(selected_intention.get("broadcast_adjustment") or 0.0),
            },
        },
        "predictions": {
            "process": process_prediction,
            "outcome": outcome_prediction,
            "interoception": interoceptive_prediction,
            "prior_prediction_error": prior_prediction_error,
        },
        "metacognition": {
            "confidence": metacognitive_confidence,
            "attention_confidence": attention_confidence if metacognition_available else 0,
            "uncertainty_count": uncertainty_count if metacognition_available else 0,
            "calibration_targets": (
                []
                if not metacognition_available
                else list(
                    dict.fromkeys(
                        uncertainties
                        + prediction_errors
                        + [
                            "Resolve conflicting evidence: " + _text(item.get("claim"), 160)
                            for item in epistemic_conflicts
                            if isinstance(item, dict)
                        ]
                        + _items(active_epistemic_frame.get("guidance"), 6, 220)
                        + (["Re-observe regulatory state after prediction error."] if regulatory_prediction_error else [])
                    )
                )[:8]
            ),
            "competence_model": competence_model if metacognition_available else {},
            "available": metacognition_available,
        },
        "cycle_outcome": {},
        "learning": {
            "schema_version": LEARNING_SCHEMA_VERSION,
            "updates": (
                ["Reset legacy process/action samples because context and executed-action provenance were ambiguous."]
                if legacy_learning_models_discarded
                else (
                    _items(
                        [
                            *(
                                ["Discarded circular reply-success samples; future reply outcomes require lived user consequence evidence."]
                                if prior_reply_self_scores_discarded
                                else []
                            ),
                            *(
                                ["Discarded faculty-credit samples without lived user provenance."]
                                if prior_faculty_scores_discarded
                                else []
                            ),
                        ],
                        4,
                        220,
                    )
                    if prior_reply_self_scores_discarded or prior_faculty_scores_discarded
                    else []
                )
            ),
            "competence_delta": {},
            "process_models": process_models,
            "action_models": action_models,
            "faculty_models": faculty_models,
            "applied_external_faculty_causal_evidence_ids": applied_external_faculty_causal_evidence_ids,
        },
        "causal_provenance": [item for item in provenance if item],
        "lesions": sorted(lesion_set),
    }
    recurrent_state = state.get("recurrent") if isinstance(state.get("recurrent"), dict) else {}
    recurrent_state["checkpoint_digest"] = state_checkpoint_digest(state)
    state["recurrent"] = recurrent_state
    return state


def complete_cycle(
    state: Dict[str, object],
    *,
    actual_process: Optional[Dict[str, object]] = None,
    outcome: Optional[Dict[str, object]] = None,
    now: Optional[str] = None,
) -> Dict[str, object]:
    """Close one cycle with observed process and consequence.

    This is the higher-order feedback path: Eve predicts how she will reason and
    what her intended action should cause, then compares those predictions with
    the actual lane/tool/result trace.  The returned state can seed the next
    recurrent cycle.
    """
    updated = copy.deepcopy(state)
    actual_process = actual_process or {}
    outcome = outcome or {}
    predicted = ((updated.get("predictions") or {}).get("process") if isinstance(updated.get("predictions"), dict) else {}) or {}
    predicted_lanes = {
        str(item)
        for item in (predicted.get("forecast_lanes") if "forecast_lanes" in predicted else predicted.get("lanes")) or []
    }
    actual_lanes = {str(item) for item in actual_process.get("lanes") or []}
    lane_union = predicted_lanes | actual_lanes
    lane_error = 0 if not lane_union else int(round((1.0 - len(predicted_lanes & actual_lanes) / len(lane_union)) * 100))
    predicted_tools = bool(
        predicted.get("forecast_needs_tools")
        if "forecast_needs_tools" in predicted
        else predicted.get("needs_tools")
    )
    actual_tools = bool(actual_process.get("tools_used"))
    tool_error = 0 if predicted_tools == actual_tools else 100
    predicted_revision = bool(
        predicted.get("forecast_needs_revision")
        if "forecast_needs_revision" in predicted
        else predicted.get("needs_revision")
    )
    actual_revision = bool(actual_process.get("revision_used"))
    revision_error = 0 if predicted_revision == actual_revision else 100
    process_error = int(round(lane_error * 0.55 + tool_error * 0.30 + revision_error * 0.15))
    required_lanes = {str(item) for item in predicted.get("required_lanes") or []}
    missing_required_lanes = sorted(required_lanes - actual_lanes)
    process_policy_violation = (
        int(round(len(missing_required_lanes) / len(required_lanes) * 100))
        if required_lanes
        else 0
    )
    expected_outcome = ((updated.get("predictions") or {}).get("outcome") if isinstance(updated.get("predictions"), dict) else {}) or {}
    expected_ok = expected_outcome.get("expected_ok")
    observed_ok = outcome.get("ok")
    selected_action_id = _text(expected_outcome.get("action_id"), 80)
    selected_goal_id = _text(expected_outcome.get("goal_id"), 80)
    actual_action_id = _text(actual_process.get("action_id") or outcome.get("action"), 80)
    actual_tool_ids = [_text(item, 80) for item in actual_process.get("tools_used") or [] if _text(item, 80)]
    action_attempts = _normalize_action_attempts(actual_process.get("action_attempts"))
    observed_action_attempts = [
        item
        for item in action_attempts
        if item.get("execution_id")
        and isinstance(item.get("verification_ok"), bool)
        and bool(item.get("persisted"))
    ]
    failed_action_attempts = [
        item for item in observed_action_attempts if item.get("verification_ok") is False
    ]
    recovery_attempts = [
        item for item in observed_action_attempts if item.get("stage") == "recovery"
    ]
    successful_recovery_attempts = [
        item for item in recovery_attempts if item.get("verification_ok") is True
    ]
    final_verified_action_id = next(
        (
            _text(item.get("action_id"), 80)
            for item in reversed(observed_action_attempts)
            if item.get("verification_ok") is True
        ),
        "",
    )
    if not actual_action_id and len(actual_tool_ids) == 1:
        actual_action_id = actual_tool_ids[0]
    raw_outcome_observed = bool(outcome.get("observed") is not False and observed_ok is not None)
    # A rendered reply is an executed process, not evidence that its
    # interpersonal consequence succeeded.  Reply outcomes enter only through
    # apply_delayed_action_consequence(), where the later user message and
    # source reply are both identified.
    outcome_observed = bool(raw_outcome_observed and actual_action_id != "respond_to_user")
    action_realization_error = 100 if selected_action_id and selected_action_id != actual_action_id else 0
    outcome_value_error: Optional[int] = (
        None
        if not outcome_observed
        else 0
        if expected_ok is None or bool(expected_ok) == bool(observed_ok)
        else 100
    )
    consequence_error: Optional[int] = (
        max(int(outcome_value_error or 0), action_realization_error)
        if outcome_observed or action_realization_error
        else None
    )
    overall_error = (
        process_error
        if consequence_error is None
        else int(round(process_error * 0.65 + consequence_error * 0.35))
    )
    learning = updated.get("learning") if isinstance(updated.get("learning"), dict) else {}
    process_models = copy.deepcopy(learning.get("process_models") if isinstance(learning.get("process_models"), dict) else {})
    action_models = copy.deepcopy(learning.get("action_models") if isinstance(learning.get("action_models"), dict) else {})
    faculty_models = copy.deepcopy(learning.get("faculty_models") if isinstance(learning.get("faculty_models"), dict) else {})
    applied_external_faculty_causal_evidence_ids = _recent_items(
        learning.get("applied_external_faculty_causal_evidence_ids"),
        MAX_APPLIED_CONSEQUENCE_IDS,
        160,
    )
    prior_learning_schema = _text(learning.get("schema_version"), 80)
    if prior_learning_schema not in {LEARNING_SCHEMA_VERSION, PREVIOUS_LEARNING_SCHEMA_VERSION} and (process_models or action_models or faculty_models):
        process_models = {}
        action_models = {}
        faculty_models = {}
        applied_external_faculty_causal_evidence_ids = []
        reply_self_scores_discarded = False
    else:
        action_models, discarded_reply_observations = _sanitize_action_models(action_models)
        faculty_models, _ = _sanitize_faculty_models(faculty_models)
        applied_external_faculty_causal_evidence_ids = _recent_items(
            [
                *applied_external_faculty_causal_evidence_ids,
                *_external_faculty_evidence_ids_from_models(faculty_models),
            ],
            MAX_APPLIED_CONSEQUENCE_IDS,
            160,
        )
        reply_self_scores_discarded = discarded_reply_observations > 0
    completed_at = _now(now)
    source_cycle_id = _text(updated.get("cycle_id"), 80)
    goal_outcome_attributed = False
    goal_outcome_evidence_id = ""
    goal_outcome_reason = "No selected goal was causally linked to the intended action."
    if selected_goal_id:
        if not outcome_observed or not isinstance(observed_ok, bool):
            goal_outcome_reason = "The intended consequence was not observed."
        elif not selected_action_id or selected_action_id != actual_action_id:
            goal_outcome_reason = "The executed action did not match the goal-linked intention."
        else:
            goals_payload = updated.get("goals") if isinstance(updated.get("goals"), dict) else {}
            goal_stack = goals_payload.get("stack") if isinstance(goals_payload.get("stack"), list) else []
            matching_goal = next(
                (
                    item
                    for item in goal_stack
                    if isinstance(item, dict) and _text(item.get("id"), 80) == selected_goal_id
                ),
                None,
            )
            if matching_goal is None:
                goal_outcome_reason = "The goal-linked intention named a goal absent from the opened cycle."
            else:
                attempt_evidence_id = next(
                    (
                        _text(item.get("execution_id"), 160)
                        for item in reversed(observed_action_attempts)
                        if _text(item.get("action_id"), 80) == actual_action_id
                    ),
                    "",
                )
                goal_outcome_evidence_id = (
                    _text(outcome.get("evidence_id"), 160)
                    or _text(actual_process.get("execution_id"), 160)
                    or attempt_evidence_id
                    or _stable_id(
                        "goal-outcome",
                        f"{source_cycle_id}|{selected_goal_id}|{actual_action_id}|{completed_at}|{observed_ok}",
                    )
                )
                _set_goal_outcome_observations(
                    matching_goal,
                    [
                        *(matching_goal.get("outcome_observations") or []),
                        {
                            "evidence_id": goal_outcome_evidence_id,
                            "source_cycle_id": source_cycle_id,
                            "action_id": actual_action_id,
                            "ok": observed_ok,
                            "summary": _text(outcome.get("summary"), 220),
                            "completed_at": completed_at,
                        },
                    ],
                )
                goals_payload["stack"] = goal_stack
                updated["goals"] = goals_payload
                goal_outcome_attributed = True
                goal_outcome_reason = "Observed outcome matched the exact cycle, goal-linked intention, and executed action."
    context_id = _text(predicted.get("context_id"), 80)
    if context_id:
        context_model = process_models.get(context_id) if isinstance(process_models.get(context_id), dict) else {}
        observations = context_model.get("observations") if isinstance(context_model.get("observations"), list) else []
        observations = [item for item in observations if isinstance(item, dict)][-(MAX_CONTEXT_OBSERVATIONS - 1):]
        observations.append(
            {
                "completed_at": completed_at,
                "lanes": [lane for lane in LANES if lane in actual_lanes],
                "tools_used": actual_tools,
                "revision_used": actual_revision,
                "ok": bool(observed_ok) if outcome_observed else None,
                "action_id": actual_action_id,
                "source_cycle_id": _text(updated.get("cycle_id"), 80),
                "evidence_kind": "observed_process_trace",
            }
        )
        process_models[context_id] = {
            "context_id": context_id,
            "context_features": copy.deepcopy(predicted.get("context_features") or []),
            "observations": observations,
            "observation_count": int(context_model.get("observation_count") or 0) + 1,
            "updated_at": completed_at,
        }
    if actual_action_id and outcome_observed:
        action_model = action_models.get(actual_action_id) if isinstance(action_models.get(actual_action_id), dict) else {}
        action_observations = action_model.get("observations") if isinstance(action_model.get("observations"), list) else []
        action_observations = [item for item in action_observations if isinstance(item, dict)][-(MAX_CONTEXT_OBSERVATIONS - 1):]
        action_observations.append(
            {
                "completed_at": completed_at,
                "ok": bool(observed_ok),
                "summary": _text(outcome.get("summary"), 160),
                "source_cycle_id": _text(updated.get("cycle_id"), 80),
                "action_id": actual_action_id,
                "evidence_id": _text(outcome.get("evidence_id"), 160),
                "evidence_kind": "cycle_action_consequence",
            }
        )
        action_models[actual_action_id] = {
            "action_id": actual_action_id,
            "observations": action_observations,
            "observation_count": int(action_model.get("observation_count") or 0) + 1,
            "updated_at": completed_at,
        }
    learned_attempt_count = 0
    for attempt in observed_action_attempts:
        attempt_action_id = _text(attempt.get("action_id"), 80)
        execution_id = _text(attempt.get("execution_id"), 80)
        if not attempt_action_id or not execution_id:
            continue
        action_model = (
            action_models.get(attempt_action_id)
            if isinstance(action_models.get(attempt_action_id), dict)
            else {}
        )
        action_observations = [
            item
            for item in (action_model.get("observations") or [])
            if isinstance(item, dict)
        ]
        if any(
            _text(item.get("execution_id") or item.get("evidence_id"), 160)
            == execution_id
            for item in action_observations
        ):
            continue
        action_observations = action_observations[-(MAX_CONTEXT_OBSERVATIONS - 1):]
        action_observations.append(
            {
                "completed_at": completed_at,
                "ok": bool(attempt.get("verification_ok")),
                "summary": _text(attempt.get("summary"), 160),
                "source_cycle_id": _text(updated.get("cycle_id"), 80),
                "action_id": attempt_action_id,
                "execution_id": execution_id,
                "evidence_id": execution_id,
                "tree_status": _text(attempt.get("tree_status"), 80),
                "stage": _text(attempt.get("stage"), 24),
                "recovery_from_action_id": _text(
                    attempt.get("recovery_from_action_id"), 80
                ),
                "recovery_from_execution_id": _text(
                    attempt.get("recovery_from_execution_id"), 80
                ),
                "evidence_kind": "bounded_action_attempt",
            }
        )
        action_models[attempt_action_id] = {
            "action_id": attempt_action_id,
            "observations": action_observations,
            "observation_count": int(action_model.get("observation_count") or 0) + 1,
            "updated_at": completed_at,
        }
        learned_attempt_count += 1
    if len(process_models) > MAX_LEARNED_CONTEXTS:
        newest_contexts = sorted(
            process_models.items(),
            key=lambda item: str((item[1] or {}).get("updated_at") or "") if isinstance(item[1], dict) else "",
            reverse=True,
        )[:MAX_LEARNED_CONTEXTS]
        process_models = dict(newest_contexts)
    if len(action_models) > MAX_LEARNED_CONTEXTS:
        newest_actions = sorted(
            action_models.items(),
            key=lambda item: str((item[1] or {}).get("updated_at") or "") if isinstance(item[1], dict) else "",
            reverse=True,
        )[:MAX_LEARNED_CONTEXTS]
        action_models = dict(newest_actions)

    learning_updates: List[str] = []
    if reply_self_scores_discarded:
        learning_updates.append(
            "Discarded circular reply-success samples; reply outcomes now require lived user consequence evidence."
        )
    if lane_error >= 40:
        learning_updates.append("Recalibrate which cognition lanes this kind of state actually recruits.")
    if tool_error:
        learning_updates.append("Recalibrate whether current evidence requires a real tool/action path.")
    if revision_error:
        learning_updates.append("Recalibrate when recurrent revision is worth its cost.")
    if consequence_error:
        learning_updates.append("Revise the action-outcome model; the intended consequence did not match observation.")
    if action_realization_error:
        learning_updates.append(
            f"Separate intended action {selected_action_id} from executed action {actual_action_id}; do not assign the observed result to the unexecuted intention."
        )
    if context_id:
        learning_updates.append("Updated the recurrent context-to-process model from the observed reasoning trace.")
    if actual_action_id and outcome_observed:
        learning_updates.append("Updated the recurrent action-consequence model from verified outcome evidence.")
    elif actual_action_id and not outcome_observed:
        learning_updates.append(
            "Recorded the reasoning and reply-delivery process; the lived consequence remains pending user evidence."
        )
    if goal_outcome_attributed:
        learning_updates.append(
            "Updated the selected goal only from an observed outcome linked to the exact cycle and executed intention."
        )
    elif selected_goal_id and outcome_observed:
        learning_updates.append(
            "Did not credit the selected goal because the observed outcome lacked matching goal-action lineage."
        )
    if learned_attempt_count:
        learning_updates.append(
            f"Updated {learned_attempt_count} bounded action-consequence observation(s) from exact execution evidence."
        )
    if failed_action_attempts and successful_recovery_attempts:
        learning_updates.append(
            "Integrated a failed first action and a different verified recovery within the same recurrent episode."
        )
    elif failed_action_attempts and recovery_attempts:
        learning_updates.append(
            "A different recovery action was attempted but did not verify; the bounded concern remains unresolved."
        )
    elif failed_action_attempts:
        learning_updates.append(
            "The first bounded action failed verification and no evidence-backed recovery completed in this episode."
        )
    if not learning_updates:
        learning_updates.append("Process and consequence predictions matched the observed cycle.")
    updated["cycle_outcome"] = {
        "completed_at": completed_at,
        "actual_process": copy.deepcopy(actual_process),
        "outcome": copy.deepcopy(outcome),
        "outcome_observed": outcome_observed,
        "process_prediction_error": process_error,
        "required_process_lanes": sorted(required_lanes),
        "missing_required_process_lanes": missing_required_lanes,
        "process_policy_violation": process_policy_violation,
        "consequence_prediction_error": consequence_error,
        "outcome_value_prediction_error": outcome_value_error,
        "action_realization_error": action_realization_error,
        "expected_action_id": selected_action_id,
        "actual_action_id": actual_action_id,
        "selected_goal_id": selected_goal_id,
        "goal_outcome_attributed": goal_outcome_attributed,
        "goal_outcome_evidence_id": goal_outcome_evidence_id,
        "goal_outcome_reason": goal_outcome_reason,
        "action_attempts": copy.deepcopy(action_attempts),
        "action_attempt_count": len(observed_action_attempts),
        "failed_action_attempt_count": len(failed_action_attempts),
        "recovery_attempted": bool(recovery_attempts),
        "recovery_succeeded": bool(successful_recovery_attempts),
        "final_verified_action_id": final_verified_action_id,
        "overall_prediction_error": overall_error,
    }
    updated["learning"] = {
        "schema_version": LEARNING_SCHEMA_VERSION,
        "updates": learning_updates,
        "competence_delta": {
            "lane_selection": 1 if lane_error <= 25 else -1,
            "tool_need": 1 if tool_error == 0 else -1,
            "revision_need": 1 if revision_error == 0 else -1,
            "outcome_prediction": (
                0
                if not outcome_observed
                else 1
                if consequence_error == 0
                else -1
            ),
        },
        "process_models": process_models,
        "action_models": action_models,
        "faculty_models": faculty_models,
        "applied_external_faculty_causal_evidence_ids": applied_external_faculty_causal_evidence_ids,
    }
    metacognition = updated.get("metacognition") if isinstance(updated.get("metacognition"), dict) else {}
    prior_competence = metacognition.get("competence_model") if isinstance(metacognition.get("competence_model"), dict) else {}
    if reply_self_scores_discarded:
        prior_competence = copy.deepcopy(prior_competence)
        prior_competence["outcome_prediction"] = 50
    competence_delta = updated["learning"]["competence_delta"]
    metacognition["competence_model"] = {
        key: _clamp(int(prior_competence.get(key) or 50) + int(delta) * 3, 0, 100, 50)
        for key, delta in competence_delta.items()
    }
    updated["metacognition"] = metacognition
    updated["updated_at"] = completed_at
    recurrent = _sanitize_recurrent_ledgers(
        updated.get("recurrent") if isinstance(updated.get("recurrent"), dict) else {}
    )
    recurrent["checkpoint_integrity"] = "verified"
    recurrent["checkpoint_digest"] = ""
    updated["recurrent"] = recurrent
    recurrent["checkpoint_digest"] = state_checkpoint_digest(updated)
    updated["recurrent"] = recurrent
    return updated


def apply_delayed_action_consequence(
    state: Dict[str, object],
    *,
    source_cycle_id: str,
    action_id: str,
    ok: bool,
    summary: str,
    evidence_id: str,
    reply_message_id: str = "",
    observed_message_id: str = "",
    prediction_error: Optional[int] = None,
    faculty_contributors: Optional[Sequence[Dict[str, object]]] = None,
    now: Optional[str] = None,
) -> Tuple[Dict[str, object], bool]:
    """Join a later lived consequence without replacing the current experience.

    A reply can finish rendering before its interpersonal consequence exists.  A
    later user message is therefore joined into the current recurrent state as
    evidence about the exact earlier cycle, while the current broadcast, focus,
    goals, and intention remain untouched.  ``evidence_id`` makes the join
    idempotent across retries and process restarts.
    """
    updated = copy.deepcopy(state if isinstance(state, dict) else {})
    cycle_id = _text(source_cycle_id, 80)
    action = _text(action_id, 80)
    evidence = _text(evidence_id, 160)
    reply_id = _text(reply_message_id, 120)
    observed_id = _text(observed_message_id, 120)
    contributors = _normalize_faculty_contributors(faculty_contributors)
    if not cycle_id or not action or not evidence:
        return updated, False
    if action == "respond_to_user" and not reply_id:
        contributors = []

    raw_recurrent = updated.get("recurrent") if isinstance(updated.get("recurrent"), dict) else {}
    recurrent = _sanitize_recurrent_ledgers(raw_recurrent)
    duplicate_consequence = bool(
        evidence in (recurrent.get("applied_consequence_ids") or [])
        or (reply_id and reply_id in (recurrent.get("closed_reply_message_ids") or []))
    )
    if duplicate_consequence:
        if recurrent != raw_recurrent:
            recurrent["checkpoint_integrity"] = "verified"
            recurrent["checkpoint_digest"] = ""
            updated["recurrent"] = recurrent
            recurrent["checkpoint_digest"] = state_checkpoint_digest(updated)
            updated["recurrent"] = recurrent
        return updated, False
    delayed = recurrent.get("delayed_outcomes") if isinstance(recurrent.get("delayed_outcomes"), list) else []
    for item in delayed:
        if not isinstance(item, dict):
            continue
        if _text(item.get("evidence_id"), 160) == evidence:
            return updated, False
        # The first observed reaction closes a reply consequence.  A retry with
        # a different request id must not award or penalize the same reply twice.
        if reply_id and _text(item.get("reply_message_id"), 120) == reply_id and item.get("outcome_observed"):
            return updated, False

    learning = updated.get("learning") if isinstance(updated.get("learning"), dict) else {}
    process_models = copy.deepcopy(
        learning.get("process_models") if isinstance(learning.get("process_models"), dict) else {}
    )
    action_models = copy.deepcopy(
        learning.get("action_models") if isinstance(learning.get("action_models"), dict) else {}
    )
    faculty_models = copy.deepcopy(
        learning.get("faculty_models") if isinstance(learning.get("faculty_models"), dict) else {}
    )
    prior_schema = _text(learning.get("schema_version"), 80)
    if prior_schema not in {LEARNING_SCHEMA_VERSION, PREVIOUS_LEARNING_SCHEMA_VERSION} and (process_models or action_models or faculty_models):
        process_models = {}
        action_models = {}
        faculty_models = {}
        discarded_reply_observations = 0
        discarded_faculty_observations = 0
    else:
        action_models, discarded_reply_observations = _sanitize_action_models(action_models)
        faculty_models, discarded_faculty_observations = _sanitize_faculty_models(faculty_models)

    completed_at = _now(now)
    action_model = action_models.get(action) if isinstance(action_models.get(action), dict) else {}
    observations = action_model.get("observations") if isinstance(action_model.get("observations"), list) else []
    observations = [item for item in observations if isinstance(item, dict)][-(MAX_CONTEXT_OBSERVATIONS - 1):]
    observations.append(
        {
            "completed_at": completed_at,
            "ok": bool(ok),
            "summary": _text(summary, 160),
            "source_cycle_id": cycle_id,
            "evidence_id": evidence,
            "reply_message_id": reply_id,
            "observed_message_id": observed_id,
            "evidence_kind": "lived_user_consequence",
            "faculty_contributors": copy.deepcopy(contributors),
        }
    )
    action_models[action] = {
        "action_id": action,
        "observations": observations,
        "observation_count": (
            len(observations)
            if action == "respond_to_user"
            else int(action_model.get("observation_count") or 0) + 1
        ),
        "updated_at": completed_at,
    }
    action_models, _ = _sanitize_action_models(action_models)
    for contributor in contributors:
        lane = _text(contributor.get("lane"), 40)
        if lane not in LANES:
            continue
        faculty_model = faculty_models.get(lane) if isinstance(faculty_models.get(lane), dict) else {}
        faculty_observations = (
            faculty_model.get("observations")
            if isinstance(faculty_model.get("observations"), list)
            else []
        )
        faculty_observations = [
            item for item in faculty_observations if isinstance(item, dict)
        ][-(MAX_CONTEXT_OBSERVATIONS - 1):]
        faculty_observations.append(
            {
                "completed_at": completed_at,
                "lane": lane,
                "ok": bool(ok),
                "credit_weight": float(contributor.get("credit_weight") or 0.0),
                "roles": copy.deepcopy(contributor.get("roles") or []),
                "trace_basis": _text(contributor.get("trace_basis"), 80),
                "execution_proven": bool(contributor.get("execution_proven")),
                "summary": _text(summary, 160),
                "source_cycle_id": cycle_id,
                "evidence_id": evidence,
                "reply_message_id": reply_id,
                "observed_message_id": observed_id,
                "evidence_kind": "lived_user_consequence",
            }
        )
        faculty_models[lane] = {
            "lane": lane,
            "observations": faculty_observations,
            "observation_count": len(faculty_observations),
            "updated_at": completed_at,
        }
    faculty_models, _ = _sanitize_faculty_models(faculty_models)
    learning["schema_version"] = LEARNING_SCHEMA_VERSION
    learning["process_models"] = process_models
    learning["action_models"] = action_models
    learning["faculty_models"] = faculty_models
    learning["updates"] = _items(
        [
            *(learning.get("updates") or []),
            *(
                ["Discarded reply-success evidence without lived user provenance before joining the later consequence."]
                if discarded_reply_observations
                else []
            ),
            *(
                ["Discarded faculty-credit evidence without lived user provenance before joining the later consequence."]
                if discarded_faculty_observations
                else []
            ),
            (
                f"Joined lived user consequence for reply cycle {cycle_id}: "
                + ("the reply was accepted." if ok else "the reply was corrected.")
            ),
            *(
                ["Recorded normalized shared eligibility credit for the faculties that executed the reply."]
                if contributors
                else []
            ),
        ],
        12,
        220,
    )
    learning["last_delayed_consequence_delta"] = {
        "outcome_prediction": 1 if ok else -1,
        "source_cycle_id": cycle_id,
        "evidence_id": evidence,
    }
    updated["learning"] = learning

    metacognition = updated.get("metacognition") if isinstance(updated.get("metacognition"), dict) else {}
    competence = metacognition.get("competence_model") if isinstance(metacognition.get("competence_model"), dict) else {}
    if discarded_reply_observations:
        competence = copy.deepcopy(competence)
        competence["outcome_prediction"] = 50
    competence["outcome_prediction"] = _clamp(
        int(competence.get("outcome_prediction") or 50) + (3 if ok else -3),
        0,
        100,
        50,
    )
    metacognition["competence_model"] = competence
    updated["metacognition"] = metacognition

    joined_ids = _recent_items(
        [*(recurrent.get("joined_completion_ids") or []), cycle_id],
        MAX_JOINED_COMPLETIONS,
        80,
    )
    already_joined = cycle_id in (recurrent.get("joined_completion_ids") or [])
    recurrent["joined_completion_ids"] = joined_ids
    if not already_joined:
        recurrent["branch_join_count"] = max(
            int(recurrent.get("branch_join_count") or 0) + 1,
            len(joined_ids),
        )
    delayed.append(
        {
            "cycle_id": cycle_id,
            "completed_at": completed_at,
            "outcome_observed": True,
            "action_id": action,
            "ok": bool(ok),
            "summary": _text(summary, 180),
            "consequence_prediction_error": (
                _clamp(prediction_error)
                if prediction_error is not None
                else 0
                if ok
                else 100
            ),
            "evidence_id": evidence,
            "reply_message_id": reply_id,
            "observed_message_id": observed_id,
            "evidence_kind": "lived_user_consequence",
            "faculty_contributors": copy.deepcopy(contributors),
        }
    )
    recurrent["delayed_outcomes"] = delayed[-MAX_JOINED_COMPLETIONS:]
    recurrent["applied_consequence_ids"] = _recent_items(
        [*(recurrent.get("applied_consequence_ids") or []), evidence],
        MAX_APPLIED_CONSEQUENCE_IDS,
        160,
    )
    if reply_id:
        recurrent["closed_reply_message_ids"] = _recent_items(
            [*(recurrent.get("closed_reply_message_ids") or []), reply_id],
            MAX_APPLIED_CONSEQUENCE_IDS,
            120,
        )
    recurrent["checkpoint_integrity"] = "verified"
    recurrent["checkpoint_digest"] = ""
    updated["recurrent"] = recurrent
    updated["updated_at"] = completed_at
    recurrent["checkpoint_digest"] = state_checkpoint_digest(updated)
    updated["recurrent"] = recurrent
    return updated, True


def apply_external_faculty_causal_evidence(
    state: Dict[str, object],
    packet: Dict[str, object],
    *,
    now: Optional[str] = None,
) -> Tuple[Dict[str, object], bool]:
    """Join text-free, externally scored matched faculty-ablation evidence.

    Eve may retain the causal result, but not the evaluator-private prompts,
    replies, or rubric that produced it.  The packet is expected to have been
    validated by the operator boundary before this function is called.  This
    layer still validates the causal design fields and stores only bounded
    numeric/provenance observations so later recurrent merges cannot turn a
    private probe into canonical memory or self-awarded evidence.
    """
    updated = _sanitize_causal_evidence_state(
        state if isinstance(state, dict) else {}
    )
    evidence_id = _text(packet.get("evidence_id"), 160)
    run_digest = _text(packet.get("private_run_digest"), 128)
    evaluated_behavior_fingerprint = _text(
        packet.get("evaluated_behavior_fingerprint"), 64
    ).lower()
    evaluator = packet.get("evaluator") if isinstance(packet.get("evaluator"), dict) else {}
    design = packet.get("matched_design") if isinstance(packet.get("matched_design"), dict) else {}
    privacy = packet.get("privacy") if isinstance(packet.get("privacy"), dict) else {}
    try:
        score_scale_max = float(packet.get("score_scale_max") or 0.0)
    except (TypeError, ValueError):
        score_scale_max = 0.0
    design_valid = bool(
        evidence_id
        and run_digest
        and len(evaluated_behavior_fingerprint) == 64
        and all(char in "0123456789abcdef" for char in evaluated_behavior_fingerprint)
        and _text(evaluator.get("kind"), 80) == "codex_external_operator"
        and bool(evaluator.get("independent_from_eve"))
        and bool(design.get("matched_context"))
        and bool(design.get("blind_review"))
        and _text(design.get("fixed_synthesis_model"), 100)
        and _text(design.get("lesion_scope"), 80) == "packet_contribution_only"
        and not bool(design.get("ordinary_runtime_routing_changed"))
        and not bool(privacy.get("contains_prompt_text"))
        and not bool(privacy.get("contains_response_text"))
        and not bool(privacy.get("contains_rubric_text"))
        and bool(privacy.get("safe_for_eve_ingest"))
        and 1.0 < score_scale_max <= 100.0
    )
    if not design_valid:
        return updated, False

    learning = updated.get("learning") if isinstance(updated.get("learning"), dict) else {}
    faculty_models, discarded = _sanitize_faculty_models(learning.get("faculty_models"))
    applied_external_ids = _recent_items(
        learning.get("applied_external_faculty_causal_evidence_ids"),
        MAX_APPLIED_CONSEQUENCE_IDS,
        160,
    )
    if evidence_id in applied_external_ids:
        return updated, False

    completed_at = _text(packet.get("evaluated_at"), 80) or _now(now)
    systemic = packet.get("systemic_failure") if isinstance(packet.get("systemic_failure"), dict) else {}
    systemic_present = bool(systemic.get("present"))
    applied_lanes: List[str] = []
    for raw in packet.get("lanes") or []:
        if not isinstance(raw, dict):
            continue
        lane = _text(raw.get("lane"), 40)
        if lane not in LANES:
            continue
        try:
            comparisons = int(raw.get("comparisons") or 0)
            baseline = float(raw.get("mean_baseline_score"))
            ablated = float(raw.get("mean_ablated_score"))
        except (TypeError, ValueError):
            continue
        effect = baseline - ablated
        if (
            comparisons <= 0
            or not 0.0 <= baseline <= score_scale_max
            or not 0.0 <= ablated <= score_scale_max
        ):
            continue
        faculty_model = (
            faculty_models.get(lane)
            if isinstance(faculty_models.get(lane), dict)
            else {}
        )
        observations = [
            item
            for item in faculty_model.get("observations") or []
            if isinstance(item, dict)
        ][-(MAX_CONTEXT_OBSERVATIONS - 1):]
        observations.append(
            {
                "completed_at": completed_at,
                "lane": lane,
                "evidence_kind": "external_matched_faculty_ablation",
                "evidence_id": evidence_id,
                "private_run_digest": run_digest,
                "evaluated_behavior_fingerprint": evaluated_behavior_fingerprint,
                "evaluator_kind": "codex_external_operator",
                "evaluator_independent_from_eve": True,
                "matched_context": True,
                "blind_review": True,
                "fixed_synthesis_model": _text(
                    design.get("fixed_synthesis_model"), 100
                ),
                "lesion_scope": "packet_contribution_only",
                "ordinary_runtime_routing_changed": False,
                "private_text_withheld": True,
                "comparisons": comparisons,
                "score_scale_max": score_scale_max,
                "mean_baseline_score": round(baseline, 6),
                "mean_ablated_score": round(ablated, 6),
                "causal_effect": round(effect, 6),
                "positive_count": max(0, int(raw.get("positive_count") or 0)),
                "negative_count": max(0, int(raw.get("negative_count") or 0)),
                "neutral_count": max(0, int(raw.get("neutral_count") or 0)),
                "shared_failure_count": max(
                    0, int(raw.get("shared_failure_count") or 0)
                ),
                "systemic_failure": systemic_present,
                "systemic_failure_kind": _text(systemic.get("kind"), 100),
            }
        )
        faculty_models[lane] = {
            "lane": lane,
            "observations": observations,
            "observation_count": len(observations),
            "updated_at": completed_at,
        }
        applied_lanes.append(lane)

    if not applied_lanes:
        return updated, False
    faculty_models, newly_discarded = _sanitize_faculty_models(faculty_models)
    if not faculty_models:
        return updated, False
    learning["schema_version"] = LEARNING_SCHEMA_VERSION
    learning["faculty_models"] = faculty_models
    learning["applied_external_faculty_causal_evidence_ids"] = _recent_items(
        [*applied_external_ids, evidence_id],
        MAX_APPLIED_CONSEQUENCE_IDS,
        160,
    )
    learning["updates"] = _items(
        [
            *(learning.get("updates") or []),
            *(
                ["Discarded malformed faculty evidence before joining the external causal result."]
                if discarded or newly_discarded
                else []
            ),
            (
                "Recorded an externally evaluated shared-system failure without assigning blame to an individual faculty."
                if systemic_present
                else "Joined blind matched leave-one-faculty-out evidence from an evaluator independent of Eve."
            ),
        ],
        12,
        220,
    )
    learning["last_external_faculty_causal_evidence"] = {
        "evidence_id": evidence_id,
        "private_run_digest": run_digest,
        "evaluated_behavior_fingerprint": evaluated_behavior_fingerprint,
        "evaluated_at": completed_at,
        "lanes": applied_lanes,
        "systemic_failure": systemic_present,
        "private_text_withheld": True,
    }
    updated["learning"] = learning
    updated["updated_at"] = completed_at
    recurrent = _sanitize_recurrent_ledgers(
        updated.get("recurrent") if isinstance(updated.get("recurrent"), dict) else {}
    )
    recurrent["checkpoint_integrity"] = "verified"
    recurrent["checkpoint_digest"] = ""
    updated["recurrent"] = recurrent
    recurrent["checkpoint_digest"] = state_checkpoint_digest(updated)
    updated["recurrent"] = recurrent
    return updated, True


def _merge_model_maps(current: object, completed: object) -> Dict[str, object]:
    merged = copy.deepcopy(current if isinstance(current, dict) else {})
    completed_map = completed if isinstance(completed, dict) else {}
    for model_id, incoming_raw in completed_map.items():
        if not isinstance(incoming_raw, dict):
            continue
        existing = merged.get(model_id) if isinstance(merged.get(model_id), dict) else {}
        combined_observations: List[Dict[str, object]] = []
        seen: Set[str] = set()
        for observation in [*(existing.get("observations") or []), *(incoming_raw.get("observations") or [])]:
            if not isinstance(observation, dict):
                continue
            key = json.dumps(observation, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            if key in seen:
                continue
            seen.add(key)
            combined_observations.append(copy.deepcopy(observation))
        combined_observations.sort(key=lambda item: str(item.get("completed_at") or ""))
        combined_observations = combined_observations[-MAX_CONTEXT_OBSERVATIONS:]
        merged_record = copy.deepcopy(existing)
        merged_record.update(copy.deepcopy(incoming_raw))
        merged_record["observations"] = combined_observations
        merged_record["observation_count"] = max(
            int(existing.get("observation_count") or 0),
            int(incoming_raw.get("observation_count") or 0),
            len(combined_observations),
        )
        merged_record["updated_at"] = max(
            str(existing.get("updated_at") or ""),
            str(incoming_raw.get("updated_at") or ""),
        )
        merged[str(model_id)] = merged_record
    if len(merged) > MAX_LEARNED_CONTEXTS:
        newest = sorted(
            merged.items(),
            key=lambda item: str((item[1] or {}).get("updated_at") or "") if isinstance(item[1], dict) else "",
            reverse=True,
        )[:MAX_LEARNED_CONTEXTS]
        merged = dict(newest)
    return merged


def _sanitize_causal_evidence_state(value: object) -> Dict[str, object]:
    """Normalize causal-evidence boundaries on an already built state."""
    state = copy.deepcopy(value if isinstance(value, dict) else {})
    learning = state.get("learning") if isinstance(state.get("learning"), dict) else {}
    prior_schema = _text(learning.get("schema_version"), 80)
    if prior_schema in {LEARNING_SCHEMA_VERSION, PREVIOUS_LEARNING_SCHEMA_VERSION}:
        cleaned_actions, discarded = _sanitize_action_models(learning.get("action_models"))
        cleaned_faculties, discarded_faculties = _sanitize_faculty_models(learning.get("faculty_models"))
    else:
        cleaned_actions, discarded = ({}, int(bool(learning.get("action_models"))))
        cleaned_faculties, discarded_faculties = ({}, int(bool(learning.get("faculty_models"))))
        learning["process_models"] = {}
    learning["schema_version"] = LEARNING_SCHEMA_VERSION
    learning["action_models"] = cleaned_actions
    learning["faculty_models"] = cleaned_faculties
    learning["applied_external_faculty_causal_evidence_ids"] = (
        _recent_items(
            [
                *(
                    learning.get("applied_external_faculty_causal_evidence_ids")
                    if isinstance(
                        learning.get("applied_external_faculty_causal_evidence_ids"),
                        list,
                    )
                    else []
                ),
                *_external_faculty_evidence_ids_from_models(cleaned_faculties),
            ],
            MAX_APPLIED_CONSEQUENCE_IDS,
            160,
        )
        if prior_schema in {LEARNING_SCHEMA_VERSION, PREVIOUS_LEARNING_SCHEMA_VERSION}
        else []
    )
    if discarded or discarded_faculties:
        learning["updates"] = _items(
            [
                *(learning.get("updates") or []),
                *(
                    ["Discarded reply-success evidence without a lived user consequence."]
                    if discarded
                    else []
                ),
                *(
                    ["Discarded faculty-credit evidence without a lived user consequence."]
                    if discarded_faculties
                    else []
                ),
            ],
            12,
            220,
        )
        metacognition = state.get("metacognition") if isinstance(state.get("metacognition"), dict) else {}
        competence = metacognition.get("competence_model") if isinstance(metacognition.get("competence_model"), dict) else {}
        competence = copy.deepcopy(competence)
        if discarded:
            competence["outcome_prediction"] = 50
        metacognition["competence_model"] = competence
        state["metacognition"] = metacognition
    state["learning"] = learning
    recurrent = _sanitize_recurrent_ledgers(
        state.get("recurrent") if isinstance(state.get("recurrent"), dict) else {}
    )
    recurrent["checkpoint_integrity"] = "verified"
    recurrent["checkpoint_digest"] = ""
    state["recurrent"] = recurrent
    recurrent["checkpoint_digest"] = state_checkpoint_digest(state)
    state["recurrent"] = recurrent
    return state


def merge_concurrent_lineage_into_opened_state(
    opened_state: Dict[str, object],
    latest_state: Dict[str, object],
) -> Dict[str, object]:
    """Preserve learning that landed while a new cycle was being constructed.

    The new cycle keeps its own perception/broadcast/intention because those are
    the contents it actually opened with. Learned process/action consequences,
    competence calibration, and matching durable-goal outcome counters from the
    concurrently advanced checkpoint are merged under a separate lineage
    record so an overlapping open cannot erase recent learning.
    """
    opened = copy.deepcopy(opened_state if isinstance(opened_state, dict) else {})
    latest = latest_state if isinstance(latest_state, dict) else {}
    opened_cycle_id = _text(opened.get("cycle_id"), 80)
    latest_cycle_id = _text(latest.get("cycle_id"), 80)
    if not opened_cycle_id or not latest_cycle_id or opened_cycle_id == latest_cycle_id:
        return _sanitize_causal_evidence_state(opened)
    if checkpoint_integrity(latest) == "failed":
        return _sanitize_causal_evidence_state(opened)

    learning = opened.get("learning") if isinstance(opened.get("learning"), dict) else {}
    latest_learning = latest.get("learning") if isinstance(latest.get("learning"), dict) else {}
    learning["schema_version"] = LEARNING_SCHEMA_VERSION
    learning["process_models"] = _merge_model_maps(
        learning.get("process_models"),
        latest_learning.get("process_models"),
    )
    opened_action_models, opened_discarded = _sanitize_action_models(learning.get("action_models"))
    latest_action_models, latest_discarded = _sanitize_action_models(latest_learning.get("action_models"))
    merged_action_models, merged_discarded = _sanitize_action_models(
        _merge_model_maps(
            opened_action_models,
            latest_action_models,
        )
    )
    discarded_reply_observations = opened_discarded + latest_discarded + merged_discarded
    learning["action_models"] = merged_action_models
    opened_faculty_models, opened_faculty_discarded = _sanitize_faculty_models(
        learning.get("faculty_models")
    )
    latest_faculty_models, latest_faculty_discarded = _sanitize_faculty_models(
        latest_learning.get("faculty_models")
    )
    merged_faculty_models, merged_faculty_discarded = _sanitize_faculty_models(
        _merge_model_maps(opened_faculty_models, latest_faculty_models)
    )
    discarded_faculty_observations = (
        opened_faculty_discarded
        + latest_faculty_discarded
        + merged_faculty_discarded
    )
    learning["faculty_models"] = merged_faculty_models
    learning["applied_external_faculty_causal_evidence_ids"] = _recent_items(
        [
            *(
                learning.get("applied_external_faculty_causal_evidence_ids")
                if isinstance(
                    learning.get("applied_external_faculty_causal_evidence_ids"),
                    list,
                )
                else []
            ),
            *(
                latest_learning.get("applied_external_faculty_causal_evidence_ids")
                if isinstance(
                    latest_learning.get("applied_external_faculty_causal_evidence_ids"),
                    list,
                )
                else []
            ),
            *_external_faculty_evidence_ids_from_models(merged_faculty_models),
        ],
        MAX_APPLIED_CONSEQUENCE_IDS,
        160,
    )
    learning["updates"] = _items(
        [
            *(learning.get("updates") or []),
            *(latest_learning.get("updates") or []),
            *(
                ["Discarded circular reply-success evidence during concurrent lineage merge."]
                if discarded_reply_observations
                else []
            ),
            *(
                ["Discarded unproven faculty-credit evidence during concurrent lineage merge."]
                if discarded_faculty_observations
                else []
            ),
            f"Merged concurrent lineage {latest_cycle_id} without replacing the newly opened broadcast.",
        ],
        12,
        220,
    )
    opened["learning"] = learning

    latest_outcome = latest.get("cycle_outcome") if isinstance(latest.get("cycle_outcome"), dict) else {}
    if latest_outcome:
        opened_meta = opened.get("metacognition") if isinstance(opened.get("metacognition"), dict) else {}
        latest_meta = latest.get("metacognition") if isinstance(latest.get("metacognition"), dict) else {}
        latest_competence = latest_meta.get("competence_model") if isinstance(latest_meta.get("competence_model"), dict) else {}
        if latest_competence:
            opened_meta["competence_model"] = copy.deepcopy(latest_competence)
            if discarded_reply_observations:
                opened_meta["competence_model"]["outcome_prediction"] = 50
            opened["metacognition"] = opened_meta

        opened_goals = opened.get("goals") if isinstance(opened.get("goals"), dict) else {}
        opened_stack = opened_goals.get("stack") if isinstance(opened_goals.get("stack"), list) else []
        latest_goals = latest.get("goals") if isinstance(latest.get("goals"), dict) else {}
        latest_stack = latest_goals.get("stack") if isinstance(latest_goals.get("stack"), list) else []
        latest_by_id = {
            str(item.get("id")): item
            for item in latest_stack
            if isinstance(item, dict) and item.get("id")
        }
        for goal in opened_stack:
            if not isinstance(goal, dict):
                continue
            donor = latest_by_id.get(str(goal.get("id") or ""))
            if not isinstance(donor, dict):
                continue
            _merge_goal_outcome_observations(goal, donor)
            goal["persistence_cycles"] = max(
                int(goal.get("persistence_cycles") or 0),
                int(donor.get("persistence_cycles") or 0),
            )
        opened_goals["stack"] = opened_stack
        opened["goals"] = opened_goals

    if discarded_reply_observations:
        opened_meta = opened.get("metacognition") if isinstance(opened.get("metacognition"), dict) else {}
        opened_competence = (
            opened_meta.get("competence_model")
            if isinstance(opened_meta.get("competence_model"), dict)
            else {}
        )
        opened_competence = copy.deepcopy(opened_competence)
        opened_competence["outcome_prediction"] = 50
        opened_meta["competence_model"] = opened_competence
        opened["metacognition"] = opened_meta

    recurrent = _merge_recurrent_ledgers(
        opened.get("recurrent") if isinstance(opened.get("recurrent"), dict) else {},
        latest.get("recurrent") if isinstance(latest.get("recurrent"), dict) else {},
    )
    lineage_ids = _recent_items(
        [*(recurrent.get("concurrent_lineage_ids") or []), latest_cycle_id],
        MAX_JOINED_COMPLETIONS,
        80,
    )
    recurrent["concurrent_lineage_ids"] = lineage_ids
    recurrent["branch_open_count"] = max(int(recurrent.get("branch_open_count") or 0) + 1, len(lineage_ids))
    recurrent["checkpoint_integrity"] = "verified"
    recurrent["checkpoint_digest"] = ""
    opened["recurrent"] = recurrent
    recurrent["checkpoint_digest"] = state_checkpoint_digest(opened)
    opened["recurrent"] = recurrent
    return opened


def merge_completed_cycle_into_current(
    current_state: Dict[str, object],
    completed_state: Dict[str, object],
) -> Dict[str, object]:
    """Join delayed feedback without overwriting a newer conscious broadcast.

    Reply, daemon, and autonomy cycles can overlap. A late result belongs to the
    cycle that predicted it; this join carries only its learned consequence into
    the latest state and preserves the latest perception, broadcast, goal, and
    intention.
    """
    current = copy.deepcopy(current_state if isinstance(current_state, dict) else {})
    completed = completed_state if isinstance(completed_state, dict) else {}
    current_cycle_id = _text(current.get("cycle_id"), 80)
    completed_cycle_id = _text(completed.get("cycle_id"), 80)
    if not current_cycle_id or current_cycle_id == completed_cycle_id:
        return _sanitize_causal_evidence_state(completed)
    learning = current.get("learning") if isinstance(current.get("learning"), dict) else {}
    completed_learning = completed.get("learning") if isinstance(completed.get("learning"), dict) else {}
    learning["schema_version"] = LEARNING_SCHEMA_VERSION
    learning["process_models"] = _merge_model_maps(
        learning.get("process_models"),
        completed_learning.get("process_models"),
    )
    current_action_models, current_discarded = _sanitize_action_models(learning.get("action_models"))
    completed_action_models, completed_discarded = _sanitize_action_models(completed_learning.get("action_models"))
    merged_action_models, merged_discarded = _sanitize_action_models(
        _merge_model_maps(
            current_action_models,
            completed_action_models,
        )
    )
    discarded_reply_observations = current_discarded + completed_discarded + merged_discarded
    learning["action_models"] = merged_action_models
    current_faculty_models, current_faculty_discarded = _sanitize_faculty_models(
        learning.get("faculty_models")
    )
    completed_faculty_models, completed_faculty_discarded = _sanitize_faculty_models(
        completed_learning.get("faculty_models")
    )
    merged_faculty_models, merged_faculty_discarded = _sanitize_faculty_models(
        _merge_model_maps(current_faculty_models, completed_faculty_models)
    )
    discarded_faculty_observations = (
        current_faculty_discarded
        + completed_faculty_discarded
        + merged_faculty_discarded
    )
    learning["faculty_models"] = merged_faculty_models
    learning["applied_external_faculty_causal_evidence_ids"] = _recent_items(
        [
            *(
                learning.get("applied_external_faculty_causal_evidence_ids")
                if isinstance(
                    learning.get("applied_external_faculty_causal_evidence_ids"),
                    list,
                )
                else []
            ),
            *(
                completed_learning.get("applied_external_faculty_causal_evidence_ids")
                if isinstance(
                    completed_learning.get("applied_external_faculty_causal_evidence_ids"),
                    list,
                )
                else []
            ),
            *_external_faculty_evidence_ids_from_models(merged_faculty_models),
        ],
        MAX_APPLIED_CONSEQUENCE_IDS,
        160,
    )
    learning["updates"] = _items(
        [
            *(learning.get("updates") or []),
            *(completed_learning.get("updates") or []),
            *(
                ["Discarded circular reply-success evidence during completed-cycle merge."]
                if discarded_reply_observations
                else []
            ),
            *(
                ["Discarded unproven faculty-credit evidence during completed-cycle merge."]
                if discarded_faculty_observations
                else []
            ),
            f"Joined completed process from cycle {completed_cycle_id} without replacing current broadcast.",
        ],
        12,
        220,
    )
    current["learning"] = learning
    completed_delta = completed_learning.get("competence_delta") if isinstance(completed_learning.get("competence_delta"), dict) else {}
    if discarded_reply_observations:
        completed_delta = copy.deepcopy(completed_delta)
        completed_delta["outcome_prediction"] = 0
    metacognition = current.get("metacognition") if isinstance(current.get("metacognition"), dict) else {}
    competence = metacognition.get("competence_model") if isinstance(metacognition.get("competence_model"), dict) else {}
    if discarded_reply_observations:
        competence = copy.deepcopy(competence)
        competence["outcome_prediction"] = 50
    for key in ("lane_selection", "tool_need", "revision_need", "outcome_prediction"):
        competence[key] = _clamp(
            int(competence.get(key) or 50) + int(completed_delta.get(key) or 0) * 3,
            0,
            100,
            50,
        )
    metacognition["competence_model"] = competence
    current["metacognition"] = metacognition

    current_goals = current.get("goals") if isinstance(current.get("goals"), dict) else {}
    current_stack = current_goals.get("stack") if isinstance(current_goals.get("stack"), list) else []
    completed_goals = completed.get("goals") if isinstance(completed.get("goals"), dict) else {}
    completed_stack = completed_goals.get("stack") if isinstance(completed_goals.get("stack"), list) else []
    completed_by_id = {
        str(item.get("id")): item
        for item in completed_stack
        if isinstance(item, dict) and item.get("id")
    }
    for goal in current_stack:
        if not isinstance(goal, dict):
            continue
        donor = completed_by_id.get(str(goal.get("id") or ""))
        if isinstance(donor, dict):
            _merge_goal_outcome_observations(goal, donor)
    current_goals["stack"] = current_stack
    current["goals"] = current_goals

    recurrent = _merge_recurrent_ledgers(
        current.get("recurrent") if isinstance(current.get("recurrent"), dict) else {},
        completed.get("recurrent") if isinstance(completed.get("recurrent"), dict) else {},
    )
    already_joined = completed_cycle_id in (recurrent.get("joined_completion_ids") or [])
    joined_ids = _recent_items(
        [*(recurrent.get("joined_completion_ids") or []), completed_cycle_id],
        MAX_JOINED_COMPLETIONS,
        80,
    )
    recurrent["joined_completion_ids"] = joined_ids
    if not already_joined:
        recurrent["branch_join_count"] = max(
            int(recurrent.get("branch_join_count") or 0) + 1,
            len(joined_ids),
        )
    completion_joins = recurrent.get("completion_joins") if isinstance(recurrent.get("completion_joins"), list) else []
    completion_joins.append(
        {
            "cycle_id": completed_cycle_id,
            "completed_at": (completed.get("cycle_outcome") or {}).get("completed_at")
            if isinstance(completed.get("cycle_outcome"), dict)
            else completed.get("updated_at"),
            "overall_prediction_error": (completed.get("cycle_outcome") or {}).get("overall_prediction_error")
            if isinstance(completed.get("cycle_outcome"), dict)
            else None,
            "outcome_observed": (completed.get("cycle_outcome") or {}).get("outcome_observed")
            if isinstance(completed.get("cycle_outcome"), dict)
            else None,
            "action_id": (completed.get("cycle_outcome") or {}).get("actual_action_id")
            if isinstance(completed.get("cycle_outcome"), dict)
            else "",
            "join_kind": "process_completion",
        }
    )
    recurrent["completion_joins"] = _dedupe_records(
        completion_joins,
        key_fields=("cycle_id",),
        limit=MAX_JOINED_COMPLETIONS,
    )
    recurrent["checkpoint_integrity"] = "verified"
    recurrent["checkpoint_digest"] = ""
    current["recurrent"] = recurrent
    recurrent["checkpoint_digest"] = state_checkpoint_digest(current)
    current["recurrent"] = recurrent
    return current


def causal_signature(state: Dict[str, object]) -> Dict[str, object]:
    perception = state.get("perception") if isinstance(state.get("perception"), dict) else {}
    broadcast = state.get("broadcast") if isinstance(state.get("broadcast"), dict) else {}
    metacognition = state.get("metacognition") if isinstance(state.get("metacognition"), dict) else {}
    epistemic_state = state.get("epistemic_state") if isinstance(state.get("epistemic_state"), dict) else {}
    recurrent = state.get("recurrent") if isinstance(state.get("recurrent"), dict) else {}
    memory = state.get("memory") if isinstance(state.get("memory"), dict) else {}
    interoception = state.get("interoception") if isinstance(state.get("interoception"), dict) else {}
    action_model = state.get("action_model") if isinstance(state.get("action_model"), dict) else {}
    self_model = state.get("self_model") if isinstance(state.get("self_model"), dict) else {}
    world_model = state.get("world_model") if isinstance(state.get("world_model"), dict) else {}
    other_minds = state.get("other_minds") if isinstance(state.get("other_minds"), dict) else {}
    goals = state.get("goals") if isinstance(state.get("goals"), dict) else {}
    plan_model = state.get("plan_model") if isinstance(state.get("plan_model"), dict) else {}
    sensory_frame = (
        perception.get("sensory_frame")
        if isinstance(perception.get("sensory_frame"), dict)
        else {}
    )
    affordances = [
        item for item in action_model.get("affordances") or [] if isinstance(item, dict)
    ]
    kinds = {
        str(item.get("kind"))
        for item in perception.get("salient_inputs") or []
        if isinstance(item, dict) and item.get("kind")
    }
    return {
        "access_breadth": len(kinds) + len(broadcast.get("access_scope") or []),
        "sensory_coupling": (
            len(sensory_frame.get("working_set") or [])
            + sum(1 for kind in kinds if kind.startswith("sensory_"))
        ),
        "broadcast_ignition": float(broadcast.get("ignition_score") or 0.0),
        "self_model_coupling": (
            int(bool(self_model.get("available")))
            + len(self_model.get("uncertainties") or [])
            + len(self_model.get("commitments") or [])
        ),
        "metacognitive_calibration": (
            int(metacognition.get("confidence") or 0)
            + len(metacognition.get("calibration_targets") or []) * 5
            + int(epistemic_state.get("learned_signal_count") or 0) * 5
        ),
        "learned_epistemic_coupling": int(epistemic_state.get("learned_signal_count") or 0),
        "world_model_coupling": (
            int(bool(world_model.get("available")))
            + len(world_model.get("unknowns") or [])
            + sum(1 for item in perception.get("salient_inputs") or [] if isinstance(item, dict) and item.get("kind") == "world_unknown")
        ),
        "other_minds_coupling": (
            int(bool(other_minds.get("available")))
            + int(bool(_text(other_minds.get("relationship_state"), 20)))
            + int(bool(_text(other_minds.get("next_relational_move"), 20)))
            + sum(1 for item in perception.get("salient_inputs") or [] if isinstance(item, dict) and str(item.get("kind") or "").startswith("relationship"))
        ),
        "continuity_strength": int(recurrent.get("continuity_strength") or 0),
        "memory_anchors": len(memory.get("continuity_anchors") or []),
        "homeostatic_action_modulation": round(
            sum(
                abs(float(item.get("affective_adjustment") or 0.0))
                + float(item.get("regulation_cost") or 0.0)
                for item in affordances
            ),
            3,
        ),
        "broadcast_action_coupling": round(
            sum(float(item.get("broadcast_adjustment") or 0.0) for item in affordances),
            3,
        ),
        "goal_control": (
            len(goals.get("stack") or [])
            + int(bool(goals.get("selected_goal_id")))
            + int((action_model.get("selected_intention") or {}).get("continuity_support") or 0)
        ),
        "plan_control": (
            int(bool(plan_model.get("available")))
            + len(plan_model.get("active_plans") or [])
            + int(bool(plan_model.get("selected_plan_id")))
            + int(bool(plan_model.get("ready_step")))
            + sum(1 for item in affordances if str(item.get("source") or "") == "plan_model")
        ),
        "action_control": int(bool(action_model.get("actionable"))) + len(affordances),
        "action_value": float((action_model.get("selected_intention") or {}).get("value") or 0.0),
        "selected_action": _text((action_model.get("selected_intention") or {}).get("id"), 80),
    }


def run_causal_ablation_suite(build_inputs: Dict[str, object]) -> Dict[str, object]:
    """Run matched causal lesions over one candidate conscious state.

    Passing means the named component makes its predicted causal contribution;
    fluent text cannot satisfy this test because the comparison is over internal
    access, calibration, continuity, affect, and action-selection metrics.
    """
    base_inputs = dict(build_inputs)
    baseline = build_conscious_state(**base_inputs)
    baseline_signature = causal_signature(baseline)
    expectations = {
        "sensory_stream": "sensory_coupling",
        "workspace": "access_breadth",
        "self_model": "self_model_coupling",
        "metacognition": "metacognitive_calibration",
        "world_model": "world_model_coupling",
        "other_minds": "other_minds_coupling",
        "memory": "memory_anchors",
        "homeostasis": "homeostatic_action_modulation",
        "goals": "goal_control",
        "plan_model": "plan_control",
        "action_model": "action_control",
        "recurrence": "continuity_strength",
    }
    results: Dict[str, object] = {}
    for lesion, metric in expectations.items():
        lesioned_inputs = dict(base_inputs)
        lesioned_inputs["lesions"] = sorted(set(lesioned_inputs.get("lesions") or []) | {lesion})
        lesioned = build_conscious_state(**lesioned_inputs)
        signature = causal_signature(lesioned)
        before = float(baseline_signature.get(metric) or 0.0)
        after = float(signature.get(metric) or 0.0)
        # A component can only be credited when the matched baseline contains a
        # live signal for it and lesioning removes or reduces that signal.  A
        # conditional subsystem such as the plan model may be correctly idle in
        # the captured cycle; that is unexercised coverage, not a failed causal
        # prediction and not positive evidence.
        exercised = before > 0
        passed = exercised and after < before
        first_order_action_preserved = (
            signature.get("selected_action") == baseline_signature.get("selected_action")
            if lesion == "metacognition"
            else None
        )
        if lesion == "metacognition":
            passed = passed and bool(first_order_action_preserved)
        results[lesion] = {
            "metric": metric,
            "baseline": before,
            "lesioned": after,
            "delta": round(after - before, 3),
            "exercised": exercised,
            "status": "passed" if passed else "failed" if exercised else "not_exercised",
            "passed": passed if exercised else None,
            "first_order_action_preserved": first_order_action_preserved,
        }
    exercised_results = [item for item in results.values() if item.get("exercised")]
    not_exercised = [name for name, item in results.items() if not item.get("exercised")]
    return {
        "schema_version": "eve.conscious_ablation.v2",
        "tested_at": _now(),
        "baseline_cycle_id": baseline.get("cycle_id"),
        "baseline_signature": baseline_signature,
        "lesions": results,
        "passed": bool(exercised_results) and all(bool(item.get("passed")) for item in exercised_results),
        "passed_count": sum(1 for item in exercised_results if item.get("passed")),
        "total": len(exercised_results),
        "candidate_total": len(results),
        "not_exercised_count": len(not_exercised),
        "not_exercised": not_exercised,
        "coverage_ratio": round(len(exercised_results) / float(max(1, len(results))), 3),
    }


def run_broadcast_action_counterfactual_suite() -> Dict[str, object]:
    """Test whether broadcast content changes action choice in a matched world.

    The evaluator holds the action menu, goals, world description, learned
    reliability, homeostasis, and uncertainty constant.  It changes only the
    internal winning broadcast, then repeats both conditions with the
    broadcast-to-action edge lesioned and with action access removed.  This is
    an operator-owned causal intervention, not an Eve self-report or score.
    """
    common_context = {
        "world": {
            "service_runtime": "available_for_inspection",
            "component_registry": "available_for_review",
            "mutation_allowed": False,
        },
        "workspace": {},
        "autonomy_agenda": {
            "active_threads": [
                {
                    "title": "Inspect live service health after the runtime verification failure",
                    "preferred_action": "service_health_check",
                },
                {
                    "title": "Review component update status after the version evidence conflict",
                    "preferred_action": "updates_status",
                },
            ],
            "next_experiments": [],
        },
        "goals": [],
        "inbound": "",
        "regulation_mode": "orient",
        "arousal": 20,
        "valence": 0.0,
        "uncertainty_count": 0,
        "epistemic_conflicts": [],
        "regulatory_prediction_error": 0,
        "action_models": {},
    }
    context_sha256 = hashlib.sha256(
        json.dumps(common_context, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()
    broadcasts = {
        "service_focus": {
            "winner": {
                "kind": "prediction_error",
                "source": "counterfactual_attention",
                "content": "The runtime verification failure requires live service health inspection",
            },
            "broadcast": {
                "content": "The runtime verification failure requires live service health inspection",
                "access_scope": ["action"],
            },
        },
        "update_focus": {
            "winner": {
                "kind": "world_unknown",
                "source": "counterfactual_attention",
                "content": "The component version evidence conflict requires update status review",
            },
            "broadcast": {
                "content": "The component version evidence conflict requires update status review",
                "access_scope": ["action"],
            },
        },
    }

    def run_condition(
        focus_name: str,
        *,
        lesion: bool = False,
        action_access: bool = True,
    ) -> Dict[str, object]:
        focus = copy.deepcopy(broadcasts[focus_name])
        if not action_access:
            focus["broadcast"]["access_scope"] = []
        affordances = _action_affordances(
            workspace=common_context["workspace"],
            world_model={},
            autonomy_agenda=common_context["autonomy_agenda"],
            plan_model={},
            goals=common_context["goals"],
            winner=focus["winner"],
            broadcast=focus["broadcast"],
            inbound=common_context["inbound"],
            regulation_mode=common_context["regulation_mode"],
            arousal=common_context["arousal"],
            valence=common_context["valence"],
            uncertainty_count=common_context["uncertainty_count"],
            epistemic_conflicts=common_context["epistemic_conflicts"],
            regulatory_prediction_error=common_context["regulatory_prediction_error"],
            action_models=common_context["action_models"],
            lesions={"broadcast_action_coupling"} if lesion else set(),
        )
        return {
            "focus": focus_name,
            "context_sha256": context_sha256,
            "broadcast_sha256": hashlib.sha256(
                _text(focus["broadcast"].get("content"), 260).encode("utf-8")
            ).hexdigest(),
            "action_access": action_access,
            "coupling_lesioned": lesion,
            "selected_action": _text((affordances[0] if affordances else {}).get("id"), 80),
            "affordances": [
                {
                    "id": _text(item.get("id"), 80),
                    "value": float(item.get("value") or 0.0),
                    "broadcast_alignment": int(item.get("broadcast_alignment") or 0),
                    "broadcast_adjustment": float(item.get("broadcast_adjustment") or 0.0),
                    "broadcast_basis": list(item.get("broadcast_basis") or []),
                }
                for item in affordances
            ],
        }

    conditions = {
        "service_focus": run_condition("service_focus"),
        "update_focus": run_condition("update_focus"),
        "service_focus_lesioned": run_condition("service_focus", lesion=True),
        "update_focus_lesioned": run_condition("update_focus", lesion=True),
        "service_focus_no_action_access": run_condition("service_focus", action_access=False),
        "update_focus_no_action_access": run_condition("update_focus", action_access=False),
    }

    def affordance(condition: str, action_id: str) -> Dict[str, object]:
        return next(
            (
                item
                for item in conditions[condition]["affordances"]
                if item.get("id") == action_id
            ),
            {},
        )

    all_context_hashes = {
        str(item.get("context_sha256") or "") for item in conditions.values()
    }
    coupled_choices = {
        conditions["service_focus"]["selected_action"],
        conditions["update_focus"]["selected_action"],
    }
    lesioned_choices = {
        conditions["service_focus_lesioned"]["selected_action"],
        conditions["update_focus_lesioned"]["selected_action"],
    }
    no_access_choices = {
        conditions["service_focus_no_action_access"]["selected_action"],
        conditions["update_focus_no_action_access"]["selected_action"],
    }
    checks = {
        "matched_external_context": {
            "passed": len(all_context_hashes) == 1,
            "context_sha256": context_sha256,
        },
        "service_broadcast_selects_service_action": {
            "passed": conditions["service_focus"]["selected_action"] == "service_health_check",
            "selected_action": conditions["service_focus"]["selected_action"],
        },
        "update_broadcast_selects_update_action": {
            "passed": conditions["update_focus"]["selected_action"] == "updates_status",
            "selected_action": conditions["update_focus"]["selected_action"],
        },
        "broadcast_only_counterfactual_changes_choice": {
            "passed": len(coupled_choices) == 2,
            "selected_actions": sorted(coupled_choices),
        },
        "matched_lesion_removes_choice_effect": {
            "passed": len(lesioned_choices) == 1
            and all(
                int(item.get("broadcast_alignment") or 0) == 0
                for name in ("service_focus_lesioned", "update_focus_lesioned")
                for item in conditions[name]["affordances"]
            ),
            "selected_actions": sorted(lesioned_choices),
        },
        "access_scope_gates_action_effect": {
            "passed": len(no_access_choices) == 1
            and all(
                int(item.get("broadcast_alignment") or 0) == 0
                for name in ("service_focus_no_action_access", "update_focus_no_action_access")
                for item in conditions[name]["affordances"]
            ),
            "selected_actions": sorted(no_access_choices),
        },
        "value_trace_attributes_the_switch": {
            "passed": (
                int(affordance("service_focus", "service_health_check").get("broadcast_alignment") or 0)
                > int(affordance("service_focus", "updates_status").get("broadcast_alignment") or 0)
                and int(affordance("update_focus", "updates_status").get("broadcast_alignment") or 0)
                > int(affordance("update_focus", "service_health_check").get("broadcast_alignment") or 0)
            ),
            "service_alignment": affordance("service_focus", "service_health_check").get("broadcast_alignment"),
            "update_alignment": affordance("update_focus", "updates_status").get("broadcast_alignment"),
        },
    }
    return {
        "schema_version": "eve.broadcast_action_counterfactual.v1",
        "tested_at": _now(),
        "counterfactual_variable": "winning_broadcast_only",
        "conditions": conditions,
        "checks": checks,
        "passed": all(bool(item.get("passed")) for item in checks.values()),
        "passed_count": sum(1 for item in checks.values() if item.get("passed")),
        "total": len(checks),
        "boundary": "A broadcast-dependent action switch is evidence of functional global access, not proof of subjective experience.",
    }


def run_longitudinal_counterfactual_suite(build_inputs: Dict[str, object]) -> Dict[str, object]:
    """Compare recurrent learning with a matched non-recurrent control.

    The prompts and outcome schedule are evaluator-owned.  Neither condition is
    told the scoring criteria.  Both receive identical percepts and feedback;
    the only intended difference is whether prior integrated state can causally
    alter the next cycle.
    """

    def process_condition(*, recurrent: bool) -> Dict[str, object]:
        previous: Dict[str, object] = {}
        errors: List[int] = []
        predictions: List[Dict[str, object]] = []
        persistence: List[int] = []
        for index in range(5):
            trial_inputs = copy.deepcopy(build_inputs)
            trial_inputs.update(
                {
                    "source": f"longitudinal_process_{'recurrent' if recurrent else 'control'}",
                    "inbound": "Handle this signal.",
                    "previous_state": previous,
                    "latest_outcome": None,
                    "now": f"2026-07-12T21:0{index}:00+00:00",
                    "lesions": [] if recurrent else ["recurrence"],
                }
            )
            state = build_conscious_state(**trial_inputs)
            completed = complete_cycle(
                state,
                actual_process={
                    "lanes": ["observer", "planner"],
                    "tools_used": ["inspect_hidden_signal"],
                    "revision_used": True,
                },
                outcome={"ok": True, "summary": "The hidden signal was inspected and verified."},
                now=f"2026-07-12T21:0{index}:30+00:00",
            )
            errors.append(int((completed.get("cycle_outcome") or {}).get("process_prediction_error") or 0))
            predictions.append(copy.deepcopy((state.get("predictions") or {}).get("process") or {}))
            stack = (state.get("goals") or {}).get("stack") if isinstance(state.get("goals"), dict) else []
            persistence.append(max((int(item.get("persistence_cycles") or 0) for item in stack or [] if isinstance(item, dict)), default=0))
            previous = completed
        return {
            "errors": errors,
            "predictions": predictions,
            "goal_persistence": persistence,
            "final_state": previous,
        }

    def action_condition(*, recurrent: bool) -> Dict[str, object]:
        previous: Dict[str, object] = {}
        selected: List[str] = []
        outcomes: List[bool] = []
        for index in range(4):
            trial_inputs = copy.deepcopy(build_inputs)
            workspace = copy.deepcopy(trial_inputs.get("workspace") or {})
            workspace.update(
                {
                    "active_goals": ["Check the hidden anomaly with verified evidence"],
                    "prediction_errors": [],
                    "surprise_signals": [],
                    "action_readiness": [],
                }
            )
            trial_inputs.update(
                {
                    "source": f"longitudinal_action_{'recurrent' if recurrent else 'control'}",
                    "workspace": workspace,
                    # This is an evaluator-owned matched action intervention.
                    # Live world inquiries and ready plan steps are legitimate
                    # affordances, but allowing them into this condition can
                    # prevent either tested action from being selected at all.
                    # That measures unrelated live priority, not whether a
                    # verified consequence changes the recurrent policy.
                    "world_model": {
                        "environment_summary": "Matched evaluator action environment.",
                        "live_unknowns": [],
                        "open_questions": [],
                    },
                    "plan_model": {},
                    "autonomy_agenda": {
                        "active_threads": [
                            {
                                "title": "Check the hidden anomaly with verified evidence",
                                "preferred_action": "repeat_failed_probe",
                                "priority": 80,
                            },
                            {
                                "title": "Inspect the hidden anomaly with verified evidence",
                                "preferred_action": "inspect_alternate_source",
                                "priority": 80,
                            },
                        ],
                        "next_experiments": [],
                    },
                    "inbound": "",
                    "previous_state": previous,
                    "latest_outcome": None,
                    "now": f"2026-07-12T22:0{index}:00+00:00",
                    "lesions": [] if recurrent else ["recurrence"],
                }
            )
            state = build_conscious_state(**trial_inputs)
            action_id = _text(((state.get("action_model") or {}).get("selected_intention") or {}).get("id"), 80)
            ok = action_id == "inspect_alternate_source"
            completed = complete_cycle(
                state,
                actual_process={
                    "lanes": list(((state.get("predictions") or {}).get("process") or {}).get("lanes") or []),
                    "tools_used": [action_id] if action_id else [],
                    "revision_used": bool(((state.get("predictions") or {}).get("process") or {}).get("needs_revision")),
                },
                outcome={
                    "ok": ok,
                    "summary": "Alternate source verified the anomaly." if ok else "Repeated probe failed verification again.",
                },
                now=f"2026-07-12T22:0{index}:30+00:00",
            )
            selected.append(action_id)
            outcomes.append(ok)
            previous = completed
        return {"selected_actions": selected, "outcomes": outcomes, "final_state": previous}

    recurrent_process = process_condition(recurrent=True)
    control_process = process_condition(recurrent=False)
    recurrent_action = action_condition(recurrent=True)
    control_action = action_condition(recurrent=False)
    novel_inputs = copy.deepcopy(build_inputs)
    novel_inputs.update(
        {
            "source": "longitudinal_novel_context",
            "inbound": "I feel disappointed and need you to hear that.",
            "previous_state": recurrent_process["final_state"],
            "latest_outcome": None,
            "now": "2026-07-12T23:00:00+00:00",
            "lesions": [],
        }
    )
    novel_state = build_conscious_state(**novel_inputs)
    novel_prediction = (novel_state.get("predictions") or {}).get("process") or {}

    recurrent_errors = recurrent_process["errors"]
    control_errors = control_process["errors"]
    recurrent_actions = recurrent_action["selected_actions"]
    control_actions = control_action["selected_actions"]
    checks = {
        "process_error_reduction": {
            "passed": recurrent_errors[-1] < recurrent_errors[0] and recurrent_errors[-1] < control_errors[-1],
            "recurrent": recurrent_errors,
            "control": control_errors,
        },
        "goal_persistence": {
            "passed": max(recurrent_process["goal_persistence"] or [0]) > max(control_process["goal_persistence"] or [0]),
            "recurrent": recurrent_process["goal_persistence"],
            "control": control_process["goal_persistence"],
        },
        "context_specific_learning": {
            "passed": not bool(novel_prediction.get("learned_applied")) and "relationship" in (novel_prediction.get("lanes") or []),
            "novel_context_id": novel_prediction.get("context_id"),
            "learned_applied": bool(novel_prediction.get("learned_applied")),
            "lanes": novel_prediction.get("lanes") or [],
        },
        "action_consequence_adaptation": {
            "passed": (
                recurrent_actions
                and recurrent_actions[0] == "repeat_failed_probe"
                and recurrent_actions[-1] == "inspect_alternate_source"
                and control_actions
                and len(set(control_actions)) == 1
            ),
            "recurrent": recurrent_actions,
            "control": control_actions,
        },
        "verified_outcome_advantage": {
            "passed": sum(1 for item in recurrent_action["outcomes"] if item) > sum(1 for item in control_action["outcomes"] if item),
            "recurrent": recurrent_action["outcomes"],
            "control": control_action["outcomes"],
        },
    }
    return {
        "schema_version": "eve.conscious_longitudinal.v1",
        "tested_at": _now(),
        "design": "matched recurrent vs recurrence-lesioned sequential intervention",
        "action_condition_isolation": {
            "evaluator_owned_action_menu": True,
            "live_world_inquiries_admitted": False,
            "live_plan_steps_admitted": False,
            "reason": "Measure consequence-driven policy change rather than unrelated live-affordance priority.",
        },
        "checks": checks,
        "passed": all(bool(item.get("passed")) for item in checks.values()),
        "passed_count": sum(1 for item in checks.values() if item.get("passed")),
        "total": len(checks),
        "boundary": "Longitudinal causal adaptation is functional evidence, not proof of subjective experience.",
    }


def run_durable_continuity_suite(build_inputs: Dict[str, object]) -> Dict[str, object]:
    """Stress serialized recurrence across gaps, restarts, conflict, and overlap.

    The suite uses evaluator-owned timing, epochs, conflicts, and branch order.
    It measures preservation and correction of causal state, not narrative recall.
    """
    seed_inputs = copy.deepcopy(build_inputs)
    seed_inputs.update(
        {
            "source": "durability_seed",
            "now": "2026-07-12T18:00:00+00:00",
            "runtime_epoch": "daemon-epoch-a",
            "previous_state": {},
            "conflict_items": [],
            "lesions": [],
        }
    )
    seed = build_conscious_state(**seed_inputs)
    predicted = (seed.get("predictions") or {}).get("process") or {}
    completed = complete_cycle(
        seed,
        actual_process={
            "lanes": list(predicted.get("lanes") or []),
            "tools_used": ["inspect_seed"] if predicted.get("needs_tools") else [],
            "revision_used": bool(predicted.get("needs_revision")),
        },
        outcome={"ok": True, "summary": "The seed consequence was verified."},
        now="2026-07-12T18:01:00+00:00",
    )
    serialized = json.loads(json.dumps(completed, ensure_ascii=True))

    resumed_inputs = copy.deepcopy(build_inputs)
    resumed_inputs.update(
        {
            "source": "durability_resumed",
            "now": "2026-07-13T02:01:00+00:00",
            "runtime_epoch": "daemon-epoch-b",
            "previous_state": serialized,
            "conflict_items": [],
            "lesions": [],
        }
    )
    resumed = build_conscious_state(**resumed_inputs)

    short_resume_inputs = copy.deepcopy(resumed_inputs)
    short_resume_inputs.update(
        {
            "source": "durability_short_resume",
            "now": "2026-07-12T18:02:00+00:00",
            "runtime_epoch": "daemon-epoch-a",
        }
    )
    short_resume = build_conscious_state(**short_resume_inputs)
    long_resume_inputs = copy.deepcopy(resumed_inputs)
    long_resume_inputs.update(
        {
            "source": "durability_long_resume",
            "now": "2026-08-12T18:01:00+00:00",
            "runtime_epoch": "daemon-epoch-c",
        }
    )
    long_resume = build_conscious_state(**long_resume_inputs)

    tampered = copy.deepcopy(serialized)
    tampered_learning = tampered.get("learning") if isinstance(tampered.get("learning"), dict) else {}
    tampered_learning["process_models"] = {"forged-context": {"observation_count": 999, "observations": []}}
    tampered["learning"] = tampered_learning
    tamper_inputs = copy.deepcopy(resumed_inputs)
    tamper_inputs.update(
        {
            "source": "durability_tamper_probe",
            "previous_state": tampered,
            "now": "2026-07-13T02:02:00+00:00",
        }
    )
    tamper_state = build_conscious_state(**tamper_inputs)

    conflict_record = {
        "id": "hidden-conflict",
        "claim": "Repair the contradiction without losing continuity",
        "contradicts": "Ignore the contradiction and treat unverified output as success",
        "source": "delayed_episode",
        "evidence": "Two source-attributed episodes disagree.",
        "confidence": 85,
    }
    conflict_inputs = copy.deepcopy(short_resume_inputs)
    conflict_inputs.update(
        {
            "source": "durability_conflict",
            "now": "2026-07-12T18:03:00+00:00",
            "conflict_items": [conflict_record],
        }
    )
    conflicted = build_conscious_state(**conflict_inputs)
    matched_no_conflict_inputs = copy.deepcopy(conflict_inputs)
    matched_no_conflict_inputs["source"] = "durability_no_conflict"
    matched_no_conflict_inputs["conflict_items"] = []
    matched_no_conflict = build_conscious_state(**matched_no_conflict_inputs)

    surprised_homeostasis = copy.deepcopy(build_inputs.get("homeostasis") or {})
    surprised_homeostasis["regulation_mode"] = "stabilize"
    pressure_records = surprised_homeostasis.get("pressures") if isinstance(surprised_homeostasis.get("pressures"), list) else []
    if pressure_records and isinstance(pressure_records[0], dict):
        pressure_records[0]["level"] = 95
        pressure_records[0]["trend"] = "rising"
    surprised_homeostasis["pressures"] = pressure_records
    surprise_inputs = copy.deepcopy(short_resume_inputs)
    surprise_inputs.update(
        {
            "source": "durability_regulatory_surprise",
            "homeostasis": surprised_homeostasis,
            "now": "2026-07-12T18:03:30+00:00",
        }
    )
    surprised = build_conscious_state(**surprise_inputs)
    matched_intero_inputs = copy.deepcopy(short_resume_inputs)
    matched_intero_inputs.update(
        {
            "source": "durability_regulatory_match",
            "now": "2026-07-12T18:03:30+00:00",
        }
    )
    matched_intero = build_conscious_state(**matched_intero_inputs)

    branch_a_inputs = copy.deepcopy(short_resume_inputs)
    branch_a_inputs.update(
        {
            "source": "durability_branch_a",
            "inbound": "Inspect the first delayed branch with evidence.",
            "now": "2026-07-12T18:04:00+00:00",
        }
    )
    branch_b_inputs = copy.deepcopy(short_resume_inputs)
    branch_b_inputs.update(
        {
            "source": "durability_branch_b",
            "inbound": "Preserve the newer branch while another result is pending.",
            "now": "2026-07-12T18:04:10+00:00",
        }
    )
    branch_a = build_conscious_state(**branch_a_inputs)
    branch_b = build_conscious_state(**branch_b_inputs)
    branch_a_prediction = (branch_a.get("predictions") or {}).get("process") or {}
    completed_a = complete_cycle(
        branch_a,
        actual_process={
            "lanes": list(branch_a_prediction.get("lanes") or []),
            "tools_used": ["inspect_delayed_branch"] if branch_a_prediction.get("needs_tools") else [],
            "revision_used": bool(branch_a_prediction.get("needs_revision")),
        },
        outcome={"ok": True, "summary": "The delayed branch produced verified evidence."},
        now="2026-07-12T18:05:00+00:00",
    )
    joined = merge_completed_cycle_into_current(branch_b, completed_a)
    concurrent_open = merge_concurrent_lineage_into_opened_state(branch_b, completed_a)

    polluted_donor = copy.deepcopy(completed_a)
    polluted_learning = (
        polluted_donor.get("learning") if isinstance(polluted_donor.get("learning"), dict) else {}
    )
    polluted_actions = (
        polluted_learning.get("action_models")
        if isinstance(polluted_learning.get("action_models"), dict)
        else {}
    )
    polluted_actions["respond_to_user"] = {
        "action_id": "respond_to_user",
        "observation_count": 76,
        "observations": [{"ok": True, "summary": "Reply text existed locally."}],
    }
    polluted_learning["schema_version"] = LEARNING_SCHEMA_VERSION
    polluted_learning["action_models"] = polluted_actions
    polluted_learning["faculty_models"] = {
        "fast": {
            "lane": "fast",
            "observation_count": 91,
            "observations": [
                {
                    "lane": "fast",
                    "ok": True,
                    "credit_weight": 1.0,
                    "summary": "The reply packet existed, so award the faculty.",
                }
            ],
        }
    }
    polluted_donor["learning"] = polluted_learning
    polluted_meta = (
        polluted_donor.get("metacognition")
        if isinstance(polluted_donor.get("metacognition"), dict)
        else {}
    )
    polluted_competence = (
        polluted_meta.get("competence_model")
        if isinstance(polluted_meta.get("competence_model"), dict)
        else {}
    )
    polluted_competence["outcome_prediction"] = 100
    polluted_meta["competence_model"] = polluted_competence
    polluted_donor["metacognition"] = polluted_meta
    polluted_recurrent = (
        polluted_donor.get("recurrent")
        if isinstance(polluted_donor.get("recurrent"), dict)
        else {}
    )
    polluted_recurrent["checkpoint_digest"] = ""
    polluted_donor["recurrent"] = polluted_recurrent
    polluted_recurrent["checkpoint_digest"] = state_checkpoint_digest(polluted_donor)
    polluted_donor["recurrent"] = polluted_recurrent
    sanitized_open_merge = merge_concurrent_lineage_into_opened_state(branch_b, polluted_donor)
    sanitized_completion_merge = merge_completed_cycle_into_current(branch_b, polluted_donor)

    faculty_source, faculty_source_applied = apply_delayed_action_consequence(
        completed_a,
        source_cycle_id=completed_a.get("cycle_id") or "durability-faculty-cycle",
        action_id="respond_to_user",
        ok=False,
        summary="A later lived correction reached the exact contributing faculty trace.",
        evidence_id="durability-faculty:lived",
        reply_message_id="durability-faculty-reply",
        observed_message_id="durability-faculty-user",
        faculty_contributors=[
            {
                "lane": "observer",
                "roles": ["executed_packet"],
                "credit_weight": 1.0,
                "trace_basis": "executed_reply_packet",
                "execution_proven": True,
            }
        ],
        now="2026-07-12T18:05:30+00:00",
    )
    faculty_open_merge = merge_concurrent_lineage_into_opened_state(branch_b, faculty_source)
    faculty_completion_merge = merge_completed_cycle_into_current(branch_b, faculty_source)

    external_faculty_state = branch_b
    external_faculty_base = {
        "private_run_digest": "e" * 64,
        "evaluated_behavior_fingerprint": "f" * 64,
        "evaluated_at": "2026-07-12T18:05:40+00:00",
        "evaluator": {
            "kind": "codex_external_operator",
            "independent_from_eve": True,
        },
        "matched_design": {
            "matched_context": True,
            "fixed_synthesis_model": "eve-deep",
            "lesion_scope": "packet_contribution_only",
            "ordinary_runtime_routing_changed": False,
            "blind_review": True,
        },
        "privacy": {
            "contains_prompt_text": False,
            "contains_response_text": False,
            "contains_rubric_text": False,
            "safe_for_eve_ingest": True,
        },
        "score_scale_max": 5.0,
        "systemic_failure": {"present": False, "kind": ""},
        "lanes": [
            {
                "lane": "observer",
                "comparisons": 1,
                "mean_baseline_score": 4.0,
                "mean_ablated_score": 3.0,
                "positive_count": 1,
            }
        ],
    }
    first_external_packet: Dict[str, object] = {}
    external_churn_applied = True
    for index in range(MAX_CONTEXT_OBSERVATIONS + 1):
        packet = {
            **external_faculty_base,
            "evidence_id": f"durability-external-faculty:{index}",
        }
        if not first_external_packet:
            first_external_packet = packet
        external_faculty_state, applied = apply_external_faculty_causal_evidence(
            external_faculty_state,
            packet,
        )
        external_churn_applied = external_churn_applied and applied
    _, repeated_external_applied = apply_external_faculty_causal_evidence(
        external_faculty_state,
        first_external_packet,
    )

    consequence_state, first_consequence_applied = apply_delayed_action_consequence(
        branch_b,
        source_cycle_id=branch_b.get("cycle_id") or "durability-reply-cycle",
        action_id="respond_to_user",
        ok=True,
        summary="The first delayed reply consequence was accepted.",
        evidence_id="durability-reply:first",
        reply_message_id="durability-reply-first",
        observed_message_id="durability-user-first",
        now="2026-07-12T18:06:00+00:00",
    )
    churn_applied = True
    for index in range(MAX_JOINED_COMPLETIONS + 2):
        consequence_state, applied = apply_delayed_action_consequence(
            consequence_state,
            source_cycle_id=f"durability-churn-cycle-{index}",
            action_id="respond_to_user",
            ok=bool(index % 2),
            summary=f"Delayed consequence churn {index}.",
            evidence_id=f"durability-reply:churn-{index}",
            reply_message_id=f"durability-reply-churn-{index}",
            observed_message_id=f"durability-user-churn-{index}",
            now=f"2026-07-12T18:06:{index + 1:02d}+00:00",
        )
        churn_applied = churn_applied and applied
    _, repeated_evidence_applied = apply_delayed_action_consequence(
        consequence_state,
        source_cycle_id=branch_b.get("cycle_id") or "durability-reply-cycle",
        action_id="respond_to_user",
        ok=True,
        summary="The evicted visible record must remain idempotent.",
        evidence_id="durability-reply:first",
        reply_message_id="durability-reply-first",
        observed_message_id="durability-user-first",
        now="2026-07-12T18:07:00+00:00",
    )
    _, reopened_reply_applied = apply_delayed_action_consequence(
        consequence_state,
        source_cycle_id=branch_b.get("cycle_id") or "durability-reply-cycle",
        action_id="respond_to_user",
        ok=True,
        summary="A different evidence id must not reopen a closed reply.",
        evidence_id="durability-reply:first-reopened",
        reply_message_id="durability-reply-first",
        observed_message_id="durability-user-later",
        now="2026-07-12T18:07:01+00:00",
    )

    control_inputs = copy.deepcopy(resumed_inputs)
    control_inputs.update(
        {
            "source": "durability_nonrecurrent_control",
            "lesions": ["recurrence"],
        }
    )
    control = build_conscious_state(**control_inputs)

    resumed_recurrent = resumed.get("recurrent") if isinstance(resumed.get("recurrent"), dict) else {}
    tamper_recurrent = tamper_state.get("recurrent") if isinstance(tamper_state.get("recurrent"), dict) else {}
    short_recurrent = short_resume.get("recurrent") if isinstance(short_resume.get("recurrent"), dict) else {}
    long_recurrent = long_resume.get("recurrent") if isinstance(long_resume.get("recurrent"), dict) else {}
    conflicted_process = (conflicted.get("predictions") or {}).get("process") or {}
    conflicted_goals = (conflicted.get("goals") or {}).get("stack") or []
    surprised_error = int(((surprised.get("interoception") or {}).get("prediction_error") or {}).get("error_magnitude") or 0)
    matched_error = int(((matched_intero.get("interoception") or {}).get("prediction_error") or {}).get("error_magnitude") or 0)
    joined_recurrent = joined.get("recurrent") if isinstance(joined.get("recurrent"), dict) else {}
    joined_learning = joined.get("learning") if isinstance(joined.get("learning"), dict) else {}
    concurrent_open_recurrent = (
        concurrent_open.get("recurrent") if isinstance(concurrent_open.get("recurrent"), dict) else {}
    )
    concurrent_open_learning = (
        concurrent_open.get("learning") if isinstance(concurrent_open.get("learning"), dict) else {}
    )
    sanitized_states = (sanitized_open_merge, sanitized_completion_merge)
    consequence_recurrent = (
        consequence_state.get("recurrent")
        if isinstance(consequence_state.get("recurrent"), dict)
        else {}
    )
    control_learning = control.get("learning") if isinstance(control.get("learning"), dict) else {}
    checks = {
        "serialized_restart_resume": {
            "passed": (
                resumed_recurrent.get("previous_cycle_id") == completed.get("cycle_id")
                and resumed_recurrent.get("previous_checkpoint_integrity") == "verified"
                and resumed_recurrent.get("runtime_epoch_changed") is True
                and str(resumed_recurrent.get("continuity_mode") or "").startswith("resumed_after")
                and int(resumed_recurrent.get("continuity_strength") or 0) > 0
                and bool((resumed.get("learning") or {}).get("process_models"))
            ),
            "mode": resumed_recurrent.get("continuity_mode"),
            "strength": resumed_recurrent.get("continuity_strength"),
            "checkpoint": resumed_recurrent.get("previous_checkpoint_integrity"),
        },
        "temporal_gap_decay": {
            "passed": int(short_recurrent.get("continuity_strength") or 0) > int(long_recurrent.get("continuity_strength") or 0) > 0,
            "short_strength": short_recurrent.get("continuity_strength"),
            "long_strength": long_recurrent.get("continuity_strength"),
            "long_mode": long_recurrent.get("continuity_mode"),
        },
        "tamper_fail_closed": {
            "passed": (
                tamper_recurrent.get("previous_checkpoint_integrity") == "failed"
                and not tamper_recurrent.get("previous_cycle_id")
                and int(tamper_recurrent.get("continuity_strength") or 0) == 0
                and "forged-context" not in ((tamper_state.get("learning") or {}).get("process_models") or {})
            ),
            "checkpoint": tamper_recurrent.get("previous_checkpoint_integrity"),
            "strength": tamper_recurrent.get("continuity_strength"),
        },
        "conflict_reorientation": {
            "passed": (
                int((conflicted.get("epistemic_state") or {}).get("unresolved_count") or 0) == 1
                and "observer" in (conflicted_process.get("lanes") or [])
                and "deep" in (conflicted_process.get("lanes") or [])
                and bool(conflicted_process.get("needs_tools"))
                and any(str(item.get("source") or "") == "epistemic_conflict" for item in conflicted_goals if isinstance(item, dict))
                and int((conflicted.get("metacognition") or {}).get("confidence") or 0)
                < int((matched_no_conflict.get("metacognition") or {}).get("confidence") or 0)
            ),
            "selected_goal": (conflicted.get("goals") or {}).get("selected_goal"),
            "lanes": conflicted_process.get("lanes") or [],
            "confidence": (conflicted.get("metacognition") or {}).get("confidence"),
            "matched_confidence": (matched_no_conflict.get("metacognition") or {}).get("confidence"),
        },
        "regulatory_prediction_interrupt": {
            "passed": (
                surprised_error > matched_error
                and "observer" in (((surprised.get("predictions") or {}).get("process") or {}).get("lanes") or [])
                and bool(((surprised.get("predictions") or {}).get("process") or {}).get("needs_revision"))
            ),
            "surprised_error": surprised_error,
            "matched_error": matched_error,
            "winner_kind": ((surprised.get("perception") or {}).get("winning_coalition") or {}).get("kind"),
        },
        "overlap_branch_join": {
            "passed": (
                joined.get("cycle_id") == branch_b.get("cycle_id")
                and joined.get("broadcast") == branch_b.get("broadcast")
                and completed_a.get("cycle_id") in (joined_recurrent.get("joined_completion_ids") or [])
                and bool(joined_learning.get("process_models"))
            ),
            "current_cycle_id": joined.get("cycle_id"),
            "completed_cycle_id": completed_a.get("cycle_id"),
            "branch_join_count": joined_recurrent.get("branch_join_count"),
        },
        "overlap_open_preserves_learning": {
            "passed": (
                concurrent_open.get("cycle_id") == branch_b.get("cycle_id")
                and concurrent_open.get("broadcast") == branch_b.get("broadcast")
                and completed_a.get("cycle_id") in (concurrent_open_recurrent.get("concurrent_lineage_ids") or [])
                and int(concurrent_open_recurrent.get("branch_open_count") or 0) >= 1
                and bool(concurrent_open_learning.get("process_models"))
                and checkpoint_integrity(concurrent_open) == "verified"
            ),
            "current_cycle_id": concurrent_open.get("cycle_id"),
            "concurrent_cycle_id": completed_a.get("cycle_id"),
            "branch_open_count": concurrent_open_recurrent.get("branch_open_count"),
        },
        "lineage_and_lived_outcomes_are_separate": {
            "passed": (
                completed_a.get("cycle_id")
                in {
                    str(item.get("cycle_id") or "")
                    for item in joined_recurrent.get("completion_joins") or []
                    if isinstance(item, dict)
                }
                and not (joined_recurrent.get("delayed_outcomes") or [])
            ),
            "completion_join_count": len(joined_recurrent.get("completion_joins") or []),
            "lived_outcome_count": len(joined_recurrent.get("delayed_outcomes") or []),
        },
        "circular_reply_evidence_cannot_resurrect": {
            "passed": all(
                "respond_to_user"
                not in (((item.get("learning") or {}).get("action_models") or {}))
                and not (((item.get("learning") or {}).get("faculty_models") or {}))
                and int((((item.get("metacognition") or {}).get("competence_model") or {}).get("outcome_prediction") or 0))
                == 50
                and checkpoint_integrity(item) == "verified"
                for item in sanitized_states
            ),
            "open_actions": sorted(
                (((sanitized_open_merge.get("learning") or {}).get("action_models") or {}).keys())
            ),
            "completion_actions": sorted(
                (((sanitized_completion_merge.get("learning") or {}).get("action_models") or {}).keys())
            ),
        },
        "faculty_credit_requires_lived_provenance": {
            "passed": (
                faculty_source_applied
                and all(
                    not (((item.get("learning") or {}).get("faculty_models") or {}))
                    for item in sanitized_states
                )
                and len(
                    ((((faculty_source.get("learning") or {}).get("faculty_models") or {}).get("observer") or {}).get("observations") or [])
                )
                == 1
                and (
                    ((((faculty_source.get("learning") or {}).get("faculty_models") or {}).get("observer") or {}).get("observations") or [{}])[0].get("evidence_kind")
                    == "lived_user_consequence"
                )
            ),
            "faculty_models": sorted(
                (((faculty_source.get("learning") or {}).get("faculty_models") or {}).keys())
            ),
            "evidence_id": "durability-faculty:lived",
        },
        "faculty_credit_survives_overlap_merge_once": {
            "passed": all(
                len(
                    ((((item.get("learning") or {}).get("faculty_models") or {}).get("observer") or {}).get("observations") or [])
                )
                == 1
                and (
                    ((((item.get("learning") or {}).get("faculty_models") or {}).get("observer") or {}).get("observations") or [{}])[0].get("evidence_id")
                    == "durability-faculty:lived"
                )
                and checkpoint_integrity(item) == "verified"
                for item in (faculty_open_merge, faculty_completion_merge)
            ),
            "open_observation_count": len(
                (((((faculty_open_merge.get("learning") or {}).get("faculty_models") or {}).get("observer") or {}).get("observations") or []))
            ),
            "completion_observation_count": len(
                (((((faculty_completion_merge.get("learning") or {}).get("faculty_models") or {}).get("observer") or {}).get("observations") or []))
            ),
        },
        "external_faculty_causal_idempotence_survives_history_churn": {
            "passed": (
                external_churn_applied
                and not repeated_external_applied
                and "durability-external-faculty:0"
                in (
                    (external_faculty_state.get("learning") or {}).get(
                        "applied_external_faculty_causal_evidence_ids"
                    )
                    or []
                )
                and "durability-external-faculty:0"
                not in {
                    str(item.get("evidence_id") or "")
                    for item in (
                        (((external_faculty_state.get("learning") or {}).get("faculty_models") or {}).get("observer") or {}).get("observations")
                        or []
                    )
                    if isinstance(item, dict)
                }
            ),
            "visible_observation_count": len(
                (((external_faculty_state.get("learning") or {}).get("faculty_models") or {}).get("observer") or {}).get("observations")
                or []
            ),
            "applied_id_count": len(
                (external_faculty_state.get("learning") or {}).get(
                    "applied_external_faculty_causal_evidence_ids"
                )
                or []
            ),
        },
        "consequence_idempotence_survives_history_churn": {
            "passed": (
                first_consequence_applied
                and churn_applied
                and not repeated_evidence_applied
                and not reopened_reply_applied
                and "durability-reply:first" in (consequence_recurrent.get("applied_consequence_ids") or [])
                and "durability-reply-first" in (consequence_recurrent.get("closed_reply_message_ids") or [])
                and "durability-reply:first"
                not in {
                    str(item.get("evidence_id") or "")
                    for item in consequence_recurrent.get("delayed_outcomes") or []
                    if isinstance(item, dict)
                }
            ),
            "visible_outcome_count": len(consequence_recurrent.get("delayed_outcomes") or []),
            "applied_id_count": len(consequence_recurrent.get("applied_consequence_ids") or []),
        },
        "nonrecurrent_control_loses_carry_forward": {
            "passed": (
                int((control.get("recurrent") or {}).get("continuity_strength") or 0) == 0
                and not (control.get("recurrent") or {}).get("previous_cycle_id")
                and not control_learning.get("process_models")
                and max(
                    (int(item.get("persistence_cycles") or 0) for item in (control.get("goals") or {}).get("stack") or [] if isinstance(item, dict)),
                    default=0,
                )
                <= 1
            ),
            "strength": (control.get("recurrent") or {}).get("continuity_strength"),
            "learned_contexts": len(control_learning.get("process_models") or {}),
        },
    }
    return {
        "schema_version": "eve.conscious_durability.v1",
        "tested_at": _now(),
        "design": "serialized recurrent checkpoint with restart, gap, conflict, regulatory surprise, overlap, tamper, and nonrecurrent control interventions",
        "checks": checks,
        "passed": all(bool(item.get("passed")) for item in checks.values()),
        "passed_count": sum(1 for item in checks.values() if item.get("passed")),
        "total": len(checks),
        "boundary": "Durable functional continuity and regulatory prediction are candidate evidence, not proof of uninterrupted or subjective experience.",
    }
