#!/usr/bin/env python3
"""Reconcile OpenClaw's local model aliases with Eve's active topology.

OpenClaw is an action/body organ, not a second lane router, but its optional
local-model catalog must not point at intentionally inactive rollback ports.
This adapter preserves five logical provider names while mapping each one to
the actual resident substrate model and endpoint selected by Eve.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_model_topology
import eve_store


PROVIDER_IDS = {
    "fast": "llamacpp",
    "deep": "llamacpp-deep",
    "observer": "llamacpp-observer",
    "planner": "llamacpp-planner",
    "relationship": "llamacpp-relationship",
}
DISPLAY_NAMES = {
    "fast": "Eve Fast",
    "deep": "Eve Deep",
    "observer": "Eve Observer",
    "planner": "Eve Planner",
    "relationship": "Eve Relationship",
}


def provider_context_size(config: Mapping[str, object], profile: str) -> int:
    field = eve_model_topology.profile_config_field(profile, "ctx_size")
    defaults = {"fast": 16384, "deep": 32768, "observer": 16384}
    try:
        return max(2048, int(config.get(field) or defaults.get(profile, 8192)))
    except (TypeError, ValueError):
        return defaults.get(profile, 8192)


def default_provider(
    *,
    host: str,
    model_id: str,
    name: str,
    context_window: int,
    max_tokens: int,
) -> Dict[str, object]:
    return {
        "baseUrl": host.rstrip("/") + "/v1",
        "apiKey": "llamacpp",
        "auth": "api-key",
        "api": "openai-responses",
        # Cold local inference can legitimately exceed OpenClaw's implicit
        # stream watchdog. Keep a bounded five-minute local timeout so a slow
        # first pass is not mislabeled as a dead provider.
        "timeoutSeconds": 300,
        "request": {"allowPrivateNetwork": True},
        "models": [
            {
                "id": model_id,
                "name": name,
                "reasoning": False,
                "input": ["text"],
                "cost": {
                    "input": 0,
                    "output": 0,
                    "cacheRead": 0,
                    "cacheWrite": 0,
                },
                "contextWindow": context_window,
                "contextTokens": max(1024, context_window - 768),
                "maxTokens": max_tokens,
                "compat": {
                    "supportsStore": False,
                    "supportsPromptCacheKey": False,
                    "supportsDeveloperRole": False,
                    "supportsReasoningEffort": False,
                    "supportsStrictMode": False,
                },
            }
        ],
    }


def rewrite_exact_model_refs(value: object, replacements: Mapping[str, str]) -> object:
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [rewrite_exact_model_refs(item, replacements) for item in value]
    if isinstance(value, dict):
        return {
            key: rewrite_exact_model_refs(item, replacements)
            for key, item in value.items()
        }
    return value


def reconcile_openclaw_topology_config(
    eve_config: Mapping[str, object],
    openclaw_config: Mapping[str, object],
) -> Tuple[Dict[str, object], Dict[str, object]]:
    snapshot = eve_model_topology.topology_snapshot(eve_config)
    if not snapshot.get("valid"):
        raise ValueError(
            "invalid Eve topology: " + "; ".join(snapshot.get("validation_errors") or [])
        )
    updated = copy.deepcopy(dict(openclaw_config))
    models_root = updated.setdefault("models", {})
    if not isinstance(models_root, dict):
        models_root = {}
        updated["models"] = models_root
    models_root["mode"] = "replace"
    providers = models_root.setdefault("providers", {})
    if not isinstance(providers, dict):
        providers = {}
        models_root["providers"] = providers

    agents = updated.setdefault("agents", {})
    if not isinstance(agents, dict):
        agents = {}
        updated["agents"] = agents
    defaults = agents.setdefault("defaults", {})
    if not isinstance(defaults, dict):
        defaults = {}
        agents["defaults"] = defaults
    aliases = defaults.get("models")
    aliases = dict(aliases) if isinstance(aliases, dict) else {}

    routes = {
        str(item.get("logical_lane")): dict(item)
        for item in snapshot.get("routes") or []
        if isinstance(item, dict)
    }
    replacements: Dict[str, str] = {}
    report_routes = []
    for lane in eve_model_topology.LOGICAL_LANE_ORDER:
        route = routes[lane]
        provider_id = PROVIDER_IDS[lane]
        substrate_profile = str(route.get("substrate_profile") or lane)
        substrate_model = str(route.get("substrate_model") or "")
        substrate_host = str(route.get("substrate_host") or "").rstrip("/")
        old_provider = providers.get(provider_id)
        old_provider = copy.deepcopy(old_provider) if isinstance(old_provider, dict) else {}
        old_models = old_provider.get("models") if isinstance(old_provider, dict) else []
        old_model = (
            copy.deepcopy(old_models[0])
            if isinstance(old_models, list) and old_models and isinstance(old_models[0], dict)
            else {}
        )
        context_window = provider_context_size(eve_config, substrate_profile)
        max_tokens = 1024 if substrate_profile == "deep" else 512
        shared = lane != substrate_profile
        display_name = DISPLAY_NAMES[lane]
        provider_name = (
            f"{display_name} via {DISPLAY_NAMES.get(substrate_profile, substrate_profile.title())} llama.cpp"
            if shared
            else f"{display_name} llama.cpp"
        )
        provider = default_provider(
            host=substrate_host,
            model_id=substrate_model,
            name=provider_name,
            context_window=context_window,
            max_tokens=max_tokens,
        )
        for key, value in old_provider.items():
            if key not in {"baseUrl", "models", "timeoutSeconds"}:
                provider[key] = value
        try:
            provider["timeoutSeconds"] = max(
                300,
                int(old_provider.get("timeoutSeconds") or 300),
            )
        except (TypeError, ValueError):
            provider["timeoutSeconds"] = 300
        model_entry = dict(provider["models"][0])
        for key, value in old_model.items():
            if key not in {"id", "name", "contextWindow", "contextTokens", "maxTokens"}:
                model_entry[key] = value
        model_entry.update(
            {
                "id": substrate_model,
                "name": provider_name,
                "contextWindow": context_window,
                "contextTokens": max(1024, context_window - 768),
                "maxTokens": max_tokens,
            }
        )
        provider["models"] = [model_entry]
        providers[provider_id] = provider

        old_alias_keys = [key for key in aliases if key.startswith(provider_id + "/")]
        for old_key in old_alias_keys:
            aliases.pop(old_key, None)
            replacements[old_key] = f"{provider_id}/{substrate_model}"
        model_ref = f"{provider_id}/{substrate_model}"
        aliases[model_ref] = {
            "alias": display_name + (f" (shared {substrate_profile})" if shared else "")
        }
        report_routes.append(
            {
                "logical_lane": lane,
                "provider": provider_id,
                "model_ref": model_ref,
                "substrate_profile": substrate_profile,
                "substrate_model": substrate_model,
                "base_url": provider["baseUrl"],
                "shared": shared,
            }
        )

    defaults["models"] = aliases
    updated["agents"] = rewrite_exact_model_refs(agents, replacements)
    # Eve's full OpenClaw profile is larger than the observer substrate's
    # verified prompt budget. Do not preserve or generate a utility route until
    # a distinct lean utility prompt has its own successful fit canary.
    updated["agents"]["defaults"].pop("utilityModel", None)
    return updated, {
        "schema_id": "eve.openclaw_model_topology_sync.v1",
        "topology_mode": snapshot.get("mode"),
        "logical_lane_count": snapshot.get("logical_lane_count"),
        "substrate_count": snapshot.get("substrate_count"),
        "routes": report_routes,
        "replaced_model_refs": replacements,
    }


def default_openclaw_config_path(profile: str) -> Path:
    state_dir = str(os.environ.get("OPENCLAW_STATE_DIR") or "").strip()
    if state_dir:
        return Path(state_dir).expanduser() / "openclaw.json"
    return Path.home() / f".openclaw-{profile}" / "openclaw.json"


def run_openclaw(profile: str, *args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["openclaw", "--profile", profile, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Map OpenClaw's five logical local providers to Eve's active substrates."
    )
    parser.add_argument("--profile", default=os.environ.get("OPENCLAW_EVE_PROFILE", "eve-repair"))
    parser.add_argument("--config", type=Path)
    parser.add_argument("--eve-config", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-validate", action="store_true")
    parser.add_argument("--restart-gateway", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = (args.config or default_openclaw_config_path(args.profile)).expanduser()
    eve_config = eve_model_topology.load_config(args.eve_config)
    try:
        current = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": f"cannot read OpenClaw config: {exc}"}))
        return 2
    if not isinstance(current, dict):
        print(json.dumps({"ok": False, "error": "OpenClaw config is not an object"}))
        return 2
    try:
        updated, report = reconcile_openclaw_topology_config(eve_config, current)
    except (TypeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    changed = updated != current
    report["changed"] = changed
    report["config_path"] = str(config_path)
    if args.dry_run:
        report["ok"] = True
        report["dry_run"] = True
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    eve_store.write_json_dict(config_path, updated, indent=2, sort_keys=False)
    if not args.no_validate:
        validation = run_openclaw(args.profile, "config", "validate")
        if validation.returncode != 0:
            eve_store.write_json_dict(config_path, current, indent=2, sort_keys=False)
            report.update(
                {
                    "ok": False,
                    "rolled_back": True,
                    "validation_error": " ".join(
                        (validation.stderr or validation.stdout or "validation failed").split()
                    )[:1000],
                }
            )
            print(json.dumps(report, indent=2, sort_keys=True))
            return 3
        report["validated"] = True
    if args.restart_gateway and changed:
        restarted = run_openclaw(args.profile, "gateway", "restart", timeout=120)
        if restarted.returncode != 0:
            report.update(
                {
                    "ok": False,
                    "gateway_restart_error": " ".join(
                        (restarted.stderr or restarted.stdout or "restart failed").split()
                    )[:1000],
                }
            )
            print(json.dumps(report, indent=2, sort_keys=True))
            return 4
        report["gateway_restarted"] = True
    report["ok"] = True
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
