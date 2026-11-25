"""Privacy-minimized read-only feature sampling for Eve prediction canaries."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
import shutil
import subprocess
from typing import Dict, Mapping, Sequence


SCHEMA = "eve.lived_feature_snapshot.v1"
CONTRACT_SCHEMA = "eve.lived_feature_transfer_contract.v1"
BOUNDARY = (
    "Read-only aggregate machine and homeostasis numbers; no process names, "
    "user content, raw media, action authority, or consciousness claim."
)

PRESSURE_IDS = (
    "resource_safety",
    "coherence",
    "social_continuity",
    "unfinished_commitments",
    "continuity_drift",
    "uncertainty_debt",
    "surprise_load",
    "trust_repair",
)
MODEL_IDS = {
    "eve-fast": "eve_fast",
    "eve-deep": "eve_deep",
    "eve-observer": "eve_observer",
}


def _timestamp(value: object = None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    text = str(value)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _bounded(value: object, limit: float) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    return round(max(0.0, min(limit, number)), 6)


def _record(
    value: object,
    *,
    limit: float,
    precision: float,
    source: str,
    source_observed_at: object,
) -> Dict[str, object] | None:
    bounded = _bounded(value, limit)
    if bounded is None:
        return None
    return {
        "value": bounded,
        "limit": float(limit),
        "source_precision": float(precision),
        "source": source,
        "source_observed_at": _timestamp(source_observed_at),
    }


def extract_feature_snapshot(
    system_snapshot: Mapping[str, object],
    homeostasis: Mapping[str, object],
    *,
    load_average: Sequence[object],
    cpu_count: object,
    disk_used_percent: object,
    aggregate_cpu_percent: object = None,
    aggregate_memory_percent: object = None,
    observed_at: object = None,
) -> Dict[str, object]:
    """Extract only the fixed numeric contract from already bounded sources."""
    try:
        cores = max(1.0, float(cpu_count))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("cpu_count must be positive and finite") from exc
    if not math.isfinite(cores):
        raise ValueError("cpu_count must be positive and finite")
    loads = list(load_average)
    if len(loads) != 3:
        raise ValueError("load_average must contain one, five, and fifteen minute values")
    timestamp = _timestamp(observed_at)
    features: Dict[str, Dict[str, object]] = {}
    for label, value in zip(("1m", "5m", "15m"), loads):
        numeric = _bounded(value, cores * 100.0)
        if numeric is not None:
            record = _record(
                numeric * 100.0 / cores,
                limit=100.0,
                precision=90.0,
                source="os_load_average",
                source_observed_at=timestamp,
            )
            if record:
                features[f"system.load_{label}_per_core_percent"] = record
            index_record = _record(
                numeric * 100.0 / cores,
                limit=400.0,
                precision=90.0,
                source="os_load_average",
                source_observed_at=timestamp,
            )
            if index_record:
                features[f"system.load_{label}_per_core_index"] = index_record
    disk_record = _record(
        disk_used_percent,
        limit=100.0,
        precision=100.0,
        source="filesystem_capacity",
        source_observed_at=timestamp,
    )
    if disk_record:
        features["system.disk_used_percent"] = disk_record

    cpu_record = _record(
        aggregate_cpu_percent,
        limit=100.0,
        precision=85.0,
        source="aggregate_process_cpu",
        source_observed_at=timestamp,
    )
    if cpu_record:
        features["system.aggregate_cpu_per_core_percent"] = cpu_record
    memory_record = _record(
        aggregate_memory_percent,
        limit=100.0,
        precision=75.0,
        source="aggregate_process_memory",
        source_observed_at=timestamp,
    )
    if memory_record:
        features["system.aggregate_process_memory_percent"] = memory_record

    battery = system_snapshot.get("battery") if isinstance(system_snapshot.get("battery"), Mapping) else {}
    snapshot_time = system_snapshot.get("timestamp")
    battery_record = (
        _record(
            battery.get("percent"),
            limit=100.0,
            precision=100.0,
            source="system_snapshot_battery",
            source_observed_at=snapshot_time,
        )
        if snapshot_time
        else None
    )
    if battery_record:
        features["system.battery_percent"] = battery_record

    model_status = (
        system_snapshot.get("model_status")
        if isinstance(system_snapshot.get("model_status"), Mapping)
        else {}
    )
    probes = model_status.get("probes") if isinstance(model_status.get("probes"), Mapping) else {}
    for model_id, safe_id in MODEL_IDS.items():
        probe = probes.get(model_id) if isinstance(probes.get(model_id), Mapping) else {}
        record = (
            _record(
                probe.get("wall_ms"),
                limit=60_000.0,
                precision=95.0,
                source="model_probe_latency",
                source_observed_at=snapshot_time,
            )
            if snapshot_time
            else None
        )
        if record:
            features[f"model.{safe_id}_latency_ms"] = record

    pressure_records = (
        homeostasis.get("pressures")
        if isinstance(homeostasis.get("pressures"), list)
        else []
    )
    levels = {
        str(item.get("id") or ""): item.get("level")
        for item in pressure_records
        if isinstance(item, Mapping) and str(item.get("id") or "") in PRESSURE_IDS
    }
    homeostasis_time = homeostasis.get("updated_at")
    for pressure_id in PRESSURE_IDS:
        record = (
            _record(
                levels.get(pressure_id),
                limit=100.0,
                precision=95.0,
                source="homeostasis_pressure",
                source_observed_at=homeostasis_time,
            )
            if homeostasis_time
            else None
        )
        if record:
            features[f"homeostasis.{pressure_id}"] = record

    return {
        "schema_version": SCHEMA,
        "observed_at": timestamp,
        "features": features,
        "feature_count": len(features),
        "read_only": True,
        "raw_media_retained": False,
        "user_content_retained": False,
        "process_identity_retained": False,
        "action_authority": False,
        "boundary": BOUNDARY,
    }


def _aggregate_ps_percent(column: str, *, divisor: float = 1.0) -> float | None:
    """Read one numeric process aggregate without requesting process identity."""
    if column not in {"%cpu", "%mem"}:
        raise ValueError("unsupported aggregate process column")
    try:
        completed = subprocess.run(
            ["ps", "-A", "-o", f"{column}="],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    total = 0.0
    for line in completed.stdout.splitlines():
        try:
            value = float(line.strip())
        except ValueError:
            continue
        if math.isfinite(value) and value >= 0:
            total += value
    return total / max(1.0, divisor)


def collect_local_snapshot(
    system_snapshot: Mapping[str, object],
    homeostasis: Mapping[str, object],
    *,
    observed_at: object = None,
) -> Dict[str, object]:
    usage = shutil.disk_usage("/")
    disk_used = usage.used * 100.0 / usage.total if usage.total else 0.0
    cores = float(os.cpu_count() or 1)
    return extract_feature_snapshot(
        system_snapshot,
        homeostasis,
        load_average=os.getloadavg(),
        cpu_count=cores,
        disk_used_percent=disk_used,
        aggregate_cpu_percent=_aggregate_ps_percent("%cpu", divisor=cores),
        aggregate_memory_percent=_aggregate_ps_percent("%mem"),
        observed_at=observed_at,
    )


def validate_contract(payload: Mapping[str, object]) -> Dict[str, object]:
    if not isinstance(payload, Mapping) or payload.get("schema_version") != CONTRACT_SCHEMA:
        raise ValueError("lived feature contract schema mismatch")
    claimed = str(payload.get("contract_digest") or "")
    material = {key: value for key, value in payload.items() if key != "contract_digest"}
    actual = hashlib.sha256(
        json.dumps(material, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    if not claimed or claimed != actual:
        raise ValueError("lived feature contract digest mismatch")
    if payload.get("read_only") is not True or payload.get("induced_perturbation") is not False:
        raise ValueError("lived feature contract must remain read-only and unperturbed")
    return dict(payload)
