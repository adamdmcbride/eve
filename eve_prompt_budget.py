#!/usr/bin/env python3

"""Exact, evidence-producing prompt-fit preflight for Eve's llama.cpp lanes.

The llama.cpp ``--ctx-size`` value is divided between parallel slots.  A
configured 16K server with two slots therefore exposes an 8K request budget.
This module asks the live server for that effective budget, renders the real
chat template, tokenizes the rendered prompt, and trims only caller-marked
optional context.  It never silently truncates required identity or user text.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib import error, request


DEFAULT_SAFETY_TOKENS = 256
DEFAULT_TIMEOUT_SECONDS = 3.0


class PromptFitError(RuntimeError):
    """Raised when required prompt material cannot fit the resident lane."""


@dataclass(frozen=True)
class PromptMeasurement:
    context_tokens: int
    prompt_tokens: int
    exact: bool
    source: str


def _post_json(url: str, payload: Dict[str, object], timeout: float) -> Dict[str, object]:
    req = request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=max(0.1, float(timeout))) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object from {url}")
    return value


def _get_json(url: str, timeout: float) -> Dict[str, object]:
    with request.urlopen(url, timeout=max(0.1, float(timeout))) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object from {url}")
    return value


def conservative_token_estimate(text: object) -> int:
    """Estimate tokens conservatively when the live tokenizer is unavailable."""

    # Three UTF-8-ish characters per token intentionally overestimates ordinary
    # English and remains safer for code, identifiers, and structured context.
    return max(1, int(math.ceil(len(str(text or "")) / 3.0)))


def normalize_messages(messages: Iterable[Dict[str, object]]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        role = " ".join(str(message.get("role") or "user").lower().split()) or "user"
        normalized.append({"role": role, "content": content})
    return normalized


def prepare_llama_cpp_messages(messages: Iterable[Dict[str, object]]) -> List[Dict[str, str]]:
    """Mirror Eve's Gemma-compatible role preparation before measurement."""

    source = normalize_messages(messages)
    prepared: List[Dict[str, str]] = []
    leading_system: List[str] = []
    conversation_started = False

    def append(role: str, content: str) -> None:
        if prepared and prepared[-1]["role"] == role:
            prepared[-1]["content"] = (
                prepared[-1]["content"].rstrip() + "\n\n" + content
            ).strip()
        else:
            prepared.append({"role": role, "content": content})

    for message in source:
        role = message["role"]
        content = message["content"]
        if role == "system" and not conversation_started:
            leading_system.append(content)
            continue
        if not conversation_started:
            conversation_started = True
            if leading_system:
                prepared.append({"role": "system", "content": "\n\n".join(leading_system)})
        if role == "assistant":
            append("assistant", content)
        elif role == "system":
            append("user", "System guidance:\n" + content)
        else:
            append("user", content)
    if not conversation_started and leading_system:
        prepared.append({"role": "system", "content": "\n\n".join(leading_system)})
    return prepared


