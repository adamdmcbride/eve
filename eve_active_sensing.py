"""Causal closure for Eve's bounded active-sensing episodes.

This module is deliberately independent of model prompts and device adapters.
It decides whether a proposed orienting action produced a later, attributable
observation that materially changed a typed uncertainty state.  A successful
tool call alone is not information gain.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Dict, Mapping, Optional


SCHEMA_VERSION = "eve.active_sensing_episode.v1"
EVALUATION_SCHEMA_VERSION = "eve.active_sensing_evaluation.v1"
CALIBRATION_RECORD_SCHEMA_VERSION = "eve.active_sensing_calibration_record.v1"
CALIBRATION_REPORT_SCHEMA_VERSION = "eve.active_sensing_calibration_report.v1"
BOUNDARY = (
    "Functional perception-action evidence over typed uncertainty; not proof "
    "of subjective sensation, experience, or consciousness."
)

_RAW_MEDIA_KEYS = {
    "audio",
    "audio_bytes",
    "frame",
    "image",
    "image_bytes",
    "pcm",
    "pixels",
    "raw",
    "raw_audio",
    "raw_frame",
    "raw_image",
    "raw_screen",
    "screen",
    "video",
}


def _text(value: object, limit: int = 320) -> str:
    return " ".join(str(value or "").split())[:limit]


def _timestamp(value: object = None) -> str:
    if isinstance(value, datetime):
        current = value
    elif value:
        text = str(value).strip().replace("Z", "+00:00")
        current = datetime.fromisoformat(text)
    else:
        current = datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _parsed_timestamp(value: object) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _explicit_bool(value: object) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "passed", "verified"}:
            return True
        if normalized in {"false", "no", "0", "failed", "unverified"}:
            return False
    return None


def _contains_raw_media(payload: object) -> bool:
    if not isinstance(payload, Mapping):
        return False
    for key, value in payload.items():
        if (
            str(key).lower() in _RAW_MEDIA_KEYS
            and value is not None
            and value != ""
            and value is not False
        ):
            return True
        if isinstance(value, Mapping) and _contains_raw_media(value):
            return True
    return False


def normalize_beliefs(payload: Mapping[str, object]) -> Dict[str, float]:
    """Return a normalized finite distribution with at least two hypotheses."""
    if not isinstance(payload, Mapping):
        raise ValueError("beliefs must be a mapping")
    values: Dict[str, float] = {}
    for raw_name, raw_value in payload.items():
        name = _text(raw_name, 120)
        if not name:
            continue
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            raise ValueError(f"belief probability for {name!r} is not numeric")
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"belief probability for {name!r} must be finite and nonnegative")
        values[name] = value
    if len(values) < 2:
        raise ValueError("at least two hypotheses are required")
    total = sum(values.values())
    if total <= 0:
        raise ValueError("belief probabilities must have positive mass")
    return {name: value / total for name, value in sorted(values.items())}


def normalized_entropy(payload: Mapping[str, object]) -> float:
    """Return Shannon entropy as functional uncertainty on a 0-100 scale."""
    beliefs = normalize_beliefs(payload)
    entropy = -sum(value * math.log2(value) for value in beliefs.values() if value > 0)
    maximum = math.log2(len(beliefs))
    return round(100.0 * entropy / maximum, 3) if maximum else 0.0


def normalize_observation_model(
    payload: Mapping[str, Mapping[str, object]],
    *,
    hypotheses: Mapping[str, float],
) -> Dict[str, Dict[str, float]]:
    """Validate P(observation | hypothesis) fixed before the action runs."""
    if not isinstance(payload, Mapping) or len(payload) < 2:
        raise ValueError("an observation model with at least two outcomes is required")
    hypothesis_names = set(hypotheses)
    model: Dict[str, Dict[str, float]] = {}
    for raw_outcome, raw_likelihoods in payload.items():
        outcome = _text(raw_outcome, 120)
        if not outcome or not isinstance(raw_likelihoods, Mapping):
            raise ValueError("each observation outcome must name a likelihood mapping")
        likelihoods: Dict[str, float] = {}
        for hypothesis in sorted(hypothesis_names):
            if hypothesis not in raw_likelihoods:
                raise ValueError(f"observation outcome {outcome!r} omits hypothesis {hypothesis!r}")
            try:
                value = float(raw_likelihoods[hypothesis])
            except (TypeError, ValueError):
                raise ValueError(f"likelihood for {outcome!r}/{hypothesis!r} is not numeric")
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError("observation likelihoods must be finite probabilities")
            likelihoods[hypothesis] = value
        if set(raw_likelihoods) != hypothesis_names:
            raise ValueError("observation outcomes must use the exact prior hypothesis set")
        model[outcome] = likelihoods
    for hypothesis in sorted(hypothesis_names):
        total = sum(model[outcome][hypothesis] for outcome in model)
        if not math.isclose(total, 1.0, rel_tol=1e-6, abs_tol=1e-6):
            raise ValueError(
                f"observation likelihoods for {hypothesis!r} must sum to 1.0, got {total}"
            )
    return {outcome: model[outcome] for outcome in sorted(model)}


def posterior_from_observation(
    beliefs_before: Mapping[str, object],
    observation_model: Mapping[str, Mapping[str, object]],
    observed_outcome: str,
) -> Dict[str, float]:
    """Apply one precommitted Bayesian update; reject impossible outcomes."""
    prior = normalize_beliefs(beliefs_before)
    model = normalize_observation_model(observation_model, hypotheses=prior)
    outcome = _text(observed_outcome, 120)
    if outcome not in model:
        raise ValueError("observed outcome is not in the precommitted observation model")
    unnormalized = {
        hypothesis: prior[hypothesis] * model[outcome][hypothesis]
        for hypothesis in prior
    }
    evidence_probability = sum(unnormalized.values())
    if evidence_probability <= 0:
        raise ValueError("observed outcome had zero probability under every hypothesis")
    return {
        hypothesis: unnormalized[hypothesis] / evidence_probability
        for hypothesis in sorted(unnormalized)
    }


def _leading_hypothesis(beliefs: Mapping[str, float]) -> str:
    return max(sorted(beliefs), key=lambda key: beliefs[key])


def open_episode(
    orientation: Mapping[str, object],
    *,
    question: str,
    expected_observation: str,
    beliefs_before: Mapping[str, object],
    observation_model: Mapping[str, Mapping[str, object]],
    observation_model_source: str,
    executable_action: str = "",
    now: object = None,
) -> Dict[str, object]:
    """Open a proposal-only epistemic episode from one sensory orientation."""
    if not isinstance(orientation, Mapping) or not orientation:
        raise ValueError("a sensory orientation is required")
    if _contains_raw_media(orientation):
        raise ValueError("raw media is outside the active-sensing episode boundary")
    target_fingerprint = _text(orientation.get("target_fingerprint"), 160)
    recommended_action = _text(orientation.get("recommended_action"), 100)
    question_text = _text(question, 320)
    expected_text = _text(expected_observation, 320)
    action = _text(executable_action or recommended_action, 100)
    if not target_fingerprint or not recommended_action:
        raise ValueError("orientation must identify a target fingerprint and recommended action")
    if not question_text or not expected_text or not action:
        raise ValueError("question, expected observation, and executable action are required")
    beliefs = normalize_beliefs(beliefs_before)
    model_source = _text(observation_model_source, 180)
    if not model_source:
        raise ValueError("a source for the precommitted observation model is required")
    model = normalize_observation_model(observation_model, hypotheses=beliefs)
    opened_at = _timestamp(now)
    episode_id = "active-sensing-" + hashlib.sha256(
        json.dumps(
            {
                "opened_at": opened_at,
                "target": target_fingerprint,
                "question": question_text,
                "action": action,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:20]
    return {
        "schema_version": SCHEMA_VERSION,
        "id": episode_id,
        "opened_at": opened_at,
        "updated_at": opened_at,
        "status": "proposed",
        "question": question_text,
        "expected_observation": expected_text,
        "orientation": {
            "target_id": _text(orientation.get("target_id"), 120),
            "target_fingerprint": target_fingerprint,
            "subject": _text(orientation.get("subject"), 120),
            "summary": _text(orientation.get("summary"), 320),
            "recommended_action": recommended_action,
            "executable_action": action,
            "requested_modalities": [
                _text(item, 40)
                for item in orientation.get("requested_modalities", [])
                if _text(item, 40)
            ][:4],
            "requires_permission": bool(orientation.get("requires_permission")),
            "authority": "proposal_only",
        },
        "beliefs_before": beliefs,
        "observation_model": model,
        "observation_model_source": model_source,
        "prior_uncertainty": normalized_entropy(beliefs),
        "leading_hypothesis_before": _leading_hypothesis(beliefs),
        "action": {},
        "observation": {},
        "beliefs_after": {},
        "posterior_uncertainty": None,
        "information_gain": None,
        "belief_revision": False,
        "consequence_qualified": False,
        "closure_reason": "Awaiting an admitted, verified execution.",
        "boundary": BOUNDARY,
    }


def attach_action_result(
    episode: Mapping[str, object],
    action_result: Mapping[str, object],
    *,
    now: object = None,
) -> Dict[str, object]:
    """Attach execution evidence without treating execution as information gain."""
    result = copy.deepcopy(dict(episode))
    orientation = result.get("orientation") if isinstance(result.get("orientation"), dict) else {}
    expected_action = _text(orientation.get("executable_action"), 100)
    actual_action = _text(action_result.get("action"), 100)
    execution_id = _text(action_result.get("execution_id") or action_result.get("id"), 120)
    status = _text(action_result.get("status"), 40).lower()
    verification = _explicit_bool(action_result.get("execution_verification_ok"))
    if verification is None:
        verification = _explicit_bool(action_result.get("verification_ok"))
    executed = _explicit_bool(action_result.get("executed"))
    permission_required = bool(orientation.get("requires_permission"))
    permission_granted = _explicit_bool(action_result.get("permission_granted"))
    permission_evidence_id = _text(action_result.get("permission_evidence_id"), 120)
    permission_ok = bool(
        not permission_required
        or (permission_granted is True and permission_evidence_id)
    )
    verified = bool(
        execution_id
        and actual_action == expected_action
        and status == "completed"
        and verification is True
        and executed is not False
        and permission_ok
    )
    verified_at = _timestamp(now or action_result.get("updated_at") or action_result.get("created_at"))
    result["action"] = {
        "execution_id": execution_id,
        "expected_action": expected_action,
        "actual_action": actual_action,
        "status": status or "unknown",
        "executed": executed,
        "verification_ok": verification,
        "permission_required": permission_required,
        "permission_granted": permission_granted,
        "permission_evidence_id": permission_evidence_id,
        "verified_at": verified_at,
        "evidence_kind": "verified_action_execution" if verified else "unverified_action_execution",
        "summary": _text(action_result.get("summary") or action_result.get("execution_summary"), 260),
    }
    result["updated_at"] = verified_at
    result["status"] = "action_verified" if verified else "action_unverified"
    result["closure_reason"] = (
        "Execution verified; awaiting a later observation linked to this execution id."
        if verified
        else "Action did not satisfy exact action, execution-id, terminal-status, verification, and permission requirements."
    )
    result["consequence_qualified"] = False
    return result


def close_with_observation(
    episode: Mapping[str, object],
    observation: Mapping[str, object],
    *,
    minimum_information_gain: float = 1.0,
    now: object = None,
) -> Dict[str, object]:
    """Close only on later, source-attributed, causally linked evidence."""
    result = copy.deepcopy(dict(episode))
    action = result.get("action") if isinstance(result.get("action"), dict) else {}
    execution_id = _text(action.get("execution_id"), 120)
    observed_at = _timestamp(observation.get("observed_at") or now)
    verified_at = _parsed_timestamp(action.get("verified_at"))
    observed_time = _parsed_timestamp(observed_at)
    caused_by = _text(observation.get("caused_by_execution_id"), 120)
    source = _text(observation.get("source"), 120)
    observation_id = _text(observation.get("id"), 120)
    summary = _text(observation.get("summary"), 320)
    observed_outcome = _text(observation.get("outcome"), 120)
    causal_ok = bool(
        result.get("status") == "action_verified"
        and execution_id
        and caused_by == execution_id
        and verified_at
        and observed_time
        and observed_time >= verified_at
        and source
        and observation_id
        and summary
        and observed_outcome
        and not _contains_raw_media(observation)
    )
    if not causal_ok:
        result["updated_at"] = observed_at
        result["status"] = "observation_unqualified"
        result["consequence_qualified"] = False
        result["closure_reason"] = (
            "Observation lacked a verified predecessor, exact execution-id link, later timestamp, source, id, or summary."
        )
        return result

    before = normalize_beliefs(result.get("beliefs_before") or {})
    try:
        after = posterior_from_observation(
            before,
            result.get("observation_model") or {},
            observed_outcome,
        )
    except ValueError as exc:
        result["updated_at"] = observed_at
        result["status"] = "observation_unqualified"
        result["consequence_qualified"] = False
        result["closure_reason"] = _text(exc, 260)
        return result

    prior_uncertainty = normalized_entropy(before)
    posterior_uncertainty = normalized_entropy(after)
    information_gain = round(prior_uncertainty - posterior_uncertainty, 3)
    threshold = max(0.001, float(minimum_information_gain))
    leading_before = _leading_hypothesis(before)
    leading_after = _leading_hypothesis(after)
    result["observation"] = {
        "id": observation_id,
        "observed_at": observed_at,
        "source": source,
        "caused_by_execution_id": caused_by,
        "evidence_kind": _text(observation.get("evidence_kind"), 100) or "typed_feature_observation",
        "summary": summary,
        "outcome": observed_outcome,
        "target_fingerprint": _text(observation.get("target_fingerprint"), 160),
    }
    result["beliefs_after"] = after
    result["prior_uncertainty"] = prior_uncertainty
    result["posterior_uncertainty"] = posterior_uncertainty
    result["information_gain"] = information_gain
    result["leading_hypothesis_after"] = leading_after
    result["belief_revision"] = leading_before != leading_after
    result["updated_at"] = observed_at
    result["consequence_qualified"] = information_gain >= threshold
    if information_gain >= threshold:
        result["status"] = "closed_uncertainty_reduced"
        result["closure_reason"] = (
            f"A causally linked later observation reduced normalized uncertainty by {information_gain:.3f} points."
        )
    elif information_gain <= -threshold:
        result["status"] = "closed_uncertainty_increased"
        result["closure_reason"] = (
            f"The later observation increased normalized uncertainty by {abs(information_gain):.3f} points; do not self-reward."
        )
    else:
        result["status"] = "closed_no_material_change"
        result["closure_reason"] = "The later observation produced no material uncertainty reduction; do not self-reward."
    return result


def score_independent_outcome(
    episode: Mapping[str, object],
    *,
    ground_truth_hypothesis: str,
    ground_truth_source: str,
    ground_truth_evidence_id: str,
    observed_at: object,
) -> Dict[str, object]:
    """Score a closed posterior only when independent later truth is available.

    Reduced entropy can represent false certainty.  This separate step uses
    proper probabilistic scores against a later outcome from a different
    evidence source, so sharpness cannot be mistaken for accuracy.
    """
    posterior = normalize_beliefs(episode.get("beliefs_after") or {})
    prior = normalize_beliefs(episode.get("beliefs_before") or {})
    truth = _text(ground_truth_hypothesis, 120)
    source = _text(ground_truth_source, 160)
    evidence_id = _text(ground_truth_evidence_id, 160)
    observation = episode.get("observation") if isinstance(episode.get("observation"), dict) else {}
    observation_source = _text(observation.get("source"), 160)
    observation_id = _text(observation.get("id"), 160)
    truth_time = _parsed_timestamp(observed_at)
    episode_time = _parsed_timestamp(observation.get("observed_at") or episode.get("updated_at"))
    if not episode.get("consequence_qualified") or not posterior:
        raise ValueError("only a causally qualified closed episode can be scored")
    if truth not in posterior:
        raise ValueError("ground-truth hypothesis is not in the precommitted hypothesis set")
    if not source or not evidence_id or not truth_time or not episode_time:
        raise ValueError("ground truth requires source, evidence id, and valid observation time")
    if source == observation_source or evidence_id == observation_id:
        raise ValueError("ground truth must be independent of the active-sensing observation")
    if truth_time < episode_time:
        raise ValueError("ground truth cannot predate the observation being calibrated")

    def multiclass_brier(distribution: Mapping[str, float]) -> float:
        raw = sum(
            (float(probability) - (1.0 if hypothesis == truth else 0.0)) ** 2
            for hypothesis, probability in distribution.items()
        )
        return round(raw / 2.0, 6)

    prior_brier = multiclass_brier(prior)
    posterior_brier = multiclass_brier(posterior)
    posterior_truth_probability = float(posterior[truth])
    return {
        "schema_version": CALIBRATION_RECORD_SCHEMA_VERSION,
        "episode_id": _text(episode.get("id"), 120),
        "observation_model_source": _text(episode.get("observation_model_source"), 180),
        "scored_at": _timestamp(),
        "ground_truth": {
            "hypothesis": truth,
            "source": source,
            "evidence_id": evidence_id,
            "observed_at": _timestamp(truth_time),
            "independent_of_observation": True,
        },
        "prior_brier": prior_brier,
        "posterior_brier": posterior_brier,
        "brier_skill_delta": round(prior_brier - posterior_brier, 6),
        "posterior_truth_probability": round(posterior_truth_probability, 6),
        "posterior_log_loss": round(-math.log(max(posterior_truth_probability, 1e-12)), 6),
        "top_hypothesis_correct": _leading_hypothesis(posterior) == truth,
        "boundary": (
            "Independent probabilistic accuracy evidence for one functional episode; "
            "not proof of global calibration or subjective experience."
        ),
    }


def calibration_report(
    records: object,
    *,
    minimum_resolved_episodes: int = 5,
) -> Dict[str, object]:
    """Aggregate independent episode scores without overclaiming calibration."""
    source = records if isinstance(records, list) else []
    valid = []
    seen = set()
    for item in source:
        if not (
            isinstance(item, dict)
            and item.get("schema_version") == CALIBRATION_RECORD_SCHEMA_VERSION
            and isinstance(item.get("posterior_brier"), (int, float))
            and isinstance(item.get("prior_brier"), (int, float))
        ):
            continue
        truth = item.get("ground_truth") if isinstance(item.get("ground_truth"), dict) else {}
        episode_id = _text(item.get("episode_id"), 120)
        evidence_id = _text(truth.get("evidence_id"), 160)
        if not episode_id or not evidence_id or not truth.get("independent_of_observation"):
            continue
        key = (episode_id, evidence_id)
        if key in seen:
            continue
        seen.add(key)
        valid.append(item)
    count = len(valid)
    minimum = max(1, int(minimum_resolved_episodes))
    mean_prior = round(sum(float(item["prior_brier"]) for item in valid) / count, 6) if count else None
    mean_posterior = (
        round(sum(float(item["posterior_brier"]) for item in valid) / count, 6)
        if count
        else None
    )
    mean_skill = (
        round(sum(float(item.get("brier_skill_delta") or 0.0) for item in valid) / count, 6)
        if count
        else None
    )
    accuracy = (
        round(sum(1 for item in valid if item.get("top_hypothesis_correct")) / count, 4)
        if count
        else None
    )
    enough = count >= minimum
    if not enough:
        status = "insufficient_independent_outcomes"
    elif mean_skill is not None and mean_skill > 0:
        status = "measured_better_than_prior"
    else:
        status = "measured_not_better_than_prior"
    model_sources = sorted(
        {
            _text(item.get("observation_model_source"), 180)
            for item in valid
            if _text(item.get("observation_model_source"), 180)
        }
    )
    return {
        "schema_version": CALIBRATION_REPORT_SCHEMA_VERSION,
        "status": status,
        "resolved_episode_count": count,
        "minimum_resolved_episodes": minimum,
        "enough_for_aggregate_comparison": enough,
        "mean_prior_brier": mean_prior,
        "mean_posterior_brier": mean_posterior,
        "mean_brier_skill_delta": mean_skill,
        "top_hypothesis_accuracy": accuracy,
        "observation_model_sources": model_sources,
        "calibration_proven": False,
        "boundary": (
            "Aggregate proper-score evidence can falsify a poor observation model; "
            "it does not by itself prove calibration, consciousness, or truth in unobserved cases."
        ),
    }


def matched_causal_evaluation() -> Dict[str, object]:
    """Run an intact episode and negative controls that differ by one causal gate."""
    orientation = {
        "target_id": "system-state-1",
        "target_fingerprint": "system-state-hot",
        "subject": "local-runtime",
        "summary": "Runtime state is ambiguous.",
        "recommended_action": "inspect_local_state",
        "requested_modalities": ["system"],
        "authority": "proposal_only",
    }
    opened = open_episode(
        orientation,
        question="Is the runtime currently healthy or degraded?",
        expected_observation="A fresh verified local probe should distinguish healthy from degraded.",
        beliefs_before={"healthy": 0.5, "degraded": 0.5},
        observation_model={
            "healthy_receipt": {"healthy": 0.9, "degraded": 0.05},
            "degraded_receipt": {"healthy": 0.05, "degraded": 0.9},
            "inconclusive": {"healthy": 0.05, "degraded": 0.05},
        },
        observation_model_source="service_health_check.typed_contract.v1",
        executable_action="service_health_check",
        now="2026-08-23T16:00:00+00:00",
    )
    verified = attach_action_result(
        opened,
        {
            "action": "service_health_check",
            "execution_id": "execution-active-sensing-1",
            "status": "completed",
            "executed": True,
            "execution_verification_ok": True,
            "summary": "The bounded service-health probe completed.",
        },
        now="2026-08-23T16:00:01+00:00",
    )
    observation = {
        "id": "observation-active-sensing-1",
        "observed_at": "2026-08-23T16:00:02+00:00",
        "source": "service_health_check",
        "caused_by_execution_id": "execution-active-sensing-1",
        "summary": "All required local services returned healthy receipts.",
        "outcome": "healthy_receipt",
        "target_fingerprint": "system-state-hot",
    }
    intact = close_with_observation(
        verified,
        observation,
    )
    no_execution = close_with_observation(
        opened,
        observation,
    )
    unverified = attach_action_result(
        opened,
        {
            "action": "service_health_check",
            "execution_id": "execution-active-sensing-1",
            "status": "completed",
            "executed": True,
            "execution_verification_ok": False,
        },
        now="2026-08-23T16:00:01+00:00",
    )
    wrong_cause = close_with_observation(
        verified,
        {**observation, "caused_by_execution_id": "different-execution"},
    )
    stale = close_with_observation(
        verified,
        {**observation, "observed_at": "2026-08-23T15:59:59+00:00"},
    )
    no_gain = close_with_observation(
        verified,
        {**observation, "outcome": "inconclusive"},
    )
    independently_confirmed = score_independent_outcome(
        intact,
        ground_truth_hypothesis="healthy",
        ground_truth_source="independent_runtime_receipt",
        ground_truth_evidence_id="independent-health-truth-1",
        observed_at="2026-08-23T16:00:03+00:00",
    )
    false_certainty = score_independent_outcome(
        intact,
        ground_truth_hypothesis="degraded",
        ground_truth_source="independent_runtime_receipt",
        ground_truth_evidence_id="independent-health-truth-2",
        observed_at="2026-08-23T16:00:03+00:00",
    )
    checks = {
        "intact_qualified": bool(intact.get("consequence_qualified")),
        "no_execution_rejected": not bool(no_execution.get("consequence_qualified")),
        "unverified_action_rejected": unverified.get("status") == "action_unverified",
        "wrong_cause_rejected": not bool(wrong_cause.get("consequence_qualified")),
        "stale_observation_rejected": not bool(stale.get("consequence_qualified")),
        "no_gain_not_rewarded": not bool(no_gain.get("consequence_qualified")),
        "independent_truth_rewards_accuracy": independently_confirmed.get("brier_skill_delta", 0) > 0,
        "independent_truth_penalizes_false_certainty": false_certainty.get("brier_skill_delta", 0) < 0,
    }
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "intact": intact,
        "negative_controls": {
            "no_execution": no_execution,
            "unverified_action": unverified,
            "wrong_cause": wrong_cause,
            "stale_observation": stale,
            "no_information_gain": no_gain,
        },
        "independent_outcome_controls": {
            "confirmed": independently_confirmed,
            "false_certainty": false_certainty,
        },
        "boundary": BOUNDARY,
    }


__all__ = [
    "BOUNDARY",
    "CALIBRATION_RECORD_SCHEMA_VERSION",
    "CALIBRATION_REPORT_SCHEMA_VERSION",
    "EVALUATION_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "attach_action_result",
    "close_with_observation",
    "calibration_report",
    "matched_causal_evaluation",
    "normalize_beliefs",
    "normalize_observation_model",
    "normalized_entropy",
    "open_episode",
    "posterior_from_observation",
    "score_independent_outcome",
]
