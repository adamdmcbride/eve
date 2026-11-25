"""Source-attributed temporal common-ground tracking for Eve.

The tracker reconstructs overt conversational positions from Eve's existing
reply-replay and prediction-check lineage.  It never treats an utterance as
direct access to a private belief, emotion, or intention.  "Belief" in this
module means an explicitly expressed epistemic position in the dialogue.

This is a functional dialogue-state mechanism, not evidence of phenomenal
experience or mind reading.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Mapping, Optional, Sequence


SCHEMA_VERSION = "eve.temporal_common_ground.v1"
TRAJECTORY_SCHEMA_VERSION = "eve.public_epistemic_trajectory.v1"
MAX_TRAJECTORIES = 16
MAX_HISTORY_STATES = 8
OBSERVABLE_RESPONSE_CLASSES = {
    "acceptance",
    "correction",
    "answer",
    "follow_up_question",
    "continuation",
    "topic_shift",
}


def _text(value: object, limit: int = 260) -> str:
    return " ".join(str(value or "").split())[:limit]


def _timestamp(value: object = None) -> str:
    text = _text(value, 80)
    if not text:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _stable_id(prefix: str, *parts: object) -> str:
    material = "|".join(_text(part, 200) for part in parts)
    return f"{prefix}-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]


def _history_state(
    state: str,
    *,
    at: object,
    actor: str,
    evidence_id: object,
    source_message_id: object = "",
    observed_class: object = "",
) -> Dict[str, object]:
    return {
        "state": _text(state, 60),
        "at": _timestamp(at),
        "actor": _text(actor, 40),
        "evidence_id": _text(evidence_id, 160),
        "source_message_id": _text(source_message_id, 120),
        "observed_class": _text(observed_class, 40),
    }


def _normalize_history(value: object) -> List[Dict[str, object]]:
    source = value if isinstance(value, list) else []
    result: List[Dict[str, object]] = []
    seen = set()
    for item in source:
        if not isinstance(item, Mapping):
            continue
        state = _text(item.get("state"), 60)
        evidence_id = _text(item.get("evidence_id"), 160)
        key = (state, evidence_id)
        if not state or key in seen:
            continue
        seen.add(key)
        result.append(
            _history_state(
                state,
                at=item.get("at"),
                actor=_text(item.get("actor"), 40),
                evidence_id=evidence_id,
                source_message_id=item.get("source_message_id"),
                observed_class=item.get("observed_class"),
            )
        )
    return result[-MAX_HISTORY_STATES:]


def normalize_trajectory(payload: object) -> Optional[Dict[str, object]]:
    if not isinstance(payload, Mapping):
        return None
    thread_id = _text(payload.get("thread_id"), 120)
    reply_message_id = _text(payload.get("reply_message_id"), 120)
    if not thread_id or not reply_message_id:
        return None
    source_message_id = _text(payload.get("source_message_id"), 120)
    trajectory_id = _text(payload.get("trajectory_id"), 100) or _stable_id(
        "cg",
        thread_id,
        source_message_id,
        reply_message_id,
    )
    history = _normalize_history(payload.get("history"))
    status = _text(payload.get("status"), 60) or "awaiting_response"
    observed_class = _text(payload.get("last_observed_class"), 40)
    if observed_class not in OBSERVABLE_RESPONSE_CLASSES:
        observed_class = ""
    return {
        "schema_version": TRAJECTORY_SCHEMA_VERSION,
        "trajectory_id": trajectory_id,
        "thread_id": thread_id,
        "source_message_id": source_message_id,
        "reply_message_id": reply_message_id,
        "opened_at": _timestamp(payload.get("opened_at")),
        "question_under_discussion": _text(payload.get("question_under_discussion"), 320),
        "visible_user_utterance_excerpt": _text(
            payload.get("visible_user_utterance_excerpt"), 320
        ),
        "visible_eve_reply_excerpt": _text(
            payload.get("visible_eve_reply_excerpt"), 320
        ),
        "user_utterance_sha256": _text(payload.get("user_utterance_sha256"), 64),
        "eve_reply_sha256": _text(payload.get("eve_reply_sha256"), 64),
        "status": status,
        "explicitly_shared": bool(payload.get("explicitly_shared")),
        "repair_required": bool(payload.get("repair_required")),
        "repair_reply_id": _text(payload.get("repair_reply_id"), 120),
        "superseded_by_reply_id": _text(payload.get("superseded_by_reply_id"), 120),
        "last_observed_class": observed_class,
        "last_observed_message_id": _text(payload.get("last_observed_message_id"), 120),
        "last_evidence_id": _text(payload.get("last_evidence_id"), 160),
        "history": history,
        "prior_states_preserved": len(history) > 1,
        "private_mental_state_inferred": False,
    }


def _prediction_check_index(
    records: Iterable[Mapping[str, object]],
) -> Dict[str, Dict[str, object]]:
    indexed: Dict[str, Dict[str, object]] = {}
    for raw in records:
        if not isinstance(raw, Mapping) or raw.get("recorded") is False:
            continue
        reply_id = _text(raw.get("scored_reply_id"), 120)
        observed = _text(raw.get("observed"), 40)
        if not reply_id or observed not in OBSERVABLE_RESPONSE_CLASSES:
            continue
        candidate = {
            "reply_message_id": reply_id,
            "thread_id": _text(raw.get("thread_id"), 120),
            "observed_class": observed,
            "observed_message_id": _text(raw.get("observed_message_id"), 120),
            "observed_at": _timestamp(raw.get("timestamp")),
            "evidence_id": _text(raw.get("evidence_id"), 160)
            or _stable_id("cg-evidence", reply_id, raw.get("observed_message_id")),
        }
        existing = indexed.get(reply_id)
        if existing is None or str(candidate["observed_at"]) < str(existing["observed_at"]):
            indexed[reply_id] = candidate
    return indexed


def _base_trajectory(replay: Mapping[str, object]) -> Optional[Dict[str, object]]:
    if replay.get("synthetic"):
        return None
    thread_id = _text(replay.get("thread_id"), 120)
    source_message_id = _text(replay.get("source_message_id"), 120)
    reply_message_id = _text(replay.get("reply_message_id"), 120)
    if not thread_id or not source_message_id or not reply_message_id:
        return None
    opened_at = _timestamp(replay.get("created_at"))
    inbound = _text(replay.get("inbound_preview"), 320)
    reply = _text(replay.get("reply_preview"), 320)
    if not inbound or not reply:
        return None
    trajectory_id = _stable_id("cg", thread_id, source_message_id, reply_message_id)
    history = [
        _history_state(
            "user_position_expressed",
            at=opened_at,
            actor="user",
            evidence_id=source_message_id,
            source_message_id=source_message_id,
        ),
        _history_state(
            "eve_position_expressed",
            at=opened_at,
            actor="eve",
            evidence_id=reply_message_id,
            source_message_id=reply_message_id,
        ),
        _history_state(
            "awaiting_observable_response",
            at=opened_at,
            actor="system",
            evidence_id=trajectory_id,
        ),
    ]
    return normalize_trajectory(
        {
            "trajectory_id": trajectory_id,
            "thread_id": thread_id,
            "source_message_id": source_message_id,
            "reply_message_id": reply_message_id,
            "opened_at": opened_at,
            "question_under_discussion": inbound,
            "visible_user_utterance_excerpt": inbound,
            "visible_eve_reply_excerpt": reply,
            "user_utterance_sha256": hashlib.sha256(inbound.encode("utf-8")).hexdigest(),
            "eve_reply_sha256": hashlib.sha256(reply.encode("utf-8")).hexdigest(),
            "status": "awaiting_response",
            "history": history,
        }
    )


def _apply_observation(
    trajectory: Dict[str, object],
    observation: Mapping[str, object],
) -> Dict[str, object]:
    result = copy.deepcopy(trajectory)
    observed = _text(observation.get("observed_class"), 40)
    observed_message_id = _text(observation.get("observed_message_id"), 120)
    evidence_id = _text(observation.get("evidence_id"), 160)
    observed_at = _timestamp(observation.get("observed_at"))
    transitions = {
        "acceptance": ("explicitly_shared", True, False),
        "correction": ("challenged", False, True),
        "answer": ("counterpart_answered", False, False),
        "follow_up_question": ("follow_up_open", False, False),
        "continuation": ("continued_unconfirmed", False, False),
        "topic_shift": ("superseded_topic_shift", False, False),
    }
    status, explicitly_shared, repair_required = transitions[observed]
    result.update(
        {
            "status": status,
            "explicitly_shared": explicitly_shared,
            "repair_required": repair_required,
            "last_observed_class": observed,
            "last_observed_message_id": observed_message_id,
            "last_evidence_id": evidence_id,
        }
    )
    result["history"] = [
        *list(result.get("history") or []),
        _history_state(
            status,
            at=observed_at,
            actor="user",
            evidence_id=evidence_id,
            source_message_id=observed_message_id,
            observed_class=observed,
        ),
    ]
    return normalize_trajectory(result) or trajectory


def _apply_repair_lineage(
    trajectory: Dict[str, object],
    *,
    replay_by_source: Mapping[str, Mapping[str, object]],
    checks_by_reply: Mapping[str, Mapping[str, object]],
) -> Dict[str, object]:
    if trajectory.get("last_observed_class") != "correction":
        return trajectory
    correction_message_id = _text(trajectory.get("last_observed_message_id"), 120)
    repair_replay = replay_by_source.get(correction_message_id)
    if not isinstance(repair_replay, Mapping) or repair_replay.get("synthetic"):
        return trajectory
    repair_reply_id = _text(repair_replay.get("reply_message_id"), 120)
    if not repair_reply_id:
        return trajectory
    result = copy.deepcopy(trajectory)
    result["status"] = "repair_attempted"
    result["repair_required"] = True
    result["repair_reply_id"] = repair_reply_id
    result["superseded_by_reply_id"] = repair_reply_id
    result["history"] = [
        *list(result.get("history") or []),
        _history_state(
            "repair_attempted",
            at=repair_replay.get("created_at"),
            actor="eve",
            evidence_id=repair_reply_id,
            source_message_id=repair_reply_id,
        ),
    ]
    repair_observation = checks_by_reply.get(repair_reply_id)
    if isinstance(repair_observation, Mapping):
        observed = _text(repair_observation.get("observed_class"), 40)
        if observed == "acceptance":
            result["status"] = "repair_confirmed"
            result["repair_required"] = False
        elif observed == "correction":
            result["status"] = "repair_rechallenged"
            result["repair_required"] = True
        else:
            result["status"] = "repair_unconfirmed"
            result["repair_required"] = False
        result["history"] = [
            *list(result.get("history") or []),
            _history_state(
                result["status"],
                at=repair_observation.get("observed_at"),
                actor="user",
                evidence_id=repair_observation.get("evidence_id"),
                source_message_id=repair_observation.get("observed_message_id"),
                observed_class=observed,
            ),
        ]
    return normalize_trajectory(result) or trajectory


def _material(payload: Mapping[str, object]) -> Dict[str, object]:
    material = copy.deepcopy(dict(payload))
    material.pop("model_sha256", None)
    return material


def normalize_model(payload: object) -> Dict[str, object]:
    source = payload if isinstance(payload, Mapping) else {}
    trajectories = [
        item
        for item in (
            normalize_trajectory(raw)
            for raw in (source.get("trajectories") if isinstance(source.get("trajectories"), list) else [])
        )
        if item is not None
    ][-MAX_TRAJECTORIES:]
    active_repairs = [item for item in trajectories if item.get("repair_required")]
    shared = [item for item in trajectories if item.get("explicitly_shared")]
    questions = [
        {
            "trajectory_id": item["trajectory_id"],
            "thread_id": item["thread_id"],
            "question": item["question_under_discussion"],
            "status": item["status"],
            "source_message_id": item["source_message_id"],
        }
        for item in trajectories
        if item.get("status")
        in {
            "awaiting_response",
            "follow_up_open",
            "challenged",
            "repair_attempted",
            "repair_rechallenged",
        }
    ][-4:]
    model: Dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": _timestamp(source.get("updated_at")),
        "status": "active" if trajectories else "empty",
        "summary": _text(
            source.get("summary"),
            260,
        )
        or (
            f"Tracked {len(trajectories)} overt dialogue trajectory(ies); "
            f"{len(shared)} explicitly shared and {len(active_repairs)} needing repair."
            if trajectories
            else "No overt dialogue trajectory has been reconstructed yet."
        ),
        "trajectories": trajectories,
        "questions_under_discussion": questions,
        "shared_commitments": [
            {
                "trajectory_id": item["trajectory_id"],
                "thread_id": item["thread_id"],
                "visible_eve_reply_excerpt": item["visible_eve_reply_excerpt"],
                "reply_message_id": item["reply_message_id"],
                "evidence_id": item["last_evidence_id"],
            }
            for item in shared[-6:]
        ],
        "active_repair": (
            {
                "required": True,
                "trajectory_id": active_repairs[-1]["trajectory_id"],
                "thread_id": active_repairs[-1]["thread_id"],
                "target_reply_id": active_repairs[-1]["reply_message_id"],
                "correction_message_id": active_repairs[-1]["last_observed_message_id"],
                "status": active_repairs[-1]["status"],
                "next_action": "Acknowledge the visible correction, preserve the prior state, and state the revised position without claiming hidden intent.",
            }
            if active_repairs
            else {"required": False}
        ),
        "trajectory_count": len(trajectories),
        "transition_count": sum(len(item.get("history") or []) for item in trajectories),
        "feedback_evidence_count": sum(
            1 for item in trajectories if item.get("last_observed_class")
        ),
        "prior_state_retrieval_count": sum(
            1 for item in trajectories if item.get("prior_states_preserved")
        ),
        "feedback_lesioned": bool(source.get("feedback_lesioned")),
        "source_contract": "exact reply replay plus first genuine next-message observation",
        "epistemic_boundary": "Only overt conversational positions are tracked. Private belief, emotion, intent, and subjective experience remain unknown.",
        "contains_private_mental_state": False,
        "consciousness_verdict_authorized": False,
    }
    model["model_sha256"] = _digest(_material(model))
    return model


def validate_model(payload: object) -> Dict[str, object]:
    if not isinstance(payload, Mapping) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported common-ground schema")
    normalized = normalize_model(payload)
    expected = _digest(_material(normalized))
    supplied = _text(payload.get("model_sha256"), 64)
    if supplied and supplied != expected:
        raise ValueError("common-ground digest mismatch")
    if normalized.get("contains_private_mental_state") is not False:
        raise ValueError("common-ground model crossed the private-state boundary")
    return normalized


def build_model(
    reply_replays: Sequence[Mapping[str, object]],
    prediction_checks: Sequence[Mapping[str, object]],
    *,
    now: object = None,
    feedback_lesioned: bool = False,
) -> Dict[str, object]:
    ordered_replays = sorted(
        [item for item in reply_replays if isinstance(item, Mapping) and not item.get("synthetic")],
        key=lambda item: (_text(item.get("created_at"), 80), _text(item.get("reply_message_id"), 120)),
    )[-MAX_TRAJECTORIES:]
    checks_by_reply = _prediction_check_index(prediction_checks)
    replay_by_source = {
        _text(item.get("source_message_id"), 120): item
        for item in ordered_replays
        if _text(item.get("source_message_id"), 120)
    }
    trajectories: List[Dict[str, object]] = []
    for replay in ordered_replays:
        trajectory = _base_trajectory(replay)
        if trajectory is None:
            continue
        if not feedback_lesioned:
            observation = checks_by_reply.get(str(trajectory["reply_message_id"]))
            if observation is not None:
                trajectory = _apply_observation(trajectory, observation)
                trajectory = _apply_repair_lineage(
                    trajectory,
                    replay_by_source=replay_by_source,
                    checks_by_reply=checks_by_reply,
                )
        trajectories.append(trajectory)
    return normalize_model(
        {
            "updated_at": _timestamp(now),
            "trajectories": trajectories,
            "feedback_lesioned": feedback_lesioned,
        }
    )


def lesion_feedback(payload: object) -> Dict[str, object]:
    model = normalize_model(payload)
    replays: List[Dict[str, object]] = []
    for item in model.get("trajectories") or []:
        if not isinstance(item, Mapping):
            continue
        replays.append(
            {
                "created_at": item.get("opened_at"),
                "thread_id": item.get("thread_id"),
                "source_message_id": item.get("source_message_id"),
                "reply_message_id": item.get("reply_message_id"),
                "inbound_preview": item.get("visible_user_utterance_excerpt"),
                "reply_preview": item.get("visible_eve_reply_excerpt"),
                "synthetic": False,
            }
        )
    return build_model(
        replays,
        [],
        now=model.get("updated_at"),
        feedback_lesioned=True,
    )


__all__ = [
    "MAX_TRAJECTORIES",
    "SCHEMA_VERSION",
    "TRAJECTORY_SCHEMA_VERSION",
    "build_model",
    "lesion_feedback",
    "normalize_model",
    "normalize_trajectory",
    "validate_model",
]
