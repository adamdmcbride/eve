#!/usr/bin/env python3
"""Run Eve's real resident-model topology promotion canary.

This is deliberately an operational canary, not a prompt benchmark.  It
changes the live topology, verifies physical residency and logical routing,
loads shared substrates concurrently, removes one shared substrate, requires
watchdog recovery, checks the independent deadman, and rolls back on failure.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple
from urllib import error, request


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_model_topology
import eve_store


SOURCE_CONFIG_PATH = ROOT / ".eve" / "config.json"
RUNTIME_DIR = Path.home() / ".eve_runtime"
RUNTIME_CONFIG_PATH = RUNTIME_DIR / ".eve" / "config.json"
RUNTIME_EVE_PATH = RUNTIME_DIR / "eve.py"
RUNTIME_WATCHDOG_PATH = RUNTIME_DIR / "bin" / "eve_model_watchdog.py"
RUNTIME_DEADMAN_PATH = RUNTIME_DIR / "bin" / "eve_deadman.sh"
RUNTIME_OPENCLAW_TOPOLOGY_SYNC_PATH = (
    RUNTIME_DIR / "bin" / "eve_openclaw_topology_sync.py"
)
SOURCE_ARTIFACT_DIR = ROOT / ".eve" / "model_topology_canaries"
RUNTIME_ARTIFACT_DIR = RUNTIME_DIR / ".eve" / "model_topology_canaries"
LOCK_PATH = ROOT / ".eve" / "model_topology_canary.lock"


class CanaryFailure(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def progress(message: str) -> None:
    print(f"[{utc_now()}] {message}", file=sys.stderr, flush=True)


def compact_text(value: object, limit: int = 3000) -> str:
    return " ".join(str(value or "").split())[:limit]


def run_command(
    command: Sequence[str],
    *,
    cwd: Path = ROOT,
    timeout: int = 300,
) -> Dict[str, object]:
    started = time.monotonic()
    try:
        result = subprocess.run(
            list(command),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "command": list(command),
            "returncode": result.returncode,
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
            "stdout": (result.stdout or "")[-12000:],
            "stderr": (result.stderr or "")[-6000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": list(command),
            "returncode": 124,
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
            "stdout": str(exc.stdout or "")[-12000:],
            "stderr": f"timeout after {timeout}s: {exc.stderr or ''}"[-6000:],
        }


def require_command(result: Mapping[str, object], label: str) -> None:
    if int(result.get("returncode") or 0) != 0:
        raise CanaryFailure(
            f"{label} failed rc={result.get('returncode')}: "
            f"{compact_text(result.get('stderr') or result.get('stdout'), 800)}"
        )


def fetch_json(url: str, timeout: int = 5) -> Dict[str, object]:
    req = request.Request(url, headers={"Accept": "application/json"}, method="GET")
    with request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def endpoint_probe(host: object, timeout: int = 4) -> Dict[str, object]:
    normalized = str(host or "").rstrip("/")
    started = time.monotonic()
    try:
        payload = fetch_json(normalized + "/v1/models", timeout=timeout)
        models = payload.get("data") if isinstance(payload.get("data"), list) else []
        return {
            "host": normalized,
            "ok": True,
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
            "models": [
                str(item.get("id") or "")
                for item in models
                if isinstance(item, dict) and item.get("id")
            ],
        }
    except Exception as exc:
        return {
            "host": normalized,
            "ok": False,
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
            "error": compact_text(exc, 500),
        }


def process_for_port(port: int) -> Dict[str, object]:
    lsof = run_command(
        ["lsof", "-nP", f"-iTCP:{int(port)}", "-sTCP:LISTEN", "-t"],
        timeout=10,
    )
    pid_text = next(
        (line.strip() for line in str(lsof.get("stdout") or "").splitlines() if line.strip()),
        "",
    )
    if not pid_text.isdigit():
        return {"port": int(port), "pid": None, "rss_kib": 0, "running": False}
    ps = run_command(
        ["ps", "-p", pid_text, "-o", "rss=", "-o", "command="],
        timeout=10,
    )
    first_line = next(
        (line.strip() for line in str(ps.get("stdout") or "").splitlines() if line.strip()),
        "",
    )
    rss_text, _, command = first_line.partition(" ")
    try:
        rss_kib = int(rss_text)
    except ValueError:
        rss_kib = 0
    physical_footprint = physical_footprint_for_pid(int(pid_text))
    return {
        "port": int(port),
        "pid": int(pid_text),
        "rss_kib": rss_kib,
        "rss_gib": round(rss_kib / 1024 / 1024, 3),
        **physical_footprint,
        "command": command.strip()[:1200],
        "running": True,
    }


def physical_footprint_for_pid(pid: int) -> Dict[str, object]:
    """Return macOS physical-footprint accounting for one process when available.

    RSS includes clean file-backed model pages and changes substantially as macOS
    pages an idle model in or out.  ``phys_footprint`` is the kernel's process
    pressure accounting and is the more appropriate live comparison for two
    freshly restarted topologies.  RSS remains recorded as supporting evidence
    and as a portability fallback.
    """

    footprint_path = Path("/usr/bin/footprint")
    if not footprint_path.exists():
        return {
            "physical_footprint_bytes": 0,
            "physical_footprint_gib": 0.0,
            "physical_footprint_available": False,
        }
    temp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="eve-model-footprint-", suffix=".json", delete=False
        ) as handle:
            temp_path = Path(handle.name)
        result = run_command(
            [
                str(footprint_path),
                "-p",
                str(int(pid)),
                "-j",
                str(temp_path),
                "--noCategories",
            ],
            timeout=30,
        )
        if int(result.get("returncode") or 0) != 0 or not temp_path.exists():
            return {
                "physical_footprint_bytes": 0,
                "physical_footprint_gib": 0.0,
                "physical_footprint_available": False,
                "physical_footprint_error": compact_text(
                    result.get("stderr") or result.get("stdout"), 500
                ),
            }
        payload = json.loads(temp_path.read_text(encoding="utf-8"))
        processes = payload.get("processes") if isinstance(payload, dict) else []
        matching = next(
            (
                item
                for item in processes or []
                if isinstance(item, dict) and int(item.get("pid") or 0) == int(pid)
            ),
            {},
        )
        auxiliary = matching.get("auxiliary") if isinstance(matching, dict) else {}
        footprint_bytes = int(
            (auxiliary.get("phys_footprint") if isinstance(auxiliary, dict) else 0)
            or matching.get("footprint")
            or payload.get("total footprint")
            or 0
        )
        return {
            "physical_footprint_bytes": footprint_bytes,
            "physical_footprint_gib": round(footprint_bytes / 1024 / 1024 / 1024, 3),
            "physical_footprint_available": footprint_bytes > 0,
        }
    except Exception as exc:
        return {
            "physical_footprint_bytes": 0,
            "physical_footprint_gib": 0.0,
            "physical_footprint_available": False,
            "physical_footprint_error": compact_text(exc, 500),
        }
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def capture_residency(config: Mapping[str, object]) -> Dict[str, object]:
    snapshot = eve_model_topology.topology_snapshot(config)
    profiles: List[Dict[str, object]] = []
    unique_pids = set()
    total_rss_kib = 0
    total_physical_footprint_bytes = 0
    footprint_complete = True
    for spec in eve_model_topology.all_profile_specs(config):
        process = process_for_port(int(spec.get("port") or 0))
        pid = process.get("pid")
        if isinstance(pid, int) and pid not in unique_pids:
            unique_pids.add(pid)
            total_rss_kib += int(process.get("rss_kib") or 0)
            total_physical_footprint_bytes += int(
                process.get("physical_footprint_bytes") or 0
            )
            footprint_complete = footprint_complete and bool(
                process.get("physical_footprint_available")
            )
        profiles.append({**spec, "endpoint": endpoint_probe(spec.get("host")), "process": process})
    return {
        "captured_at": utc_now(),
        "topology": snapshot,
        "profiles": profiles,
        "resident_process_count": len(unique_pids),
        "resident_pids": sorted(unique_pids),
        "total_rss_kib": total_rss_kib,
        "total_rss_gib": round(total_rss_kib / 1024 / 1024, 3),
        "total_physical_footprint_bytes": total_physical_footprint_bytes,
        "total_physical_footprint_gib": round(
            total_physical_footprint_bytes / 1024 / 1024 / 1024, 3
        ),
        "physical_footprint_complete": footprint_complete and bool(unique_pids),
    }


def capture_residency_window(
    config: Mapping[str, object],
    *,
    sample_count: int,
    sample_interval: float,
) -> Dict[str, object]:
    """Capture a small equal-age window and compare medians, not one RSS instant."""

    captures: List[Dict[str, object]] = []
    for index in range(max(1, int(sample_count))):
        captures.append(capture_residency(config))
        if index + 1 < max(1, int(sample_count)):
            time.sleep(max(0.0, float(sample_interval)))
    latest = dict(captures[-1])
    rss_samples = [float(item.get("total_rss_gib") or 0.0) for item in captures]
    footprint_samples = [
        float(item.get("total_physical_footprint_gib") or 0.0) for item in captures
    ]
    process_counts = [int(item.get("resident_process_count") or 0) for item in captures]
    latest["instantaneous_total_rss_gib"] = latest.get("total_rss_gib")
    latest["instantaneous_total_physical_footprint_gib"] = latest.get(
        "total_physical_footprint_gib"
    )
    latest["total_rss_gib"] = round(statistics.median(rss_samples), 3)
    latest["total_physical_footprint_gib"] = round(
        statistics.median(footprint_samples), 3
    )
    latest["resident_process_count_stable"] = len(set(process_counts)) == 1
    latest["measurement_window"] = {
        "sample_count": len(captures),
        "sample_interval_seconds": float(sample_interval),
        "process_counts": process_counts,
        "rss_gib_samples": rss_samples,
        "physical_footprint_gib_samples": footprint_samples,
        "rss_gib_median": latest["total_rss_gib"],
        "physical_footprint_gib_median": latest[
            "total_physical_footprint_gib"
        ],
    }
    return latest


def topology_ready(config: Mapping[str, object]) -> Tuple[bool, Dict[str, object]]:
    snapshot = eve_model_topology.topology_snapshot(config)
    active = []
    inactive = []
    for spec in snapshot.get("active_substrates") or []:
        if isinstance(spec, dict):
            active.append(endpoint_probe(spec.get("host")))
    for spec in snapshot.get("inactive_substrates") or []:
        if isinstance(spec, dict):
            inactive.append(endpoint_probe(spec.get("host")))
    ready = (
        bool(snapshot.get("valid"))
        and all(item.get("ok") for item in active)
        and all(not item.get("ok") for item in inactive)
    )
    return ready, {"snapshot": snapshot, "active": active, "inactive": inactive}


def wait_for_topology(config: Mapping[str, object], timeout: int = 240) -> Dict[str, object]:
    deadline = time.monotonic() + timeout
    latest: Dict[str, object] = {}
    while time.monotonic() < deadline:
        ready, latest = topology_ready(config)
        if ready:
            return latest
        time.sleep(2)
    raise CanaryFailure(
        "model topology did not converge: " + compact_text(json.dumps(latest, sort_keys=True), 1200)
    )


def parse_last_json(text: object) -> Optional[Dict[str, object]]:
    for line in reversed(str(text or "").splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def routed_private_probe(name: str, prompt: str, lanes: str, timeout: int) -> Dict[str, object]:
    command = [
        sys.executable,
        str(RUNTIME_EVE_PATH),
        "chat",
        prompt,
        "--private-audit",
        "--private-audit-routed-primary",
        "--private-audit-force-lanes",
        lanes,
        "--private-audit-attribution-json",
        "--max-tokens",
        "180",
    ]
    result = run_command(command, cwd=RUNTIME_DIR, timeout=timeout)
    payload = parse_last_json(result.get("stdout"))
    route = payload.get("route") if isinstance(payload, dict) and isinstance(payload.get("route"), dict) else {}
    topology = route.get("model_topology") if isinstance(route.get("model_topology"), dict) else {}
    response = str(payload.get("response") or "") if isinstance(payload, dict) else ""
    ok = bool(
        int(result.get("returncode") or 0) == 0
        and payload
        and response.strip()
        and topology.get("mode") == eve_model_topology.MODEL_LANE_TOPOLOGY_THREE_SUBSTRATE
        and int(route.get("stream_error_count") or 0) == 0
        and route.get("stream_reply_used") is True
    )
    return {
        "name": name,
        "lanes": lanes.split(","),
        "ok": ok,
        "returncode": result.get("returncode"),
        "duration_ms": result.get("duration_ms"),
        "response_chars": len(response),
        "response_excerpt": compact_text(response, 800),
        "topology_mode": topology.get("mode"),
        "substrate_count": topology.get("substrate_count"),
        "active_lanes": route.get("active_lanes"),
        "stream_routes": route.get("stream_routes"),
        "stream_error_count": route.get("stream_error_count"),
        "stderr": compact_text(result.get("stderr"), 1000),
    }


def concurrency_probe(timeout: int) -> Dict[str, object]:
    cases = [
        (
            "all_logical_faculties",
            "Analyze whether sharing physical model substrates can preserve distinct logical cognitive functions. Give one risk, one verification, and one rollback condition.",
            "fast,observer,planner,deep,relationship",
        ),
        (
            "observer_planner_shared",
            "A service reports success while verification is false. Separate observation from the next responsible action.",
            "observer,planner",
        ),
        (
            "fast_relationship_shared",
            "Respond briefly but with continuity: explain why a fast answer can still preserve trust without pretending certainty.",
            "fast,relationship",
        ),
    ]
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(cases)) as executor:
        futures = [
            executor.submit(routed_private_probe, name, prompt, lanes, timeout)
            for name, prompt, lanes in cases
        ]
        results = [future.result(timeout=timeout + 30) for future in futures]
    return {
        "ok": all(item.get("ok") for item in results),
        "duration_ms": round((time.monotonic() - started) * 1000, 3),
        "results": results,
    }


def wait_endpoint_state(host: str, desired: bool, timeout: int) -> Dict[str, object]:
    deadline = time.monotonic() + timeout
    latest: Dict[str, object] = {}
    while time.monotonic() < deadline:
        latest = endpoint_probe(host)
        if bool(latest.get("ok")) is desired:
            return latest
        time.sleep(1)
    raise CanaryFailure(f"endpoint {host} did not become {'up' if desired else 'down'}")


def shared_failure_recovery(config: Mapping[str, object], timeout: int) -> Dict[str, object]:
    snapshot = eve_model_topology.topology_snapshot(config)
    observer = next(
        (
            dict(item)
            for item in snapshot.get("active_substrates") or []
            if isinstance(item, dict) and item.get("profile") == "observer"
        ),
        None,
    )
    if observer is None:
        raise CanaryFailure("observer shared substrate is missing")
    host = str(observer.get("host") or "")
    label = str(observer.get("launch_label") or "")
    domain = f"gui/{os.getuid()}"
    bootout = run_command(["launchctl", "bootout", f"{domain}/{label}"], timeout=30)
    wait_endpoint_state(host, False, timeout=30)
    unaffected = {
        str(item.get("profile")): endpoint_probe(item.get("host"))
        for item in snapshot.get("active_substrates") or []
        if isinstance(item, dict) and item.get("profile") in {"fast", "deep"}
    }
    if not all(item.get("ok") for item in unaffected.values()):
        raise CanaryFailure("observer failure disrupted an unrelated substrate")
    started = time.monotonic()
    watchdog = run_command(
        [sys.executable, str(RUNTIME_WATCHDOG_PATH)],
        cwd=RUNTIME_DIR,
        timeout=timeout,
    )
    require_command(watchdog, "topology-aware watchdog recovery")
    recovered = wait_endpoint_state(host, True, timeout=timeout)
    recovery_seconds = round(time.monotonic() - started, 3)
    for item in snapshot.get("inactive_substrates") or []:
        if isinstance(item, dict) and endpoint_probe(item.get("host")).get("ok"):
            raise CanaryFailure(f"inactive duplicate endpoint restarted: {item.get('profile')}")
    logical_probe = routed_private_probe(
        "observer_planner_after_shared_recovery",
        "After a shared analytical service recovered, distinguish the observed recovery from the next verification step.",
        "observer,planner",
        timeout,
    )
    if not logical_probe.get("ok"):
        raise CanaryFailure("observer/planner logical routes failed after shared recovery")
    routes = logical_probe.get("stream_routes") if isinstance(logical_probe.get("stream_routes"), dict) else {}
    observer_route = routes.get("observer") if isinstance(routes.get("observer"), dict) else {}
    planner_route = routes.get("planner") if isinstance(routes.get("planner"), dict) else {}
    if (
        observer_route.get("substrate_host") != planner_route.get("substrate_host")
        or observer_route.get("substrate_model") != planner_route.get("substrate_model")
    ):
        raise CanaryFailure("recovered observer/planner attribution did not identify one shared substrate")
    status_path = RUNTIME_DIR / ".eve" / "model_watchdog_status.json"
    status = eve_store.load_json_dict(status_path, default={})
    return {
        "ok": True,
        "failed_profile": "observer",
        "affected_logical_lanes": observer.get("logical_lanes"),
        "bootout": bootout,
        "unaffected_substrates": unaffected,
        "watchdog": watchdog,
        "watchdog_actions": status.get("actions"),
        "recovery_seconds": recovery_seconds,
        "recovered_endpoint": recovered,
        "logical_probe": logical_probe,
    }


def update_config_mode(config: Dict[str, object], mode: str) -> Dict[str, object]:
    updated = dict(config)
    updated["model_lane_topology_mode"] = eve_model_topology.normalize_topology_mode(mode)
    updated.setdefault(
        "model_lane_three_substrate_profile_map",
        dict(eve_model_topology.THREE_SUBSTRATE_PROFILE_MAP),
    )
    snapshot = eve_model_topology.topology_snapshot(updated)
    if not snapshot.get("valid"):
        raise CanaryFailure(
            "refusing invalid topology: " + "; ".join(snapshot.get("validation_errors") or [])
        )
    eve_store.write_json_dict(SOURCE_CONFIG_PATH, updated, indent=2, sort_keys=False)
    return updated


def deploy_current_source_config(timeout: int) -> List[Dict[str, object]]:
    steps = []
    sync = run_command([sys.executable, str(ROOT / "eve.py"), "runtime", "sync"], timeout=timeout)
    steps.append(sync)
    require_command(sync, "runtime sync")
    install = run_command(
        [sys.executable, str(RUNTIME_EVE_PATH), "daemon", "install"],
        cwd=RUNTIME_DIR,
        timeout=timeout,
    )
    steps.append(install)
    require_command(install, "runtime daemon/service reinstall")
    openclaw_config = Path.home() / ".openclaw-eve-repair" / "openclaw.json"
    if RUNTIME_OPENCLAW_TOPOLOGY_SYNC_PATH.is_file() and openclaw_config.is_file():
        openclaw_sync = run_command(
            [
                sys.executable,
                str(RUNTIME_OPENCLAW_TOPOLOGY_SYNC_PATH),
                "--profile",
                "eve-repair",
                "--config",
                str(openclaw_config),
                "--eve-config",
                str(RUNTIME_CONFIG_PATH),
                "--restart-gateway",
            ],
            cwd=RUNTIME_DIR,
            timeout=timeout,
        )
        steps.append(openclaw_sync)
        require_command(openclaw_sync, "OpenClaw model-topology reconciliation")
    return steps


def write_artifacts(record: Dict[str, object]) -> Dict[str, str]:
    SOURCE_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = str(record.get("run_id") or uuid.uuid4())
    history_name = f"{run_id}.json"
    destinations = {
        "source_latest": SOURCE_ARTIFACT_DIR / "latest.json",
        "source_history": SOURCE_ARTIFACT_DIR / history_name,
        "runtime_latest": RUNTIME_ARTIFACT_DIR / "latest.json",
        "runtime_history": RUNTIME_ARTIFACT_DIR / history_name,
    }
    for path in destinations.values():
        eve_store.write_json_dict(path, record, indent=2, sort_keys=False)
    return {key: str(path) for key, path in destinations.items()}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Eve's live model-topology lifecycle canary.")
    parser.add_argument(
        "--target-mode",
        choices=sorted(eve_model_topology.MODEL_LANE_TOPOLOGY_MODES),
        default=eve_model_topology.MODEL_LANE_TOPOLOGY_THREE_SUBSTRATE,
    )
    parser.add_argument("--promote-on-pass", action="store_true")
    parser.add_argument("--skip-failure-injection", action="store_true")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--memory-settle-seconds", type=float, default=5.0)
    parser.add_argument("--memory-samples", type=int, default=3)
    parser.add_argument("--memory-sample-interval", type=float, default=2.0)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    SOURCE_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = f"topology-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    original_config = eve_store.load_json_dict(SOURCE_CONFIG_PATH, default={})
    target_config = dict(original_config)
    target_config["model_lane_topology_mode"] = args.target_mode
    target_snapshot = eve_model_topology.topology_snapshot(target_config)
    if args.dry_run:
        print(json.dumps({"run_id": run_id, "target": target_snapshot}, indent=2, sort_keys=True))
        return 0 if target_snapshot.get("valid") else 2

    record: Dict[str, object] = {
        "schema_id": "eve.model_lane_live_topology_canary.v1",
        "run_id": run_id,
        "started_at": utc_now(),
        "source": "external_codex_operator",
        "target_mode": args.target_mode,
        "promote_on_pass": bool(args.promote_on_pass),
        "memory_measurement": {
            "baseline_normalized_by_fresh_redeploy": True,
            "settle_seconds": args.memory_settle_seconds,
            "sample_count": args.memory_samples,
            "sample_interval_seconds": args.memory_sample_interval,
            "preferred_metric": "macos_phys_footprint",
            "fallback_metric": "rss",
        },
        "status": "running",
        "passed": False,
        "gates": {},
    }
    promoted = False
    target_deployed = False
    failure = ""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with eve_store.file_lock(LOCK_PATH):
            progress("normalizing baseline topology through a fresh service reinstall")
            record["baseline_deployment_steps"] = deploy_current_source_config(args.timeout)
            record["baseline_topology_convergence"] = wait_for_topology(
                original_config, timeout=args.timeout
            )
            if args.memory_settle_seconds > 0:
                time.sleep(args.memory_settle_seconds)
            progress("capturing equal-age baseline residency window")
            baseline = capture_residency_window(
                original_config,
                sample_count=args.memory_samples,
                sample_interval=args.memory_sample_interval,
            )
            record["baseline"] = baseline
            progress(f"deploying target topology {args.target_mode}")
            target_config = update_config_mode(original_config, args.target_mode)
            target_deployed = True
            record["deployment_steps"] = deploy_current_source_config(args.timeout)
            record["topology_convergence"] = wait_for_topology(target_config, timeout=args.timeout)
            if args.memory_settle_seconds > 0:
                time.sleep(args.memory_settle_seconds)
            progress("target endpoints converged; measuring equal-age residency window")
            post = capture_residency_window(
                target_config,
                sample_count=args.memory_samples,
                sample_interval=args.memory_sample_interval,
            )
            record["post_deployment"] = post
            expected_processes = int(post.get("topology", {}).get("substrate_count") or 0)
            process_gate = (
                int(post.get("resident_process_count") or 0) == expected_processes
                and bool(post.get("resident_process_count_stable"))
            )
            baseline_process_count = int(baseline.get("resident_process_count") or 0)
            baseline_rss_gib = float(baseline.get("total_rss_gib") or 0.0)
            post_rss_gib = float(post.get("total_rss_gib") or 0.0)
            baseline_footprint_gib = float(
                baseline.get("total_physical_footprint_gib") or 0.0
            )
            post_footprint_gib = float(
                post.get("total_physical_footprint_gib") or 0.0
            )
            footprint_comparable = bool(
                baseline.get("physical_footprint_complete")
                and post.get("physical_footprint_complete")
                and baseline_footprint_gib > 0.0
                and post_footprint_gib > 0.0
            )
            memory_metric = "macos_phys_footprint" if footprint_comparable else "rss"
            baseline_memory_gib = (
                baseline_footprint_gib if footprint_comparable else baseline_rss_gib
            )
            post_memory_gib = post_footprint_gib if footprint_comparable else post_rss_gib
            memory_delta_gib = round(
                post_memory_gib - baseline_memory_gib,
                3,
            )
            rss_delta_gib = round(post_rss_gib - baseline_rss_gib, 3)
            footprint_delta_gib = round(
                post_footprint_gib - baseline_footprint_gib, 3
            )
            record["gates"]["physical_residency"] = {
                "passed": process_gate,
                "expected_process_count": expected_processes,
                "actual_process_count": post.get("resident_process_count"),
                "baseline_process_count": baseline_process_count,
                "baseline_rss_gib": baseline_rss_gib,
                "post_rss_gib": post_rss_gib,
                "baseline_physical_footprint_gib": baseline_footprint_gib,
                "post_physical_footprint_gib": post_footprint_gib,
                "memory_metric": memory_metric,
                "memory_delta_gib": memory_delta_gib,
                "rss_delta_gib": rss_delta_gib,
                "physical_footprint_delta_gib": footprint_delta_gib,
            }
            if not process_gate:
                raise CanaryFailure("physical process residency did not match the target topology")
            memory_gate = (
                baseline_process_count <= expected_processes
                or baseline_memory_gib <= 0.0
                or post_memory_gib < baseline_memory_gib
            )
            record["gates"]["memory_reduction"] = {
                "passed": memory_gate,
                "metric": memory_metric,
                "baseline_gib": baseline_memory_gib,
                "post_gib": post_memory_gib,
                "baseline_rss_gib": baseline_rss_gib,
                "post_rss_gib": post_rss_gib,
                "baseline_physical_footprint_gib": baseline_footprint_gib,
                "post_physical_footprint_gib": post_footprint_gib,
                "memory_delta_gib": memory_delta_gib,
                "rss_delta_gib": rss_delta_gib,
                "physical_footprint_delta_gib": footprint_delta_gib,
            }
            if not memory_gate:
                raise CanaryFailure("fewer processes did not reduce measured resident memory")

            progress("running concurrent logical-lane load through shared substrates")
            concurrency = concurrency_probe(args.timeout)
            record["concurrency"] = concurrency
            record["gates"]["concurrency"] = {"passed": bool(concurrency.get("ok"))}
            if not concurrency.get("ok"):
                raise CanaryFailure("shared-substrate concurrency probe failed")

            if args.skip_failure_injection:
                recovery = {"ok": True, "skipped": True}
            else:
                progress("removing the shared observer/planner substrate and requiring watchdog recovery")
                recovery = shared_failure_recovery(target_config, args.timeout)
            record["shared_failure_recovery"] = recovery
            record["gates"]["shared_failure_recovery"] = {"passed": bool(recovery.get("ok"))}
            if not recovery.get("ok"):
                raise CanaryFailure("shared-substrate failure recovery failed")

            progress("checking independent deadman topology recognition")
            deadman = run_command(
                ["/bin/zsh", str(RUNTIME_DEADMAN_PATH), "--check-only"],
                cwd=RUNTIME_DIR,
                timeout=60,
            )
            deadman_text = str(deadman.get("stdout") or "") + " " + str(deadman.get("stderr") or "")
            deadman_topology_ok = (
                f"topology={args.target_mode}" in deadman_text
                and "active model substrate(s) down" not in deadman_text
                and "active model substrates down" not in deadman_text
            )
            record["deadman_check"] = deadman
            record["gates"]["deadman_topology"] = {"passed": deadman_topology_ok}
            if not deadman_topology_ok:
                raise CanaryFailure("independent deadman did not recognize the active topology")

            progress("running post-canary doctor")
            doctor = run_command(
                [sys.executable, str(RUNTIME_EVE_PATH), "doctor"],
                cwd=RUNTIME_DIR,
                timeout=args.timeout,
            )
            record["doctor"] = doctor
            record["gates"]["doctor"] = {"passed": int(doctor.get("returncode") or 0) == 0}
            require_command(doctor, "post-canary doctor")

            record["passed"] = True
            if args.promote_on_pass:
                promoted = True
                record["status"] = "passed_promoted"
                progress("all gates passed; retaining the three-substrate live topology")
            else:
                record["status"] = "passed_rolled_back"
    except BaseException as exc:
        failure = compact_text(exc, 2000)
        record["failure"] = failure
        record["status"] = "failed_rollback_pending"
    finally:
        if target_deployed and not promoted:
            try:
                progress("restoring the original topology")
                eve_store.write_json_dict(SOURCE_CONFIG_PATH, original_config, indent=2, sort_keys=False)
                rollback_steps = deploy_current_source_config(args.timeout)
                record["rollback_steps"] = rollback_steps
                wait_for_topology(original_config, timeout=args.timeout)
                record["status"] = "failed_rolled_back" if failure else "passed_rolled_back"
            except Exception as rollback_exc:
                record["rollback_failure"] = compact_text(rollback_exc, 2000)
                record["status"] = "failed_rollback_failed"
        record["completed_at"] = utc_now()
        record["final_source_mode"] = eve_model_topology.configured_topology_mode(
            eve_store.load_json_dict(SOURCE_CONFIG_PATH, default={})
        )
        artifacts = write_artifacts(record)
        record["artifacts"] = artifacts
        write_artifacts(record)
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0 if record.get("passed") and record.get("status") in {"passed_promoted", "passed_rolled_back"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
