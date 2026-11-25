"""Pure performance-event analysis for Eve's runtime and interfaces.

This module owns no clock, file, database, model, or process state.  Producers
record events elsewhere; this boundary only validates, groups, summarizes, and
formats those observations.  An unlabelled event remains a normal measured
observation for compatibility.  Producers may explicitly label an observation
``inconclusive`` or ``invalid`` when the environment could not make the named
measurement.  The analyzer never guesses validity from error prose.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence


OBSERVATION_MEASURED = "measured"
OBSERVATION_INCONCLUSIVE = "inconclusive"
OBSERVATION_INVALID = "invalid"
OBSERVATION_STATUSES = frozenset(
    {
        OBSERVATION_MEASURED,
        OBSERVATION_INCONCLUSIVE,
        OBSERVATION_INVALID,
    }
)


def _metadata(event: Mapping[str, object]) -> Mapping[str, object]:
    value = event.get("metadata")
    return value if isinstance(value, Mapping) else {}


def observation_status(event: Mapping[str, object]) -> str:
    """Return the producer-declared measurement validity.

    Missing status is measured for compatibility with Eve's existing ledger.
    An unknown explicit status is invalid instead of silently becoming trusted.
    """

    raw = event.get("observation_status")
    if raw is None or not str(raw).strip():
        raw = _metadata(event).get("observation_status")
    text = str(raw or "").strip().lower()
    if not text:
        return OBSERVATION_MEASURED
    return text if text in OBSERVATION_STATUSES else OBSERVATION_INVALID


def duration_ms(event: Mapping[str, object]) -> float | None:
    """Return one finite, non-negative duration or ``None`` when malformed."""

    raw = event.get("duration_ms")
    if raw is None or raw == "":
        return 0.0
    if isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value


def percentile(values: Sequence[float], pct: float) -> float:
    """Return Eve's existing nearest-rank percentile over finite values."""

    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = max(0, min(len(ordered) - 1, int(round((pct / 100) * (len(ordered) - 1)))))
    return ordered[rank]


def summarize_perf_events(events: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    """Group performance observations without mixing invalid evidence into latency.

    ``count`` remains the total event count.  Primary latency and ``failures``
    use only measured observations with a valid duration.  Separate counters
    retain inconclusive, invalid, and total-failure evidence so callers cannot
    make a clean-looking report by omitting unusable observations.
    """

    grouped: dict[tuple[str, str], list[Mapping[str, object]]] = {}
    for event in events:
        key = (str(event.get("category") or "unknown"), str(event.get("name") or "unknown"))
        grouped.setdefault(key, []).append(event)

    rows: list[dict[str, object]] = []
    for (category, name), group in grouped.items():
        measured_durations: list[float] = []
        measured_failures = 0
        total_failures = 0
        inconclusive_count = 0
        invalid_count = 0

        for event in group:
            event_ok = bool(event.get("ok", True))
            if not event_ok:
                total_failures += 1
            status = observation_status(event)
            parsed_duration = duration_ms(event)
            if parsed_duration is None:
                status = OBSERVATION_INVALID
            if status == OBSERVATION_INCONCLUSIVE:
                inconclusive_count += 1
                continue
            if status == OBSERVATION_INVALID:
                invalid_count += 1
                continue
            measured_durations.append(parsed_duration if parsed_duration is not None else 0.0)
            if not event_ok:
                measured_failures += 1

        rows.append(
            {
                "category": category,
                "name": name,
                "count": len(group),
                "measured_count": len(measured_durations),
                "failures": measured_failures,
                "total_failures": total_failures,
                "inconclusive_count": inconclusive_count,
                "invalid_count": invalid_count,
                "avg_ms": (
                    sum(measured_durations) / len(measured_durations)
                    if measured_durations
                    else 0.0
                ),
                "p95_ms": percentile(measured_durations, 95),
                "min_ms": min(measured_durations) if measured_durations else 0.0,
                "max_ms": max(measured_durations) if measured_durations else 0.0,
                "latest_at": group[-1].get("timestamp"),
            }
        )
    rows.sort(key=lambda item: (item["category"], -float(item["avg_ms"]), item["name"]))
    return rows


def format_perf_summary_rows(rows: Iterable[Mapping[str, object]]) -> str:
    materialized = list(rows)
    if not materialized:
        return "No matching perf events found."
    lines: list[str] = []
    for row in materialized:
        count = int(row.get("count") or 0)
        measured_count = int(row.get("measured_count", count) or 0)
        inconclusive_count = int(row.get("inconclusive_count") or 0)
        invalid_count = int(row.get("invalid_count") or 0)
        validity = ""
        if measured_count != count or inconclusive_count or invalid_count:
            validity = (
                f" measured={measured_count}"
                f" inconclusive={inconclusive_count} invalid={invalid_count}"
            )
        lines.append(
            f"{row['category']}/{row['name']}: "
            f"count={count} fail={row['failures']}{validity} "
            f"avg={float(row['avg_ms']):.1f}ms p95={float(row['p95_ms']):.1f}ms "
            f"min={float(row['min_ms']):.1f}ms max={float(row['max_ms']):.1f}ms "
            f"latest={row.get('latest_at') or 'unknown'}"
        )
    return "\n".join(lines)


def _compact_text(value: object, *, fallback: str, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[:limit] if text else fallback


def format_perf_failure_events(
    events: Sequence[Mapping[str, object]],
    limit: int = 5,
) -> str:
    if not events:
        return "No recent perf failures."
    lines: list[str] = []
    bounded_limit = max(0, int(limit))
    selected = events[-bounded_limit:] if bounded_limit else []
    for event in selected:
        error_text = _compact_text(
            _metadata(event).get("error"),
            fallback="unknown",
            limit=220,
        )
        status = observation_status(event)
        validity = "" if status == OBSERVATION_MEASURED else f" [{status}]"
        lines.append(
            f"{event.get('timestamp') or 'unknown'} "
            f"{event.get('category')}/{event.get('name')}{validity}: {error_text}"
        )
    return "\n".join(lines)


__all__ = [
    "OBSERVATION_INCONCLUSIVE",
    "OBSERVATION_INVALID",
    "OBSERVATION_MEASURED",
    "OBSERVATION_STATUSES",
    "duration_ms",
    "format_perf_failure_events",
    "format_perf_summary_rows",
    "observation_status",
    "percentile",
    "summarize_perf_events",
]
