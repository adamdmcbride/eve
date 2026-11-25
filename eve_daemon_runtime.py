"""Core runner ownership and cycle activity, independent of cognition policy.

The kernel lock is the authority. JSON records are diagnostic receipts only.
Source and runtime entrypoints share a lease under their configured runtime
directory, outside the mirrored continuity store and Python bundle manifest.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import csv
import json
import os
from pathlib import Path
import stat
import subprocess
import threading
import time
import uuid

import eve_store


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def owner_path(runtime_dir: Path) -> Path:
    return runtime_dir / ".eve-daemon-owner.json"


def _check_process(pid: int) -> None:
    if os.name != "nt":
        os.kill(pid, 0)
        return
    # Windows os.kill(pid, 0) terminates, rather than probes, a process.
    # Query only; never send a signal to establish liveness.
    result = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, timeout=3, check=False,
    )
    if result.returncode:
        raise OSError("process_query_failed")
    if not any(len(row) > 1 and row[1] == str(pid) for row in csv.reader(result.stdout.splitlines())):
        raise ProcessLookupError("owner_process_missing")


def _read_record(path: Path, limit: int = 16384) -> dict:
    """Bound local diagnostic reads; never hydrate optional cloud evidence."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or getattr(info, "st_flags", 0) & 0x40000000:
        raise ValueError("record_not_local_regular_file")
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("record_size_or_type_invalid")
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("record_too_large")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("record_not_object")
    return value


def inspect_runner(runtime_dir: Path) -> dict:
    """Read lock ownership separately from the last reported PID/run mode.

    This is an instantaneous diagnostic, not permission for a later run. Only
    runner_lease can authorize entry. A killed owner's receipt can remain on
    disk indefinitely without blocking a replacement or proving liveness.
    """
    path = owner_path(runtime_dir)
    lock_path = path.with_name(f".{path.name}.lock")
    if not path.exists() and not lock_path.exists():
        return {"lease_held": False, "owner_receipt": {}, "path": str(path)}
    try:
        with eve_store.file_lock(path, blocking=False, reentrant=False):
            held = False
    except eve_store.LockBusy:
        held = True
    error = ""
    try:
        record = _read_record(path)
    except FileNotFoundError:
        record = {}
    except (OSError, ValueError) as exc:
        record, error = {}, type(exc).__name__
    return {"lease_held": held, "owner_receipt": record, "path": str(path), "read_error": error}


def observe_runner(runtime_dir: Path, *, code_roots) -> dict:
    """Join only operational fields from one stable, lease-backed owner.

    This never selects a repository, copies data, hydrates ledgers, or grants
    write authority. Roots are supplied by the caller, not trusted from JSON.
    Missing/inconsistent evidence for an owned runner is not a native fallback.
    """
    result = {"available": False, "consistent": False, "state": {}, "activity": {}}
    try:
        before = inspect_runner(runtime_dir)
        result["ownership"] = before
        owner = before.get("owner_receipt") or {}
        if not (before["lease_held"] or owner or before.get("read_error")):
            return result
        result["available"] = True
        if not before["lease_held"]:
            result["problem"] = "owner_not_held"
            return result
        roots = {Path(root).resolve() for root in code_roots}
        code = Path(str(owner.get("code_path") or ""))
        root = Path(str(owner.get("state_root") or ""))
        if (not code.is_absolute() or code.name != "eve.py" or code.parent.resolve() not in roots
                or not root.is_absolute() or root.resolve() != code.parent.resolve() / ".eve"):
            raise ValueError("owner_root_not_admitted")
        pid = owner.get("pid")
        if (type(pid) is not int or pid <= 0 or not isinstance(owner.get("owner_id"), str)
                or not owner["owner_id"] or owner.get("run_mode") not in ("recurrent", "once")
                or owner.get("status") != "running"):
            raise ValueError("owner_identity_invalid")
        _check_process(pid)
        state = _read_record(root / "state.json", limit=1024 * 1024)
        activity = _read_record(root / "daemon_activity.json")
        if (state.get("daemon_runner_owner_id") != owner["owner_id"]
                or state.get("daemon_runner_mode") != owner["run_mode"]
                or activity.get("owner_id") != owner["owner_id"]
                or activity.get("pid") != pid or activity.get("run_mode") != owner["run_mode"]):
            raise ValueError("owner_state_activity_mismatch")
        if owner["run_mode"] == "recurrent" and (
                state.get("daemon_process_id") != pid or state.get("daemon_code_path") != str(code)):
            raise ValueError("resident_identity_mismatch")
        after = inspect_runner(runtime_dir)
        if not after["lease_held"] or after.get("owner_receipt") != owner:
            raise ValueError("owner_changed_during_observation")
        result.update({
            "consistent": True,
            "state_path": str(root / "state.json"),
            "activity_path": str(root / "daemon_activity.json"),
            # Do not expose the rest of state.json or arbitrary activity fields.
            "state": {k: state.get(k) for k in ["daemon_process_id", "last_loop_at"]},
            "activity": {k: activity.get(k) for k in [
                "cycle_id", "pid", "owner_id", "run_mode", "status", "cycle_started_at",
                "last_heartbeat_at", "heartbeat_interval_seconds", "max_active_cycle_seconds",
                "heartbeat_count", "cycle_completed_at",
            ]},
        })
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        result["available"] = True
        # Fixed validation codes or exception class; never echo file contents.
        result["problem"] = str(exc) if type(exc) is ValueError and str(exc).isidentifier() else type(exc).__name__
    return result


