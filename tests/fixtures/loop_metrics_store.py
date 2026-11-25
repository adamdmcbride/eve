"""Tiny fixture ``.eve`` store for tests/test_loop_metrics.py.

The row shapes mirror what was observed read-only in the live store on 2026-09-17:

- entries.jsonl: ``{id, timestamp, kind, text, tags, metadata}`` with ``mind_tick`` metadata
  ``{source, model, used_fallback, fallback_reason, current_focus, next_step}``, ``reflection``
  metadata ``{days, model, source_entries, source}``, ``cycle_skipped`` metadata ``{source, gate}``.
- messages.jsonl: ``{id, timestamp, created_at, sender, recipient, kind, subject, body, metadata, ...}``;
  daemon rows are ``sender == "eve"`` with a non-``reply`` kind.
- proposals.jsonl: ``{id, created_at, updated_at, title, summary, body, status, source, metadata}``.
- self_change_ledger.jsonl: ``{started_at, finished_at, session_id, proposal_id, proposal_title,
  outcome, changes, patched_paths, verified, verification, rollback, error, report}``.
- tensions.jsonl / experiments.jsonl / outcomes.jsonl / action_executions.jsonl as written by
  ``cmd_tension_add`` / ``cmd_experiment_add`` / the outcome and action-execution ledgers.
- operational_state.sqlite3: ``perf_events(id, created_at, category, name, duration_ms, ok, metadata_json)``
  plus the ``idx_perf_events_category_name_created`` index (PRAGMA table_info verified live).

Everything is written into the directory the caller passes (a temp dir); nothing touches the live store.
"""

import json
import sqlite3
from pathlib import Path

NOW_ISO = "2026-09-17T00:00:00+00:00"


def _entry(ts, kind, text="", metadata=None, entry_id=None):
    return {
        "id": entry_id or "%s-%s" % (kind, ts),
        "timestamp": ts,
        "kind": kind,
        "text": text or kind,
        "tags": [],
        "metadata": metadata if metadata is not None else {"source": "daemon"},
    }


def _mind_tick(ts, used_fallback, model, reason=""):
    return _entry(
        ts,
        "mind_tick",
        "Focus X. Next check: Y",
        {
            "source": "daemon",
            "model": model,
            "used_fallback": used_fallback,
            "fallback_reason": reason,
            "current_focus": "X",
            "next_step": "Y",
        },
    )


ENTRIES = [
    # outside the 7-day window
    _entry("2026-09-01T00:00:00+00:00", "thought", "old thought", {"source": "daemon", "model": "eve-fast"}),
    _entry("2026-09-01T01:00:00+00:00", "reflection", "old reflection", {"days": 30, "model": "eve-deep", "source_entries": 1, "source": "daemon"}),
    # inside the window, before the reflection
    _entry("2026-09-11T00:00:00+00:00", "nervous_system_run"),
    _entry("2026-09-11T01:00:00+00:00", "nervous_system_run"),
    _entry("2026-09-12T00:00:00+00:00", "cycle_skipped", "thought skipped: lanes over budget", {"source": "daemon", "gate": "system"}),
    _entry("2026-09-12T01:00:00+00:00", "thought", "a lived thought", {"source": "daemon", "model": "eve-fast"}),
    _mind_tick("2026-09-12T02:00:00+00:00", True, "deterministic", "background model tick failed: Could not parse"),
    _entry("2026-09-12T03:00:00+00:00", "user_request", "The operator asked a question", {"source": "chat"}),
    # the reflection reads the newest 4 entries before it: cycle_skipped, thought, mind_tick, user_request
    _entry("2026-09-15T12:00:00+00:00", "reflection", "# Reflection", {"days": 30, "model": "eve-deep", "source_entries": 4, "source": "daemon"}),
    # after the reflection
    _mind_tick("2026-09-15T13:00:00+00:00", False, "eve-fast"),
    _mind_tick("2026-09-15T14:00:00+00:00", True, "deterministic", "System load is hot"),
    _entry("2026-09-16T00:00:00+00:00", "cycle_skipped", "quiet consolidation skipped: quiet period", {"source": "daemon", "gate": "quiet_period"}),
    _entry("2026-09-16T01:00:00+00:00", "cycle_skipped", "self change skipped: lanes over budget", {"source": "daemon", "gate": "system"}),
    _entry("2026-09-16T02:00:00+00:00", "daemon_error", "ambient model thought failed: prompt does not fit", {"source": "daemon"}),
    _entry("2026-09-16T03:00:00+00:00", "daemon_error", "reflection failed: timeout", {"source": "daemon"}),
]


