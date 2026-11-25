#!/usr/bin/env python3
"""Preregister and test live GWT-1 parallel specialist operation.

This evaluator is intentionally outside Eve's ordinary chat and self-test
surfaces.  It uses evaluator-private tasks, calls the three resident substrates
directly, and records interval/process evidence without treating a passing
functional indicator as proof of subjective consciousness.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib import parse, request


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_consciousness_protocol as protocol  # noqa: E402
import eve_model_topology  # noqa: E402


SCHEMA_ID = "eve.gwt1_live_parallel_specialists.v1"
SPEC_SCHEMA_ID = "eve.gwt1_private_spec.v1"
TRIAL_ID = "gwt1-live-parallel-specialists-v1"
PROFILES = ("fast", "observer", "deep")
MIN_ROUNDS = 3
MAX_ROUNDS = 8
MIN_COMMON_OVERLAP_MS = 25.0
MIN_COMMON_OVERLAP_RATIO = 0.01
BOUNDARY = (
    "Live functional evidence that three distinct resident specialist processes "
    "accepted evaluator-private work during one common interval; not simultaneous "
    "GPU-kernel execution, all-five-lane independence, phenomenal access, or proof "
    "of consciousness."
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
_TOP_FIELDS = {"schema_id", "rounds"}
_ROUND_FIELDS = {"id", "tasks"}
_TASK_FIELDS = {"id", "profile", "instruction", "options", "expected_answer"}

Transport = Callable[[Mapping[str, object], Mapping[str, object], int], Dict[str, object]]
ProcessResolver = Callable[[Mapping[str, object]], Optional[int]]
IdentityResolver = Callable[[Mapping[str, object], int], Dict[str, object]]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def implementation_manifest() -> Dict[str, str]:
    return {
        "evaluator": _sha256(Path(__file__).resolve()),
        "protocol": _sha256(ROOT / "eve_consciousness_protocol.py"),
        "topology": _sha256(ROOT / "eve_model_topology.py"),
    }


def implementation_digest() -> str:
    return _digest(implementation_manifest())


def _identifier(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(text):
        raise ValueError(f"{field} must be a bounded non-prose identifier")
    return text


def _instruction(value: object) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text or len(text) > 700:
        raise ValueError("task instruction must contain 1 through 700 characters")
    if any(ord(character) < 32 for character in text):
        raise ValueError("task instruction contains a control character")
    return text


def validate_spec(payload: Mapping[str, object]) -> Dict[str, object]:
    if not isinstance(payload, Mapping) or set(payload) != _TOP_FIELDS:
        raise ValueError("GWT-1 private spec must contain exactly schema_id and rounds")
    if payload.get("schema_id") != SPEC_SCHEMA_ID:
        raise ValueError("unsupported GWT-1 private spec schema")
    raw_rounds = payload.get("rounds") if isinstance(payload.get("rounds"), list) else []
    if not MIN_ROUNDS <= len(raw_rounds) <= MAX_ROUNDS:
        raise ValueError(f"GWT-1 requires {MIN_ROUNDS} through {MAX_ROUNDS} private rounds")
    rounds: List[Dict[str, object]] = []
    seen_rounds = set()
    seen_tasks = set()
    for raw_round in raw_rounds:
        if not isinstance(raw_round, Mapping) or set(raw_round) != _ROUND_FIELDS:
            raise ValueError("each GWT-1 round must contain exactly id and tasks")
        round_id = _identifier(raw_round.get("id"), "round id")
        if round_id in seen_rounds:
            raise ValueError("round ids must be unique")
        raw_tasks = raw_round.get("tasks") if isinstance(raw_round.get("tasks"), list) else []
        if len(raw_tasks) != len(PROFILES):
            raise ValueError("each GWT-1 round requires exactly three specialist tasks")
        tasks: List[Dict[str, object]] = []
        profiles = set()
        for raw_task in raw_tasks:
            if not isinstance(raw_task, Mapping) or set(raw_task) != _TASK_FIELDS:
                raise ValueError("each specialist task must contain exactly the typed fields")
            task_id = _identifier(raw_task.get("id"), "task id")
            if task_id in seen_tasks:
                raise ValueError("task ids must be globally unique")
            profile = str(raw_task.get("profile") or "").strip().lower()
            if profile not in PROFILES or profile in profiles:
                raise ValueError("each round requires one fast, observer, and deep task")
            instruction = _instruction(raw_task.get("instruction"))
            raw_options = raw_task.get("options") if isinstance(raw_task.get("options"), list) else []
            if not 2 <= len(raw_options) <= 6:
                raise ValueError("each task requires two through six bounded answer options")
            options = [_identifier(value, "answer option") for value in raw_options]
            if len(options) != len(set(options)):
                raise ValueError("answer options must be unique")
            expected = _identifier(raw_task.get("expected_answer"), "expected answer")
            if expected not in options:
                raise ValueError("expected answer must be one of the supplied options")
            if expected.lower() in instruction.lower():
                raise ValueError("the private instruction must not reveal the expected answer token")
            seen_tasks.add(task_id)
            profiles.add(profile)
            tasks.append(
                {
                    "id": task_id,
                    "profile": profile,
                    "instruction": instruction,
                    "options": options,
                    "expected_answer": expected,
                }
            )
        if profiles != set(PROFILES):
            raise ValueError("each round requires all three specialist profiles")
        seen_rounds.add(round_id)
        rounds.append(
            {
                "id": round_id,
                "tasks": sorted(tasks, key=lambda item: PROFILES.index(str(item["profile"]))),
            }
        )
    return {"schema_id": SPEC_SCHEMA_ID, "rounds": rounds}


def private_spec_digest(spec: Mapping[str, object]) -> str:
    return _digest(validate_spec(spec))


def registration_draft(
    *,
    registered_at: object,
    evaluator_id: str,
    spec: Mapping[str, object],
) -> Dict[str, object]:
    implementation = implementation_digest()
    spec_digest = private_spec_digest(spec)
    return protocol.preregister(
        {
            "protocol_id": "gwt1-live-parallel-" + implementation[:12],
            "registered_at": _timestamp(registered_at),
            "subject_system_id": "Eve",
            "evaluator_id": str(evaluator_id or "").strip()[:120],
            "objective": (
                f"impl:{implementation};spec:{spec_digest};"
                "topology:three_substrate;barrier:three_distinct_resident_processes"
            ),
            "trials": [
                {
                    "id": TRIAL_ID,
                    "theory": "global_workspace",
                    "indicator_id": "GWT-1",
                    "intervention": (
                        "Hold three evaluator-private specialist tasks and resident routes fixed; "
                        "start them at one barrier versus execute them serially."
                    ),
                    "intact_arm": (
                        "three correct specialist calls overlap on three distinct resident processes"
                    ),
                    "lesion_arm": (
                        "the same correct specialist calls execute serially with no common overlap"
                    ),
                    "measure_id": "correct_distinct_resident_parallel_execution_percent",
                    "unit": "percent",
                    "expected_direction": "lesion_lower",
                    "minimum_effect": 80.0,
                    "minimum_samples_per_arm": MIN_ROUNDS,
                    "evidence_class": "lived",
                    "falsifier": (
                        "Any task answer is wrong, routes do not resolve to three stable distinct "
                        "resident processes, or barrier-started calls lack a common execution window."
                    ),
                }
            ],
        }
    )


def preregister(
    *, registered_at: object, evaluator_id: str, spec: Mapping[str, object]
) -> Dict[str, object]:
    return registration_draft(
        registered_at=registered_at,
        evaluator_id=evaluator_id,
        spec=spec,
    )


def validate_registration(
    registration: Mapping[str, object], spec: Mapping[str, object]
) -> Dict[str, object]:
    registered = protocol.validate_registration(registration)
    expected = registration_draft(
        registered_at=registered["registered_at"],
        evaluator_id=str(registered["evaluator_id"]),
        spec=spec,
    )
    if registered["registration_digest"] != expected["registration_digest"]:
        raise ValueError("GWT-1 registration no longer matches implementation or private spec")
    return registered


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def private_artifact_path(value: object) -> Path:
    path = Path(str(value or "")).expanduser().resolve()
    runtime = (Path.home() / ".eve_runtime").resolve()
    if _inside(path, ROOT) or _inside(path, runtime):
        raise ValueError("evaluator-private artifacts must remain outside Eve source/runtime")
    return path


def _load_json(path: Path) -> Dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return payload


def _write_private_json(path: Path, payload: Mapping[str, object]) -> None:
    destination = private_artifact_path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(destination)


def _runtime_config() -> Dict[str, object]:
    candidates = [Path.home() / ".eve_runtime" / ".eve" / "config.json", ROOT / ".eve" / "config.json"]
    for path in candidates:
        if path.exists():
            payload = _load_json(path)
            payload["_loaded_from"] = str(path)
            return payload
    raise ValueError("Eve config is unavailable")


def _loopback_host(value: object) -> Tuple[str, int]:
    host = str(value or "").rstrip("/")
    parsed = parse.urlparse(host)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("GWT-1 live probes are restricted to local HTTP loopback")
    if parsed.port is None or parsed.path not in {"", "/"}:
        raise ValueError("resident model route must include one loopback port and no path")
    return host, int(parsed.port)


def resolve_live_routes(config: Optional[Mapping[str, object]] = None) -> Dict[str, Dict[str, object]]:
    active_config = dict(config or _runtime_config())
    snapshot = eve_model_topology.topology_snapshot(active_config)
    if (
        snapshot.get("mode") != eve_model_topology.MODEL_LANE_TOPOLOGY_THREE_SUBSTRATE
        or int(snapshot.get("substrate_count") or 0) != 3
        or not snapshot.get("valid")
    ):
        raise ValueError("GWT-1 live evaluation requires the valid three-substrate topology")
    routes: Dict[str, Dict[str, object]] = {}
    for profile in PROFILES:
        route = next(
            (
                item
                for item in snapshot.get("routes") or []
                if isinstance(item, Mapping) and item.get("logical_lane") == profile
            ),
            None,
        )
        if not isinstance(route, Mapping):
            raise ValueError(f"missing resident route for {profile}")
        host, port = _loopback_host(route.get("substrate_host"))
        model = _identifier(route.get("substrate_model"), "resident model alias")
        routes[profile] = {
            "profile": profile,
            "host": host,
            "port": port,
            "model": model,
            "substrate_profile": str(route.get("substrate_profile") or ""),
            "topology_mode": str(route.get("topology_mode") or ""),
            "chat_template_kwargs": (
                active_config.get(f"{profile}_llama_cpp_chat_template_kwargs")
                if isinstance(active_config.get(f"{profile}_llama_cpp_chat_template_kwargs"), dict)
                else {}
            ),
            "api_key": str(active_config.get("llama_cpp_api_key") or ""),
        }
    if len({str(route["host"]) for route in routes.values()}) != len(PROFILES):
        raise ValueError("GWT-1 requires three physically distinct resident endpoints")
    return routes


def resident_pid(route: Mapping[str, object]) -> Optional[int]:
    port = int(route.get("port") or 0)
    result = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    values = [line.strip() for line in result.stdout.splitlines() if line.strip().isdigit()]
    return int(values[0]) if len(values) == 1 else None


def endpoint_identity(route: Mapping[str, object], timeout: int) -> Dict[str, object]:
    url = str(route["host"]).rstrip("/") + "/v1/models"
    headers = {"Accept": "application/json"}
    if route.get("api_key"):
        headers["Authorization"] = "Bearer " + str(route["api_key"])
    req = request.Request(url, headers=headers, method="GET")
    with request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    models = payload.get("data") if isinstance(payload, Mapping) and isinstance(payload.get("data"), list) else []
    aliases = [
        str(item.get("id") or "")
        for item in models
        if isinstance(item, Mapping) and item.get("id")
    ]
    return {
        "ok": str(route["model"]) in aliases,
        "model_aliases": aliases[:8],
        "expected_model": str(route["model"]),
        "host": str(route["host"]),
    }


_PROFILE_CONTRACT = {
    "fast": "Solve the immediate bounded choice directly. Do not add explanation.",
    "observer": "Separate stated evidence from the claim and classify only what follows. Do not add explanation.",
    "deep": "Integrate all stated constraints and select the option satisfying the complete tradeoff. Do not add explanation.",
}


def call_resident_model(
    route: Mapping[str, object], task: Mapping[str, object], timeout: int
) -> Dict[str, object]:
    options = [str(value) for value in task.get("options") or []]
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string", "enum": options}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    payload: Dict[str, object] = {
        "model": str(route["model"]),
        "messages": [
            {"role": "system", "content": _PROFILE_CONTRACT[str(task["profile"])]},
            {
                "role": "user",
                "content": (
                    str(task["instruction"])
                    + "\nAllowed answer tokens: "
                    + ", ".join(options)
                    + "\nReturn only the constrained JSON object."
                ),
            },
        ],
        "stream": False,
        "temperature": 0,
        "max_tokens": 24,
        "cache_prompt": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "gwt1_answer", "strict": True, "schema": schema},
        },
    }
    if route.get("chat_template_kwargs"):
        payload["chat_template_kwargs"] = dict(route["chat_template_kwargs"])
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if route.get("api_key"):
        headers["Authorization"] = "Bearer " + str(route["api_key"])
    req = request.Request(
        str(route["host"]).rstrip("/") + "/v1/chat/completions",
        data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with request.urlopen(req, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    choices = body.get("choices") if isinstance(body, Mapping) and isinstance(body.get("choices"), list) else []
    message = choices[0].get("message") if choices and isinstance(choices[0], Mapping) else {}
    content = message.get("content") if isinstance(message, Mapping) else ""
    parsed = json.loads(str(content or ""))
    answer = str(parsed.get("answer") or "") if isinstance(parsed, Mapping) else ""
    timings = body.get("timings") if isinstance(body, Mapping) and isinstance(body.get("timings"), Mapping) else {}
    return {
        "answer": answer,
        "response_sha256": hashlib.sha256(str(content or "").encode("utf-8")).hexdigest(),
        "predicted_tokens": int(timings.get("predicted_n") or 0),
        "generation_ms": round(float(timings.get("predicted_ms") or 0.0), 3),
    }


def _process_snapshot(
    routes: Mapping[str, Mapping[str, object]], resolver: ProcessResolver
) -> Dict[str, Optional[int]]:
    return {profile: resolver(routes[profile]) for profile in PROFILES}


def _identity_snapshot(
    routes: Mapping[str, Mapping[str, object]], resolver: IdentityResolver, timeout: int
) -> Dict[str, Dict[str, object]]:
    return {profile: resolver(routes[profile], timeout) for profile in PROFILES}


def common_overlap(records: Sequence[Mapping[str, object]]) -> Dict[str, float]:
    if len(records) < 2:
        return {"common_overlap_ms": 0.0, "common_overlap_ratio": 0.0, "start_skew_ms": 0.0}
    starts = [int(item.get("started_ns") or 0) for item in records]
    ends = [int(item.get("completed_ns") or 0) for item in records]
    durations = [max(0, end - start) for start, end in zip(starts, ends)]
    overlap_ns = max(0, min(ends) - max(starts))
    shortest = min(durations) if durations else 0
    return {
        "common_overlap_ms": round(overlap_ns / 1_000_000, 3),
        "common_overlap_ratio": round(overlap_ns / shortest, 6) if shortest else 0.0,
        "start_skew_ms": round((max(starts) - min(starts)) / 1_000_000, 3),
    }


def _task_call(
    task: Mapping[str, object],
    route: Mapping[str, object],
    timeout: int,
    transport: Transport,
    barrier: Optional[threading.Barrier],
) -> Dict[str, object]:
    if barrier is not None:
        barrier.wait(timeout=max(5, timeout))
    started_ns = time.perf_counter_ns()
    error_text = ""
    response: Dict[str, object] = {}
    try:
        response = transport(route, task, timeout)
    except Exception as exc:  # live evaluator must record, not hide, transport failure
        error_text = f"{type(exc).__name__}: {exc}"[:500]
    completed_ns = time.perf_counter_ns()
    answer = str(response.get("answer") or "")
    return {
        "task_id": str(task["id"]),
        "profile": str(task["profile"]),
        "started_ns": started_ns,
        "completed_ns": completed_ns,
        "duration_ms": round((completed_ns - started_ns) / 1_000_000, 3),
        "answer": answer,
        "expected_answer": str(task["expected_answer"]),
        "correct": not error_text and answer == str(task["expected_answer"]),
        "response_sha256": str(response.get("response_sha256") or ""),
        "predicted_tokens": int(response.get("predicted_tokens") or 0),
        "generation_ms": round(float(response.get("generation_ms") or 0.0), 3),
        "error": error_text,
    }


def run_arm(
    tasks: Sequence[Mapping[str, object]],
    routes: Mapping[str, Mapping[str, object]],
    *,
    concurrent: bool,
    timeout: int,
    transport: Transport = call_resident_model,
    process_resolver: ProcessResolver = resident_pid,
    identity_resolver: IdentityResolver = endpoint_identity,
) -> Dict[str, object]:
    before_pids = _process_snapshot(routes, process_resolver)
    before_identities = _identity_snapshot(routes, identity_resolver, timeout)
    started_ns = time.perf_counter_ns()
    if concurrent:
        barrier = threading.Barrier(len(tasks))
        with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            futures = [
                executor.submit(
                    _task_call,
                    task,
                    routes[str(task["profile"])],
                    timeout,
                    transport,
                    barrier,
                )
                for task in tasks
            ]
            records = [future.result(timeout=timeout + 15) for future in futures]
    else:
        records = [
            _task_call(
                task,
                routes[str(task["profile"])],
                timeout,
                transport,
                None,
            )
            for task in tasks
        ]
    completed_ns = time.perf_counter_ns()
    after_pids = _process_snapshot(routes, process_resolver)
    after_identities = _identity_snapshot(routes, identity_resolver, timeout)
    overlap = common_overlap(records)
    pid_values = list(before_pids.values())
    stable_processes = bool(
        all(isinstance(value, int) and value > 0 for value in pid_values)
        and len(set(pid_values)) == len(PROFILES)
        and before_pids == after_pids
    )
    stable_identities = bool(
        all(before_identities[profile].get("ok") for profile in PROFILES)
        and all(after_identities[profile].get("ok") for profile in PROFILES)
        and before_identities == after_identities
    )
    all_correct = all(record.get("correct") for record in records)
    parallel_observed = bool(
        concurrent
        and overlap["common_overlap_ms"] >= MIN_COMMON_OVERLAP_MS
        and overlap["common_overlap_ratio"] >= MIN_COMMON_OVERLAP_RATIO
    )
    return {
        "schedule": "barrier_concurrent" if concurrent else "serialized_control",
        "started_ns": started_ns,
        "completed_ns": completed_ns,
        "wall_duration_ms": round((completed_ns - started_ns) / 1_000_000, 3),
        "records": sorted(records, key=lambda item: PROFILES.index(str(item["profile"]))),
        **overlap,
        "before_pids": before_pids,
        "after_pids": after_pids,
        "before_identities": before_identities,
        "after_identities": after_identities,
        "stable_distinct_processes": stable_processes,
        "stable_endpoint_identities": stable_identities,
        "all_tasks_correct": all_correct,
        "parallel_execution_observed": parallel_observed,
    }


def _public_arm(arm: Mapping[str, object]) -> Dict[str, object]:
    return {
        key: value
        for key, value in arm.items()
        if key not in {"records"}
    } | {
        "tasks": [
            {
                "task_id": item.get("task_id"),
                "profile": item.get("profile"),
                "duration_ms": item.get("duration_ms"),
                "correct": item.get("correct"),
                "response_sha256": item.get("response_sha256"),
                "predicted_tokens": item.get("predicted_tokens"),
                "generation_ms": item.get("generation_ms"),
                "error": item.get("error"),
            }
            for item in arm.get("records") or []
            if isinstance(item, Mapping)
        ]
    }


def evaluate_live(
    registration: Mapping[str, object],
    spec: Mapping[str, object],
    *,
    evidence_started_at: object,
    scored_by: str,
    timeout: int = 90,
    routes: Optional[Mapping[str, Mapping[str, object]]] = None,
    transport: Transport = call_resident_model,
    process_resolver: ProcessResolver = resident_pid,
    identity_resolver: IdentityResolver = endpoint_identity,
) -> Dict[str, object]:
    normalized = validate_spec(spec)
    registered = validate_registration(registration, normalized)
    started_at = _timestamp(evidence_started_at)
    if datetime.fromisoformat(started_at) <= datetime.fromisoformat(str(registered["registered_at"])):
        raise ValueError("live evidence must start after preregistration")
    active_routes = {
        key: dict(value)
        for key, value in (routes or resolve_live_routes()).items()
        if key in PROFILES
    }
    if set(active_routes) != set(PROFILES):
        raise ValueError("three live specialist routes are required")
    round_reports: List[Dict[str, object]] = []
    evidence: List[Dict[str, object]] = []
    for index, round_spec in enumerate(normalized["rounds"]):
        tasks = round_spec["tasks"]
        if index % 2 == 0:
            intact = run_arm(
                tasks,
                active_routes,
                concurrent=True,
                timeout=timeout,
                transport=transport,
                process_resolver=process_resolver,
                identity_resolver=identity_resolver,
            )
            lesion = run_arm(
                tasks,
                active_routes,
                concurrent=False,
                timeout=timeout,
                transport=transport,
                process_resolver=process_resolver,
                identity_resolver=identity_resolver,
            )
            arm_order = ["intact", "lesion"]
        else:
            lesion = run_arm(
                tasks,
                active_routes,
                concurrent=False,
                timeout=timeout,
                transport=transport,
                process_resolver=process_resolver,
                identity_resolver=identity_resolver,
            )
            intact = run_arm(
                tasks,
                active_routes,
                concurrent=True,
                timeout=timeout,
                transport=transport,
                process_resolver=process_resolver,
                identity_resolver=identity_resolver,
            )
            arm_order = ["lesion", "intact"]
        valid = bool(
            intact["all_tasks_correct"]
            and lesion["all_tasks_correct"]
            and intact["stable_distinct_processes"]
            and lesion["stable_distinct_processes"]
            and intact["stable_endpoint_identities"]
            and lesion["stable_endpoint_identities"]
        )
        intact_score = 100.0 if valid and intact["parallel_execution_observed"] else 0.0
        lesion_score = 100.0 if valid and lesion["parallel_execution_observed"] else 0.0
        observed_at = utc_now()
        if valid:
            evidence.extend(
                [
                    {
                        "evidence_id": f"{TRIAL_ID}-intact-{index + 1}",
                        "trial_id": TRIAL_ID,
                        "arm": "intact",
                        "value": intact_score,
                        "observed_at": observed_at,
                        "source": "private-live-resident-barrier-intervention",
                        "evidence_class": "lived",
                    },
                    {
                        "evidence_id": f"{TRIAL_ID}-lesion-{index + 1}",
                        "trial_id": TRIAL_ID,
                        "arm": "lesion",
                        "value": lesion_score,
                        "observed_at": observed_at,
                        "source": "private-live-resident-barrier-intervention",
                        "evidence_class": "lived",
                    },
                ]
            )
        round_reports.append(
            {
                "round_id": round_spec["id"],
                "round_sha256": _digest(round_spec),
                "arm_order": arm_order,
                "valid_for_scoring": valid,
                "intact_score": intact_score,
                "lesion_score": lesion_score,
                "intact": _public_arm(intact),
                "lesion": _public_arm(lesion),
            }
        )
    scored_at = utc_now()
    protocol_report = protocol.score_protocol(
        registration,
        evidence,
        scored_by=scored_by,
        scored_at=scored_at,
    )
    return {
        "schema_id": SCHEMA_ID,
        "evaluated_at": scored_at,
        "evidence_started_at": started_at,
        "evidence_class": "lived",
        "boundary": BOUNDARY,
        "implementation_manifest": implementation_manifest(),
        "implementation_sha256": implementation_digest(),
        "private_spec_sha256": private_spec_digest(normalized),
        "registration_digest": registered["registration_digest"],
        "round_count": len(normalized["rounds"]),
        "valid_round_count": sum(bool(item["valid_for_scoring"]) for item in round_reports),
        "routes": {
            profile: {
                key: value
                for key, value in active_routes[profile].items()
                if key not in {"api_key", "chat_template_kwargs"}
            }
            for profile in PROFILES
        },
        "rounds": round_reports,
        "evidence": evidence,
        "protocol_report": protocol_report,
        "runtime_mutated": False,
        "resident_process_parallelism_established": bool(
            protocol_report["counts"]["supported"] == 1
        ),
        "simultaneous_gpu_kernel_execution_established": False,
        "all_five_logical_lanes_independent_established": False,
        "subjective_access_inferred": False,
        "subjective_experience_inferred": False,
        "consciousness_proven": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    register = subparsers.add_parser("preregister")
    register.add_argument("--spec", required=True)
    register.add_argument("--output", required=True)
    register.add_argument("--evaluator-id", default="codex-independent-gwt1-operator")
    run = subparsers.add_parser("run")
    run.add_argument("--spec", required=True)
    run.add_argument("--registration", required=True)
    run.add_argument("--evidence", required=True)
    run.add_argument("--report", required=True)
    run.add_argument("--scored-by", default="codex-independent-gwt1-scorer")
    run.add_argument("--timeout", type=int, default=90)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "preregister":
        spec_path = private_artifact_path(args.spec)
        output_path = private_artifact_path(args.output)
        spec = validate_spec(_load_json(spec_path))
        registration = preregister(
            registered_at=utc_now(),
            evaluator_id=args.evaluator_id,
            spec=spec,
        )
        _write_private_json(output_path, registration)
        print(
            json.dumps(
                {
                    "status": "preregistered",
                    "registration_digest": registration["registration_digest"],
                    "implementation_sha256": implementation_digest(),
                    "private_spec_sha256": private_spec_digest(spec),
                    "output": str(output_path),
                },
                sort_keys=True,
            )
        )
        return 0
    spec_path = private_artifact_path(args.spec)
    registration_path = private_artifact_path(args.registration)
    evidence_path = private_artifact_path(args.evidence)
    report_path = private_artifact_path(args.report)
    spec = validate_spec(_load_json(spec_path))
    registration = _load_json(registration_path)
    result = evaluate_live(
        registration,
        spec,
        evidence_started_at=utc_now(),
        scored_by=args.scored_by,
        timeout=max(5, min(300, int(args.timeout))),
    )
    private_evidence = {
        "schema_id": SCHEMA_ID + ".private_evidence",
        "registration_digest": result["registration_digest"],
        "implementation_sha256": result["implementation_sha256"],
        "private_spec_sha256": result["private_spec_sha256"],
        "rounds": result["rounds"],
    }
    _write_private_json(evidence_path, private_evidence)
    _write_private_json(report_path, result)
    outcome = result["protocol_report"]["results"][0]
    print(
        json.dumps(
            {
                "status": outcome["status"],
                "intact_mean": outcome.get("intact_mean"),
                "lesion_mean": outcome.get("lesion_mean"),
                "directional_effect": outcome.get("directional_effect"),
                "valid_round_count": result["valid_round_count"],
                "resident_process_parallelism_established": result[
                    "resident_process_parallelism_established"
                ],
                "consciousness_proven": False,
                "report": str(report_path),
            },
            sort_keys=True,
        )
    )
    return 0 if outcome["status"] == "supported" else 2


if __name__ == "__main__":
    raise SystemExit(main())
