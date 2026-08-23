#!/usr/bin/env python3
import json
import os
import signal
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib import error, request

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_platform
import eve_model_topology
import eve_store

APP_DIR = ROOT / ".eve"
RUNTIME_DIR = eve_platform.runtime_dir()
RUNTIME_APP_DIR = RUNTIME_DIR / ".eve"
CONFIG_PATH = APP_DIR / "config.json"
STATUS_PATH = APP_DIR / "model_watchdog_status.json"
HEALTH_LOG_PATH = APP_DIR / "model_health.jsonl"
RUNTIME_STATUS_PATH = RUNTIME_APP_DIR / "model_watchdog_status.json"
RUNTIME_HEALTH_LOG_PATH = RUNTIME_APP_DIR / "model_health.jsonl"
LOCK_PATH = APP_DIR / "model_watchdog.lock"
PYTHON_BIN = eve_platform.python_executable()
LLAMA_CPP_FAST_LABEL = eve_model_topology.profile_launch_label("fast")
LLAMA_CPP_DEEP_LABEL = eve_model_topology.profile_launch_label("deep")
LLAMA_CPP_OBSERVER_LABEL = eve_model_topology.profile_launch_label("observer")
LLAMA_CPP_PLANNER_LABEL = eve_model_topology.profile_launch_label("planner")
LLAMA_CPP_RELATIONSHIP_LABEL = eve_model_topology.profile_launch_label("relationship")

LLAMA_CPP_PROFILE_DEFAULTS = {
    profile: {
        "host": str(eve_model_topology.PROFILE_DEFAULTS[profile]["host"]),
        "alias": str(eve_model_topology.PROFILE_DEFAULTS[profile]["alias"]),
    }
    for profile in eve_model_topology.PROFILE_ORDER
}

LLAMA_CPP_PROFILE_ROUTE_FIELDS = dict(eve_model_topology.PROFILE_ROUTE_FIELDS)


