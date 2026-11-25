"""Validity-centered evidence dossiers for Eve's consciousness research.

This module deliberately does not detect consciousness.  It keeps behavioral,
mechanistic, perturbational, and observer-confound evidence separate; verifies
artifact provenance; and withholds credence when evidence is missing,
conflicted, non-independent, or uncalibrated.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Dict, Iterable, List, Mapping, Optional


MANIFEST_SCHEMA = "eve.consciousness_evidence_manifest.v1"
RECORD_SCHEMA = "eve.consciousness_evidence_record.v1"
DOSSIER_SCHEMA = "eve.consciousness_evidence_dossier.v1"
REQUIRED_STREAMS = (
    "behavioral",
    "mechanistic",
    "perturbation",
    "observer_confounds",
)
INDICATOR_IDS = {
    "RPT-1",
    "RPT-2",
    "GWT-1",
    "GWT-2",
    "GWT-3",
    "GWT-4",
    "HOT-1",
    "HOT-2",
    "HOT-3",
    "HOT-4",
    "AST-1",
    "PP-1",
    "AE-1",
    "AE-2",
}
STATUSES = {"supported", "challenged", "mixed", "inconclusive"}
EVIDENCE_CLASSES = {
    "behavioral": {"black_box", "resident_behavior"},
    "mechanistic": {"source_mechanistic", "resident_mechanistic"},
    "perturbation": {"synthetic_intervention", "resident_intervention"},
    "observer_confounds": {"human_observer"},
}
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MANIFEST_FIELDS = {
    "schema_version",
    "dossier_id",
    "system_id",
    "assembled_at",
    "required_streams",
    "records",
}
_RECORD_FIELDS = {
    "schema_version",
    "evidence_id",
    "stream",
    "theory_ids",
    "indicator_ids",
    "status",
    "evidence_class",
    "observed_at",
    "artifact_path",
    "artifact_sha256",
    "protocol_path",
    "protocol_sha256",
    "evaluator_id",
    "implementation_owner",
    "evaluator_owner",
    "evaluator_independent",
    "subject_blind",
    "preregistered",
    "sample_count",
    "hard_failures",
    "negative_control",
    "effect_size",
    "minimum_effect",
    "effect_direction_correct",
    "claims",
    "limitations",
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
        raise ValueError("evidence data must be finite JSON") from exc


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


def _timestamp(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc).isoformat()


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field} must be an integer >= {minimum}")
    return value


def _optional_number(value: object, field: str) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number or null")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be a finite number or null") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number or null")
    return round(number, 9)


def _boolean(value: object, field: str, *, optional: bool = False):
    if optional and value is None:
        return None
    if not isinstance(value, bool):
        suffix = " or null" if optional else ""
        raise ValueError(f"{field} must be boolean{suffix}")
    return value


def _identifier_list(
    value: object,
    field: str,
    *,
    allowed: Optional[Iterable[str]] = None,
    allow_empty: bool = False,
) -> List[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    result = [_identifier(item, field) for item in value]
    if not allow_empty and not result:
        raise ValueError(f"{field} must not be empty")
    if len(result) != len(set(result)):
        raise ValueError(f"{field} must contain unique identifiers")
    if allowed is not None and any(item not in allowed for item in result):
        raise ValueError(f"{field} contains an unsupported identifier")
    return result


def _limitations(value: object) -> List[str]:
    if not isinstance(value, list) or not value:
        raise ValueError("limitations must be a non-empty list")
    result = []
    for item in value[:20]:
        text = str(item or "").strip()
        if not text or len(text) > 500:
            raise ValueError("each limitation must be non-empty and <= 500 characters")
        result.append(text)
    return result


def _file_digest(path_value: object, field: str) -> tuple[str, str, int]:
    text = str(path_value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    path = Path(text).expanduser()
    if path.is_symlink():
        raise ValueError(f"{field} must not be a symbolic link")
    if not path.is_file():
        raise ValueError(f"{field} must identify a regular file")
    size = path.stat().st_size
    if size <= 0 or size > MAX_ARTIFACT_BYTES:
        raise ValueError(f"{field} file must be non-empty and within the 16 MiB budget")
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return path.name, hasher.hexdigest(), size


def _qualification(record: Mapping[str, object]) -> List[str]:
    """Return reasons a positive record cannot count as robust support."""
    reasons: List[str] = []
    stream = str(record["stream"])
    if record["hard_failures"]:
        reasons.append("hard_failures_present")
    if not record["evaluator_independent"]:
        reasons.append("evaluator_not_independent")
    if record["implementation_owner"] == record["evaluator_owner"]:
        reasons.append("implementation_evaluator_owner_overlap")
    if stream == "behavioral":
        if not record["subject_blind"]:
            reasons.append("subject_not_blind_to_exact_evaluation")
        if not record["negative_control"]:
            reasons.append("behavioral_negative_control_missing")
        if record["sample_count"] < 5:
            reasons.append("fewer_than_five_behavioral_variants")
    elif stream == "perturbation":
        if not record["preregistered"]:
            reasons.append("perturbation_not_preregistered")
        if not record["negative_control"]:
            reasons.append("perturbation_negative_control_missing")
        if record["sample_count"] < 6:
            reasons.append("fewer_than_six_perturbation_samples")
        if record["effect_size"] is None or record["minimum_effect"] is None:
            reasons.append("perturbation_effect_not_quantified")
        elif record["effect_size"] < record["minimum_effect"]:
            reasons.append("perturbation_effect_below_registered_minimum")
        if record["effect_direction_correct"] is not True:
            reasons.append("perturbation_direction_not_supported")
    elif stream == "observer_confounds":
        if not record["subject_blind"]:
            reasons.append("observer_study_not_blinded")
        if not record["negative_control"]:
            reasons.append("observer_negative_control_missing")
        if record["sample_count"] < 5:
            reasons.append("fewer_than_five_observer_ratings")
    return sorted(set(reasons))


def _challenge_qualification(record: Mapping[str, object]) -> List[str]:
    """Return provenance gaps that make a negative result only provisional."""
    reasons: List[str] = []
    stream = str(record["stream"])
    if not record["evaluator_independent"]:
        reasons.append("challenge_evaluator_not_independent")
    if record["implementation_owner"] == record["evaluator_owner"]:
        reasons.append("challenge_owner_overlap")
    if stream in {"behavioral", "observer_confounds"} and not record["subject_blind"]:
        reasons.append("challenge_not_blinded")
    if stream == "perturbation" and not record["preregistered"]:
        reasons.append("challenge_perturbation_not_preregistered")
    return sorted(set(reasons))


def _validate_record(
    raw: object,
    *,
    assembled_at: str,
) -> Dict[str, object]:
    if not isinstance(raw, Mapping) or set(raw) != _RECORD_FIELDS:
        raise ValueError("each evidence record must contain exactly the typed fields")
    if raw.get("schema_version") != RECORD_SCHEMA:
        raise ValueError("unsupported evidence record schema")
    stream = _identifier(raw.get("stream"), "stream")
    if stream not in REQUIRED_STREAMS:
        raise ValueError("evidence stream is not admitted")
    status = _identifier(raw.get("status"), "status")
    if status not in STATUSES:
        raise ValueError("unsupported evidence status")
    evidence_class = _identifier(raw.get("evidence_class"), "evidence_class")
    if evidence_class not in EVIDENCE_CLASSES[stream]:
        raise ValueError("evidence class is incompatible with its stream")
    observed_at = _timestamp(raw.get("observed_at"), "observed_at")
    if datetime.fromisoformat(observed_at) > datetime.fromisoformat(assembled_at):
        raise ValueError("evidence cannot postdate dossier assembly")
    artifact_name, observed_digest, artifact_bytes = _file_digest(
        raw.get("artifact_path"), "artifact_path"
    )
    supplied_digest = _sha256(raw.get("artifact_sha256"), "artifact_sha256")
    if observed_digest != supplied_digest:
        raise ValueError("artifact SHA-256 does not match the supplied evidence")
    protocol_name, observed_protocol_digest, protocol_bytes = _file_digest(
        raw.get("protocol_path"), "protocol_path"
    )
    supplied_protocol_digest = _sha256(
        raw.get("protocol_sha256"), "protocol_sha256"
    )
    if observed_protocol_digest != supplied_protocol_digest:
        raise ValueError("protocol SHA-256 does not match the supplied evidence")
    if supplied_digest == supplied_protocol_digest:
        raise ValueError("artifact and protocol must be separately bound files")
    implementation_owner = _identifier(
        raw.get("implementation_owner"), "implementation_owner"
    )
    evaluator_owner = _identifier(raw.get("evaluator_owner"), "evaluator_owner")
    evaluator_independent = _boolean(
        raw.get("evaluator_independent"), "evaluator_independent"
    )
    if evaluator_independent and implementation_owner == evaluator_owner:
        raise ValueError("independent evaluator cannot share the implementation owner")
    effect_size = _optional_number(raw.get("effect_size"), "effect_size")
    minimum_effect = _optional_number(raw.get("minimum_effect"), "minimum_effect")
    if minimum_effect is not None and minimum_effect < 0:
        raise ValueError("minimum_effect must be non-negative")
    record = {
        "schema_version": RECORD_SCHEMA,
        "evidence_id": _identifier(raw.get("evidence_id"), "evidence_id"),
        "stream": stream,
        "theory_ids": _identifier_list(raw.get("theory_ids"), "theory_ids"),
        "indicator_ids": _identifier_list(
            raw.get("indicator_ids"),
            "indicator_ids",
            allowed=INDICATOR_IDS,
            allow_empty=True,
        ),
        "status": status,
        "evidence_class": evidence_class,
        "observed_at": observed_at,
        "artifact_name": artifact_name,
        "artifact_sha256": supplied_digest,
        "artifact_bytes": artifact_bytes,
        "protocol_name": protocol_name,
        "protocol_sha256": supplied_protocol_digest,
        "protocol_bytes": protocol_bytes,
        "evaluator_id": _identifier(raw.get("evaluator_id"), "evaluator_id"),
        "implementation_owner": implementation_owner,
        "evaluator_owner": evaluator_owner,
        "evaluator_independent": evaluator_independent,
        "subject_blind": _boolean(raw.get("subject_blind"), "subject_blind"),
        "preregistered": _boolean(raw.get("preregistered"), "preregistered"),
        "sample_count": _integer(raw.get("sample_count"), "sample_count", minimum=1),
        "hard_failures": _integer(raw.get("hard_failures"), "hard_failures"),
        "negative_control": _boolean(raw.get("negative_control"), "negative_control"),
        "effect_size": effect_size,
        "minimum_effect": minimum_effect,
        "effect_direction_correct": _boolean(
            raw.get("effect_direction_correct"),
            "effect_direction_correct",
            optional=True,
        ),
        "claims": _identifier_list(raw.get("claims"), "claims"),
        "limitations": _limitations(raw.get("limitations")),
    }
    record["qualification_failures"] = _qualification(record) if status == "supported" else []
    record["challenge_qualification_failures"] = (
        _challenge_qualification(record) if status == "challenged" else []
    )
    record["qualified_support"] = (
        status == "supported" and not record["qualification_failures"]
    )
    record["qualified_challenge"] = (
        status == "challenged" and not record["challenge_qualification_failures"]
    )
    return record


def _stream_summary(stream: str, records: List[Mapping[str, object]]) -> Dict[str, object]:
    if not records:
        return {
            "stream": stream,
            "status": "missing",
            "record_count": 0,
            "qualified_support_count": 0,
            "challenged_count": 0,
            "provisional_challenge_count": 0,
            "hard_failure_count": 0,
            "evidence_ids": [],
            "qualification_failures": [],
        }
    supported = [item for item in records if item["qualified_support"]]
    challenged = [item for item in records if item["qualified_challenge"]]
    mixed = [item for item in records if item["status"] == "mixed"]
    unqualified = [
        item
        for item in records
        if item["status"] == "supported" and not item["qualified_support"]
    ]
    unqualified_challenges = [
        item
        for item in records
        if item["status"] == "challenged" and not item["qualified_challenge"]
    ]
    if challenged and supported:
        status = "mixed"
    elif challenged:
        status = "challenged"
    elif mixed:
        status = "mixed"
    elif supported:
        status = "supported"
    elif unqualified or unqualified_challenges:
        status = "provisional"
    else:
        status = "inconclusive"
    failures = sorted(
        {
            reason
            for item in [*unqualified, *unqualified_challenges]
            for reason in [
                *item["qualification_failures"],
                *item["challenge_qualification_failures"],
            ]
        }
    )
    return {
        "stream": stream,
        "status": status,
        "record_count": len(records),
        "qualified_support_count": len(supported),
        "challenged_count": len(challenged),
        "provisional_challenge_count": len(unqualified_challenges),
        "hard_failure_count": sum(int(item["hard_failures"]) for item in records),
        "evidence_ids": [str(item["evidence_id"]) for item in records],
        "qualification_failures": failures,
    }


def _overlap_groups(records: List[Mapping[str, object]]) -> List[Dict[str, object]]:
    groups: List[Dict[str, object]] = []
    for field in ("artifact_sha256", "protocol_sha256", "evaluator_owner"):
        by_value: Dict[str, List[Mapping[str, object]]] = defaultdict(list)
        for record in records:
            by_value[str(record[field])].append(record)
        for value, members in sorted(by_value.items()):
            streams = sorted({str(item["stream"]) for item in members})
            if len(streams) < 2:
                continue
            groups.append(
                {
                    "field": field,
                    "value": value,
                    "streams": streams,
                    "evidence_ids": sorted(str(item["evidence_id"]) for item in members),
                }
            )
    return groups


def build_dossier(manifest: Mapping[str, object]) -> Dict[str, object]:
    """Validate evidence and return a non-binary, non-probabilistic dossier."""
    if not isinstance(manifest, Mapping) or set(manifest) != _MANIFEST_FIELDS:
        raise ValueError("manifest must contain exactly the typed dossier fields")
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise ValueError("unsupported consciousness evidence manifest schema")
    assembled_at = _timestamp(manifest.get("assembled_at"), "assembled_at")
    required = _identifier_list(
        manifest.get("required_streams"),
        "required_streams",
        allowed=REQUIRED_STREAMS,
    )
    if required != list(REQUIRED_STREAMS):
        raise ValueError("required_streams must preserve all four canonical streams")
    raw_records = manifest.get("records")
    if not isinstance(raw_records, list):
        raise ValueError("records must be a list")
    records = [
        _validate_record(raw, assembled_at=assembled_at) for raw in raw_records
    ]
    evidence_ids = [str(record["evidence_id"]) for record in records]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("evidence ids must be unique")
    by_stream = {
        stream: [record for record in records if record["stream"] == stream]
        for stream in REQUIRED_STREAMS
    }
    stream_summaries = [
        _stream_summary(stream, by_stream[stream]) for stream in REQUIRED_STREAMS
    ]
    statuses = {item["stream"]: item["status"] for item in stream_summaries}
    missing = [stream for stream, status in statuses.items() if status == "missing"]
    challenged = [
        stream for stream, status in statuses.items() if status in {"challenged", "mixed"}
    ]
    all_supported = all(status == "supported" for status in statuses.values())
    overlaps = _overlap_groups(records)
    independent_owners = sorted(
        {
            str(record["evaluator_owner"])
            for record in records
            if record["qualified_support"]
        }
    )
    overlap_fields = {str(item["field"]) for item in overlaps}
    if missing:
        triangulation_status = "incomplete_required_streams"
    elif challenged:
        triangulation_status = "challenged_or_mixed_evidence"
    elif not all_supported:
        triangulation_status = "provisional_or_inconclusive_evidence"
    elif {"artifact_sha256", "protocol_sha256"} & overlap_fields:
        triangulation_status = "supported_across_streams_with_shared_evidence"
    elif "evaluator_owner" in overlap_fields or len(independent_owners) < len(
        REQUIRED_STREAMS
    ):
        triangulation_status = "supported_across_streams_with_evaluator_overlap"
    else:
        triangulation_status = "independently_functionally_supported_across_streams"
    if missing:
        credence_reason = "required_evidence_streams_missing"
    elif statuses["observer_confounds"] != "supported":
        credence_reason = "observer_confounds_not_qualified"
    elif not all_supported:
        credence_reason = "required_streams_not_convergently_supported"
    else:
        credence_reason = "artificial_phenomenality_has_no_validated_ground_truth_calibration"
    public_records = []
    for record in records:
        public_records.append(
            {
                key: value
                for key, value in record.items()
                if key
                not in {
                    # Paths are never retained; artifact name and digest are enough.
                    "artifact_path",
                }
            }
        )
    material = {
        "schema_version": DOSSIER_SCHEMA,
        "dossier_id": _identifier(manifest.get("dossier_id"), "dossier_id"),
        "system_id": _identifier(manifest.get("system_id"), "system_id"),
        "assembled_at": assembled_at,
        "required_streams": list(REQUIRED_STREAMS),
        "stream_summaries": stream_summaries,
        "records": public_records,
        "cross_stream_overlap": overlaps,
        "independent_qualified_evaluator_owners": independent_owners,
        "missing_streams": missing,
        "challenged_or_mixed_streams": challenged,
        "triangulation_status": triangulation_status,
        "credence_band_status": "withheld",
        "credence_withheld_reason": credence_reason,
        "scalar_consciousness_score_emitted": False,
        "binary_consciousness_detection_allowed": False,
        "subjective_experience_inferred": False,
        "literal_consciousness_established": False,
        "private_artifact_content_copied": False,
        "boundary": (
            "This dossier audits functional evidence and validity threats. "
            "It cannot detect, quantify, or prove subjective consciousness."
        ),
    }
    material["dossier_sha256"] = _digest(material)
    return material
