#!/usr/bin/env python3
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_platform
import eve_profile
import eve_store

APP_DIR = ROOT / ".eve"
RUNTIME_DIR = eve_platform.runtime_dir()
RUNTIME_APP_DIR = RUNTIME_DIR / ".eve"
SNAPSHOT_PATH = APP_DIR / "system_snapshot.json"
ACTIVITY_LOG_PATH = APP_DIR / "system_activity.jsonl"
RUNTIME_SNAPSHOT_PATH = RUNTIME_APP_DIR / "system_snapshot.json"
RUNTIME_ACTIVITY_LOG_PATH = RUNTIME_APP_DIR / "system_activity.jsonl"
LOCK_PATH = APP_DIR / "system_observer.lock"
WORKSPACE_SCAN_INTERVAL_SECONDS = 900
TOP_PROCESS_LIMIT = 8
WORKSPACE_FOCUS_LIMIT = 6
WORKSPACE_CHANGE_LIMIT = 6
WORKSPACE_PREVIEW_CHAR_LIMIT = 180
WORKSPACE_PREVIEW_LINE_SCAN_LIMIT = 80
WORKSPACE_PREVIEW_MAX_BYTES = 250000
WORKSPACE_FOCUS_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".md",
    ".modelfile",
    ".m",
    ".plist",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default: Dict[str, object]) -> Dict[str, object]:
    return eve_store.load_json_dict(path, default=default)


def write_json(path: Path, payload: Dict[str, object]) -> None:
    eve_store.write_json_dict(path, payload)


def append_jsonl(path: Path, payload: Dict[str, object]) -> None:
    eve_store.append_jsonl_record(path, payload, ensure_ascii=True)


def write_snapshot(payload: Dict[str, object]) -> None:
    write_json(SNAPSHOT_PATH, payload)
    if RUNTIME_APP_DIR.exists():
        write_json(RUNTIME_SNAPSHOT_PATH, payload)


def append_activity(payload: Dict[str, object]) -> None:
    append_jsonl(ACTIVITY_LOG_PATH, payload)
    if RUNTIME_APP_DIR.exists():
        append_jsonl(RUNTIME_ACTIVITY_LOG_PATH, payload)


def run_command(cmd: List[str], timeout: int = 5) -> Tuple[int, str, str]:
    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = str(exc)
        return 124, stdout, stderr
    return result.returncode, (result.stdout or "").strip(), (result.stderr or "").strip()


def safe_int(value: object) -> Optional[int]:
    try:
        return int(str(value).strip())
    except Exception:
        return None


def safe_float(value: object) -> Optional[float]:
    try:
        return float(str(value).strip())
    except Exception:
        return None


def sysctl_value(name: str) -> Optional[str]:
    code, stdout, _ = run_command(["sysctl", "-n", name], timeout=3)
    return stdout if code == 0 and stdout else None


def parse_iso(value: object) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def battery_status() -> Dict[str, object]:
    if eve_platform.is_linux():
        power_supply_dir = Path("/sys/class/power_supply")
        if not power_supply_dir.exists():
            return {}
        battery_dirs = [path for path in power_supply_dir.iterdir() if path.is_dir() and path.name.upper().startswith("BAT")]
        adapter_dirs = [
            path
            for path in power_supply_dir.iterdir()
            if path.is_dir() and any(token in path.name.upper() for token in ["AC", "ADP", "MAINS"])
        ]
        percent = None
        charging = None
        if battery_dirs:
            capacity_path = battery_dirs[0] / "capacity"
            status_path = battery_dirs[0] / "status"
            if capacity_path.exists():
                percent = safe_int(capacity_path.read_text().strip())
            if status_path.exists():
                status_text = status_path.read_text().strip().lower()
                if status_text in {"charging", "full"}:
                    charging = True
                elif status_text in {"discharging", "not charging"}:
                    charging = False
        power_source = "Battery Power"
        for adapter_dir in adapter_dirs:
            online_path = adapter_dir / "online"
            if online_path.exists() and safe_int(online_path.read_text().strip()) == 1:
                power_source = "AC Power"
                break
        return {
            "power_source": power_source,
            "percent": percent,
            "charging": charging,
        }
    if not eve_platform.is_macos():
        return {}
    code, stdout, _ = run_command(["pmset", "-g", "batt"], timeout=4)
    if code != 0 or not stdout:
        return {}
    lines = stdout.splitlines()
    if len(lines) < 2:
        return {"raw": stdout[:200]}
    power_source = lines[0].replace("Now drawing from ", "").strip().strip("'")
    detail = lines[1]
    percent = safe_int(re.search(r"(\d+)%", detail).group(1)) if re.search(r"(\d+)%", detail) else None
    charging = None
    estimate = None
    battery_id = None
    if "(" in detail and "id=" in detail:
        try:
            battery_id = detail.split("id=", 1)[1].split(")", 1)[0]
        except Exception:
            battery_id = None
    lowered = detail.lower()
    if "charging" in lowered or "charged" in lowered:
        charging = True
    elif "discharging" in lowered:
        charging = False
    if ";" in detail:
        estimate = ";".join(part.strip() for part in detail.split(";")[1:] if part.strip()) or None
    return {
        "power_source": power_source,
        "battery_id": battery_id,
        "percent": percent,
        "charging": charging,
        "estimate": estimate,
    }