class FetchTimeoutError(TimeoutError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(value: object) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def load_json(path: Path, default: Dict[str, object]) -> Dict[str, object]:
    return eve_store.load_json_dict(path, default=default)


def write_json(path: Path, payload: Dict[str, object]) -> None:
    eve_store.write_json_dict(path, payload)


def append_jsonl(path: Path, payload: Dict[str, object]) -> None:
    eve_store.append_jsonl_record(path, payload, ensure_ascii=True)


def write_health_status(payload: Dict[str, object]) -> None:
    write_json(STATUS_PATH, payload)
    if RUNTIME_APP_DIR.exists():
        write_json(RUNTIME_STATUS_PATH, payload)


def append_health_log(payload: Dict[str, object]) -> None:
    append_jsonl(HEALTH_LOG_PATH, payload)
    if RUNTIME_APP_DIR.exists():
        append_jsonl(RUNTIME_HEALTH_LOG_PATH, payload)


def normalize_model_name(value: object) -> str:
    text = str(value or "").strip()
    return text


def normalize_model_backend(value: object) -> str:
    text = " ".join(str(value or "").lower().replace("-", "_").split())
    if text in {"llama.cpp", "llama cpp", "llama_server", "llama"}:
        text = "llama_cpp"
    return text if text in {"ollama", "llama_cpp"} else "ollama"


def normalize_optional_model_backend(value: object) -> Optional[str]:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return None
    return normalize_model_backend(text)


def configured_model_backend(config: Dict[str, object], model: str) -> str:
    normalized_model = eve_model_topology.effective_substrate_model(config, model)
    fast_model = normalize_model_name(config.get("fast_model"))
    deep_model = normalize_model_name(config.get("deep_model"))
    fast_backend = normalize_optional_model_backend(config.get("fast_model_backend"))
    deep_backend = normalize_optional_model_backend(config.get("deep_model_backend"))
    if fast_backend and normalized_model == fast_model:
        return fast_backend
    if deep_backend and normalized_model == deep_model:
        return deep_backend
    return normalize_model_backend(config.get("model_backend"))


def llama_cpp_config_field(profile: str, suffix: str) -> str:
    return eve_model_topology.profile_config_field(profile, suffix)


def llama_cpp_profile_specs(config: Dict[str, object]) -> List[Dict[str, str]]:
    return [
        {
            "profile": str(spec.get("profile") or ""),
            "alias": str(spec.get("alias") or ""),
            "host": str(spec.get("host") or "").rstrip("/"),
        }
        for spec in eve_model_topology.all_profile_specs(config)
    ]


def llama_cpp_profile_spec_for_model(config: Dict[str, object], model: str) -> Optional[Dict[str, str]]:
    normalized_model = eve_model_topology.effective_substrate_model(config, model)
    if not normalized_model:
        return None
    for spec in llama_cpp_profile_specs(config):
        if normalized_model == normalize_model_name(spec.get("alias")):
            return spec
    return None


def llama_cpp_host_for_model(config: Dict[str, object], model: str) -> str:
    spec = llama_cpp_profile_spec_for_model(config, model)
    if spec:
        return str(spec.get("host") or "").rstrip("/")
    normalized_model = normalize_model_name(model)
    deep_model = normalize_model_name(config.get("deep_model"))
    if normalized_model and normalized_model == deep_model:
        deep_host = str(config.get("deep_llama_cpp_host") or "").strip()
        if deep_host:
            return deep_host
    return str(config.get("llama_cpp_host") or "http://127.0.0.1:8080").strip()


def llama_cpp_profile_name_for_model(config: Dict[str, object], model: str) -> str:
    spec = llama_cpp_profile_spec_for_model(config, model)
    if spec and spec.get("profile"):
        return str(spec["profile"])
    normalized_model = normalize_model_name(model)
    if normalized_model and normalized_model == normalize_model_name(config.get("deep_model")):
        return "deep"
    return "fast"


def llama_cpp_profile_config_value(
    config: Dict[str, object],
    model: str,
    suffix: str,
    fallback: object = None,
) -> object:
    profile = llama_cpp_profile_name_for_model(config, model)
    candidates = [config.get(llama_cpp_config_field(profile, suffix))]
    if profile != "fast":
        candidates.append(config.get(llama_cpp_config_field("fast", suffix)))
    for candidate in candidates:
        if candidate is not None and candidate != "":
            return candidate
    return fallback


def llama_cpp_chat_template_kwargs(config: Dict[str, object], model: str) -> Optional[Dict[str, object]]:
    raw_value = llama_cpp_profile_config_value(config, model, "chat_template_kwargs", None)
    if isinstance(raw_value, dict):
        return {str(key): value for key, value in raw_value.items()}
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return {str(key): value for key, value in parsed.items()}
    return None


def configured_model_host(config: Dict[str, object], model: str) -> str:
    backend = configured_model_backend(config, model)
    if backend == "llama_cpp":
        return llama_cpp_host_for_model(config, model)
    return str(config.get("ollama_host") or "http://127.0.0.1:11434").strip()


def configured_all_model_names(config: Dict[str, object]) -> List[str]:
    names: List[str] = []
    for key, value in config.items():
        if key == "model" or key.endswith("_model"):
            if key.startswith("experimental_"):
                continue
            normalized = eve_model_topology.effective_substrate_model(config, value)
            if normalized and normalized not in names:
                names.append(normalized)
    for item in config.get("resident_models") or []:
        normalized = eve_model_topology.effective_substrate_model(config, item)
        if normalized and normalized not in names:
            names.append(normalized)
    return names


def configured_model_names_for_backend(config: Dict[str, object], backend: str) -> List[str]:
    desired = normalize_model_backend(backend)
    return [
        name
        for name in configured_all_model_names(config)
        if configured_model_backend(config, name) == desired
    ]


def fetch_json(url: str, payload: Optional[Dict[str, object]] = None, timeout: int = 60) -> Dict[str, object]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")
    previous_handler = None

    def alarm_handler(signum, frame):
        raise FetchTimeoutError(f"Request to {url} timed out after {timeout}s")

    use_alarm = timeout > 0 and hasattr(signal, "SIGALRM") and hasattr(signal, "setitimer")
    if use_alarm:
        previous_handler = signal.signal(signal.SIGALRM, alarm_handler)
        signal.setitimer(signal.ITIMER_REAL, float(timeout))
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    finally:
        if use_alarm and previous_handler is not None:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)


def ollama_ready(host: str, timeout: int = 5) -> bool:
    try:
        fetch_json(host.rstrip("/") + "/api/tags", timeout=timeout)
        return True
    except Exception:
        return False


