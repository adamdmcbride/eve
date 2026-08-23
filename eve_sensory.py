"""Privacy-bounded selective-perception primitives for Eve.

This module models a functional attention loop; it does not claim that machine
telemetry is sensation or that the resulting state is subjective experience.
Many source-attributed signals may arrive concurrently, while only a small
working set is admitted after novelty, change, relevance, precision,
habituation, and inhibition-of-return are considered.

The module is dependency-free so the attention policy can be lesion-tested
without a model, daemon, device sensor, or mutable runtime store.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


EVENT_SCHEMA = "eve.sensory_event.v1"
FRAME_SCHEMA = "eve.sensory_frame.v1"
ADAPTER_SCHEMA = "eve.sensory_adapter_event.v1"
QUALITY_SPACE_SCHEMA = "eve.perceptual_quality_space.v1"
ATTENTION_SCHEMA_SCHEMA = "eve.attention_schema.v1"
PREDICTIVE_PERCEPTION_SCHEMA = "eve.predictive_perception.v1"
BOUNDARY = (
    "Functional selective perception over typed evidence; not proof of "
    "subjective sensation or consciousness."
)
ATTENTION_SCHEMA_BOUNDARY = (
    "A descriptive and predictive engineering model used to control Eve's "
    "selective-perception policy; not subjective awareness or proof of "
    "consciousness."
)
PREDICTIVE_PERCEPTION_BOUNDARY = (
    "Recurrent prediction and precision-weighted error over admitted feature "
    "state; not a claim that prediction error is consciously experienced."
)
MODALITIES = {
    "auditory",
    "interoceptive",
    "proprioceptive",
    "social",
    "system",
    "visual",
    "world",
}
PRIVACY_LEVELS = {"public", "local_private", "sensitive"}
RAW_FIELDS = {
    "audio",
    "bytes",
    "content_bytes",
    "frame",
    "image",
    "pixels",
    "raw",
    "raw_content",
    "raw_payload",
    "screen_capture",
    "transcript",
}
RAW_INGEST_FIELDS = RAW_FIELDS | {
    "base64",
    "blob",
    "data_url",
    "embedding",
    "feature_vector",
    "key",
    "key_code",
    "keypress",
    "ocr_text",
    "pcm",
    "sample_buffer",
    "samples",
    "typed_text",
    "video",
    "video_frame",
    "waveform",
}
PRIVATE_ADAPTER_MODALITIES = {"auditory", "visual", "proprioceptive"}
ADAPTER_EVENT_FIELDS = {
    "change",
    "correlation_id",
    "features",
    "goal_relevance",
    "id",
    "intensity",
    "modality",
    "novelty",
    "observed_at",
    "permission_granted",
    "persistence",
    "precision",
    "privacy",
    "schema_version",
    "self_relevance",
    "social_relevance",
    "source",
    "subject",
    "summary",
    "urgency",
}
ADAPTER_SOURCES = {
    "eve_app_camera_features",
    "eve_app_interaction_features",
    "eve_app_microphone_features",
    "go_private_device_adapter",
    "private_device_adapter",
}
ADAPTER_SUBJECTS = {
    "eve_app_interaction",
    "local_auditory_scene",
    "local_proprioceptive_scene",
    "local_scene",
    "local_visual_scene",
}
ADAPTER_SCORE_FIELDS = {
    "change",
    "goal_relevance",
    "intensity",
    "novelty",
    "precision",
    "self_relevance",
    "social_relevance",
    "urgency",
}
FEATURE_LIMITS = {
    "action_latency_ms": 60_000.0,
    "contact_count": 100.0,
    "energy_percent": 100.0,
    "face_count": 32.0,
    "focus_changes": 100.0,
    "force_percent": 100.0,
    "interaction_rate": 100.0,
    "key_events": 500.0,
    "luminance_percent": 100.0,
    "motion_percent": 100.0,
    "object_count": 128.0,
    "person_count": 32.0,
    "pointer_events": 500.0,
    "position_delta": 100.0,
    "scene_change_percent": 100.0,
    "sound_change_percent": 100.0,
    "source_count": 32.0,
    "spectral_centroid_hz": 24_000.0,
    "speech_likelihood": 100.0,
    "zero_crossing_rate": 1.0,
}
FEATURE_ENUMS = {
    "activity_state": {"quiet", "sound", "speech_like", "active", "idle", "unknown"},
    "actuator_state": {"idle", "moving", "blocked", "complete", "unknown"},
    "focus_state": {"focused", "unfocused", "unknown"},
    "scene_state": {"stable", "movement", "large_change", "unknown"},
    "visibility_state": {"visible", "hidden", "unknown"},
}
DEFAULT_CAPACITY = 4
DEFAULT_BINDING_WINDOW_SECONDS = 3
DEFAULT_RECOVERY_SECONDS = 300
DEFAULT_ORIENT_THRESHOLD = 68
DEFAULT_QUALITY_CHANGE_THRESHOLD = 8.0
DEFAULT_ATTENTION_SCHEMA_TEMPERATURE = 12.0
DEFAULT_ATTENTION_SCHEMA_CONTROL_LIMIT = 28.0
DEFAULT_PREDICTION_ERROR_THRESHOLD = 8.0


def _text(value: object, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def _identifier(value: object, fallback: str, limit: int = 80) -> str:
    """Return a low-entropy identifier, never caller-supplied prose."""
    candidate = _text(value, limit).lower().replace("-", "_")
    candidate = re.sub(r"[^a-z0-9_.:]", "_", candidate)
    candidate = re.sub(r"_+", "_", candidate).strip("_.:")
    return candidate[:limit] or fallback


def _number(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _is_finite_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _clamp(value: object, low: float = 0.0, high: float = 100.0, default: float = 0.0) -> float:
    return max(low, min(high, _number(value, default)))


def _now(value: object = None) -> str:
    parsed = _parse_time(value)
    if parsed is None:
        parsed = datetime.now(timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()


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


def _stable_hash(*parts: object, length: int = 24) -> str:
    material = "|".join(_text(part, 500).lower() for part in parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:length]


def _privacy_summary(
    *,
    privacy: str,
    modality: str,
    source: str,
    summary: str,
) -> str:
    if privacy != "sensitive":
        return summary
    return f"Sensitive {modality} signal observed from {source}; content withheld."


def forbidden_ingest_paths(value: object, *, prefix: str = "") -> List[str]:
    """Find recursively supplied raw/private fields before normalization.

    Normalization alone is not enough at a device boundary: silently dropping a
    raw frame would still mean the backend received it. Adapters therefore fail
    closed before persistence when a payload contains samples, pixels, speech,
    keystrokes, high-dimensional vectors, or encoded media.
    """
    found: List[str] = []
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = _text(raw_key, 80).lower().replace("-", "_")
            path = f"{prefix}.{key}" if prefix else key
            if key in RAW_INGEST_FIELDS:
                found.append(path)
                continue
            found.extend(forbidden_ingest_paths(child, prefix=path))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            path = f"{prefix}[{index}]" if prefix else f"[{index}]"
            found.extend(forbidden_ingest_paths(child, prefix=path))
    return found[:24]


def _normalize_features(
    modality: str,
    value: object,
    *,
    strict: bool = False,
) -> Dict[str, object]:
    source = value if isinstance(value, dict) else {}
    if strict and value is not None and not isinstance(value, dict):
        raise ValueError("sensory features must be an object")
    normalized: Dict[str, object] = {}
    for raw_key, raw_value in source.items():
        key = _text(raw_key, 80).lower().replace("-", "_")
        if key in FEATURE_LIMITS:
            if strict and not _is_finite_number(raw_value):
                raise ValueError(f"sensory feature {key} must be a finite number")
            normalized[key] = round(_clamp(raw_value, 0.0, FEATURE_LIMITS[key]), 3)
        elif key in FEATURE_ENUMS:
            if strict and not isinstance(raw_value, str):
                raise ValueError(f"sensory feature {key} must be categorical text")
            enum_value = _identifier(raw_value, "unknown", 32)
            normalized[key] = enum_value if enum_value in FEATURE_ENUMS[key] else "unknown"
        elif key in {"active", "visible"}:
            if strict and not isinstance(raw_value, bool):
                raise ValueError(f"sensory feature {key} must be boolean")
            normalized[key] = bool(raw_value)
        elif strict:
            raise ValueError(f"unknown sensory feature: {key or 'missing'}")
    # Do not allow a caller to smuggle a second representation into this safe
    # feature map. The modality is retained for auditability even if no known
    # features survived.
    normalized["feature_modality"] = modality
    return normalized


def _feature_signature(features: Dict[str, object]) -> Tuple[Tuple[str, object], ...]:
    """Coarsen sensor values so real state changes dishabituate without noise.

    The signature is derived only from admitted low-dimensional features. Ten
    broad bins per numeric feature avoid treating tiny microphone/camera jitter
    as a new object on every sample.
    """
    signature: List[Tuple[str, object]] = []
    for key, value in sorted(features.items()):
        if key == "feature_modality":
            continue
        if key in FEATURE_LIMITS and isinstance(value, (int, float)) and not isinstance(value, bool):
            width = max(FEATURE_LIMITS[key] / 10.0, 0.001)
            signature.append((key, int(round(float(value) / width))))
        elif isinstance(value, (str, bool)):
            signature.append((key, value))
    return tuple(signature)


def feature_quality_distance(
    current: object,
    previous: object,
) -> Dict[str, object]:
    """Measure smooth distance between two admitted low-dimensional percepts.

    Numeric dimensions are normalized by their declared physical range;
    categorical and boolean dimensions use exact-match distance. Only shared,
    admitted dimensions are compared, and low coverage fails closed rather than
    treating an adapter-shape change as a perceptual jump.
    """
    current_features = current if isinstance(current, dict) else {}
    previous_features = previous if isinstance(previous, dict) else {}
    current_modality = _text(current_features.get("feature_modality"), 32)
    previous_modality = _text(previous_features.get("feature_modality"), 32)
    admitted_keys = set(FEATURE_LIMITS) | set(FEATURE_ENUMS) | {"active", "visible"}
    current_keys = {
        key
        for key in current_features
        if key != "feature_modality" and key in admitted_keys
    }
    previous_keys = {
        key
        for key in previous_features
        if key != "feature_modality" and key in admitted_keys
    }
    shared = sorted(current_keys & previous_keys)
    union = current_keys | previous_keys
    coverage = float(len(shared)) / float(len(union)) if union else 0.0
    if (
        not shared
        or coverage < 0.5
        or not current_modality
        or current_modality != previous_modality
    ):
        return {
            "schema_version": QUALITY_SPACE_SCHEMA,
            "comparable": False,
            "modality": current_modality or previous_modality,
            "dimension_count": 0,
            "coverage": round(coverage, 3),
            "rms_distance": None,
            "maximum_distance": None,
        }

    distances: List[float] = []
    for key in shared:
        current_value = current_features.get(key)
        previous_value = previous_features.get(key)
        if (
            key in FEATURE_LIMITS
            and _is_finite_number(current_value)
            and _is_finite_number(previous_value)
        ):
            limit = max(0.001, float(FEATURE_LIMITS[key]))
            distance = min(1.0, abs(float(current_value) - float(previous_value)) / limit)
        elif key in FEATURE_ENUMS and isinstance(current_value, str) and isinstance(previous_value, str):
            distance = 0.0 if current_value == previous_value else 1.0
        elif key in {"active", "visible"} and isinstance(current_value, bool) and isinstance(previous_value, bool):
            distance = 0.0 if current_value == previous_value else 1.0
        else:
            continue
        distances.append(distance)
    if not distances:
        return {
            "schema_version": QUALITY_SPACE_SCHEMA,
            "comparable": False,
            "modality": current_modality,
            "dimension_count": 0,
            "coverage": round(coverage, 3),
            "rms_distance": None,
            "maximum_distance": None,
        }
    rms = math.sqrt(sum(value * value for value in distances) / len(distances)) * 100.0
    maximum = max(distances) * 100.0
    return {
        "schema_version": QUALITY_SPACE_SCHEMA,
        "comparable": True,
        "modality": current_modality,
        "dimension_count": len(distances),
        "coverage": round(coverage, 3),
        "rms_distance": round(rms, 3),
        "maximum_distance": round(maximum, 3),
    }


def predict_next_features(
    current: object,
    previous: object,
) -> Dict[str, object]:
    """Project one bounded step in an admitted low-dimensional feature space.

    Numeric dimensions use a clipped constant-velocity forecast. Categorical
    and boolean dimensions use persistence. This is intentionally small and
    inspectable; it is not a learned world model and never reconstructs raw
    sensor content.
    """
    current_features = current if isinstance(current, dict) else {}
    previous_features = previous if isinstance(previous, dict) else {}
    modality = _text(current_features.get("feature_modality"), 32)
    if not modality:
        return {}
    previous_modality = _text(previous_features.get("feature_modality"), 32)
    compatible_previous = previous_modality == modality
    prediction: Dict[str, object] = {"feature_modality": modality}
    for key, current_value in current_features.items():
        if key == "feature_modality":
            continue
        previous_value = previous_features.get(key)
        if key in FEATURE_LIMITS and _is_finite_number(current_value):
            projected = float(current_value)
            if compatible_previous and _is_finite_number(previous_value):
                projected += float(current_value) - float(previous_value)
            prediction[key] = round(
                _clamp(projected, 0.0, float(FEATURE_LIMITS[key]), float(current_value)),
                3,
            )
        elif key in FEATURE_ENUMS and isinstance(current_value, str):
            prediction[key] = current_value
        elif key in {"active", "visible"} and isinstance(current_value, bool):
            prediction[key] = current_value
    return prediction if len(prediction) > 1 else {}


def feature_prediction_error(
    actual: object,
    predicted: object,
    *,
    precision: object = 100.0,
) -> Dict[str, object]:
    """Compare a prior recurrent forecast with a later admitted percept."""
    distance = feature_quality_distance(actual, predicted)
    precision_weight = _clamp(precision, 0.0, 100.0, 0.0) / 100.0
    if not distance.get("comparable"):
        return {
            "schema_version": PREDICTIVE_PERCEPTION_SCHEMA,
            "comparable": False,
            "modality": distance.get("modality") or "",
            "dimension_count": 0,
            "coverage": distance.get("coverage") or 0.0,
            "raw_maximum_error": None,
            "precision_weight": round(precision_weight, 3),
            "weighted_error": None,
            "surprising": False,
        }
    raw_error = float(distance.get("maximum_distance") or 0.0)
    weighted_error = raw_error * precision_weight
    return {
        "schema_version": PREDICTIVE_PERCEPTION_SCHEMA,
        "comparable": True,
        "modality": distance.get("modality") or "",
        "dimension_count": int(distance.get("dimension_count") or 0),
        "coverage": distance.get("coverage") or 0.0,
        "raw_maximum_error": round(raw_error, 3),
        "precision_weight": round(precision_weight, 3),
        "weighted_error": round(weighted_error, 3),
        "surprising": weighted_error >= DEFAULT_PREDICTION_ERROR_THRESHOLD,
    }


def normalize_adapter_event(
    event: object,
    *,
    allowed_modalities: Iterable[str],
    session_id: str,
    now: object = None,
) -> Dict[str, object]:
    """Validate one private-device feature event for Eve's event spine."""
    if not isinstance(event, dict):
        raise ValueError("sensory adapter events must be objects")
    try:
        serialized_size = len(json.dumps(event, ensure_ascii=True).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ValueError("sensory adapter event must be JSON serializable") from exc
    if serialized_size > 8_192:
        raise ValueError("sensory adapter event is too large")
    forbidden = forbidden_ingest_paths(event)
    if forbidden:
        raise ValueError("raw sensor content is forbidden: " + ", ".join(forbidden))
    unknown_fields = sorted(
        _text(key, 80).lower().replace("-", "_")
        for key in event
        if _text(key, 80).lower().replace("-", "_") not in ADAPTER_EVENT_FIELDS
    )
    if unknown_fields:
        raise ValueError("unknown sensory adapter field: " + ", ".join(unknown_fields[:8]))

    modality = _text(event.get("modality"), 32).lower()
    allowed = {_text(item, 32).lower() for item in allowed_modalities}
    if modality not in PRIVATE_ADAPTER_MODALITIES or modality not in allowed:
        raise ValueError(f"sensory modality is not admitted for this session: {modality or 'missing'}")
    if modality in {"auditory", "visual"} and event.get("permission_granted") is not True:
        raise ValueError(f"{modality} input requires current device permission")
    for score_field in ADAPTER_SCORE_FIELDS:
        if score_field not in event:
            continue
        score_value = event.get(score_field)
        if not _is_finite_number(score_value):
            raise ValueError(f"sensory field {score_field} must be a finite number")
    if event.get("observed_at") is not None and _parse_time(event.get("observed_at")) is None:
        raise ValueError("sensory observed_at must be an ISO-8601 timestamp")

    session = _text(session_id, 120)
    if not session:
        raise ValueError("sensory session id is required")
    correlation = _text(event.get("correlation_id"), 120)
    if correlation and (
        correlation != session
        and not re.fullmatch(
            re.escape(session) + r":(?:scene|interaction):[0-9]{1,16}",
            correlation,
        )
    ):
        raise ValueError("sensory correlation id must belong to the current session")
    source_candidate = _identifier(event.get("source"), "private_device_adapter", 80)
    source = source_candidate if source_candidate in ADAPTER_SOURCES else "private_device_adapter"
    subject_candidate = _identifier(event.get("subject"), f"local_{modality}_scene", 80)
    subject = subject_candidate if subject_candidate in ADAPTER_SUBJECTS else f"local_{modality}_scene"
    features = _normalize_features(modality, event.get("features"), strict=True)
    if len(features) <= 1:
        raise ValueError("at least one admitted sensory feature is required")
    if modality == "auditory":
        activity = str(features.get("activity_state") or "unknown")
        summary = {
            "quiet": "The local acoustic scene is quiet; no recording or words were retained.",
            "speech_like": "Speech-band acoustic activity changed nearby; no recording or words were retained.",
        }.get(activity, "The local acoustic scene changed; no recording or words were retained.")
    elif modality == "visual":
        scene = str(features.get("scene_state") or "unknown")
        summary = {
            "stable": "The local visual scene is stable; no frame was retained.",
            "movement": "Movement changed the local visual scene; no frame was retained.",
            "large_change": "The local visual scene changed substantially; no frame was retained.",
        }.get(scene, "Local visual features changed; no frame was retained.")
    else:
        summary = "Aggregate local interaction state changed; no keys or content were retained."
    observed_at = _now(event.get("observed_at") or now)
    fingerprint = _stable_hash(modality, source, subject, _feature_signature(features))
    safe_event = {
        "schema_version": ADAPTER_SCHEMA,
        # Caller ids are ignored so a nominal identifier cannot become a text
        # side channel. The server derives an id from the admitted fields.
        "id": f"adapter_{_stable_hash(session, modality, correlation, observed_at, features, event.get('change'))}",
        "observed_at": observed_at,
        "modality": modality,
        "source": source,
        "subject": subject,
        "correlation_id": correlation or session,
        # Caller prose is deliberately ignored. The backend derives a small
        # categorical description so transcripts/OCR cannot hide in summary.
        "summary": summary,
        "features": features,
        "fingerprint": fingerprint,
        "intensity": _clamp(event.get("intensity"), default=35),
        "novelty": _clamp(event.get("novelty"), default=50),
        "change": _clamp(event.get("change"), default=0),
        "urgency": _clamp(event.get("urgency"), default=20),
        "goal_relevance": _clamp(event.get("goal_relevance"), default=35),
        "self_relevance": _clamp(event.get("self_relevance"), default=35),
        "social_relevance": _clamp(event.get("social_relevance"), default=0),
        "precision": _clamp(event.get("precision"), default=70),
        # An ambient acoustic classifier cannot promote itself into a human
        # message or emergency interrupt. Those require separate admitted paths.
        "direct_human": False,
        "safety_critical": False,
        "privacy": "local_private",
        "persistence": "features_only",
        "private_adapter_event": True,
        "permission_granted": True,
        "requires_permission": False,
    }
    return normalize_event(safe_event, now=now)


def normalize_adapter_batch(
    events: object,
    *,
    allowed_modalities: Iterable[str],
    session_id: str,
    now: object = None,
    maximum_events: int = 12,
) -> List[Dict[str, object]]:
    if not isinstance(events, list) or not events:
        raise ValueError("sensory events must be a non-empty array")
    if len(events) > max(1, int(maximum_events)):
        raise ValueError("too many sensory events in one batch")
    return [
        normalize_adapter_event(
            item,
            allowed_modalities=allowed_modalities,
            session_id=session_id,
            now=now,
        )
        for item in events
    ]


def normalize_event(event: object, *, now: object = None) -> Dict[str, object]:
    """Return one source-attributed feature record with raw sensor data removed."""
    source_event = event if isinstance(event, dict) else {}
    modality = _text(source_event.get("modality"), 32).lower()
    if modality not in MODALITIES:
        modality = "world"
    source = _text(source_event.get("source"), 120) or "unknown_source"
    subject = _text(source_event.get("subject") or source_event.get("entity"), 120)
    privacy = _text(source_event.get("privacy"), 32).lower()
    if privacy not in PRIVACY_LEVELS:
        privacy = "local_private"
    original_summary = _text(
        source_event.get("summary")
        or source_event.get("text")
        or source_event.get("description"),
        320,
    ) or f"{modality} signal from {source}"
    fingerprint = _text(source_event.get("fingerprint"), 80) or _stable_hash(
        modality,
        source,
        subject,
        original_summary,
    )
    event_id = _text(source_event.get("id"), 120) or f"sensory-{fingerprint}"
    observed_at = _now(source_event.get("observed_at") or source_event.get("created_at") or now)
    direct_human = bool(source_event.get("direct_human"))
    safety_critical = bool(source_event.get("safety_critical"))
    permission_granted = bool(source_event.get("permission_granted"))
    normalized = {
        "schema_version": EVENT_SCHEMA,
        "id": event_id,
        "observed_at": observed_at,
        "modality": modality,
        "source": source,
        "subject": subject,
        "correlation_id": _text(source_event.get("correlation_id"), 120),
        "summary": _privacy_summary(
            privacy=privacy,
            modality=modality,
            source=source,
            summary=original_summary,
        ),
        "features": _normalize_features(modality, source_event.get("features")),
        "fingerprint": fingerprint,
        "intensity": round(_clamp(source_event.get("intensity"), default=35), 2),
        "novelty": round(_clamp(source_event.get("novelty"), default=50), 2),
        "change": round(_clamp(source_event.get("change"), default=0), 2),
        "urgency": round(_clamp(source_event.get("urgency"), default=20), 2),
        "goal_relevance": round(_clamp(source_event.get("goal_relevance"), default=35), 2),
        "self_relevance": round(_clamp(source_event.get("self_relevance"), default=35), 2),
        "social_relevance": round(_clamp(source_event.get("social_relevance"), default=0), 2),
        "precision": round(_clamp(source_event.get("precision"), default=70), 2),
        "direct_human": direct_human,
        "safety_critical": safety_critical,
        "privacy": privacy,
        "persistence": "features_only",
        "private_adapter_event": bool(source_event.get("private_adapter_event")),
        "permission_granted": permission_granted,
        "requires_permission": bool(
            source_event.get("requires_permission")
            or (modality in {"auditory", "visual"} and not permission_granted)
        ),
    }
    # Keep the contract auditable: no caller-supplied raw field survives, even
    # for local-private events whose short summary is allowed.
    assert not RAW_FIELDS.intersection(normalized)
    return normalized


def _entity_tracks(
    events: Sequence[Dict[str, object]],
    *,
    prior_frame: object,
    timestamp: str,
    retention_seconds: int = 300,
) -> List[Dict[str, object]]:
    prior = prior_frame if isinstance(prior_frame, dict) else {}
    now_dt = _parse_time(timestamp) or datetime.now(timezone.utc)
    tracks: Dict[str, Dict[str, object]] = {}
    for record in prior.get("entity_tracks") or []:
        if not isinstance(record, dict):
            continue
        key = _text(record.get("track_key"), 120)
        last_seen = _parse_time(record.get("last_seen_at"))
        if not key or last_seen is None:
            continue
        if 0 <= (now_dt - last_seen).total_seconds() <= max(1, retention_seconds):
            tracks[key] = copy.deepcopy(record)

    ordered_events = sorted(
        events,
        key=lambda item: (
            _parse_time(item.get("observed_at"))
            or datetime.min.replace(tzinfo=timezone.utc),
            str(item.get("id") or ""),
        ),
    )
    for event in ordered_events:
        identity = _text(event.get("subject"), 120) or _text(event.get("correlation_id"), 120)
        if not identity:
            continue
        key = _stable_hash("entity-track", identity, length=20)
        previous = tracks.get(key, {})
        previous_fingerprint = _text(previous.get("last_fingerprint"), 80)
        fingerprint = _text(event.get("fingerprint"), 80)
        event_time = _parse_time(event.get("observed_at")) or now_dt
        previous_time = _parse_time(previous.get("last_seen_at"))
        observation_key = _stable_hash(
            "entity-observation",
            event.get("id"),
            event.get("observed_at"),
            fingerprint,
            length=20,
        )
        recent_observation_keys = [
            _text(item, 40)
            for item in (previous.get("recent_observation_keys") or [])
            if _text(item, 40)
        ][-31:]
        replayed = observation_key in recent_observation_keys or bool(
            previous
            and not recent_observation_keys
            and previous_time is not None
            and event_time <= previous_time
        )
        modalities = {
            _text(item, 32)
            for item in (previous.get("modalities") or [])
            if _text(item, 32)
        }
        modalities.add(_text(event.get("modality"), 32))
        if replayed:
            previous["modalities"] = sorted(item for item in modalities if item)
            tracks[key] = previous
            continue
        recent_observation_keys.append(observation_key)
        tracks[key] = {
            "track_key": key,
            "subject": identity,
            "first_seen_at": previous.get("first_seen_at") or event.get("observed_at") or timestamp,
            "last_seen_at": event.get("observed_at") or timestamp,
            "observation_count": min(10_000, int(previous.get("observation_count") or 0) + 1),
            "recent_observation_keys": recent_observation_keys[-32:],
            "modalities": sorted(item for item in modalities if item),
            "last_summary": _text(event.get("summary"), 240),
            "last_fingerprint": fingerprint,
            "changed": bool(previous_fingerprint and fingerprint and previous_fingerprint != fingerprint),
            "precision": round(_clamp(event.get("precision"), default=70), 2),
            "persistence": "features_only",
        }
    return sorted(
        tracks.values(),
        key=lambda item: (_parse_time(item.get("last_seen_at")) or datetime.min.replace(tzinfo=timezone.utc)),
        reverse=True,
    )[:24]


def _channel_key(event: Dict[str, object]) -> str:
    return _stable_hash(
        event.get("modality"),
        event.get("source"),
        event.get("subject") or "unbound",
        length=20,
    )


def _event_score(event: Dict[str, object], habituation_factor: float, return_penalty: float) -> Tuple[float, Dict[str, float]]:
    bottom_up = (
        float(event["intensity"]) * 0.20
        + float(event["novelty"]) * 0.25
        + float(event["change"]) * 0.25
        + float(event["urgency"]) * 0.30
    )
    top_down = (
        float(event["goal_relevance"]) * 0.35
        + float(event["self_relevance"]) * 0.25
        + float(event["social_relevance"]) * 0.25
        + float(event["precision"]) * 0.15
    )
    base = bottom_up * 0.55 + top_down * 0.45
    if event.get("direct_human"):
        base = max(base, 94.0)
    if event.get("safety_critical"):
        base = max(base, 98.0)
    effective = max(0.0, min(100.0, base * habituation_factor - return_penalty))
    return round(effective, 2), {
        "bottom_up": round(bottom_up, 2),
        "top_down": round(top_down, 2),
        "base": round(base, 2),
        "habituation_factor": round(habituation_factor, 3),
        "inhibition_of_return": round(return_penalty, 2),
    }


def _prior_dict(frame: object, key: str) -> Dict[str, Dict[str, object]]:
    source = frame if isinstance(frame, dict) else {}
    value = source.get(key) if isinstance(source.get(key), dict) else {}
    return {
        _text(name, 120): copy.deepcopy(record)
        for name, record in value.items()
        if _text(name, 120) and isinstance(record, dict)
    }


def _habituation(
    event: Dict[str, object],
    *,
    prior_frame: object,
    timestamp: str,
    recovery_seconds: int,
    quality_space_enabled: bool,
    predictive_coding_enabled: bool,
) -> Tuple[int, float, bool, Dict[str, object]]:
    prior_habituation = _prior_dict(prior_frame, "habituation")
    prior_channels = _prior_dict(prior_frame, "channels")
    fingerprint = str(event["fingerprint"])
    channel = _channel_key(event)
    previous = prior_habituation.get(fingerprint, {})
    prior_channel = prior_channels.get(channel, {})
    now_dt = _parse_time(timestamp) or datetime.now(timezone.utc)
    previous_dt = _parse_time(previous.get("last_seen_at"))
    elapsed = (now_dt - previous_dt).total_seconds() if previous_dt else None
    same_recent = elapsed is not None and 0 <= elapsed <= recovery_seconds
    prior_channel_dt = _parse_time(prior_channel.get("last_seen_at"))
    channel_elapsed = (now_dt - prior_channel_dt).total_seconds() if prior_channel_dt else None
    same_channel_recent = channel_elapsed is not None and 0 <= channel_elapsed <= recovery_seconds
    quality = (
        feature_quality_distance(event.get("features"), prior_channel.get("last_features"))
        if quality_space_enabled
        else {
            "schema_version": QUALITY_SPACE_SCHEMA,
            "comparable": False,
            "modality": event.get("modality"),
            "dimension_count": 0,
            "coverage": 0.0,
            "rms_distance": None,
            "maximum_distance": None,
        }
    )
    prediction_error = (
        feature_prediction_error(
            event.get("features"),
            prior_channel.get("predicted_features"),
            precision=event.get("precision"),
        )
        if predictive_coding_enabled
        else {
            "schema_version": PREDICTIVE_PERCEPTION_SCHEMA,
            "comparable": False,
            "modality": event.get("modality"),
            "dimension_count": 0,
            "coverage": 0.0,
            "raw_maximum_error": None,
            "precision_weight": round(
                _clamp(event.get("precision"), 0.0, 100.0, 0.0) / 100.0,
                3,
            ),
            "weighted_error": None,
            "surprising": False,
            "lesioned": True,
        }
    )
    quality_changed = bool(
        quality.get("comparable")
        and float(quality.get("maximum_distance") or 0.0)
        >= DEFAULT_QUALITY_CHANGE_THRESHOLD
    )
    if prediction_error.get("comparable"):
        changed = bool(prediction_error.get("surprising"))
        repeat_count = (
            int(prior_channel.get("repeat_count") or previous.get("repeat_count") or 0) + 1
            if same_channel_recent and not changed
            else 1
        )
    elif quality.get("comparable"):
        changed = quality_changed
        repeat_count = (
            int(prior_channel.get("repeat_count") or previous.get("repeat_count") or 0) + 1
            if same_channel_recent and not changed
            else 1
        )
    else:
        repeat_count = int(previous.get("repeat_count") or 0) + 1 if same_recent else 1
        changed = bool(
            prior_channel.get("last_fingerprint")
            and prior_channel.get("last_fingerprint") != fingerprint
        )
    event["quality_distance"] = quality
    event["prediction_error"] = prediction_error
    event["predicted_change"] = bool(
        prediction_error.get("comparable")
        and quality_changed
        and not prediction_error.get("surprising")
    )
    event["prediction_violation"] = bool(
        prediction_error.get("comparable")
        and prediction_error.get("surprising")
    )
    if changed:
        repeat_count = 1
        if quality.get("comparable") or prediction_error.get("comparable"):
            maximum_distance = max(
                float(quality.get("maximum_distance") or 0.0),
                float(prediction_error.get("weighted_error") or 0.0),
            )
            derived_change = min(100.0, max(55.0, maximum_distance * 1.5))
            derived_novelty = min(100.0, max(50.0, maximum_distance * 1.25))
        else:
            derived_change = 90.0
            derived_novelty = 85.0
        event["change"] = max(float(event.get("change") or 0), derived_change)
        event["novelty"] = max(float(event.get("novelty") or 0), derived_novelty)
    factor = max(0.18, 1.0 / (1.0 + 0.38 * max(0, repeat_count - 1)))
    if event.get("direct_human"):
        factor = max(factor, 0.90)
    if event.get("safety_critical"):
        factor = 1.0
    next_prediction = predict_next_features(
        event.get("features"),
        prior_channel.get("last_features"),
    )
    return repeat_count, round(factor, 3), changed, {
        "channel": channel,
        "fingerprint": fingerprint,
        "repeat_count": repeat_count,
        "last_seen_at": timestamp,
        "quality_distance": quality,
        "prediction_error": prediction_error,
        "last_features": copy.deepcopy(event.get("features") or {}),
        "predicted_features": next_prediction,
    }


def _recent_orientation_penalty(event: Dict[str, object], prior_frame: object, timestamp: str) -> float:
    if event.get("direct_human") or event.get("safety_critical") or float(event.get("change") or 0) >= 70:
        return 0.0
    prior = prior_frame if isinstance(prior_frame, dict) else {}
    now_dt = _parse_time(timestamp) or datetime.now(timezone.utc)
    for record in prior.get("recent_orientations") or []:
        if not isinstance(record, dict) or record.get("fingerprint") != event.get("fingerprint"):
            continue
        oriented_dt = _parse_time(record.get("oriented_at"))
        if oriented_dt and 0 <= (now_dt - oriented_dt).total_seconds() <= 60:
            return 18.0
    return 0.0


def _bind_events(
    scored: Sequence[Dict[str, object]],
    *,
    binding_window_seconds: int,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    """Bind only cross-modal signals sharing an entity or correlation id."""
    groups: Dict[str, List[Dict[str, object]]] = {}
    for event in scored:
        identity = _text(event.get("correlation_id"), 120) or _text(event.get("subject"), 120)
        if not identity:
            continue
        groups.setdefault(identity.lower(), []).append(event)
    episodes: List[Dict[str, object]] = []
    member_ids: set[str] = set()
    for identity, members in groups.items():
        grouped_member_ids = {
            str(item.get("id")) for item in members if item.get("id")
        }
        # A sliding event window can contain several samples from the same
        # modality. Binding every sample makes one acoustic/visual state appear
        # several times in a scarce working set. Keep the strongest, newest
        # representative of each modality before testing the temporal episode.
        representatives: Dict[str, Dict[str, object]] = {}
        for item in members:
            modality = str(item.get("modality") or "world")
            current = representatives.get(modality)
            item_rank = (
                float(item.get("attention_score") or 0),
                _parse_time(item.get("observed_at"))
                or datetime.min.replace(tzinfo=timezone.utc),
                str(item.get("id") or ""),
            )
            current_rank = (
                float(current.get("attention_score") or 0),
                _parse_time(current.get("observed_at"))
                or datetime.min.replace(tzinfo=timezone.utc),
                str(current.get("id") or ""),
            ) if current else None
            if current_rank is None or item_rank > current_rank:
                representatives[modality] = item
        members = list(representatives.values())
        modalities = {str(item.get("modality")) for item in members}
        timestamps = [_parse_time(item.get("observed_at")) for item in members]
        valid_times = [item for item in timestamps if item is not None]
        if len(modalities) < 2 or len(valid_times) < 2:
            continue
        span = (max(valid_times) - min(valid_times)).total_seconds()
        if span > max(0, int(binding_window_seconds)):
            continue
        members = sorted(members, key=lambda item: (-float(item.get("attention_score") or 0), str(item.get("id") or "")))
        episode_id = "episode-" + _stable_hash(identity, *(item.get("id") for item in members), length=20)
        summary = " + ".join(_text(item.get("summary"), 130) for item in members[:3])
        score = min(100.0, max(float(item.get("attention_score") or 0) for item in members) + 6.0)
        episode_subject = _text(members[0].get("subject"), 120) or identity
        member_fingerprints = sorted(
            {
                str(item.get("fingerprint"))
                for item in members
                if item.get("fingerprint")
            }
        )
        episode = {
            "schema_version": EVENT_SCHEMA,
            "id": episode_id,
            "observed_at": max(valid_times).replace(microsecond=0).isoformat(),
            "modality": "multisensory",
            "modalities": sorted(modalities),
            "source": "temporal_entity_binding",
            "subject": episode_subject,
            "correlation_id": _text(members[0].get("correlation_id"), 120),
            "summary": _text(summary, 320),
            # Correlation ids identify a sampling instant. They must not make
            # an otherwise unchanged bound state look novel on every sample.
            "fingerprint": _stable_hash(
                "episode",
                episode_subject,
                *sorted(modalities),
                *member_fingerprints,
            ),
            "attention_score": round(score, 2),
            "precision": round(sum(float(item.get("precision") or 0) for item in members) / len(members), 2),
            "member_ids": [str(item.get("id")) for item in members],
            "member_fingerprints": member_fingerprints,
            "direct_human": any(bool(item.get("direct_human")) for item in members),
            "safety_critical": any(bool(item.get("safety_critical")) for item in members),
            "requires_permission": any(bool(item.get("requires_permission")) for item in members),
            "privacy": "sensitive" if any(item.get("privacy") == "sensitive" for item in members) else "local_private",
            "persistence": "features_only",
            "disposition": "orient" if score >= DEFAULT_ORIENT_THRESHOLD else "monitor",
            "binding_basis": "same entity or correlation id within temporal window",
        }
        episodes.append(episode)
        member_ids.update(grouped_member_ids)
    unbound = [item for item in scored if str(item.get("id")) not in member_ids]
    return unbound, episodes


def _coalesce_candidates(
    candidates: Sequence[Dict[str, object]],
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    """Collapse repeated samples of one semantic state before admission.

    The event spine intentionally preserves bounded sample evidence. The
    capacity-limited working set serves a different purpose: representing the
    distinct states that currently compete for global access. This boundary
    prevents a fast sensor or repeated event poll from winning by multiplicity.
    """
    selected: Dict[Tuple[str, str, str, str], Dict[str, object]] = {}
    duplicates: List[Dict[str, object]] = []
    counts: Dict[Tuple[str, str, str, str], int] = {}
    for item in candidates:
        key = (
            str(item.get("modality") or "world"),
            str(item.get("source") or "unknown_source"),
            str(item.get("subject") or ""),
            str(item.get("fingerprint") or item.get("id") or "unknown"),
        )
        counts[key] = counts.get(key, 0) + 1
        current = selected.get(key)
        item_rank = (
            float(item.get("attention_score") or 0),
            _parse_time(item.get("observed_at"))
            or datetime.min.replace(tzinfo=timezone.utc),
            str(item.get("id") or ""),
        )
        current_rank = (
            float(current.get("attention_score") or 0),
            _parse_time(current.get("observed_at"))
            or datetime.min.replace(tzinfo=timezone.utc),
            str(current.get("id") or ""),
        ) if current else None
        if current_rank is None or item_rank > current_rank:
            if current is not None:
                duplicates.append(current)
            selected[key] = copy.deepcopy(item)
        else:
            duplicates.append(item)
    coalesced = []
    for key, item in selected.items():
        item["coalesced_observation_count"] = counts[key]
        coalesced.append(item)
    return coalesced, duplicates


def _attention_state_key(candidate: Dict[str, object]) -> str:
    return _stable_hash(
        "attention-state",
        candidate.get("modality"),
        candidate.get("source"),
        candidate.get("subject"),
        candidate.get("fingerprint") or candidate.get("id"),
        length=20,
    )


def _selection_score(candidate: Dict[str, object]) -> float:
    return _clamp(
        candidate.get("selection_score", candidate.get("attention_score")),
        0.0,
        100.0,
        0.0,
    )


def _attention_distribution(
    candidates: Sequence[Dict[str, object]],
) -> Tuple[List[Dict[str, object]], float]:
    """Return a bounded uncertainty proxy over the current priority map.

    This is deliberately labelled a model distribution rather than an
    empirical probability. Longitudinal calibration below scores its
    conditional next-state forecasts against later frames.
    """
    bounded = list(candidates[:8])
    if not bounded:
        return [], 0.0
    temperature = max(0.001, float(DEFAULT_ATTENTION_SCHEMA_TEMPERATURE))
    scores = [_selection_score(item) for item in bounded]
    maximum = max(scores)
    weights = [math.exp((score - maximum) / temperature) for score in scores]
    total = sum(weights) or 1.0
    probabilities = [weight / total for weight in weights]
    entropy = -sum(
        probability * math.log(probability)
        for probability in probabilities
        if probability > 0.0
    )
    normalized_entropy = (
        entropy / math.log(len(probabilities))
        if len(probabilities) > 1
        else 0.0
    )
    return [
        {
            "state_key": _attention_state_key(item),
            "target_id": item.get("id"),
            "fingerprint": item.get("fingerprint"),
            "probability": round(probability, 6),
            "selection_score": round(score, 2),
        }
        for item, probability, score in zip(bounded, probabilities, scores)
    ], round(normalized_entropy, 6)


def _attention_control_utility(candidate: Dict[str, object]) -> float:
    if candidate.get("safety_critical") or candidate.get("direct_human"):
        return 100.0
    return _clamp(
        float(candidate.get("goal_relevance") or 0.0) * 0.50
        + float(candidate.get("self_relevance") or 0.0) * 0.20
        + float(candidate.get("social_relevance") or 0.0) * 0.10
        + float(candidate.get("precision") or 0.0) * 0.20,
        0.0,
        100.0,
        0.0,
    )


def _attention_control_adjustment(
    candidate: Dict[str, object],
    *,
    overloaded: bool,
    enabled: bool,
) -> float:
    if not enabled or not overloaded:
        return 0.0
    if candidate.get("safety_critical") or candidate.get("direct_human"):
        return 0.0
    if not isinstance(candidate.get("score_components"), dict):
        # Bound multisensory episodes intentionally contain only aggregate
        # evidence. Do not invent missing goal/control features to suppress or
        # boost them.
        return 0.0
    utility = _attention_control_utility(candidate)
    components = (
        candidate.get("score_components")
        if isinstance(candidate.get("score_components"), dict)
        else {}
    )
    bottom_up = float(components.get("bottom_up") or 0.0)
    top_down = float(components.get("top_down") or 0.0)
    goal_relevance = _clamp(candidate.get("goal_relevance"), 0.0, 100.0, 0.0)
    capture_risk = max(0.0, bottom_up - top_down) * (1.0 - goal_relevance / 100.0)
    raw_adjustment = (utility - 50.0) * 0.75 - capture_risk * 0.15
    limit = float(DEFAULT_ATTENTION_SCHEMA_CONTROL_LIMIT)
    return round(max(-limit, min(limit, raw_adjustment)), 2)


def _apply_attention_schema_control(
    candidates: Sequence[Dict[str, object]],
    *,
    capacity: int,
    enabled: bool,
    orient_threshold: float = DEFAULT_ORIENT_THRESHOLD,
) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    baseline = sorted(
        [copy.deepcopy(item) for item in candidates],
        key=lambda item: (
            -float(item.get("attention_score") or 0.0),
            -float(item.get("precision") or 0.0),
            str(item.get("id") or ""),
        ),
    )
    for item in baseline:
        # A projected candidate may carry a prior control score. The baseline
        # arm must always begin from the current first-order attention score.
        item["selection_score"] = round(
            _clamp(item.get("attention_score"), 0.0, 100.0, 0.0),
            2,
        )
        item["attention_schema_adjustment"] = 0.0
    overloaded = len(baseline) > max(1, int(capacity))
    baseline_distribution, baseline_entropy = _attention_distribution(baseline)
    baseline_winner = baseline[0] if baseline else {}
    controlled: List[Dict[str, object]] = []
    for item in baseline:
        candidate = copy.deepcopy(item)
        adjustment = _attention_control_adjustment(
            candidate,
            overloaded=overloaded,
            enabled=enabled,
        )
        candidate["attention_schema_adjustment"] = adjustment
        candidate["attention_control_utility"] = round(
            _attention_control_utility(candidate),
            2,
        )
        urgency_floor = (
            _clamp(candidate.get("urgency"), 0.0, 100.0, 0.0)
            if (
                enabled
                and overloaded
                and float(candidate.get("urgency") or 0.0) >= 75.0
            )
            else 0.0
        )
        candidate["attention_urgency_floor"] = round(urgency_floor, 2)
        candidate["selection_score"] = round(
            max(
                urgency_floor,
                _clamp(float(candidate.get("attention_score") or 0.0) + adjustment),
            ),
            2,
        )
        candidate["disposition"] = (
            "orient"
            if candidate["selection_score"] >= float(orient_threshold)
            else "monitor"
            if candidate["selection_score"] >= 35
            else "ignore"
        )
        controlled.append(candidate)
    controlled.sort(
        key=lambda item: (
            -_selection_score(item),
            -float(item.get("precision") or 0.0),
            str(item.get("id") or ""),
        )
    )
    controlled_distribution, controlled_entropy = _attention_distribution(controlled)
    controlled_winner = controlled[0] if controlled else {}
    baseline_margin = (
        float(baseline[0].get("attention_score") or 0.0)
        - float(baseline[1].get("attention_score") or 0.0)
        if len(baseline) > 1
        else float(baseline_winner.get("attention_score") or 0.0)
    )
    controlled_margin = (
        _selection_score(controlled[0]) - _selection_score(controlled[1])
        if len(controlled) > 1
        else _selection_score(controlled_winner)
    )
    changed_winner = bool(
        baseline_winner
        and controlled_winner
        and _attention_state_key(baseline_winner) != _attention_state_key(controlled_winner)
    )
    adjusted_count = sum(
        1
        for item in controlled
        if abs(float(item.get("attention_schema_adjustment") or 0.0)) > 0.0
    )
    schema = {
        "schema_version": ATTENTION_SCHEMA_SCHEMA,
        "enabled": bool(enabled),
        "model_class": "bounded_counterfactual_priority_map",
        "current_state": {
            "candidate_count": len(baseline),
            "capacity": max(1, int(capacity)),
            "overloaded": overloaded,
            "baseline_target_id": baseline_winner.get("id"),
            "baseline_target_state_key": (
                _attention_state_key(baseline_winner) if baseline_winner else ""
            ),
            "baseline_margin": round(baseline_margin, 2),
            "baseline_normalized_entropy": baseline_entropy,
        },
        "prediction": {
            "target_id": controlled_winner.get("id"),
            "target_state_key": (
                _attention_state_key(controlled_winner) if controlled_winner else ""
            ),
            "margin": round(controlled_margin, 2),
            "normalized_entropy": controlled_entropy,
            "distribution": controlled_distribution,
            "scope": "current admitted candidates only",
        },
        "control": {
            "applied": bool(enabled and overloaded and adjusted_count),
            "adjusted_candidate_count": adjusted_count,
            "changed_winner": changed_winner,
            "lesioned": not bool(enabled),
            "maximum_adjustment": DEFAULT_ATTENTION_SCHEMA_CONTROL_LIMIT,
            "basis": (
                "protect direct-human and safety capture; under overload, compare "
                "the baseline priority map with goal, self, social, precision, and "
                "bottom-up capture counterfactuals"
            ),
            "authority": "selection_policy_only",
        },
        "baseline_distribution": baseline_distribution,
        "boundary": ATTENTION_SCHEMA_BOUNDARY,
    }
    return controlled, schema


def _project_next_attention_state(
    candidates: Sequence[Dict[str, object]],
    *,
    capacity: int,
    orientation: Dict[str, object],
    attention_schema_enabled: bool,
    orient_threshold: float,
) -> Dict[str, object]:
    projected: List[Dict[str, object]] = []
    oriented_fingerprint = _text(orientation.get("target_fingerprint"), 80)
    for raw in candidates:
        candidate = copy.deepcopy(raw)
        components = (
            candidate.get("score_components")
            if isinstance(candidate.get("score_components"), dict)
            else {}
        )
        if components:
            next_repeat = max(1, int(candidate.get("repeat_count") or 1) + 1)
            factor = max(0.18, 1.0 / (1.0 + 0.38 * max(0, next_repeat - 1)))
            if candidate.get("direct_human"):
                factor = max(factor, 0.90)
            if candidate.get("safety_critical"):
                factor = 1.0
            penalty = 0.0
            if (
                oriented_fingerprint
                and oriented_fingerprint == _text(candidate.get("fingerprint"), 80)
                and not candidate.get("direct_human")
                and not candidate.get("safety_critical")
                and float(candidate.get("change") or 0.0) < 70.0
            ):
                penalty = 18.0
            candidate["attention_score"] = round(
                _clamp(float(components.get("base") or 0.0) * factor - penalty),
                2,
            )
            candidate["repeat_count"] = next_repeat
        projected.append(candidate)
    controlled, _ = _apply_attention_schema_control(
        projected,
        capacity=capacity,
        enabled=attention_schema_enabled,
        orient_threshold=orient_threshold,
    )
    distribution, entropy = _attention_distribution(controlled)
    winner = controlled[0] if controlled else {}
    current_winner = candidates[0] if candidates else {}
    current_key = _attention_state_key(current_winner) if current_winner else ""
    persistence_probability = next(
        (
            float(item.get("probability") or 0.0)
            for item in distribution
            if item.get("state_key") == current_key
        ),
        0.0,
    )
    return {
        "target_id": winner.get("id"),
        "target_state_key": _attention_state_key(winner) if winner else "",
        "distribution": distribution,
        "normalized_entropy": entropy,
        "current_focus_persistence_probability": round(persistence_probability, 6),
        "condition_state_keys": sorted(_attention_state_key(item) for item in candidates),
        "condition": (
            "same semantic candidate set, no new direct-human or safety signal, "
            "and no unmodeled feature change"
        ),
    }


def _score_prior_attention_prediction(
    prior_frame: object,
    candidates: Sequence[Dict[str, object]],
    winner: Dict[str, object],
) -> Dict[str, object]:
    prior = prior_frame if isinstance(prior_frame, dict) else {}
    prior_schema = prior.get("attention_schema") if isinstance(prior.get("attention_schema"), dict) else {}
    prior_calibration = (
        prior_schema.get("calibration")
        if isinstance(prior_schema.get("calibration"), dict)
        else {}
    )
    count = int(prior_calibration.get("comparable_predictions") or 0)
    correct = int(prior_calibration.get("correct_predictions") or 0)
    mean_brier = float(prior_calibration.get("mean_brier") or 0.0)
    prediction = (
        prior_schema.get("next_state_prediction")
        if isinstance(prior_schema.get("next_state_prediction"), dict)
        else {}
    )
    expected_keys = sorted(
        _text(item, 40)
        for item in (prediction.get("condition_state_keys") or [])
        if _text(item, 40)
    )
    current_keys = sorted(_attention_state_key(item) for item in candidates)
    comparable = bool(
        prediction
        and winner
        and expected_keys
        and expected_keys == current_keys
        and not any(bool(item.get("dishabituated")) for item in candidates)
    )
    latest: Dict[str, object] = {
        "status": "not_scored_due_to_input_change",
        "comparable": False,
    }
    if comparable:
        distribution = [
            item
            for item in (prediction.get("distribution") or [])
            if isinstance(item, dict) and _text(item.get("state_key"), 40)
        ]
        actual_key = _attention_state_key(winner)
        keys = {
            _text(item.get("state_key"), 40)
            for item in distribution
            if _text(item.get("state_key"), 40)
        }
        keys.add(actual_key)
        probabilities = {
            _text(item.get("state_key"), 40): _clamp(
                float(item.get("probability") or 0.0),
                0.0,
                1.0,
                0.0,
            )
            for item in distribution
        }
        brier = sum(
            (probabilities.get(key, 0.0) - (1.0 if key == actual_key else 0.0)) ** 2
            for key in keys
        ) / max(1, len(keys))
        predicted_key = _text(prediction.get("target_state_key"), 40)
        was_correct = predicted_key == actual_key
        prior_total = mean_brier * count
        count += 1
        correct += int(was_correct)
        mean_brier = (prior_total + brier) / count
        latest = {
            "status": "scored",
            "comparable": True,
            "predicted_state_key": predicted_key,
            "actual_state_key": actual_key,
            "correct": was_correct,
            "brier": round(brier, 6),
        }
    return {
        "comparable_predictions": count,
        "correct_predictions": correct,
        "accuracy": round(correct / count, 6) if count else None,
        "mean_brier": round(mean_brier, 6) if count else None,
        "latest": latest,
        "probability_status": (
            "empirically_scored" if count else "uncalibrated_model_distribution"
        ),
    }


def _orienting_request(winner: Dict[str, object], threshold: float) -> Dict[str, object]:
    if not winner or _selection_score(winner) < threshold:
        return {}
    modality = str(winner.get("modality") or "world")
    requires_permission = bool(winner.get("requires_permission"))
    if requires_permission:
        action = "request_sensor_permission"
    elif winner.get("direct_human"):
        action = "attend_to_human_message"
    elif modality == "auditory":
        action = "listen_for_more_evidence"
    elif modality == "visual":
        action = "look_for_more_evidence"
    elif modality == "multisensory":
        action = "inspect_bound_event"
    elif modality in {"system", "interoceptive", "proprioceptive"}:
        action = "inspect_local_state"
    else:
        action = "sample_relevant_evidence"
    return {
        "target_id": winner.get("id"),
        "target_fingerprint": winner.get("fingerprint"),
        "subject": winner.get("subject"),
        "summary": winner.get("summary"),
        "recommended_action": action,
        "requires_permission": requires_permission,
        "requested_modalities": (
            [_text(item, 32) for item in winner.get("modalities") if _text(item, 32)]
            if isinstance(winner.get("modalities"), list)
            else [modality]
        ),
        "maximum_sample_seconds": 15,
        "authority": "proposal_only",
        "reason": (
            "Highest admitted selection score after bounded attention control; "
            "execution remains under Eve's existing capability and permission gates."
        ),
    }


def build_frame(
    events: Iterable[object],
    *,
    prior_frame: object = None,
    now: object = None,
    capacity: int = DEFAULT_CAPACITY,
    binding_window_seconds: int = DEFAULT_BINDING_WINDOW_SECONDS,
    recovery_seconds: int = DEFAULT_RECOVERY_SECONDS,
    orient_threshold: float = DEFAULT_ORIENT_THRESHOLD,
    quality_space_enabled: bool = True,
    attention_schema_enabled: bool = True,
    predictive_coding_enabled: bool = True,
) -> Dict[str, object]:
    timestamp = _now(now)
    bounded_capacity = max(1, min(8, int(capacity or DEFAULT_CAPACITY)))
    normalized: List[Dict[str, object]] = []
    seen_ids: set[str] = set()
    for raw in events:
        event = normalize_event(raw, now=timestamp)
        event_id = str(event.get("id") or "")
        if event_id in seen_ids:
            continue
        seen_ids.add(event_id)
        normalized.append(event)

    prior_habituation = _prior_dict(prior_frame, "habituation")
    prior_channels = _prior_dict(prior_frame, "channels")
    habituation = copy.deepcopy(prior_habituation)
    channels = copy.deepcopy(prior_channels)
    scored: List[Dict[str, object]] = []
    habituated_count = 0
    dishabituated_count = 0
    for event in normalized:
        repeat_count, factor, changed, memory = _habituation(
            event,
            prior_frame=prior_frame,
            timestamp=timestamp,
            recovery_seconds=max(1, int(recovery_seconds)),
            quality_space_enabled=bool(quality_space_enabled),
            predictive_coding_enabled=bool(predictive_coding_enabled),
        )
        penalty = _recent_orientation_penalty(event, prior_frame, timestamp)
        score, components = _event_score(event, factor, penalty)
        event["attention_score"] = score
        event["score_components"] = components
        event["repeat_count"] = repeat_count
        event["habituated"] = bool(repeat_count > 1 and factor < 0.95)
        event["dishabituated"] = changed
        event["disposition"] = "orient" if score >= orient_threshold else "monitor" if score >= 35 else "ignore"
        if event["habituated"]:
            habituated_count += 1
        if changed:
            dishabituated_count += 1
        habituation[str(event["fingerprint"])] = memory
        channels[str(memory["channel"])] = {
            "last_fingerprint": event["fingerprint"],
            "last_seen_at": timestamp,
            "last_features": copy.deepcopy(event.get("features") or {}),
            "predicted_features": copy.deepcopy(memory.get("predicted_features") or {}),
            "repeat_count": repeat_count,
        }
        scored.append(event)

    unbound, episodes = _bind_events(
        scored,
        binding_window_seconds=max(0, int(binding_window_seconds)),
    )
    coalesced_candidates, duplicate_candidates = _coalesce_candidates(
        [*unbound, *episodes]
    )
    baseline_candidates = sorted(
        coalesced_candidates,
        key=lambda item: (
            -float(item.get("attention_score") or 0),
            -float(item.get("precision") or 0),
            str(item.get("id") or ""),
        ),
    )
    candidates, attention_schema = _apply_attention_schema_control(
        baseline_candidates,
        capacity=bounded_capacity,
        enabled=bool(attention_schema_enabled),
        orient_threshold=float(orient_threshold),
    )
    working_set = [copy.deepcopy(item) for item in candidates[:bounded_capacity]]
    winner = copy.deepcopy(working_set[0]) if working_set else {}
    ignored = [
        {
            "id": item.get("id"),
            "source": item.get("source"),
            "modality": item.get("modality"),
            "reason": (
                "below_attention_gate"
                if item.get("disposition") == "ignore"
                else "working_set_capacity"
            ),
            "attention_score": item.get("attention_score"),
            "selection_score": item.get("selection_score"),
        }
        for item in candidates
        if item not in working_set
    ]
    ignored.extend(
        {
            "id": item.get("id"),
            "source": item.get("source"),
            "modality": item.get("modality"),
            "reason": "duplicate_current_state",
            "attention_score": item.get("attention_score"),
            "selection_score": item.get("selection_score", item.get("attention_score")),
        }
        for item in duplicate_candidates
    )
    orientation = _orienting_request(winner, float(orient_threshold))
    attention_schema["next_state_prediction"] = _project_next_attention_state(
        candidates,
        capacity=bounded_capacity,
        orientation=orientation,
        attention_schema_enabled=bool(attention_schema_enabled),
        orient_threshold=float(orient_threshold),
    )
    attention_schema["calibration"] = _score_prior_attention_prediction(
        prior_frame,
        candidates,
        winner,
    )
    entity_tracks = _entity_tracks(
        normalized,
        prior_frame=prior_frame,
        timestamp=timestamp,
    )
    recent_orientations = [
        copy.deepcopy(item)
        for item in ((prior_frame or {}).get("recent_orientations") or [])
        if isinstance(item, dict)
    ][-7:]
    if orientation:
        recent_orientations.append(
            {
                "fingerprint": orientation.get("target_fingerprint"),
                "oriented_at": timestamp,
            }
        )
    # Bound state growth and discard old fingerprints that were not observed in
    # this or the immediately prior frame.
    active_fingerprints = {
        str(item.get("fingerprint"))
        for item in normalized
        if item.get("fingerprint")
    }
    prior_active = {
        str(item.get("fingerprint"))
        for item in ((prior_frame or {}).get("observations") or [])
        if isinstance(item, dict) and item.get("fingerprint")
    }
    retained = active_fingerprints | prior_active
    habituation = {key: value for key, value in habituation.items() if key in retained}
    active_channels = {_channel_key(item) for item in normalized}
    channels = {key: value for key, value in channels.items() if key in active_channels}
    private_adapter_observed = any(bool(item.get("private_adapter_event")) for item in normalized)
    quality_comparisons = [
        item.get("quality_distance")
        for item in scored
        if isinstance(item.get("quality_distance"), dict)
        and item["quality_distance"].get("comparable")
    ]
    quality_distances = [
        float(item.get("rms_distance") or 0.0)
        for item in quality_comparisons
    ]
    prediction_errors = [
        item.get("prediction_error")
        for item in scored
        if isinstance(item.get("prediction_error"), dict)
        and item["prediction_error"].get("comparable")
    ]
    weighted_prediction_errors = [
        float(item.get("weighted_error") or 0.0)
        for item in prediction_errors
    ]
    return {
        "schema_version": FRAME_SCHEMA,
        "generated_at": timestamp,
        "status": "attending" if winner else "quiet",
        "observed_count": len(normalized),
        "modality_count": len({str(item.get("modality")) for item in normalized}),
        "admitted_count": len(working_set),
        "ignored_count": len(ignored),
        "habituated_count": habituated_count,
        "dishabituated_count": dishabituated_count,
        "bound_episode_count": sum(
            1 for item in candidates if item.get("modality") == "multisensory"
        ),
        "bound_episode_observed_count": len(episodes),
        "coalesced_duplicate_count": len(duplicate_candidates),
        "entity_track_count": len(entity_tracks),
        "capacity": bounded_capacity,
        "observations": normalized[:24],
        "working_set": working_set,
        "winner": winner,
        "alternatives": working_set[1:],
        "ignored": ignored[:24],
        "orienting_request": orientation,
        "entity_tracks": entity_tracks,
        "habituation": habituation,
        "channels": channels,
        "recent_orientations": recent_orientations[-8:],
        "attention_schema": attention_schema,
        "predictive_perception": {
            "schema_version": PREDICTIVE_PERCEPTION_SCHEMA,
            "enabled": bool(predictive_coding_enabled),
            "comparison_count": len(prediction_errors),
            "surprising_count": sum(
                1 for item in prediction_errors if item.get("surprising")
            ),
            "expected_change_suppressed_count": sum(
                1 for item in scored if item.get("predicted_change")
            ),
            "mean_weighted_error": (
                round(
                    sum(weighted_prediction_errors) / len(weighted_prediction_errors),
                    3,
                )
                if weighted_prediction_errors
                else None
            ),
            "error_threshold": DEFAULT_PREDICTION_ERROR_THRESHOLD,
            "forecast": "clipped_constant_velocity_numeric_and_persistent_categorical",
            "precision_weighted": True,
            "causal_role": "habituation, dishabituation, novelty, and attention",
            "boundary": PREDICTIVE_PERCEPTION_BOUNDARY,
        },
        "quality_space": {
            "schema_version": QUALITY_SPACE_SCHEMA,
            "enabled": bool(quality_space_enabled),
            "comparison_count": len(quality_comparisons),
            "mean_rms_distance": (
                round(sum(quality_distances) / len(quality_distances), 3)
                if quality_distances
                else None
            ),
            "change_threshold": DEFAULT_QUALITY_CHANGE_THRESHOLD,
            "representation": "normalized_sparse_features",
            "causal_role": "graded habituation and dishabituation",
        },
        "privacy": {
            "raw_audio_retained": False,
            "raw_images_retained": False,
            "raw_screen_retained": False,
            "default_persistence": "features_only",
            "private_device_features_observed": private_adapter_observed,
            "private_device_sensors_enabled": private_adapter_observed,
        },
        "boundary": BOUNDARY,
    }


def public_frame(frame: object) -> Dict[str, object]:
    """Return the bounded frame safe to persist or place in a workspace."""
    source = frame if isinstance(frame, dict) else {}
    allowed = {
        "schema_version",
        "generated_at",
        "status",
        "observed_count",
        "modality_count",
        "admitted_count",
        "ignored_count",
        "habituated_count",
        "dishabituated_count",
        "bound_episode_count",
        "bound_episode_observed_count",
        "coalesced_duplicate_count",
        "entity_track_count",
        "capacity",
        "observations",
        "working_set",
        "winner",
        "alternatives",
        "ignored",
        "orienting_request",
        "entity_tracks",
        "habituation",
        "channels",
        "recent_orientations",
        "attention_schema",
        "predictive_perception",
        "quality_space",
        "privacy",
        "boundary",
    }
    result = {key: copy.deepcopy(value) for key, value in source.items() if key in allowed}
    # Defensive serialization catches accidental non-JSON device objects before
    # they can reach the event spine.
    return json.loads(json.dumps(result, ensure_ascii=True))
