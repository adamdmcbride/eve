"""Calibrated observable-response prediction for Eve's social control loop.

This module predicts only what a counterpart may *observably do next* in the
current conversation.  It deliberately does not infer private emotions,
beliefs, desires, or intentions.  Predictions are probability distributions,
are joined to an exact reply, and are scored with a proper multiclass score
when the next genuine counterpart message arrives.

The resulting signal is useful for conversational prediction error and
relationship calibration.  It is not evidence of subjective experience or
consciousness, and it must not be optimized for engagement or compliance.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import math
import re
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


SCHEMA_VERSION = "eve.observable_social_prediction.v1"
OUTCOME_SCHEMA_VERSION = "eve.observable_social_outcome.v1"
MODEL_SCHEMA_VERSION = "eve.observable_social_model.v1"
RESPONSE_CLASSES: Tuple[str, ...] = (
    "acceptance",
    "correction",
    "answer",
    "follow_up_question",
    "continuation",
    "topic_shift",
)
BOUNDARY = (
    "Observable conversational behavior only; no private mental-state access, "
    "engagement optimization, persuasion objective, or consciousness claim."
)


def _text(value: object, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def _finite(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _clamp(value: object, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, _finite(value, low)))


def _normalized_distribution(value: object) -> Dict[str, float]:
    raw = value if isinstance(value, Mapping) else {}
    weights = {
        label: max(0.0, _finite(raw.get(label), 0.0))
        for label in RESPONSE_CLASSES
    }
    total = sum(weights.values())
    if total <= 0.0:
        return {label: round(1.0 / len(RESPONSE_CLASSES), 6) for label in RESPONSE_CLASSES}
    rounded = {label: round(weight / total, 6) for label, weight in weights.items()}
    # Preserve an exact probability simplex after rounding.
    drift = round(1.0 - sum(rounded.values()), 6)
    winner = max(RESPONSE_CLASSES, key=lambda label: rounded[label])
    rounded[winner] = round(rounded[winner] + drift, 6)
    return rounded


def _normalized_entropy(distribution: Mapping[str, object]) -> float:
    probabilities = [_clamp(distribution.get(label)) for label in RESPONSE_CLASSES]
    entropy = -sum(p * math.log(p) for p in probabilities if p > 0.0)
    denominator = math.log(len(RESPONSE_CLASSES))
    return round(entropy / denominator if denominator else 0.0, 6)


def _looks_like_question(text: str) -> bool:
    lowered = text.lower().strip()
    if "?" in lowered:
        return True
    return lowered.startswith(
        (
            "who ",
            "what ",
            "when ",
            "where ",
            "why ",
            "how ",
            "can ",
            "could ",
            "would ",
            "should ",
            "do ",
            "does ",
            "did ",
            "is ",
            "are ",
            "will ",
        )
    )


def _reply_features(reply_text: object, inbound_text: object = "") -> Dict[str, bool]:
    reply = _text(reply_text, 1200).lower().replace("’", "'")
    inbound = _text(inbound_text, 800).lower().replace("’", "'")
    action_claim = any(
        cue in reply
        for cue in (
            "i'll ",
            "i will ",
            "let me ",
            "i'm going to ",
            "i have ",
            "i've ",
            "done.",
            "fixed",
            "completed",
            "i can ",
        )
    )
    topic_shift_invitation = any(
        cue in reply
        for cue in ("anything else", "what next", "another topic", "what else")
    )
    return {
        "reply_asked_question": _looks_like_question(reply),
        "inbound_was_question": _looks_like_question(inbound),
        "reply_made_action_claim": action_claim,
        "reply_invited_topic_shift": topic_shift_invitation,
    }


def _base_distribution(features: Mapping[str, bool]) -> Dict[str, float]:
    if features.get("reply_invited_topic_shift"):
        weights = {
            "acceptance": 0.07,
            "correction": 0.05,
            "answer": 0.03,
            "follow_up_question": 0.15,
            "continuation": 0.15,
            "topic_shift": 0.55,
        }
    elif features.get("reply_asked_question"):
        weights = {
            "acceptance": 0.08,
            "correction": 0.08,
            "answer": 0.52,
            "follow_up_question": 0.13,
            "continuation": 0.14,
            "topic_shift": 0.05,
        }
    elif features.get("reply_made_action_claim"):
        weights = {
            "acceptance": 0.25,
            "correction": 0.20,
            "answer": 0.03,
            "follow_up_question": 0.22,
            "continuation": 0.20,
            "topic_shift": 0.10,
        }
    else:
        weights = {
            "acceptance": 0.13,
            "correction": 0.10,
            "answer": 0.02,
            "follow_up_question": 0.30,
            "continuation": 0.32,
            "topic_shift": 0.13,
        }
    return _normalized_distribution(weights)


def _history_prior(history: object) -> Tuple[Dict[str, float], int]:
    summary = history if isinstance(history, Mapping) else {}
    count = max(0, int(summary.get("scored_count") or summary.get("evidence_count") or 0))
    return _normalized_distribution(summary.get("response_prior")), count


def build_prediction(
    *,
    reply_text: object,
    inbound_text: object = "",
    thread_id: object = "",
    source_message_id: object = "",
    reply_message_id: object = "",
    made_at: object = "",
    history: Optional[Mapping[str, object]] = None,
    lesioned: bool = False,
) -> Dict[str, object]:
    """Build one exact-lineage probability distribution over observable replies."""
    clean_thread_id = _text(thread_id, 120)
    clean_source_id = _text(source_message_id, 120)
    clean_reply_id = _text(reply_message_id, 120)
    clean_made_at = _text(made_at, 80)
    features = _reply_features(reply_text, inbound_text)
    base = _base_distribution(features)
    prior, history_count = _history_prior(history)
    # Sparse personal history should never erase the immediate conversational
    # evidence.  The contribution rises slowly and is capped at 25%.
    history_weight = 0.0 if history_count < 4 else min(0.25, 0.06 + math.log1p(history_count) / 24.0)
    if lesioned:
        distribution = _normalized_distribution({})
        history_weight = 0.0
    else:
        distribution = _normalized_distribution(
            {
                label: (1.0 - history_weight) * base[label] + history_weight * prior[label]
                for label in RESPONSE_CLASSES
            }
        )
    predicted_class = max(RESPONSE_CLASSES, key=lambda label: distribution[label])
    seed = ":".join((SCHEMA_VERSION, clean_thread_id, clean_source_id, clean_reply_id))
    prediction_id = "social-prediction:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    reply_fingerprint = hashlib.sha256(_text(reply_text, 4000).encode("utf-8")).hexdigest()
    confidence = distribution[predicted_class]
    return {
        "schema_version": SCHEMA_VERSION,
        "prediction_id": prediction_id,
        "made_at": clean_made_at,
        "thread_id": clean_thread_id,
        "source_message_id": clean_source_id,
        "reply_message_id": clean_reply_id,
        "reply_fingerprint": reply_fingerprint,
        "classes": list(RESPONSE_CLASSES),
        "distribution": distribution,
        "predicted_class": predicted_class,
        "top_probability": round(confidence, 6),
        "normalized_entropy": _normalized_entropy(distribution),
        "history_evidence_count": history_count,
        "history_weight": round(history_weight, 6),
        "features": features,
        "authority": "observation_and_calibration_only",
        "boundary": BOUNDARY,
        "lesioned": bool(lesioned),
    }


def classify_observed_response(
    text: object,
    *,
    prediction: Optional[Mapping[str, object]] = None,
    correction: bool = False,
    explicit_acceptance: bool = False,
) -> str:
    """Classify visible response form without claiming access to hidden state."""
    normalized = _text(text, 1200).lower().replace("’", "'")
    if not normalized:
        return ""
    if correction:
        return "correction"
    if explicit_acceptance:
        return "acceptance"
    if normalized.startswith(
        (
            "new question",
            "different question",
            "another question",
            "separately",
            "unrelated",
            "changing topics",
            "on another topic",
        )
    ):
        return "topic_shift"
    features = prediction.get("features") if isinstance(prediction, Mapping) else {}
    if isinstance(features, Mapping) and features.get("reply_asked_question") and not _looks_like_question(normalized):
        return "answer"
    if _looks_like_question(normalized):
        return "follow_up_question"
    return "continuation"


def explicitly_corrects_prior_reply(
    text: object,
    *,
    prediction: Optional[Mapping[str, object]] = None,
) -> bool:
    """Recognize corrections aimed at the exchange, not incidental words.

    A broad keyword such as ``wrong`` is insufficient: "what is wrong with the
    server?" is a question, not evidence that Eve's previous reply failed.
    """
    normalized = _text(text, 1200).lower().replace("’", "'")
    if not normalized:
        return False
    features = prediction.get("features") if isinstance(prediction, Mapping) else {}
    reply_asked_question = bool(
        isinstance(features, Mapping) and features.get("reply_asked_question")
    )
    explicit_exchange_cues = (
        "answer my question",
        "you didn't answer",
        "you didnt answer",
        "you missed my question",
        "that's wrong",
        "that is wrong",
        "your answer is wrong",
        "you are wrong",
        "you're wrong",
        "not what i asked",
        "not what i meant",
        "wrong conversation",
        "you keep repeating",
    )
    if re.match(r"^(?:no|nope)(?:\b|[,.!])", normalized):
        if reply_asked_question and not any(cue in normalized for cue in explicit_exchange_cues):
            return False
        return True
    if re.match(
        r"^(?:i mean|what i mean is|not what i asked|that's not what|that is not what)\b",
        normalized,
    ):
        return True
    if any(cue in normalized for cue in explicit_exchange_cues):
        return True
    return bool(
        re.search(
            r"\b(?:your answer|your response|what you said|you)\b.{0,48}\b(?:incorrect|missed|mistaken)\b",
            normalized,
        )
    )


def explicitly_accepts_prior_reply(
    text: object,
    *,
    coarse_acceptance: bool,
    prediction: Optional[Mapping[str, object]] = None,
) -> bool:
    """Keep answers to Eve's own question from becoming false reward."""
    if not coarse_acceptance:
        return False
    normalized = _text(text, 1200).lower().replace("’", "'")
    features = prediction.get("features") if isinstance(prediction, Mapping) else {}
    reply_asked_question = bool(
        isinstance(features, Mapping) and features.get("reply_asked_question")
    )
    if re.search(r"\b(?:but|however|although|though|except)\b", normalized):
        return False
    if not reply_asked_question:
        return True
    evaluative_cues = (
        "thank you",
        "thanks",
        "great",
        "perfect",
        "that's correct",
        "that is correct",
        "that works",
        "looks good",
        "sounds good",
        "good job",
    )
    return any(cue in normalized for cue in evaluative_cues)


