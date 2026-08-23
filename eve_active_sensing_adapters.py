"""Typed adapters from Eve actions to causally qualified observations.

An action tree can prove that a tool ran.  It cannot, by itself, prove the
state of the world the tool was intended to inspect.  This module keeps those
claims separate for the first low-risk active-sensing route: Eve's own service
health.  The action receipt is attached first; a newly collected structured
snapshot is then classified and linked to the exact execution id.

Only compact feature indicators cross this boundary.  Process lists, log
tails, paths, prompts, and other raw/private payloads do not.
"""

from __future__ import annotations

import hashlib
import json
from typing import Dict, Mapping, Optional

import eve_active_sensing


SERVICE_HEALTH_ACTION = "service_health_check"
SERVICE_HEALTH_TARGET = "eve-core-service-health.v1"
SERVICE_HEALTH_MODEL_SOURCE = "eve.service_health_observation_model.v1"
SERVICE_HEALTH_OBSERVATION_SOURCE = "system_observer.service_health_features.v1"

# These likelihoods are deliberately fixed before the action.  An
# inconclusive structured snapshot has equal likelihood under both hypotheses,
# so it cannot manufacture information gain.
SERVICE_HEALTH_OBSERVATION_MODEL = {
    "operational_receipt": {"operational": 0.90, "degraded": 0.05},
    "degraded_receipt": {"operational": 0.05, "degraded": 0.90},
    "inconclusive": {"operational": 0.05, "degraded": 0.05},
}


def _text(value: object, limit: int = 180) -> str:
    return " ".join(str(value or "").split())[:limit]


def _explicit_bool(value: object) -> Optional[bool]:
    if value is True or value is False:
        return bool(value)
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    return None


def open_service_health_episode(
    *,
    beliefs_before: Optional[Mapping[str, object]] = None,
    now: object = None,
) -> Dict[str, object]:
    """Open a read-only service-health inquiry with a precommitted model."""
    return eve_active_sensing.open_episode(
        {
            "target_id": "eve-runtime",
            "target_fingerprint": SERVICE_HEALTH_TARGET,
            "subject": "Eve runtime service health",
            "summary": "Whether Eve's daemon, watchdog, resident models, and required model probes are operational is unresolved.",
            "recommended_action": SERVICE_HEALTH_ACTION,
            "requested_modalities": ["system_state"],
            "requires_permission": False,
            "authority": "proposal_only",
        },
        question="Are Eve's required runtime services and resident model probes operational now?",
        expected_observation="A new structured system snapshot collected after the probe should show operational, degraded, or incomplete required-service features.",
        beliefs_before=beliefs_before or {"operational": 0.5, "degraded": 0.5},
        observation_model=SERVICE_HEALTH_OBSERVATION_MODEL,
        observation_model_source=SERVICE_HEALTH_MODEL_SOURCE,
        executable_action=SERVICE_HEALTH_ACTION,
        now=now,
    )


def attach_service_health_execution(
    episode: Mapping[str, object],
    action_result: Mapping[str, object],
    *,
    now: object = None,
) -> Dict[str, object]:
    """Normalize an operational action-tree receipt without inferring health."""
    tree_status = _text(
        action_result.get("execution_tree_status") or action_result.get("tree_status"),
        40,
    ).upper()
    verification = _explicit_bool(
        action_result.get("execution_verification_ok")
        if "execution_verification_ok" in action_result
        else action_result.get("verification_ok")
    )
    status = _text(action_result.get("status"), 40).lower()
    if not status and tree_status == "SUCCESS" and verification is True:
        status = "completed"
    normalized = {
        "action": _text(action_result.get("action"), 100),
        "execution_id": _text(action_result.get("execution_id"), 120),
        "status": status,
        "executed": _explicit_bool(action_result.get("executed")),
        "execution_verification_ok": verification,
        "summary": _text(
            action_result.get("execution_summary") or action_result.get("summary"),
            260,
        ),
        "updated_at": action_result.get("updated_at") or action_result.get("created_at"),
    }
    return eve_active_sensing.attach_action_result(episode, normalized, now=now)


