"""Runtime usage sampler: which of Eve's functions actually run while she lives.

Enabled with EVE_TRACE_USAGE=1 in any Eve process (daemon, chat backend, CLI). A background thread
samples every thread's stack 40 times a second and counts each repo-defined function that is on a
stack (tests and vendored code excluded). Counts are flushed to .eve/function_usage/<process>-<pid>.json
every 60 seconds and at exit; the census tool merges the files.

Sampling, not tracing: a call-tracing profiler made `import eve` take minutes. Sampling costs a few
percent and, over a day of her ordinary cycles, catches everything that runs for more than a few
milliseconds; the static census covers the rest. This is evidence for the rebuild: code that is
never on a stack in a day of her life is either a tool she uses only on request, or dead.
"""
from __future__ import annotations

import atexit
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Tuple

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / ".eve" / "function_usage"
SAMPLE_INTERVAL_SECONDS = 0.025
_counts: Dict[Tuple[str, str, int], int] = {}
_lock = threading.Lock()
_started_at = time.time()
_samples = 0
_prefix = str(ROOT) + os.sep
_skip_parts = (os.sep + "tests" + os.sep, os.sep + "vendor" + os.sep, os.sep + ".venv", os.sep + "EveBackups" + os.sep, os.sep + "__pycache__" + os.sep)
_self_thread_id = 0


def _label() -> str:
    argv = " ".join(sys.argv[:4])
    for name in ("daemon run", " app ", "message", "autonomy", "runtime", "code"):
        if name.strip() in argv:
            return name.strip().replace(" ", "_")
    return Path(sys.argv[0]).stem or "python"


def _sample_once() -> None:
    global _samples
    seen: set = set()
    for thread_id, frame in list(sys._current_frames().items()):
        if thread_id == _self_thread_id:
            continue
        while frame is not None:
            code = frame.f_code
            filename = code.co_filename
            if filename.startswith(_prefix) and not any(part in filename for part in _skip_parts):
                seen.add((filename[len(_prefix):], code.co_name, code.co_firstlineno))
            frame = frame.f_back
    with _lock:
        _samples += 1
        for key in seen:
            _counts[key] = _counts.get(key, 0) + 1


def flush() -> None:
    with _lock:
        rows = [{"file": f, "function": fn, "line": ln, "samples": c} for (f, fn, ln), c in _counts.items()]
        samples = _samples
    if not rows:
        return
    try:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / f"{_label()}-{os.getpid()}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"process": _label(), "pid": os.getpid(), "argv": sys.argv[:6], "started_at": _started_at, "flushed_at": time.time(), "sample_interval_seconds": SAMPLE_INTERVAL_SECONDS, "samples": samples, "functions": rows}), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def _sampler() -> None:
    global _self_thread_id
    _self_thread_id = threading.get_ident()
    last_flush = time.time()
    while True:
        time.sleep(SAMPLE_INTERVAL_SECONDS)
        try:
            _sample_once()
        except Exception:  # noqa: BLE001 - the sampler must never take the process down
            pass
        if time.time() - last_flush >= 60:
            flush()
            last_flush = time.time()


def install() -> bool:
    if os.environ.get("EVE_TRACE_USAGE", "").strip() not in {"1", "true", "yes"}:
        return False
    thread = threading.Thread(target=_sampler, name="eve-usage-sampler", daemon=True)
    thread.start()
    atexit.register(flush)
    return True