def _message(ts, sender, kind, subject="", metadata=None, recipient="user", message_id=None):
    return {
        "id": message_id or "%s-%s-%s" % (sender, kind or "nokind", ts),
        "timestamp": ts,
        "created_at": ts,
        "updated_at": ts,
        "thread_id": "thread-1",
        "sender": sender,
        "recipient": recipient,
        "subject": subject or kind,
        "body": "body",
        "kind": kind,
        "status": "unread",
        "reply_to": None,
        "metadata": metadata if metadata is not None else {"source": "daemon"},
    }


MESSAGES = [
    _message("2026-09-01T00:00:00+00:00", "eve", "proactive_outreach"),  # outside the window
    _message("2026-09-13T00:00:00+00:00", "user", "message", "hello", {}),
    _message("2026-09-13T00:05:00+00:00", "eve", "reply", "re: hello", {"source": "eve_chat", "model": "eve-fast"}),
    _message("2026-09-14T00:00:00+00:00", "eve", "upgrade_review_update"),
    _message("2026-09-14T01:00:00+00:00", "eve", "upgrade_review_update"),
    _message("2026-09-15T00:00:00+00:00", "eve", "proactive_outreach", metadata={"source": "daemon", "model": "eve-fast"}),
    # kind only in metadata: the reader falls back to metadata["kind"]
    _message("2026-09-15T01:00:00+00:00", "eve", "", "reflection", {"source": "daemon", "kind": "reflection_update"}, message_id="eve-meta-kind"),
]


def _proposal(pid, ts, title, status, metadata=None):
    return {
        "id": pid,
        "created_at": ts,
        "updated_at": ts,
        "title": title,
        "summary": title,
        "body": title,
        "status": status,
        "source": "daemon",
        "metadata": metadata if metadata is not None else {},
    }


PROPOSALS = [
    _proposal("p-dup-1", "2026-09-13T00:00:00+00:00", "Repair degraded local Eve services", "draft"),
    _proposal("p-dup-2", "2026-09-14T00:00:00+00:00", "Repair degraded  local Eve services", "draft"),
    _proposal("p-lineage", "2026-09-14T01:00:00+00:00", "Fix the deep lane timeout", "draft", {"tension_ids": ["t-1"], "rollback": "set the key back"}),
    _proposal("p-tensions-only", "2026-09-14T02:00:00+00:00", "Only tensions, no rollback", "draft", {"tension_ids": ["t-1"]}),
    _proposal("p-applied", "2026-09-15T00:00:00+00:00", "Route proposals to the fast lane", "applied", {"applied_by": "self_change"}),
    _proposal("p-archived", "2026-09-01T00:00:00+00:00", "Old idea", "archived", {"archived_reason": "stale"}),
]


def _ledger(started, finished, session_id, proposal_id, title, outcome, **extra):
    row = {
        "started_at": started,
        "finished_at": finished,
        "elapsed_seconds": 60.0,
        "source": "daemon",
        "session_id": session_id,
        "proposal_id": proposal_id,
        "proposal_title": title,
        "outcome": outcome,
        "changes": [],
        "patched_paths": [],
        "verified": True,
        "verification": "no code changed",
        "rollback": [],
        "restart_requested": False,
        "error": "",
        "report": "",
    }
    row.update(extra)
    return row