def score_prediction(
    prediction: Mapping[str, object],
    observed_class: object,
    *,
    observed_message_id: object = "",
    observed_at: object = "",
    lesioned: bool = False,
) -> Dict[str, object]:
    """Score a later visible response with normalized multiclass Brier loss."""
    label = _text(observed_class, 40)
    distribution = _normalized_distribution(prediction.get("distribution"))
    valid = (
        prediction.get("schema_version") == SCHEMA_VERSION
        and label in RESPONSE_CLASSES
        and bool(_text(prediction.get("prediction_id"), 100))
        and bool(_text(prediction.get("reply_message_id"), 120))
    )
    if not valid:
        return {
            "schema_version": OUTCOME_SCHEMA_VERSION,
            "scored": False,
            "reason": "invalid_or_unscorable_prediction",
            "boundary": BOUNDARY,
        }
    if lesioned:
        distribution = _normalized_distribution({})
    squared = sum(
        (distribution[candidate] - (1.0 if candidate == label else 0.0)) ** 2
        for candidate in RESPONSE_CLASSES
    )
    normalized_brier = round(squared / 2.0, 6)
    probability = max(1e-9, distribution[label])
    log_loss = round(-math.log(probability), 6)
    predicted_class = max(RESPONSE_CLASSES, key=lambda candidate: distribution[candidate])
    return {
        "schema_version": OUTCOME_SCHEMA_VERSION,
        "scored": True,
        "prediction_id": _text(prediction.get("prediction_id"), 100),
        "reply_message_id": _text(prediction.get("reply_message_id"), 120),
        "observed_message_id": _text(observed_message_id, 120),
        "observed_at": _text(observed_at, 80),
        "observed_class": label,
        "predicted_class": predicted_class,
        "top1_correct": predicted_class == label,
        "observed_probability": round(probability, 6),
        "normalized_brier": normalized_brier,
        "log_loss": log_loss,
        "error_magnitude": int(round(normalized_brier * 100.0)),
        "lesioned": bool(lesioned),
        "boundary": BOUNDARY,
    }