def llama_cpp_ready(host: str, timeout: int = 5) -> bool:
    try:
        fetch_json(host.rstrip("/") + "/v1/models", timeout=timeout)
        return True
    except Exception:
        return False


def launch_ollama(max_loaded_models: Optional[int] = None) -> None:
    serve_command: Optional[List[str]] = None
    app_binary = Path("/Applications/Ollama.app/Contents/Resources/ollama")
    if app_binary.exists():
        serve_command = [str(app_binary), "serve"]
    else:
        ollama_cli = shutil.which("ollama")
        if ollama_cli:
            serve_command = [ollama_cli, "serve"]
    if eve_platform.is_macos():
        subprocess.run(["launchctl", "setenv", "OLLAMA_KEEP_ALIVE", "-1"], check=False)
        if max_loaded_models:
            subprocess.run(
                ["launchctl", "setenv", "OLLAMA_MAX_LOADED_MODELS", str(max_loaded_models)],
                check=False,
            )
        if serve_command:
            subprocess.Popen(
                serve_command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        return
    if serve_command:
        subprocess.Popen(
            serve_command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )


def wait_for_ollama(host: str, seconds: int) -> bool:
    for _ in range(seconds):
        if ollama_ready(host, timeout=3):
            return True
        time.sleep(1)
    return False


def clear_ollama_launchctl_env() -> None:
    if eve_platform.is_macos():
        subprocess.run(["launchctl", "unsetenv", "OLLAMA_KEEP_ALIVE"], check=False)
        subprocess.run(["launchctl", "unsetenv", "OLLAMA_MAX_LOADED_MODELS"], check=False)


def wait_for_llama_cpp(host: str, seconds: int) -> bool:
    for _ in range(seconds):
        if llama_cpp_ready(host, timeout=3):
            return True
        time.sleep(1)
    return False


def list_loaded_models(host: str) -> List[Dict[str, object]]:
    try:
        data = fetch_json(host.rstrip("/") + "/api/ps", timeout=20)
    except Exception:
        return []
    models = data.get("models")
    return models if isinstance(models, list) else []


def loaded_model_map(host: str) -> Dict[str, Dict[str, object]]:
    records = {}
    for item in list_loaded_models(host):
        if not isinstance(item, dict):
            continue
        name = normalize_model_name(item.get("name") or item.get("model"))
        if not name:
            continue
        records[name] = item
        base_name = name.split(":")[0]
        records.setdefault(base_name, item)
    return records


def list_llama_cpp_models(host: str, timeout: int = 20) -> List[Dict[str, object]]:
    data = fetch_json(host.rstrip("/") + "/v1/models", timeout=timeout)
    models = data.get("data")
    return models if isinstance(models, list) else []


def llama_cpp_model_map(host: str) -> Dict[str, Dict[str, object]]:
    records = {}
    for item in list_llama_cpp_models(host):
        if not isinstance(item, dict):
            continue
        name = normalize_model_name(item.get("id"))
        if not name:
            continue
        records[name] = item
        records.setdefault(name.split(":")[0], item)
        for alias in item.get("aliases") or []:
            alias_name = normalize_model_name(alias)
            if alias_name:
                records.setdefault(alias_name, item)
                records.setdefault(alias_name.split(":")[0], item)
    return records


def llama_cpp_launch_label_for_model(config: Dict[str, object], model: str) -> str:
    spec = llama_cpp_profile_spec_for_model(config, model)
    profile = str(spec.get("profile") or "") if spec else ""
    if profile == "deep":
        return LLAMA_CPP_DEEP_LABEL
    if profile == "observer":
        return LLAMA_CPP_OBSERVER_LABEL
    if profile == "planner":
        return LLAMA_CPP_PLANNER_LABEL
    if profile == "relationship":
        return LLAMA_CPP_RELATIONSHIP_LABEL
    return LLAMA_CPP_FAST_LABEL


def reconcile_llama_cpp_service_topology(config: Dict[str, object]) -> Dict[str, object]:
    """Make launchd residency agree with the router's physical topology.

    All five plist definitions remain installed for rollback.  Only active
    substrate profiles are enabled; inactive shared-lane duplicates are
    booted out and disabled so KeepAlive cannot resurrect them.
    """
    snapshot = eve_model_topology.topology_snapshot(config)
    result: Dict[str, object] = {
        "mode": snapshot.get("mode"),
        "valid": bool(snapshot.get("valid")),
        "validation_errors": list(snapshot.get("validation_errors") or []),
        "active_labels": [
            str(item.get("launch_label") or "")
            for item in snapshot.get("active_substrates") or []
            if isinstance(item, dict)
        ],
        "inactive_labels": [
            str(item.get("launch_label") or "")
            for item in snapshot.get("inactive_substrates") or []
            if isinstance(item, dict)
        ],
        "operations": [],
    }
    if not result["valid"] or not eve_platform.is_macos():
        return result
    domain = f"gui/{os.getuid()}"
    operations: List[Dict[str, object]] = []
    for label in result["inactive_labels"]:
        target = f"{domain}/{label}"
        # An already-unloaded rollback service is the desired steady state.
        # launchctl reports that idempotent case as "No such process" on
        # stderr, so keep it in the return code record without emitting a
        # misleading watchdog warning on every healthy pass.
        bootout = subprocess.run(
            ["launchctl", "bootout", target],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        disabled = subprocess.run(["launchctl", "disable", target], check=False)
        operations.append(
            {
                "label": label,
                "desired": "inactive",
                "bootout_returncode": bootout.returncode,
                "disable_returncode": disabled.returncode,
            }
        )
    for label in result["active_labels"]:
        target = f"{domain}/{label}"
        enabled = subprocess.run(["launchctl", "enable", target], check=False)
        operations.append(
            {
                "label": label,
                "desired": "active",
                "enable_returncode": enabled.returncode,
            }
        )
    result["operations"] = operations
    return result


def restart_llama_cpp_service(config: Dict[str, object], model: str) -> bool:
    if not eve_platform.is_macos():
        return False
    label = llama_cpp_launch_label_for_model(config, model)
    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{label}"
    subprocess.run(["launchctl", "enable", target], check=False)
    result = subprocess.run(["launchctl", "kickstart", "-k", target], check=False)
    if result.returncode != 0:
        definition = eve_platform.service_definition_path(label)
        if definition.exists():
            subprocess.run(["launchctl", "bootstrap", domain, str(definition)], check=False)
            result = subprocess.run(["launchctl", "kickstart", "-k", target], check=False)
    return result.returncode == 0


def pin_model(host: str, model: str, timeout: int) -> Dict[str, object]:
    payload = {"model": model, "keep_alive": -1, "stream": False}
    started = time.time()
    try:
        response = fetch_json(host.rstrip("/") + "/api/generate", payload=payload, timeout=timeout)
        return {
            "ok": True,
            "wall_ms": round((time.time() - started) * 1000, 2),
            "done": response.get("done"),
        }
    except Exception as exc:
        return {
            "ok": False,
            "wall_ms": round((time.time() - started) * 1000, 2),
            "error": str(exc),
        }


def probe_model(host: str, model: str, max_tokens: int, timeout: int) -> Dict[str, object]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Return only the final answer. No hidden reasoning."},
            {"role": "user", "content": "Reply with exactly: ok"},
        ],
        "stream": False,
        "keep_alive": -1,
        "think": False,
        "options": {"num_predict": max_tokens},
    }
    started = time.time()
    try:
        response = fetch_json(host.rstrip("/") + "/api/chat", payload=payload, timeout=timeout)
        message = response.get("message") if isinstance(response.get("message"), dict) else {}
        content = str(message.get("content") or "").strip()
        thinking = str(message.get("thinking") or "").strip()
        success = bool(response.get("done")) and not bool(response.get("error")) and bool(content)
        return {
            "ok": success,
            "content": content[:80],
            "thinking": thinking[:80],
            "signal": "response" if content else "thinking_only" if thinking else "empty",
            "wall_ms": round((time.time() - started) * 1000, 2),
            "total_ms": round((float(response.get("total_duration") or 0) / 1_000_000), 2),
            "load_ms": round((float(response.get("load_duration") or 0) / 1_000_000), 2),
            "eval_count": response.get("eval_count"),
            "prompt_eval_count": response.get("prompt_eval_count"),
            "done_reason": response.get("done_reason"),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "wall_ms": round((time.time() - started) * 1000, 2),
        }


