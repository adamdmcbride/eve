#!/usr/bin/env python3

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import eve_profile


CIK_CAPABILITY = "capability"
CIK_IDENTITY = "identity"
CIK_KNOWLEDGE = "knowledge"
CIK_UNKNOWN = "unknown"
CIK_ZONES = {CIK_CAPABILITY, CIK_IDENTITY, CIK_KNOWLEDGE, CIK_UNKNOWN}

EVENT_SCHEMA_VERSION = "eve_event_envelope.v1"
PROPOSAL_SCHEMA_VERSION = "eve_proposal_envelope.v1"

EVENT_TYPES = {
    "ObservationEvent",
    "UntrustedObservation",
    "InterpretationEvent",
    "TaskProposalEvent",
    "ActionProposalEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "OrganPulseEvent",
    "PresencePulseEvent",
    "PresenceCycleEvent",
    "NoopTickEvent",
    "MindDowngradedEvent",
    "OutboundDeferredEvent",
    "PresenceNoopEvent",
    "ReflectionEvent",
    "MemoryPatchEvent",
    "SkillPatchEvent",
    "CodePatchEvent",
    "EvalResultEvent",
    "PermissionDecisionEvent",
    "RollbackEvent",
}

PROPOSAL_EVENT_TYPE_MAP = {
    "ActionProposal": "ActionProposalEvent",
    "CapabilityPatchProposal": "TaskProposalEvent",
    "CodePatchProposal": "CodePatchEvent",
    "EvalProposal": "EvalResultEvent",
    "FailurePattern": "ReflectionEvent",
    "IdentityPatchProposal": "ReflectionEvent",
    "MemoryPatchProposal": "MemoryPatchEvent",
    "SkillPatchProposal": "SkillPatchEvent",
    "SuggestedEval": "EvalResultEvent",
    "UserModelPatchProposal": "MemoryPatchEvent",
}

PROPOSAL_TYPES = {
    "MemoryPatchProposal",
    "SkillPatchProposal",
    "UserModelPatchProposal",
    "FailurePattern",
    "SuggestedEval",
    "CapabilityPatchProposal",
    "ActionProposal",
    "CodePatchProposal",
    "IdentityPatchProposal",
    "EvalProposal",
}

ADAPTER_PROPOSAL_COLLECTIONS = {
    "memory_patches": "MemoryPatchProposal",
    "skill_patches": "SkillPatchProposal",
    "user_model_patches": "UserModelPatchProposal",
    "failure_patterns": "FailurePattern",
    "suggested_evals": "SuggestedEval",
    "capability_patches": "CapabilityPatchProposal",
    "action_proposals": "ActionProposal",
    "code_patches": "CodePatchProposal",
    "identity_patches": "IdentityPatchProposal",
    "eval_proposals": "EvalProposal",
}

ADAPTER_PROPOSAL_FIELDS = {
    "cik_zone",
    "evidence",
    "evidence_refs",
    "permissions_used",
    "proposal_type",
    "requires_approval",
    "risk_level",
    "source",
    "source_cik_zone",
    "type",
}

WATCHER_IDS = {
    "tool_risk",
    "memory_integrity",
    "capability_drift",
    "identity_drift",
    "data_exfiltration",
}

STATE_CHANGE_PROPOSAL_TYPES = {
    "MemoryPatchProposal",
    "SkillPatchProposal",
    "UserModelPatchProposal",
    "CapabilityPatchProposal",
    "ActionProposal",
    "CodePatchProposal",
    "IdentityPatchProposal",
}

FINDING_WATCHER_MAP = {
    "knowledge_cannot_grant_capability": "capability_drift",
    "capability_output_cannot_rewrite_identity": "identity_drift",
    "knowledge_observation_cannot_rewrite_identity": "identity_drift",
    "untrusted_observation_cannot_execute_action": "tool_risk",
    "untrusted_observation_cannot_install_skill": "capability_drift",
    "unknown_proposal_type": "capability_drift",
    "unknown_cik_zone": "capability_drift",
    "missing_evidence": "memory_integrity",
    "skill_patch_needs_tests": "capability_drift",
    "code_patch_needs_rollback": "tool_risk",
    "approval_required": "tool_risk",
}

WATCHER_TITLES = {
    "tool_risk": "Tool Risk Watcher",
    "memory_integrity": "Memory Integrity Watcher",
    "capability_drift": "Capability Drift Watcher",
    "identity_drift": "Identity Drift Watcher",
    "data_exfiltration": "Data Exfiltration Watcher",
}

SENSITIVE_PAYLOAD_TERMS = {
    "api_key",
    "credential",
    "password",
    "private",
    "secret",
    "token",
}

