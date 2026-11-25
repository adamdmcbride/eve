"""Bounded, unambiguous query parsing for Eve's local HTTP surfaces.

``urllib.parse.parse_qs`` is intentionally permissive: duplicate fields become
lists, blank values may disappear, Boolean spellings are caller-defined, and
integer coercion is commonly repeated ad hoc.  This module gives Eve's runtime
API one small query contract and lets the app proxy apply the same input budget
before forwarding a request.

It is a parsing and resource boundary, not authentication or authorization.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Optional
from urllib.parse import parse_qs


DEFAULT_MAX_QUERY_CHARACTERS = 8 * 1024
DEFAULT_MAX_QUERY_FIELDS = 32
DEFAULT_MAX_QUERY_KEY_CHARACTERS = 128
DEFAULT_MAX_QUERY_VALUE_CHARACTERS = 512
TRUE_QUERY_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_QUERY_VALUES = frozenset({"0", "false", "no", "off"})


def _contains_control(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


@dataclass(frozen=True)
class BoundedQuery:
    """Parsed query values with strict typed single-value accessors."""

    values: Mapping[str, tuple[str, ...]]

    @classmethod
    def parse(
        cls,
        query_string: object,
        *,
        maximum_characters: int = DEFAULT_MAX_QUERY_CHARACTERS,
        maximum_fields: int = DEFAULT_MAX_QUERY_FIELDS,
    ) -> "BoundedQuery":
        if not isinstance(query_string, str):
            raise ValueError("query string must be text")
        if len(query_string) > maximum_characters:
            raise ValueError(
                f"query string exceeds the {maximum_characters}-character limit"
            )
        if not query_string:
            # An absent query is valid. Python 3.9's ``parse_qs`` raises under
            # ``strict_parsing`` for the empty string, which made every plain
            # request (``/health``, ``/v1/models``) a 400 on the app backend.
            return cls(values=MappingProxyType({}))
        try:
            parsed = parse_qs(
                query_string,
                keep_blank_values=True,
                strict_parsing=True,
                encoding="utf-8",
                errors="strict",
                max_num_fields=maximum_fields,
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError("query string is malformed or has too many fields") from exc

        normalized: dict[str, tuple[str, ...]] = {}
        for key, values in parsed.items():
            if (
                not key
                or len(key) > DEFAULT_MAX_QUERY_KEY_CHARACTERS
                or _contains_control(key)
            ):
                raise ValueError("query field names must be short printable text")
            normalized[key] = tuple(values)
        return cls(values=MappingProxyType(normalized))

    def value(
        self,
        name: str,
        *,
        default: Optional[str] = None,
        maximum_characters: int = DEFAULT_MAX_QUERY_VALUE_CHARACTERS,
        strip: bool = True,
    ) -> Optional[str]:
        values = self.values.get(name)
        if values is None:
            return default
        if len(values) != 1:
            raise ValueError(f"{name} must be supplied at most once")
        value = values[0].strip() if strip else values[0]
        if not value:
            raise ValueError(f"{name} cannot be empty")
        if len(value) > maximum_characters or _contains_control(value):
            raise ValueError(
                f"{name} must be printable text no longer than {maximum_characters} characters"
            )
        return value

    def integer(
        self,
        name: str,
        *,
        default: Optional[int] = None,
        minimum: int,
        maximum: int,
    ) -> Optional[int]:
        raw = self.value(name, strip=False)
        if raw is None:
            return default
        if len(raw) > 20 or any(character < "0" or character > "9" for character in raw):
            raise ValueError(f"{name} must be an ASCII-decimal integer")
        value = int(raw)
        if not minimum <= value <= maximum:
            raise ValueError(f"{name} must be from {minimum} through {maximum}")
        return value

    def boolean(self, name: str, *, default: bool) -> bool:
        raw = self.value(name, strip=False)
        if raw is None:
            return default
        normalized = raw.lower()
        if normalized in TRUE_QUERY_VALUES:
            return True
        if normalized in FALSE_QUERY_VALUES:
            return False
        raise ValueError(
            f"{name} must be one of 1, true, yes, on, 0, false, no, or off"
        )