def probe_llama_cpp_model(
    host: str,
    model: str,
    max_tokens: int,
    timeout: int,
    chat_template_kwargs: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Return only the final answer. Reply with exactly: ok"},
        ],
        "stream": False,
        "max_tokens": max_tokens,
    }
    if chat_template_kwargs:
        payload["chat_template_kwargs"] = chat_template_kwargs
    started = time.time()
    try:
        response = fetch_json(host.rstrip("/") + "/v1/chat/completions", payload=payload, timeout=timeout)
        choices = response.get("choices") if isinstance(response.get("choices"), list) else []
        first_choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        message = first_choice.get("message") if isinstance(first_choice.get("message"), dict) else {}
        content = str(message.get("content") or first_choice.get("text") or "").strip()
        success = bool(content)
        return {
            "ok": success,
            "content": content[:80],
            "signal": "response" if content else "empty",
            "wall_ms": round((time.time() - started) * 1000, 2),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "wall_ms": round((time.time() - started) * 1000, 2),
        }


def update_failure_count(status: Dict[str, object], key: str, healthy: bool) -> int:
    failures = status.get("consecutive_failures")
    if not isinstance(failures, dict):
        failures = {}
    if healthy:
        failures[key] = 0
    else:
        failures[key] = int(failures.get(key) or 0) + 1
    status["consecutive_failures"] = failures
    return int(failures[key])


