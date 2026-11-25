"""Request-scoped reply contracts and pure critic receipt validation."""
from dataclasses import dataclass
from typing import Dict, Mapping, Tuple


@dataclass(frozen=True)
class ReplyScope:
    body: str
    posture: str
    closed_world: bool
    current_inner_state: bool
    epistemic_boundary: bool
    taxonomy_classification: bool


@dataclass(frozen=True)
class ReplyAssessment:
    issues: Tuple[str, ...]
    blocking: Tuple[str, ...]


def unavailable_critic(reason: str) -> Dict[str, object]:
    return {"evaluated": True, "ok": False, "model": "", "unsupported_claims": [], "error": reason}


def critic_receipt(raw: object) -> Dict[str, object]:
    """Malformed verdicts are unavailable evidence, not semantic rejections."""
    if not isinstance(raw, Mapping):
        return unavailable_critic("invalid critic receipt")
    result = dict(raw)
    if not isinstance(result.get("evaluated"), bool) or not isinstance(result.get("ok"), bool):
        return unavailable_critic("invalid critic boolean fields")
    if not isinstance(result.get("unsupported_claims", []), list) or not isinstance(result.get("error", ""), str):
        return unavailable_critic("invalid critic evidence fields")
    result.setdefault("model", "")
    result.setdefault("unsupported_claims", [])
    return result


def correction_receipt(raw: object) -> Dict[str, object]:
    if not isinstance(raw, Mapping) or not isinstance(raw.get("response", ""), str):
        return {"attempted": True, "accepted": False, "response": "", "model": "", "error": "invalid correction receipt"}
    result = dict(raw)
    result.setdefault("attempted", True)
    # Acceptance/trace attribution belong to the application, never the model.
    result["accepted"] = False
    for field in ("accepted_with_critic_unavailable", "attempt_index", "attempt_count", "attempts", "critic"):
        result.pop(field, None)
    result.setdefault("response", "")
    return result


def critic_is_unavailable(result: Mapping[str, object]) -> bool:
    return result.get("evaluated") is True and bool(result.get("error"))


def critic_rejected(result: Mapping[str, object]) -> bool:
    return result.get("evaluated") is True and result.get("ok") is False and not critic_is_unavailable(result)