def frontmost_app() -> Optional[str]:
    if not eve_platform.is_macos():
        return None
    code, stdout, _ = run_command(
        [
            "osascript",
            "-e",
            'tell application "System Events" to get name of first application process whose frontmost is true',
        ],
        timeout=4,
    )
    return stdout if code == 0 and stdout else None


def idle_seconds() -> Optional[int]:
    if not eve_platform.is_macos():
        return None
    code, stdout, _ = run_command(
        ["/bin/zsh", "-lc", r"ioreg -c IOHIDSystem | awk '/HIDIdleTime/ {print int($NF/1000000000); exit}'"],
        timeout=4,
    )
    return safe_int(stdout) if code == 0 else None


def load_average_state(loads: Tuple[float, float, float], cpu_count: Optional[int]) -> str:
    if not cpu_count or cpu_count <= 0:
        return "unknown"
    ratio = loads[0] / cpu_count
    if ratio < 0.25:
        return "calm"
    if ratio < 0.55:
        return "busy"
    return "hot"


def macos_volume_capacity(path: Path) -> Dict[str, object]:
    if not eve_platform.is_macos():
        return {}
    script_path = ROOT / "bin" / "eve_macos_volume_capacity.swift"
    if not script_path.exists():
        return {}
    code, stdout, stderr = run_command(["swift", str(script_path), str(path)], timeout=8)
    if code != 0 or not stdout:
        return {"capacity_probe_error": (stderr or f"swift exited {code}")[:240]}
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return {"capacity_probe_error": f"invalid swift capacity JSON: {exc}"[:240]}
    return payload if isinstance(payload, dict) else {}


def positive_int(mapping: Dict[str, object], key: str) -> Optional[int]:
    value = safe_int(mapping.get(key))
    return value if value is not None and value > 0 else None


def disk_status() -> Dict[str, object]:
    path = ROOT
    usage = shutil.disk_usage(path)
    strict_free = usage.free
    total = usage.total
    capacity = macos_volume_capacity(path)
    mac_total = positive_int(capacity, "total_bytes")
    if mac_total:
        total = mac_total
    important_free = positive_int(capacity, "important_available_bytes")
    available_free = positive_int(capacity, "available_bytes")
    free = important_free or available_free or strict_free
    used = max(total - free, 0)
    strict_used = max(total - strict_free, 0)
    percent = round((used / total) * 100, 1) if total else 0.0
    strict_percent = round((strict_used / total) * 100, 1) if total else 0.0
    source = "macos_important_usage" if important_free else ("macos_available" if available_free else "posix_statvfs")
    return {
        "path": str(path),
        "volume_name": capacity.get("volume_name"),
        "capacity_source": source,
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "used_percent": percent,
        "strict_free_bytes": strict_free,
        "strict_used_percent": strict_percent,
        "available_bytes": available_free,
        "important_available_bytes": important_free,
        "opportunistic_available_bytes": positive_int(capacity, "opportunistic_available_bytes"),
        "capacity_probe_error": capacity.get("capacity_probe_error"),
    }


