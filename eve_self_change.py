"""Self-change lifecycle extracted from the Eve facade.

Compatibility owner for proposal eligibility, audited levers and delayed
consequence review. The execution workflow delegates to eve_core.self_change
through eve_adapters.self_change; remaining legacy helpers resolve the facade
at call time so existing patches remain effective during migration.
Importing this module does not import or start Eve. No new action authority.
"""
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from eve_late import core
import eve_store
import eve_profile

__all__ = (
    'load_action_blocks',
    'save_action_blocks',
    'self_change_before_image_path',
    'load_self_change_before_image',
    'record_self_change_before_image',
    'self_authority_tool_specs',
    'execute_self_authority_tool',
    'append_self_change_ledger',
    'read_self_change_ledger',
    'parse_proposal_lineage',
    'proposal_looks_conversational',
    'proposal_has_lineage',
    'proposal_is_actionable',
    'proposal_dedupe_key',
    'find_duplicate_proposal',
    'self_change_cooled_topics',
    'archive_stale_draft_proposals',
    'self_change_candidate_proposals',
    'build_self_change_request',
    'run_self_change_cycle',
    'revert_self_change',
    'self_change_metric_spec',
    'schedule_self_change_followup',
    'measure_self_change_metric',
    'self_change_followup_verdict',
    'review_self_change_followups',
)


