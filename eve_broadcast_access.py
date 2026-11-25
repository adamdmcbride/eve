"""Exact-cycle global-broadcast delivery receipts for Eve.

The conscious-state kernel can declare that selected content is available to a
named consumer.  This module makes delivery inspectable without persisting the
content itself.  A receipt proves that a callable was invoked with the exact
cycle/selection/delivery envelope and returned a digestible result.  It does not
prove semantic comprehension, subjective access, or consciousness.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


ENVELOPE_SCHEMA = "eve.global_broadcast_delivery_envelope.v1"
RECEIPT_SCHEMA = "eve.global_broadcast_consumption_receipt.v1"
COVERAGE_SCHEMA = "eve.global_broadcast_consumption_coverage.v1"
CONSUMER_IDS = ("reply", "mind", "autonomy", "action", "memory", "learning")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RECEIPT_FIELDS = {
    "schema_version",
    "receipt_id",
    "consumed_at",
    "consumer_id",
    "purpose",
    "cycle_id",
    "cycle_index",
    "selection_digest",
    "delivery_digest",
    "content_sha256",
    "envelope_sha256",
    "consumer_output_sha256",
    "receipt_sha256",
}


def _canonical(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("broadcast receipt values must be finite JSON data") from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _identifier(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(text):
        raise ValueError(f"{field} must be a bounded non-prose identifier")
    return text


def _sha256(value: object, field: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA256.fullmatch(text):
        raise ValueError(f"{field} must be a SHA-256 digest")
    return text


def _timestamp(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("an ISO-8601 timestamp is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc).isoformat()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cycle_index(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("cycle_index must be a non-negative integer")
    number = value
    if number < 0:
        raise ValueError("cycle_index must be a non-negative integer")
    return number


def _consumer(value: object) -> str:
    consumer_id = str(value or "").strip().lower()
    if consumer_id not in CONSUMER_IDS:
        raise ValueError("consumer_id must name an admitted global-broadcast consumer")
    return consumer_id


def _json_clone(value: object) -> object:
    return json.loads(_canonical(value))


def _list(value: object, field: str) -> List[object]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    return list(value)


def _validated_broadcast(broadcast: Mapping[str, object]) -> Dict[str, object]:
    """Validate the kernel's own selection and delivery bindings.

    Receipts must not make a corrupted or hand-assembled broadcast look
    authoritative merely because it contains two well-formed digest strings.
    This recomputes the same independent selection and delivery materials used
    by ``eve_consciousness`` before any consumer is invoked.
    """
    if broadcast.get("schema_version") != "eve.global_broadcast.v1":
        raise ValueError("unsupported or missing global broadcast schema")
    bottleneck_active = broadcast.get("bottleneck_active")
    if not isinstance(bottleneck_active, bool):
        raise ValueError("broadcast bottleneck_active must be boolean")
    candidate_count = _cycle_index(broadcast.get("candidate_count"))
    selected_candidate_ids = [
        _identifier(value, "selected candidate id")
        for value in _list(
            broadcast.get("selected_candidate_ids"),
            "selected_candidate_ids",
        )
    ]
    if not selected_candidate_ids:
        raise ValueError("broadcast must bind at least one selected candidate")
    if len(selected_candidate_ids) != len(set(selected_candidate_ids)):
        raise ValueError("selected candidate ids contain duplicates")
    if len(selected_candidate_ids) > candidate_count:
        raise ValueError("selected candidates exceed candidate_count")
    content = broadcast.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("broadcast content must be a non-empty string")
    access_scope = [
        str(value or "").strip().lower()
        for value in _list(broadcast.get("access_scope"), "access_scope")
    ]
    if any(not value for value in access_scope):
        raise ValueError("broadcast access scope contains an empty consumer")
    if len(access_scope) != len(set(access_scope)):
        raise ValueError("broadcast access scope contains duplicates")
    if any(value not in CONSUMER_IDS for value in access_scope):
        raise ValueError("broadcast access scope contains an unknown consumer")
    source_kinds = [
        _identifier(value, "source kind")
        for value in _list(broadcast.get("source_kinds"), "source_kinds")
    ][:12]
    selection_material = {
        "schema_version": "eve.global_broadcast.v1",
        "bottleneck_active": bottleneck_active,
        "candidate_count": candidate_count,
        "selected_candidate_ids": selected_candidate_ids,
        "content": content,
    }
    selection_digest = _sha256(
        broadcast.get("selection_digest"), "selection_digest"
    )
    if selection_digest != _digest(selection_material):
        raise ValueError("broadcast selection digest does not match selected content")
    delivery_digest = _sha256(broadcast.get("delivery_digest"), "delivery_digest")
    if delivery_digest != _digest(
        {"selection_digest": selection_digest, "access_scope": access_scope}
    ):
        raise ValueError("broadcast delivery digest does not match access scope")
    return {
        "access_scope": access_scope,
        "bottleneck_active": bottleneck_active,
        "candidate_count": candidate_count,
        "content": content,
        "delivery_digest": delivery_digest,
        "selected_candidate_ids": selected_candidate_ids,
        "selection_digest": selection_digest,
        "source_kinds": source_kinds,
    }


def broadcast_envelope(
    state: Mapping[str, object], consumer_id: object
) -> Dict[str, object]:
    """Return the exact selected-content envelope for an admitted consumer."""
    consumer = _consumer(consumer_id)
    if not isinstance(state, Mapping):
        raise ValueError("conscious state must be a mapping")
    cycle_id = _identifier(state.get("cycle_id"), "cycle_id")
    cycle_index = _cycle_index(state.get("cycle_index"))
    updated_at = _timestamp(state.get("updated_at"))
    raw_broadcast = state.get("broadcast")
    if not isinstance(raw_broadcast, Mapping):
        raise ValueError("conscious state must contain a broadcast mapping")
    broadcast = _validated_broadcast(raw_broadcast)
    access_scope = broadcast["access_scope"]
    if consumer not in access_scope:
        raise PermissionError(f"broadcast does not grant access to {consumer}")
    selection_digest = str(broadcast["selection_digest"])
    delivery_digest = str(broadcast["delivery_digest"])
    content = str(broadcast["content"])
    source_kinds = list(broadcast["source_kinds"])
    selected_candidate_ids = list(broadcast["selected_candidate_ids"])
    winner_id = _identifier(
        raw_broadcast.get("winner_id") or selected_candidate_ids[0],
        "winner_id",
    )
    material = {
        "schema_version": ENVELOPE_SCHEMA,
        "cycle_id": cycle_id,
        "cycle_index": cycle_index,
        "state_updated_at": updated_at,
        "consumer_id": consumer,
        "selection_digest": selection_digest,
        "delivery_digest": delivery_digest,
        "content": content,
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "source_kinds": source_kinds,
        "winner_id": winner_id,
    }
    material["envelope_sha256"] = _digest(material)
    return material


def _receipt_material(
    *,
    envelope: Mapping[str, object],
    consumer_id: str,
    purpose: str,
    consumed_at: str,
    output_sha256: str,
) -> Dict[str, object]:
    return {
        "schema_version": RECEIPT_SCHEMA,
        "receipt_id": (
            f"broadcast:{envelope['cycle_id']}:{consumer_id}:"
            f"{str(envelope['selection_digest'])[:12]}"
        ),
        "consumed_at": consumed_at,
        "consumer_id": consumer_id,
        "purpose": purpose,
        "cycle_id": envelope["cycle_id"],
        "cycle_index": envelope["cycle_index"],
        "selection_digest": envelope["selection_digest"],
        "delivery_digest": envelope["delivery_digest"],
        "content_sha256": envelope["content_sha256"],
        "envelope_sha256": envelope["envelope_sha256"],
        "consumer_output_sha256": output_sha256,
    }


def consume_broadcast(
    state: Mapping[str, object],
    consumer_id: object,
    consumer: Callable[[Mapping[str, object]], object],
    *,
    purpose: object,
    consumed_at: Optional[object] = None,
) -> Tuple[object, Dict[str, object]]:
    """Invoke one consumer with a detached envelope and return an exact receipt.

    No receipt is produced when access validation or the consumer callable
    fails. The receipt stores only hashes and typed lineage, never content or
    consumer output.
    """
    if not callable(consumer):
        raise ValueError("consumer must be callable")
    consumer_name = _consumer(consumer_id)
    purpose_name = _identifier(purpose, "purpose")
    envelope = broadcast_envelope(state, consumer_name)
    timestamp = _timestamp(consumed_at or _utc_now())
    if datetime.fromisoformat(timestamp) < datetime.fromisoformat(
        str(envelope["state_updated_at"])
    ):
        raise ValueError("consumption cannot predate the conscious state")
    delivered = _json_clone(envelope)
    result = consumer(delivered)
    output_sha256 = _digest(result)
    material = _receipt_material(
        envelope=envelope,
        consumer_id=consumer_name,
        purpose=purpose_name,
        consumed_at=timestamp,
        output_sha256=output_sha256,
    )
    receipt = dict(material)
    receipt["receipt_sha256"] = _digest(material)
    return result, receipt


def verify_receipt(
    receipt: Mapping[str, object],
    state: Mapping[str, object],
    *,
    consumer_id: Optional[object] = None,
    expected_output: object = None,
    verify_output: bool = False,
) -> Dict[str, object]:
    """Validate one receipt against the current exact broadcast state."""
    if not isinstance(receipt, Mapping) or set(receipt) != _RECEIPT_FIELDS:
        raise ValueError("receipt must contain exactly the consumption fields")
    supplied = dict(receipt)
    receipt_sha256 = _sha256(supplied.pop("receipt_sha256"), "receipt_sha256")
    if receipt_sha256 != _digest(supplied):
        raise ValueError("receipt digest mismatch")
    consumer_name = _consumer(supplied.get("consumer_id"))
    if consumer_id is not None and consumer_name != _consumer(consumer_id):
        raise ValueError("receipt consumer does not match expected consumer")
    purpose = _identifier(supplied.get("purpose"), "purpose")
    timestamp = _timestamp(supplied.get("consumed_at"))
    envelope = broadcast_envelope(state, consumer_name)
    expected = _receipt_material(
        envelope=envelope,
        consumer_id=consumer_name,
        purpose=purpose,
        consumed_at=timestamp,
        output_sha256=_sha256(
            supplied.get("consumer_output_sha256"),
            "consumer_output_sha256",
        ),
    )
    if supplied != expected:
        raise ValueError("receipt does not match the exact current broadcast envelope")
    if datetime.fromisoformat(timestamp) < datetime.fromisoformat(
        str(envelope["state_updated_at"])
    ):
        raise ValueError("receipt predates the conscious state")
    if verify_output and supplied["consumer_output_sha256"] != _digest(expected_output):
        raise ValueError("consumer output does not match the receipt")
    return {
        "valid": True,
        "consumer_id": consumer_name,
        "purpose": purpose,
        "cycle_id": envelope["cycle_id"],
        "selection_digest": envelope["selection_digest"],
        "delivery_digest": envelope["delivery_digest"],
        "receipt_sha256": receipt_sha256,
        "content_exposed_in_receipt": False,
        "semantic_comprehension_established": False,
        "subjective_access_inferred": False,
        "consciousness_proven": False,
    }


def receipt_coverage(
    receipts: Iterable[Mapping[str, object]],
    state: Mapping[str, object],
    *,
    required_consumers: Sequence[object] = CONSUMER_IDS,
) -> Dict[str, object]:
    """Return exact-cycle coverage without accepting invalid or replayed rows."""
    required = [_consumer(value) for value in required_consumers]
    if len(required) != len(set(required)):
        raise ValueError("required consumers must be unique")
    verified: List[str] = []
    duplicates: List[str] = []
    invalid: List[Dict[str, object]] = []
    seen = set()
    for index, receipt in enumerate(receipts):
        try:
            result = verify_receipt(receipt, state)
        except (ValueError, PermissionError) as exc:
            invalid.append({"index": index, "reason": str(exc)[:240]})
            continue
        consumer = str(result["consumer_id"])
        if consumer in seen:
            duplicates.append(consumer)
            continue
        seen.add(consumer)
        if consumer in required:
            verified.append(consumer)
    verified = [consumer for consumer in required if consumer in verified]
    missing = [consumer for consumer in required if consumer not in verified]
    return {
        "schema_version": COVERAGE_SCHEMA,
        "cycle_id": _identifier(state.get("cycle_id"), "cycle_id"),
        "required_consumers": required,
        "verified_consumers": verified,
        "missing_consumers": missing,
        "duplicate_consumers": sorted(set(duplicates)),
        "invalid_receipt_count": len(invalid),
        "invalid_receipts": invalid,
        "complete": not missing and not duplicates and not invalid,
        "availability_is_not_consumption": True,
        "semantic_comprehension_established": False,
        "subjective_access_inferred": False,
        "consciousness_proven": False,
    }