def top_processes(limit: int = TOP_PROCESS_LIMIT) -> List[Dict[str, object]]:
    code, stdout, _ = run_command(
        ["ps", "-axo", "pid,%cpu,%mem,rss,comm", "-r"],
        timeout=5,
    )
    if code != 0 or not stdout:
        return []
    rows = stdout.splitlines()[1 : limit + 1]
    processes: List[Dict[str, object]] = []
    for row in rows:
        parts = row.split(None, 4)
        if len(parts) != 5:
            continue
        pid, cpu, mem, rss, command = parts
        processes.append(
            {
                "pid": safe_int(pid),
                "cpu_percent": safe_float(cpu),
                "memory_percent": safe_float(mem),
                "rss_kb": safe_int(rss),
                "command": command,
            }
        )
    return processes


def launch_agent_state(label: str) -> Dict[str, object]:
    if eve_platform.is_windows() and eve_platform.command_available("schtasks"):
        code, stdout, stderr = run_command(["schtasks", "/Query", "/TN", label, "/FO", "LIST", "/V"], timeout=5)
        if code != 0:
            return {"label": label, "loaded": False, "state": "missing", "error": (stderr or stdout)[:200]}
        values: Dict[str, str] = {}
        for line in stdout.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            values[key.strip().lower()] = value.strip()
        state = values.get("status") or "unknown"
        return {
            "label": label,
            "loaded": state.lower() not in {"could not start", "disabled", "queued"},
            "state": state,
            "last_exit_code": values.get("last result"),
            "next_run_time": values.get("next run time"),
            "task_to_run": values.get("task to run"),
        }
    if eve_platform.is_linux() and eve_platform.command_available("systemctl"):
        unit = f"{label}.service"
        code, stdout, stderr = run_command(["systemctl", "--user", "show", unit, "--no-pager"], timeout=5)
        if code != 0:
            return {"label": label, "loaded": False, "state": "missing", "error": (stderr or stdout)[:200]}
        values: Dict[str, str] = {}
        for line in stdout.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
        active = values.get("ActiveState") or "unknown"
        substate = values.get("SubState") or ""
        return {
            "label": label,
            "loaded": active not in {"inactive", "failed", "unknown"},
            "state": f"{active}/{substate}".strip("/"),
            "unit_file_state": values.get("UnitFileState"),
            "fragment_path": values.get("FragmentPath"),
            "last_exit_code": values.get("ExecMainStatus"),
        }
    uid = str(os.getuid())
    code, stdout, stderr = run_command(["launchctl", "print", f"gui/{uid}/{label}"], timeout=5)
    if code != 0:
        return {"label": label, "loaded": False, "state": "missing", "error": stderr[:200]}
    state = None
    launchctl_state = None
    last_exit = None
    run_interval_seconds = None
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("state = "):
            launchctl_state = stripped.split("=", 1)[1].strip()
            state = launchctl_state
        elif stripped.startswith("last exit code = "):
            last_exit = stripped.split("=", 1)[1].strip()
        elif stripped.startswith("run interval = "):
            match = re.search(r"(\d+)", stripped)
            if match:
                run_interval_seconds = safe_int(match.group(1))
    if (
        state == "not running"
        and run_interval_seconds
        and str(last_exit or "").strip() in {"", "0"}
    ):
        state = "scheduled"
    return {
        "label": label,
        "loaded": True,
        "state": state,
        "launchctl_state": launchctl_state,
        "last_exit_code": last_exit,
        "run_interval_seconds": run_interval_seconds,
    }


def model_status_timestamp(status: Dict[str, object]) -> float:
    updated_at = parse_iso(status.get("updated_at") or status.get("timestamp"))
    return updated_at.timestamp() if updated_at is not None else float("-inf")


def load_model_status() -> Dict[str, object]:
    candidates: List[Tuple[float, int, Dict[str, object]]] = []
    for preference_rank, path in enumerate(
        [RUNTIME_APP_DIR / "model_watchdog_status.json", APP_DIR / "model_watchdog_status.json"]
    ):
        if not path.exists():
            continue
        data = load_json(path, {})
        if data:
            candidates.append((model_status_timestamp(data), -preference_rank, data))
    if not candidates:
        return {}
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def model_summary_from_status(model_status: Dict[str, object]) -> Optional[str]:
    if not isinstance(model_status, dict) or not model_status:
        return None
    summary = str(model_status.get("summary") or "").strip()
    if summary:
        return summary
    fast = str(model_status.get("preferred_fast_model") or model_status.get("effective_fast_model") or "").strip()
    deep = str(model_status.get("preferred_deep_model") or model_status.get("effective_deep_model") or "").strip()
    residency = model_status.get("residency") if isinstance(model_status.get("residency"), dict) else {}
    parts = []
    if fast:
        parts.append(f"Fast {fast}")
    if deep:
        parts.append(f"Deep {deep}")
    if residency.get("both_preferred_loaded"):
        parts.append("both resident")
    elif residency:
        parts.append(
            f"fast {'up' if residency.get('preferred_fast_loaded') else 'down'} / "
            f"deep {'up' if residency.get('preferred_deep_loaded') else 'down'}"
        )
    return " · ".join(parts) if parts else None


