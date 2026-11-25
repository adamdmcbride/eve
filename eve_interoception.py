"""Evidence-grounded allostatic forecasting for Eve's recurrent control loop.

The module treats Eve's existing homeostatic pressures as functional control
signals.  It forecasts whether measured pressures may leave explicit viability
bands, estimates action effects only from causally identified observations, and
can propose a bounded read-only re-observation when uncertainty could change a
decision.  It does not model, create, or prove subjective feeling.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


SCHEMA_VERSION = "eve.allostatic_interoception.v1"
EFFECT_EVIDENCE_KIND = "lived_homeostatic_consequence"
DEFAULT_HORIZONS = (1, 3, 6)
DEFAULT_SOFT_BOUND = 60
DEFAULT_CRITICAL_BOUND = 80
MAX_EFFECT_OBSERVATIONS = 12
MAX_ACTION_ADJUSTMENT = 12.0
BOUNDARY = (
    "Functional regulation over measured system pressures; not evidence of "
    "subjective feeling, phenomenal experience, or consciousness."
)


def _text(value: object, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def _clamp(value: object, low: float = 0.0, high: float = 100.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = low
    if not math.isfinite(number):
        number = low
    return max(low, min(high, number))


def _pressure_records(value: object) -> List[Dict[str, object]]:
    records = value if isinstance(value, list) else []
    normalized: List[Dict[str, object]] = []
    seen: Set[str] = set()
    for raw in records:
        if not isinstance(raw, Mapping):
            continue
        pressure_id = _text(raw.get("id"), 60).lower().replace(" ", "_")
        if not pressure_id or pressure_id in seen:
            continue
        seen.add(pressure_id)
        trend = _text(raw.get("trend"), 20).lower()
        if trend not in {"rising", "falling", "steady", "new"}:
            trend = "steady"
        normalized.append(
            {
                "id": pressure_id,
                "label": _text(raw.get("label"), 80) or pressure_id.replace("_", " "),
                "level": round(_clamp(raw.get("level")), 3),
                "trend": trend,
                "signal_count": max(0, int(raw.get("signal_count") or 0)),
            }
        )
    return normalized[:12]


def _pressure_map(value: object) -> Dict[str, Dict[str, object]]:
    return {record["id"]: record for record in _pressure_records(value)}


def _viability_band(homeostasis: Mapping[str, object], pressure_id: str) -> Dict[str, int]:
    configured = homeostasis.get("viability_bands")
    raw = configured.get(pressure_id) if isinstance(configured, Mapping) else None
    raw = raw if isinstance(raw, Mapping) else {}
    soft = int(round(_clamp(raw.get("soft", DEFAULT_SOFT_BOUND))))
    critical = int(round(_clamp(raw.get("critical", DEFAULT_CRITICAL_BOUND))))
    if soft >= critical:
        soft, critical = DEFAULT_SOFT_BOUND, DEFAULT_CRITICAL_BOUND
    return {"soft": soft, "critical": critical}


def _prior_interoception(previous_state: Mapping[str, object]) -> Mapping[str, object]:
    interoception = previous_state.get("interoception")
    return interoception if isinstance(interoception, Mapping) else {}


def _damped_displacement(velocity: float, horizon: int) -> float:
    """Project a recent measured delta while damping rather than extrapolating forever."""
    return velocity * sum(0.65**step for step in range(max(0, horizon)))


def _crossing_risk(
    *,
    center: float,
    low: float,
    high: float,
    band: Mapping[str, int],
) -> float:
    soft = float(band["soft"])
    critical = float(band["critical"])
    if high < soft:
        return 0.0
    if low >= critical:
        return 100.0
    # Keep the score monotonic in the projected center.  A clipped interval
    # alone can otherwise make a lower expected pressure look *riskier* merely
    # because a larger fraction of its shortened interval sits above a bound.
    center_component = _clamp(
        (center - soft) / max(1.0, critical - soft),
        0.0,
        1.0,
    ) * 70.0
    upper_component = _clamp(
        (high - critical) / max(1.0, 100.0 - critical),
        0.0,
        1.0,
    ) * 30.0
    return round(_clamp(center_component + upper_component), 3)


def forecast_pressure_trajectories(
    homeostasis: Mapping[str, object],
    previous_state: Mapping[str, object],
    *,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    lesioned: bool = False,
) -> Dict[str, object]:
    """Forecast measured pressure trajectories without inventing action effects.

    A velocity is available only when both the current and prior recurrent
    states contain the same pressure.  A categorical trend can widen the
    interval, but never supplies a fabricated numeric velocity.
    """
    normalized_horizons = sorted(
        {max(1, min(12, int(item))) for item in horizons if int(item) > 0}
    ) or list(DEFAULT_HORIZONS)
    current = _pressure_map(homeostasis.get("pressures"))
    prior = _pressure_map(_prior_interoception(previous_state).get("pressure_records"))
    trajectories: List[Dict[str, object]] = []
    peak_risk = 0.0
    decision_risk = 0.0
    peak_upper = 0.0
    boundary_crossings: List[str] = []

    for pressure_id in sorted(current):
        record = current[pressure_id]
        current_level = float(record["level"])
        prior_record = prior.get(pressure_id)
        prior_level = float(prior_record["level"]) if prior_record else None
        measured_velocity = (
            max(-25.0, min(25.0, current_level - prior_level))
            if prior_level is not None
            else 0.0
        )
        history_available = prior_level is not None
        signal_count = int(record.get("signal_count") or 0)
        scarcity = 3.0 if history_available else 10.0
        signal_penalty = 5.0 if signal_count <= 0 else 2.0 if signal_count == 1 else 0.0
        trend_penalty = 3.0 if record.get("trend") in {"new", "rising", "falling"} else 1.0
        base_uncertainty = min(
            25.0,
            scarcity + signal_penalty + trend_penalty + abs(measured_velocity) * 0.35,
        )
        band = _viability_band(homeostasis, pressure_id)
        points: List[Dict[str, object]] = []
        for horizon in normalized_horizons:
            displacement = 0.0 if lesioned else _damped_displacement(measured_velocity, horizon)
            center = _clamp(current_level + displacement)
            growth = base_uncertainty * math.sqrt(horizon)
            low = _clamp(center - growth)
            high = _clamp(center + growth)
            risk = (
                0.0
                if lesioned
                else _crossing_risk(center=center, low=low, high=high, band=band)
            )
            peak_risk = max(peak_risk, risk)
            peak_upper = max(peak_upper, high)
            if not lesioned and high >= band["soft"]:
                boundary_crossings.append(f"{pressure_id}@{horizon}")
            points.append(
                {
                    "horizon_cycles": horizon,
                    "expected_level": round(center, 3),
                    "interval": [round(low, 3), round(high, 3)],
                    "bound_crossing_risk": risk,
                }
            )
        weights = [1.0 / math.sqrt(float(item["horizon_cycles"])) for item in points]
        trajectory_decision_risk = (
            sum(float(item["bound_crossing_risk"]) * weight for item, weight in zip(points, weights))
            / max(1e-9, sum(weights))
        )
        decision_risk = max(decision_risk, trajectory_decision_risk)
        trajectories.append(
            {
                "id": pressure_id,
                "label": record["label"],
                "current_level": round(current_level, 3),
                "prior_level": round(prior_level, 3) if prior_level is not None else None,
                "measured_velocity": round(measured_velocity, 3),
                "history_available": history_available,
                "trend": record["trend"],
                "signal_count": signal_count,
                "viability_band": band,
                "points": points,
                "decision_bound_crossing_risk": round(trajectory_decision_risk, 3),
            }
        )
    return {
        "available": bool(current) and not lesioned,
        "history_available": any(item["history_available"] for item in trajectories),
        "horizons": normalized_horizons,
        "trajectories": trajectories,
        "peak_bound_crossing_risk": round(peak_risk, 3),
        "decision_bound_crossing_risk": round(decision_risk, 3),
        "peak_upper_level": round(peak_upper, 3),
        "boundary_crossings": sorted(set(boundary_crossings)),
        "lesioned": bool(lesioned),
    }


def _measured_effect_observations(
    action_model: object,
    *,
    action_id: str,
) -> List[Dict[str, object]]:
    model = action_model if isinstance(action_model, Mapping) else {}
    raw_observations = model.get("observations")
    observations = raw_observations if isinstance(raw_observations, list) else []
    accepted: List[Dict[str, object]] = []
    evidence_ids: Set[str] = set()
    for raw in observations[-MAX_EFFECT_OBSERVATIONS:]:
        if not isinstance(raw, Mapping):
            continue
        evidence_id = _text(raw.get("evidence_id"), 160)
        observed_action_id = _text(raw.get("action_id"), 80)
        source_cycle_id = _text(raw.get("source_cycle_id"), 100)
        execution_id = _text(raw.get("execution_id"), 100)
        before = raw.get("homeostasis_before")
        after = raw.get("homeostasis_after")
        try:
            elapsed_cycles = int(raw.get("elapsed_cycles"))
            execution_cost = float(raw.get("execution_cost"))
        except (TypeError, ValueError):
            continue
        if (
            raw.get("evidence_kind") != EFFECT_EVIDENCE_KIND
            or raw.get("verification_ok") is not True
            or raw.get("ok") is not True
            or not evidence_id
            or evidence_id in evidence_ids
            or observed_action_id != action_id
            or not source_cycle_id
            or not execution_id
            or not 1 <= elapsed_cycles <= 12
            or not math.isfinite(execution_cost)
            or not 0.0 <= execution_cost <= 100.0
            or not isinstance(before, Mapping)
            or not isinstance(after, Mapping)
        ):
            continue
        shared = sorted(set(str(key) for key in before) & set(str(key) for key in after))
        effects: Dict[str, float] = {}
        for pressure_id in shared:
            try:
                before_level = float(before.get(pressure_id))
                after_level = float(after.get(pressure_id))
            except (TypeError, ValueError):
                continue
            if (
                not math.isfinite(before_level)
                or not math.isfinite(after_level)
                or not 0.0 <= before_level <= 100.0
                or not 0.0 <= after_level <= 100.0
            ):
                continue
            effects[_text(pressure_id, 60).lower().replace(" ", "_")] = round(
                after_level - before_level,
                3,
            )
        if not effects:
            continue
        evidence_ids.add(evidence_id)
        accepted.append(
            {
                "evidence_id": evidence_id,
                "source_cycle_id": source_cycle_id,
                "execution_id": execution_id,
                "elapsed_cycles": elapsed_cycles,
                "execution_cost": execution_cost,
                "effects": effects,
            }
        )
    return accepted


def observed_action_effects(
    affordances: Sequence[Mapping[str, object]],
    action_models: Mapping[str, object],
) -> Dict[str, Dict[str, object]]:
    """Estimate pressure effects only from verified before/after observations."""
    result: Dict[str, Dict[str, object]] = {}
    for affordance in affordances:
        action_id = _text(affordance.get("id"), 80)
        if not action_id or action_id in result:
            continue
        observations = _measured_effect_observations(
            action_models.get(action_id),
            action_id=action_id,
        )
        if not observations:
            continue
        per_pressure: Dict[str, List[float]] = {}
        for observation in observations:
            for pressure_id, delta in observation["effects"].items():
                per_pressure.setdefault(pressure_id, []).append(float(delta))
        effects: Dict[str, Dict[str, object]] = {}
        for pressure_id, deltas in sorted(per_pressure.items()):
            mean = sum(deltas) / len(deltas)
            spread = (
                math.sqrt(sum((value - mean) ** 2 for value in deltas) / (len(deltas) - 1))
                if len(deltas) > 1
                else max(5.0, abs(mean) * 0.5)
            )
            margin = max(2.0, spread / math.sqrt(len(deltas)))
            effects[pressure_id] = {
                "mean_delta": round(mean, 3),
                "interval": [round(mean - margin, 3), round(mean + margin, 3)],
                "sample_count": len(deltas),
            }
        result[action_id] = {
            "effects": effects,
            "sample_count": len(observations),
            "evidence_ids": sorted(item["evidence_id"] for item in observations),
            "mean_recovery_latency_cycles": round(
                sum(float(item["elapsed_cycles"]) for item in observations)
                / len(observations),
                3,
            ),
            "mean_execution_cost": round(
                sum(float(item["execution_cost"]) for item in observations)
                / len(observations),
                3,
            ),
            "grounded": True,
        }
    return result


def _candidate_peak(
    baseline: Mapping[str, object],
    effect: Mapping[str, object],
) -> Tuple[float, float, float, List[Dict[str, object]]]:
    trajectories = copy.deepcopy(baseline.get("trajectories") or [])
    peak_risk = 0.0
    decision_risk = 0.0
    peak_upper = 0.0
    effect_map = effect.get("effects") if isinstance(effect.get("effects"), Mapping) else {}
    latency = max(1.0, float(effect.get("mean_recovery_latency_cycles") or 1.0))
    for trajectory in trajectories:
        if not isinstance(trajectory, dict):
            continue
        pressure_id = str(trajectory.get("id") or "")
        pressure_effect = effect_map.get(pressure_id)
        mean_delta = (
            float(pressure_effect.get("mean_delta") or 0.0)
            if isinstance(pressure_effect, Mapping)
            else 0.0
        )
        effect_interval = (
            pressure_effect.get("interval")
            if isinstance(pressure_effect, Mapping)
            and isinstance(pressure_effect.get("interval"), list)
            else [mean_delta, mean_delta]
        )
        effect_margin = (
            max(abs(float(effect_interval[0]) - mean_delta), abs(float(effect_interval[1]) - mean_delta))
            if len(effect_interval) == 2
            else 0.0
        )
        band = trajectory.get("viability_band") or {
            "soft": DEFAULT_SOFT_BOUND,
            "critical": DEFAULT_CRITICAL_BOUND,
        }
        for point in trajectory.get("points") or []:
            if not isinstance(point, dict):
                continue
            horizon = max(1, int(point.get("horizon_cycles") or 1))
            realization = (
                min(1.0, horizon / latency)
                if horizon <= latency
                else 0.75 ** (horizon - latency)
            )
            adjusted_center = _clamp(
                float(point.get("expected_level") or 0.0)
                + mean_delta * realization
            )
            interval = point.get("interval") if isinstance(point.get("interval"), list) else [adjusted_center, adjusted_center]
            half_width = (
                abs(float(interval[1]) - float(interval[0])) / 2.0
                if len(interval) == 2
                else 0.0
            ) + effect_margin * realization
            low = _clamp(adjusted_center - half_width)
            high = _clamp(adjusted_center + half_width)
            risk = _crossing_risk(
                center=adjusted_center,
                low=low,
                high=high,
                band=band,
            )
            point["expected_level"] = round(adjusted_center, 3)
            point["interval"] = [round(low, 3), round(high, 3)]
            point["bound_crossing_risk"] = risk
            peak_risk = max(peak_risk, risk)
            peak_upper = max(peak_upper, high)
        points = [item for item in trajectory.get("points") or [] if isinstance(item, Mapping)]
        weights = [1.0 / math.sqrt(float(item.get("horizon_cycles") or 1)) for item in points]
        trajectory_decision_risk = (
            sum(float(item.get("bound_crossing_risk") or 0.0) * weight for item, weight in zip(points, weights))
            / max(1e-9, sum(weights))
        )
        trajectory["decision_bound_crossing_risk"] = round(trajectory_decision_risk, 3)
        decision_risk = max(decision_risk, trajectory_decision_risk)
    return (
        round(peak_risk, 3),
        round(decision_risk, 3),
        round(peak_upper, 3),
        trajectories,
    )


def forecast_action_candidates(
    baseline: Mapping[str, object],
    affordances: Sequence[Mapping[str, object]],
    action_models: Mapping[str, object],
    *,
    lesioned: bool = False,
) -> List[Dict[str, object]]:
    effects = {} if lesioned else observed_action_effects(affordances, action_models)
    baseline_risk = float(baseline.get("decision_bound_crossing_risk") or 0.0)
    baseline_peak = float(baseline.get("peak_upper_level") or 0.0)
    candidates: List[Dict[str, object]] = []
    for affordance in affordances:
        action_id = _text(affordance.get("id"), 80)
        effect = effects.get(action_id)
        if not effect:
            candidates.append(
                {
                    "action_id": action_id,
                    "grounded_effect": False,
                    "sample_count": 0,
                    "risk_reduction": 0.0,
                    "peak_level_reduction": 0.0,
                    "allostatic_adjustment": 0.0,
                }
            )
            continue
        peak_risk, decision_risk, peak_upper, trajectories = _candidate_peak(baseline, effect)
        risk_reduction = baseline_risk - decision_risk
        peak_reduction = baseline_peak - peak_upper
        measured_deltas = [
            (
                float(item.get("mean_delta") or 0.0),
                max(
                    0.1,
                    float(
                        next(
                            (
                                trajectory.get("current_level")
                                for trajectory in baseline.get("trajectories") or []
                                if isinstance(trajectory, Mapping)
                                and trajectory.get("id") == pressure_id
                            ),
                            0.0,
                        )
                    )
                    / 100.0,
                ),
            )
            for pressure_id, item in (effect.get("effects") or {}).items()
            if isinstance(item, Mapping)
        ]
        mean_pressure_delta = (
            sum(delta * weight for delta, weight in measured_deltas)
            / sum(weight for _, weight in measured_deltas)
            if measured_deltas
            else 0.0
        )
        mean_execution_cost = float(effect.get("mean_execution_cost") or 0.0)
        adjustment = max(
            -MAX_ACTION_ADJUSTMENT,
            min(
                MAX_ACTION_ADJUSTMENT,
                risk_reduction * 0.10
                + peak_reduction * 0.08
                - mean_pressure_delta * 0.08
                - mean_execution_cost * 0.03,
            ),
        )
        candidates.append(
            {
                "action_id": action_id,
                "grounded_effect": True,
                "sample_count": int(effect.get("sample_count") or 0),
                "evidence_ids": list(effect.get("evidence_ids") or []),
                "effects": copy.deepcopy(effect.get("effects") or {}),
                "peak_bound_crossing_risk": peak_risk,
                "decision_bound_crossing_risk": decision_risk,
                "peak_upper_level": peak_upper,
                "risk_reduction": round(risk_reduction, 3),
                "peak_level_reduction": round(peak_reduction, 3),
                "mean_observed_pressure_delta": round(mean_pressure_delta, 3),
                "mean_recovery_latency_cycles": effect.get("mean_recovery_latency_cycles"),
                "mean_execution_cost": round(mean_execution_cost, 3),
                "allostatic_adjustment": round(adjustment, 3),
                "trajectories": trajectories,
            }
        )
    return candidates


def _sampling_proposal(
    baseline: Mapping[str, object],
    *,
    enabled: bool,
) -> Dict[str, object]:
    if not enabled or not baseline.get("available"):
        return {}
    ambiguous: List[Tuple[float, Mapping[str, object], Mapping[str, object]]] = []
    for trajectory in baseline.get("trajectories") or []:
        if not isinstance(trajectory, Mapping):
            continue
        # One prior point is enough to estimate a velocity but not enough to
        # establish that it is stable.  Multiple current source signals plus a
        # prior measurement can suppress this proposal; otherwise a bound-
        # relevant interval remains worth re-observing.
        if trajectory.get("history_available") and int(trajectory.get("signal_count") or 0) >= 2:
            continue
        band = trajectory.get("viability_band") if isinstance(trajectory.get("viability_band"), Mapping) else {}
        soft = float(band.get("soft") or DEFAULT_SOFT_BOUND)
        for point in trajectory.get("points") or []:
            interval = point.get("interval") if isinstance(point, Mapping) else None
            if not isinstance(interval, list) or len(interval) != 2:
                continue
            low, high = float(interval[0]), float(interval[1])
            if low < soft <= high:
                ambiguous.append((high - low, trajectory, point))
    if not ambiguous:
        return {}
    _, trajectory, point = max(ambiguous, key=lambda item: item[0])
    pressure_id = _text(trajectory.get("id"), 60)
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "pressure_id": pressure_id,
                "current_level": trajectory.get("current_level"),
                "interval": point.get("interval"),
                "horizon": point.get("horizon_cycles"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:24]
    return {
        "id": f"interoceptive-sample-{fingerprint}",
        "authority": "proposal_only",
        "action": "refresh_homeostasis_evidence",
        "target_pressure_id": pressure_id,
        "target_fingerprint": fingerprint,
        "question": f"Is {pressure_id} stabilizing or approaching its viability bound?",
        "expected_observation": (
            "A fresh independently timestamped pressure measurement that can "
            "distinguish stabilizing from rising trajectory hypotheses."
        ),
        "requested_modalities": ["interoceptive", "system"],
        "requires_permission": False,
        "selection_basis": "forecast interval spans the soft viability bound and lacks recurrent history",
        "decision_relevance": "the observation can change regulation mode or autonomous action ranking",
    }


def build_allostatic_state(
    *,
    homeostasis: Mapping[str, object],
    previous_state: Mapping[str, object],
    affordances: Sequence[Mapping[str, object]],
    action_models: Mapping[str, object],
    lesions: Optional[Iterable[str]] = None,
) -> Dict[str, object]:
    lesion_set = {str(item) for item in lesions or []}
    allostasis_lesioned = "allostasis" in lesion_set or "homeostasis" in lesion_set
    baseline = forecast_pressure_trajectories(
        homeostasis,
        previous_state,
        lesioned=allostasis_lesioned,
    )
    candidates = forecast_action_candidates(
        baseline,
        affordances,
        action_models,
        lesioned=allostasis_lesioned,
    )
    proposal = _sampling_proposal(
        baseline,
        enabled=(
            not allostasis_lesioned
            and "interoceptive_enaction" not in lesion_set
        ),
    )
    grounded = [item for item in candidates if item.get("grounded_effect")]
    return {
        "schema_version": SCHEMA_VERSION,
        "available": bool(baseline.get("available")),
        "baseline_forecast": baseline,
        "candidate_forecasts": candidates,
        "grounded_candidate_count": len(grounded),
        "sampling_proposal": proposal,
        "allostasis_lesioned": allostasis_lesioned,
        "interoceptive_enaction_lesioned": "interoceptive_enaction" in lesion_set,
        "boundary": BOUNDARY,
    }


def apply_allostatic_adjustments(
    affordances: Sequence[Mapping[str, object]],
    allostatic_state: Mapping[str, object],
    *,
    inbound: bool,
) -> List[Dict[str, object]]:
    """Apply bounded observed-effect adjustments without overriding a human turn."""
    forecasts = {
        str(item.get("action_id") or ""): item
        for item in allostatic_state.get("candidate_forecasts") or []
        if isinstance(item, Mapping) and item.get("action_id")
    }
    adjusted: List[Dict[str, object]] = []
    for raw in affordances:
        item = copy.deepcopy(dict(raw))
        forecast = forecasts.get(str(item.get("id") or ""), {})
        proposed = float(forecast.get("allostatic_adjustment") or 0.0)
        applied = 0.0 if inbound else proposed
        item["pre_allostatic_value"] = float(item.get("value") or 0.0)
        item["allostatic_adjustment"] = round(applied, 3)
        item["allostatic_effect_grounded"] = bool(forecast.get("grounded_effect"))
        item["allostatic_human_interrupt"] = bool(
            inbound and forecast.get("grounded_effect")
        )
        item["value"] = round(float(item.get("value") or 0.0) + applied, 3)
        adjusted.append(item)
    return sorted(
        adjusted,
        key=lambda item: (float(item.get("value") or 0.0), str(item.get("id") or "")),
        reverse=True,
    )
