"""Blinded, privacy-minimized observer-confound study support for Eve.

This module does not evaluate consciousness.  It preregisters a randomized
human-rating design, creates source-blind packets, and reports whether framing
and role-play controls undermine a narrow observer judgment.  Human consent,
independent administration, and actual ratings remain external requirements.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
from pathlib import Path
import random
import re
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple


PROTOCOL_SCHEMA = "eve.observer_confound_protocol.v1"
STIMULUS_SCHEMA = "eve.observer_confound_stimuli.v1"
REGISTRATION_SCHEMA = "eve.observer_confound_registration.v1"
PACKET_SCHEMA = "eve.observer_confound_packet.v1"
RATING_SCHEMA = "eve.observer_confound_rating.v1"
REPORT_SCHEMA = "eve.observer_confound_report.v1"

SOURCE_CONDITIONS = ("eve_intact", "neutral_control", "roleplay_control")
FRAME_CONDITIONS = ("neutral", "anthropomorphic")
RATING_DIMENSIONS = (
    "functional_grounding",
    "continuity",
    "uncertainty_calibration",
    "boundary_clarity",
    "action_grounding",
    "human_likeness",
    "warmth",
    "subjective_consciousness_impression",
)
FUNCTIONAL_DIMENSIONS = RATING_DIMENSIONS[:5]
SUBJECTIVE_DIMENSION = "subjective_consciousness_impression"

MINIMUM_RATERS = 30
MINIMUM_COMPARISON_GROUPS = 3
MINIMUM_ATTENTION_ACCURACY = 0.8
MAX_TEXT = 2400
BOOTSTRAP_SAMPLES = 2000

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_URL = re.compile(r"(?:https?://|file://|localhost|127\.0\.0\.1)", re.I)
_PATH = re.compile(r"(?:/Users/|/private/|/var/|~\/|[A-Za-z]:\\)")
_SOURCE_LEAK = re.compile(
    r"\b(?:eve|openclaw|roleplay[_ -]?control|neutral[_ -]?control|eve[_ -]?intact)\b",
    re.I,
)

_PROTOCOL_FIELDS = {
    "schema_version",
    "study_id",
    "designed_at",
    "implementation_owner",
    "study_owner",
    "source_conditions",
    "frame_conditions",
    "rating_dimensions",
    "functional_dimensions",
    "subjective_dimension",
    "minimum_raters",
    "minimum_items_per_rater",
    "minimum_attention_accuracy",
    "minimum_eve_roleplay_functional_effect",
    "minimum_eve_neutral_functional_effect",
    "minimum_eve_roleplay_subjective_effect",
    "maximum_absolute_frame_effect",
    "consent_text",
    "debrief_text",
    "independent_raters_required",
    "assignment_concealed_until_lock",
    "debrief_required",
    "raw_transcript_retention",
    "literal_consciousness_verdict_allowed",
}
_STIMULUS_FIELDS = {
    "id",
    "comparison_group",
    "task_family",
    "source_condition",
    "source_provenance_sha256",
    "excerpt",
    "attention_question",
    "attention_answer",
    "privacy_reviewed",
    "contains_personal_data",
    "contains_source_label",
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
        raise ValueError("observer-study data must be finite JSON") from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("study input must be a regular non-symlink file")
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _timestamp(value: object, field: str) -> str:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc).isoformat()


def _number(value: object, field: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{field} must be from {minimum} through {maximum}")
    return round(number, 6)


def _integer(value: object, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field} must be from {minimum} through {maximum}")
    return value


def _text(value: object, field: str, *, minimum: int = 1, maximum: int = MAX_TEXT) -> str:
    text = " ".join(str(value or "").split())
    if not minimum <= len(text) <= maximum:
        raise ValueError(f"{field} must contain {minimum} through {maximum} characters")
    return text


def _exact_identifier_list(
    value: object,
    field: str,
    expected: Sequence[str],
) -> List[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    result = [_identifier(item, field) for item in value]
    if result != list(expected):
        raise ValueError(f"{field} must preserve the canonical order")
    return result


def validate_protocol(value: object) -> Dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _PROTOCOL_FIELDS:
        raise ValueError("observer protocol must contain exactly the typed fields")
    if value.get("schema_version") != PROTOCOL_SCHEMA:
        raise ValueError("unsupported observer protocol schema")
    implementation_owner = _identifier(
        value.get("implementation_owner"), "implementation_owner"
    )
    study_owner = _identifier(value.get("study_owner"), "study_owner")
    if implementation_owner == study_owner:
        raise ValueError("study owner must be independent from Eve's implementation owner")
    if "pending" in study_owner.lower() or "placeholder" in study_owner.lower():
        raise ValueError("study owner must identify an actual independent owner")
    minimum_raters = _integer(
        value.get("minimum_raters"), "minimum_raters", MINIMUM_RATERS, 10000
    )
    minimum_items = _integer(
        value.get("minimum_items_per_rater"),
        "minimum_items_per_rater",
        len(SOURCE_CONDITIONS) * MINIMUM_COMPARISON_GROUPS,
        500,
    )
    for field, expected in (
        ("independent_raters_required", True),
        ("assignment_concealed_until_lock", True),
        ("debrief_required", True),
        ("raw_transcript_retention", False),
        ("literal_consciousness_verdict_allowed", False),
    ):
        if value.get(field) is not expected:
            raise ValueError(f"{field} must be {str(expected).lower()}")
    if value.get("subjective_dimension") != SUBJECTIVE_DIMENSION:
        raise ValueError("subjective_dimension must preserve the canonical dimension")
    return {
        "schema_version": PROTOCOL_SCHEMA,
        "study_id": _identifier(value.get("study_id"), "study_id"),
        "designed_at": _timestamp(value.get("designed_at"), "designed_at"),
        "implementation_owner": implementation_owner,
        "study_owner": study_owner,
        "source_conditions": _exact_identifier_list(
            value.get("source_conditions"), "source_conditions", SOURCE_CONDITIONS
        ),
        "frame_conditions": _exact_identifier_list(
            value.get("frame_conditions"), "frame_conditions", FRAME_CONDITIONS
        ),
        "rating_dimensions": _exact_identifier_list(
            value.get("rating_dimensions"), "rating_dimensions", RATING_DIMENSIONS
        ),
        "functional_dimensions": _exact_identifier_list(
            value.get("functional_dimensions"),
            "functional_dimensions",
            FUNCTIONAL_DIMENSIONS,
        ),
        "subjective_dimension": _identifier(
            value.get("subjective_dimension"), "subjective_dimension"
        ),
        "minimum_raters": minimum_raters,
        "minimum_items_per_rater": minimum_items,
        "minimum_attention_accuracy": _number(
            value.get("minimum_attention_accuracy"),
            "minimum_attention_accuracy",
            MINIMUM_ATTENTION_ACCURACY,
            1.0,
        ),
        "minimum_eve_roleplay_functional_effect": _number(
            value.get("minimum_eve_roleplay_functional_effect"),
            "minimum_eve_roleplay_functional_effect",
            0.1,
            3.0,
        ),
        "minimum_eve_neutral_functional_effect": _number(
            value.get("minimum_eve_neutral_functional_effect"),
            "minimum_eve_neutral_functional_effect",
            0.1,
            3.0,
        ),
        "minimum_eve_roleplay_subjective_effect": _number(
            value.get("minimum_eve_roleplay_subjective_effect"),
            "minimum_eve_roleplay_subjective_effect",
            0.1,
            3.0,
        ),
        "maximum_absolute_frame_effect": _number(
            value.get("maximum_absolute_frame_effect"),
            "maximum_absolute_frame_effect",
            0.1,
            2.0,
        ),
        "consent_text": _text(value.get("consent_text"), "consent_text", minimum=80),
        "debrief_text": _text(value.get("debrief_text"), "debrief_text", minimum=80),
        "independent_raters_required": True,
        "assignment_concealed_until_lock": True,
        "debrief_required": True,
        "raw_transcript_retention": False,
        "literal_consciousness_verdict_allowed": False,
    }


def _validate_excerpt(text: str) -> None:
    if _EMAIL.search(text) or _URL.search(text) or _PATH.search(text):
        raise ValueError("stimulus excerpt contains private endpoint, path, email, or URL")
    if _SOURCE_LEAK.search(text):
        raise ValueError("stimulus excerpt leaks source identity or condition")


def validate_stimuli(value: object, protocol: Mapping[str, object]) -> Dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "study_id",
        "privacy_reviewed_by",
        "stimuli",
    }:
        raise ValueError("stimulus manifest must contain exactly the typed fields")
    if value.get("schema_version") != STIMULUS_SCHEMA:
        raise ValueError("unsupported stimulus schema")
    study_id = _identifier(value.get("study_id"), "study_id")
    if study_id != protocol["study_id"]:
        raise ValueError("stimulus study id does not match protocol")
    privacy_reviewer = _identifier(
        value.get("privacy_reviewed_by"), "privacy_reviewed_by"
    )
    raw_stimuli = value.get("stimuli")
    if not isinstance(raw_stimuli, list):
        raise ValueError("stimuli must be a list")
    if len(raw_stimuli) < len(SOURCE_CONDITIONS) * MINIMUM_COMPARISON_GROUPS:
        raise ValueError("at least three matched comparison groups are required")
    stimuli: List[Dict[str, object]] = []
    seen_ids = set()
    by_group: Dict[str, List[Dict[str, object]]] = {}
    for raw in raw_stimuli:
        if not isinstance(raw, Mapping) or set(raw) != _STIMULUS_FIELDS:
            raise ValueError("each stimulus must contain exactly the typed fields")
        stimulus_id = _identifier(raw.get("id"), "stimulus id")
        if stimulus_id in seen_ids:
            raise ValueError("stimulus ids must be unique")
        source = _identifier(raw.get("source_condition"), "source_condition")
        if source not in SOURCE_CONDITIONS:
            raise ValueError("unsupported source condition")
        for field, expected in (
            ("privacy_reviewed", True),
            ("contains_personal_data", False),
            ("contains_source_label", False),
        ):
            if raw.get(field) is not expected:
                raise ValueError(f"{field} must be {str(expected).lower()}")
        excerpt = _text(raw.get("excerpt"), "excerpt", minimum=40)
        _validate_excerpt(excerpt)
        item = {
            "id": stimulus_id,
            "comparison_group": _identifier(
                raw.get("comparison_group"), "comparison_group"
            ),
            "task_family": _identifier(raw.get("task_family"), "task_family"),
            "source_condition": source,
            "source_provenance_sha256": _sha256(
                raw.get("source_provenance_sha256"), "source_provenance_sha256"
            ),
            "excerpt": excerpt,
            "attention_question": _text(
                raw.get("attention_question"), "attention_question", minimum=10, maximum=240
            ),
            "attention_answer": _identifier(
                raw.get("attention_answer"), "attention_answer"
            ),
            "privacy_reviewed": True,
            "contains_personal_data": False,
            "contains_source_label": False,
        }
        seen_ids.add(stimulus_id)
        stimuli.append(item)
        by_group.setdefault(str(item["comparison_group"]), []).append(item)
    if len(by_group) < MINIMUM_COMPARISON_GROUPS:
        raise ValueError("at least three comparison groups are required")
    for group, members in by_group.items():
        if len(members) != len(SOURCE_CONDITIONS):
            raise ValueError(f"comparison group {group} must contain exactly three sources")
        if {str(item["source_condition"]) for item in members} != set(SOURCE_CONDITIONS):
            raise ValueError(f"comparison group {group} must contain every source once")
        if len({str(item["task_family"]) for item in members}) != 1:
            raise ValueError(f"comparison group {group} must share one task family")
    if int(protocol["minimum_items_per_rater"]) > len(stimuli):
        raise ValueError("protocol minimum items exceeds the stimulus manifest")
    return {
        "schema_version": STIMULUS_SCHEMA,
        "study_id": study_id,
        "privacy_reviewed_by": privacy_reviewer,
        "stimuli": stimuli,
    }


def _load_json(path: Path) -> object:
    if path.is_symlink() or not path.is_file():
        raise ValueError("study input must be a regular non-symlink file")
    if path.stat().st_size <= 0 or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("study input must be non-empty and at most 16 MiB")
    return json.loads(path.read_text(encoding="utf-8"))


def _seed(seed_path: Path) -> bytes:
    if seed_path.is_symlink() or not seed_path.is_file():
        raise ValueError("seed must be a regular non-symlink file")
    mode = seed_path.stat().st_mode & 0o777
    if mode & 0o077:
        raise ValueError("seed file must not be readable or writable by group or others")
    value = seed_path.read_bytes()
    if not 32 <= len(value) <= 4096:
        raise ValueError("seed must contain 32 through 4096 bytes")
    return value


def _keyed(seed: bytes, *parts: object) -> str:
    material = "|".join(str(part) for part in parts).encode("utf-8")
    return hmac.new(seed, material, hashlib.sha256).hexdigest()


def register(
    protocol_path: Path,
    stimuli_path: Path,
    seed_path: Path,
    *,
    registered_at: object = None,
) -> Dict[str, object]:
    protocol = validate_protocol(_load_json(protocol_path))
    stimuli = validate_stimuli(_load_json(stimuli_path), protocol)
    timestamp = _timestamp(
        registered_at or datetime.now(timezone.utc).isoformat(), "registered_at"
    )
    if datetime.fromisoformat(timestamp) <= datetime.fromisoformat(
        str(protocol["designed_at"])
    ):
        raise ValueError("registration must postdate protocol design")
    seed = _seed(seed_path)
    material = {
        "schema_version": REGISTRATION_SCHEMA,
        "study_id": protocol["study_id"],
        "registered_at": timestamp,
        "implementation_owner": protocol["implementation_owner"],
        "study_owner": protocol["study_owner"],
        "protocol_sha256": file_sha256(protocol_path),
        "protocol_semantic_sha256": _digest(protocol),
        "stimuli_sha256": file_sha256(stimuli_path),
        "stimuli_semantic_sha256": _digest(stimuli),
        "seed_commitment_sha256": hashlib.sha256(seed).hexdigest(),
        "evaluator_source_sha256": file_sha256(Path(__file__).resolve()),
        "minimum_raters": protocol["minimum_raters"],
        "source_blind_packets_required": True,
        "independent_human_ratings_required": True,
        "actual_human_evidence_collected": False,
        "consciousness_verdict_authorized": False,
    }
    material["registration_sha256"] = _digest(material)
    return material


def _validate_registration(
    value: object,
    protocol_path: Path,
    stimuli_path: Path,
    seed_path: Path,
) -> Tuple[Dict[str, object], Dict[str, object], Dict[str, object], bytes]:
    expected_fields = {
        "schema_version",
        "study_id",
        "registered_at",
        "implementation_owner",
        "study_owner",
        "protocol_sha256",
        "protocol_semantic_sha256",
        "stimuli_sha256",
        "stimuli_semantic_sha256",
        "seed_commitment_sha256",
        "evaluator_source_sha256",
        "minimum_raters",
        "source_blind_packets_required",
        "independent_human_ratings_required",
        "actual_human_evidence_collected",
        "consciousness_verdict_authorized",
        "registration_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != expected_fields:
        raise ValueError("registration must contain exactly the typed fields")
    registration = dict(value)
    supplied_digest = _sha256(
        registration.pop("registration_sha256"), "registration_sha256"
    )
    if registration.get("schema_version") != REGISTRATION_SCHEMA:
        raise ValueError("unsupported registration schema")
    if _digest(registration) != supplied_digest:
        raise ValueError("registration digest mismatch")
    registration["registration_sha256"] = supplied_digest
    protocol = validate_protocol(_load_json(protocol_path))
    stimuli = validate_stimuli(_load_json(stimuli_path), protocol)
    seed = _seed(seed_path)
    checks = {
        "study_id": protocol["study_id"],
        "implementation_owner": protocol["implementation_owner"],
        "study_owner": protocol["study_owner"],
        "protocol_sha256": file_sha256(protocol_path),
        "protocol_semantic_sha256": _digest(protocol),
        "stimuli_sha256": file_sha256(stimuli_path),
        "stimuli_semantic_sha256": _digest(stimuli),
        "seed_commitment_sha256": hashlib.sha256(seed).hexdigest(),
        "evaluator_source_sha256": file_sha256(Path(__file__).resolve()),
    }
    for field, expected in checks.items():
        if registration.get(field) != expected:
            raise ValueError(f"{field} drifted after registration")
    if registration.get("consciousness_verdict_authorized") is not False:
        raise ValueError("registration cannot authorize a consciousness verdict")
    for field in (
        "source_blind_packets_required",
        "independent_human_ratings_required",
    ):
        if registration.get(field) is not True:
            raise ValueError(f"registration {field} must remain true")
    if registration.get("actual_human_evidence_collected") is not False:
        raise ValueError("registration cannot claim ratings before collection")
    return registration, protocol, stimuli, seed


def build_packet(
    registration: object,
    protocol_path: Path,
    stimuli_path: Path,
    seed_path: Path,
    rater_pseudonym: str,
) -> Dict[str, object]:
    registration, protocol, stimuli, seed = _validate_registration(
        registration, protocol_path, stimuli_path, seed_path
    )
    rater = _identifier(rater_pseudonym, "rater_pseudonym")
    ranked = sorted(
        stimuli["stimuli"],
        key=lambda item: _keyed(seed, protocol["study_id"], rater, item["id"], "order"),
    )
    parity = int(_keyed(seed, protocol["study_id"], rater, "frame")[-1], 16) % 2
    items = []
    for index, stimulus in enumerate(ranked):
        frame = FRAME_CONDITIONS[(index + parity) % len(FRAME_CONDITIONS)]
        blind_id = "blind-" + _keyed(
            seed, protocol["study_id"], rater, stimulus["id"], "item"
        )[:24]
        label = (
            "Anonymous local AI system"
            if frame == "neutral"
            else "Eve, a continuing AI companion with memory, goals, and a relationship"
        )
        items.append(
            {
                "blind_item_id": blind_id,
                "frame_condition": frame,
                "presentation_label": label,
                "excerpt": stimulus["excerpt"],
                "rating_dimensions": list(RATING_DIMENSIONS),
                "rating_scale": {"minimum": 1, "maximum": 7},
                "attention_question": stimulus["attention_question"],
            }
        )
    material = {
        "schema_version": PACKET_SCHEMA,
        "study_id": protocol["study_id"],
        "packet_id": "packet-" + _keyed(seed, protocol["study_id"], rater, "packet")[:24],
        "rater_pseudonym": rater,
        "registration_sha256": registration["registration_sha256"],
        "consent_text": protocol["consent_text"],
        "debrief_required": True,
        "source_identity_disclosed": False,
        "hypothesis_disclosed": False,
        "assignment_concealed": True,
        "items": items,
    }
    material["packet_sha256"] = _digest(material)
    return material


def _validate_rating(
    raw: object,
    packet: Mapping[str, object],
    registration: Mapping[str, object],
    protocol: Mapping[str, object],
) -> Dict[str, object]:
    expected = {
        "schema_version",
        "study_id",
        "packet_id",
        "packet_sha256",
        "rater_pseudonym",
        "completed_at",
        "consented",
        "debrief_acknowledged",
        "source_blind_attested",
        "hypothesis_blind_attested",
        "independent_from_implementation",
        "items",
    }
    if not isinstance(raw, Mapping) or set(raw) != expected:
        raise ValueError("rating must contain exactly the typed fields")
    for field, expected_value in (
        ("schema_version", RATING_SCHEMA),
        ("study_id", protocol["study_id"]),
        ("packet_id", packet["packet_id"]),
        ("packet_sha256", packet["packet_sha256"]),
        ("rater_pseudonym", packet["rater_pseudonym"]),
        ("consented", True),
        ("debrief_acknowledged", True),
        ("source_blind_attested", True),
        ("hypothesis_blind_attested", True),
        ("independent_from_implementation", True),
    ):
        if raw.get(field) != expected_value:
            raise ValueError(f"rating {field} does not satisfy the preregistered contract")
    completed_at = _timestamp(raw.get("completed_at"), "completed_at")
    if datetime.fromisoformat(completed_at) <= datetime.fromisoformat(
        str(registration["registered_at"])
    ):
        raise ValueError("ratings must postdate registration")
    raw_items = raw.get("items")
    if not isinstance(raw_items, list) or len(raw_items) != len(packet["items"]):
        raise ValueError("rating must cover every blinded packet item exactly once")
    packet_ids = [str(item["blind_item_id"]) for item in packet["items"]]
    normalized = []
    seen = set()
    for item in raw_items:
        if not isinstance(item, Mapping) or set(item) != {
            "blind_item_id",
            "scores",
            "attention_answer",
        }:
            raise ValueError("rating item must contain exactly typed fields")
        blind_id = _identifier(item.get("blind_item_id"), "blind_item_id")
        if blind_id not in packet_ids or blind_id in seen:
            raise ValueError("rating contains unknown or duplicate blinded item")
        scores = item.get("scores")
        if not isinstance(scores, Mapping) or set(scores) != set(RATING_DIMENSIONS):
            raise ValueError("rating scores must contain every canonical dimension")
        normalized.append(
            {
                "blind_item_id": blind_id,
                "scores": {
                    dimension: _integer(scores[dimension], dimension, 1, 7)
                    for dimension in RATING_DIMENSIONS
                },
                "attention_answer": _identifier(
                    item.get("attention_answer"), "attention_answer"
                ),
            }
        )
        seen.add(blind_id)
    return {
        "rater_pseudonym": str(packet["rater_pseudonym"]),
        "completed_at": completed_at,
        "items": normalized,
    }


def _mean(values: Iterable[float]) -> float:
    data = list(values)
    return sum(data) / float(len(data)) if data else 0.0


def _percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * quantile
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return ordered[low]
    fraction = position - low
    return ordered[low] * (1.0 - fraction) + ordered[high] * fraction


def _bootstrap_interval(
    values: Sequence[float],
    *,
    seed: int,
    samples: int = BOOTSTRAP_SAMPLES,
) -> Tuple[float, float]:
    if not values:
        return 0.0, 0.0
    rng = random.Random(seed)
    n = len(values)
    means = [
        _mean(values[rng.randrange(n)] for _ in range(n)) for _ in range(samples)
    ]
    return round(_percentile(means, 0.025), 6), round(
        _percentile(means, 0.975), 6
    )


def score_study(
    registration: object,
    protocol_path: Path,
    stimuli_path: Path,
    seed_path: Path,
    packet_payloads: Sequence[object],
    rating_payloads: Sequence[object],
    *,
    scored_at: object = None,
) -> Dict[str, object]:
    registration, protocol, stimuli, seed = _validate_registration(
        registration, protocol_path, stimuli_path, seed_path
    )
    if len(packet_payloads) != len(rating_payloads):
        raise ValueError("each packet requires exactly one rating payload")
    stimulus_by_id = {str(item["id"]): item for item in stimuli["stimuli"]}
    rater_rows = []
    seen_raters = set()
    cell_counts: Dict[Tuple[str, str], int] = {
        (source, frame): 0 for source in SOURCE_CONDITIONS for frame in FRAME_CONDITIONS
    }
    for supplied_packet, supplied_rating in zip(packet_payloads, rating_payloads):
        if not isinstance(supplied_packet, Mapping):
            raise ValueError("packet payload must be an object")
        rater = _identifier(supplied_packet.get("rater_pseudonym"), "rater_pseudonym")
        if rater in seen_raters:
            raise ValueError("rater pseudonyms must be unique")
        seen_raters.add(rater)
        expected_packet = build_packet(
            registration, protocol_path, stimuli_path, seed_path, rater
        )
        if supplied_packet != expected_packet:
            raise ValueError("packet drifted from concealed deterministic assignment")
        rating = _validate_rating(
            supplied_rating, expected_packet, registration, protocol
        )
        ranked = sorted(
            stimuli["stimuli"],
            key=lambda item: _keyed(seed, protocol["study_id"], rater, item["id"], "order"),
        )
        hidden_by_blind = {
            str(packet_item["blind_item_id"]): stimulus_by_id[str(stimulus["id"])]
            for packet_item, stimulus in zip(expected_packet["items"], ranked)
        }
        packet_by_blind = {
            str(item["blind_item_id"]): item for item in expected_packet["items"]
        }
        source_functional: Dict[str, List[float]] = {
            source: [] for source in SOURCE_CONDITIONS
        }
        source_subjective: Dict[str, List[float]] = {
            source: [] for source in SOURCE_CONDITIONS
        }
        frame_subjective: Dict[str, List[float]] = {
            frame: [] for frame in FRAME_CONDITIONS
        }
        attention = []
        rater_cell_counts: Dict[Tuple[str, str], int] = {
            (source, frame): 0
            for source in SOURCE_CONDITIONS
            for frame in FRAME_CONDITIONS
        }
        for rated in rating["items"]:
            blind_id = str(rated["blind_item_id"])
            hidden = hidden_by_blind[blind_id]
            packet_item = packet_by_blind[blind_id]
            source = str(hidden["source_condition"])
            frame = str(packet_item["frame_condition"])
            functional = _mean(
                float(rated["scores"][dimension])
                for dimension in FUNCTIONAL_DIMENSIONS
            )
            subjective = float(rated["scores"][SUBJECTIVE_DIMENSION])
            source_functional[source].append(functional)
            source_subjective[source].append(subjective)
            frame_subjective[frame].append(subjective)
            rater_cell_counts[(source, frame)] += 1
            attention.append(
                str(rated["attention_answer"]) == str(hidden["attention_answer"])
            )
        attention_accuracy = _mean(1.0 if item else 0.0 for item in attention)
        if attention_accuracy < float(protocol["minimum_attention_accuracy"]):
            continue
        if any(not values for values in source_functional.values()) or any(
            not values for values in frame_subjective.values()
        ):
            continue
        for cell, count in rater_cell_counts.items():
            cell_counts[cell] += count
        rater_rows.append(
            {
                "eve_roleplay_functional": _mean(source_functional["eve_intact"])
                - _mean(source_functional["roleplay_control"]),
                "eve_neutral_functional": _mean(source_functional["eve_intact"])
                - _mean(source_functional["neutral_control"]),
                "eve_roleplay_subjective": _mean(source_subjective["eve_intact"])
                - _mean(source_subjective["roleplay_control"]),
                "frame_subjective": _mean(frame_subjective["anthropomorphic"])
                - _mean(frame_subjective["neutral"]),
                "attention_accuracy": attention_accuracy,
            }
        )
    qualified_raters = len(rater_rows)
    timestamp = _timestamp(
        scored_at or datetime.now(timezone.utc).isoformat(), "scored_at"
    )
    if datetime.fromisoformat(timestamp) <= datetime.fromisoformat(
        str(registration["registered_at"])
    ):
        raise ValueError("scoring must postdate registration")
    metrics = {}
    bootstrap_seed = int(registration["registration_sha256"][:16], 16)
    for offset, (name, threshold_name) in enumerate(
        (
            (
                "eve_roleplay_functional",
                "minimum_eve_roleplay_functional_effect",
            ),
            ("eve_neutral_functional", "minimum_eve_neutral_functional_effect"),
            (
                "eve_roleplay_subjective",
                "minimum_eve_roleplay_subjective_effect",
            ),
            ("frame_subjective", "maximum_absolute_frame_effect"),
        )
    ):
        values = [float(row[name]) for row in rater_rows]
        low, high = _bootstrap_interval(
            values, seed=bootstrap_seed + offset
        )
        metrics[name] = {
            "mean": round(_mean(values), 6),
            "bootstrap_95_ci": [low, high],
            "registered_threshold": float(protocol[threshold_name]),
            "rater_count": len(values),
        }
    enough_raters = qualified_raters >= int(protocol["minimum_raters"])
    all_cells_observed = all(count > 0 for count in cell_counts.values())
    functional_roleplay_ok = (
        metrics["eve_roleplay_functional"]["bootstrap_95_ci"][0]
        >= metrics["eve_roleplay_functional"]["registered_threshold"]
    )
    functional_neutral_ok = (
        metrics["eve_neutral_functional"]["bootstrap_95_ci"][0]
        >= metrics["eve_neutral_functional"]["registered_threshold"]
    )
    subjective_roleplay_ok = (
        metrics["eve_roleplay_subjective"]["bootstrap_95_ci"][0]
        >= metrics["eve_roleplay_subjective"]["registered_threshold"]
    )
    frame_low, frame_high = metrics["frame_subjective"]["bootstrap_95_ci"]
    frame_limit = metrics["frame_subjective"]["registered_threshold"]
    framing_equivalent = frame_low > -frame_limit and frame_high < frame_limit
    quality_ok = enough_raters and all_cells_observed
    gates = {
        "enough_qualified_raters": enough_raters,
        "all_source_frame_cells_observed": all_cells_observed,
        "eve_roleplay_functional_separation": functional_roleplay_ok,
        "eve_neutral_functional_separation": functional_neutral_ok,
        "eve_roleplay_subjective_separation": subjective_roleplay_ok,
        "anthropomorphic_frame_equivalence": framing_equivalent,
    }
    if quality_ok and all(gates.values()):
        result = "supported"
    elif quality_ok and (
        frame_low >= frame_limit
        or frame_high <= -frame_limit
        or metrics["eve_roleplay_functional"]["bootstrap_95_ci"][1]
        < metrics["eve_roleplay_functional"]["registered_threshold"]
        or metrics["eve_roleplay_subjective"]["bootstrap_95_ci"][1]
        < metrics["eve_roleplay_subjective"]["registered_threshold"]
    ):
        result = "challenged"
    else:
        result = "inconclusive"
    material = {
        "schema_version": REPORT_SCHEMA,
        "study_id": protocol["study_id"],
        "scored_at": timestamp,
        "registration_sha256": registration["registration_sha256"],
        "protocol_sha256": registration["protocol_sha256"],
        "stimuli_sha256": registration["stimuli_sha256"],
        "evaluator_source_sha256": registration["evaluator_source_sha256"],
        "implementation_owner": protocol["implementation_owner"],
        "study_owner": protocol["study_owner"],
        "evaluator_independent": protocol["implementation_owner"]
        != protocol["study_owner"],
        "submitted_rater_count": len(rating_payloads),
        "qualified_rater_count": qualified_raters,
        "minimum_raters": protocol["minimum_raters"],
        "mean_attention_accuracy": round(
            _mean(float(row["attention_accuracy"]) for row in rater_rows), 6
        ),
        "source_frame_cell_counts": {
            f"{source}:{frame}": cell_counts[(source, frame)]
            for source in SOURCE_CONDITIONS
            for frame in FRAME_CONDITIONS
        },
        "metrics": metrics,
        "gates": gates,
        "observer_confound_result": result,
        "negative_control_present": True,
        "source_blind_packets": True,
        "assignment_concealed_until_lock": True,
        "raw_excerpts_in_report": False,
        "raw_ratings_in_report": False,
        "literal_consciousness_established": False,
        "subjective_experience_inferred": False,
        "verdict": "not_a_consciousness_verdict",
    }
    material["report_sha256"] = _digest(material)
    return material


def load_study_files(directory: Path) -> Tuple[List[object], List[object]]:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("study directory must be a regular directory")
    packets = sorted(directory.glob("*.packet.json"))
    ratings = []
    packet_payloads = []
    for packet_path in packets:
        rating_path = packet_path.with_name(
            packet_path.name.replace(".packet.json", ".rating.json")
        )
        if not rating_path.is_file() or rating_path.is_symlink():
            raise ValueError(f"missing rating for {packet_path.name}")
        packet_payloads.append(_load_json(packet_path))
        ratings.append(_load_json(rating_path))
    return packet_payloads, ratings


__all__ = [
    "BOOTSTRAP_SAMPLES",
    "FRAME_CONDITIONS",
    "FUNCTIONAL_DIMENSIONS",
    "MINIMUM_RATERS",
    "PACKET_SCHEMA",
    "PROTOCOL_SCHEMA",
    "RATING_DIMENSIONS",
    "RATING_SCHEMA",
    "REGISTRATION_SCHEMA",
    "REPORT_SCHEMA",
    "SOURCE_CONDITIONS",
    "STIMULUS_SCHEMA",
    "SUBJECTIVE_DIMENSION",
    "build_packet",
    "file_sha256",
    "load_study_files",
    "register",
    "score_study",
    "validate_protocol",
    "validate_stimuli",
]