def normalize_preview_line(text: str) -> str:
    return " ".join(text.split()).strip()


def workspace_focus_category(relative: Path) -> str:
    suffix = relative.suffix.lower()
    if suffix in {".py", ".js", ".jsx", ".ts", ".tsx", ".swift", ".go", ".rs", ".java", ".c", ".cc", ".cpp", ".h", ".hpp"}:
        return "code"
    if suffix in {".md", ".txt"}:
        return "docs"
    if suffix in {".sh"}:
        return "script"
    if suffix in {".json", ".yaml", ".yml", ".toml", ".plist", ".modelfile"}:
        return "config"
    if suffix in {".html", ".css"}:
        return "ui"
    return "workspace"


def is_workspace_focus_candidate(relative: Path, size_bytes: int) -> bool:
    parts = relative.parts
    if not parts:
        return False
    top_level = parts[0]
    if top_level == ".git" or top_level == "__pycache__" or top_level.startswith(".eve"):
        return False
    if top_level == "coordination":
        return False
    if size_bytes <= 0 or size_bytes > WORKSPACE_PREVIEW_MAX_BYTES:
        return False
    suffix = relative.suffix.lower()
    return suffix in WORKSPACE_FOCUS_SUFFIXES or relative.name.upper() == "README"


def preview_candidates_for_category(lines: List[str], category: str) -> List[str]:
    if category == "code":
        candidates = [
            line
            for line in lines
            if re.match(r"^(async\s+def|def|class|struct|enum|func|const|let|var|public\s+|private\s+|final\s+class)", line)
        ]
        if candidates:
            return candidates
    if category == "docs":
        headings = [line for line in lines if line.startswith("#")]
        if headings:
            return headings
    if category == "config":
        keyed = [line for line in lines if re.match(r"^[A-Za-z0-9_.-]+\s*[:=]", line)]
        if keyed:
            return keyed
    if category == "script":
        script_lines = [line for line in lines if line.startswith("#!") or re.match(r"^(function\s+|[A-Za-z0-9_-]+\s*\(\)\s*\{)", line)]
        if script_lines:
            return script_lines
    if category == "ui":
        ui_lines = [line for line in lines if re.match(r"^(<[^>]+>|export\s+default|function\s+|const\s+|body\s*\{|@media)", line)]
        if ui_lines:
            return ui_lines
    return lines


def read_workspace_focus_preview(relative_path: str) -> str:
    path = ROOT / relative_path
    if not path.exists() or not path.is_file():
        return ""
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    if not raw.strip():
        return ""
    category = workspace_focus_category(Path(relative_path))
    lines = [
        normalize_preview_line(line)
        for line in raw.splitlines()[:WORKSPACE_PREVIEW_LINE_SCAN_LIMIT]
        if normalize_preview_line(line)
    ]
    if not lines:
        return ""
    for line in preview_candidates_for_category(lines, category):
        if line:
            return line[:WORKSPACE_PREVIEW_CHAR_LIMIT]
    return lines[0][:WORKSPACE_PREVIEW_CHAR_LIMIT]


def build_workspace_focus(recent_files: List[Tuple[float, str, int]]) -> Dict[str, object]:
    focus_files: List[Dict[str, object]] = []
    focus_area_counter: Counter[str] = Counter()
    for modified_at, relative_path, size_bytes in recent_files:
        relative = Path(relative_path)
        if not is_workspace_focus_candidate(relative, size_bytes):
            continue
        preview = read_workspace_focus_preview(relative_path)
        if not preview:
            continue
        top_level = relative.parts[0] if len(relative.parts) > 1 else "root"
        focus_area_counter[top_level] += 1
        focus_files.append(
            {
                "path": relative_path,
                "bytes": size_bytes,
                "modified_at": datetime.fromtimestamp(modified_at, timezone.utc).isoformat(),
                "category": workspace_focus_category(relative),
                "preview": preview,
            }
        )
        if len(focus_files) >= WORKSPACE_FOCUS_LIMIT:
            break
    return {
        "focus_areas": dict(focus_area_counter.most_common(6)),
        "focus_files": focus_files,
    }


