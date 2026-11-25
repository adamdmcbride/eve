"""Bounded multi-hypothesis forecasting for Eve's sparse perceptual features.

This is an isolated cognition primitive.  It operates only on short histories
of admitted scalar or categorical features and has no sensor, tool, action,
memory, or model-serving authority.
"""

from __future__ import annotations

import math
from typing import Dict, List, Mapping, Sequence


SCHEMA = "eve.predictive_dynamics.v1"
BOUNDARY = (
    "Auditable forecasts over short admitted feature histories; not a claim "
    "that predictions, errors, or uncertainty are consciously experienced."
)
DEFAULT_ERROR_THRESHOLD = 8.0
MAX_HISTORY = 16

NUMERIC_EXPERTS = ("persistence", "velocity", "acceleration", "period_2")
_COMPLEXITY_PENALTY = {
    "persistence": 0.0,
    "velocity": 0.5,
    "acceleration": 1.0,
    "period_2": 1.0,
}
_MINIMUM_HISTORY = {
    "persistence": 1,
    "velocity": 2,
    "acceleration": 3,
    "period_2": 2,
}


def _finite(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("numeric feature history must contain finite numbers")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("numeric feature history must contain finite numbers")
    return number


def _clip(value: float, limit: float) -> float:
    return max(0.0, min(limit, value))


def _numeric_history(values: Sequence[object], *, limit: object) -> tuple[List[float], float]:
    try:
        bound = float(limit)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("feature limit must be a positive finite number") from exc
    if not math.isfinite(bound) or bound <= 0:
        raise ValueError("feature limit must be a positive finite number")
    history = [_finite(item) for item in list(values)[-MAX_HISTORY:]]
    if len(history) < 2:
        raise ValueError("at least two numeric observations are required")
    if any(item < 0 or item > bound for item in history):
        raise ValueError("numeric feature history exceeds its admitted range")
    return history, bound


def _expert_prediction(name: str, history: Sequence[float], limit: float) -> float:
    if name == "persistence":
        prediction = history[-1]
    elif name == "velocity":
        prediction = history[-1] + (history[-1] - history[-2])
    elif name == "acceleration":
        latest_delta = history[-1] - history[-2]
        prior_delta = history[-2] - history[-3]
        prediction = history[-1] + latest_delta + (latest_delta - prior_delta)
    elif name == "period_2":
        prediction = history[-2]
    else:
        raise ValueError(f"unknown predictive expert: {name}")
    return _clip(prediction, limit)


def _expert_backtest(name: str, history: Sequence[float], limit: float) -> Dict[str, object]:
    minimum = _MINIMUM_HISTORY[name]
    errors: List[float] = []
    for index in range(minimum, len(history)):
        prediction = _expert_prediction(name, history[:index], limit)
        errors.append(abs(history[index] - prediction) * 100.0 / limit)
    prediction = _expert_prediction(name, history, limit)
    mean_error = sum(errors) / len(errors) if errors else 100.0
    # A one-hit complex expert should not beat a simpler model on a tie.  The
    # penalty vanishes gradually as more prospective errors have been seen.
    evidence_penalty = 1.0 / max(1, len(errors)) if name in {"acceleration", "period_2"} else 0.0
    selection_score = mean_error + _COMPLEXITY_PENALTY[name] + evidence_penalty
    return {
        "name": name,
        "prediction": round(prediction, 6),
        "backtest_count": len(errors),
        "mean_absolute_error_percent": round(mean_error, 6),
        "selection_score": round(selection_score, 6),
    }


def forecast_numeric(
    values: Sequence[object],
    *,
    limit: object,
    source_precision: object = 100.0,
    enabled_experts: Sequence[str] = NUMERIC_EXPERTS,
) -> Dict[str, object]:
    """Select one dynamics hypothesis from prospective history errors."""
    history, bound = _numeric_history(values, limit=limit)
    try:
        raw_source_weight = float(source_precision)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("source precision must be a finite number") from exc
    if not math.isfinite(raw_source_weight):
        raise ValueError("source precision must be a finite number")
    source_weight = max(0.0, min(100.0, raw_source_weight))
    admitted = []
    for raw_name in enabled_experts:
        name = str(raw_name)
        if name not in NUMERIC_EXPERTS or name in admitted:
            continue
        if len(history) >= _MINIMUM_HISTORY[name]:
            admitted.append(name)
    if not admitted:
        raise ValueError("no predictive expert has enough admitted history")
    experts = sorted(
        (_expert_backtest(name, history, bound) for name in admitted),
        key=lambda item: (float(item["selection_score"]), NUMERIC_EXPERTS.index(str(item["name"]))),
    )
    selected = experts[0]
    runner_up_score = float(experts[1]["selection_score"]) if len(experts) > 1 else 100.0
    gap = max(0.0, runner_up_score - float(selected["selection_score"]))
    evidence_factor = min(1.0, float(selected["backtest_count"]) / 3.0)
    near_predictions = [
        float(item["prediction"])
        for item in experts
        if float(item["selection_score"]) <= float(selected["selection_score"]) + 3.0
    ]
    consensus_factor = 0.0
    if len(near_predictions) >= 2:
        spread_percent = (max(near_predictions) - min(near_predictions)) * 100.0 / bound
        consensus_factor = max(0.0, 1.0 - min(20.0, spread_percent) / 20.0)
    ambiguity_factor = max(min(1.0, gap / 10.0), consensus_factor)
    error_factor = max(
        0.2,
        1.0 - min(80.0, float(selected["mean_absolute_error_percent"])) / 100.0,
    )
    forecast_precision = (
        (40.0 + 35.0 * evidence_factor + 25.0 * ambiguity_factor) * error_factor
    )
    forecast_precision = max(0.0, min(source_weight, forecast_precision))
    return {
        "schema_version": SCHEMA,
        "kind": "numeric",
        "history_length": len(history),
        "history_retention_limit": MAX_HISTORY,
        "feature_limit": round(bound, 6),
        "selected_expert": selected["name"],
        "prediction": selected["prediction"],
        "source_precision": round(source_weight, 3),
        "forecast_precision": round(forecast_precision, 3),
        "selection_margin": round(gap, 6),
        "near_expert_consensus": round(consensus_factor, 6),
        "experts": experts,
        "raw_media_retained": False,
        "action_authority": False,
        "boundary": BOUNDARY,
    }


def forecast_categorical(
    values: Sequence[object],
    *,
    source_precision: object = 100.0,
    periodic_enabled: bool = True,
) -> Dict[str, object]:
    """Forecast a bounded categorical stream using persistence or period two."""
    history = list(values)[-MAX_HISTORY:]
    if len(history) < 2 or any(not isinstance(item, (str, bool)) for item in history):
        raise ValueError("categorical prediction requires at least two string or boolean values")
    if len({bool if isinstance(item, bool) else str for item in history}) != 1:
        raise ValueError("categorical feature history must not mix value types")
    if any(isinstance(item, str) and len(item) > 64 for item in history):
        raise ValueError("categorical feature values must be bounded")
    try:
        raw_source_weight = float(source_precision)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("source precision must be a finite number") from exc
    if not math.isfinite(raw_source_weight):
        raise ValueError("source precision must be a finite number")
    source_weight = max(0.0, min(100.0, raw_source_weight))
    alternating = bool(
        periodic_enabled
        and
        len(history) >= 4
        and history[-1] == history[-3]
        and history[-2] == history[-4]
        and history[-1] != history[-2]
    )
    selected = "period_2" if alternating else "persistence"
    prediction = history[-2] if alternating else history[-1]
    evidence = min(1.0, (len(history) - 1) / 3.0)
    forecast_precision = min(source_weight, 55.0 + 40.0 * evidence)
    return {
        "schema_version": SCHEMA,
        "kind": "categorical",
        "history_length": len(history),
        "history_retention_limit": MAX_HISTORY,
        "selected_expert": selected,
        "prediction": prediction,
        "source_precision": round(source_weight, 3),
        "forecast_precision": round(forecast_precision, 3),
        "experts": [
            {"name": "persistence", "available": True},
            {
                "name": "period_2",
                "available": bool(periodic_enabled and len(history) >= 4),
                "selected": alternating,
            },
        ],
        "raw_media_retained": False,
        "action_authority": False,
        "boundary": BOUNDARY,
    }


def evaluate_observation(
    actual: object,
    forecast: Mapping[str, object],
    *,
    error_threshold: object = DEFAULT_ERROR_THRESHOLD,
) -> Dict[str, object]:
    """Score a later observation against one prior auditable forecast."""
    if forecast.get("schema_version") != SCHEMA:
        raise ValueError("predictive dynamics forecast schema mismatch")
    try:
        threshold = float(error_threshold)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("error threshold must be positive and finite") from exc
    if not math.isfinite(threshold) or threshold <= 0:
        raise ValueError("error threshold must be positive and finite")
    raw_precision = float(forecast.get("forecast_precision") or 0.0)
    if not math.isfinite(raw_precision):
        raise ValueError("forecast precision must be finite")
    precision_weight = max(0.0, min(100.0, raw_precision)) / 100.0
    if forecast.get("kind") == "numeric":
        value = _finite(actual)
        limit = float(forecast.get("feature_limit") or 0.0)
        if value < 0 or value > limit:
            raise ValueError("numeric observation exceeds its admitted range")
        raw_error = abs(value - float(forecast.get("prediction") or 0.0)) * 100.0 / limit
    elif forecast.get("kind") == "categorical":
        if not isinstance(actual, (str, bool)):
            raise ValueError("categorical observation type mismatch")
        raw_error = 0.0 if actual == forecast.get("prediction") else 100.0
    else:
        raise ValueError("unknown predictive dynamics forecast kind")
    weighted_error = raw_error * precision_weight
    return {
        "schema_version": SCHEMA,
        "comparable": True,
        "actual": actual,
        "prediction": forecast.get("prediction"),
        "selected_expert": forecast.get("selected_expert"),
        "raw_error_percent": round(raw_error, 6),
        "precision_weight": round(precision_weight, 6),
        "weighted_error": round(weighted_error, 6),
        "error_threshold": round(threshold, 6),
        "surprising": weighted_error >= threshold,
        "boundary": BOUNDARY,
    }


def forecast_feature_history(
    values: Sequence[object],
    *,
    limit: object = None,
    source_precision: object = 100.0,
) -> Dict[str, object]:
    if values and all(isinstance(item, (str, bool)) for item in values):
        return forecast_categorical(values, source_precision=source_precision)
    if limit is None:
        raise ValueError("numeric feature prediction requires an admitted feature limit")
    return forecast_numeric(values, limit=limit, source_precision=source_precision)
