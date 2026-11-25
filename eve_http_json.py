"""Typed, bounded JSON field primitives for Eve's local mutation APIs.

The request-body reader owns byte framing; this module owns the smaller
application values inside the decoded object.  It avoids permissive ``str``
and ``bool`` coercions, validates raw length before trimming, and gives lists a
finite shape before their elements reach persistence or model work.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


DEFAULT_MAX_TEXT_CHARACTERS = 32_000
DEFAULT_MAX_IDENTIFIER_CHARACTERS = 512
DEFAULT_MAX_LIST_ITEMS = 32
_MULTILINE_CONTROLS = frozenset({"\t", "\n", "\r"})


class JSONFieldError(ValueError):
    """One decoded JSON field is outside Eve's admitted schema."""


def _positive_limit(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    if value <= 0:
        raise ValueError(f"{label} must be positive")
    return value


def require_json_object(payload: object) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise JSONFieldError("Request body must be a JSON object")
    return payload


def require_text_value(
    value: object,
    *,
    label: str,
    maximum_characters: int = DEFAULT_MAX_TEXT_CHARACTERS,
    required: bool = False,
    multiline: bool = False,
) -> str:
    """Return bounded Unicode text while rejecting hidden control characters."""

    limit = _positive_limit(maximum_characters, label="maximum_characters")
    if not isinstance(label, str) or not label:
        raise ValueError("label is required")
    if value is None:
        raw = ""
    elif isinstance(value, str):
        raw = value
    else:
        raise JSONFieldError(f"{label} must be text")
    if len(raw) > limit:
        raise JSONFieldError(f"{label} is too long")
    for character in raw:
        if character.isprintable():
            continue
        if multiline and character in _MULTILINE_CONTROLS:
            continue
        raise JSONFieldError(
            f"{label} must be printable"
            + (" text with ordinary line breaks" if multiline else "")
        )
    normalized = raw.strip()
    if required and not normalized:
        raise JSONFieldError(f"{label} is required")
    return normalized


def text_field(
    payload: object,
    key: str,
    *,
    label: str | None = None,
    maximum_characters: int = DEFAULT_MAX_TEXT_CHARACTERS,
    default: str = "",
    required: bool = False,
    multiline: bool = False,
) -> str:
    fields = require_json_object(payload)
    if not isinstance(key, str) or not key:
        raise ValueError("key is required")
    value = fields[key] if key in fields and fields[key] is not None else default
    return require_text_value(
        value,
        label=label or key,
        maximum_characters=maximum_characters,
        required=required,
        multiline=multiline,
    )


def boolean_field(
    payload: object,
    key: str,
    *,
    default: bool,
    label: str | None = None,
) -> bool:
    fields = require_json_object(payload)
    if not isinstance(key, str) or not key:
        raise ValueError("key is required")
    if not isinstance(default, bool):
        raise TypeError("default must be a Boolean")
    if key not in fields:
        return default
    value = fields[key]
    if not isinstance(value, bool):
        raise JSONFieldError(f"{label or key} must be a JSON Boolean")
    return value


def object_list_value(
    value: object,
    *,
    maximum_items: int = DEFAULT_MAX_LIST_ITEMS,
    label: str,
) -> list[dict[str, Any]]:
    limit = _positive_limit(maximum_items, label="maximum_items")
    if value is None:
        return []
    if not isinstance(value, list):
        raise JSONFieldError(f"{label} must be an array")
    if len(value) > limit:
        raise JSONFieldError(f"{label} accepts at most {limit} items")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise JSONFieldError(f"{label}[{index}] must be an object")
        normalized.append(item)
    return normalized


def object_list_field(
    payload: object,
    key: str,
    *,
    maximum_items: int = DEFAULT_MAX_LIST_ITEMS,
    label: str | None = None,
) -> list[dict[str, Any]]:
    fields = require_json_object(payload)
    return object_list_value(
        fields.get(key),
        maximum_items=maximum_items,
        label=label or key,
    )


def string_list_value(
    value: object,
    *,
    label: str,
    maximum_items: int = DEFAULT_MAX_LIST_ITEMS,
    maximum_item_characters: int = 64,
    allow_space_separated_string: bool = False,
) -> list[str]:
    item_limit = _positive_limit(maximum_items, label="maximum_items")
    character_limit = _positive_limit(
        maximum_item_characters,
        label="maximum_item_characters",
    )
    if value is None:
        candidates: list[object] = []
    elif isinstance(value, str) and allow_space_separated_string:
        normalized = require_text_value(
            value,
            label=label,
            maximum_characters=(item_limit * character_limit) + max(0, item_limit - 1),
        )
        candidates = normalized.split()
    elif isinstance(value, list):
        candidates = value
    else:
        raise JSONFieldError(f"{label} must be an array")
    if len(candidates) > item_limit:
        raise JSONFieldError(f"{label} accepts at most {item_limit} items")
    return [
        require_text_value(
            item,
            label=f"{label}[{index}]",
            maximum_characters=character_limit,
            required=True,
        )
        for index, item in enumerate(candidates)
    ]


def string_list_field(
    payload: object,
    key: str,
    *,
    maximum_items: int = DEFAULT_MAX_LIST_ITEMS,
    maximum_item_characters: int = 64,
    allow_space_separated_string: bool = False,
    label: str | None = None,
) -> list[str]:
    fields = require_json_object(payload)
    return string_list_value(
        fields.get(key),
        label=label or key,
        maximum_items=maximum_items,
        maximum_item_characters=maximum_item_characters,
        allow_space_separated_string=allow_space_separated_string,
    )
