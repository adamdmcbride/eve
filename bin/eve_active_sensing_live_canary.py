#!/usr/bin/env python3
"""Run one bounded lived active-sensing service-health episode."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Callable, Dict, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_active_sensing_adapters as adapters  # noqa: E402


SCHEMA = "eve.lived_active_sensing_canary.v1"
BOUNDARY = (
    "One read-only perception-action-consequence episode over Eve's own "
    "service health; not subjective experience or proof of consciousness."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(value: object) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def run_canary(
    *,
    action_runner: Callable[[], Mapping[str, object]],
    snapshot_collector: Callable[[], Mapping[str, object]],
    now: Callable[[], str] = _now,
) -> Dict[str, object]:
    """Open, act, re-observe, and close without persisting action authority."""
    opened = adapters.open_service_health_episode(now=now())
    raw_action = dict(action_runner())
    raw_action.setdefault("action", adapters.SERVICE_HEALTH_ACTION)
    attached = adapters.attach_service_health_execution(opened, raw_action, now=now())
    action = attached.get("action") if isinstance(attached.get("action"), Mapping) else {}
    if attached.get("status") != "action_verified":
        return {
            "schema_version": SCHEMA,
            "status": "action_unverified",
            "action": adapters.SERVICE_HEALTH_ACTION,
            "execution_id_sha256": _hash(action.get("execution_id")),
            "tree_status": raw_action.get("execution_tree_status") or raw_action.get("tree_status"),
            "verification_ok": action.get("verification_ok") is True,
            "observation_collected": False,
            "observer_evidence_refreshed": False,
            "consequence_qualified": False,
            "information_gain": None,
            "service_state_mutated": False,
            "action_authority": False,
            "consciousness_proven": False,
            "boundary": BOUNDARY,
        }
    snapshot = dict(snapshot_collector())
    closed = adapters.close_service_health_episode(attached, snapshot)
    observation = (
        closed.get("observation")
        if isinstance(closed.get("observation"), Mapping)
        else {}
    )
    return {
        "schema_version": SCHEMA,
        "status": str(closed.get("status") or "observation_unqualified"),
        "action": adapters.SERVICE_HEALTH_ACTION,
        "execution_id_sha256": _hash(action.get("execution_id")),
        "tree_status": raw_action.get("execution_tree_status") or raw_action.get("tree_status"),
        "verification_ok": action.get("verification_ok") is True,
        "observation_collected": True,
        "observer_evidence_refreshed": True,
        "observation_id_sha256": _hash(observation.get("id")),
        "observation_source": observation.get("source"),
        "observation_outcome": observation.get("outcome"),
        "observation_after_verified_action": bool(
            observation.get("caused_by_execution_id") == action.get("execution_id")
        ),
        "prior_uncertainty": closed.get("prior_uncertainty"),
        "posterior_uncertainty": closed.get("posterior_uncertainty"),
        "information_gain": closed.get("information_gain"),
        "belief_revision": bool(closed.get("belief_revision")),
        "beliefs_before": dict(closed.get("beliefs_before") or {}),
        "beliefs_after": dict(closed.get("beliefs_after") or {}),
        "consequence_qualified": bool(closed.get("consequence_qualified")),
        "content_persisted": False,
        "raw_media_retained": False,
        "service_state_mutated": False,
        "action_authority": False,
        "consciousness_proven": False,
        "subjective_experience_inferred": False,
        "boundary": BOUNDARY,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    import eve  # noqa: WPS433

    config = eve.load_config()
    report = run_canary(
        action_runner=lambda: eve.run_operational_action_tree(
            adapters.SERVICE_HEALTH_ACTION,
            config,
            source="developmental_active_sensing_canary",
            persist=False,
        ),
        # The action itself collected one snapshot.  Collect a second snapshot
        # after its verified receipt so execution cannot be mistaken for the
        # intended consequence observation.
        snapshot_collector=eve.refresh_system_snapshot_via_observer,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0 if report.get("consequence_qualified") else 1


if __name__ == "__main__":
    raise SystemExit(main())