def read_config() -> Dict[str, object]:
    default = {
        "model_backend": "ollama",
        "model": "eve-deep",
        "fast_model": "eve-fast",
        "deep_model": "eve-deep",
        "fast_model_backend": None,
        "deep_model_backend": None,
        "resident_models": [],
        "preferred_fast_model": "eve-fast",
        "preferred_deep_model": "eve-deep",
        "ollama_host": "http://127.0.0.1:11434",
        "llama_cpp_host": "http://127.0.0.1:8080",
        "deep_llama_cpp_host": "",
        "observer_llama_cpp_host": "",
        "planner_llama_cpp_host": "",
        "relationship_llama_cpp_host": "",
        "model_lane_topology_mode": eve_model_topology.MODEL_LANE_TOPOLOGY_FIVE_ENDPOINT,
        "model_lane_three_substrate_profile_map": dict(
            eve_model_topology.THREE_SUBSTRATE_PROFILE_MAP
        ),
        "model_watchdog_interval_seconds": 300,
        "model_watchdog_probe_max_tokens": 32,
        "model_watchdog_failure_threshold": 2,
        "model_watchdog_timeout_seconds": 45,
        "model_watchdog_auto_fallback": True,
        "model_watchdog_fast_probe_interval_seconds": 300,
        "model_watchdog_deep_probe_interval_seconds": 1800,
    }
    data = load_json(CONFIG_PATH, default)
    for key, value in default.items():
        data.setdefault(key, value)
    if str(data.get("model_watchdog_timeout_seconds") or "").strip() == "90":
        data["model_watchdog_timeout_seconds"] = 45
    data["model_backend"] = normalize_model_backend(data.get("model_backend"))
    data["fast_model_backend"] = normalize_optional_model_backend(data.get("fast_model_backend"))
    data["deep_model_backend"] = normalize_optional_model_backend(data.get("deep_model_backend"))
    resident = []
    for item in data.get("resident_models") or []:
        normalized = normalize_model_name(item)
        if normalized and normalized not in resident:
            resident.append(normalized)
    data["resident_models"] = resident
    return data


def configured_model_names(config: Dict[str, object]) -> List[str]:
    return configured_model_names_for_backend(config, "ollama")


def target_loaded_model_cap(config: Dict[str, object]) -> int:
    return max(3, len(configured_model_names(config)))


def daemon_restart() -> Dict[str, object]:
    started = time.time()
    command = [PYTHON_BIN, str(ROOT / "eve.py"), "daemon", "install"]
    result = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True, check=False)
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "wall_ms": round((time.time() - started) * 1000, 2),
        "stdout": (result.stdout or "").strip()[:400],
        "stderr": (result.stderr or "").strip()[:400],
    }


