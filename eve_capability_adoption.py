#!/usr/bin/env python3
"""Capability-first research and adoption planning for Eve.

This module joins evidence that already exists in Eve without becoming a
second scheduler or an authority surface.  It answers one question before any
code is requested: does Eve already have, configure, admit, update, or merely
need to research the requested capability?

The live runtime owns persistence, recurrence, canary execution, OpenClaw
actions, Hermes proposal intake, and Codex handoffs.  Functions here are kept
pure where practical so the capability-first rule can be tested without
touching Eve's runtime or the network.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib import error, parse, request


RESOLUTION_SCHEMA_ID = "eve_capability_first_resolution.v1"
CYCLE_SCHEMA_ID = "eve_capability_adoption_cycle.v1"
STATE_SCHEMA_ID = "eve_capability_adoption_state.v1"
RESEARCH_SCHEMA_ID = "eve_online_capability_research.v1"

CLASSIFICATIONS = {
    "use_existing",
    "use_existing_with_permission",
    "configure_or_admit_existing",
    "canary_existing_update",
    "research_existing_upstream",
    "build_required",
}

STOP_WORDS = {
    "a",
    "about",
    "all",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "before",
    "build",
    "can",
    "capability",
    "do",
    "does",
    "eve",
    "feature",
    "for",
    "from",
    "get",
    "have",
    "help",
    "her",
    "herself",
    "how",
    "i",
    "if",
    "in",
    "is",
    "it",
    "make",
    "need",
    "new",
    "of",
    "on",
    "or",
    "our",
    "please",
    "should",
    "something",
    "that",
    "the",
    "this",
    "to",
    "try",
    "use",
    "we",
    "what",
    "when",
    "with",
    "you",
}

GITHUB_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SEMVER_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9_.-]+)?$")
GENERIC_ID_TOKENS = {
    "adopt",
    "agent",
    "canary",
    "component",
    "evaluate",
    "existing",
    "framework",
    "integration",
    "model",
    "python",
    "release",
    "runtime",
    "source",
    "stage",
    "system",
    "tool",
    "update",
    "upgrade",
}

JsonFetcher = Callable[[str, int], object]
TextFetcher = Callable[[str, int], str]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def compact_text(value: object, limit: int = 320) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def stable_json_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_token(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def meaningful_tokens(value: object) -> List[str]:
    tokens = []
    aliases = {
        "browse": "web",
        "browsing": "web",
        "continuously": "continuous",
        "discover": "search",
        "discovering": "search",
        "discovery": "search",
        "internet": "web",
        "imessage": "channel",
        "online": "web",
        "recurrent": "continuous",
        "recurring": "continuous",
        "research": "search",
        "researching": "search",
        "searched": "search",
        "searching": "search",
    }
    for token in normalize_token(value).split():
        if token in STOP_WORDS or len(token) < 3:
            continue
        # A tiny singularization step makes "tools" and "tool" comparable
        # without importing a language model or stemming dependency.
        if token.endswith("s") and len(token) > 4 and not token.endswith(("ss", "us", "is", "ous", "ics")):
            token = token[:-1]
        token = aliases.get(token, token)
        if token in STOP_WORDS:
            continue
        tokens.append(token)
    return sorted(set(tokens))


def _iter_text(value: object, *, depth: int = 0) -> Iterable[str]:
    if depth > 3:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _iter_text(item, depth=depth + 1)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_text(item, depth=depth + 1)
    elif value is not None and isinstance(value, (int, float, bool)):
        yield str(value)


def record_search_text(record: Dict[str, object]) -> str:
    preferred: List[object] = [
        record.get("id"),
        record.get("name"),
        record.get("category"),
        record.get("component_id"),
        record.get("component_name"),
        record.get("repository"),
        record.get("capability_domains"),
        record.get("feature_summary"),
        record.get("feature_bullets"),
        record.get("candidate_role"),
        record.get("missing_dependency"),
        record.get("next_acquisition_step"),
        record.get("evidence"),
    ]
    return " ".join(text for item in preferred for text in _iter_text(item))


def match_score(objective: object, record: Dict[str, object]) -> Dict[str, object]:
    objective_text = normalize_token(objective)
    record_text = normalize_token(record_search_text(record))
    objective_tokens = meaningful_tokens(objective_text)
    record_tokens = set(meaningful_tokens(record_text))
    overlap = sorted(set(objective_tokens) & record_tokens)
    exact_phrase = bool(objective_text and len(objective_text) >= 5 and objective_text in record_text)
    id_or_name = normalize_token(f"{record.get('id') or ''} {record.get('name') or ''}")
    id_name_phrase = bool(objective_text and len(objective_text) >= 5 and objective_text in id_or_name)
    id_name_tokens = set(meaningful_tokens(id_or_name))
    specific_id_overlap = sorted(
        token
        for token in objective_tokens
        if len(token) >= 5 and token not in GENERIC_ID_TOKENS and token in id_name_tokens
    )
    coverage = len(overlap) / max(1, len(objective_tokens))
    precision = len(overlap) / max(1, min(len(record_tokens), max(4, len(objective_tokens) * 3)))
    score = coverage * 0.72 + min(0.28, precision * 0.28)
    if exact_phrase:
        score += 0.3
    if id_name_phrase:
        score += 0.25
    if specific_id_overlap:
        score += 0.22
    # One generic overlap is not enough to conclude that coding is unnecessary.
    credible = bool(
        id_name_phrase
        or exact_phrase
        or bool(specific_id_overlap)
        or len(overlap) >= 2
        or (len(objective_tokens) == 1 and len(overlap) == 1 and len(objective_tokens[0]) >= 5)
    )
    return {
        "score": round(min(1.0, score), 4),
        "credible": credible and score >= 0.34,
        "overlap": overlap,
        "objective_tokens": objective_tokens,
        "exact_phrase": exact_phrase,
        "id_name_phrase": id_name_phrase,
        "specific_id_overlap": specific_id_overlap,
    }


def _rank_records(objective: object, records: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    ranked: List[Dict[str, object]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        match = match_score(objective, record)
        ranked.append({"record": record, "match": match})
    ranked.sort(
        key=lambda item: (
            bool(item["match"].get("credible")),
            float(item["match"].get("score") or 0.0),
            bool(item["record"].get("verified")),
            bool(item["record"].get("callable")),
        ),
        reverse=True,
    )
    return ranked


def route_missing_capability(objective: object) -> Dict[str, object]:
    text = normalize_token(objective)
    tokens = set(meaningful_tokens(text))

    def has(*values: str) -> bool:
        return any(value in text or value in tokens for value in values)

    if has("memory", "learn", "learning", "skill", "habit", "reflection", "user model", "preference"):
        primary = "hermes"
        supporting = ["codex", "openclaw"]
        reason = "The missing function is primarily a learning, skill, habit, or memory proposal problem."
    elif has("tool", "action", "browser", "channel", "device", "home", "mcp", "plugin", "openclaw", "webhook", "voice"):
        primary = "openclaw"
        supporting = ["codex", "hermes"]
        reason = "The missing function is primarily an embodied action, tool, channel, or integration problem."
    elif has("code", "runtime", "ui", "interface", "model", "train", "eval", "adapter", "router", "daemon", "api"):
        primary = "codex"
        supporting = ["openclaw", "hermes"]
        reason = "The missing function requires implementation, tests, or runtime integration."
    else:
        primary = "codex"
        supporting = ["hermes", "openclaw"]
        reason = "No admitted path was found; Codex should implement only after Eve's capability-first preflight is attached."
    return {
        "owner": "eve",
        "primary_organ": primary,
        "supporting_organs": supporting,
        "reason": reason,
        "authority": "proposal_or_handoff_only",
    }


def _component_by_id(components: Sequence[Dict[str, object]], component_id: object) -> Dict[str, object]:
    target = str(component_id or "")
    return next(
        (item for item in components if isinstance(item, dict) and str(item.get("id") or "") == target),
        {},
    )


def _feature_review_from_target(
    target: Optional[Dict[str, object]],
    feature_reviews: Sequence[Dict[str, object]],
) -> Dict[str, object]:
    if not isinstance(target, dict):
        return {}
    review_id = str(target.get("feature_review_id") or target.get("id") or "")
    component_id = str(target.get("component_id") or "")
    version = str(target.get("target_version") or "")
    for item in feature_reviews:
        if not isinstance(item, dict):
            continue
        if review_id and str(item.get("id") or "") == review_id:
            return item
        if component_id and str(item.get("component_id") or "") == component_id:
            if not version or str(item.get("target_version") or "") == version:
                return item
    return {}


def resolve_capability_first(
    objective: object,
    capability_matrix: Optional[Dict[str, object]] = None,
    intelligence: Optional[Dict[str, object]] = None,
    *,
    components: Sequence[Dict[str, object]] = (),
    radar: Optional[Dict[str, object]] = None,
    target: Optional[Dict[str, object]] = None,
    resolved_at: Optional[str] = None,
) -> Dict[str, object]:
    """Resolve an objective against Eve's live capability evidence.

    The resolver is intentionally conservative.  A weak lexical resemblance
    never suppresses a real build, and a release note never becomes proof that
    a feature is installed or callable.
    """

    objective_text = compact_text(objective, 1200)
    capability_matrix = capability_matrix if isinstance(capability_matrix, dict) else {}
    intelligence = intelligence if isinstance(intelligence, dict) else {}
    radar = radar if isinstance(radar, dict) else {}
    matrix_records = [
        item
        for item in capability_matrix.get("capabilities") or []
        if isinstance(item, dict) and str(item.get("category") or "") != "capability_gap"
    ]
    feature_reviews = [
        item
        for item in intelligence.get("feature_reviews") or []
        if isinstance(item, dict)
        and str(item.get("state") or "") != "historical"
        and (item.get("visible_in_current_feed") is not False)
    ]
    components = [item for item in components if isinstance(item, dict)]

    ranked_capabilities = _rank_records(objective_text, matrix_records)
    capability_hit = next((item for item in ranked_capabilities if item["match"].get("credible")), {})
    matched_capability = capability_hit.get("record") if isinstance(capability_hit.get("record"), dict) else {}
    capability_match = capability_hit.get("match") if isinstance(capability_hit.get("match"), dict) else {}

    exact_review = _feature_review_from_target(target, feature_reviews)
    ranked_reviews = _rank_records(objective_text, feature_reviews)
    review_hit = next((item for item in ranked_reviews if item["match"].get("credible")), {})
    matched_review = exact_review or (
        review_hit.get("record") if isinstance(review_hit.get("record"), dict) else {}
    )
    review_match = (
        {"score": 1.0, "credible": True, "overlap": ["target_id"], "exact_target": True}
        if exact_review
        else review_hit.get("match") if isinstance(review_hit.get("match"), dict) else {}
    )
    matched_component = _component_by_id(components, matched_review.get("component_id"))

    classification = "build_required"
    reason = "No credible installed, configurable, admitted, or upstream feature path matched the objective."
    recommended_action = "Create a bounded build handoff with this preflight attached, then test and ingest only verified artifacts."
    organ_route = route_missing_capability(objective_text)
    existing_path_found = False
    coding_allowed = True

    # An exact structured release target outranks a loose capability-name hit;
    # a candidate package may expose related words while still requiring its
    # own isolated version canary.
    review_state = str(matched_review.get("state") or "")
    exact_release_target = bool(exact_review)
    objective_normalized = normalize_token(objective_text)
    target_version_normalized = normalize_token(matched_review.get("target_version"))
    candidate_named_target = bool(
        review_state in {"candidate", "lab_candidate"}
        and review_match.get("credible")
        and review_match.get("specific_id_overlap")
        and (
            (target_version_normalized and target_version_normalized in objective_normalized)
            or any(cue in objective_normalized.split() for cue in ("adopt", "canary", "evaluate", "stage", "update", "upgrade"))
        )
    )
    if (exact_release_target or candidate_named_target) and review_state in {"candidate", "lab_candidate"}:
        classification = "canary_existing_update"
        reason = str(matched_review.get("classification_reason") or "A newer release exists for an installed or staged Eve component.")
        recommended_action = str(matched_review.get("required_gate") or "Stage the candidate and run its component canary before live adoption.")
        organ_route = {
            "owner": "eve",
            "primary_organ": "eve_runtime",
            "supporting_organs": ["codex", "openclaw", "hermes"],
            "reason": "Eve's local runtime executes the isolated candidate canary; Codex is used only if integration or repair code is needed, and OpenClaw only for an admitted body/action surface.",
            "authority": "canary_only",
        }
        existing_path_found = True
        coding_allowed = False
    elif exact_release_target and review_state == "research_only":
        classification = "research_existing_upstream"
        reason = str(matched_review.get("classification_reason") or "An upstream feature source exists but is not installed evidence.")
        recommended_action = "Inspect the official repository, README/docs, and recent commits; then re-resolve before writing code."
        organ_route = {
            "owner": "eve",
            "primary_organ": "eve_runtime",
            "supporting_organs": ["hermes", "openclaw", "codex"],
            "reason": "Eve's local runtime reads and attributes official sources; Hermes may propose what Eve should learn, OpenClaw may inspect admitted local surfaces, and Codex is held until a real adapter gap is proven.",
            "authority": "research_only",
        }
        existing_path_found = True
        coding_allowed = False
    elif matched_capability:
        existing_path_found = True
        coding_allowed = False
        if bool(matched_capability.get("available")) and bool(matched_capability.get("callable")):
            if bool(matched_capability.get("needs_permission")):
                classification = "use_existing_with_permission"
                reason = "Eve already has a callable path, but its current capability contract requires the recorded permission boundary."
                recommended_action = str(matched_capability.get("next_acquisition_step") or "Use the existing typed path after permission evidence is present.")
            else:
                classification = "use_existing"
                reason = "Eve already has a callable capability matching this objective; new code would duplicate an existing path."
                recommended_action = str(matched_capability.get("next_acquisition_step") or "Use the existing typed path and verify its result.")
            organ_route = {
                "owner": "eve",
                "primary_organ": "openclaw" if str(matched_capability.get("category")) in {"openclaw_native", "operational_action", "operational_router", "tool"} else "eve",
                "supporting_organs": [],
                "reason": "Use the admitted capability rather than starting a build.",
                "authority": "existing_contract",
            }
        else:
            classification = "configure_or_admit_existing"
            reason = "Eve can see an existing capability surface, but it is not yet mapped to a callable, verified contract."
            recommended_action = str(matched_capability.get("next_acquisition_step") or "Configure or admit the existing surface and run a focused canary.")
            category = str(matched_capability.get("category") or "")
            capability_id = str(matched_capability.get("id") or "")
            primary_organ = (
                "hermes"
                if "hermes" in capability_id or category in {"learning", "learning_organ"}
                else "openclaw"
                if "openclaw" in capability_id
                or category in {"openclaw_native", "operational_action", "operational_router", "tool"}
                else "eve_runtime"
            )
            organ_route = {
                "owner": "eve",
                "primary_organ": primary_organ,
                "supporting_organs": [
                    item for item in ["openclaw", "hermes", "codex"] if item != primary_organ
                ],
                "reason": "Finish the visible surface's owning configuration/admission contract; Codex is only for a missing adapter proven by that attempt.",
                "authority": "admission_required",
            }
    elif matched_review and review_state in {"candidate", "lab_candidate"}:
        classification = "canary_existing_update"
        reason = str(matched_review.get("classification_reason") or "A newer release exists for an installed or staged Eve component.")
        recommended_action = str(matched_review.get("required_gate") or "Stage and canary the existing candidate before coding.")
        organ_route = {
            "owner": "eve",
            "primary_organ": "eve_runtime",
            "supporting_organs": ["codex", "openclaw", "hermes"],
            "reason": "Eve's local runtime runs the existing component canary before deciding an adapter, action admission, or repair is needed.",
            "authority": "canary_only",
        }
        existing_path_found = True
        coding_allowed = False
    elif matched_review and review_state in {"research_only", "in_use"}:
        classification = "research_existing_upstream" if review_state == "research_only" else "configure_or_admit_existing"
        reason = str(matched_review.get("classification_reason") or "A relevant upstream source already exists.")
        recommended_action = "Research the official source and compare it with Eve's admitted path before coding."
        organ_route = {
            "owner": "eve",
            "primary_organ": "eve_runtime",
            "supporting_organs": ["hermes", "openclaw", "codex"],
            "reason": "Eve's local runtime learns and inspects official and installed evidence first; build only if the owned contract cannot satisfy the objective.",
            "authority": "research_only",
        }
        existing_path_found = True
        coding_allowed = False

    confidence = max(
        float(capability_match.get("score") or 0.0),
        float(review_match.get("score") or 0.0),
        0.7 if classification == "build_required" else 0.0,
    )
    resolution = {
        "schema_id": RESOLUTION_SCHEMA_ID,
        "id": str(uuid.uuid4()),
        "resolved_at": str(resolved_at or utc_now()),
        "objective": objective_text,
        "classification": classification,
        "confidence": round(min(1.0, confidence), 4),
        "existing_path_found": existing_path_found,
        "coding_allowed": coding_allowed,
        "reason": compact_text(reason, 600),
        "recommended_action": compact_text(recommended_action, 700),
        "organ_route": organ_route,
        "matched_capability": matched_capability,
        "capability_match": capability_match,
        "matched_feature_review": matched_review,
        "feature_review_match": review_match,
        "matched_component": matched_component,
        "top_alternatives": [
            {
                "id": item["record"].get("id"),
                "name": item["record"].get("name") or item["record"].get("component_name"),
                "score": item["match"].get("score"),
                "credible": item["match"].get("credible"),
            }
            for item in (ranked_capabilities[:3] + ranked_reviews[:3])
        ],
        "evidence": {
            "capability_matrix_updated_at": capability_matrix.get("updated_at"),
            "capability_count": len(matrix_records),
            "intelligence_generated_at": intelligence.get("generated_at"),
            "feature_review_count": len(feature_reviews),
            "radar_updated_at": radar.get("updated_at"),
            "target_id": target.get("id") if isinstance(target, dict) else None,
        },
    }
    resolution["fingerprint"] = stable_json_hash(
        {
            "objective": resolution["objective"],
            "classification": classification,
            "matched_capability": matched_capability.get("id"),
            "matched_feature_review": matched_review.get("id"),
            "recommended_action": resolution["recommended_action"],
        }
    )
    return resolution


def _parse_timestamp(value: object) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


def select_next_target(
    capability_matrix: Optional[Dict[str, object]],
    intelligence: Optional[Dict[str, object]],
    prior_cycles: Sequence[Dict[str, object]] = (),
    *,
    objective: object = "",
) -> Dict[str, object]:
    """Rotate real gaps and current release heads instead of repeating probes."""

    objective_text = compact_text(objective, 1200)
    if objective_text:
        return {
            "id": f"objective:{stable_json_hash(objective_text)[:16]}",
            "kind": "explicit_objective",
            "objective": objective_text,
            "priority": 0,
        }
    capability_matrix = capability_matrix if isinstance(capability_matrix, dict) else {}
    intelligence = intelligence if isinstance(intelligence, dict) else {}
    last_attempt: Dict[str, datetime] = {}
    for cycle in prior_cycles:
        if not isinstance(cycle, dict):
            continue
        target = cycle.get("target") if isinstance(cycle.get("target"), dict) else {}
        target_id = str(target.get("id") or cycle.get("target_id") or "")
        if target_id:
            last_attempt[target_id] = max(
                last_attempt.get(target_id, datetime(1970, 1, 1, tzinfo=timezone.utc)),
                _parse_timestamp(cycle.get("completed_at") or cycle.get("started_at")),
            )

    targets: List[Dict[str, object]] = []
    for item in capability_matrix.get("capabilities") or []:
        if not isinstance(item, dict) or str(item.get("category") or "") != "capability_gap":
            continue
        target_id = str(item.get("id") or "")
        targets.append(
            {
                "id": target_id,
                "kind": "capability_gap",
                "objective": compact_text(item.get("name") or item.get("missing_dependency"), 600),
                "capability_id": target_id,
                "priority": 0,
                "first_seen_at": item.get("last_tried") or "",
                "evidence": item.get("evidence") or {},
            }
        )
    for item in intelligence.get("feature_reviews") or []:
        if not isinstance(item, dict) or not item.get("visible_in_current_feed"):
            continue
        state = str(item.get("state") or "")
        if state not in {"candidate", "lab_candidate", "research_only"}:
            continue
        # Prereleases are worth tracking but should not consume every research
        # cycle ahead of stable installed-component candidates.
        kind = "release_candidate" if state in {"candidate", "lab_candidate"} else "upstream_research"
        priority = 1 if kind == "release_candidate" else 2 + int(bool(item.get("prerelease")))
        targets.append(
            {
                "id": str(item.get("id") or ""),
                "kind": kind,
                "objective": compact_text(
                    f"{item.get('component_name') or item.get('repository')} {item.get('feature_summary') or item.get('target_version')}",
                    800,
                ),
                "feature_review_id": item.get("id"),
                "component_id": item.get("component_id"),
                "repository": item.get("repository"),
                "target_version": item.get("target_version"),
                "review_state": state,
                "priority": priority,
                "first_seen_at": item.get("first_seen_at") or item.get("published_at") or "",
            }
        )
    if not targets:
        return {
            "id": "inventory:capability-first-refresh",
            "kind": "inventory_refresh",
            "objective": "Refresh Eve's capability inventory and official upstream feature sources.",
            "priority": 3,
        }
    # Exhaust new evidence before repeating familiar work.  Priority chooses
    # which *unattempted* target Eve sees first, but it must not let one durable
    # capability gap starve release canaries and upstream research forever.
    unattempted = [item for item in targets if str(item.get("id") or "") not in last_attempt]
    if unattempted:
        unattempted.sort(
            key=lambda item: (
                int(item.get("priority") or 0),
                _parse_timestamp(item.get("first_seen_at")),
                str(item.get("id") or ""),
            )
        )
        return unattempted[0]
    targets.sort(
        key=lambda item: (
            last_attempt.get(str(item.get("id") or ""), datetime(1970, 1, 1, tzinfo=timezone.utc)),
            int(item.get("priority") or 0),
            _parse_timestamp(item.get("first_seen_at")),
            str(item.get("id") or ""),
        )
    )
    return targets[0]


def default_fetch_json(url: str, timeout: int) -> object:
    req = request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Eve-Capability-Research/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with request.urlopen(req, timeout=max(1, int(timeout))) as response:
        return json.loads(response.read().decode("utf-8"))


def default_fetch_text(url: str, timeout: int) -> str:
    req = request.Request(url, headers={"User-Agent": "Eve-Capability-Research/1.0"})
    with request.urlopen(req, timeout=max(1, int(timeout))) as response:
        return response.read().decode("utf-8", errors="replace")


def markdown_headings(text: object, limit: int = 40) -> List[str]:
    headings: List[str] = []
    for line in str(text or "").splitlines():
        match = re.match(r"^\s{0,3}#{1,4}\s+(.+?)\s*$", line)
        if not match:
            continue
        heading = compact_text(re.sub(r"[`*_]+", "", match.group(1)), 180)
        if heading and heading not in headings:
            headings.append(heading)
        if len(headings) >= limit:
            break
    return headings


def _research_error(exc: BaseException) -> str:
    if isinstance(exc, error.HTTPError):
        return f"HTTP {exc.code}: {compact_text(exc.reason, 160)}"
    if isinstance(exc, error.URLError):
        return compact_text(exc.reason, 220)
    return compact_text(exc, 220)


def research_repository(
    repository: object,
    *,
    fetch_json: JsonFetcher = default_fetch_json,
    fetch_text: TextFetcher = default_fetch_text,
    timeout: int = 20,
    researched_at: Optional[str] = None,
) -> Dict[str, object]:
    """Read official GitHub metadata, README/docs, and recent commits."""

    repository_text = str(repository or "").strip().strip("/")
    record: Dict[str, object] = {
        "schema_id": RESEARCH_SCHEMA_ID,
        "id": str(uuid.uuid4()),
        "researched_at": str(researched_at or utc_now()),
        "kind": "official_repository_review",
        "repository": repository_text,
        "authority": "official_primary_source" if GITHUB_REPOSITORY_RE.fullmatch(repository_text) else "invalid",
        "status": "failed",
        "source_urls": [],
        "repository_metadata": {},
        "readme": {},
        "docs_entries": [],
        "recent_commits": [],
        "errors": [],
    }
    if not GITHUB_REPOSITORY_RE.fullmatch(repository_text):
        record["errors"] = ["Repository must be an owner/name GitHub slug."]
        record["fingerprint"] = stable_json_hash(record)
        return record
    api_root = f"https://api.github.com/repos/{repository_text}"
    metadata_url = api_root
    readme_url = f"{api_root}/readme"
    docs_url = f"{api_root}/contents/docs"
    commits_url = f"{api_root}/commits?per_page=8"
    record["source_urls"] = [metadata_url, readme_url, docs_url, commits_url]

    try:
        metadata = fetch_json(metadata_url, timeout)
        if isinstance(metadata, dict):
            record["repository_metadata"] = {
                "full_name": metadata.get("full_name"),
                "description": compact_text(metadata.get("description"), 500),
                "html_url": metadata.get("html_url"),
                "homepage": metadata.get("homepage"),
                "default_branch": metadata.get("default_branch"),
                "updated_at": metadata.get("updated_at"),
                "pushed_at": metadata.get("pushed_at"),
                "archived": bool(metadata.get("archived")),
                "disabled": bool(metadata.get("disabled")),
                "topics": [str(item) for item in (metadata.get("topics") or [])[:30]],
                "license": (metadata.get("license") or {}).get("spdx_id") if isinstance(metadata.get("license"), dict) else None,
            }
    except BaseException as exc:  # network adapters differ across Python versions
        record["errors"].append(f"metadata: {_research_error(exc)}")

    readme_text = ""
    try:
        readme_payload = fetch_json(readme_url, timeout)
        if isinstance(readme_payload, dict):
            encoded = str(readme_payload.get("content") or "").replace("\n", "")
            if encoded:
                readme_text = base64.b64decode(encoded).decode("utf-8", errors="replace")
            elif readme_payload.get("download_url"):
                readme_text = fetch_text(str(readme_payload.get("download_url")), timeout)
            record["readme"] = {
                "name": readme_payload.get("name"),
                "html_url": readme_payload.get("html_url"),
                "download_url": readme_payload.get("download_url"),
                "sha": readme_payload.get("sha"),
                "headings": markdown_headings(readme_text),
                "sha256": hashlib.sha256(readme_text.encode("utf-8")).hexdigest() if readme_text else "",
                "excerpt": compact_text(readme_text, 1000),
            }
    except BaseException as exc:
        record["errors"].append(f"readme: {_research_error(exc)}")

    try:
        docs_payload = fetch_json(docs_url, timeout)
        if isinstance(docs_payload, list):
            record["docs_entries"] = [
                {
                    "name": item.get("name"),
                    "type": item.get("type"),
                    "path": item.get("path"),
                    "html_url": item.get("html_url"),
                    "sha": item.get("sha"),
                }
                for item in docs_payload[:60]
                if isinstance(item, dict)
            ]
    except BaseException as exc:
        # Many real repositories do not use a top-level docs directory.  That
        # is evidence, not a reason to fail the entire repository review.
        record["errors"].append(f"docs: {_research_error(exc)}")

    try:
        commits_payload = fetch_json(commits_url, timeout)
        if isinstance(commits_payload, list):
            commits: List[Dict[str, object]] = []
            for item in commits_payload[:8]:
                if not isinstance(item, dict):
                    continue
                commit = item.get("commit") if isinstance(item.get("commit"), dict) else {}
                author = commit.get("author") if isinstance(commit.get("author"), dict) else {}
                commits.append(
                    {
                        "sha": str(item.get("sha") or "")[:12],
                        "message": compact_text(commit.get("message"), 360),
                        "authored_at": author.get("date"),
                        "html_url": item.get("html_url"),
                    }
                )
            record["recent_commits"] = commits
    except BaseException as exc:
        record["errors"].append(f"commits: {_research_error(exc)}")

    record["status"] = "complete" if record.get("repository_metadata") and record.get("readme") else "partial"
    record["summary"] = compact_text(
        f"Reviewed {repository_text}: {len(record.get('readme', {}).get('headings') or [])} README headings, "
        f"{len(record.get('docs_entries') or [])} docs entries, and {len(record.get('recent_commits') or [])} recent commits.",
        360,
    )
    record["fingerprint"] = stable_json_hash(
        {
            "repository": repository_text,
            "metadata": record.get("repository_metadata"),
            "readme_sha": (record.get("readme") or {}).get("sha"),
            "docs": record.get("docs_entries"),
            "commits": record.get("recent_commits"),
        }
    )
    return record


def discover_repositories(
    query: object,
    *,
    fetch_json: JsonFetcher = default_fetch_json,
    timeout: int = 20,
    researched_at: Optional[str] = None,
) -> Dict[str, object]:
    """Discover possible projects without treating search results as adopted."""

    query_text = compact_text(query, 240)
    url = "https://api.github.com/search/repositories?" + parse.urlencode(
        {"q": query_text, "sort": "updated", "order": "desc", "per_page": 10}
    )
    record: Dict[str, object] = {
        "schema_id": RESEARCH_SCHEMA_ID,
        "id": str(uuid.uuid4()),
        "researched_at": str(researched_at or utc_now()),
        "kind": "repository_discovery",
        "query": query_text,
        "source_urls": [url],
        "authority": "unverified_discovery_signal",
        "status": "failed",
        "results": [],
        "errors": [],
    }
    try:
        payload = fetch_json(url, timeout)
        items = payload.get("items") if isinstance(payload, dict) else []
        record["results"] = [
            {
                "repository": item.get("full_name"),
                "description": compact_text(item.get("description"), 420),
                "html_url": item.get("html_url"),
                "updated_at": item.get("updated_at"),
                "pushed_at": item.get("pushed_at"),
                "archived": bool(item.get("archived")),
                "topics": [str(topic) for topic in (item.get("topics") or [])[:20]],
                "license": (item.get("license") or {}).get("spdx_id") if isinstance(item.get("license"), dict) else None,
                "adoption_state": "research_only",
            }
            for item in (items or [])[:10]
            if isinstance(item, dict)
        ]
        record["status"] = "complete"
    except BaseException as exc:
        record["errors"].append(_research_error(exc))
    record["summary"] = f"Discovered {len(record.get('results') or [])} research-only repository signals for `{query_text}`."
    record["fingerprint"] = stable_json_hash(
        {"query": query_text, "results": record.get("results"), "errors": record.get("errors")}
    )
    return record


def normalize_python_package_version(value: object) -> str:
    text = str(value or "").strip()
    if text.lower().startswith("v") and SEMVER_RE.fullmatch(text[1:]):
        return text[1:]
    return text if SEMVER_RE.fullmatch(text) else ""


def python_candidate_plan(
    feature_review: Optional[Dict[str, object]],
    component: Optional[Dict[str, object]],
) -> Dict[str, object]:
    feature_review = feature_review if isinstance(feature_review, dict) else {}
    component = component if isinstance(component, dict) else {}
    package = str(component.get("package") or "").strip()
    version = normalize_python_package_version(feature_review.get("target_version"))
    kind = str(component.get("kind") or "")
    eligible = bool(kind == "python_package" and package and version)
    import_name = {
        "arize-phoenix": "phoenix",
        "openinference-semantic-conventions": "openinference.semconv",
        "opentelemetry-sdk": "opentelemetry.sdk",
        "huggingface-hub": "huggingface_hub",
        "mlx-lm": "mlx_lm",
        "mlx-embeddings": "mlx_embeddings",
        "py_trees": "py_trees",
    }.get(package, package.replace("-", "_"))
    return {
        "eligible": eligible,
        "component_id": component.get("id") or feature_review.get("component_id"),
        "package": package,
        "version": version,
        "requirement": f"{package}=={version}" if eligible else "",
        "import_name": import_name,
        "python_command": [str(item) for item in (component.get("python_command") or [])],
        "reason": (
            "Candidate can be installed into an isolated uv environment and import/version checked."
            if eligible
            else "This candidate needs its component-specific source/build canary; it is not a simple Python package release."
        ),
    }


def format_resolution(resolution: Dict[str, object], *, full: bool = False) -> str:
    lines = [
        f"Capability-first resolution: {resolution.get('classification') or 'unknown'}",
        f"objective: {resolution.get('objective') or '-'}",
        f"reason: {resolution.get('reason') or '-'}",
        f"next: {resolution.get('recommended_action') or '-'}",
    ]
    capability = resolution.get("matched_capability") if isinstance(resolution.get("matched_capability"), dict) else {}
    review = resolution.get("matched_feature_review") if isinstance(resolution.get("matched_feature_review"), dict) else {}
    route = resolution.get("organ_route") if isinstance(resolution.get("organ_route"), dict) else {}
    lines.append(
        "route: owner={owner} primary={primary} support={support}".format(
            owner=route.get("owner") or "eve",
            primary=route.get("primary_organ") or "-",
            support=", ".join(str(item) for item in route.get("supporting_organs") or []) or "none",
        )
    )
    if capability:
        lines.append(
            f"existing: {capability.get('id')} available={bool(capability.get('available'))} "
            f"callable={bool(capability.get('callable'))} verified={bool(capability.get('verified'))}"
        )
    if review:
        lines.append(
            f"upstream: {review.get('repository')} {review.get('target_version')} state={review.get('state')}"
        )
    if full:
        lines.append("resolution_id: " + str(resolution.get("id") or "-"))
        lines.append("fingerprint: " + str(resolution.get("fingerprint") or "-"))
        alternatives = resolution.get("top_alternatives") or []
        if alternatives:
            lines.append("alternatives:")
            for item in alternatives:
                if isinstance(item, dict):
                    lines.append(
                        f"  - {item.get('id') or item.get('name')}: score={item.get('score')} credible={item.get('credible')}"
                    )
    return "\n".join(lines)


def format_cycle(cycle: Dict[str, object], *, full: bool = False) -> str:
    target = cycle.get("target") if isinstance(cycle.get("target"), dict) else {}
    resolution = cycle.get("resolution") if isinstance(cycle.get("resolution"), dict) else {}
    lines = [
        f"Capability adoption cycle: {cycle.get('status') or 'unknown'}",
        f"target: {target.get('kind') or '-'} {target.get('id') or '-'}",
        f"classification: {resolution.get('classification') or '-'}",
        f"summary: {cycle.get('summary') or '-'}",
        f"next: {cycle.get('next_action') or resolution.get('recommended_action') or '-'}",
    ]
    research = cycle.get("research") if isinstance(cycle.get("research"), dict) else {}
    canary = cycle.get("canary") if isinstance(cycle.get("canary"), dict) else {}
    handoff = cycle.get("build_handoff") if isinstance(cycle.get("build_handoff"), dict) else {}
    assignment = cycle.get("organ_assignment") if isinstance(cycle.get("organ_assignment"), dict) else {}
    if assignment:
        lines.append(
            f"organ: {assignment.get('primary_organ') or '-'} support="
            + (", ".join(str(item) for item in assignment.get("supporting_organs") or []) or "none")
        )
    if research:
        lines.append(
            f"research: {research.get('status') or '-'} {research.get('repository') or research.get('query') or '-'}"
        )
    if canary:
        lines.append(
            f"canary: {canary.get('status') or '-'} {canary.get('component_id') or canary.get('package') or '-'}"
        )
    if handoff:
        lines.append(
            f"build_handoff: {handoff.get('status') or '-'} {handoff.get('message_id') or handoff.get('reason') or '-'}"
        )
    if full:
        lines.append(f"cycle_id: {cycle.get('id') or '-'}")
        lines.append(f"started_at: {cycle.get('started_at') or '-'}")
        lines.append(f"completed_at: {cycle.get('completed_at') or '-'}")
        lines.append(f"artifact: {cycle.get('artifact_path') or '-'}")
    return "\n".join(lines)


def format_state_markdown(state: Dict[str, object]) -> str:
    latest = state.get("latest_cycle") if isinstance(state.get("latest_cycle"), dict) else {}
    target = latest.get("target") if isinstance(latest.get("target"), dict) else {}
    resolution = latest.get("resolution") if isinstance(latest.get("resolution"), dict) else {}
    lines = [
        "# Eve Capability-First Self-Development",
        "",
        f"Updated: `{state.get('updated_at') or 'never'}`",
        "",
        "## Rule",
        "",
        "Check Eve's callable capability map, subsystem configuration/admission surfaces, and official upstream features before writing code. Canary an existing path first. Build only when the evidence says `build_required`.",
        "",
        "## Latest cycle",
        "",
        f"- status: `{latest.get('status') or 'not_run'}`",
        f"- target: `{target.get('id') or '-'}`",
        f"- classification: `{resolution.get('classification') or '-'}`",
        f"- summary: {latest.get('summary') or 'No capability-adoption cycle has run yet.'}",
        f"- next: {latest.get('next_action') or resolution.get('recommended_action') or '-'}",
        "",
        "## Totals",
        "",
    ]
    for key, value in sorted((state.get("counts") or {}).items()):
        lines.append(f"- {key}: `{value}`")
    lines.extend(
        [
            "",
            "## Authority",
            "",
            "Eve owns selection, official-source research, isolated canary execution, and evidence. OpenClaw executes admitted body/actions and owns their configuration/admission contracts. Hermes proposes learning/skills. Codex implements only proven gaps. None of these sources silently become Eve's identity or canonical memory.",
            "",
        ]
    )
    return "\n".join(lines)


def summarize_cycles(cycles: Sequence[Dict[str, object]]) -> Dict[str, int]:
    counts: Dict[str, int] = {"cycles": 0}
    for cycle in cycles:
        if not isinstance(cycle, dict):
            continue
        counts["cycles"] += 1
        resolution = cycle.get("resolution") if isinstance(cycle.get("resolution"), dict) else {}
        classification = str(resolution.get("classification") or "unknown")
        counts[classification] = counts.get(classification, 0) + 1
        canary = cycle.get("canary") if isinstance(cycle.get("canary"), dict) else {}
        if canary.get("status"):
            key = f"canary_{canary.get('status')}"
            counts[key] = counts.get(key, 0) + 1
        if cycle.get("research"):
            counts["research_runs"] = counts.get("research_runs", 0) + 1
        handoff = cycle.get("build_handoff") if isinstance(cycle.get("build_handoff"), dict) else {}
        if handoff.get("message_id"):
            counts["build_handoffs"] = counts.get("build_handoffs", 0) + 1
    return counts