LEDGER = [
    # outside the window: a failure
    _ledger("2026-09-01T00:00:00+00:00", "2026-09-01T00:01:00+00:00", "self-change-old", "p-old", "Old failing change", "failed", error="step limit"),
    # applied with an explicit consequence and a before.json on disk
    _ledger("2026-09-15T00:00:00+00:00", "2026-09-15T00:01:00+00:00", "self-change-s1", "p-applied", "Route proposals to the fast lane", "applied", consequence="proposal timeouts stopped for 24h", changes=["set_config:{}"]),
    # applied; consequence only via an outcome row within 24h
    _ledger("2026-09-15T02:00:00+00:00", "2026-09-15T02:01:00+00:00", "self-change-s2", "p-applied", "Route proposals to the fast lane", "applied", changes=["set_config:{}"]),
    # applied with nothing recorded after it
    _ledger("2026-09-15T04:00:00+00:00", "2026-09-15T04:01:00+00:00", "self-change-s3", "p-dup-1", "Repair degraded local Eve services", "applied", changes=["block_action:{}"]),
    _ledger("2026-09-16T00:00:00+00:00", "2026-09-16T00:01:00+00:00", "self-change-s4", "p-dup-2", "Repair degraded local Eve services", "no_change"),
]


TENSIONS = [
    {"id": "t-old", "timestamp": "2026-09-01T00:00:00+00:00", "summary": "old", "side_a": "a", "side_b": "b", "values": [], "question": "q", "next_step": "n", "status": "open", "source": "reflection"},
    {"id": "t-1", "timestamp": "2026-09-15T12:05:00+00:00", "summary": "reflection tension", "side_a": "a", "side_b": "b", "values": [], "question": "q", "next_step": "n", "status": "open", "source": "reflection"},
    {"id": "t-2", "timestamp": "2026-09-15T13:00:00+00:00", "summary": "manual tension", "side_a": "a", "side_b": "b", "values": [], "question": "q", "next_step": "n", "status": "open"},
]


def _experiment(eid, ts, status, outcome=""):
    return {
        "id": eid,
        "created_at": ts,
        "updated_at": ts,
        "name": eid,
        "hypothesis": "h",
        "action": "a",
        "success_criteria": "s",
        "duration_days": 1,
        "status": status,
        "outcome": outcome,
        "notes": "",
    }


EXPERIMENTS = [
    _experiment("e-evidence", "2026-09-14T00:00:00+00:00", "completed", "supported: the lane answered in budget"),
    _experiment("e-observe", "2026-09-14T01:00:00+00:00", "completed", "observe: measurement-only run completed"),
    _experiment("e-expired", "2026-09-14T02:00:00+00:00", "expired_unverified", ""),
    _experiment("e-active", "2026-09-14T03:00:00+00:00", "active", ""),
]


OUTCOMES = [
    {"id": "o-1", "created_at": "2026-09-15T00:00:00+00:00", "updated_at": "2026-09-15T00:00:00+00:00", "target_kind": "experiment", "target_id": "e-evidence", "thread_id": "", "direction": "positive", "outcome": "verified", "summary": "s", "evidence": "e", "source": "daemon"},
    {"id": "o-2", "created_at": "2026-09-15T04:00:00+00:00", "updated_at": "2026-09-15T04:00:00+00:00", "target_kind": "self_change", "target_id": "self-change-s2", "thread_id": "", "direction": "positive", "outcome": "consequence_observed", "summary": "s", "evidence": "e", "source": "daemon"},
    {"id": "o-3", "created_at": "2026-09-15T05:00:00+00:00", "updated_at": "2026-09-15T05:00:00+00:00", "target_kind": "message", "target_id": "m-1", "thread_id": "thread-1", "direction": "positive", "outcome": "counterpart_replied", "summary": "s", "evidence": "e", "source": "daemon"},
]


def _action(ts, action, result_ok, source="daemon"):
    return {
        "id": "%s-%s" % (action, ts),
        "created_at": ts,
        "updated_at": ts,
        "action": action,
        "source": source,
        "backend": "dependency_graph_executor",
        "tree_status": "SUCCESS" if result_ok else "FAILURE",
        "verification_ok": result_ok,
        "steps": [],
        "activity_tail": [],
        "summary": action,
        "result_ok": result_ok,
    }


ACTIONS = [
    _action("2026-09-01T00:00:00+00:00", "system_tasks", True),
    _action("2026-09-14T00:00:00+00:00", "system_tasks", True),
    _action("2026-09-14T01:00:00+00:00", "openclaw_log_check", False),
    _action("2026-09-15T00:00:00+00:00", "system_tasks", True, source="autonomy_free_run:free-run-1"),
]