def maybe_apply_fallback(
    config: Dict[str, object],
    status: Dict[str, object],
    probes: Dict[str, Dict[str, object]],
) -> Dict[str, object]:
    preferred_fast = normalize_model_name(config.get("preferred_fast_model")) or normalize_model_name(config.get("fast_model"))
    preferred_deep = normalize_model_name(config.get("preferred_deep_model")) or normalize_model_name(config.get("deep_model")) or preferred_fast
    preferred_fast_backend = configured_model_backend(config, preferred_fast)
    preferred_deep_backend = configured_model_backend(config, preferred_deep)
    failure_threshold = int(config.get("model_watchdog_failure_threshold") or 2)
    auto_fallback = bool(config.get("model_watchdog_auto_fallback"))

    fast_probe = probes.get(preferred_fast, {}) if preferred_fast_backend == "ollama" else {}
    deep_probe = probes.get(preferred_deep, {}) if preferred_deep_backend == "ollama" else {}
    fast_failures = (
        update_failure_count(status, preferred_fast, bool(fast_probe.get("ok")))
        if preferred_fast_backend == "ollama"
        else 0
    )
    deep_failures = (
        update_failure_count(status, preferred_deep, bool(deep_probe.get("ok")))
        if preferred_deep_backend == "ollama"
        else 0
    )

    desired_fast = preferred_fast
    desired_deep = preferred_deep
    desired_model = preferred_deep
    actions: List[str] = []

    if auto_fallback and preferred_fast_backend == "ollama" and preferred_deep_backend == "ollama":
        if not bool(fast_probe.get("ok")) and fast_failures >= failure_threshold and bool(deep_probe.get("ok")):
            desired_fast = preferred_deep
            actions.append("fallback_fast_to_deep")
        if not bool(deep_probe.get("ok")) and deep_failures >= failure_threshold and bool(fast_probe.get("ok")):
            desired_deep = preferred_fast
            desired_model = preferred_fast
            actions.append("fallback_deep_to_fast")

    changed = (
        normalize_model_name(config.get("fast_model")) != desired_fast
        or normalize_model_name(config.get("deep_model")) != desired_deep
        or normalize_model_name(config.get("model")) != desired_model
    )

    if changed:
        config["fast_model"] = desired_fast
        config["deep_model"] = desired_deep
        config["model"] = desired_model
        write_json(CONFIG_PATH, config)

    return {
        "changed": changed,
        "actions": actions,
        "effective_fast_model": desired_fast,
        "effective_deep_model": desired_deep,
        "effective_fallback_model": desired_model,
        "preferred_fast_model": preferred_fast,
        "preferred_deep_model": preferred_deep,
        "fast_failures": fast_failures,
        "deep_failures": deep_failures,
    }


