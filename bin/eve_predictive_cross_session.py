#!/usr/bin/env python3
"""Preregister, collect, and score separated PP-1 host sessions.

This protocol extends Eve's short-horizon lived predictive canary without
promoting repeated measurements into a consciousness claim.  Each invocation
collects a complete within-session protocol, compares Eve's stored prospective
predictions with an independently calculated adaptive exponential-smoothing
baseline, and seals the privacy-minimized source reports into a digest-bound
session bundle.  Cross-session scoring is allowed only against the original
registration.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_lived_feature_stream as lived  # noqa: E402


LONGITUDINAL_PATH = ROOT / "bin" / "eve_lived_predictive_longitudinal.py"
REGISTRATION_SCHEMA = "eve.pp1_cross_session_registration.v1"
SESSION_SCHEMA = "eve.pp1_cross_session_bundle.v1"
REPORT_SCHEMA = "eve.pp1_cross_session_report.v1"
CONTEXT_FEATURE_ID = "system.aggregate_cpu_per_core_percent"
BASELINE_ID = "adaptive_exponential_smoothing.v1"
BASELINE_ALPHAS = (0.2, 0.5, 0.8)
BOUNDARY = (
    "Separated read-only aggregate PP-1 replication evidence on one host; not "
    "subjective experience, external replication, or proof of consciousness."
)
FORBIDDEN_PAYLOAD_KEYS = {
    "audio",
    "audio_bytes",
    "content",
    "frame",
    "image",
    "image_bytes",
    "path",
    "pixels",
    "process_name",
    "process_names",
    "prompt",
    "query",
    "raw",
    "raw_audio",
    "raw_frame",
    "raw_image",
    "raw_screen",
    "response",
    "screen",
    "text",
    "user_content",
    "video",
}
FALSE_BOUNDARY_KEYS = {
    "action_authority",
    "process_identity_retained",
    "raw_media_retained",
    "user_content_retained",
}


def _load_longitudinal():
    spec = importlib.util.spec_from_file_location(
        "eve_lived_predictive_longitudinal", LONGITUDINAL_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("lived predictive longitudinal evaluator is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _timestamp(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("an ISO-8601 timestamp is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _parsed(value: object) -> datetime:
    return datetime.fromisoformat(_timestamp(value))


def _finite(value: object, *, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _valid_digest(value: object) -> bool:
    text = str(value or "").lower()
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _implementation_digests() -> Dict[str, str]:
    """Freeze both the scorer and the mechanism used to make new forecasts."""
    paths = {
        "cross_session_scorer": Path(__file__).resolve(),
        "longitudinal_validator": LONGITUDINAL_PATH,
        "lived_transfer_runner": ROOT / "bin" / "eve_lived_predictive_transfer.py",
        "predictive_dynamics": ROOT / "eve_predictive_dynamics.py",
        "lived_feature_stream": ROOT / "eve_lived_feature_stream.py",
    }
    return {name: _file_digest(path) for name, path in sorted(paths.items())}


def _assert_feature_only_payload(payload: object) -> None:
    if isinstance(payload, Mapping):
        for raw_key, value in payload.items():
            key = str(raw_key).strip().lower()
            if key in FALSE_BOUNDARY_KEYS and value is not False:
                raise ValueError(f"source evidence violates {key} boundary")
            if key in FORBIDDEN_PAYLOAD_KEYS and not (
                value is None or value == "" or value is False
            ):
                raise ValueError("source evidence contains forbidden raw or user payload")
            _assert_feature_only_payload(value)
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            _assert_feature_only_payload(value)
    elif isinstance(payload, (bytes, bytearray, memoryview)):
        raise ValueError("binary payloads cannot enter cross-session evidence")


def _registration_material(payload: Mapping[str, object]) -> Dict[str, object]:
    contract = lived.validate_contract(
        payload.get("source_contract")
        if isinstance(payload.get("source_contract"), Mapping)
        else {}
    )
    try:
        windows_per_session = int(payload.get("windows_per_session") or 0)
        minimum_sessions = int(payload.get("minimum_valid_sessions") or 0)
        minimum_days = int(payload.get("minimum_distinct_utc_days") or 0)
        gap = float(payload.get("window_gap_seconds") or 0.0)
        session_gap = float(payload.get("minimum_session_gap_seconds") or 0.0)
    except (TypeError, ValueError) as exc:
        raise ValueError("cross-session count or separation contract is invalid") from exc
    if windows_per_session < 6 or minimum_sessions < 6:
        raise ValueError("at least six windows per session and six sessions are required")
    if minimum_days < 3 or minimum_days > minimum_sessions:
        raise ValueError("at least three distinct UTC days are required")
    if gap < 0 or session_gap < 3600:
        raise ValueError("sessions must be separated by at least one hour")

    lower_max = _finite(
        payload.get("lower_activity_max_percent"), name="lower activity threshold"
    )
    higher_min = _finite(
        payload.get("higher_activity_min_percent"), name="higher activity threshold"
    )
    effect = _finite(
        payload.get("minimum_median_effect_vs_adaptive_ema_pp"),
        name="minimum adaptive-baseline effect",
    )
    positive_fraction = _finite(
        payload.get("minimum_positive_session_fraction"),
        name="minimum positive session fraction",
    )
    temporal = _finite(
        payload.get("minimum_median_temporal_specificity_pp"),
        name="minimum temporal specificity",
    )
    within_fraction = _finite(
        payload.get("minimum_short_horizon_support_fraction"),
        name="minimum within-session support fraction",
    )
    if not 0 <= lower_max < higher_min <= 100:
        raise ValueError("activity thresholds must define separated lower and higher strata")
    if effect <= 0 or temporal <= 0:
        raise ValueError("effect thresholds must be positive")
    if not 0.5 < positive_fraction <= 1 or not 0.5 < within_fraction <= 1:
        raise ValueError("fraction thresholds must be in (0.5, 1]")

    protocol_id = str(payload.get("protocol_id") or "").strip()[:120]
    subject = str(payload.get("subject_system_id") or "").strip()[:120]
    author = str(payload.get("protocol_author_id") or "").strip()[:120]
    scorer = str(payload.get("scorer_id") or "").strip()[:120]
    if not protocol_id or not subject or not author or not scorer:
        raise ValueError("protocol, subject, author, and scorer ids are required")
    if subject.lower() in {author.lower(), scorer.lower()}:
        raise ValueError("protocol author and scorer must be distinct from Eve")

    lower_registration = (
        payload.get("within_session_registration")
        if isinstance(payload.get("within_session_registration"), Mapping)
        else {}
    )
    longitudinal = _load_longitudinal()
    lower_material = longitudinal.validate_registration(lower_registration)
    registered_at = _timestamp(payload.get("registered_at"))
    if lower_material["contract_digest"] != contract["contract_digest"]:
        raise ValueError("within-session registration and source contract differ")
    if _timestamp(lower_material["registered_at"]) != registered_at:
        raise ValueError("within- and cross-session registrations must be simultaneous")
    if int(lower_material["planned_window_count"]) != windows_per_session:
        raise ValueError("within-session window count differs from cross-session contract")
    implementation_digests = (
        dict(payload.get("implementation_digests"))
        if isinstance(payload.get("implementation_digests"), Mapping)
        else {}
    )
    if not implementation_digests or any(
        not _valid_digest(value) for value in implementation_digests.values()
    ):
        raise ValueError("all scorer and mechanism implementations must be digest-bound")
    if implementation_digests != _implementation_digests():
        raise ValueError("registered scorer or mechanism implementation has changed")

    return {
        "schema_version": REGISTRATION_SCHEMA,
        "protocol_id": protocol_id,
        "registered_at": registered_at,
        "subject_system_id": subject,
        "protocol_author_id": author,
        "scorer_id": scorer,
        "source_contract": contract,
        "source_contract_digest": contract["contract_digest"],
        "within_session_registration": dict(lower_registration),
        "implementation_digests": implementation_digests,
        "windows_per_session": windows_per_session,
        "minimum_valid_sessions": minimum_sessions,
        "window_gap_seconds": gap,
        "minimum_session_gap_seconds": session_gap,
        "minimum_distinct_utc_days": minimum_days,
        "context_feature_id": CONTEXT_FEATURE_ID,
        "lower_activity_max_percent": lower_max,
        "higher_activity_min_percent": higher_min,
        "required_context_strata": ["lower_activity", "higher_activity"],
        "baseline_id": BASELINE_ID,
        "baseline_alphas": list(BASELINE_ALPHAS),
        "minimum_median_effect_vs_adaptive_ema_pp": effect,
        "minimum_positive_session_fraction": positive_fraction,
        "minimum_median_temporal_specificity_pp": temporal,
        "minimum_short_horizon_support_fraction": within_fraction,
        "indicator_id": "PP-1",
        "evidence_class": "lived_cross_session",
    }


def preregister(payload: Mapping[str, object]) -> Dict[str, object]:
    material = _registration_material(payload)
    return {
        **material,
        "status": "preregistered",
        "registration_digest": _digest(material),
        "independent_replication_authorized": False,
        "consciousness_verdict_authorized": False,
        "boundary": BOUNDARY,
    }


def create_registration(
    contract: Mapping[str, object],
    *,
    protocol_id: str,
    registered_at: object,
    protocol_author_id: str,
    scorer_id: str,
    windows_per_session: int = 6,
    minimum_valid_sessions: int = 6,
    window_gap_seconds: float = 3.0,
    minimum_session_gap_seconds: float = 6 * 3600,
    minimum_distinct_utc_days: int = 3,
    lower_activity_max_percent: float = 20.0,
    higher_activity_min_percent: float = 35.0,
    minimum_median_effect_vs_adaptive_ema_pp: float = 0.25,
    minimum_positive_session_fraction: float = 2 / 3,
    minimum_median_temporal_specificity_pp: float = 0.1,
    minimum_short_horizon_support_fraction: float = 2 / 3,
) -> Dict[str, object]:
    validated_contract = lived.validate_contract(contract)
    timestamp = _timestamp(registered_at)
    longitudinal = _load_longitudinal()
    lower = longitudinal.preregister(
        {
            "protocol_id": f"{protocol_id}-within-session",
            "registered_at": timestamp,
            "subject_system_id": "Eve",
            "evaluator_id": scorer_id,
            "contract_digest": validated_contract["contract_digest"],
            "planned_window_count": windows_per_session,
            "minimum_valid_windows": windows_per_session,
            "window_gap_seconds": window_gap_seconds,
            "minimum_median_effect_pp": 0.25,
            "minimum_positive_window_fraction": 1.0,
            "maximum_sign_test_p": 0.05,
            "minimum_temporal_specificity_pp": 0.1,
        }
    )
    return preregister(
        {
            "protocol_id": protocol_id,
            "registered_at": timestamp,
            "subject_system_id": "Eve",
            "protocol_author_id": protocol_author_id,
            "scorer_id": scorer_id,
            "source_contract": validated_contract,
            "within_session_registration": lower,
            "implementation_digests": _implementation_digests(),
            "windows_per_session": windows_per_session,
            "minimum_valid_sessions": minimum_valid_sessions,
            "window_gap_seconds": window_gap_seconds,
            "minimum_session_gap_seconds": minimum_session_gap_seconds,
            "minimum_distinct_utc_days": minimum_distinct_utc_days,
            "lower_activity_max_percent": lower_activity_max_percent,
            "higher_activity_min_percent": higher_activity_min_percent,
            "minimum_median_effect_vs_adaptive_ema_pp": (
                minimum_median_effect_vs_adaptive_ema_pp
            ),
            "minimum_positive_session_fraction": minimum_positive_session_fraction,
            "minimum_median_temporal_specificity_pp": (
                minimum_median_temporal_specificity_pp
            ),
            "minimum_short_horizon_support_fraction": (
                minimum_short_horizon_support_fraction
            ),
        }
    )


def validate_registration(payload: Mapping[str, object]) -> Dict[str, object]:
    if payload.get("schema_version") != REGISTRATION_SCHEMA:
        raise ValueError("cross-session registration schema mismatch")
    material = _registration_material(payload)
    if str(payload.get("registration_digest") or "") != _digest(material):
        raise ValueError("registration digest mismatch; protocol may have changed")
    return material


def adaptive_ema_forecast(history: Sequence[float]) -> Tuple[float, float]:
    """Select alpha only from prospective errors within the available history."""
    values = [_finite(value, name="baseline history") for value in history]
    if not values:
        raise ValueError("adaptive EMA requires history")
    if len(values) == 1:
        return values[-1], BASELINE_ALPHAS[0]
    candidates: List[Tuple[float, float, float]] = []
    for alpha in BASELINE_ALPHAS:
        level = values[0]
        errors: List[float] = []
        for actual in values[1:]:
            errors.append(abs(level - actual))
            level = alpha * actual + (1.0 - alpha) * level
        candidates.append((statistics.fmean(errors), alpha, level))
    _, alpha, forecast = min(candidates, key=lambda item: (item[0], item[1]))
    return forecast, alpha


def _source_reports_metrics(
    reports: Sequence[Mapping[str, object]],
    registration: Mapping[str, object],
) -> Dict[str, object]:
    source_digests: List[str] = []
    integrated_accuracy: List[float] = []
    baseline_accuracy: List[float] = []
    context_values: List[float] = []
    longitudinal = _load_longitudinal()
    lower = registration["within_session_registration"]
    for report in reports:
        _assert_feature_only_payload(report)
        # This validates schema, privacy, ordering, paired arms, timestamps,
        # contract digest, and every lower-level check before extra scoring.
        longitudinal._report_window(report, lower)
        source_digests.append(_digest(report))
        samples = report.get("samples") if isinstance(report.get("samples"), list) else []
        arms = report.get("arms") if isinstance(report.get("arms"), Mapping) else {}
        intact = arms.get("intact") if isinstance(arms.get("intact"), list) else []
        feature_series: Dict[str, List[float]] = {}
        feature_limits: Dict[str, float] = {}
        for sample in samples:
            features = (
                sample.get("features")
                if isinstance(sample, Mapping)
                and isinstance(sample.get("features"), Mapping)
                else {}
            )
            for feature_id, record in features.items():
                if not isinstance(record, Mapping):
                    continue
                value = _finite(record.get("value"), name="sample feature")
                limit = _finite(record.get("limit"), name="sample feature limit")
                if limit <= 0:
                    raise ValueError("feature limits must be positive")
                feature_series.setdefault(str(feature_id), []).append(value)
                feature_limits[str(feature_id)] = limit
                if str(feature_id) == CONTEXT_FEATURE_ID:
                    context_values.append(value)
        for arm_name in ("intact", "lesion"):
            records = arms.get(arm_name) if isinstance(arms.get(arm_name), list) else []
            for record in records:
                if not isinstance(record, Mapping):
                    raise ValueError(f"{arm_name} forecast is malformed")
                feature_id = str(record.get("feature_id") or "")
                sample_index = int(record.get("sample_index") or 0)
                series = feature_series.get(feature_id) or []
                if sample_index <= 0 or sample_index >= len(series):
                    raise ValueError(
                        f"{arm_name} forecast cannot be aligned to source samples"
                    )
                actual = _finite(record.get("actual"), name=f"{arm_name} actual")
                if not math.isclose(actual, series[sample_index], abs_tol=1e-6):
                    raise ValueError(f"{arm_name} actual differs from source sample")
                prediction = _finite(
                    record.get("prediction"), name=f"{arm_name} prediction"
                )
                limit = feature_limits[feature_id]
                recomputed = max(
                    0.0, 100.0 - abs(prediction - actual) * 100.0 / limit
                )
                reported = _finite(
                    record.get("accuracy_percent"),
                    name=f"{arm_name} reported accuracy",
                )
                if not math.isclose(recomputed, reported, abs_tol=1e-5):
                    raise ValueError(
                        f"{arm_name} reported accuracy does not match its prediction"
                    )

        for record in intact:
            feature_id = str(record.get("feature_id") or "")
            sample_index = int(record.get("sample_index") or 0)
            series = feature_series[feature_id]
            actual = _finite(record.get("actual"), name="intact actual")
            prediction = _finite(record.get("prediction"), name="intact prediction")
            limit = feature_limits[feature_id]
            integrated = max(
                0.0, 100.0 - abs(prediction - actual) * 100.0 / limit
            )
            baseline_prediction, _ = adaptive_ema_forecast(series[:sample_index])
            baseline = max(
                0.0,
                100.0 - abs(baseline_prediction - actual) * 100.0 / limit,
            )
            integrated_accuracy.append(integrated)
            baseline_accuracy.append(baseline)
    if not integrated_accuracy or len(integrated_accuracy) != len(baseline_accuracy):
        raise ValueError("session has no adaptive-baseline comparisons")
    if not context_values:
        raise ValueError("session lacks the preregistered context feature")
    context_median = statistics.median(context_values)
    if context_median <= float(registration["lower_activity_max_percent"]):
        context_label = "lower_activity"
    elif context_median >= float(registration["higher_activity_min_percent"]):
        context_label = "higher_activity"
    else:
        context_label = "transition_activity"
    return {
        "source_report_digests": source_digests,
        "paired_adaptive_baseline_comparisons": len(integrated_accuracy),
        "integrated_mean_accuracy_percent": statistics.fmean(integrated_accuracy),
        "adaptive_ema_mean_accuracy_percent": statistics.fmean(baseline_accuracy),
        "effect_vs_adaptive_ema_pp": (
            statistics.fmean(integrated_accuracy) - statistics.fmean(baseline_accuracy)
        ),
        "context_feature_median": context_median,
        "context_label": context_label,
    }


def build_session_bundle(
    registration: Mapping[str, object],
    reports: Sequence[Mapping[str, object]],
    *,
    created_at: object,
    collected_by: str,
    host_boot_fingerprint_sha256: str = "",
) -> Dict[str, object]:
    registered = validate_registration(registration)
    collector = str(collected_by or "").strip()[:120]
    if not collector or collector.lower() == str(registered["subject_system_id"]).lower():
        raise ValueError("session collection requires an operator distinct from Eve")
    if len(reports) != int(registered["windows_per_session"]):
        raise ValueError("session window count differs from preregistration")
    created = _timestamp(created_at)
    longitudinal = _load_longitudinal()
    within = longitudinal.score_reports(
        registered["within_session_registration"],
        reports,
        scored_at=created,
        scored_by=collector,
    )
    windows = within.get("windows") if isinstance(within.get("windows"), list) else []
    if not windows:
        raise ValueError("within-session evaluator returned no windows")
    started_at = min(str(item["started_at"]) for item in windows)
    ended_at = max(str(item["ended_at"]) for item in windows)
    if _parsed(created) < _parsed(ended_at):
        raise ValueError("session bundle cannot be created before collection ended")
    extra = _source_reports_metrics(reports, registered)
    boot = str(host_boot_fingerprint_sha256 or "").lower()
    if boot and not _valid_digest(boot):
        raise ValueError("host boot fingerprint must be empty or SHA-256")
    session_id = "pp1-session-" + _digest(
        {
            "registration_digest": registration["registration_digest"],
            "started_at": started_at,
            "ended_at": ended_at,
            "source_report_digests": extra["source_report_digests"],
        }
    )[:20]
    material = {
        "schema_version": SESSION_SCHEMA,
        "protocol_id": registered["protocol_id"],
        "registration_digest": registration["registration_digest"],
        "session_id": session_id,
        "created_at": created,
        "collected_by": collector,
        "started_at": started_at,
        "ended_at": ended_at,
        "host_boot_fingerprint_sha256": boot,
        "source_reports": [dict(report) for report in reports],
        "source_report_digests": extra["source_report_digests"],
        "within_session_status": within["status"],
        "within_session_median_effect_pp": within["median_window_effect_pp"],
        "within_session_temporal_specificity_pp": within[
            "median_temporal_specificity_pp"
        ],
        "paired_adaptive_baseline_comparisons": extra[
            "paired_adaptive_baseline_comparisons"
        ],
        "integrated_mean_accuracy_percent": round(
            float(extra["integrated_mean_accuracy_percent"]), 6
        ),
        "adaptive_ema_mean_accuracy_percent": round(
            float(extra["adaptive_ema_mean_accuracy_percent"]), 6
        ),
        "effect_vs_adaptive_ema_pp": round(
            float(extra["effect_vs_adaptive_ema_pp"]), 6
        ),
        "context_feature_id": CONTEXT_FEATURE_ID,
        "context_feature_median": round(float(extra["context_feature_median"]), 6),
        "context_label": extra["context_label"],
        "baseline_id": BASELINE_ID,
        "runtime_mutated": False,
        "action_authority": False,
        "consciousness_proven": False,
        "subjective_experience_inferred": False,
        "boundary": BOUNDARY,
    }
    return {**material, "session_digest": _digest(material)}


def validate_session_bundle(
    payload: Mapping[str, object], registration: Mapping[str, object]
) -> Dict[str, object]:
    if payload.get("schema_version") != SESSION_SCHEMA:
        raise ValueError("cross-session bundle schema mismatch")
    reports = payload.get("source_reports") if isinstance(payload.get("source_reports"), list) else []
    rebuilt = build_session_bundle(
        registration,
        reports,
        created_at=payload.get("created_at"),
        collected_by=str(payload.get("collected_by") or ""),
        host_boot_fingerprint_sha256=str(
            payload.get("host_boot_fingerprint_sha256") or ""
        ),
    )
    if _digest({key: value for key, value in payload.items() if key != "session_digest"}) != str(
        payload.get("session_digest") or ""
    ):
        raise ValueError("session digest mismatch; evidence may have changed")
    if payload != rebuilt:
        raise ValueError("session summary does not match independently recomputed evidence")
    return rebuilt


def score_sessions(
    registration: Mapping[str, object],
    sessions: Iterable[Mapping[str, object]],
    *,
    scored_at: object,
    scored_by: str,
) -> Dict[str, object]:
    registered = validate_registration(registration)
    scorer = str(scored_by or "").strip()[:120]
    if not scorer or scorer.lower() == str(registered["subject_system_id"]).lower():
        raise ValueError("cross-session scoring requires an evaluator distinct from Eve")
    scored = _timestamp(scored_at)
    validated = [validate_session_bundle(session, registration) for session in sessions]
    if len({item["session_digest"] for item in validated}) != len(validated):
        raise ValueError("duplicate session bundles are not replication evidence")
    source_digests = [
        digest
        for item in validated
        for digest in item.get("source_report_digests", [])
    ]
    if len(source_digests) != len(set(source_digests)):
        raise ValueError("source windows were reused across sessions")
    ordered = sorted(validated, key=lambda item: item["started_at"])
    if ordered and _parsed(scored) < max(_parsed(item["created_at"]) for item in ordered):
        raise ValueError("cross-session scoring cannot predate session evidence")
    gaps: List[float] = []
    for previous, current in zip(ordered, ordered[1:]):
        gap = (_parsed(current["started_at"]) - _parsed(previous["ended_at"])).total_seconds()
        if gap < 0:
            raise ValueError("cross-session bundles overlap")
        gaps.append(gap)
    effects = [float(item["effect_vs_adaptive_ema_pp"]) for item in ordered]
    temporal = [
        float(item["within_session_temporal_specificity_pp"])
        for item in ordered
    ]
    minimum_sessions = int(registered["minimum_valid_sessions"])
    valid_session_count = len(ordered)
    enough = valid_session_count >= minimum_sessions
    median_effect = statistics.median(effects) if effects else None
    positive_fraction = sum(value > 0 for value in effects) / len(effects) if effects else 0.0
    median_temporal = statistics.median(temporal) if temporal else None
    within_fraction = (
        sum(item["within_session_status"] == "short_horizon_supported" for item in ordered)
        / len(ordered)
        if ordered
        else 0.0
    )
    distinct_days = sorted({_parsed(item["started_at"]).date().isoformat() for item in ordered})
    observed_strata = sorted({str(item["context_label"]) for item in ordered})
    required_strata = list(registered["required_context_strata"])
    boot_fingerprints = sorted(
        {
            str(item["host_boot_fingerprint_sha256"])
            for item in ordered
            if item.get("host_boot_fingerprint_sha256")
        }
    )
    gates = {
        "minimum_valid_sessions_met": enough,
        "minimum_session_separation_met": bool(
            enough
            and len(gaps) >= minimum_sessions - 1
            and all(
                value >= float(registered["minimum_session_gap_seconds"])
                for value in gaps
            )
        ),
        "minimum_distinct_days_met": (
            len(distinct_days) >= int(registered["minimum_distinct_utc_days"])
        ),
        "counterbalanced_contexts_met": all(
            item in observed_strata for item in required_strata
        ),
        "adaptive_baseline_effect_met": bool(
            median_effect is not None
            and median_effect
            >= float(registered["minimum_median_effect_vs_adaptive_ema_pp"])
        ),
        "positive_session_fraction_met": (
            positive_fraction
            >= float(registered["minimum_positive_session_fraction"])
        ),
        "temporal_specificity_met": bool(
            median_temporal is not None
            and median_temporal
            >= float(registered["minimum_median_temporal_specificity_pp"])
        ),
        "within_session_support_fraction_met": (
            within_fraction
            >= float(registered["minimum_short_horizon_support_fraction"])
        ),
    }
    if not enough:
        status = "collecting"
        reason = "fewer than the preregistered number of separated sessions are available"
    elif all(gates.values()):
        status = "cross_session_supported"
        reason = "all preregistered same-host cross-session PP-1 gates passed"
    elif median_effect is not None and median_effect <= -float(
        registered["minimum_median_effect_vs_adaptive_ema_pp"]
    ):
        status = "challenged"
        reason = "the preregistered adaptive-baseline direction reversed"
    else:
        status = "inconclusive"
        reason = "one or more preregistered cross-session gates did not pass"
    summary_sessions = [
        {
            "session_digest": item["session_digest"],
            "started_at": item["started_at"],
            "ended_at": item["ended_at"],
            "within_session_status": item["within_session_status"],
            "effect_vs_adaptive_ema_pp": item["effect_vs_adaptive_ema_pp"],
            "temporal_specificity_pp": item[
                "within_session_temporal_specificity_pp"
            ],
            "context_label": item["context_label"],
            "context_feature_median": item["context_feature_median"],
            "host_boot_fingerprint_sha256": item[
                "host_boot_fingerprint_sha256"
            ],
        }
        for item in ordered
    ]
    material = {
        "schema_version": REPORT_SCHEMA,
        "protocol_id": registered["protocol_id"],
        "registration_digest": registration["registration_digest"],
        "scored_at": scored,
        "scored_by": scorer,
        "status": status,
        "reason": reason,
        "indicator_id": "PP-1",
        "evidence_class": "lived_cross_session",
        "valid_session_count": valid_session_count,
        "planned_session_count": minimum_sessions,
        "distinct_utc_days": distinct_days,
        "observed_context_strata": observed_strata,
        "required_context_strata": required_strata,
        "inter_session_gaps_seconds": [round(value, 6) for value in gaps],
        "distinct_boot_fingerprint_count": len(boot_fingerprints),
        "median_effect_vs_adaptive_ema_pp": (
            round(median_effect, 6) if median_effect is not None else None
        ),
        "positive_session_fraction": round(positive_fraction, 6),
        "median_temporal_specificity_pp": (
            round(median_temporal, 6) if median_temporal is not None else None
        ),
        "short_horizon_support_fraction": round(within_fraction, 6),
        "gates": gates,
        "sessions": summary_sessions,
        "serial_independence_established": False,
        "external_authorship_established": False,
        "independent_replication_established": False,
        "runtime_mutated": False,
        "action_authority": False,
        "consciousness_proven": False,
        "subjective_experience_inferred": False,
        "boundary": BOUNDARY,
    }
    return {**material, "report_digest": _digest(material)}


def _boot_fingerprint() -> str:
    try:
        completed = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "kern.boottime"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    value = completed.stdout.strip() if completed.returncode == 0 else ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def _read_json(path: Path) -> Mapping[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _write(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    register = sub.add_parser("register")
    register.add_argument("--contract", type=Path, required=True)
    register.add_argument("--output", type=Path, required=True)
    register.add_argument("--protocol-id", required=True)
    register.add_argument("--protocol-author-id", required=True)
    register.add_argument("--scorer-id", required=True)
    register.add_argument("--minimum-session-gap-seconds", type=float, default=21600)

    collect = sub.add_parser("collect-session")
    collect.add_argument("--registration", type=Path, required=True)
    collect.add_argument("--window-dir", type=Path, required=True)
    collect.add_argument("--output", type=Path, required=True)
    collect.add_argument("--collected-by", required=True)

    score = sub.add_parser("score")
    score.add_argument("--registration", type=Path, required=True)
    score.add_argument("--session", type=Path, action="append", required=True)
    score.add_argument("--output", type=Path, required=True)
    score.add_argument("--scored-by", required=True)
    args = parser.parse_args()

    if args.command == "register":
        result = create_registration(
            _read_json(args.contract),
            protocol_id=args.protocol_id,
            registered_at=datetime.now(timezone.utc).isoformat(),
            protocol_author_id=args.protocol_author_id,
            scorer_id=args.scorer_id,
            minimum_session_gap_seconds=args.minimum_session_gap_seconds,
        )
    elif args.command == "collect-session":
        registration = _read_json(args.registration)
        registered = validate_registration(registration)
        longitudinal = _load_longitudinal()
        reports = longitudinal.collect_windows(
            registered["within_session_registration"],
            registered["source_contract"],
            output_dir=args.window_dir,
        )
        result = build_session_bundle(
            registration,
            reports,
            created_at=datetime.now(timezone.utc).isoformat(),
            collected_by=args.collected_by,
            host_boot_fingerprint_sha256=_boot_fingerprint(),
        )
    else:
        registration = _read_json(args.registration)
        result = score_sessions(
            registration,
            [_read_json(path) for path in args.session],
            scored_at=datetime.now(timezone.utc).isoformat(),
            scored_by=args.scored_by,
        )
    _write(args.output, result)
    sys.stdout.write(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n")
    return 1 if result.get("status") in {"challenged"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
