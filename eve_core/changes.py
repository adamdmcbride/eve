"""Pure self-change evidence rules; no models, files or runtime globals."""
from dataclasses import dataclass
import json
from typing import Mapping, Optional, Tuple


def compact_text(value: object, fallback: str = "", limit: int = 320) -> str:
    text = " ".join(str(value or "").split())
    return (text or fallback)[:limit]


def bounded_integer(value: object, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(high, max(low, parsed))


@dataclass(frozen=True)
class ChangeEvidence:
    paths: Tuple[str, ...] = ()
    changes: Tuple[str, ...] = ()
    tests_ok: Optional[bool] = None
    attempted: int = 0
    deferred: Tuple[str, ...] = ()
    errors: Tuple[str, ...] = ()

    @property
    def deferred_only(self) -> bool:
        return bool(self.deferred) and self.attempted == len(self.deferred) and not self.errors and not self.paths and not self.changes


def collect_change_evidence(agent: object, authority_tools: Tuple[str, ...]) -> ChangeEvidence:
    """Validate transport envelopes before deciding whether any effects occurred.

    A declaration via record_change retains its existing meaning: reported
    operational evidence, not independent verification of an arbitrary command.
    Failed tests are sticky. String 'true' is not a successful boolean receipt.
    """
    if not isinstance(agent, Mapping) or not isinstance(agent.get("tool_calls", []), list):
        return ChangeEvidence(errors=("malformed coder result",))
    paths, changes, deferred, errors = [], [], [], []
    tests_ok, attempted = None, 0
    for call in agent.get("tool_calls", []):
        if not isinstance(call, Mapping) or not isinstance(call.get("result"), Mapping):
            errors.append("malformed tool receipt")
            continue
        name, result = str(call.get("tool") or ""), call["result"]
        args = call.get("args") or {}
        if not isinstance(args, Mapping):
            errors.append("malformed tool arguments")
            continue
        action = name == "apply_patch" or name in authority_tools
        holder = result.get("deferred_claim")
        if (action and name != "record_change") or holder:
            attempted += 1
            if holder:
                deferred.append(str(holder))
        if holder:
            continue
        success = result.get("ok") is True
        if action and not success:
            errors.append(compact_text(result.get("error"), name + " did not succeed", 200))
        if name == "apply_patch" and success:
            touched = result.get("paths")
            if not isinstance(touched, list) or not touched or not all(isinstance(path, str) and path for path in touched):
                errors.append("successful patch is missing affected paths")
            else:
                paths.extend(touched)
        if name in authority_tools and success and name != "record_change" and not result.get("no_op"):
            try:
                encoded = json.dumps(dict(args), ensure_ascii=True)[:160]
            except (TypeError, ValueError):
                errors.append("non-JSON tool arguments")
            else:
                changes.append(name + ":" + encoded)
        if name == "record_change" and success:
            what, checked = compact_text(args.get("what"), limit=120), compact_text(args.get("verification"), limit=100)
            if not what or not checked:
                errors.append("change declaration is missing verification")
            else:
                changes.append("by command: " + what + " (verified: " + checked + ")")
        if name == "run_tests":
            tests_ok = success if tests_ok is not False else False
    return ChangeEvidence(tuple(dict.fromkeys(paths)), tuple(changes), tests_ok, attempted, tuple(deferred), tuple(errors))