def main() -> int:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w") as handle:
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return 0

        config = read_config()
        status = load_json(STATUS_PATH, {})
        host = str(config.get("ollama_host") or "http://127.0.0.1:11434")
        timeout_seconds = int(config.get("model_watchdog_timeout_seconds") or 180)
        probe_max_tokens = max(32, int(config.get("model_watchdog_probe_max_tokens") or 32))
        fast_probe_interval = int(config.get("model_watchdog_fast_probe_interval_seconds") or 300)
        deep_probe_interval = int(config.get("model_watchdog_deep_probe_interval_seconds") or 1800)
        all_models_to_watch = configured_all_model_names(config)
        ollama_models_to_watch = configured_model_names_for_backend(config, "ollama")
        llama_models_to_watch = configured_model_names_for_backend(config, "llama_cpp")
        desired_model_cap = max(3, len(ollama_models_to_watch))

        actions: List[str] = []
        service_topology = reconcile_llama_cpp_service_topology(config)
        if not service_topology.get("valid"):
            actions.append("invalid_model_service_topology")
        for operation in service_topology.get("operations") or []:
            if not isinstance(operation, dict) or operation.get("desired") != "inactive":
                continue
            if int(operation.get("bootout_returncode") or 0) == 0:
                actions.append(f"stop_inactive_llama_cpp:{operation.get('label')}")
        ollama_ready_now = True
        loaded_before: Dict[str, Dict[str, object]] = {}
        loaded_after: Dict[str, Dict[str, object]] = {}
        if not ollama_models_to_watch:
            clear_ollama_launchctl_env()
        if ollama_models_to_watch:
            if not ollama_ready(host):
                launch_ollama(max_loaded_models=desired_model_cap)
                actions.append("launch_ollama")
            ollama_ready_now = wait_for_ollama(host, seconds=45)
            if not ollama_ready_now:
                actions.append("ollama_unavailable")
            else:
                launchctl_set = None
                launchctl_model_cap = None
                if eve_platform.is_macos():
                    launchctl_set = subprocess.run(["launchctl", "setenv", "OLLAMA_KEEP_ALIVE", "-1"], check=False)
                    launchctl_model_cap = subprocess.run(
                        ["launchctl", "setenv", "OLLAMA_MAX_LOADED_MODELS", str(desired_model_cap)],
                        check=False,
                    )
                if launchctl_set is not None and launchctl_set.returncode == 0:
                    actions.append("set_keep_alive_forever")
                if launchctl_model_cap is not None and launchctl_model_cap.returncode == 0:
                    actions.append(f"set_max_loaded_models:{desired_model_cap}")
                loaded_before = loaded_model_map(host)

        pin_results: Dict[str, Dict[str, object]] = {}
        if ollama_ready_now and ollama_models_to_watch:
            for model in ollama_models_to_watch:
                if model not in loaded_before:
                    pin_results[model] = pin_model(host, model, timeout=timeout_seconds)
                    actions.append(f"repin:{model}")
            loaded_after = loaded_model_map(host)

        llama_host_ready: Dict[str, bool] = {}
        llama_visible_models: Dict[str, Dict[str, Dict[str, object]]] = {}
        llama_model_entries: Dict[str, List[Dict[str, object]]] = {}
        for model in llama_models_to_watch:
            model_host = configured_model_host(config, model)
            if not model_host or model_host in llama_host_ready:
                continue
            if not llama_cpp_ready(model_host):
                if restart_llama_cpp_service(config, model):
                    actions.append(f"restart_llama_cpp:{model}")
            ready = wait_for_llama_cpp(model_host, seconds=45)
            llama_host_ready[model_host] = ready
            if not ready:
                actions.append(f"llama_cpp_unavailable:{model_host}")
                continue
            llama_visible_models[model_host] = llama_cpp_model_map(model_host)
            llama_model_entries[model_host] = list_llama_cpp_models(model_host)

        previous_probes = status.get("probes") if isinstance(status.get("probes"), dict) else {}
        previous_probe_timestamps = (
            status.get("probe_timestamps") if isinstance(status.get("probe_timestamps"), dict) else {}
        )
        probes: Dict[str, Dict[str, object]] = {}
        probe_timestamps: Dict[str, str] = {}
        now = datetime.now(timezone.utc)
        preferred_fast = normalize_model_name(config.get("preferred_fast_model")) or normalize_model_name(config.get("fast_model"))
        preferred_deep = normalize_model_name(config.get("preferred_deep_model")) or normalize_model_name(config.get("deep_model"))
        preferred_fast_backend = configured_model_backend(config, preferred_fast)
        preferred_deep_backend = configured_model_backend(config, preferred_deep)
        top_level_timestamp = parse_timestamp(status.get("timestamp"))
        for model in all_models_to_watch:
            backend = configured_model_backend(config, model)
            model_host = configured_model_host(config, model)
            interval_seconds = deep_probe_interval if model == preferred_deep else fast_probe_interval
            cached_probe = previous_probes.get(model) if isinstance(previous_probes.get(model), dict) else None
            cached_timestamp = parse_timestamp(previous_probe_timestamps.get(model)) or top_level_timestamp
            if backend == "llama_cpp":
                model_loaded = model in (llama_visible_models.get(model_host) or {})
            else:
                model_loaded = model in loaded_after
            use_cache = (
                model == preferred_deep
                and
                cached_probe is not None
                and bool(cached_probe.get("ok"))
                and bool(str(cached_probe.get("content") or "").strip())
                and cached_timestamp is not None
                and model_loaded
                and (now - cached_timestamp).total_seconds() < interval_seconds
            )
            if use_cache:
                probe = dict(cached_probe)
                probe["cached"] = True
                probes[model] = probe
                probe_timestamps[model] = cached_timestamp.isoformat()
                continue
            if backend == "llama_cpp":
                if not llama_host_ready.get(model_host):
                    probe = {
                        "ok": False,
                        "error": f"llama.cpp host unavailable: {model_host}",
                        "wall_ms": 0.0,
                    }
                else:
                    probe = probe_llama_cpp_model(
                        model_host,
                        model,
                        probe_max_tokens,
                        timeout_seconds,
                        chat_template_kwargs=llama_cpp_chat_template_kwargs(config, model),
                    )
            else:
                if not ollama_ready_now:
                    probe = {
                        "ok": False,
                        "error": f"ollama host unavailable: {host}",
                        "wall_ms": 0.0,
                    }
                else:
                    probe = probe_model(host, model, probe_max_tokens, timeout_seconds)
            probes[model] = probe
            probe_timestamps[model] = now.isoformat()
        fallback = maybe_apply_fallback(config, status, probes)
        actions.extend(fallback["actions"])

        daemon_result = None
        if fallback["changed"]:
            daemon_result = daemon_restart()
            actions.append("daemon_reinstall" if daemon_result.get("ok") else "daemon_reinstall_failed")

        loaded_final = loaded_model_map(host) if ollama_ready_now else {}
        loaded_summary = []
        for name, item in loaded_final.items():
            if ":" in name:
                loaded_summary.append(
                    {
                        "name": name,
                        "backend": "ollama",
                        "host": host,
                        "context_length": item.get("context_length"),
                        "expires_at": item.get("expires_at"),
                        "size_vram": item.get("size_vram"),
                    }
                )
        for model_host, entries in llama_model_entries.items():
            for item in entries:
                if not isinstance(item, dict):
                    continue
                name = normalize_model_name(item.get("id"))
                if not name:
                    continue
                meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
                loaded_summary.append(
                    {
                        "name": name,
                        "backend": "llama_cpp",
                        "host": model_host,
                        "context_length": meta.get("n_ctx_train"),
                        "expires_at": None,
                        "size_vram": meta.get("size"),
                    }
                )
        loaded_summary.sort(key=lambda entry: str(entry.get("name")))

        def model_resident(model: str) -> bool:
            backend = configured_model_backend(config, model)
            if backend == "llama_cpp":
                model_host = configured_model_host(config, model)
                return model in (llama_visible_models.get(model_host) or {})
            return model in loaded_final

        overall_ready = (
            bool(service_topology.get("valid"))
            and (not ollama_models_to_watch or ollama_ready_now)
            and all(list(llama_host_ready.values()) or [True])
        )

        record = {
            "timestamp": utc_now(),
            "updated_at": utc_now(),
            "host": host,
            "ready": overall_ready,
            "model_topology": eve_model_topology.topology_snapshot(config),
            "service_topology_reconciliation": service_topology,
            "actions": actions,
            "recent_actions": actions[-6:],
            "preferred_fast_model": fallback["preferred_fast_model"],
            "preferred_deep_model": fallback["preferred_deep_model"],
            "effective_fast_model": fallback["effective_fast_model"],
            "effective_deep_model": fallback["effective_deep_model"],
            "effective_fallback_model": fallback["effective_fallback_model"],
            "llama_hosts": [
                {
                    "host": model_host,
                    "ready": ready,
                    "models": sorted((llama_visible_models.get(model_host) or {}).keys()),
                }
                for model_host, ready in sorted(llama_host_ready.items())
            ],
            "loaded_models": loaded_summary,
            "residency": {
                "preferred_fast_backend": preferred_fast_backend,
                "preferred_deep_backend": preferred_deep_backend,
                "preferred_fast_loaded": model_resident(fallback["preferred_fast_model"]),
                "preferred_deep_loaded": model_resident(fallback["preferred_deep_model"]),
                "both_preferred_loaded": (
                    model_resident(fallback["preferred_fast_model"])
                    and model_resident(fallback["preferred_deep_model"])
                ),
            },
            "pin_results": pin_results,
            "probes": probes,
            "probe_timestamps": probe_timestamps,
            "consecutive_failures": status.get("consecutive_failures", {}),
            "config_changed": fallback["changed"],
            "daemon_restart": daemon_result,
        }
        status.update(record)
        write_health_status(status)
        append_health_log(record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
