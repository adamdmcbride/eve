#!/usr/bin/env python3

import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Tuple

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]


_LOCK_REGISTRY_GUARD = threading.Lock()
_THREAD_LOCAL = threading.local()
_PATH_LOCKS: dict[str, threading.RLock] = {}
_MACOS_DATALESS_FLAG = 0x40000000


def _temp_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.tmp.{os.getpid()}.{threading.get_ident()}")


def _path_key(path: Path) -> str:
    return str(path.resolve())


def _path_lock(path: Path) -> threading.RLock:
    key = _path_key(path)
    with _LOCK_REGISTRY_GUARD:
        lock = _PATH_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PATH_LOCKS[key] = lock
        return lock


def _remove_dataless_lock_placeholder(lock_path: Path) -> None:
    """Drop zero-byte iCloud/dataless lock placeholders before opening them.

    macOS can leave ignored lock files as dataless placeholders. Opening one
    with write mode may block while the system tries to hydrate it, which makes
    normal Eve store writes look like a deadlock. Active lock files are opened
    and flocked by a process, so only remove empty dataless placeholders.
    """
    try:
        stat_result = lock_path.stat()
    except FileNotFoundError:
        return
    except OSError:
        return
    flags = int(getattr(stat_result, "st_flags", 0) or 0)
    if stat_result.st_size == 0 and flags & _MACOS_DATALESS_FLAG:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            return
        except OSError:
            return


def _thread_depths() -> dict[str, int]:
    depths = getattr(_THREAD_LOCAL, "depths", None)
    if depths is None:
        depths = {}
        _THREAD_LOCAL.depths = depths
    return depths


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _temp_path(path)
    temp_path.write_text(content, encoding=encoding)
    temp_path.replace(path)


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    key = _path_key(path)
    local_lock = _path_lock(path)
    depths = _thread_depths()
    local_lock.acquire()
    already_held = depths.get(key, 0) > 0
    depths[key] = depths.get(key, 0) + 1
    if already_held:
        try:
            yield
        finally:
            remaining = depths.get(key, 1) - 1
            if remaining > 0:
                depths[key] = remaining
            else:
                depths.pop(key, None)
            local_lock.release()
        return
    lock_path = path.with_name(f".{path.name}.lock")
    _remove_dataless_lock_placeholder(lock_path)
    with lock_path.open("w", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            remaining = depths.get(key, 1) - 1
            if remaining > 0:
                depths[key] = remaining
            else:
                depths.pop(key, None)
            local_lock.release()


def parse_jsonl_line(line: str) -> Optional[Dict[str, object]]:
    stripped = line.strip()
    if not stripped:
        return None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def append_jsonl_record(path: Path, record: Dict[str, object], ensure_ascii: bool = True) -> Dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=ensure_ascii) + "\n")
    return record


def read_jsonl_records(path: Path) -> List[Dict[str, object]]:
    if not path.exists():
        return []
    records: List[Dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            record = parse_jsonl_line(line)
            if record is not None:
                records.append(record)
    return records


def read_jsonl_tail_records(path: Path, limit: int, chunk_size: int = 65536) -> List[Dict[str, object]]:
    if limit <= 0 or not path.exists():
        return []
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            position = handle.tell()
            buffer = b""
            while position > 0:
                read_size = min(chunk_size, position)
                position -= read_size
                handle.seek(position)
                buffer = handle.read(read_size) + buffer
                lines = buffer.decode("utf-8", errors="replace").splitlines()
                records = [record for record in (parse_jsonl_line(line) for line in lines) if record is not None]
                if len(records) >= limit:
                    return records[-limit:]
    except OSError:
        return []
    lines = buffer.decode("utf-8", errors="replace").splitlines()
    records = [record for record in (parse_jsonl_line(line) for line in lines) if record is not None]
    return records[-limit:]


def count_jsonl_lines(path: Path, chunk_size: int = 1024 * 1024) -> int:
    if not path.exists():
        return 0
    count = 0
    saw_data = False
    last_byte = b""
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                saw_data = True
                count += chunk.count(b"\n")
                last_byte = chunk[-1:]
    except OSError:
        return 0
    if saw_data and last_byte != b"\n":
        count += 1
    return count


def read_text_tail(path: Path, max_lines: int = 8, max_chars: int = 500, chunk_size: int = 65536) -> str:
    if max_lines <= 0 or max_chars <= 0 or not path.exists():
        return ""
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            position = handle.tell()
            buffer = b""
            while position > 0:
                read_size = min(chunk_size, position)
                position -= read_size
                handle.seek(position)
                buffer = handle.read(read_size) + buffer
                lines = [line.strip() for line in buffer.decode("utf-8", errors="replace").splitlines() if line.strip()]
                if len(lines) >= max_lines:
                    tail = " | ".join(lines[-max_lines:])
                    return tail[:max_chars]
    except OSError:
        return ""
    lines = [line.strip() for line in buffer.decode("utf-8", errors="replace").splitlines() if line.strip()]
    tail = " | ".join(lines[-max_lines:]) if lines else ""
    return tail[:max_chars]


def write_jsonl_records(path: Path, records: List[Dict[str, object]], ensure_ascii: bool = True) -> None:
    lines = "".join(json.dumps(record, ensure_ascii=ensure_ascii) + "\n" for record in records)
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path):
        atomic_write_text(path, lines, encoding="utf-8")


def load_json_dict(path: Path, default: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    fallback = dict(default or {})
    if not path.exists():
        return fallback
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fallback
    return payload if isinstance(payload, dict) else fallback


def write_json_dict(
    path: Path,
    payload: Dict[str, object],
    *,
    indent: int = 2,
    sort_keys: bool = False,
    ensure_ascii: bool = True,
) -> None:
    with file_lock(path):
        atomic_write_text(
            path,
            json.dumps(payload, indent=indent, sort_keys=sort_keys, ensure_ascii=ensure_ascii) + "\n",
            encoding="utf-8",
        )


def mutate_json_dict(
    path: Path,
    mutator: Callable[[Dict[str, object]], object],
    *,
    default: Optional[Dict[str, object]] = None,
    indent: int = 2,
    sort_keys: bool = False,
    ensure_ascii: bool = True,
) -> Tuple[Dict[str, object], object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path):
        payload = load_json_dict(path, default=default)
        result = mutator(payload)
        atomic_write_text(
            path,
            json.dumps(payload, indent=indent, sort_keys=sort_keys, ensure_ascii=ensure_ascii) + "\n",
            encoding="utf-8",
        )
        return payload, result
