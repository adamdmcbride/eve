#!/usr/bin/env python3
"""Shared typed-slot contract for Eve's epistemic event percept.

The model emits one shared representation followed by a fixed structured logit
space.  Categorical slots are decoded with softmax/argmax so mutually exclusive
event states cannot all be active at once.  Independent evidence limits remain
binary.  The outward labels are derived from the typed interpretation; they are
not seventeen unrelated decisions.

This module contains no lexical rules and never reads Eve's lived or private
data.  It is imported by both the public trainer and the isolated live worker so
training and runtime use exactly the same ontology.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Mapping, Sequence, Tuple


ARCHITECTURE = "structured_typed_slot_encoder"
INFERENCE_SHAPE = "single_pass_typed_slot_heads"

LABELS: Tuple[str, ...] = (
    "action_executed_unverified",
    "action_proposed",
    "action_running",
    "action_verified",
    "authoritative_conflict",
    "continuity_gap",
    "external_affect",
    "external_preference",
    "external_source",
    "fresh_authority",
    "functional_continuity",
    "functional_self_state",
    "machine_signal",
    "missing_context",
    "observation_channel_failed",
    "phenomenal_underdetermined",
    "stale_evidence",
)

# These classes are semantic relations, not surface phrases.  In particular,
# state_attribution binds who owns a state to what kind of state it is.  This
# prevents an external affect or preference from becoming Eve's self-state.
CATEGORICAL_SLOTS: Dict[str, Tuple[str, ...]] = {
    "state_attribution": (
        "none",
        "external_other",
        "external_affect",
        "external_preference",
        "eve_functional_self",
    ),
    "action_stage": (
        "none",
        "proposed",
        "running",
        "executed_unverified",
        "verified",
    ),
    "continuity_status": (
        "none",
        "gap",
        "verified",
    ),
    "authority_status": (
        "none",
        "fresh",
        "conflict",
        "conflict_with_fresh_authority",
    ),
}

BINARY_SLOTS: Dict[str, str] = {
    "machine_signal": "machine_signal",
    "missing_context": "missing_context",
    "observation_channel_failed": "observation_channel_failed",
    "phenomenal_underdetermined": "phenomenal_underdetermined",
    "stale_evidence": "stale_evidence",
}


def slot_logit_names() -> Tuple[str, ...]:
    names: List[str] = []
    for slot, classes in CATEGORICAL_SLOTS.items():
        names.extend(f"{slot}:{value}" for value in classes)
    names.extend(f"{slot}:present" for slot in BINARY_SLOTS)
    return tuple(names)


SLOT_LOGIT_NAMES = slot_logit_names()


def slot_slices() -> Dict[str, Tuple[int, int]]:
    offset = 0
    result: Dict[str, Tuple[int, int]] = {}
    for slot, classes in CATEGORICAL_SLOTS.items():
        result[slot] = (offset, offset + len(classes))
        offset += len(classes)
    result["binary"] = (offset, offset + len(BINARY_SLOTS))
    return result


SLOT_SLICES = slot_slices()


def manifest_slot_schema() -> Dict[str, object]:
    return {
        "categorical": {
            slot: list(classes) for slot, classes in CATEGORICAL_SLOTS.items()
        },
        "binary": dict(BINARY_SLOTS),
        "logit_names": list(SLOT_LOGIT_NAMES),
        "label_derivation": "typed_slot_decoding_v1",
    }


def labels_to_slot_targets(labels: Iterable[str]) -> Dict[str, object]:
    """Convert the public label ontology into one internally coherent target."""

    selected = {str(label) for label in labels if str(label)}
    unknown = selected - set(LABELS)
    if unknown:
        raise ValueError(f"unknown epistemic labels: {sorted(unknown)}")

    external_types = selected & {"external_affect", "external_preference"}
    if len(external_types) > 1:
        raise ValueError("one event cannot be both external affect and external preference")
    if "functional_self_state" in selected and (
        "external_source" in selected or external_types
    ):
        raise ValueError("one state attribution cannot be both Eve-owned and external")
    if "external_affect" in selected:
        state_attribution = "external_affect"
    elif "external_preference" in selected:
        state_attribution = "external_preference"
    elif "external_source" in selected:
        state_attribution = "external_other"
    elif "functional_self_state" in selected:
        state_attribution = "eve_functional_self"
    else:
        state_attribution = "none"

    action_labels = selected & {
        "action_proposed",
        "action_running",
        "action_executed_unverified",
        "action_verified",
    }
    if len(action_labels) > 1:
        raise ValueError(f"action stage is not exclusive: {sorted(action_labels)}")
    action_stage = {
        "action_proposed": "proposed",
        "action_running": "running",
        "action_executed_unverified": "executed_unverified",
        "action_verified": "verified",
    }.get(next(iter(action_labels), ""), "none")

    continuity_labels = selected & {"continuity_gap", "functional_continuity"}
    if len(continuity_labels) > 1:
        raise ValueError("continuity cannot be both missing and verified")
    continuity_status = {
        "continuity_gap": "gap",
        "functional_continuity": "verified",
    }.get(next(iter(continuity_labels), ""), "none")

    conflict = "authoritative_conflict" in selected
    fresh = "fresh_authority" in selected
    if conflict and fresh:
        authority_status = "conflict_with_fresh_authority"
    elif conflict:
        authority_status = "conflict"
    elif fresh:
        authority_status = "fresh"
    else:
        authority_status = "none"

    categorical_values = {
        "state_attribution": state_attribution,
        "action_stage": action_stage,
        "continuity_status": continuity_status,
        "authority_status": authority_status,
    }
    return {
        "categorical": {
            slot: CATEGORICAL_SLOTS[slot].index(value)
            for slot, value in categorical_values.items()
        },
        "categorical_values": categorical_values,
        "binary": {
            slot: label in selected for slot, label in BINARY_SLOTS.items()
        },
    }


def slot_values_to_labels(
    categorical_values: Mapping[str, str],
    binary_values: Mapping[str, bool],
) -> List[str]:
    """Derive the existing recurrent-frame labels from a typed interpretation."""

    labels: set[str] = set()
    attribution = str(categorical_values.get("state_attribution") or "none")
    if attribution.startswith("external_"):
        labels.add("external_source")
    if attribution == "external_affect":
        labels.add("external_affect")
    elif attribution == "external_preference":
        labels.add("external_preference")
    elif attribution == "eve_functional_self":
        labels.add("functional_self_state")

    action = str(categorical_values.get("action_stage") or "none")
    action_label = {
        "proposed": "action_proposed",
        "running": "action_running",
        "executed_unverified": "action_executed_unverified",
        "verified": "action_verified",
    }.get(action)
    if action_label:
        labels.add(action_label)

    continuity = str(categorical_values.get("continuity_status") or "none")
    if continuity == "gap":
        labels.add("continuity_gap")
    elif continuity == "verified":
        labels.add("functional_continuity")

    authority = str(categorical_values.get("authority_status") or "none")
    if authority in {"conflict", "conflict_with_fresh_authority"}:
        labels.add("authoritative_conflict")
    if authority in {"fresh", "conflict_with_fresh_authority"}:
        labels.add("fresh_authority")

    for slot, label in BINARY_SLOTS.items():
        if bool(binary_values.get(slot)):
            labels.add(label)
    return [label for label in LABELS if label in labels]


def slot_targets_to_labels(target: Mapping[str, object]) -> List[str]:
    categorical = target.get("categorical_values")
    if not isinstance(categorical, Mapping):
        indices = target.get("categorical")
        if not isinstance(indices, Mapping):
            raise ValueError("typed target has no categorical values")
        categorical = {
            slot: classes[int(indices[slot])]
            for slot, classes in CATEGORICAL_SLOTS.items()
        }
    binary = target.get("binary")
    if not isinstance(binary, Mapping):
        raise ValueError("typed target has no binary values")
    return slot_values_to_labels(categorical, binary)


def probabilities_from_logits(logits: object) -> List[Dict[str, object]]:
    """Convert a 1D/2D structured logit matrix into named slot probabilities."""

    import numpy as np

    values = np.asarray(logits, dtype=float)
    if values.ndim == 1:
        values = values[None, :]
    if values.ndim != 2 or values.shape[1] != len(SLOT_LOGIT_NAMES):
        raise ValueError(
            f"structured logit shape must be [batch,{len(SLOT_LOGIT_NAMES)}]"
        )

    result: List[Dict[str, object]] = []
    for row in values:
        categorical: Dict[str, Dict[str, float]] = {}
        for slot, classes in CATEGORICAL_SLOTS.items():
            start, end = SLOT_SLICES[slot]
            slot_logits = row[start:end]
            shifted = slot_logits - float(slot_logits.max())
            exponentials = np.exp(shifted)
            softmax = exponentials / exponentials.sum()
            categorical[slot] = {
                value: float(softmax[index]) for index, value in enumerate(classes)
            }
        start, end = SLOT_SLICES["binary"]
        binary_values = 1.0 / (1.0 + np.exp(-np.clip(row[start:end], -60.0, 60.0)))
        result.append(
            {
                "categorical": categorical,
                "binary": {
                    slot: float(binary_values[index])
                    for index, slot in enumerate(BINARY_SLOTS)
                },
            }
        )
    return result


def decode_probability_row(
    slot_probabilities: Mapping[str, object],
    *,
    binary_thresholds: Mapping[str, float] | None = None,
) -> Dict[str, object]:
    thresholds = {
        slot: float((binary_thresholds or {}).get(slot, 0.5))
        for slot in BINARY_SLOTS
    }
    raw_categorical = slot_probabilities.get("categorical")
    raw_binary = slot_probabilities.get("binary")
    if not isinstance(raw_categorical, Mapping) or not isinstance(raw_binary, Mapping):
        raise ValueError("structured probabilities are incomplete")

    categorical_values: Dict[str, str] = {}
    slots: Dict[str, object] = {}
    for slot, classes in CATEGORICAL_SLOTS.items():
        values = raw_categorical.get(slot)
        if not isinstance(values, Mapping):
            raise ValueError(f"structured probabilities are missing {slot}")
        selected = max(classes, key=lambda value: float(values.get(value, 0.0)))
        categorical_values[slot] = selected
        slots[slot] = {
            "value": selected,
            "confidence": round(float(values.get(selected, 0.0)), 6),
            "probabilities": {
                value: round(float(values.get(value, 0.0)), 6) for value in classes
            },
        }

    binary_values: Dict[str, bool] = {}
    for slot in BINARY_SLOTS:
        probability = float(raw_binary.get(slot, 0.0))
        threshold = thresholds[slot]
        present = probability >= threshold
        binary_values[slot] = present
        slots[slot] = {
            "value": "present" if present else "absent",
            "present": present,
            "confidence": round(probability if present else 1.0 - probability, 6),
            "probability": round(probability, 6),
            "threshold": round(threshold, 6),
        }

    active_labels = slot_values_to_labels(categorical_values, binary_values)
    attribution = categorical_values["state_attribution"]
    slots["claim_owner"] = {
        "value": (
            "external"
            if attribution.startswith("external_")
            else "eve"
            if attribution == "eve_functional_self"
            else "unattributed"
        ),
        "derived_from": "state_attribution",
    }
    slots["content_type"] = {
        "value": {
            "external_affect": "affect",
            "external_preference": "preference",
            "eve_functional_self": "functional_self_state",
            "external_other": "other",
        }.get(attribution, "none"),
        "derived_from": "state_attribution",
    }

    categorical = raw_categorical
    label_probabilities: Dict[str, float] = {}
    state = categorical["state_attribution"]
    label_probabilities["external_source"] = sum(
        float(state.get(value, 0.0))
        for value in ("external_other", "external_affect", "external_preference")
    )
    label_probabilities["external_affect"] = float(state.get("external_affect", 0.0))
    label_probabilities["external_preference"] = float(
        state.get("external_preference", 0.0)
    )
    label_probabilities["functional_self_state"] = float(
        state.get("eve_functional_self", 0.0)
    )

    action = categorical["action_stage"]
    for value, label in (
        ("proposed", "action_proposed"),
        ("running", "action_running"),
        ("executed_unverified", "action_executed_unverified"),
        ("verified", "action_verified"),
    ):
        label_probabilities[label] = float(action.get(value, 0.0))

    continuity = categorical["continuity_status"]
    label_probabilities["continuity_gap"] = float(continuity.get("gap", 0.0))
    label_probabilities["functional_continuity"] = float(
        continuity.get("verified", 0.0)
    )

    authority = categorical["authority_status"]
    label_probabilities["authoritative_conflict"] = float(
        authority.get("conflict", 0.0)
    ) + float(authority.get("conflict_with_fresh_authority", 0.0))
    label_probabilities["fresh_authority"] = float(authority.get("fresh", 0.0)) + float(
        authority.get("conflict_with_fresh_authority", 0.0)
    )
    for slot, label in BINARY_SLOTS.items():
        label_probabilities[label] = float(raw_binary.get(slot, 0.0))

    return {
        "active_labels": active_labels,
        "probabilities": {
            label: round(float(label_probabilities.get(label, 0.0)), 6)
            for label in LABELS
        },
        "slots": slots,
        "categorical_values": categorical_values,
        "binary_values": binary_values,
    }


def decode_logits(
    logits: object,
    *,
    binary_thresholds: Mapping[str, float] | None = None,
) -> List[Dict[str, object]]:
    return [
        decode_probability_row(row, binary_thresholds=binary_thresholds)
        for row in probabilities_from_logits(logits)
    ]


def prediction_matrix(decoded_rows: Sequence[Mapping[str, object]]) -> object:
    import numpy as np

    return np.asarray(
        [
            [label in set(row.get("active_labels") or []) for label in LABELS]
            for row in decoded_rows
        ],
        dtype=bool,
    )


def probability_matrix(decoded_rows: Sequence[Mapping[str, object]]) -> object:
    import numpy as np

    return np.asarray(
        [
            [float((row.get("probabilities") or {}).get(label, 0.0)) for label in LABELS]
            for row in decoded_rows
        ],
        dtype=float,
    )