def _parse_timestamp(value: object) -> Optional[datetime]:
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


def observation_matches_prediction(
    prediction: Mapping[str, object],
    *,
    thread_id: object,
    reply_message_id: object,
    observed_message_id: object,
    observed_at: object = "",
) -> bool:
    """Require exact thread/reply lineage and a later distinct observation."""
    if prediction.get("schema_version") != SCHEMA_VERSION:
        return False
    if _text(prediction.get("thread_id"), 120) != _text(thread_id, 120):
        return False
    if _text(prediction.get("reply_message_id"), 120) != _text(reply_message_id, 120):
        return False
    observed_id = _text(observed_message_id, 120)
    if not observed_id or observed_id == _text(prediction.get("source_message_id"), 120):
        return False
    made = _parse_timestamp(prediction.get("made_at"))
    observed = _parse_timestamp(observed_at)
    return not (made and observed and observed < made)


def summarize_records(
    records: Iterable[Mapping[str, object]],
    *,
    feedback_lesioned: bool = False,
) -> Dict[str, object]:
    """Derive a bounded, text-free dynamic model from scored observations."""
    scored: List[Mapping[str, object]] = []
    abstentions = 0
    for record in records:
        if str(record.get("kind") or "") != "conversational":
            continue
        outcome = record.get("social_outcome")
        if not isinstance(outcome, Mapping) or not outcome.get("scored"):
            abstentions += 1
            continue
        if _text(outcome.get("observed_class"), 40) not in RESPONSE_CLASSES:
            continue
        scored.append(record)
    if feedback_lesioned:
        scored = []
    counts = {label: 0 for label in RESPONSE_CLASSES}
    briers: List[float] = []
    correct = 0
    evidence_ids: List[str] = []
    for record in scored[-256:]:
        outcome = record.get("social_outcome") if isinstance(record.get("social_outcome"), Mapping) else {}
        label = _text(outcome.get("observed_class"), 40)
        counts[label] += 1
        briers.append(_clamp(outcome.get("normalized_brier")))
        correct += int(bool(outcome.get("top1_correct")))
        evidence_id = _text(record.get("evidence_id"), 160)
        if evidence_id:
            evidence_ids.append(evidence_id)
    count = len(scored)
    response_prior = _normalized_distribution({label: counts[label] + 1.0 for label in RESPONSE_CLASSES})
    recent = scored[-8:]
    prior_window = scored[-16:-8]
    shift: Optional[float] = None
    if recent and prior_window:
        recent_counts = {label: 1.0 for label in RESPONSE_CLASSES}
        prior_counts = {label: 1.0 for label in RESPONSE_CLASSES}
        for record in recent:
            outcome = record.get("social_outcome") if isinstance(record.get("social_outcome"), Mapping) else {}
            recent_counts[_text(outcome.get("observed_class"), 40)] += 1.0
        for record in prior_window:
            outcome = record.get("social_outcome") if isinstance(record.get("social_outcome"), Mapping) else {}
            prior_counts[_text(outcome.get("observed_class"), 40)] += 1.0
        recent_dist = _normalized_distribution(recent_counts)
        prior_dist = _normalized_distribution(prior_counts)
        shift = round(
            0.5 * sum(abs(recent_dist[label] - prior_dist[label]) for label in RESPONSE_CLASSES),
            6,
        )
    last = scored[-1] if scored else {}
    last_outcome = last.get("social_outcome") if isinstance(last.get("social_outcome"), Mapping) else {}
    return {
        "schema_version": MODEL_SCHEMA_VERSION,
        "authority": "observable_behavior_only",
        "evidence_count": count,
        "scored_count": count,
        "abstention_count": abstentions,
        "response_prior": response_prior,
        "observed_counts": counts,
        "mean_normalized_brier": round(sum(briers) / count, 6) if count else None,
        "top1_accuracy": round(correct / count, 6) if count else None,
        "last_observed_class": _text(last_outcome.get("observed_class"), 40),
        "last_prediction_id": _text(last_outcome.get("prediction_id"), 100),
        "distribution_shift": shift,
        "recent_evidence_ids": evidence_ids[-8:],
        "feedback_lesioned": bool(feedback_lesioned),
        "contains_user_text": False,
        "contains_private_mental_state": False,
        "boundary": BOUNDARY,
    }


