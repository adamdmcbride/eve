#!/usr/bin/env python3
"""Pure model-lane topology contract shared by cognition and supervision.

Logical lanes describe cognitive functions.  Profiles describe resident
llama.cpp processes.  Keeping that distinction in one dependency-light module
prevents the reply router, watchdog, launchd lifecycle, control app, and
independent deadman from silently disagreeing about which processes should be
alive.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse

import eve_profile


MODEL_LANE_TOPOLOGY_FIVE_ENDPOINT = "five_endpoint"
MODEL_LANE_TOPOLOGY_THREE_SUBSTRATE = "three_substrate"
MODEL_LANE_TOPOLOGY_MODES = {
    MODEL_LANE_TOPOLOGY_FIVE_ENDPOINT,
    MODEL_LANE_TOPOLOGY_THREE_SUBSTRATE,
}

# Logical order follows the reply council.  Physical profile order preserves
# the long-standing port/service order used by operator tooling.
LOGICAL_LANE_ORDER: Tuple[str, ...] = (
    "fast",
    "observer",
    "planner",
    "deep",
    "relationship",
)
PROFILE_ORDER: Tuple[str, ...] = (
    "fast",
    "deep",
    "observer",
    "planner",
    "relationship",
)

IDENTITY_PROFILE_MAP = {lane: lane for lane in LOGICAL_LANE_ORDER}
THREE_SUBSTRATE_PROFILE_MAP = {
    "fast": "fast",
    "relationship": "fast",
    "observer": "observer",
    "planner": "observer",
    "deep": "deep",
}

PROFILE_DEFAULTS: Dict[str, Dict[str, object]] = {
    "fast": {
        "host": "http://127.0.0.1:8080",
        "alias": "eve-fast",
        "launch_label": eve_profile.service_label("llama-cpp"),
    },
    "deep": {
        "host": "http://127.0.0.1:8081",
        "alias": "eve-deep",
        "launch_label": eve_profile.service_label("llama-cpp-deep"),
    },
    "observer": {
        "host": "http://127.0.0.1:8082",
        "alias": "eve-observer",
        "launch_label": eve_profile.service_label("llama-cpp-observer"),
    },
    "planner": {
        "host": "http://127.0.0.1:8083",
        "alias": "eve-planner",
        "launch_label": eve_profile.service_label("llama-cpp-planner"),
    },
    "relationship": {
        "host": "http://127.0.0.1:8084",
        "alias": "eve-relationship",
        "launch_label": eve_profile.service_label("llama-cpp-relationship"),
    },
}

PROFILE_ROUTE_FIELDS: Dict[str, Tuple[str, ...]] = {
    "fast": ("fast_model", "model"),
    "deep": ("deep_model", "model"),
    "observer": ("mind_stream_observer_model",),
    "planner": ("mind_stream_planner_model",),
    "relationship": ("mind_stream_relationship_model", "reply_stream_listener_model"),
}


def normalize_model_name(value: object) -> str:
    return str(value or "").strip()


def normalize_topology_mode(value: object) -> str:
    normalized = " ".join(str(value or "").strip().lower().replace("-", "_").split())
    aliases = {
        "five": MODEL_LANE_TOPOLOGY_FIVE_ENDPOINT,
        "five_endpoints": MODEL_LANE_TOPOLOGY_FIVE_ENDPOINT,
        "five_endpoint": MODEL_LANE_TOPOLOGY_FIVE_ENDPOINT,
        "three": MODEL_LANE_TOPOLOGY_THREE_SUBSTRATE,
        "three_substrates": MODEL_LANE_TOPOLOGY_THREE_SUBSTRATE,
        "three_substrate": MODEL_LANE_TOPOLOGY_THREE_SUBSTRATE,
    }
    return aliases.get(normalized, MODEL_LANE_TOPOLOGY_FIVE_ENDPOINT)


def configured_topology_mode(config: Mapping[str, object]) -> str:
    transient = config.get("_model_lane_topology_mode")
    configured = config.get("model_lane_topology_mode")
    return normalize_topology_mode(transient if transient not in {None, ""} else configured)


def topology_profile_map(
    config: Mapping[str, object],
    *,
    mode: Optional[str] = None,
) -> Dict[str, str]:
    selected = normalize_topology_mode(mode or configured_topology_mode(config))
    if selected == MODEL_LANE_TOPOLOGY_FIVE_ENDPOINT:
        return dict(IDENTITY_PROFILE_MAP)
    result = dict(THREE_SUBSTRATE_PROFILE_MAP)
    configured = config.get("model_lane_three_substrate_profile_map")
    if isinstance(configured, Mapping):
        for lane in LOGICAL_LANE_ORDER:
            candidate = " ".join(str(configured.get(lane) or "").strip().lower().split())
            if candidate in PROFILE_ORDER:
                result[lane] = candidate
    return result


def profile_config_field(profile: str, suffix: str) -> str:
    normalized = str(profile or "fast").strip().lower() or "fast"
    if normalized == "fast":
        return f"llama_cpp_{suffix}"
    return f"{normalized}_llama_cpp_{suffix}"


def profile_alias(config: Mapping[str, object], profile: str) -> str:
    normalized = str(profile or "fast").strip().lower() or "fast"
    defaults = PROFILE_DEFAULTS[normalized]
    candidates = [normalize_model_name(config.get(profile_config_field(normalized, "model_alias")))]
    candidates.extend(
        normalize_model_name(config.get(field))
        for field in PROFILE_ROUTE_FIELDS.get(normalized, ())
    )
    candidates.append(str(defaults["alias"]))
    return next((candidate for candidate in candidates if candidate), str(defaults["alias"]))


def profile_host(config: Mapping[str, object], profile: str) -> str:
    normalized = str(profile or "fast").strip().lower() or "fast"
    defaults = PROFILE_DEFAULTS[normalized]
    return str(
        config.get(profile_config_field(normalized, "host")) or defaults["host"]
    ).strip().rstrip("/")


def profile_port(config: Mapping[str, object], profile: str) -> int:
    host = profile_host(config, profile)
    parsed = urlparse(host if "://" in host else f"http://{host}")
    if parsed.port:
        return int(parsed.port)
    return 443 if parsed.scheme == "https" else 80


def profile_launch_label(profile: str) -> str:
    normalized = str(profile or "fast").strip().lower() or "fast"
    return str(PROFILE_DEFAULTS[normalized]["launch_label"])


def active_substrate_profiles(
    config: Mapping[str, object],
    *,
    mode: Optional[str] = None,
) -> List[str]:
    mapping = topology_profile_map(config, mode=mode)
    used = set(mapping.values())
    return [profile for profile in PROFILE_ORDER if profile in used]


def inactive_substrate_profiles(
    config: Mapping[str, object],
    *,
    mode: Optional[str] = None,
) -> List[str]:
    active = set(active_substrate_profiles(config, mode=mode))
    return [profile for profile in PROFILE_ORDER if profile not in active]


def profile_spec(
    config: Mapping[str, object],
    profile: str,
    *,
    mode: Optional[str] = None,
) -> Dict[str, object]:
    selected = normalize_topology_mode(mode or configured_topology_mode(config))
    mapping = topology_profile_map(config, mode=selected)
    normalized = str(profile or "fast").strip().lower() or "fast"
    return {
        "profile": normalized,
        "alias": profile_alias(config, normalized),
        "host": profile_host(config, normalized),
        "port": profile_port(config, normalized),
        "launch_label": profile_launch_label(normalized),
        "active": normalized in set(mapping.values()),
        "logical_lanes": [
            lane for lane in LOGICAL_LANE_ORDER if mapping.get(lane) == normalized
        ],
    }


def all_profile_specs(
    config: Mapping[str, object],
    *,
    mode: Optional[str] = None,
) -> List[Dict[str, object]]:
    return [profile_spec(config, profile, mode=mode) for profile in PROFILE_ORDER]


def active_substrate_specs(
    config: Mapping[str, object],
    *,
    mode: Optional[str] = None,
) -> List[Dict[str, object]]:
    active = set(active_substrate_profiles(config, mode=mode))
    return [
        spec
        for spec in all_profile_specs(config, mode=mode)
        if str(spec["profile"]) in active
    ]


def effective_substrate_profile_for_model(
    config: Mapping[str, object],
    model: object,
    *,
    mode: Optional[str] = None,
) -> Optional[str]:
    normalized_model = normalize_model_name(model)
    if not normalized_model:
        return None
    mapping = topology_profile_map(config, mode=mode)
    # Match nominal lane aliases first so planner/relationship resolve through
    # their shared substrate when the three-process topology is active.
    for lane in LOGICAL_LANE_ORDER:
        if normalized_model == profile_alias(config, lane):
            return mapping.get(lane, lane)
    for profile in active_substrate_profiles(config, mode=mode):
        if normalized_model == profile_alias(config, profile):
            return profile
    return None


def effective_substrate_model(
    config: Mapping[str, object],
    model: object,
    *,
    mode: Optional[str] = None,
) -> str:
    normalized_model = normalize_model_name(model)
    profile = effective_substrate_profile_for_model(config, normalized_model, mode=mode)
    return profile_alias(config, profile) if profile else normalized_model


def logical_routes(
    config: Mapping[str, object],
    *,
    mode: Optional[str] = None,
) -> List[Dict[str, object]]:
    selected = normalize_topology_mode(mode or configured_topology_mode(config))
    mapping = topology_profile_map(config, mode=selected)
    routes: List[Dict[str, object]] = []
    for lane in LOGICAL_LANE_ORDER:
        substrate_profile = mapping.get(lane, lane)
        routes.append(
            {
                "logical_lane": lane,
                "topology_mode": selected,
                "nominal_profile": lane,
                "nominal_model": profile_alias(config, lane),
                "substrate_profile": substrate_profile,
                "substrate_model": profile_alias(config, substrate_profile),
                "substrate_host": profile_host(config, substrate_profile),
                "substrate_port": profile_port(config, substrate_profile),
                "substrate_launch_label": profile_launch_label(substrate_profile),
                "shared_lanes": [
                    candidate
                    for candidate in LOGICAL_LANE_ORDER
                    if mapping.get(candidate) == substrate_profile
                ],
            }
        )
    return routes


def topology_snapshot(
    config: Mapping[str, object],
    *,
    mode: Optional[str] = None,
) -> Dict[str, object]:
    selected = normalize_topology_mode(mode or configured_topology_mode(config))
    routes = logical_routes(config, mode=selected)
    active = active_substrate_specs(config, mode=selected)
    inactive = [
        spec for spec in all_profile_specs(config, mode=selected) if not bool(spec["active"])
    ]
    errors: List[str] = []
    expected_substrate_count = (
        3 if selected == MODEL_LANE_TOPOLOGY_THREE_SUBSTRATE else 5
    )
    if len(active) != expected_substrate_count:
        errors.append(
            f"{selected} requires {expected_substrate_count} active substrates, found {len(active)}"
        )
    for field in ("alias", "host", "launch_label"):
        values = [str(spec.get(field) or "") for spec in active]
        if any(not value for value in values):
            errors.append(f"active substrate {field} is missing")
        if len(values) != len(set(values)):
            errors.append(f"active substrate {field} values are not unique")
    if len(routes) != len(LOGICAL_LANE_ORDER):
        errors.append("logical route count is not five")
    return {
        "schema_id": "eve.model_lane_service_topology.v1",
        "mode": selected,
        "valid": not errors,
        "validation_errors": errors,
        "logical_lane_count": len(routes),
        "substrate_count": len(active),
        "routes": routes,
        "active_substrates": active,
        "inactive_substrates": inactive,
    }


def load_config(path: Optional[Path] = None) -> Dict[str, object]:
    candidate = path
    if candidate is None:
        environment_path = str(os.environ.get("EVE_MODEL_TOPOLOGY_CONFIG_PATH") or "").strip()
        if environment_path:
            candidate = Path(environment_path).expanduser()
        else:
            runtime = Path.home() / ".eve_runtime" / ".eve" / "config.json"
            local = Path(__file__).resolve().parent / ".eve" / "config.json"
            candidate = runtime if runtime.is_file() else local
    try:
        payload = json.loads(Path(candidate).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def shell_assignment(name: str, values: Sequence[object]) -> str:
    return f"{name}=({' '.join(shlex.quote(str(value)) for value in values)})"


def shell_contract(snapshot: Mapping[str, object]) -> str:
    active = [dict(item) for item in snapshot.get("active_substrates") or []]
    inactive = [dict(item) for item in snapshot.get("inactive_substrates") or []]
    all_specs = active + inactive
    lines = [
        f"EVE_MODEL_TOPOLOGY_MODE={shlex.quote(str(snapshot.get('mode') or ''))}",
        f"EVE_MODEL_TOPOLOGY_VALID={shlex.quote('1' if snapshot.get('valid') else '0')}",
        shell_assignment("MODEL_LANE_ACTIVE_LABELS", [item.get("launch_label") for item in active]),
        shell_assignment("MODEL_LANE_INACTIVE_LABELS", [item.get("launch_label") for item in inactive]),
        shell_assignment("MODEL_LANE_ALL_LABELS", [item.get("launch_label") for item in all_specs]),
        shell_assignment("EVE_ACTIVE_MODEL_PROFILES", [item.get("profile") for item in active]),
        shell_assignment("EVE_ACTIVE_MODEL_URLS", [item.get("host") for item in active]),
        shell_assignment("EVE_ACTIVE_MODEL_ALIASES", [item.get("alias") for item in active]),
        shell_assignment("EVE_ALL_MODEL_PORTS", [item.get("port") for item in all_specs]),
    ]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect Eve logical-lane and resident-process topology.")
    parser.add_argument("command", nargs="?", default="snapshot", choices={
        "snapshot",
        "validate",
        "shell",
        "mode",
        "active-profiles",
        "active-labels",
        "inactive-labels",
        "active-urls",
        "all-ports",
    })
    parser.add_argument("--config", type=Path)
    parser.add_argument("--mode", choices=sorted(MODEL_LANE_TOPOLOGY_MODES))
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    snapshot = topology_snapshot(config, mode=args.mode)
    active = [dict(item) for item in snapshot["active_substrates"]]
    inactive = [dict(item) for item in snapshot["inactive_substrates"]]
    if args.command == "snapshot":
        print(json.dumps(snapshot, indent=2, sort_keys=True))
    elif args.command == "validate":
        print(json.dumps({
            "mode": snapshot["mode"],
            "valid": snapshot["valid"],
            "validation_errors": snapshot["validation_errors"],
        }, indent=2, sort_keys=True))
    elif args.command == "shell":
        print(shell_contract(snapshot))
    elif args.command == "mode":
        print(snapshot["mode"])
    elif args.command == "active-profiles":
        print("\n".join(str(item["profile"]) for item in active))
    elif args.command == "active-labels":
        print("\n".join(str(item["launch_label"]) for item in active))
    elif args.command == "inactive-labels":
        print("\n".join(str(item["launch_label"]) for item in inactive))
    elif args.command == "active-urls":
        print("\n".join(str(item["host"]) for item in active))
    elif args.command == "all-ports":
        print("\n".join(str(item["port"]) for item in [*active, *inactive]))
    return 0 if snapshot["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