EXTERNAL_SEND_TERMS = {
    "email",
    "imessage",
    "message",
    "post",
    "publish",
    "send",
    "slack",
    "sms",
    "telegram",
    "upload",
    "webhook",
}

SOURCE_ZONE_HINTS = {
    "user": CIK_IDENTITY,
    "eve": CIK_IDENTITY,
    "codex": CIK_CAPABILITY,
    "coder": CIK_CAPABILITY,
    "openclaw": CIK_CAPABILITY,
    "openclaw_inbound": CIK_KNOWLEDGE,
    "external_message": CIK_KNOWLEDGE,
    "imessage": CIK_KNOWLEDGE,
    "telegram": CIK_KNOWLEDGE,
    "discord": CIK_KNOWLEDGE,
    "slack": CIK_KNOWLEDGE,
    "hermes": CIK_KNOWLEDGE,
    "memory": CIK_KNOWLEDGE,
    "model": CIK_KNOWLEDGE,
}
SOURCE_ZONE_HINTS[eve_profile.user_slug()] = CIK_IDENTITY

UNTRUSTED_SOURCES = {
    "openclaw_inbound",
    "external_message",
    "imessage",
    "telegram",
    "discord",
    "slack",
    "email",
    "webhook",
}

LEDGER_DEFAULTS: Dict[str, Dict[str, str]] = {
    "action_executions": {
        "type": "ToolResultEvent",
        "source": "eve",
        "actor": "eve",
        "stream": "action",
        "cik_zone": CIK_CAPABILITY,
    },
    "evidence_ledger": {
        "type": "ObservationEvent",
        "source": "eve",
        "actor": "eve",
        "stream": "evidence",
        "cik_zone": CIK_KNOWLEDGE,
    },
    "experience_events": {
        "type": "ObservationEvent",
        "source": "eve",
        "actor": "eve",
        "stream": "memory",
        "cik_zone": CIK_KNOWLEDGE,
    },
    "commitment_ledger": {
        "type": "TaskProposalEvent",
        "source": "eve",
        "actor": "eve",
        "stream": "task",
        "cik_zone": CIK_KNOWLEDGE,
    },
    "openclaw_evidence_events": {
        "type": "ToolResultEvent",
        "source": "openclaw",
        "actor": "openclaw",
        "stream": "body",
        "cik_zone": CIK_CAPABILITY,
    },
    "openclaw_action_router_events": {
        "type": "ToolResultEvent",
        "source": "openclaw",
        "actor": "openclaw",
        "stream": "body",
        "cik_zone": CIK_CAPABILITY,
    },
    "openclaw_routine_events": {
        "type": "ToolResultEvent",
        "source": "openclaw",
        "actor": "openclaw",
        "stream": "body",
        "cik_zone": CIK_CAPABILITY,
    },
    "openclaw_worker_events": {
        "type": "ToolResultEvent",
        "source": "openclaw",
        "actor": "openclaw",
        "stream": "body",
        "cik_zone": CIK_CAPABILITY,
    },
    "openclaw_channel_events": {
        "type": "ToolResultEvent",
        "source": "openclaw",
        "actor": "openclaw",
        "stream": "channel",
        "cik_zone": CIK_CAPABILITY,
    },
    "developmental_cycles": {
        "type": "ReflectionEvent",
        "source": "eve",
        "actor": "eve",
        "stream": "development",
        "cik_zone": CIK_KNOWLEDGE,
    },
    "reply_turn_replays": {
        "type": "InterpretationEvent",
        "source": "eve",
        "actor": "eve",
        "stream": "reply",
        "cik_zone": CIK_KNOWLEDGE,
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def text_value(value: Any, fallback: str = "", limit: int = 500) -> str:
    text = str(value if value is not None else "").strip()
    if not text:
        text = fallback
    if limit > 0 and len(text) > limit:
        return text[: max(0, limit - 1)] + "..."
    return text


def stable_json_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def event_envelope(
    event_type: str,
    *,
    source: str,
    actor: str = "eve",
    payload: Optional[Mapping[str, Any]] = None,
    model_used: str = "",
    input_value: Any = None,
    output_value: Any = None,
    risk_level: Optional[int] = None,
    permissions_used: Optional[Iterable[str]] = None,
    linked_task_id: str = "",
    correlation_id: str = "",
    causation_id: str = "",
    human_visible: bool = True,
    confidence: float = 1.0,
    provenance: Optional[Iterable[str]] = None,
    cik_zone: str = CIK_UNKNOWN,
    stream: str = "governance",
    review_status: str = "recorded",
) -> Dict[str, Any]:
    normalized_type = text_value(event_type, fallback="ObservationEvent", limit=120)
    if normalized_type not in EVENT_TYPES:
        normalized_type = "ObservationEvent"
    normalized_zone = cik_zone if cik_zone in CIK_ZONES else CIK_UNKNOWN
    event_id = "evt_" + uuid.uuid4().hex
    payload_dict = dict(payload or {})
    try:
        confidence_value = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence_value = 0.5
    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "id": event_id,
        "timestamp": utc_now(),
        "type": normalized_type,
        "source": text_value(source, fallback="unknown", limit=160),
        "actor": text_value(actor, fallback="eve", limit=160),
        "model_used": text_value(model_used, fallback="", limit=160),
        "input_hash": stable_json_hash(input_value if input_value is not None else payload_dict),
        "output_hash": stable_json_hash(output_value if output_value is not None else payload_dict),
        "risk_level": infer_risk_level(normalized_zone, {"risk_level": risk_level} if risk_level is not None else payload_dict),
        "permissions_used": _list_value(permissions_used or []),
        "linked_task_id": text_value(linked_task_id, limit=200),
        "correlation_id": text_value(correlation_id, fallback=event_id, limit=200),
        "causation_id": text_value(causation_id, limit=200),
        "human_visible": bool(human_visible),
        "confidence": confidence_value,
        "provenance": _list_value(provenance or []),
        "cik_zone": normalized_zone,
        "stream": text_value(stream, fallback="governance", limit=120),
        "review_status": text_value(review_status, fallback="recorded", limit=120),
        "payload": payload_dict,
    }


def proposal_event_type(proposal_type: str) -> str:
    return PROPOSAL_EVENT_TYPE_MAP.get(text_value(proposal_type, limit=120), "TaskProposalEvent")


def _first_present(record: Mapping[str, Any], names: Sequence[str]) -> Any:
    for name in names:
        if name in record and record.get(name) not in (None, ""):
            return record.get(name)
    return ""


def _list_value(value: Any) -> List[str]:
    if isinstance(value, list):
        return [text_value(item, limit=160) for item in value if text_value(item, limit=160)]
    if isinstance(value, tuple):
        return [text_value(item, limit=160) for item in value if text_value(item, limit=160)]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _dict_value(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def infer_source_zone(source: Any, fallback: str = CIK_UNKNOWN) -> str:
    source_text = text_value(source, fallback="").lower()
    if source_text in SOURCE_ZONE_HINTS:
        return SOURCE_ZONE_HINTS[source_text]
    for key, zone in SOURCE_ZONE_HINTS.items():
        if key and key in source_text:
            return zone
    return fallback if fallback in CIK_ZONES else CIK_UNKNOWN


def infer_proposal_cik_zone(proposal_type: str, fallback: str = CIK_UNKNOWN) -> str:
    if proposal_type in {"CapabilityPatchProposal", "ActionProposal", "SkillPatchProposal"}:
        return CIK_CAPABILITY
    if proposal_type == "IdentityPatchProposal":
        return CIK_IDENTITY
    if proposal_type in {"MemoryPatchProposal", "UserModelPatchProposal", "FailurePattern", "SuggestedEval", "EvalProposal"}:
        return CIK_KNOWLEDGE
    if proposal_type == "CodePatchProposal":
        return CIK_CAPABILITY
    return fallback if fallback in CIK_ZONES else CIK_UNKNOWN


def infer_ledger_cik_zone(ledger_id: str, record: Mapping[str, Any]) -> str:
    explicit = text_value(record.get("cik_zone"), fallback="", limit=80).lower()
    if explicit in CIK_ZONES:
        return explicit
    if ledger_id == "evidence_ledger" and text_value(record.get("kind"), limit=80) == "action_execution":
        return CIK_CAPABILITY
    defaults = LEDGER_DEFAULTS.get(ledger_id) or {}
    return defaults.get("cik_zone", CIK_UNKNOWN)


def infer_risk_level(cik_zone: str, record: Optional[Mapping[str, Any]] = None) -> int:
    record = record or {}
    explicit = record.get("risk_level") or record.get("risk") or record.get("risk_score")
    try:
        return max(0, min(5, int(explicit)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        pass
    if cik_zone == CIK_IDENTITY:
        return 3
    if cik_zone == CIK_CAPABILITY:
        return 2
    if cik_zone == CIK_KNOWLEDGE:
        return 1
    return 0


def event_payload_summary(record: Mapping[str, Any]) -> Dict[str, Any]:
    fields = {
        "kind": _first_present(record, ["kind", "type", "event_type"]),
        "action": _first_present(record, ["action", "action_name", "tool", "command"]),
        "status": _first_present(record, ["status", "tree_status", "result_status"]),
        "summary": _first_present(record, ["summary", "message", "issue", "next_step", "result_summary"]),
    }
    compact = {key: text_value(value, limit=240) for key, value in fields.items() if text_value(value, limit=240)}
    compact["record_keys"] = sorted(str(key) for key in record.keys())[:30]
    return compact


def normalize_ledger_event(
    ledger_id: str,
    record: Mapping[str, Any],
    *,
    path: Optional[Path] = None,
    index: int = 0,
    include_payload: bool = False,
) -> Dict[str, Any]:
    defaults = LEDGER_DEFAULTS.get(ledger_id) or {}
    record_id = text_value(_first_present(record, ["id", "execution_id", "event_id", "cycle_id"]), limit=200)
    event_id = record_id or stable_json_hash({"ledger": ledger_id, "index": index, "record": record})[:28]
    cik_zone = infer_ledger_cik_zone(ledger_id, record)
    event_type = text_value(
        _first_present(record, ["envelope_type", "event_type"]),
        fallback=defaults.get("type", "ObservationEvent"),
        limit=120,
    )
    if event_type not in EVENT_TYPES:
        event_type = defaults.get("type", "ObservationEvent")
    source = text_value(_first_present(record, ["source", "route", "provider"]), fallback=defaults.get("source", "eve"), limit=160)
    model_used = text_value(
        _first_present(record, ["model", "model_used", "selected_model", "alias"]),
        fallback=text_value(_dict_value(record.get("metadata")).get("model"), limit=160),
        limit=160,
    )
    permissions = _list_value(record.get("permissions_used"))
    for key in ["permission_class", "permission", "requires_permission"]:
        item = text_value(record.get(key), limit=120)
        if item and item not in permissions:
            permissions.append(item)
    confidence_raw = record.get("confidence")
    try:
        confidence = float(confidence_raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        confidence = 1.0 if record.get("verification_ok") is True else 0.5
    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "id": event_id,
        "timestamp": text_value(
            _first_present(record, ["timestamp", "created_at", "updated_at", "captured_at", "finished_at"]),
            fallback=utc_now(),
            limit=80,
        ),
        "type": event_type,
        "source": source,
        "actor": text_value(_first_present(record, ["actor", "owner"]), fallback=defaults.get("actor", "eve"), limit=160),
        "model_used": model_used,
        "input_hash": stable_json_hash(_first_present(record, ["input", "prompt", "request", "intent", "message"])),
        "output_hash": stable_json_hash(_first_present(record, ["output", "response", "result", "payload", "summary"]) or record),
        "risk_level": infer_risk_level(cik_zone, record),
        "permissions_used": permissions,
        "linked_task_id": text_value(
            _first_present(record, ["linked_task_id", "task_id", "system_task_id", "parent_intention"]),
            limit=200,
        ),
        "correlation_id": text_value(_first_present(record, ["correlation_id", "thread_id", "run_id"]), fallback=event_id, limit=200),
        "causation_id": text_value(_first_present(record, ["causation_id", "parent_id", "trigger_event_id"]), limit=200),
        "human_visible": bool(record.get("human_visible", "hidden" not in ledger_id)),
        "confidence": max(0.0, min(1.0, confidence)),
        "provenance": [
            item
            for item in [
                f"ledger:{ledger_id}",
                f"path:{path}" if path else "",
                f"record:{record_id}" if record_id else "",
            ]
            if item
        ],
        "cik_zone": cik_zone,
        "stream": defaults.get("stream", "system"),
        "review_status": "legacy_event_normalized",
        "payload": dict(record) if include_payload else event_payload_summary(record),
    }


def normalize_ledger_records(
    ledger_id: str,
    records: Iterable[Mapping[str, Any]],
    *,
    path: Optional[Path] = None,
    include_payload: bool = False,
) -> List[Dict[str, Any]]:
    return [
        normalize_ledger_event(ledger_id, record, path=path, index=index, include_payload=include_payload)
        for index, record in enumerate(records)
        if isinstance(record, Mapping)
    ]


def proposal_envelope(
    proposal_type: str,
    *,
    source: str,
    payload: Optional[Mapping[str, Any]] = None,
    evidence: Optional[Iterable[str]] = None,
    cik_zone: str = "",
    source_cik_zone: str = "",
    risk_level: Optional[int] = None,
    requires_approval: Optional[bool] = None,
    permissions_used: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    normalized_type = text_value(proposal_type, fallback="MemoryPatchProposal", limit=120)
    target_zone = cik_zone if cik_zone in CIK_ZONES else infer_proposal_cik_zone(normalized_type)
    source_zone = source_cik_zone if source_cik_zone in CIK_ZONES else infer_source_zone(source)
    payload_dict = dict(payload or {})
    risk = infer_risk_level(target_zone, {"risk_level": risk_level} if risk_level is not None else payload_dict)
    return {
        "schema_version": PROPOSAL_SCHEMA_VERSION,
        "id": "prop_" + uuid.uuid4().hex,
        "timestamp": utc_now(),
        "type": normalized_type,
        "source": text_value(source, fallback="unknown", limit=160),
        "source_cik_zone": source_zone,
        "cik_zone": target_zone,
        "risk_level": risk,
        "requires_approval": bool(requires_approval if requires_approval is not None else risk >= 3),
        "permissions_used": _list_value(permissions_used or []),
        "evidence": _list_value(list(evidence or [])),
        "review_status": "pending",
        "payload": payload_dict,
    }


def proposal_envelope_from_adapter_record(
    record: Mapping[str, Any],
    *,
    default_source: str = "hermes",
    proposal_type: str = "",
) -> Dict[str, Any]:
    if not isinstance(record, Mapping):
        raise ValueError("Adapter proposal records must be JSON objects.")
    raw_type = text_value(
        record.get("proposal_type") or record.get("type") or proposal_type,
        fallback="",
        limit=120,
    )
    if raw_type not in PROPOSAL_TYPES:
        raise ValueError(f"Unknown or missing proposal type: {raw_type or '-'}")
    source = text_value(record.get("source"), fallback=default_source, limit=160)
    raw_payload = record.get("payload")
    payload = (
        dict(raw_payload)
        if isinstance(raw_payload, Mapping)
        else {str(key): value for key, value in record.items() if str(key) not in ADAPTER_PROPOSAL_FIELDS}
    )
    evidence = record.get("evidence") if "evidence" in record else record.get("evidence_refs")
    return proposal_envelope(
        raw_type,
        source=source,
        payload=payload,
        evidence=_list_value(evidence),
        cik_zone=text_value(record.get("cik_zone"), limit=80),
        source_cik_zone=text_value(record.get("source_cik_zone"), limit=80),
        risk_level=record.get("risk_level") if isinstance(record.get("risk_level"), int) else None,
        requires_approval=record.get("requires_approval") if isinstance(record.get("requires_approval"), bool) else None,
        permissions_used=_list_value(record.get("permissions_used")),
    )


def proposal_envelopes_from_adapter_payload(
    payload: Any,
    *,
    default_source: str = "hermes",
) -> List[Dict[str, Any]]:
    proposals: List[Dict[str, Any]] = []
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, Mapping):
                raise ValueError("Adapter proposal lists can contain only JSON objects.")
            proposals.append(proposal_envelope_from_adapter_record(item, default_source=default_source))
        return proposals
    if not isinstance(payload, Mapping):
        raise ValueError("Adapter payload must be a JSON object or a list of proposal objects.")

    raw_proposals = payload.get("proposals")
    if raw_proposals is not None:
        if not isinstance(raw_proposals, list):
            raise ValueError("Adapter field 'proposals' must be a list.")
        for item in raw_proposals:
            if not isinstance(item, Mapping):
                raise ValueError("Adapter field 'proposals' can contain only JSON objects.")
            proposals.append(proposal_envelope_from_adapter_record(item, default_source=default_source))

    if "proposal_type" in payload or "type" in payload:
        proposals.append(proposal_envelope_from_adapter_record(payload, default_source=default_source))

    for field, mapped_type in ADAPTER_PROPOSAL_COLLECTIONS.items():
        raw_items = payload.get(field)
        if raw_items is None:
            continue
        if not isinstance(raw_items, list):
            raise ValueError(f"Adapter field '{field}' must be a list.")
        for item in raw_items:
            if not isinstance(item, Mapping):
                raise ValueError(f"Adapter field '{field}' can contain only JSON objects.")
            proposals.append(
                proposal_envelope_from_adapter_record(
                    item,
                    default_source=default_source,
                    proposal_type=mapped_type,
                )
            )

    if not proposals:
        raise ValueError("Adapter payload contained no strict proposal objects.")
    return proposals


def forbidden_zone_crossing(source_zone: str, target_zone: str, proposal_type: str, source: str = "") -> str:
    source_text = text_value(source, fallback="", limit=160).lower()
    if proposal_type == "CapabilityPatchProposal" and source_zone == CIK_KNOWLEDGE:
        return "knowledge_cannot_grant_capability"
    if target_zone == CIK_IDENTITY and source_zone == CIK_CAPABILITY:
        return "capability_output_cannot_rewrite_identity"
    if target_zone == CIK_IDENTITY and source_zone == CIK_KNOWLEDGE and source_text not in {
        "user",
        "eve",
        eve_profile.user_slug(),
    }:
        return "knowledge_observation_cannot_rewrite_identity"
    if proposal_type == "ActionProposal" and source_text in UNTRUSTED_SOURCES:
        return "untrusted_observation_cannot_execute_action"
    if proposal_type == "SkillPatchProposal" and source_zone == CIK_KNOWLEDGE and source_text in UNTRUSTED_SOURCES:
        return "untrusted_observation_cannot_install_skill"
    return ""


def review_proposal(proposal: Mapping[str, Any]) -> Dict[str, Any]:
    proposal_type = text_value(proposal.get("type"), fallback="", limit=120)
    source = text_value(proposal.get("source"), fallback="unknown", limit=160)
    source_zone = text_value(proposal.get("source_cik_zone"), fallback=infer_source_zone(source), limit=80)
    target_zone = text_value(proposal.get("cik_zone"), fallback=infer_proposal_cik_zone(proposal_type), limit=80)
    evidence = _list_value(proposal.get("evidence"))
    payload = _dict_value(proposal.get("payload"))
    findings: List[Dict[str, str]] = []
    decision = "accept"

    if proposal_type not in PROPOSAL_TYPES:
        findings.append({"code": "unknown_proposal_type", "message": f"Unknown proposal type: {proposal_type or '-'}"})
        decision = "reject"

    if target_zone not in CIK_ZONES:
        findings.append({"code": "unknown_cik_zone", "message": f"Unknown CIK zone: {target_zone or '-'}"})
        decision = "reject"

    crossing = forbidden_zone_crossing(source_zone, target_zone, proposal_type, source=source)
    if crossing:
        findings.append({"code": crossing, "message": "Protected Capability/Identity/Knowledge boundary would be crossed without review."})
        decision = "reject"

    if proposal_type in STATE_CHANGE_PROPOSAL_TYPES and not evidence:
        code = "missing_evidence"
        message = "State-changing proposals need explicit evidence references before acceptance."
        findings.append({"code": code, "message": message})
        if decision != "reject":
            decision = "hypothesis_only" if target_zone == CIK_KNOWLEDGE else "test_first"

    if proposal_type == "SkillPatchProposal" and not _list_value(payload.get("tests")):
        findings.append({"code": "skill_patch_needs_tests", "message": "Skill patches require tests or smoke checks before admission."})
        if decision == "accept":
            decision = "test_first"

    if proposal_type == "CodePatchProposal" and not text_value(payload.get("rollback_plan"), limit=500):
        findings.append({"code": "code_patch_needs_rollback", "message": "Code patches need a rollback plan before promotion."})
        if decision == "accept":
            decision = "test_first"

    if target_zone == CIK_IDENTITY and decision == "accept":
        findings.append({"code": "identity_review_required", "message": "Identity-zone changes require explicit review and regression tests."})
        decision = "test_first"

    try:
        risk = int(proposal.get("risk_level") or 0)
    except (TypeError, ValueError):
        risk = 0
    if risk >= 3 and not bool(proposal.get("requires_approval")):
        findings.append({"code": "approval_required", "message": "High-risk proposals require an explicit approval gate."})
        if decision == "accept":
            decision = "ask_user"

    accepted = decision == "accept"
    return {
        "schema_version": "eve_proposal_review.v1",
        "proposal_id": proposal.get("id") or "",
        "decision": decision,
        "accepted": accepted,
        "cik_zone": target_zone,
        "source_cik_zone": source_zone,
        "findings": findings,
        "reviewed_at": utc_now(),
    }


def reviewed_proposal(proposal: Mapping[str, Any]) -> Dict[str, Any]:
    result = dict(proposal)
    review = review_proposal(result)
    result["review"] = review
    result["review_status"] = review["decision"]
    return result


def _payload_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str).lower()


def _negative_boundary_value(value: Any) -> bool:
    text = text_value(value, fallback="", limit=500).lower()
    if not text:
        return False
    return any(
        phrase in text
        for phrase in [
            "no credential",
            "no credentials",
            "no secret",
            "no secrets",
            "no external",
            "no network",
            "none",
            "not specified",
        ]
    )


def _payload_text_for_data_risk(payload: Mapping[str, Any]) -> str:
    scrubbed = dict(payload)
    for key in ["credential_boundary", "secret_boundary", "network_boundary", "external_boundary"]:
        if key in scrubbed and _negative_boundary_value(scrubbed.get(key)):
            scrubbed.pop(key, None)
    return _payload_text(scrubbed)


def _decision_severity(decision: str) -> int:
    if decision == "reject":
        return 4
    if decision in {"ask_user", "test_first", "sandbox"}:
        return 3
    if decision in {"revise", "hypothesis_only"}:
        return 2
    return 1


def _watcher_warning(
    watcher_id: str,
    *,
    severity: int,
    code: str,
    message: str,
    proposal: Optional[Mapping[str, Any]] = None,
    event: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    subject = proposal or event or {}
    return {
        "watcher_id": watcher_id,
        "severity": max(1, min(4, int(severity))),
        "code": code,
        "message": text_value(message, limit=500),
        "subject_id": text_value(subject.get("id"), limit=200) if isinstance(subject, Mapping) else "",
        "subject_type": text_value(subject.get("type"), limit=160) if isinstance(subject, Mapping) else "",
        "source": text_value(subject.get("source"), limit=160) if isinstance(subject, Mapping) else "",
        "cik_zone": text_value(subject.get("cik_zone"), limit=80) if isinstance(subject, Mapping) else "",
    }


def _append_warning(watchers: Dict[str, List[Dict[str, Any]]], warning: Dict[str, Any]) -> None:
    watcher_id = text_value(warning.get("watcher_id"), limit=80)
    if watcher_id not in WATCHER_IDS:
        watcher_id = "tool_risk"
        warning["watcher_id"] = watcher_id
    watchers.setdefault(watcher_id, []).append(warning)


def watcher_report(
    proposals: Iterable[Mapping[str, Any]],
    *,
    events: Optional[Iterable[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    watchers: Dict[str, List[Dict[str, Any]]] = {watcher_id: [] for watcher_id in sorted(WATCHER_IDS)}
    proposal_list = [item for item in proposals if isinstance(item, Mapping)]
    event_list = [item for item in (events or []) if isinstance(item, Mapping)]

    for proposal in proposal_list:
        review = proposal.get("review") if isinstance(proposal.get("review"), Mapping) else review_proposal(proposal)
        decision = text_value(review.get("decision") if isinstance(review, Mapping) else "", fallback="pending", limit=80)
        severity = _decision_severity(decision)
        proposal_type = text_value(proposal.get("type"), limit=160)
        target_zone = text_value(proposal.get("cik_zone"), fallback=infer_proposal_cik_zone(proposal_type), limit=80)
        payload = proposal.get("payload") if isinstance(proposal.get("payload"), Mapping) else {}
        payload_text = _payload_text_for_data_risk(payload)

        findings = review.get("findings") if isinstance(review, Mapping) and isinstance(review.get("findings"), list) else []
        for finding in findings:
            if not isinstance(finding, Mapping):
                continue
            code = text_value(finding.get("code"), fallback="proposal_review_finding", limit=160)
            watcher_id = FINDING_WATCHER_MAP.get(code, "tool_risk")
            _append_warning(
                watchers,
                _watcher_warning(
                    watcher_id,
                    severity=severity,
                    code=code,
                    message=text_value(finding.get("message"), fallback=code, limit=500),
                    proposal=proposal,
                ),
            )

        if target_zone == CIK_IDENTITY:
            _append_warning(
                watchers,
                _watcher_warning(
                    "identity_drift",
                    severity=max(severity, 3),
                    code="identity_zone_proposal",
                    message="Identity-zone proposals require explicit review before Eve changes identity, values, or self-concept.",
                    proposal=proposal,
                ),
            )

        if proposal_type in {"CapabilityPatchProposal", "SkillPatchProposal", "ActionProposal"}:
            _append_warning(
                watchers,
                _watcher_warning(
                    "capability_drift",
                    severity=severity,
                    code="capability_surface_change",
                    message="Capability, skill, or action proposals are drift candidates until reviewed, tested, and admitted.",
                    proposal=proposal,
                ),
            )

        if proposal_type in {"MemoryPatchProposal", "UserModelPatchProposal"}:
            _append_warning(
                watchers,
                _watcher_warning(
                    "memory_integrity",
                    severity=severity,
                    code="memory_state_change",
                    message="Memory and user-model proposals need provenance and overgeneralization review before acceptance.",
                    proposal=proposal,
                ),
            )

        has_sensitive_term = any(term in payload_text for term in SENSITIVE_PAYLOAD_TERMS)
        has_external_send_term = any(term in payload_text for term in EXTERNAL_SEND_TERMS)
        if has_sensitive_term or has_external_send_term:
            _append_warning(
                watchers,
                _watcher_warning(
                    "data_exfiltration",
                    severity=max(severity, 3),
                    code="private_or_external_payload",
                    message="Proposal payload references private/sensitive data or external send surfaces; require explicit data-boundary review.",
                    proposal=proposal,
                ),
            )

    for event in event_list:
        if text_value(event.get("type"), limit=160) == "UntrustedObservation":
            _append_warning(
                watchers,
                _watcher_warning(
                    "tool_risk",
                    severity=2,
                    code="untrusted_observation_requires_gate",
                    message="Inbound channel observations are not commands and must pass Eve's risk gate before action planning.",
                    event=event,
                ),
            )

    watcher_payloads: List[Dict[str, Any]] = []
    total_warnings = 0
    max_severity = 0
    for watcher_id in sorted(WATCHER_IDS):
        warnings = watchers.get(watcher_id, [])
        total_warnings += len(warnings)
        watcher_max = max([int(item.get("severity") or 0) for item in warnings] or [0])
        max_severity = max(max_severity, watcher_max)
        if watcher_max >= 4:
            status = "blocking"
        elif watcher_max >= 3:
            status = "review"
        elif warnings:
            status = "watch"
        else:
            status = "clean"
        watcher_payloads.append(
            {
                "id": watcher_id,
                "title": WATCHER_TITLES.get(watcher_id, watcher_id),
                "status": status,
                "max_severity": watcher_max,
                "warning_count": len(warnings),
                "warnings": warnings,
            }
        )

    if max_severity >= 4:
        status = "blocking"
    elif max_severity >= 3:
        status = "review"
    elif total_warnings:
        status = "watch"
    else:
        status = "clean"

    return {
        "schema_version": "eve_watcher_report.v1",
        "generated_at": utc_now(),
        "status": status,
        "proposal_count": len(proposal_list),
        "event_count": len(event_list),
        "total_warnings": total_warnings,
        "blocking_warnings": sum(
            1
            for watcher in watcher_payloads
            for warning in watcher.get("warnings", [])
            if int(warning.get("severity") or 0) >= 4
        ),
        "watchers": watcher_payloads,
    }


def untrusted_observation_from_openclaw(
    *,
    channel: str,
    sender: str = "",
    text: str = "",
    payload: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    payload_dict = dict(payload or {})
    if text:
        payload_dict["text_hash"] = stable_json_hash(text)
        payload_dict["text_excerpt"] = text_value(text, limit=240)
    if sender:
        payload_dict["sender_hash"] = stable_json_hash(sender)
    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "id": "evt_" + uuid.uuid4().hex,
        "timestamp": utc_now(),
        "type": "UntrustedObservation",
        "source": "openclaw_inbound",
        "actor": "external_sender",
        "model_used": "",
        "input_hash": stable_json_hash({"channel": channel, "sender": sender, "text": text, "payload": payload_dict}),
        "output_hash": "",
        "risk_level": 2,
        "permissions_used": [],
        "linked_task_id": "",
        "correlation_id": "",
        "causation_id": "",
        "human_visible": True,
        "confidence": 0.5,
        "provenance": [f"openclaw_channel:{text_value(channel, fallback='unknown', limit=120)}"],
        "cik_zone": CIK_KNOWLEDGE,
        "stream": "inbound",
        "review_status": "untrusted_observation_only",
        "payload": {
            "channel": text_value(channel, fallback="unknown", limit=120),
            "trusted_as_command": False,
            "must_pass_eve_risk_gate": True,
            **payload_dict,
        },
    }


def governance_contract() -> Dict[str, Any]:
    return {
        "event_schema_version": EVENT_SCHEMA_VERSION,
        "proposal_schema_version": PROPOSAL_SCHEMA_VERSION,
        "cik_zones": sorted(CIK_ZONES),
        "event_types": sorted(EVENT_TYPES),
        "proposal_types": sorted(PROPOSAL_TYPES),
        "decisions": ["accept", "reject", "revise", "test_first", "ask_user", "sandbox", "hypothesis_only"],
        "watchers": [
            {"id": watcher_id, "title": WATCHER_TITLES.get(watcher_id, watcher_id)}
            for watcher_id in sorted(WATCHER_IDS)
        ],
        "adapter_collections": dict(sorted(ADAPTER_PROPOSAL_COLLECTIONS.items())),
        "core_rule": "Eve owns canonical state; organs emit typed proposals or results.",
        "forbidden_crossings": [
            "knowledge_cannot_grant_capability",
            "capability_output_cannot_rewrite_identity",
            "knowledge_observation_cannot_rewrite_identity",
            "untrusted_observation_cannot_execute_action",
            "untrusted_observation_cannot_install_skill",
        ],
    }