def live_context_tokens(host: str, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> int:
    props = _get_json(host.rstrip("/") + "/props", timeout)
    settings = props.get("default_generation_settings")
    if not isinstance(settings, dict):
        return 0
    value = settings.get("n_ctx")
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def render_live_chat_prompt(
    host: str,
    messages: Sequence[Dict[str, object]],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    result = _post_json(
        host.rstrip("/") + "/apply-template",
        {"messages": prepare_llama_cpp_messages(messages), "add_generation_prompt": True},
        timeout,
    )
    prompt = result.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        raise ValueError("llama.cpp /apply-template returned no prompt")
    return prompt


def tokenize_live_text(
    host: str,
    text: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> int:
    result = _post_json(
        host.rstrip("/") + "/tokenize",
        {"content": str(text or ""), "add_special": False},
        timeout,
    )
    tokens = result.get("tokens")
    if not isinstance(tokens, list):
        raise ValueError("llama.cpp /tokenize returned no token list")
    return len(tokens)


def measure_prompt(
    host: str,
    messages: Sequence[Dict[str, object]],
    *,
    fallback_context_tokens: int = 0,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> PromptMeasurement:
    try:
        context_tokens = live_context_tokens(host, timeout=timeout)
        prompt = render_live_chat_prompt(host, messages, timeout=timeout)
        prompt_tokens = tokenize_live_text(host, prompt, timeout=timeout)
        if context_tokens <= 0:
            raise ValueError("llama.cpp did not report a positive per-slot context")
        return PromptMeasurement(
            context_tokens=context_tokens,
            prompt_tokens=prompt_tokens,
            exact=True,
            source="llama_cpp_props_apply_template_tokenize",
        )
    except (OSError, ValueError, json.JSONDecodeError, error.URLError):
        normalized = normalize_messages(messages)
        rendered_estimate = "\n\n".join(
            f"<{item['role']}>\n{item['content']}" for item in normalized
        )
        return PromptMeasurement(
            context_tokens=max(0, int(fallback_context_tokens or 0)),
            prompt_tokens=conservative_token_estimate(rendered_estimate),
            exact=False,
            source="conservative_character_fallback",
        )


def available_prompt_tokens(
    context_tokens: int,
    max_tokens: int,
    *,
    safety_tokens: int = DEFAULT_SAFETY_TOKENS,
) -> int:
    return max(0, int(context_tokens) - max(1, int(max_tokens)) - max(0, int(safety_tokens)))


def _trim_middle(text: str, target_chars: int) -> str:
    target = max(0, int(target_chars))
    if len(text) <= target:
        return text
    marker = "\n[optional context trimmed to fit resident lane]\n"
    if target <= len(marker) + 24:
        return text[:target]
    remaining = target - len(marker)
    head = max(12, int(remaining * 0.65))
    tail = max(12, remaining - head)
    return text[:head].rstrip() + marker + text[-tail:].lstrip()


def fit_messages(
    host: str,
    messages: Sequence[Dict[str, object]],
    *,
    max_tokens: int,
    safety_tokens: int = DEFAULT_SAFETY_TOKENS,
    fallback_context_tokens: int = 0,
    required_indices: Optional[Iterable[int]] = None,
    optional_priorities: Optional[Dict[int, int]] = None,
    minimum_optional_chars: int = 160,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    measurement: Optional[Callable[[Sequence[Dict[str, object]]], PromptMeasurement]] = None,
) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    """Fit a prompt by reducing only explicitly optional messages.

    ``required_indices`` are never edited or removed. ``optional_priorities``
    maps message indexes to integer priorities; lower values are reclaimed
    first.  Unlisted messages are required.  The return metadata contains
    counts and indexes only, never prompt text.
    """

    working = [dict(item) for item in messages]
    required = {int(index) for index in (required_indices or [])}
    priorities = {int(index): int(value) for index, value in (optional_priorities or {}).items()}
    required.update(index for index in range(len(working)) if index not in priorities)

    def run_measure(current: Sequence[Dict[str, object]]) -> PromptMeasurement:
        if measurement is not None:
            return measurement(current)
        return measure_prompt(
            host,
            current,
            fallback_context_tokens=fallback_context_tokens,
            timeout=timeout,
        )

    before = run_measure(working)
    budget = available_prompt_tokens(
        before.context_tokens,
        max_tokens,
        safety_tokens=safety_tokens,
    )
    if before.context_tokens <= 0:
        raise PromptFitError("Resident lane context size is unknown; refusing unbounded prompt submission.")

    removed: List[int] = []
    trimmed: List[int] = []
    active_indexes = list(range(len(working)))
    current = before

    # Lower priority optional messages yield first. Stable index ordering keeps
    # this deterministic and makes behavior auditable.
    candidates = sorted(
        (index for index in priorities if index not in required and 0 <= index < len(working)),
        key=lambda index: (priorities[index], index),
    )
    for original_index in candidates:
        if current.prompt_tokens <= budget:
            break
        if original_index not in active_indexes:
            continue
        position = active_indexes.index(original_index)
        content = str(working[position].get("content") or "")
        excess = max(1, current.prompt_tokens - budget)
        chars_per_token = max(1.0, sum(len(str(item.get("content") or "")) for item in working) / max(1, current.prompt_tokens))
        target_chars = max(
            int(minimum_optional_chars),
            len(content) - int(math.ceil(excess * chars_per_token * 1.15)),
        )
        if len(content) > int(minimum_optional_chars) and target_chars < len(content):
            working[position]["content"] = _trim_middle(content, target_chars)
            trimmed.append(original_index)
            current = run_measure(working)
        if current.prompt_tokens > budget:
            del working[position]
            active_indexes.remove(original_index)
            removed.append(original_index)
            current = run_measure(working)

    if current.prompt_tokens > budget:
        raise PromptFitError(
            "Required prompt material exceeds the resident lane budget "
            f"({current.prompt_tokens}>{budget} tokens)."
        )

    final_user_before = next(
        (str(item.get("content") or "") for item in reversed(messages) if str(item.get("role") or "").lower() == "user"),
        "",
    )
    final_user_after = next(
        (str(item.get("content") or "") for item in reversed(working) if str(item.get("role") or "").lower() == "user"),
        "",
    )
    metadata: Dict[str, object] = {
        "schema_id": "eve.prompt_fit.v1",
        "status": "trimmed" if removed or trimmed else "fit",
        "measurement_source": current.source,
        "exact_measurement": bool(current.exact),
        "context_tokens": int(current.context_tokens),
        "prompt_budget_tokens": int(budget),
        "prompt_tokens_before": int(before.prompt_tokens),
        "prompt_tokens_after": int(current.prompt_tokens),
        "max_output_tokens": int(max_tokens),
        "safety_tokens": int(safety_tokens),
        "trimmed_message_indices": sorted(set(trimmed)),
        "removed_message_indices": sorted(set(removed)),
        "required_message_indices": sorted(required),
        "final_user_preserved": final_user_before == final_user_after,
        "content_persisted": False,
    }
    return working, metadata