def normalize_model(value: object) -> Dict[str, object]:
    """Normalize a persisted/derived social model without accepting prose state."""
    raw = value if isinstance(value, Mapping) else {}
    counts_raw = raw.get("observed_counts") if isinstance(raw.get("observed_counts"), Mapping) else {}
    evidence_ids = raw.get("recent_evidence_ids") if isinstance(raw.get("recent_evidence_ids"), list) else []
    evidence_count = max(0, min(1000000, int(raw.get("evidence_count") or 0)))
    scored_count = max(0, min(evidence_count, int(raw.get("scored_count") or evidence_count)))
    mean_brier = raw.get("mean_normalized_brier")
    accuracy = raw.get("top1_accuracy")
    shift = raw.get("distribution_shift")
    return {
        "schema_version": MODEL_SCHEMA_VERSION,
        "authority": "observable_behavior_only",
        "evidence_count": evidence_count,
        "scored_count": scored_count,
        "abstention_count": max(0, min(1000000, int(raw.get("abstention_count") or 0))),
        "response_prior": _normalized_distribution(raw.get("response_prior")),
        "observed_counts": {
            label: max(0, min(1000000, int(counts_raw.get(label) or 0)))
            for label in RESPONSE_CLASSES
        },
        "mean_normalized_brier": round(_clamp(mean_brier), 6) if mean_brier is not None else None,
        "top1_accuracy": round(_clamp(accuracy), 6) if accuracy is not None else None,
        "last_observed_class": (
            _text(raw.get("last_observed_class"), 40)
            if _text(raw.get("last_observed_class"), 40) in RESPONSE_CLASSES
            else ""
        ),
        "last_prediction_id": _text(raw.get("last_prediction_id"), 100),
        "distribution_shift": round(_clamp(shift), 6) if shift is not None else None,
        "recent_evidence_ids": [
            _text(item, 160) for item in evidence_ids[-8:] if _text(item, 160)
        ],
        "feedback_lesioned": bool(raw.get("feedback_lesioned")),
        "contains_user_text": False,
        "contains_private_mental_state": False,
        "boundary": BOUNDARY,
    }


def sanitize_ledger_record(record: Mapping[str, object]) -> Dict[str, object]:
    """Remove user text while preserving exact ids, labels, and scores."""
    sanitized = dict(record)
    observed_text = _text(sanitized.pop("observed_text", ""), 4000)
    if observed_text:
        sanitized["observed_text_sha256"] = hashlib.sha256(observed_text.encode("utf-8")).hexdigest()
    sanitized["contains_user_text"] = False
    sanitized["contains_private_mental_state"] = False
    return sanitized