def tracked_workspace_file_record(relative: Path, stat: os.stat_result) -> Dict[str, object]:
    return {
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "bytes": stat.st_size,
        "category": workspace_focus_category(relative),
    }


def workspace_change_item(path: str, change_type: str, metadata: Dict[str, object]) -> Dict[str, object]:
    preview = ""
    if change_type != "removed":
        preview = read_workspace_focus_preview(path)
    return {
        "path": path,
        "change": change_type,
        "modified_at": metadata.get("modified_at"),
        "bytes": metadata.get("bytes"),
        "category": metadata.get("category"),
        "preview": preview,
    }


def build_workspace_changes(
    previous_workspace: Dict[str, object],
    tracked_files: Dict[str, Dict[str, object]],
) -> Dict[str, object]:
    previous_tracked = previous_workspace.get("tracked_files") if isinstance(previous_workspace.get("tracked_files"), dict) else {}
    if not previous_tracked:
        return {
            "recent_changes": [],
            "recent_changes_summary": "Initial workspace scan.",
        }

    added_or_updated: List[Tuple[float, str, str, Dict[str, object]]] = []
    removed: List[Tuple[float, str, Dict[str, object]]] = []

    for path, metadata in tracked_files.items():
        previous_metadata = previous_tracked.get(path)
        modified_at = parse_iso(metadata.get("modified_at"))
        sort_key = modified_at.timestamp() if modified_at is not None else 0.0
        if not isinstance(previous_metadata, dict):
            added_or_updated.append((sort_key, path, "added", metadata))
            continue
        if str(metadata.get("modified_at") or "") != str(previous_metadata.get("modified_at") or ""):
            added_or_updated.append((sort_key, path, "updated", metadata))

    for path, previous_metadata in previous_tracked.items():
        if path in tracked_files or not isinstance(previous_metadata, dict):
            continue
        modified_at = parse_iso(previous_metadata.get("modified_at"))
        sort_key = modified_at.timestamp() if modified_at is not None else 0.0
        removed.append((sort_key, path, previous_metadata))

    added_or_updated.sort(key=lambda item: item[0], reverse=True)
    removed.sort(key=lambda item: item[0], reverse=True)

    recent_changes: List[Dict[str, object]] = []
    for _, path, change_type, metadata in added_or_updated[:WORKSPACE_CHANGE_LIMIT]:
        recent_changes.append(workspace_change_item(path, change_type, metadata))
    remaining_slots = max(0, WORKSPACE_CHANGE_LIMIT - len(recent_changes))
    for _, path, metadata in removed[:remaining_slots]:
        recent_changes.append(workspace_change_item(path, "removed", metadata))

    change_counts = {
        "added": sum(1 for _, _, change_type, _ in added_or_updated if change_type == "added"),
        "updated": sum(1 for _, _, change_type, _ in added_or_updated if change_type == "updated"),
        "removed": len(removed),
    }
    changed_labels = [f"{item['change']} {item['path']}" for item in recent_changes[:3]]
    summary_parts: List[str] = []
    for label in ["added", "updated", "removed"]:
        count = change_counts[label]
        if count:
            summary_parts.append(f"{count} {label}")
    if changed_labels:
        summary_parts.append("top: " + "; ".join(changed_labels))
    summary = " | ".join(summary_parts) if summary_parts else "No recent tracked workspace changes."

    return {
        "recent_changes": recent_changes,
        "recent_changes_summary": summary,
    }


