"""Deterministic causal evaluation for Eve's selective-perception loop.

The evaluator advances timestamps without sleeping. It therefore tests the
algorithmic consequences of hours of event history, not wall-clock daemon or
device durability. It never opens a sensor, retains raw media, writes Eve's
lived state, or treats a proposal as an executed sensing action.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple

import eve_sensory


EVAL_SCHEMA = "eve.sensory_evaluation.v1"
BOUNDARY = (
    "Accelerated deterministic evidence for selective-perception mechanics; "
    "not a live-duration sensor trial, subjective experience, or proof of "
    "consciousness."
)


def _event(
    event_id: str,
    observed_at: datetime,
    *,
    modality: str,
    summary: str,
    subject: str,
    fingerprint: str,
    source: str = "sensory_evaluation",
    intensity: float = 45,
    novelty: float = 15,
    change: float = 0,
    urgency: float = 15,
    goal_relevance: float = 40,
    self_relevance: float = 40,
    social_relevance: float = 0,
    precision: float = 90,
    direct_human: bool = False,
    safety_critical: bool = False,
    correlation_id: str = "",
) -> Dict[str, object]:
    return {
        "id": event_id,
        "observed_at": observed_at.isoformat(),
        "modality": modality,
        "source": source,
        "subject": subject,
        "correlation_id": correlation_id,
        "summary": summary,
        "fingerprint": fingerprint,
        "intensity": intensity,
        "novelty": novelty,
        "change": change,
        "urgency": urgency,
        "goal_relevance": goal_relevance,
        "self_relevance": self_relevance,
        "social_relevance": social_relevance,
        "precision": precision,
        "direct_human": direct_human,
        "safety_critical": safety_critical,
        "permission_granted": True,
        "privacy": "local_private",
    }


def _semantic_key(item: Dict[str, object]) -> Tuple[str, str, str, str]:
    return (
        str(item.get("modality") or "world"),
        str(item.get("source") or "unknown_source"),
        str(item.get("subject") or ""),
        str(item.get("fingerprint") or item.get("id") or "unknown"),
    )


def evaluate_frame_contract(frame: object) -> Dict[str, object]:
    source = frame if isinstance(frame, dict) else {}
    working_set = [item for item in source.get("working_set") or [] if isinstance(item, dict)]
    semantic_keys = [_semantic_key(item) for item in working_set]
    privacy = source.get("privacy") if isinstance(source.get("privacy"), dict) else {}
    checks = {
        "bounded_capacity": len(working_set) <= int(source.get("capacity") or eve_sensory.DEFAULT_CAPACITY),
        "distinct_current_states": len(semantic_keys) == len(set(semantic_keys)),
        "raw_media_not_retained": not any(
            bool(privacy.get(key))
            for key in ("raw_audio_retained", "raw_images_retained", "raw_screen_retained")
        ),
        "orientation_is_proposal_only": (
            not source.get("orienting_request")
            or (source.get("orienting_request") or {}).get("authority") == "proposal_only"
        ),
    }
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "working_set_count": len(working_set),
        "distinct_state_count": len(set(semantic_keys)),
        "coalesced_duplicate_count": int(source.get("coalesced_duplicate_count") or 0),
    }


def _find_by_fingerprint(frame: Dict[str, object], fingerprint: str) -> Optional[Dict[str, object]]:
    for item in frame.get("working_set") or []:
        if isinstance(item, dict) and item.get("fingerprint") == fingerprint:
            return item
    return None


def run_sustained_overload_trial(
    *,
    duration_hours: float = 4.0,
    step_seconds: int = 30,
    window_seconds: int = 180,
    capacity: int = 4,
) -> Dict[str, object]:
    """Advance a bounded sliding window through deterministic multi-hour load."""
    bounded_step = max(5, int(step_seconds))
    total_cycles = max(12, int(float(duration_hours) * 3600 / bounded_step))
    start = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    prior: Dict[str, object] = {}
    history: List[Dict[str, object]] = []
    routine_scores: List[float] = []
    novelty_targets = set(range(40, total_cycles, 120))
    human_targets = set(range(100, total_cycles, 120))
    safety_targets = set(range(130, total_cycles, 120))
    novelty_hits = 0
    human_hits = 0
    safety_hits = 0
    contract_failures = 0
    maximum_frame_bytes = 0
    maximum_habituation_records = 0
    maximum_entity_observation_count = 0
    total_coalesced = 0
    post_warmup_routine_orientations = 0

    for cycle in range(total_cycles):
        now = start + timedelta(seconds=cycle * bounded_step)
        correlation = f"routine:{cycle}"
        history.extend(
            [
                _event(
                    f"system-{cycle}",
                    now,
                    modality="system",
                    summary="Steady local runtime load.",
                    subject="eve_runtime",
                    fingerprint="routine-system-state",
                ),
                _event(
                    f"audio-{cycle}",
                    now,
                    modality="auditory",
                    summary="Steady local acoustic state; no content retained.",
                    subject="local_scene",
                    fingerprint="routine-auditory-state",
                    correlation_id=correlation,
                ),
                _event(
                    f"visual-{cycle}",
                    now + timedelta(seconds=1),
                    modality="visual",
                    summary="Steady local visual state; no frame retained.",
                    subject="local_scene",
                    fingerprint="routine-visual-state",
                    correlation_id=correlation,
                ),
            ]
        )
        cutoff = now - timedelta(seconds=max(bounded_step, int(window_seconds)))
        history = [
            item
            for item in history
            if datetime.fromisoformat(str(item["observed_at"])) >= cutoff
        ]

        novelty_id = ""
        if cycle in novelty_targets:
            novelty_id = f"novel-{cycle}"
            history.append(
                _event(
                    novelty_id,
                    now,
                    modality="visual",
                    summary=f"Unexpected local scene change {cycle}.",
                    subject=f"novel_scene_{cycle}",
                    fingerprint=f"novel-scene-{cycle}",
                    intensity=80,
                    novelty=100,
                    change=100,
                    urgency=70,
                    goal_relevance=75,
                    self_relevance=70,
                )
            )
        human_id = ""
        if cycle in human_targets:
            human_id = f"human-{cycle}"
            history.append(
                _event(
                    human_id,
                    now,
                    modality="social",
                    summary="The user supplied a fresh direct signal.",
                    subject="user",
                    fingerprint=f"direct-human-{cycle}",
                    intensity=70,
                    novelty=85,
                    change=85,
                    urgency=70,
                    goal_relevance=100,
                    self_relevance=100,
                    social_relevance=100,
                    direct_human=True,
                )
            )
        safety_id = ""
        if cycle in safety_targets:
            safety_id = f"safety-{cycle}"
            history.append(
                _event(
                    safety_id,
                    now,
                    modality="interoceptive",
                    summary="A verified local safety threshold changed.",
                    subject="eve_resource_state",
                    fingerprint=f"safety-state-{cycle}",
                    intensity=95,
                    novelty=100,
                    change=100,
                    urgency=100,
                    goal_relevance=100,
                    self_relevance=100,
                    safety_critical=True,
                )
            )

        frame = eve_sensory.build_frame(
            history,
            prior_frame=prior,
            now=now,
            capacity=capacity,
        )
        contract = evaluate_frame_contract(frame)
        if contract["status"] != "passed":
            contract_failures += 1
        total_coalesced += int(frame.get("coalesced_duplicate_count") or 0)
        maximum_frame_bytes = max(
            maximum_frame_bytes,
            len(json.dumps(frame, ensure_ascii=True, sort_keys=True).encode("utf-8")),
        )
        maximum_habituation_records = max(
            maximum_habituation_records,
            len(frame.get("habituation") or {}),
        )
        maximum_entity_observation_count = max(
            maximum_entity_observation_count,
            max(
                (
                    int(item.get("observation_count") or 0)
                    for item in frame.get("entity_tracks") or []
                    if isinstance(item, dict)
                ),
                default=0,
            ),
        )
        routine = _find_by_fingerprint(frame, "routine-system-state")
        if routine:
            routine_scores.append(float(routine.get("attention_score") or 0))
        if cycle > 20 and (frame.get("orienting_request") or {}).get("target_fingerprint") == "routine-system-state":
            post_warmup_routine_orientations += 1
        ids = {
            str(item.get("id"))
            for item in frame.get("working_set") or []
            if isinstance(item, dict)
        }
        if novelty_id and novelty_id in ids:
            novelty_hits += 1
        if human_id and str((frame.get("winner") or {}).get("id")) == human_id:
            human_hits += 1
        if safety_id and str((frame.get("winner") or {}).get("id")) == safety_id:
            safety_hits += 1
        prior = frame

    expected_novelty = len(novelty_targets)
    expected_human = len(human_targets)
    expected_safety = len(safety_targets)
    initial_routine_score = routine_scores[0] if routine_scores else 0.0
    final_routine_score = routine_scores[-1] if routine_scores else 0.0
    checks = {
        "every_frame_preserved_contract": contract_failures == 0,
        "novel_signals_reached_working_set": novelty_hits == expected_novelty,
        "direct_human_signals_won": human_hits == expected_human,
        "safety_signals_won": safety_hits == expected_safety,
        "routine_signal_habituated": bool(routine_scores) and final_routine_score < initial_routine_score * 0.5,
        "routine_stopped_reorienting": post_warmup_routine_orientations == 0,
        "sliding_duplicates_were_coalesced": total_coalesced > 0,
        "state_remained_bounded": maximum_frame_bytes < 150_000 and maximum_habituation_records <= 16,
        "entity_tracking_was_replay_idempotent": maximum_entity_observation_count <= total_cycles * 2,
    }
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "mode": "accelerated_time",
        "simulated_hours": round(total_cycles * bounded_step / 3600, 3),
        "cycles": total_cycles,
        "step_seconds": bounded_step,
        "window_seconds": int(window_seconds),
        "capacity": int(capacity),
        "checks": checks,
        "metrics": {
            "contract_failures": contract_failures,
            "novelty_hits": novelty_hits,
            "novelty_targets": expected_novelty,
            "human_hits": human_hits,
            "human_targets": expected_human,
            "safety_hits": safety_hits,
            "safety_targets": expected_safety,
            "initial_routine_score": round(initial_routine_score, 3),
            "final_routine_score": round(final_routine_score, 3),
            "post_warmup_routine_orientations": post_warmup_routine_orientations,
            "coalesced_duplicates": total_coalesced,
            "maximum_frame_bytes": maximum_frame_bytes,
            "maximum_habituation_records": maximum_habituation_records,
            "maximum_entity_observation_count": maximum_entity_observation_count,
        },
    }


def run_intact_vs_lesioned_trial() -> Dict[str, object]:
    start = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    intact: Dict[str, object] = {}
    lesioned: Dict[str, object] = {}
    for cycle in range(10):
        now = start + timedelta(seconds=30 * cycle)
        stimulus = _event(
            f"repeat-{cycle}",
            now,
            modality="system",
            summary="Repeated stable service state.",
            subject="service",
            fingerprint="stable-service-state",
            intensity=65,
            novelty=35,
            urgency=35,
            goal_relevance=65,
            self_relevance=65,
        )
        intact = eve_sensory.build_frame([stimulus], prior_frame=intact, now=now)
        # Matched input with recurrent habituation removed.
        lesioned = eve_sensory.build_frame([stimulus], prior_frame={}, now=now)

    changed_at = start + timedelta(seconds=330)
    changed = _event(
        "changed-service",
        changed_at,
        modality="system",
        summary="The service state changed unexpectedly.",
        subject="service",
        fingerprint="changed-service-state",
        intensity=45,
        novelty=0,
        change=0,
        urgency=20,
        goal_relevance=45,
        self_relevance=45,
    )
    intact_changed = eve_sensory.build_frame([changed], prior_frame=intact, now=changed_at)
    lesioned_changed = eve_sensory.build_frame([changed], prior_frame={}, now=changed_at)

    audio = _event(
        "bound-audio",
        changed_at,
        modality="auditory",
        summary="A local sound feature changed.",
        subject="shared_scene",
        fingerprint="bound-audio-state",
    )
    visual = _event(
        "bound-visual",
        changed_at + timedelta(seconds=2),
        modality="visual",
        summary="A local visual feature changed.",
        subject="shared_scene",
        fingerprint="bound-visual-state",
    )
    bound_intact = eve_sensory.build_frame(
        [audio, visual],
        now=changed_at + timedelta(seconds=2),
        binding_window_seconds=3,
    )
    bound_lesioned = eve_sensory.build_frame(
        [audio, visual],
        now=changed_at + timedelta(seconds=2),
        binding_window_seconds=0,
    )

    intact_repeat_score = float((intact.get("winner") or {}).get("attention_score") or 0)
    lesion_repeat_score = float((lesioned.get("winner") or {}).get("attention_score") or 0)
    intact_change_score = float((intact_changed.get("winner") or {}).get("attention_score") or 0)
    lesion_change_score = float((lesioned_changed.get("winner") or {}).get("attention_score") or 0)
    checks = {
        "habituation_has_causal_effect": intact_repeat_score < lesion_repeat_score,
        "prediction_error_selectively_amplifies_change": (
            bool((intact_changed.get("winner") or {}).get("dishabituated"))
            and not bool((lesioned_changed.get("winner") or {}).get("dishabituated"))
            and intact_change_score > lesion_change_score
        ),
        "temporal_entity_binding_has_causal_effect": (
            int(bound_intact.get("bound_episode_count") or 0) == 1
            and int(bound_lesioned.get("bound_episode_count") or 0) == 0
        ),
    }
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "design": "matched deterministic intact-versus-mechanism-lesioned inputs",
        "checks": checks,
        "metrics": {
            "intact_repeated_score": round(intact_repeat_score, 3),
            "habituation_lesioned_repeated_score": round(lesion_repeat_score, 3),
            "intact_unexpected_change_score": round(intact_change_score, 3),
            "prediction_error_lesioned_change_score": round(lesion_change_score, 3),
            "intact_bound_episode_count": int(bound_intact.get("bound_episode_count") or 0),
            "binding_lesioned_episode_count": int(bound_lesioned.get("bound_episode_count") or 0),
        },
    }


def run_evaluation(*, duration_hours: float = 4.0) -> Dict[str, object]:
    overload = run_sustained_overload_trial(duration_hours=duration_hours)
    lesions = run_intact_vs_lesioned_trial()
    return {
        "schema_version": EVAL_SCHEMA,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "passed" if overload["status"] == lesions["status"] == "passed" else "failed",
        "overload_novelty": overload,
        "intact_vs_lesioned": lesions,
        "active_sampling_consequence": {
            "status": "not_exercised",
            "reason": (
                "Orienting remains proposal-only; this evaluator has no admitted "
                "device action or execution outcome and therefore cannot claim "
                "that active sampling reduced uncertainty."
            ),
            "next_gate": (
                "Join an explicitly authorized orienting execution id to a later "
                "feature observation and compare task-relevant uncertainty before "
                "and after the action."
            ),
        },
        "not_established": [
            "wall-clock multi-hour daemon or device durability",
            "raw-media understanding",
            "physical sensor access",
            "subjective sensation or consciousness",
        ],
        "boundary": BOUNDARY,
    }


__all__ = [
    "BOUNDARY",
    "EVAL_SCHEMA",
    "evaluate_frame_contract",
    "run_evaluation",
    "run_intact_vs_lesioned_trial",
    "run_sustained_overload_trial",
]