def _service_state(payload: object) -> Optional[bool]:
    if not isinstance(payload, Mapping):
        return None
    state = _text(payload.get("state") or payload.get("launchctl_state"), 40).lower()
    loaded = _explicit_bool(payload.get("loaded"))
    if state in {"active", "running"} and loaded is not False:
        return True
    if state in {"inactive", "failed", "missing", "not running", "stopped"} or loaded is False:
        return False
    return None


def _probe_state(payload: object) -> Optional[bool]:
    if not isinstance(payload, Mapping):
        return None
    return _explicit_bool(payload.get("ok"))


def classify_service_health_snapshot(snapshot: Mapping[str, object]) -> Dict[str, object]:
    """Classify only explicit required-service features from one snapshot."""
    if not isinstance(snapshot, Mapping):
        snapshot = {}
    services = snapshot.get("eve_services") if isinstance(snapshot.get("eve_services"), Mapping) else {}
    model_status = snapshot.get("model_status") if isinstance(snapshot.get("model_status"), Mapping) else {}
    residency = model_status.get("residency") if isinstance(model_status.get("residency"), Mapping) else {}
    probes = model_status.get("probes") if isinstance(model_status.get("probes"), Mapping) else {}
    fast_name = _text(model_status.get("preferred_fast_model"), 80)
    deep_name = _text(model_status.get("preferred_deep_model"), 80)

    indicators = {
        "daemon_active": _service_state(services.get("daemon")),
        "watchdog_active": _service_state(services.get("model_watchdog")),
        "both_models_resident": _explicit_bool(residency.get("both_preferred_loaded")),
        "fast_probe_ok": _probe_state(probes.get(fast_name)) if fast_name else None,
        "deep_probe_ok": _probe_state(probes.get(deep_name)) if deep_name else None,
    }
    missing = sorted(name for name, value in indicators.items() if value is None)
    failed = sorted(name for name, value in indicators.items() if value is False)
    passed = sorted(name for name, value in indicators.items() if value is True)
    if missing:
        outcome = "inconclusive"
        summary = (
            f"Structured service-health observation was incomplete: {len(passed)} required indicator(s) passed, "
            f"{len(failed)} failed, and {len(missing)} were missing."
        )
    elif failed:
        outcome = "degraded_receipt"
        summary = (
            f"Structured service-health observation found {len(failed)} failed required indicator(s) "
            f"and {len(passed)} passing indicator(s)."
        )
    else:
        outcome = "operational_receipt"
        summary = f"All {len(passed)} required structured service-health indicators passed."
    return {
        "outcome": outcome,
        "summary": summary,
        "observed_at": _text(snapshot.get("timestamp"), 80),
        "indicators": indicators,
        "passed_indicators": passed,
        "failed_indicators": failed,
        "missing_indicators": missing,
        "feature_only": True,
    }


def service_health_observation(
    verified_episode: Mapping[str, object],
    snapshot: Mapping[str, object],
) -> Dict[str, object]:
    """Bind a later feature snapshot to the exact verified execution id."""
    action = verified_episode.get("action") if isinstance(verified_episode.get("action"), Mapping) else {}
    execution_id = _text(action.get("execution_id"), 120)
    classified = classify_service_health_snapshot(snapshot)
    observed_at = _text(classified.get("observed_at"), 80)
    evidence_id = "service-health-observation-" + hashlib.sha256(
        json.dumps(
            {
                "execution_id": execution_id,
                "observed_at": observed_at,
                "outcome": classified["outcome"],
                "indicators": classified["indicators"],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:20]
    return {
        "id": evidence_id,
        "observed_at": observed_at,
        "source": SERVICE_HEALTH_OBSERVATION_SOURCE,
        "caused_by_execution_id": execution_id,
        "summary": classified["summary"],
        "outcome": classified["outcome"],
        "target_fingerprint": SERVICE_HEALTH_TARGET,
        "evidence_kind": "typed_service_health_features",
    }


def close_service_health_episode(
    verified_episode: Mapping[str, object],
    snapshot: Mapping[str, object],
    *,
    minimum_information_gain: float = 1.0,
) -> Dict[str, object]:
    """Close from a newly collected snapshot; never from the action's ``ok``."""
    observation = service_health_observation(verified_episode, snapshot)
    return eve_active_sensing.close_with_observation(
        verified_episode,
        observation,
        minimum_information_gain=minimum_information_gain,
    )