def _age(value, now):
    try:
        when = datetime.fromisoformat(str(value))
        if when.tzinfo is None:
            return None
        seconds = (now - when).total_seconds()
        return max(0.0, seconds) if seconds >= -5 else None
    except (ValueError, TypeError, OverflowError):
        return None


def _bounded_int(value, default, low, high):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError, OverflowError):
        return default


def observed_liveness(observation: dict, config: dict, *, now=None) -> dict:
    """Evaluate an owner-joined snapshot; existence is not active recurrence."""
    now = now or datetime.now(timezone.utc)
    ownership = observation.get("ownership") or {}
    owner = ownership.get("owner_receipt") or {}
    activity = observation.get("activity") or {}
    state = observation.get("state") or {}
    mode = owner.get("run_mode") or "unknown"
    loop_age = _age(state.get("last_loop_at"), now)
    heartbeat_age = _age(activity.get("last_heartbeat_at"), now)
    cycle_age = _age(activity.get("cycle_started_at"), now)
    owner_age = _age(owner.get("started_at"), now)
    loop_bound = max(180, _bounded_int(config.get("loop_sleep_seconds"), 60, 1, 3600) * 4)
    heartbeat_bound = max(60, _bounded_int(activity.get("heartbeat_interval_seconds"), 15, 5, 60) * 3)
    cycle_bound = min(_bounded_int(config.get("daemon_max_active_cycle_seconds"), 900, 180, 3600),
                      _bounded_int(activity.get("max_active_cycle_seconds"), 900, 180, 3600))
    joined = observation.get("consistent") is True
    running = ownership.get("lease_held") is True and joined and mode == "recurrent"
    valid_clock = (owner_age is not None and cycle_age is not None and heartbeat_age is not None
                   and heartbeat_age <= cycle_age <= owner_age)
    active = bool(running and valid_clock and activity.get("status") == "active"
                  and heartbeat_age <= heartbeat_bound and cycle_age <= cycle_bound)
    idle = bool(running and valid_clock and activity.get("status") == "idle"
                and loop_age is not None and loop_age <= min(loop_bound, owner_age)
                and heartbeat_age <= loop_bound)
    if not ownership.get("lease_held") and observation.get("problem") in (None, "owner_not_held"):
        status, reason = "dormant", "No core runner holds the kernel lease."
    elif not joined:
        status, reason = "inconclusive", "Core ownership and activity could not be joined; do not infer health from a mirror."
    elif mode == "once":
        status, reason = "diagnostic", "A one-shot diagnostic owns the runner; it is not recurrent continuity."
    elif active:
        status, reason = "active", "The owned core is inside a bounded cycle with a fresh activity heartbeat."
    elif idle:
        status, reason = "live", "The owned core completed a recent cycle and is between recurrent runs."
    else:
        status, reason = "stale", "The owned core has failed, stale, future-dated or over-bound cycle evidence."
    return {
        "status": status, "live": active or idle, "active": active, "daemon_running": running,
        "last_loop_at": state.get("last_loop_at") or "",
        "last_loop_age_minutes": round(loop_age / 60, 2) if loop_age is not None else None,
        "max_loop_age_seconds": loop_bound,
        "activity": {**activity, "heartbeat_max_age_seconds": heartbeat_bound,
                     "max_active_cycle_seconds": cycle_bound, "pid_matches": joined,
                     "heartbeat_age_minutes": round(heartbeat_age / 60, 2) if heartbeat_age is not None else None,
                     "cycle_age_minutes": round(cycle_age / 60, 2) if cycle_age is not None else None},
        "reason": reason,
        "observation": {k: observation.get(k) for k in ["consistent", "problem", "state_path", "activity_path"]},
        "ownership": ownership,
    }