def _perf(row_id, ts, category, name, duration_ms, ok, model, backend="llama_cpp", extra=None):
    meta = {
        "attempt": "primary",
        "backend": backend,
        "host": "http://127.0.0.1:8080",
        "max_tokens": 320,
        "message_count": 2,
        "model": model,
        "operation": name,
    }
    if extra:
        meta.update(extra)
    return (row_id, ts, category, name, float(duration_ms), 1 if ok else 0, json.dumps(meta, sort_keys=True))


PERF_EVENTS = [
    _perf("pe-old", "2026-09-01T00:00:00+00:00", "model_call", "continuous_thought", 1000, True, "eve-fast"),
    _perf("pe-1", "2026-09-13T00:00:00+00:00", "model_call", "continuous_thought", 1000, True, "eve-fast"),
    _perf("pe-2", "2026-09-13T01:00:00+00:00", "model_call", "continuous_thought", 2000, False, "eve-fast", extra={"error": "timeout"}),
    _perf("pe-3", "2026-09-14T00:00:00+00:00", "model_call", "reflection", 3600000, True, "eve-deep"),
    _perf("pe-4", "2026-09-14T01:00:00+00:00", "model_call", "daemon_model_mind_tick", 500, False, "eve-deep", extra={"error": "parse", "truncated": True}),
    _perf("pe-5", "2026-09-15T00:00:00+00:00", "model_call", "daemon_model_mind_tick", 500, True, "eve-observer"),
    _perf("pe-6", "2026-09-15T01:00:00+00:00", "model_call", "reply_stream_fast", 100, True, "gemma", backend="ollama"),
    _perf("pe-7", "2026-09-15T02:00:00+00:00", "prompt_fit", "continuous_thought", 20, True, "eve-fast"),
]


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def perf_jsonl_rows():
    """The same perf rows in the ``.eve/perf_events.jsonl`` mirror shape (``timestamp`` + ``metadata`` dict)."""
    rows = []
    for row_id, ts, category, name, duration_ms, ok, metadata_json in PERF_EVENTS:
        rows.append(
            {
                "id": row_id,
                "timestamp": ts,
                "category": category,
                "name": name,
                "duration_ms": duration_ms,
                "ok": bool(ok),
                "metadata": json.loads(metadata_json),
            }
        )
    return rows


def build_fixture(root, with_sqlite=True, with_perf_jsonl=True):
    """Write the fixture store under ``root`` (a temp dir) and return its Path."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if with_perf_jsonl:
        _write_jsonl(root / "perf_events.jsonl", perf_jsonl_rows())
    _write_jsonl(root / "entries.jsonl", ENTRIES)
    _write_jsonl(root / "messages.jsonl", MESSAGES)
    _write_jsonl(root / "proposals.jsonl", PROPOSALS)
    _write_jsonl(root / "self_change_ledger.jsonl", LEDGER)
    _write_jsonl(root / "tensions.jsonl", TENSIONS)
    _write_jsonl(root / "experiments.jsonl", EXPERIMENTS)
    _write_jsonl(root / "outcomes.jsonl", OUTCOMES)
    _write_jsonl(root / "action_executions.jsonl", ACTIONS)
    before_dir = root / "self_change" / "self-change-s1"
    before_dir.mkdir(parents=True, exist_ok=True)
    (before_dir / "before.json").write_text(json.dumps({"operation_model_overrides": {}}), encoding="utf-8")
    (root / "self_change" / "self-change-s2").mkdir(parents=True, exist_ok=True)
    if with_sqlite:
        connection = sqlite3.connect(str(root / "operational_state.sqlite3"))
        try:
            connection.execute(
                "CREATE TABLE perf_events ("
                "id TEXT PRIMARY KEY, created_at TEXT NOT NULL, category TEXT NOT NULL, name TEXT NOT NULL, "
                "duration_ms REAL NOT NULL, ok INTEGER NOT NULL DEFAULT 1, metadata_json TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE INDEX idx_perf_events_category_name_created ON perf_events(category, name, created_at)"
            )
            connection.executemany("INSERT INTO perf_events VALUES (?, ?, ?, ?, ?, ?, ?)", PERF_EVENTS)
            connection.commit()
        finally:
            connection.close()
    return root