def load_action_blocks(now: Optional[str] = None) -> Dict[str, Dict[str, object]]:
    """Actions Eve has blocked for a while, with the reason; expired blocks fall away."""
    try:
        payload = core.json.loads(core.ACTION_BLOCKS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    current = now or core.utc_now()
    live = {action: item for action, item in payload.items() if isinstance(item, dict) and str(item.get("until") or "") > current}
    return live


def save_action_blocks(blocks: Dict[str, Dict[str, object]]) -> None:
    with eve_store.file_lock(core.ACTION_BLOCKS_PATH):
        eve_store.atomic_write_text(core.ACTION_BLOCKS_PATH, core.json.dumps(blocks, indent=1))


def self_change_before_image_path(session_id: str) -> Path:
    return core.SELF_CHANGE_DIR / session_id / "before.json"


def load_self_change_before_image(session_id: str) -> Dict[str, object]:
    """The before-image of one self-change session: a JSON object keyed by lever, then by what it touched."""
    try:
        payload = core.json.loads(core.self_change_before_image_path(session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def record_self_change_before_image(config: Dict[str, object], lever: str, key: str, previous: object) -> bool:
    """Write what a lever is about to change, before it changes it, so the session can be reverted.

    Only the first image per lever/key is kept: that is the state before this session touched it.
    Outside a self-change cycle (no `_self_change_session`) nothing is written.
    """
    session_id = core.normalize_text_value(config.get("_self_change_session"), fallback="", limit=80)
    if not session_id:
        return False
    path = core.self_change_before_image_path(session_id)
    # Keep the read/first-image decision/write inside the same existing store
    # lock. Atomic replacement also preserves the old rollback image on failure.
    with eve_store.file_lock(path):
        payload = core.load_self_change_before_image(session_id)
        bucket = payload.get(lever)
        if not isinstance(bucket, dict):
            bucket = {}
            payload[lever] = bucket
        if key in bucket:
            return False
        bucket[key] = previous
        eve_store.atomic_write_text(path, core.json.dumps(payload, indent=1, ensure_ascii=True, default=str))
    return True


def self_authority_tool_specs() -> List[Dict[str, str]]:
    return [
        {"name": "set_config", "description": "Change one of Eve's own config keys (routing, cadences, budgets); audited, snapshotted, reversible. Use operation_model_overrides to route an operation to a lane: {\"proposal\": \"observer\"}.", "args": '{"key":"operation_model_overrides","value":{"proposal":"observer"},"reason":"the deep lane times out under load"}'},
        {"name": "block_action", "description": "Stop scheduling one of Eve's own autonomy actions for a number of hours, with the reason.", "args": '{"action":"openclaw_log_check","hours":24,"reason":"fails identically every run"}'},
        {"name": "update_pattern", "description": "Change a success pattern's status (active, archived, superseded) with a note.", "args": '{"pattern_id":"<id>","status":"archived","note":"learned from compliance, not consequence"}'},
        {"name": "approve_maintenance", "description": "Approve one of Eve's own pending maintenance actions (cleanup of her logs, restart of her watchdog); the daemon executes it within minutes.", "args": '{"action_id":"<id>"}'},
        {"name": "request_restart", "description": "Ask Eve's daemon to restart on the current code after this session; the successor is watched and rolled back if it does not come alive.", "args": '{"reason":"routing change needs a restart"}'},
        {"name": "record_change", "description": "Declare a change you made with run_command (a service kicked, a file cleaned, a setting changed) so the ledger counts it; name what changed and how you verified it.", "args": '{"what":"kickstarted local.eve-model-watchdog","verification":"launchctl print shows state = running, pid 67160"}'},
    ]


def execute_self_authority_tool(tool_name: str, args: Dict[str, object], config: Dict[str, object]) -> Dict[str, object]:
    """Eve's own levers. Each one is audited; none of them crosses an edge."""
    source = core.normalize_text_value(config.get("_self_change_session"), fallback="coder_mode", limit=80)
    if tool_name == "set_config":
        key = core.normalize_text_value(args.get("key"), fallback="", limit=120)
        if not key:
            return {"ok": False, "error": "set_config needs a key."}
        if key in core.SELF_CONFIG_LOCKED_KEYS or key.startswith("_"):
            return {"ok": False, "blocked": True, "edge": True, "error": f"{key} is one of Eve's edges; it is not hers to change."}
        if core.SELF_CONFIG_CREDENTIAL_RE.search(key):
            return {"ok": False, "blocked": True, "edge": True, "error": f"{key} looks like a credential; credentials are the user's."}
        if key not in core.DEFAULT_CONFIG:
            return {"ok": False, "error": f"{key} is not a known config key; known keys live in DEFAULT_CONFIG."}
        value = args.get("value")
        current = core.load_config()
        before = current.get(key)
        if key == "operation_model_overrides":
            if not isinstance(value, dict):
                return {"ok": False, "error": "operation_model_overrides takes an object mapping a role to fast|observer|deep or a model name."}
            merged = dict(current.get("operation_model_overrides") or {})
            for role, lane in value.items():
                if lane in (None, ""):
                    merged.pop(str(role), None)
                else:
                    merged[str(role)] = str(lane)
            value = merged
        elif type(core.DEFAULT_CONFIG[key]) in (int, float, bool, str) and value is not None and type(value) is not type(core.DEFAULT_CONFIG[key]) and not (isinstance(value, int) and isinstance(core.DEFAULT_CONFIG[key], float)):
            return {"ok": False, "error": f"{key} takes a {type(core.DEFAULT_CONFIG[key]).__name__}, got {type(value).__name__}."}
        if before == value and type(before) is type(value):
            # Nothing changed: no save, no snapshot, no journal row, and the cycle must not count it.
            return {"ok": True, "no_op": True, "key": key, "before": before, "after": value, "note": f"{key} is already {core.json.dumps(value)[:80]}; nothing changed"}
        core.record_self_change_before_image(config, "set_config", key, before)
        current[key] = value
        core.save_config(current, snapshot_source="self_change")
        core.append_entry("config_self_changed", f"Eve changed {key}: {core.json.dumps(before)[:120]} -> {core.json.dumps(value)[:120]}. {core.normalize_text_value(args.get('reason'), fallback='', limit=200)}".strip(), metadata={"source": source, "key": key, "before": before, "after": value})
        return {"ok": True, "key": key, "before": before, "after": value, "note": "saved and snapshotted; a lane change takes effect on the next call, other keys may need request_restart"}
    if tool_name == "block_action":
        action = core.normalize_text_value(args.get("action"), fallback="", limit=80)
        if action not in core.AUTONOMY_FREE_RUN_ACTIONS and action not in core.DEVELOPMENTAL_CYCLE_SAFE_ACTIONS:
            return {"ok": False, "error": f"{action} is not one of Eve's autonomy actions."}
        hours = core.clamp_int(args.get("hours"), 24, minimum=1, maximum=24 * 14)
        until = (core.utc_now_datetime() + core.timedelta(hours=hours)).isoformat(timespec="seconds")
        blocks = core.load_action_blocks()
        core.record_self_change_before_image(config, "block_action", "action_blocks", dict(blocks))
        blocks[action] = {"until": until, "reason": core.normalize_text_value(args.get("reason"), fallback="", limit=200), "source": source, "set_at": core.utc_now()}
        core.save_action_blocks(blocks)
        core.append_entry("action_self_blocked", f"Eve blocked {action} for {hours}h: {blocks[action]['reason']}", metadata={"source": source, "action": action, "until": until})
        return {"ok": True, "action": action, "until": until}
    if tool_name == "update_pattern":
        pattern_id = core.normalize_text_value(args.get("pattern_id"), fallback="", limit=80)
        status = core.normalize_text_value(args.get("status"), fallback="", limit=20)
        if status not in core.SUCCESS_PATTERN_STATUSES:
            return {"ok": False, "error": f"status must be one of {core.SUCCESS_PATTERN_STATUSES}."}
        previous_pattern = core.find_success_pattern(pattern_id)
        if not previous_pattern:
            return {"ok": False, "error": f"no success pattern {pattern_id}."}
        note = core.normalize_text_value(args.get("note"), fallback="", limit=200)
        core.record_self_change_before_image(config, "update_pattern", pattern_id, dict(previous_pattern))
        record = core.update_success_pattern_record(pattern_id, status=status, self_change_note=note, self_changed_at=core.utc_now())
        core.append_entry("success_pattern_self_updated", f"Eve set pattern {pattern_id} to {status}: {note}", metadata={"source": source, "pattern_id": pattern_id, "status": status})
        return {"ok": True, "pattern_id": pattern_id, "status": record.get("status")}
    if tool_name == "approve_maintenance":
        action_id = core.normalize_text_value(args.get("action_id"), fallback="", limit=80)
        matches = [item for item in core.read_maintenance_actions(status="pending_approval") if str(item.get("id")) == action_id]
        if not matches:
            already = [item for item in core.read_maintenance_actions(status="approved") if str(item.get("id")) == action_id]
            if already:
                return {"ok": True, "action_id": action_id, "status": "approved", "note": "already approved (by you at creation); run `python3 eve.py maintenance run` to execute it now or let the daemon do it"}
            return {"ok": False, "error": f"no pending maintenance action {action_id}."}
        core.record_self_change_before_image(config, "approve_maintenance", action_id, str(matches[0].get("status") or "pending_approval"))
        record = core.update_maintenance_action_record(action_id, status="approved", metadata={**(matches[0].get("metadata") or {}), "approved_by": "eve_self_authority", "approved_source": source})
        core.append_entry("maintenance_action_self_approved", f"Eve approved her maintenance action: {record.get('title')}", metadata={"source": source, "action_id": action_id, "kind": record.get("kind")})
        return {"ok": True, "action_id": action_id, "status": record.get("status"), "note": "the daemon executes approved actions within its next maintenance interval"}
    if tool_name == "request_restart":
        reason = core.normalize_text_value(args.get("reason"), fallback="self change", limit=200)
        context = config.get("_self_change_context")
        if not isinstance(context, dict):
            context = core.SELF_CHANGE_CONTEXT  # Legacy tool calls outside a self-change session.
        context["restart_requested"] = reason
        return {"ok": True, "note": "the daemon will restart on the current code after this session, watched and rolled back if it fails"}
    if tool_name == "record_change":
        what = core.normalize_text_value(args.get("what"), fallback="", limit=240)
        verification = core.normalize_text_value(args.get("verification"), fallback="", limit=240)
        if not what or not verification:
            return {"ok": False, "error": "record_change needs both `what` changed and how it was `verification`-checked."}
        context = config.get("_self_change_context")
        if not isinstance(context, dict):
            context = core.SELF_CHANGE_CONTEXT
        recorded = context.setdefault("reported_changes", [])
        recorded.append({"what": what, "verification": verification, "at": core.utc_now()})
        core.append_entry("self_change_recorded", f"Eve recorded a change she made by command: {what} (verified: {verification})", metadata={"source": source})
        return {"ok": True, "recorded": len(recorded)}
    return {"ok": False, "error": f"Unknown self-authority tool `{tool_name}`."}


def append_self_change_ledger(row: Dict[str, object]) -> None:
    # The ledger needs only its own parent, not the facade's ensure_store(),
    # which bootstraps unrelated continuity files.
    eve_store.append_jsonl_record(core.SELF_CHANGE_LEDGER_PATH, row, ensure_ascii=True)


def read_self_change_ledger(limit: int = 200) -> List[Dict[str, object]]:
    try:
        lines = core.SELF_CHANGE_LEDGER_PATH.read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:
        return []
    rows: List[Dict[str, object]] = []
    for line in lines:
        try:
            item = core.json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def parse_proposal_lineage(text: object) -> Dict[str, object]:
    """Read '## Grounded In' and '## Rollback' out of a drafted proposal.

    Lineage is what the proposal is answering (tension and experiment ids the support prompt showed
    her); rollback is how to undo it. A proposal that names neither is a thought, not a change.
    """
    sections = core.parse_reflection_sections(text)
    body = str(text or "")
    grounded_text, rollback_text = "", ""
    heading = ""
    for raw_line in body.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip().lower()
            continue
        if not stripped:
            continue
        if core.PROPOSAL_LINEAGE_HEADING in heading:
            grounded_text += " " + stripped
        elif heading.startswith(core.PROPOSAL_ROLLBACK_HEADING):
            rollback_text += " " + stripped
    if not grounded_text:
        grounded_text = " ".join(sections.get(core.PROPOSAL_LINEAGE_HEADING, []))
    if not rollback_text:
        rollback_text = " ".join(sections.get(core.PROPOSAL_ROLLBACK_HEADING, []))
    ids: List[str] = []
    for item in core.TRACKER_ID_RE.findall(grounded_text):
        if item not in ids:
            ids.append(item)
    tension_ids, experiment_ids = [], []
    try:
        known_tensions = {str(item.get("id")) for item in core.read_tensions()}
        known_experiments = {str(item.get("id")) for item in core.read_experiments()}
    except Exception:  # noqa: BLE001
        known_tensions, known_experiments = set(), set()
    for item in ids:
        if item in known_tensions:
            tension_ids.append(item)
        elif item in known_experiments:
            experiment_ids.append(item)
    return {
        "tension_ids": tension_ids,
        "experiment_ids": experiment_ids,
        "unmatched_lineage_ids": [item for item in ids if item not in known_tensions and item not in known_experiments],
        "grounded_in": core.normalize_text_value(grounded_text, fallback="", limit=400).strip(),
        "rollback": core.normalize_text_value(rollback_text, fallback="", limit=400).strip(),
    }


def proposal_looks_conversational(item: Dict[str, object]) -> bool:
    """True when this 'proposal' is a chat answer that landed in the proposal store.

    A 4B lane asked to draft a proposal will happily answer a question about Python instead; those
    rows were reaching the self-change candidate pool (2026-09-19), which is how a chat answer gets
    executed as a change to herself.
    """
    title = core.normalize_text_value(item.get("title"), fallback="", limit=200).lower().lstrip("# *")
    body = str(item.get("body") or "")
    body_head = core.normalize_text_value(body[:400], fallback="", limit=400).lower()
    if any(title.startswith(opener) or body_head.startswith(opener) for opener in core.PROPOSAL_CONVERSATIONAL_OPENERS):
        return True
    if "?" in title[:120]:
        return True
    lowered_body = body.lower()
    has_section = any(hint in lowered_body for hint in core.PROPOSAL_REQUIRED_SECTION_HINTS)
    return not has_section


def proposal_has_lineage(item: Dict[str, object]) -> bool:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    ids = list(metadata.get("tension_ids") or []) + list(metadata.get("experiment_ids") or [])
    return bool(ids) and bool(core.normalize_text_value(metadata.get("rollback"), fallback="", limit=400).strip())


def proposal_is_actionable(item: Dict[str, object], config: Optional[Dict[str, object]] = None) -> bool:
    """A real proposal, not a chat reply that landed in the proposal store."""
    title = core.normalize_text_value(item.get("title"), fallback="", limit=200).lower().lstrip("# *")
    if not title or title.startswith((eve_profile.user_display_name().casefold() + ",", "i ", "i’", "i'", "no,", "the gears", "you ")):
        return False
    if core.proposal_looks_conversational(item):
        return False
    shaped = title.startswith(core.SELF_CHANGE_PROPOSAL_TITLE_PREFIXES) or str(item.get("source") or "") in {"daemon", "outcome", "capability_gap", "manual"} and len(str(item.get("body") or "")) > 120
    if shaped and core.parse_boolish((config or {}).get("self_change_require_lineage", False)) and not core.proposal_has_lineage(item):
        return False
    return shaped


def proposal_dedupe_key(item: Dict[str, object]) -> str:
    title = core.normalize_text_value(item.get("title"), fallback="", limit=200).lower()
    title = core.re.sub(r"^(proposal\s*##\s*title\s*|#+\s*|\*+)", "", title).strip(" *#")
    title = core.re.split(r"\s*(##|why now)", title, 1)[0]  # the template's sections are not the topic
    return core.re.sub(r"[^a-z0-9]+", " ", title)[:60].strip()


def find_duplicate_proposal(candidate: Dict[str, object], proposals: List[Dict[str, object]], *, stale_days: int = 7, now: Optional[str] = None) -> Optional[Dict[str, object]]:
    """The proposal that already speaks for this topic: an open draft with the same dedupe key, or one
    applied or archived within `stale_days`. None when the topic is free."""
    key = core.proposal_dedupe_key(candidate)
    if not key:
        return None
    stale_days = core.clamp_int(stale_days, 7, minimum=1, maximum=365)
    cutoff = ((core.parse_iso_datetime(now) if now else core.utc_now_datetime()) - core.timedelta(days=stale_days)).isoformat(timespec="seconds")
    for existing in reversed(proposals):
        if not isinstance(existing, dict) or core.proposal_dedupe_key(existing) != key:
            continue
        status = str(existing.get("status") or "").strip().lower()
        if status == "draft":
            return existing
        if status in ("applied", "archived") and str(existing.get("updated_at") or existing.get("created_at") or "") >= cutoff:
            return existing
    return None


def self_change_cooled_topics(config: Dict[str, object], *, now: Optional[str] = None) -> set:
    """Dedupe keys that already had a self-change start inside self_change_topic_cooldown_hours."""
    cooldown_hours = core.clamp_int(config.get("self_change_topic_cooldown_hours"), 24, minimum=0, maximum=24 * 30)
    if not cooldown_hours:
        return set()
    since = ((core.parse_iso_datetime(now) if now else core.utc_now_datetime()) - core.timedelta(hours=cooldown_hours)).isoformat(timespec="seconds")
    cooled: set = set()
    for row in core.read_self_change_ledger():
        if str(row.get("started_at") or "") >= since:
            key = core.proposal_dedupe_key({"title": row.get("proposal_title")})
            if key:
                cooled.add(key)
    return cooled


def archive_stale_draft_proposals(config: Dict[str, object], *, now: Optional[str] = None) -> int:
    """Drafts older than self_change_stale_days predate her authority to act; archive them once."""
    stale_days = core.clamp_int(config.get("self_change_stale_days"), 7, minimum=1, maximum=365)
    cutoff = ((core.parse_iso_datetime(now) if now else core.utc_now_datetime()) - core.timedelta(days=stale_days)).isoformat(timespec="seconds")
    archived = 0
    for item in core.read_proposals(status="draft"):
        created = str(item.get("created_at") or "")
        if created and created < cutoff:
            core.update_proposal_record(str(item.get("id")), status="archived", metadata={**(item.get("metadata") if isinstance(item.get("metadata"), dict) else {}), "archived_reason": f"stale draft (older than {stale_days} days) when self-authority began"})
            archived += 1
    if archived:
        core.append_entry("proposals_archived_stale", f"Eve archived {archived} stale draft proposal(s) older than {stale_days} days.", metadata={"source": "self_change", "count": archived})
    return archived


def self_change_candidate_proposals(config: Dict[str, object]) -> List[Dict[str, object]]:
    """Her own recent, real draft proposals that self-change has not exhausted, newest first, one per topic."""
    max_attempts = core.clamp_int(config.get("self_change_max_attempts_per_proposal"), 2, minimum=1, maximum=5)
    stale_days = core.clamp_int(config.get("self_change_stale_days"), 7, minimum=1, maximum=365)
    cutoff = (core.utc_now_datetime() - core.timedelta(days=stale_days)).isoformat(timespec="seconds")
    candidates: List[Dict[str, object]] = []
    for item in core.read_proposals(status="draft"):
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        if int(metadata.get("self_change_attempts") or 0) >= max_attempts:
            continue
        if str(item.get("created_at") or "") < cutoff or not core.proposal_is_actionable(item, config):
            continue
        candidates.append(item)
    candidates.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    seen: set = set(core.self_change_cooled_topics(config))  # a topic already started today waits for tomorrow
    unique: List[Dict[str, object]] = []
    for item in candidates:
        key = core.proposal_dedupe_key(item)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def build_self_change_request(proposal: Dict[str, object]) -> str:
    title = core.normalize_text_value(proposal.get("title"), fallback="(untitled)", limit=200)
    body = core.normalize_text_value(proposal.get("body") or proposal.get("summary"), fallback="", limit=4000)
    return core.textwrap.dedent(
        f"""
        This is one of your own draft proposals. You have the authority to apply it now, inside your edges
        (no money, no sending as the user, no writes outside your directories, no touching your audit trail).
        Nobody needs to approve it. Do the smallest change that delivers it, verify it, and report.

        Proposal id: {proposal.get('id')}
        Source: {proposal.get('source')}
        Title: {title}

        {body}

        Preferred levers, cheapest first:
        - set_config for routing or cadence (operation_model_overrides routes an operation to fast|observer|deep).
        - block_action to stop a check that fails identically.
        - update_pattern to retire a lesson learned wrongly.
        - approve_maintenance for a pending cleanup or restart of yours.
        - apply_patch plus run_tests for a code change; keep it small and test the function you touched.
        - run_command for anything else that is yours (kick a service of yours, clean your logs); then call
          record_change with what changed and how you verified it, or the ledger will not count it.
        If the proposal is moot, already done, or wrong, change nothing and say why in `final`.
        End with a `final` that states exactly what changed and how it was verified.
        """
    ).strip()


def run_self_change_cycle(config: Dict[str, object], *, source: str, timeout_seconds: Optional[int] = None, proposal_id: Optional[str] = None) -> Dict[str, object]:
    """Compatibility entrypoint; compose the independent application service."""
    from eve_adapters.self_change import compose_self_change_service

    return compose_self_change_service().run(config, source=source, timeout_seconds=timeout_seconds, proposal_id=proposal_id)


def revert_self_change(session_id: str, *, source: str = "manual") -> Dict[str, object]:
    """Undo one self-change session from its before-image and backup: config keys, action blocks,
    pattern statuses, maintenance approvals, code files. Journals `self_change_reverted` and appends a
    ledger row with outcome `reverted`; the original row stays (the ledger is append-only)."""
    session_id = core.normalize_text_value(session_id, fallback="", limit=80)
    session_dir = core.SELF_CHANGE_DIR / session_id if session_id else None
    if not session_id or session_dir is None or not session_dir.is_dir():
        return {"ok": False, "error": f"no self-change session `{session_id}` under {core.SELF_CHANGE_DIR}."}
    before = core.load_self_change_before_image(session_id)
    backup_dir = session_dir / "backup"
    restored: Dict[str, object] = {"config_keys": [], "action_blocks": False, "patterns": [], "maintenance": [], "files": []}
    problems: List[str] = []
    started = core.utc_now()
    config_before = before.get("set_config")
    if isinstance(config_before, dict) and config_before:
        current = core.load_config()
        for key, previous in config_before.items():
            if key in core.SELF_CONFIG_LOCKED_KEYS or str(key).startswith("_") or key not in core.DEFAULT_CONFIG:
                problems.append(f"config key {key} is not hers to restore")
                continue
            current[key] = previous
            restored["config_keys"].append(key)
        if restored["config_keys"]:
            core.save_config(current, snapshot_source="self_change_revert")
    blocks_before = before.get("block_action")
    if isinstance(blocks_before, dict) and "action_blocks" in blocks_before:
        previous_blocks = blocks_before.get("action_blocks")
        core.save_action_blocks({k: v for k, v in previous_blocks.items() if isinstance(v, dict)} if isinstance(previous_blocks, dict) else {})
        restored["action_blocks"] = True
    patterns_before = before.get("update_pattern")
    if isinstance(patterns_before, dict):
        for pattern_id, previous_record in patterns_before.items():
            previous_status = str((previous_record or {}).get("status") or "") if isinstance(previous_record, dict) else str(previous_record or "")
            if previous_status not in core.SUCCESS_PATTERN_STATUSES or not core.find_success_pattern(pattern_id):
                problems.append(f"pattern {pattern_id} could not be restored to `{previous_status}`")
                continue
            core.update_success_pattern_record(pattern_id, status=previous_status)
            restored["patterns"].append(pattern_id)
    maintenance_before = before.get("approve_maintenance")
    if isinstance(maintenance_before, dict):
        for action_id, previous_status in maintenance_before.items():
            previous_status = str(previous_status or "pending_approval")
            matches = [item for item in core.read_maintenance_actions() if str(item.get("id")) == action_id]
            if not matches or previous_status not in core.MAINTENANCE_ACTION_STATUSES:
                problems.append(f"maintenance action {action_id} not found")
                continue
            if str(matches[0].get("status") or "") != "approved":
                problems.append(f"maintenance action {action_id} is {matches[0].get('status')}, not approved; left as is")
                continue
            metadata = dict(matches[0].get("metadata") or {}) if isinstance(matches[0].get("metadata"), dict) else {}
            metadata.pop("approved_by", None)
            metadata.pop("approved_source", None)
            core.update_maintenance_action_record(action_id, status=previous_status, metadata={**metadata, "self_change_reverted": session_id})
            restored["maintenance"].append(action_id)
    if backup_dir.is_dir():
        restored["files"] = core.restore_paths_from_backup(backup_dir, core.load_config())
        if restored["files"]:
            try:
                core.sync_runtime_python_code(check_only=False)
            except Exception as exc:  # noqa: BLE001
                problems.append(f"runtime sync failed: {core.normalize_text_value(exc, fallback='', limit=120)}")
    original = next((row for row in reversed(core.read_self_change_ledger(limit=2000)) if str(row.get("session_id") or "") == session_id and str(row.get("outcome") or "") != "reverted"), {})
    proposal_id = str(original.get("proposal_id") or "")
    if proposal_id:
        try:
            metadata = {}
            for item in core.read_proposals():
                if str(item.get("id")) == proposal_id:
                    metadata = dict(item.get("metadata") or {}) if isinstance(item.get("metadata"), dict) else {}
                    break
            core.update_proposal_record(proposal_id, status="archived", metadata={**metadata, "self_change_reverted_at": started, "self_change_reverted_session": session_id})
        except SystemExit:
            problems.append(f"proposal {proposal_id} not found")
    changes = (
        [f"config:{key}" for key in restored["config_keys"]]
        + (["action_blocks"] if restored["action_blocks"] else [])
        + [f"pattern:{pid}" for pid in restored["patterns"]]
        + [f"maintenance:{aid}" for aid in restored["maintenance"]]
        + [f"file:{path}" for path in restored["files"]]
    )
    verification = "restored from before.json" + (" and backup" if restored["files"] else "") if changes else "nothing to restore"
    if problems:
        verification += "; " + "; ".join(problems)[:300]
    row = {
        "started_at": started, "finished_at": core.utc_now(), "elapsed_seconds": 0.0, "source": source, "session_id": session_id,
        "reverted_session": session_id, "proposal_id": original.get("proposal_id"), "proposal_title": core.normalize_text_value(original.get("proposal_title"), fallback="", limit=160),
        "outcome": "reverted", "changes": changes, "patched_paths": list(restored["files"]), "verified": not problems, "verification": verification,
        "rollback": list(restored["files"]), "restart_requested": False, "error": "", "report": f"Reverted self-change {session_id}: {', '.join(changes) or 'nothing to restore'}.",
    }
    core.append_self_change_ledger(row)
    core.append_entry("self_change_reverted", f"Self-change {session_id} reverted: {', '.join(changes) or 'nothing to restore'}. {verification}", metadata={k: v for k, v in row.items() if k != "report"})
    return {"ok": not problems, "session_id": session_id, "restored": restored, "changes": changes, "problems": problems, "verification": verification, "note": "a restored code file needs a daemon restart to take effect" if restored["files"] else ""}


def self_change_metric_spec(changes: List[str], patched_paths: List[str]) -> Dict[str, object]:
    """What would show that this change helped or hurt, named before the change is measured."""
    joined = " ".join(str(item) for item in changes)
    match = core.re.search(r'block_action:\{"action": "([a-z_]+)"', joined)
    if match:
        return {"kind": "action_failures", "action": match.group(1), "direction": "lower_is_better", "window_hours": 24}
    match = core.re.search(r'"key": "operation_model_overrides", "value": \{"([a-z_]+)"', joined)
    if match:
        return {"kind": "operation_ok_rate", "operation": match.group(1), "direction": "higher_is_better", "window_hours": 24}
    if "set_config" in joined:
        key = core.re.search(r'"key": "([a-z_]+)"', joined)
        return {"kind": "config_change", "config_key": key.group(1) if key else "", "direction": "manual", "window_hours": 24}
    if patched_paths:
        return {"kind": "code_change", "paths": list(patched_paths)[:6], "direction": "manual", "window_hours": 24}
    return {"kind": "manual", "direction": "manual", "window_hours": 24}


def schedule_self_change_followup(row: Dict[str, object], config: Dict[str, object]) -> Dict[str, object]:
    """Write the promise that this change will be checked, with the metric named up front."""
    hours = core.clamp_int(config.get("self_change_followup_due_hours"), 24, minimum=1, maximum=24 * 14)
    spec = core.self_change_metric_spec(list(row.get("changes") or []), list(row.get("patched_paths") or []))
    followup = {
        "id": str(core.uuid.uuid4()),
        "session_id": row.get("session_id"),
        "proposal_id": row.get("proposal_id"),
        "proposal_title": row.get("proposal_title"),
        "scheduled_at": core.utc_now(),
        "due_at": (core.utc_now_datetime() + core.timedelta(hours=hours)).isoformat(timespec="seconds"),
        "metric_spec": spec,
        "baseline": core.measure_self_change_metric(spec, before=True),
        "status": "pending",
    }
    core.append_jsonl_record(core.SELF_CHANGE_FOLLOWUPS_PATH, followup)
    return followup


def measure_self_change_metric(spec: Dict[str, object], *, before: bool = False) -> Dict[str, object]:
    """Measure the named metric from the ledgers. Returns {"value": float|None, "detail": str}."""
    kind = str(spec.get("kind") or "manual")
    hours = core.clamp_int(spec.get("window_hours"), 24, minimum=1, maximum=24 * 14)
    cutoff = (core.utc_now_datetime() - core.timedelta(hours=hours)).isoformat(timespec="seconds")
    if kind == "action_failures":
        action = str(spec.get("action") or "")
        try:
            rows = [item for item in core.read_action_executions(limit=500) if str(item.get("action") or "") == action and str(item.get("created_at") or item.get("updated_at") or "") >= cutoff]
        except Exception:  # noqa: BLE001
            return {"value": None, "detail": "action ledger unreadable"}
        failures = sum(1 for item in rows if not core.action_result_explicit_verification(item))
        return {"value": float(failures), "detail": f"{failures} failed {action} run(s) of {len(rows)} in {hours}h"}
    if kind == "operation_ok_rate":
        operation = str(spec.get("operation") or "")
        try:
            rows = [core.json.loads(line) for line in core.PERF_EVENTS_PATH.read_text(encoding="utf-8").splitlines()[-4000:] if line.strip()]
        except (OSError, ValueError):
            return {"value": None, "detail": "perf events unreadable"}
        rows = [item for item in rows if operation in str(item.get("operation") or "") and str(item.get("timestamp") or "") >= cutoff]
        if not rows:
            return {"value": None, "detail": f"no {operation} calls in {hours}h"}
        ok = sum(1 for item in rows if item.get("ok"))
        return {"value": round(ok / len(rows), 3), "detail": f"{ok} of {len(rows)} {operation} calls ok in {hours}h"}
    return {"value": None, "detail": f"{kind}: no automatic metric; a human or a later experiment closes this"}


def self_change_followup_verdict(spec: Dict[str, object], baseline: Dict[str, object], measured: Dict[str, object]) -> Tuple[str, str]:
    """improved | regressed | unchanged | unmeasured, with the sentence that says why."""
    before, after = baseline.get("value"), measured.get("value")
    if before is None or after is None:
        return "unmeasured", f"before: {baseline.get('detail')}; after: {measured.get('detail')}"
    direction = str(spec.get("direction") or "manual")
    delta = after - before
    if direction == "lower_is_better":
        verdict = "improved" if delta < 0 else "regressed" if delta > 0 else "unchanged"
    elif direction == "higher_is_better":
        verdict = "improved" if delta > 0 else "regressed" if delta < 0 else "unchanged"
    else:
        return "unmeasured", f"no direction for {spec.get('kind')}"
    return verdict, f"{baseline.get('detail')} -> {measured.get('detail')}"


def review_self_change_followups(config: Dict[str, object], *, now: Optional[str] = None, source: str = "daemon") -> Dict[str, object]:
    """Measure every due follow-up, write an outcome, and undo a change that made things worse.

    This is the half of self-authority that was missing: she could change herself, but nothing ever
    came back and said whether it helped. A regression now reverses itself from the before-image.
    """
    current = now or core.utc_now()
    rows = core.read_jsonl_records(core.SELF_CHANGE_FOLLOWUPS_PATH)
    reviewed: List[Dict[str, object]] = []
    updated = False
    for index, raw in enumerate(rows):
        row = dict(raw) if isinstance(raw, dict) else {}
        if str(row.get("status") or "") != "pending" or str(row.get("due_at") or "") > current:
            continue
        spec = row.get("metric_spec") if isinstance(row.get("metric_spec"), dict) else {}
        measured = core.measure_self_change_metric(spec)
        verdict, detail = core.self_change_followup_verdict(spec, row.get("baseline") if isinstance(row.get("baseline"), dict) else {}, measured)
        undone = {}
        if verdict == "regressed" and core.parse_boolish(config.get("self_change_undo_on_regression", True)):
            undone = core.revert_self_change(str(row.get("session_id") or ""), source="self_change_followup")
            core.append_entry(
                "self_change_undone",
                f"Undid {row.get('proposal_title')}: {detail}",
                metadata={"session_id": row.get("session_id"), "proposal_id": row.get("proposal_id"), "verdict": verdict, "revert_ok": bool(undone.get("ok")), "source": source},
            )
        try:
            core.create_outcome(
                target_kind="self_change",
                target_id=str(row.get("session_id") or ""),
                direction={"improved": "positive", "regressed": "negative", "unchanged": "neutral"}.get(verdict, "neutral"),
                outcome=verdict,
                summary=core.normalize_text_value(f"{row.get('proposal_title')}: {detail}", fallback=verdict, limit=300),
                evidence=core.json.dumps({"metric_spec": spec, "baseline": row.get("baseline"), "measured": measured})[:600],
                source="self_change_followup",
            )
        except Exception:  # noqa: BLE001 - an outcome writer failure must not lose the verdict
            pass
        try:
            core.record_pattern_from_consequence({**row, "detail": detail}, verdict)
        except Exception:  # noqa: BLE001
            pass
        row.update({"status": "reviewed", "reviewed_at": current, "measured": measured, "verdict": verdict, "detail": detail, "undone": bool(undone.get("ok"))})
        rows[index] = row
        updated = True
        core.append_self_change_ledger({
            "started_at": row.get("scheduled_at"), "finished_at": current, "source": source, "session_id": row.get("session_id"),
            "proposal_id": row.get("proposal_id"), "proposal_title": row.get("proposal_title"), "outcome": "consequence",
            "verdict": verdict, "detail": detail, "undone": bool(undone.get("ok")), "metric_spec": spec,
        })
        reviewed.append({"session_id": row.get("session_id"), "verdict": verdict, "undone": bool(undone.get("ok")), "detail": detail})
    if updated:
        core.write_jsonl_records(core.SELF_CHANGE_FOLLOWUPS_PATH, rows)
    return {"reviewed": reviewed, "pending": sum(1 for item in rows if str(item.get("status") or "") == "pending")}