@contextmanager
def runner_lease(runtime_dir: Path, *, code_path: Path, state_root: Path, mode: str):
    if mode not in {"recurrent", "once"}:
        raise ValueError("Core runner mode must be recurrent or once")
    path = owner_path(runtime_dir)
    with eve_store.file_lock(path, blocking=False, reentrant=False):
        owner = {
            "schema_id": "eve.daemon_owner.v1",
            "owner_id": str(uuid.uuid4()),
            "pid": os.getpid(),
            "run_mode": mode,
            "code_path": str(code_path.resolve()),
            "state_root": str(state_root.resolve()),
            "started_at": _now(),
            "status": "running",
        }

        def persist(record):
            # Do not reacquire the non-reentrant lifetime lock to write its
            # metadata. Never unlink/replace the kernel lock's inode.
            eve_store.atomic_write_text(path, json.dumps(record, indent=2) + "\n")

        persist(owner)
        failed = False
        try:
            yield dict(owner)
        except BaseException:
            failed = True
            raise
        finally:
            # Preserve unexpected external edits rather than overwriting them
            # as our own receipt. Kernel ownership lasts through this cleanup.
            current = eve_store.load_json_dict(path, default={})
            if current.get("owner_id") == owner["owner_id"]:
                persist({**owner, "status": "failed" if failed else "stopped", "stopped_at": _now()})


@contextmanager
def cycle_activity(*, interval_seconds, max_active_seconds, write, now, owner=None):
    """Observe a cycle without scheduling jobs or claiming execution finished.

    The maximum is a liveness bound, not a cancellation timer. Job deadlines
    remain owned by their existing executors.
    """
    owner = owner or {}
    started_at = now()
    started_monotonic = time.monotonic()
    stop_event = threading.Event()
    write_lock = threading.Lock()
    activity = {
        "schema_id": "eve_daemon_activity.v1",
        "cycle_id": str(uuid.uuid4()),
        "owner_id": owner.get("owner_id", ""),
        "run_mode": owner.get("run_mode", "unowned"),
        "pid": os.getpid(),
        "status": "active",
        "cycle_started_at": started_at,
        "last_heartbeat_at": started_at,
        "heartbeat_count": 1,
        "heartbeat_interval_seconds": interval_seconds,
        "max_active_cycle_seconds": max_active_seconds,
        "completed_jobs": [],
    }

    def persist(status):
        with write_lock:
            activity["status"] = status
            activity["last_heartbeat_at"] = now()
            activity["elapsed_seconds"] = round(time.monotonic() - started_monotonic, 2)
            write(dict(activity))

    persist("active")

    def heartbeat_worker():
        while not stop_event.wait(interval_seconds):
            activity["heartbeat_count"] += 1
            persist("active")

    worker = threading.Thread(target=heartbeat_worker, name="eve-daemon-cycle-heartbeat", daemon=True)
    worker.start()
    failure = ""
    try:
        yield activity
    except BaseException as exc:
        failure = " ".join(str(exc).split())[:240] or exc.__class__.__name__
        raise
    finally:
        stop_event.set()
        # Never release the runner lease while its heartbeat could still write
        # over a replacement. A stuck store write is stale, not a free lease.
        worker.join()
        activity["cycle_completed_at"] = now()
        activity["failure"] = failure
        persist("failed" if failure else "idle")