def project_file_counts() -> Dict[str, object]:
    extension_counter: Counter[str] = Counter()
    top_level_counter: Counter[str] = Counter()
    recent_files: List[Tuple[float, str, int]] = []
    tracked_files: Dict[str, Dict[str, object]] = {}
    total_files = 0
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        parts = relative.parts
        if parts and parts[0] in {".git", "__pycache__"}:
            continue
        if ".DS_Store" in path.name:
            continue
        total_files += 1
        top_level = parts[0] if parts else "."
        top_level_counter[top_level] += 1
        extension = path.suffix.lower() or "<no_ext>"
        extension_counter[extension] += 1
        try:
            stat = path.stat()
        except OSError:
            continue
        recent_files.append((stat.st_mtime, str(relative), stat.st_size))
        if is_workspace_focus_candidate(relative, stat.st_size):
            tracked_files[str(relative)] = tracked_workspace_file_record(relative, stat)
    recent_files.sort(reverse=True)
    focus = build_workspace_focus(recent_files)
    return {
        "total_files": total_files,
        "top_level_counts": dict(top_level_counter.most_common(10)),
        "top_extensions": dict(extension_counter.most_common(12)),
        "recent_files": [
            {
                "path": item[1],
                "bytes": item[2],
                "modified_at": datetime.fromtimestamp(item[0], timezone.utc).isoformat(),
            }
            for item in recent_files[:12]
        ],
        "focus_areas": focus["focus_areas"],
        "focus_files": focus["focus_files"],
        "tracked_files": tracked_files,
    }


def build_workspace_snapshot(previous: Dict[str, object]) -> Tuple[Dict[str, object], bool]:
    previous_snapshot = previous.get("workspace") if isinstance(previous.get("workspace"), dict) else {}
    last_scanned = parse_iso(previous_snapshot.get("scanned_at"))
    if last_scanned is not None and (datetime.now(timezone.utc) - last_scanned).total_seconds() < WORKSPACE_SCAN_INTERVAL_SECONDS:
        return previous_snapshot, False
    workspace = project_file_counts()
    workspace_changes = build_workspace_changes(previous_snapshot, workspace.get("tracked_files") if isinstance(workspace.get("tracked_files"), dict) else {})
    workspace["recent_changes"] = workspace_changes["recent_changes"]
    workspace["recent_changes_summary"] = workspace_changes["recent_changes_summary"]
    workspace["scanned_at"] = utc_now()
    return workspace, True


def snapshot_summary(snapshot: Dict[str, object]) -> str:
    frontmost = snapshot.get("frontmost_app") or "unknown app"
    model_summary = snapshot.get("model_summary") or "no model summary"
    idle = snapshot.get("idle_seconds")
    idle_text = f"idle {idle}s" if isinstance(idle, int) else "idle unknown"
    return f"{frontmost} · {model_summary} · {idle_text}"


def change_events(previous: Dict[str, object], current: Dict[str, object], workspace_refreshed: bool) -> List[str]:
    events: List[str] = []
    if previous.get("frontmost_app") != current.get("frontmost_app"):
        if current.get("frontmost_app"):
            events.append(f"frontmost_app:{current['frontmost_app']}")
    previous_power = previous.get("battery") if isinstance(previous.get("battery"), dict) else {}
    current_power = current.get("battery") if isinstance(current.get("battery"), dict) else {}
    if previous_power.get("power_source") != current_power.get("power_source"):
        if current_power.get("power_source"):
            events.append(f"power_source:{current_power['power_source']}")
    prev_percent = previous_power.get("percent")
    curr_percent = current_power.get("percent")
    if isinstance(prev_percent, int) and isinstance(curr_percent, int) and abs(curr_percent - prev_percent) >= 5:
        events.append(f"battery:{curr_percent}")
    if previous.get("load_state") != current.get("load_state"):
        events.append(f"load_state:{current.get('load_state')}")
    if previous.get("model_summary") != current.get("model_summary"):
        events.append("model_summary_changed")
    previous_services = previous.get("eve_services") if isinstance(previous.get("eve_services"), dict) else {}
    current_services = current.get("eve_services") if isinstance(current.get("eve_services"), dict) else {}
    if previous_services != current_services and current_services:
        events.append("eve_services_changed")
    if workspace_refreshed:
        events.append("workspace_refreshed")
    current_workspace = current.get("workspace") if isinstance(current.get("workspace"), dict) else {}
    recent_changes = current_workspace.get("recent_changes") if isinstance(current_workspace.get("recent_changes"), list) else []
    if recent_changes:
        events.append("workspace_changes_detected")
    return events


