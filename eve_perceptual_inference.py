"""Precision-weighted generative hypotheses over Eve's admitted sensor features.

This module never reconstructs raw input and never changes the observation that
arrived.  It compares a bounded top-down feature prediction with a sparse
bottom-up feature vector and exposes an auditable posterior hypothesis.  The
result can request more evidence, but has no action, memory, or truth authority.
"""

from __future__ import annotations

import copy
import math
from typing import Dict, Mapping


SCHEMA_ID = "eve.generative_perceptual_inference.v1"
BOUNDARY = (
    "Precision-weighted hypothesis over already-admitted sparse features; not "
    "raw perception, a truth rewrite, subjective experience, or proof of consciousness."
)


def _finite(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _clamp(value: object, low: float, high: float, default: float = 0.0) -> float:
    return max(low, min(high, _finite(value, default)))


def _normalized_features(
    value: object,
    *,
    feature_limits: Mapping[str, float],
    feature_enums: Mapping[str, object],
) -> Dict[str, object]:
    source = value if isinstance(value, Mapping) else {}
    modality = str(source.get("feature_modality") or "").strip().lower()[:32]
    result: Dict[str, object] = {"feature_modality": modality} if modality else {}
    for key, raw in source.items():
        if key == "feature_modality":
            continue
        if key in feature_limits and not isinstance(raw, bool):
            number = _finite(raw, float("nan"))
            if math.isfinite(number):
                result[key] = round(
                    max(0.0, min(float(feature_limits[key]), number)),
                    6,
                )
        elif key in feature_enums and isinstance(raw, str):
            admitted = feature_enums[key]
            if raw in admitted:
                result[key] = raw
        elif key in {"active", "visible"} and isinstance(raw, bool):
            result[key] = raw
    return result


def infer_hypothesis(
    observed_features: object,
    predicted_features: object,
    *,
    sensory_precision: object,
    prior_precision: object,
    feature_limits: Mapping[str, float],
    feature_enums: Mapping[str, object],
    lesioned: bool = False,
) -> Dict[str, object]:
    """Combine top-down prediction and bottom-up evidence without overwriting either."""
    observed = _normalized_features(
        observed_features,
        feature_limits=feature_limits,
        feature_enums=feature_enums,
    )
    predicted = _normalized_features(
        predicted_features,
        feature_limits=feature_limits,
        feature_enums=feature_enums,
    )
    modality = str(observed.get("feature_modality") or "")
    same_modality = bool(
        modality and modality == str(predicted.get("feature_modality") or "")
    )
    sensory = _clamp(sensory_precision, 0.0, 100.0, 0.0)
    prior = 0.0 if lesioned or not same_modality else _clamp(
        prior_precision, 0.0, 100.0, 0.0
    )
    comparable_keys = sorted(
        key
        for key in observed
        if key != "feature_modality" and key in predicted
    )
    posterior = copy.deepcopy(observed)
    dimension_evidence: Dict[str, Dict[str, object]] = {}
    normalized_disagreements = []
    normalized_shifts = []
    denominator = sensory + prior
    for key in comparable_keys:
        actual = observed[key]
        expectation = predicted[key]
        if key in feature_limits and not isinstance(actual, bool):
            limit = max(1e-9, float(feature_limits[key]))
            disagreement = min(100.0, abs(float(actual) - float(expectation)) / limit * 100.0)
            inferred = (
                (sensory * float(actual) + prior * float(expectation)) / denominator
                if denominator > 0.0
                else float(actual)
            )
            inferred = max(0.0, min(limit, inferred))
            posterior[key] = round(inferred, 6)
            shift = min(100.0, abs(inferred - float(actual)) / limit * 100.0)
        else:
            disagreement = 0.0 if actual == expectation else 100.0
            inferred = expectation if prior > sensory else actual
            posterior[key] = inferred
            shift = 0.0 if inferred == actual else 100.0
        normalized_disagreements.append(disagreement)
        normalized_shifts.append(shift)
        dimension_evidence[key] = {
            "observed": actual,
            "predicted": expectation,
            "posterior": posterior[key],
            "disagreement_percent": round(disagreement, 6),
            "posterior_shift_percent": round(shift, 6),
        }

    prior_weight = prior / denominator if denominator > 0.0 else 0.0
    sensory_weight = sensory / denominator if denominator > 0.0 else 1.0
    maximum_disagreement = max(normalized_disagreements, default=0.0)
    maximum_shift = max(normalized_shifts, default=0.0)
    if not comparable_keys or prior <= 0.0:
        dominance = "bottom_up_only"
    elif prior_weight > 0.60:
        dominance = "top_down"
    elif sensory_weight > 0.60:
        dominance = "bottom_up"
    else:
        dominance = "balanced"
    sensory_override = bool(
        prior > 0.0
        and comparable_keys
        and sensory >= 70.0
        and maximum_disagreement >= 8.0
    )
    needs_active_sampling = bool(
        not lesioned
        and prior > 0.0
        and comparable_keys
        and maximum_disagreement >= 8.0
        and (
            sensory < 50.0
            or (abs(sensory - prior) <= 15.0 and max(sensory, prior) < 75.0)
        )
    )
    status = (
        "lesioned"
        if lesioned
        else "no_top_down_prediction"
        if not comparable_keys or prior <= 0.0
        else "sensory_override"
        if sensory_override
        else "ambiguous_inference"
        if needs_active_sampling
        else "integrated_hypothesis"
    )
    return {
        "schema_version": SCHEMA_ID,
        "status": status,
        "enabled": not bool(lesioned),
        "lesioned": bool(lesioned),
        "modality": modality,
        "comparable": bool(comparable_keys and prior > 0.0),
        "dimension_count": len(comparable_keys),
        "sensory_precision": round(sensory, 6),
        "prior_precision": round(prior, 6),
        "sensory_weight": round(sensory_weight, 6),
        "prior_weight": round(prior_weight, 6),
        "dominance": dominance,
        "maximum_disagreement_percent": round(maximum_disagreement, 6),
        "maximum_posterior_shift_percent": round(maximum_shift, 6),
        "sensory_override": sensory_override,
        "needs_active_sampling": needs_active_sampling,
        "observed_features": observed,
        "predicted_features": predicted if same_modality else {},
        "posterior_features": posterior,
        "dimension_evidence": dimension_evidence,
        "observation_rewritten": False,
        "proposal_only": True,
        "causal_role": "hypothesis selection and proposal-only uncertainty sampling",
        "boundary": BOUNDARY,
    }
