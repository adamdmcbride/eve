"""Bounded, evidence-bound procedural learning for Eve's existing chooser.

This is a computational analogy to contextual, reversible learning, not a
biological circuit or a consciousness measure. No model calls, stores or tools.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone


SCHEMA = "eve.action_context.v1"
POLICY = "eve.contextual_action_learning.v1"
MAX_AGE_SECONDS = 30 * 86400
KINDS = {"cycle_action_consequence", "bounded_action_attempt",
         "lived_homeostatic_consequence", "lived_user_consequence"}


def _time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_context(*, source, inbound, regulation_mode, metadata):
    """Encode pre-action conditions, never post-action prose or guessed health.

    Source family and query kind are existing typed control inputs. Intent
    labels are coarse request features, not facts about the environment.
    Opaque goal identity prevents credit leaking between unrelated goals.
    """
    text = str(inbound or "").lower()
    features = {
        "mode": "conversation" if text else "background",
        "source": str(source or "unknown").split(":", 1)[0][:80],
        "regulation": str(regulation_mode or "unknown")[:40],
        "query_kind": str(metadata.get("module_query_kind") or "none")[:80],
        "goal": _hash(str(metadata["goal_id"]))[:20] if metadata.get("goal_id") else "none",
    }
    for label, words in {
        "relational": r"feel|trust|hurt|care|relationship|love",
        "inspect": r"check|inspect|verify|evidence|status|diagnose",
        "act": r"fix|run|build|change|implement|do",
        "recall": r"remember|previous|before|again",
        "reflect": r"conscious|meaning|identity|why|mind",
    }.items():
        features[label] = bool(re.search(r"\b(?:" + words + r")\b", text))
    return {"schema_id": SCHEMA, "id": _hash(features), "features": features}


def valid_context(value):
    if not isinstance(value, dict) or value.get("schema_id") != SCHEMA:
        return False
    features = value.get("features")
    strings = {"mode", "source", "regulation", "query_kind", "goal"}
    flags = {"relational", "inspect", "act", "recall", "reflect"}
    return (isinstance(features, dict) and set(features) == strings | flags
            and all(isinstance(features[key], str) and len(features[key]) <= 80 for key in strings)
            and all(type(features[key]) is bool for key in flags)
            and value.get("id") == _hash(features))


def capture_credit(state, action_id):
    """Capture the original affordance, not a newer state or an unchosen tool.

    Multiple descriptions for one action can carry different goals. Ambiguous
    attribution is omitted instead of borrowing the selected action's context.
    """
    if not isinstance(state, dict) or not state.get("cycle_id"):
        return {}
    model = state.get("action_model") or {}
    selected = model.get("selected_intention") or {}
    candidates = [selected] if selected.get("id") == action_id else [
        row for row in model.get("affordances") or []
        if isinstance(row, dict) and row.get("id") == action_id
    ]
    contexts = {row["action_context"]["id"]: row["action_context"] for row in candidates
                if valid_context(row.get("action_context"))}
    if len(contexts) != 1:
        return {}
    return {"source_cycle_id": state["cycle_id"], "action_id": action_id,
            "action_context": copy.deepcopy(next(iter(contexts.values())))}


def bound_context(credit, source_cycle_id, action_id):
    if (isinstance(credit, dict) and credit.get("source_cycle_id") == source_cycle_id
            and credit.get("action_id") == action_id and valid_context(credit.get("action_context"))):
        return copy.deepcopy(credit["action_context"])
    return {}


def qualified_observations(model, context, *, now):
    if not valid_context(context):
        return []
    timestamp = _time(now)
    if timestamp is None:
        return []
    rows = []
    for row in (model or {}).get("observations") or []:
        if not isinstance(row, dict) or type(row.get("ok")) is not bool:
            continue
        if (not valid_context(row.get("action_context"))
                or row["action_context"]["id"] != context["id"]
                or not row.get("source_cycle_id") or not row.get("evidence_id")
                or row.get("evidence_kind") not in KINDS):
            continue
        if row.get("evidence_kind") == "lived_user_consequence" and not (
                row.get("reply_message_id") and row.get("observed_message_id")):
            continue
        at = _time(row.get("completed_at"))
        if at is None or not 0 <= (timestamp - at).total_seconds() <= MAX_AGE_SECONDS:
            continue
        rows.append(row)
    # Completion and attempt can describe the same execution; one cycle is at
    # most one independent sample for this action/context. Contradiction vetoes.
    # Re-reading an execution later with a success label cannot erase an
    # explicit conflicting failure for that same cycle or receipt.
    rows = [{**row, "ok": False, "verification_ok": False}
            if any(other["ok"] is False and (
                other["source_cycle_id"] == row["source_cycle_id"]
                or other["evidence_id"] == row["evidence_id"]
                or (row.get("execution_id") and other.get("execution_id") == row["execution_id"])) for other in rows)
            else row for row in rows]
    unique = []
    seen_cycles, seen_evidence, seen_executions = set(), set(), set()
    rows.sort(key=lambda row: (_time(row["completed_at"]), not row["ok"]), reverse=True)
    for row in rows:
        duplicate = (row["source_cycle_id"] in seen_cycles or row["evidence_id"] in seen_evidence
                     or (row.get("execution_id") and row["execution_id"] in seen_executions))
        seen_cycles.add(row["source_cycle_id"])
        seen_evidence.add(row["evidence_id"])
        if row.get("execution_id"):
            seen_executions.add(row["execution_id"])
        if not duplicate:
            unique.append(row)
    return list(reversed(unique[:12]))


def estimate(model, context, *, now, enabled=True):
    rows = qualified_observations(model, context, now=now) if enabled else []
    # Recency makes reversal possible without erasing the opposing evidence.
    # Time decay moves old confidence toward ignorance, not toward success.
    timestamp = _time(now)
    weights = [0.75 ** (len(rows) - i - 1) * 0.5 ** (
        (timestamp - _time(row["completed_at"])).total_seconds() / (7 * 86400))
        for i, row in enumerate(rows)]
    probability = (2.0 + sum(w for w, row in zip(weights, rows) if row["ok"])) / (4.0 + sum(weights))
    return {"policy": POLICY, "mode": "active" if enabled else "lesioned",
            "attempts": len(rows), "probability": round(probability, 6),
            "adjustment": round((probability - 0.5) * min(48.0, len(rows) * 12.0), 2),
            "evidence_ids": [row["evidence_id"] for row in rows],
            "context_id": context.get("id", "") if valid_context(context) else "",
            "unmatched_or_unqualified": len((model or {}).get("observations") or []) - len(rows)}


def consolidated_candidates(action_models, *, now):
    """Only verified repeated execution becomes a context-bound procedure.

    Returned records go through Eve's existing success-pattern intake. No new
    authority, executable code, identity fact, or language-model weight update.
    """
    candidates = []
    for action, model in sorted((action_models or {}).items()):
        if action == "respond_to_user" or not isinstance(model, dict):
            continue  # acceptance is not a verified executable skill
        contexts = {row["action_context"]["id"]: row["action_context"]
                    for row in model.get("observations") or [] if isinstance(row, dict)
                    and valid_context(row.get("action_context"))}
        for context_id, context in sorted(contexts.items()):
            rows = qualified_observations(model, context, now=now)
            recent = rows[-3:]
            if len(recent) < 3 or not all(row["ok"] and row.get("verification_ok") is True
                                        and row.get("execution_id") for row in recent):
                continue
            prediction = estimate(model, context, now=now)
            candidates.append({
                "dedupe_key": "core-context:" + _hash([action, context_id])[:40],
                "title": "Verified contextual procedure: " + action,
                "situation": "Only when the current pre-action context matches " + context_id,
                "good_move": "Consider the already-admitted action " + action + "; verify its consequence again.",
                "why_it_worked": "Three distinct cycles supplied verified execution receipts in this context.",
                "avoid_when": ["Context changed, evidence expired, or a later outcome contradicted this procedure."],
                "source_kinds": [POLICY], "source_ids": [row["evidence_id"] for row in recent],
                "evidence": [row["evidence_id"] for row in recent], "support_count": 3,
                "confidence": prediction["probability"],
                "metadata": {"contextual_learning": POLICY, "action_id": action,
                             "action_context": context},
            })
    return candidates