def eve_freshness_check(previous: Dict[str, object]) -> Dict[str, object]:
    """Second-layer dead-man freshness check (banner-only; the primary alerter
    is the standalone Eve dead-man agent, which has no Eve imports).
    Stats the runtime liveness artifacts and reports stale ones in the snapshot."""
    import time as _time

    now = _time.time()
    targets = {
        "presence_pulses": (RUNTIME_APP_DIR / "presence_pulses.jsonl", 3 * 3600),
        "gateway_state": (Path.home() / ".openclaw-eve-repair" / "state" / "openclaw.sqlite", 2 * 3600),
        "dreams": (RUNTIME_DIR / "openclaw" / "DREAMS.md", 30 * 3600),
    }
    stale = []
    detail: Dict[str, object] = {}
    for name, (path, threshold) in targets.items():
        try:
            age = int(now - path.stat().st_mtime)
        except OSError:
            age = -1
        detail[name] = {"age_seconds": age, "threshold_seconds": threshold}
        if age < 0 or age > threshold:
            stale.append(name)
    previous_freshness = previous.get("freshness") if isinstance(previous.get("freshness"), dict) else {}
    previous_stale = previous_freshness.get("stale") if isinstance(previous_freshness.get("stale"), list) else []
    newly_stale = [name for name in stale if name not in previous_stale]
    if newly_stale:
        try:
            subprocess.run(
                [
                    "/usr/bin/osascript",
                    "-e",
                    f'display notification "stale: {", ".join(stale)}" with title "Eve freshness (observer)"',
                ],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass
    detail["stale"] = stale
    return detail


def observe_system() -> int:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w") as handle:
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return 0

        previous = load_json(SNAPSHOT_PATH, {})

        cpu_count = safe_int(sysctl_value("hw.ncpu"))
        physical_cpu = safe_int(sysctl_value("hw.physicalcpu"))
        performance_cpu = safe_int(sysctl_value("hw.perflevel0.physicalcpu"))
        efficiency_cpu = safe_int(sysctl_value("hw.perflevel1.physicalcpu"))
        memory_bytes = safe_int(sysctl_value("hw.memsize"))
        load1, load5, load15 = os.getloadavg()
        battery = battery_status()
        disk = disk_status()
        frontmost = frontmost_app()
        idle = idle_seconds()
        top_cpu_processes = top_processes()
        workspace, workspace_refreshed = build_workspace_snapshot(previous)
        model_status = load_model_status()
        model_summary = model_summary_from_status(model_status)
        eve_services = {
            "daemon": launch_agent_state(eve_profile.service_label()),
            "model_warm": launch_agent_state(eve_profile.service_label("model-warm")),
            "model_watchdog": launch_agent_state(eve_profile.service_label("model-watchdog")),
        }

        snapshot = {
            "timestamp": utc_now(),
            "hostname": socket.gethostname(),
            "platform": eve_platform.platform_capabilities(),
            "hardware": {
                "cpu_count": cpu_count,
                "physical_cpu": physical_cpu,
                "performance_cores": performance_cpu,
                "efficiency_cores": efficiency_cpu,
                "memory_bytes": memory_bytes,
            },
            "load_average": {
                "one": round(load1, 2),
                "five": round(load5, 2),
                "fifteen": round(load15, 2),
            },
            "load_state": load_average_state((load1, load5, load15), cpu_count),
            "battery": battery,
            "disk": disk,
            "frontmost_app": frontmost,
            "idle_seconds": idle,
            "model_summary": model_summary,
            "model_status": {
                "updated_at": model_status.get("updated_at"),
                "preferred_fast_model": model_status.get("preferred_fast_model"),
                "preferred_deep_model": model_status.get("preferred_deep_model"),
                "residency": model_status.get("residency"),
                "recent_actions": model_status.get("recent_actions"),
                "probes": model_status.get("probes"),
            },
            "eve_services": eve_services,
            "freshness": eve_freshness_check(previous),
            "top_processes": top_cpu_processes,
            "workspace": workspace,
            "summary": "",
        }
        snapshot["summary"] = snapshot_summary(snapshot)

        write_snapshot(snapshot)
        events = change_events(previous, snapshot, workspace_refreshed)
        if events or not ACTIVITY_LOG_PATH.exists():
            append_activity(
                {
                    "timestamp": snapshot["timestamp"],
                    "summary": snapshot["summary"],
                    "events": events or ["initial_snapshot"],
                    "frontmost_app": frontmost,
                    "load_state": snapshot["load_state"],
                    "model_summary": model_summary,
                    "battery": battery,
                }
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(observe_system())
