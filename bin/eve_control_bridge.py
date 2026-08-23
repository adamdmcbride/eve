#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse


DEFAULT_RUNTIME_URL = os.environ.get("EVE_CONTROL_RUNTIME_URL", "http://127.0.0.1:8765")
DEFAULT_HOME_URL = os.environ.get(
    "EVE_HOME_ASSISTANT_URL",
    os.environ.get("EVE_HOME_URL", os.environ.get("EVE_URL", "http://127.0.0.1:8123")),
)
DEFAULT_RUNTIME_HOSTS = {"127.0.0.1", "localhost", "::1"}
DEFAULT_RUNTIME_PORT = 8765
DEFAULT_HOME_PORT = 8123


def default_control_project_root() -> Path:
    raw_root = os.environ.get("EVE_CONTROL_PROJECT_ROOT")
    if raw_root:
        return Path(raw_root).expanduser()
    return Path(__file__).resolve().parents[2] / "EveHomeNative"


def request_json(
    runtime_url: str,
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
    timeout: float = 10,
) -> Dict[str, Any]:
    url = runtime_url.rstrip("/") + path
    body: Optional[bytes] = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=body, method=method.upper(), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"{method.upper()} {path} failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"{method.upper()} {path} could not reach headless Eve Control runtime-core at {runtime_url}: {exc}"
        ) from exc

    try:
        decoded = json.loads(data.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{method.upper()} {path} returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError(f"{method.upper()} {path} returned JSON {type(decoded).__name__}, expected object")
    return decoded


def should_autostart_runtime(runtime_url: str) -> bool:
    parsed = urlparse(runtime_url)
    scheme = parsed.scheme or "http"
    return (
        scheme == "http"
        and (parsed.hostname or "") in DEFAULT_RUNTIME_HOSTS
        and (parsed.port or 80) == DEFAULT_RUNTIME_PORT
    )


def should_autostart_home(home_url: str) -> bool:
    parsed = urlparse(home_url)
    scheme = parsed.scheme or "http"
    return (
        scheme == "http"
        and (parsed.hostname or "") in DEFAULT_RUNTIME_HOSTS
        and (parsed.port or 80) == DEFAULT_HOME_PORT
    )


def home_reachable(home_url: str, timeout: float = 5) -> bool:
    request = urllib.request.Request(home_url.rstrip("/") + "/", method="GET", headers={"Accept": "text/html"})
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            return True
    except urllib.error.HTTPError as exc:
        return 200 <= exc.code < 500
    except urllib.error.URLError:
        return False


def run_home_backend(control_project_root: Path, action: str, timeout: float, check: bool = True) -> subprocess.CompletedProcess[str]:
    script = control_project_root / "bin" / "run_eve.sh"
    if not script.exists():
        raise RuntimeError(f"Eve Home lifecycle script is missing: {script}")
    return subprocess.run(
        [str(script), action],
        cwd=str(control_project_root),
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def start_headless_runtime(control_project_root: Path, timeout: float) -> None:
    script = control_project_root / "bin" / "run_eve_core.sh"
    if not script.exists():
        raise RuntimeError(f"headless runtime start script is missing: {script}")

    try:
        subprocess.run(
            [str(script), "start"],
            cwd=str(control_project_root),
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"headless runtime start timed out after {timeout:g}s") from exc
    except subprocess.CalledProcessError as exc:
        detail = "\n".join(part.strip() for part in (exc.stdout, exc.stderr) if part and part.strip())
        if detail:
            raise RuntimeError(f"headless runtime start failed:\n{detail}") from exc
        raise RuntimeError(f"headless runtime start failed with exit code {exc.returncode}") from exc


def ensure_runtime_available(runtime_url: str, control_project_root: Path, timeout: float) -> None:
    if not should_autostart_runtime(runtime_url):
        return

    try:
        request_json(runtime_url, "GET", "/v1/health", timeout=min(timeout, 2))
        return
    except RuntimeError:
        pass

    start_headless_runtime(control_project_root, timeout=max(timeout, 20))
    request_json(runtime_url, "GET", "/v1/health", timeout=min(timeout, 5))


def ensure_home_available(home_url: str, control_project_root: Path, timeout: float) -> None:
    if not should_autostart_home(home_url):
        return
    if home_reachable(home_url, timeout=min(timeout, 3)):
        return

    try:
        run_home_backend(control_project_root, "start", timeout=max(timeout, 150))
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Eve Home start timed out after {max(timeout, 150):g}s") from exc
    except subprocess.CalledProcessError as exc:
        detail = "\n".join(part.strip() for part in (exc.stdout, exc.stderr) if part and part.strip())
        if detail:
            raise RuntimeError(f"Eve Home start failed:\n{detail}") from exc
        raise RuntimeError(f"Eve Home start failed with exit code {exc.returncode}") from exc

    if not home_reachable(home_url, timeout=min(timeout, 5)):
        raise RuntimeError(f"Eve Home start completed, but {home_url} is not reachable")


def home_status_payload(home_url: str, control_project_root: Path, timeout: float) -> Dict[str, Any]:
    try:
        result = run_home_backend(control_project_root, "status", timeout=timeout, check=False)
        raw_status = (result.stdout or result.stderr or "").strip()
        lifecycle_ok = result.returncode == 0
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Eve Home status timed out after {timeout:g}s") from exc

    return {
        "app": "eve-control-bridge",
        "backend": "eve_home",
        "homeURL": home_url,
        "lifecycleStatus": raw_status or "unknown",
        "lifecycleOK": lifecycle_ok,
        "reachable": home_reachable(home_url, timeout=min(timeout, 5)),
        "consumerAppRequired": False,
    }


def run_home_action(action: str, home_url: str, control_project_root: Path, timeout: float) -> Dict[str, Any]:
    if action == "status":
        return home_status_payload(home_url, control_project_root, timeout)

    try:
        result = run_home_backend(control_project_root, action, timeout=max(timeout, 150))
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Eve Home {action} timed out after {max(timeout, 150):g}s") from exc
    except subprocess.CalledProcessError as exc:
        detail = "\n".join(part.strip() for part in (exc.stdout, exc.stderr) if part and part.strip())
        if detail:
            raise RuntimeError(f"Eve Home {action} failed:\n{detail}") from exc
        raise RuntimeError(f"Eve Home {action} failed with exit code {exc.returncode}") from exc

    payload = home_status_payload(home_url, control_project_root, timeout)
    payload["action"] = action
    payload["message"] = (result.stdout or result.stderr or "").strip()
    return payload


def parse_service_data(raw: str) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"service data is not valid JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise argparse.ArgumentTypeError("service data must be a JSON object")
    return decoded


def build_control_payload(
    entity_ids: Iterable[str],
    service: str,
    domain: str = "",
    service_data: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    cleaned_entity_ids = [entity_id.strip() for entity_id in entity_ids if entity_id.strip()]
    if not cleaned_entity_ids:
        raise ValueError("at least one --entity-id is required")
    payload: Dict[str, Any] = {
        "entityIds": cleaned_entity_ids,
        "service": service.strip(),
    }
    if domain.strip():
        payload["domain"] = domain.strip()
    if service_data:
        payload["serviceData"] = service_data
    if dry_run:
        payload["dryRun"] = True
    return payload


def print_json(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def print_status(payload: Dict[str, Any]) -> None:
    capabilities = ", ".join(payload.get("capabilities") or [])
    print(f"Eve Control headless runtime: {payload.get('status', 'unknown')} ({payload.get('app', 'unknown')})")
    if payload.get("surfaceRole"):
        print(f"surface: {payload['surfaceRole']}")
    if "consumerAppRequired" in payload:
        print(f"consumer app required: {'yes' if payload.get('consumerAppRequired') else 'no'}")
    if payload.get("projectRoot"):
        print(f"project: {payload['projectRoot']}")
    if capabilities:
        print(f"capabilities: {capabilities}")


def print_snapshot(payload: Dict[str, Any], limit: int, controllable_only: bool) -> None:
    entities = payload.get("entities") or []
    if controllable_only:
        entities = [entity for entity in entities if entity.get("controllable")]

    print(
        "Eve Home snapshot: "
        f"{payload.get('entityCount', 0)} entities, "
        f"{payload.get('controllableEntityCount', 0)} controllable, "
        f"route={payload.get('route', 'unknown')}"
    )
    for entity in entities[: max(0, limit)]:
        controls = ", ".join(entity.get("controlServices") or [])
        suffix = f" controls=[{controls}]" if controls else ""
        print(
            f"- {entity.get('entityId', 'unknown')} "
            f"state={entity.get('state', 'unknown')} "
            f"name={entity.get('name', '')}{suffix}"
        )


def filtered_snapshot_payload(payload: Dict[str, Any], controllable_only: bool) -> Dict[str, Any]:
    if not controllable_only:
        return payload
    filtered = dict(payload)
    entities = payload.get("entities") or []
    filtered_entities = [entity for entity in entities if isinstance(entity, dict) and entity.get("controllable")]
    filtered["entities"] = filtered_entities
    filtered["returnedEntityCount"] = len(filtered_entities)
    return filtered


def print_control(payload: Dict[str, Any]) -> None:
    entity_ids = ", ".join(payload.get("entityIds") or [])
    print(
        "Eve Home control "
        f"{payload.get('status', 'unknown')}: "
        f"{payload.get('domain', '?')}.{payload.get('service', '?')} -> {entity_ids}"
    )
    print(f"route: {payload.get('route', 'unknown')}")


def print_home(payload: Dict[str, Any]) -> None:
    print(
        "Eve Home backend "
        f"{payload.get('lifecycleStatus', 'unknown')}; "
        f"reachable={'yes' if payload.get('reachable') else 'no'}; "
        f"consumer app required={'yes' if payload.get('consumerAppRequired') else 'no'}"
    )
    if payload.get("message"):
        print(payload["message"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bridge Eve to the headless local Eve Control runtime-core / Eve Home API without opening the consumer app."
    )
    parser.add_argument(
        "--runtime-url",
        default=DEFAULT_RUNTIME_URL,
        help="Eve Control runtime-core URL. Defaults to EVE_CONTROL_RUNTIME_URL or http://127.0.0.1:8765.",
    )
    parser.add_argument(
        "--control-project-root",
        type=Path,
        default=default_control_project_root(),
        help="EveHomeNative project root used to start runtime-core headlessly when the default local runtime is down.",
    )
    parser.add_argument(
        "--no-ensure-runtime",
        action="store_true",
        help="Do not auto-start the default local runtime-core service before sending the request.",
    )
    parser.add_argument(
        "--home-url",
        default=DEFAULT_HOME_URL,
        help="Eve Home/Home Assistant URL. Defaults to EVE_HOME_ASSISTANT_URL, EVE_HOME_URL, EVE_URL, or http://127.0.0.1:8123.",
    )
    parser.add_argument(
        "--no-ensure-home",
        action="store_true",
        help="Do not auto-start the default local Eve Home backend before snapshot or real control.",
    )
    parser.add_argument("--timeout", type=float, default=10, help="HTTP timeout in seconds.")
    parser.add_argument("--json", action="store_true", help="Print raw JSON.")

    subparsers = parser.add_subparsers(dest="command", required=True)
    status = subparsers.add_parser("status", help="Check the Eve Control runtime-core health endpoint.")
    status.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Print raw JSON.")

    home = subparsers.add_parser("home", help="Manage the headless Eve Home backend without opening the consumer app.")
    home.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Print raw JSON.")
    home.add_argument("action", choices=["status", "start", "stop", "restart"], help="Backend lifecycle action.")

    snapshot = subparsers.add_parser("snapshot", help="Read Eve Home state and controllable entities.")
    snapshot.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Print raw JSON.")
    snapshot.add_argument("--limit", type=int, default=20, help="Number of entities to print in text mode.")
    snapshot.add_argument("--controllable-only", action="store_true", help="Only print entities with control services.")

    control = subparsers.add_parser("control", help="Send an allowlisted Eve Home control command.")
    control.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Print raw JSON.")
    control.add_argument("--entity-id", action="append", required=True, help="Target entity id. Can be repeated.")
    control.add_argument("--domain", default="", help="Optional domain override; inferred from entity id by default.")
    control.add_argument("--service", required=True, help="Allowlisted service, such as turn_on or set_value.")
    control.add_argument("--service-data-json", type=parse_service_data, default={}, help="Optional JSON object service data.")
    control.add_argument("--dry-run", action="store_true", help="Validate the command shape without sending it.")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command != "home" and not args.no_ensure_runtime:
            ensure_runtime_available(args.runtime_url, args.control_project_root, args.timeout)

        if args.command == "status":
            payload = request_json(args.runtime_url, "GET", "/v1/health", timeout=args.timeout)
            if args.json:
                print_json(payload)
            else:
                print_status(payload)
            return 0

        if args.command == "snapshot":
            if not args.no_ensure_home:
                ensure_home_available(args.home_url, args.control_project_root, args.timeout)
            payload = request_json(args.runtime_url, "GET", "/v1/home/snapshot", timeout=args.timeout)
            payload = filtered_snapshot_payload(payload, controllable_only=args.controllable_only)
            if args.json:
                print_json(payload)
            else:
                print_snapshot(payload, limit=args.limit, controllable_only=args.controllable_only)
            return 0

        if args.command == "control":
            payload = build_control_payload(
                entity_ids=args.entity_id,
                service=args.service,
                domain=args.domain,
                service_data=args.service_data_json,
                dry_run=args.dry_run,
            )
            if not args.dry_run and not args.no_ensure_home:
                ensure_home_available(args.home_url, args.control_project_root, args.timeout)
            response = request_json(args.runtime_url, "POST", "/v1/home/control", payload=payload, timeout=args.timeout)
            if args.json:
                print_json(response)
            else:
                print_control(response)
            return 0

        if args.command == "home":
            payload = run_home_action(args.action, args.home_url, args.control_project_root, args.timeout)
            if args.json:
                print_json(payload)
            else:
                print_home(payload)
            return 0
    except (RuntimeError, ValueError) as exc:
        print(f"eve_control_bridge: {exc}", file=sys.stderr)
        return 1

    parser.error(f"unsupported command {args.command!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
