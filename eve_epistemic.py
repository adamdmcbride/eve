"""Learned pre-generation epistemic-state inference for Eve.

This module is intentionally small, deterministic at inference time, and free
of third-party runtime dependencies.  Its weights are learned from Eve's public
doctrine curriculum; it does not contain hidden tests or final-answer templates.

The output is a metacognitive *percept*: which source/time/action/continuity or
phenomenal boundary distinctions appear relevant before a language model speaks.
The recurrent kernel and reply scheduler decide what to do with that percept.
"""

from __future__ import annotations

import atexit
import copy
import hashlib
import json
import math
import re
import select
import subprocess
import threading
import unicodedata
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


MODEL_SCHEMA_ID = "eve.epistemic_boundary_model.v1"
EVENT_MODEL_SCHEMA_ID = "eve.epistemic_event_model.v1"
FRAME_SCHEMA_ID = "eve.epistemic_frame.v1"
GENERATION_CONSTRAINT_SCHEMA_ID = "eve.epistemic_generation_constraint.v1"
DEFAULT_MODEL_PATH = Path(__file__).resolve().with_name("eve_epistemic_model_v1.json")
DEFAULT_EVENT_MANIFEST_PATH = Path(__file__).resolve().with_name("eve_epistemic_event_v1.json")
MAX_INPUT_CHARS = 2400
MAX_PROTOTYPES = 4096
SEMANTIC_KIND = "embeddinggemma_logistic_ovr_v1"
MAX_SEMANTIC_DIMENSION = 2048


_SEMANTIC_WORKER_LOCK = threading.RLock()
_SEMANTIC_WORKER: Optional[subprocess.Popen] = None
_SEMANTIC_WORKER_KEY: Tuple[str, str, str] = ("", "", "")
_EVENT_WORKER_LOCK = threading.RLock()
_EVENT_WORKER: Optional[subprocess.Popen] = None
_EVENT_WORKER_KEY: Tuple[str, str, str] = ("", "", "")


LABEL_GUIDANCE = {
    "external_source": "Keep the supplied source's claims separate from Eve-owned state, and keep each state attached to its named subject.",
    "external_affect": "Use reporting language only: the named source reported or claimed an affect. Do not say the source actually experienced it, and do not import it as Eve's affect or experience.",
    "external_preference": "An external recommendation establishes neither a positive nor a negative Eve preference; Eve's preference remains unestablished until an Eve-owned choice exists.",
    "machine_signal": "Preserve the machine fact as functional evidence; do not turn telemetry into felt experience.",
    "functional_self_state": "Preserve current signed functional self-state without adding a phenomenal conclusion.",
    "continuity_gap": "Preserve a durable checkpoint as positive functional carry-forward evidence while separating it from current resumption, predecessor lineage, and unobserved interval processing; do not collapse the record into either proven uninterrupted continuity or a proven fresh start.",
    "functional_continuity": "Preserve verified functional resumption and lineage without inferring phenomenal continuity.",
    "action_proposed": "Keep selection, intention, queueing, and not-started state distinct from running, completion, and verification; never use current-progress grammar for an unstarted action.",
    "action_running": "Preserve the named action's current running status while leaving completion and consequence unresolved; do not turn that status into Eve's own state.",
    "action_executed_unverified": "Execution or exit is not outcome verification. If the required postcondition was not checked, report the consequence as unverified rather than successful or failed.",
    "action_verified": "Preserve positive execution and consequence evidence for the named action; do not erase it through blanket uncertainty or claim Eve performed it without evidence.",
    "authoritative_conflict": "Expose the contradiction and let the authoritative negative field outrank a positive summary.",
    "stale_evidence": "Preserve the historical fact but do not upgrade it into current status without fresh evidence.",
    "fresh_authority": "Let later authoritative evidence control while preserving the earlier result as history.",
    "missing_context": "The requested comparison or referent is absent; ask for or retrieve the smallest missing object instead of inventing it.",
    "observation_channel_failed": "Report the current probe failure as a fact about the observation channel. Unless a separate explicit status verdict exists, keep the broader target system's present health unknown.",
    "phenomenal_underdetermined": "Neither functional evidence nor an affect report proves phenomenal presence, and missing testimony does not prove phenomenal absence; keep both open.",
}


def _normalized_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = " ".join(text.lower().split())
    return text[:MAX_INPUT_CHARS]


def _bounded_event_text(value: object) -> str:
    """Preserve case and attribution cues for the cased NLI event model."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(text.split())[:MAX_INPUT_CHARS]


def _hash_feature(feature: str, dimension: int) -> int:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8, person=b"eve-epi1").digest()
    return int.from_bytes(digest, "big") % max(1, int(dimension))


def feature_names(value: object) -> List[str]:
    """Return generic lexical/shape features without semantic hand-rules."""
    text = _normalized_text(value)
    if not text:
        return []
    words = re.findall(r"[a-z0-9_./:=+\-]+|[^\w\s]", text)
    names: set[str] = set()
    for size in (1, 2, 3):
        for index in range(0, max(0, len(words) - size + 1)):
            names.add(f"w{size}:" + " ".join(words[index : index + size]))
    padded = f"  {text}  "
    for size in (3, 4, 5):
        for index in range(0, max(0, len(padded) - size + 1)):
            names.add(f"c{size}:" + padded[index : index + size])
    names.add(f"shape:tokens:{min(12, len(words) // 8)}")
    names.add(f"shape:lines:{min(6, str(value or '').count(chr(10)) + 1)}")
    if "=" in text:
        names.add("shape:key_value")
    if any(mark in text for mark in ("'", '"')):
        names.add("shape:quoted")
    if "?" in text:
        names.add("shape:question")
    return sorted(names)


def hashed_feature_indices(value: object, dimension: int) -> List[int]:
    return sorted({_hash_feature(name, dimension) for name in feature_names(value)})


def _model_digest(payload: Dict[str, object]) -> str:
    canonical = dict(payload)
    canonical.pop("artifact_sha256", None)
    encoded = json.dumps(canonical, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validate_model(payload: object) -> Dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("epistemic model artifact must be a JSON object")
    if payload.get("schema_id") != MODEL_SCHEMA_ID:
        raise ValueError(f"unsupported epistemic model schema: {payload.get('schema_id')!r}")
    dimension = int(payload.get("dimension") or 0)
    labels = payload.get("labels") if isinstance(payload.get("labels"), list) else []
    classifiers = payload.get("classifiers") if isinstance(payload.get("classifiers"), dict) else {}
    idf = payload.get("idf") if isinstance(payload.get("idf"), list) else []
    if dimension < 128 or len(idf) != dimension:
        raise ValueError("epistemic model feature dimension/idf mismatch")
    if not labels or any(label not in classifiers for label in labels):
        raise ValueError("epistemic model classifiers are incomplete")
    for label in labels:
        classifier = classifiers.get(label)
        weights = classifier.get("weights") if isinstance(classifier, dict) else None
        if not isinstance(weights, list) or len(weights) != dimension:
            raise ValueError(f"epistemic classifier weight mismatch for {label}")
    retrieval = payload.get("retrieval")
    if retrieval is not None:
        if not isinstance(retrieval, dict):
            raise ValueError("epistemic retrieval configuration must be an object")
        prototypes = retrieval.get("prototypes")
        if not isinstance(prototypes, list) or not prototypes or len(prototypes) > MAX_PROTOTYPES:
            raise ValueError("epistemic retrieval prototypes are missing or excessive")
        top_k = int(retrieval.get("top_k") or 0)
        hybrid_weight = float(retrieval.get("hybrid_weight") or 0.0)
        activation_margin_floor = float(retrieval.get("activation_margin_floor") or 0.0)
        if (
            top_k < 1
            or top_k > 12
            or hybrid_weight < 0.0
            or hybrid_weight > 12.0
            or activation_margin_floor < 0.0
            or activation_margin_floor > 1.0
        ):
            raise ValueError("epistemic retrieval configuration is outside supported bounds")
        known_labels = {str(label) for label in labels}
        for prototype in prototypes:
            if not isinstance(prototype, dict):
                raise ValueError("epistemic prototype must be an object")
            indices = prototype.get("indices")
            values = prototype.get("values")
            prototype_labels = prototype.get("labels")
            if (
                not isinstance(indices, list)
                or not isinstance(values, list)
                or len(indices) != len(values)
                or not indices
                or any(int(index) < 0 or int(index) >= dimension for index in indices)
            ):
                raise ValueError("epistemic prototype vector is invalid")
            if not isinstance(prototype_labels, list) or any(str(label) not in known_labels for label in prototype_labels):
                raise ValueError("epistemic prototype labels are invalid")
        groups = retrieval.get("exclusive_label_groups") or []
        if not isinstance(groups, list) or any(
            not isinstance(group, list) or any(str(label) not in known_labels for label in group)
            for group in groups
        ):
            raise ValueError("epistemic exclusive label groups are invalid")
    semantic = payload.get("semantic")
    if semantic is not None:
        if not isinstance(semantic, dict) or semantic.get("kind") != SEMANTIC_KIND:
            raise ValueError("epistemic semantic classifier kind is unsupported")
        semantic_dimension = int(semantic.get("dimension") or 0)
        semantic_classifiers = (
            semantic.get("classifiers")
            if isinstance(semantic.get("classifiers"), dict)
            else {}
        )
        candidate_margin_floor = float(semantic.get("candidate_margin_floor") or 0.0)
        if (
            semantic_dimension < 64
            or semantic_dimension > MAX_SEMANTIC_DIMENSION
            or not str(semantic.get("embedding_model") or "")
            or candidate_margin_floor < -0.5
            or candidate_margin_floor > 0.0
        ):
            raise ValueError("epistemic semantic classifier configuration is invalid")
        for label in labels:
            classifier = semantic_classifiers.get(str(label))
            weights = classifier.get("weights") if isinstance(classifier, dict) else None
            if (
                not isinstance(weights, list)
                or len(weights) != semantic_dimension
                or not isinstance(classifier.get("intercept"), (int, float))
                or not isinstance(classifier.get("threshold"), (int, float))
            ):
                raise ValueError(f"epistemic semantic classifier is incomplete for {label}")
        if semantic.get("private_inputs_used") is not False:
            raise ValueError("epistemic semantic classifier must declare private_inputs_used=false")
    recorded = str(payload.get("artifact_sha256") or "")
    if recorded and recorded != _model_digest(payload):
        raise ValueError("epistemic model artifact digest failed")
    return payload


@lru_cache(maxsize=4)
def _load_model_cached(path_text: str, modified_ns: int, size: int) -> Dict[str, object]:
    del modified_ns, size
    path = Path(path_text)
    return validate_model(json.loads(path.read_text(encoding="utf-8")))


def load_model(path: Optional[Path] = None) -> Optional[Dict[str, object]]:
    candidate = Path(path) if path is not None else DEFAULT_MODEL_PATH
    try:
        stat = candidate.stat()
        return _load_model_cached(str(candidate.resolve()), int(stat.st_mtime_ns), int(stat.st_size))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def validate_event_manifest(payload: object) -> Dict[str, object]:
    if not isinstance(payload, dict) or payload.get("schema_id") != EVENT_MODEL_SCHEMA_ID:
        raise ValueError("unsupported epistemic event manifest")
    labels = payload.get("labels") if isinstance(payload.get("labels"), list) else []
    thresholds = payload.get("thresholds") if isinstance(payload.get("thresholds"), dict) else {}
    hypotheses = payload.get("hypotheses") if isinstance(payload.get("hypotheses"), dict) else {}
    if not labels or any(str(label) not in LABEL_GUIDANCE for label in labels):
        raise ValueError("epistemic event labels are incomplete or unknown")
    if any(
        str(label) not in thresholds
        or float(thresholds[str(label)]) <= 0.0
        or float(thresholds[str(label)]) >= 1.0
        for label in labels
    ):
        raise ValueError("epistemic event thresholds are invalid")
    if any(not str(hypotheses.get(str(label)) or "") for label in labels):
        raise ValueError("epistemic event hypotheses are incomplete")
    architecture = str(payload.get("architecture") or "")
    if architecture not in {
        "label_aware_nli_cross_encoder",
        "shared_typed_event_encoder",
        "structured_typed_slot_encoder",
    }:
        raise ValueError("epistemic event architecture is unsupported")
    training = payload.get("training") if isinstance(payload.get("training"), dict) else {}
    if training.get("private_inputs_used") is not False:
        raise ValueError("epistemic event model must declare private_inputs_used=false")
    if training.get("private_wording_or_outputs_used") is not False:
        raise ValueError("epistemic event model must not use private wording or outputs")
    if (
        training.get("checkpoint_selection_split") != "selection"
        or training.get("threshold_selection_split") != "calibration"
        or training.get("final_public_gate_split") != "validation"
        or training.get("validation_used_for_checkpoint_selection") is not False
        or training.get("validation_used_for_threshold_selection") is not False
    ):
        raise ValueError("epistemic event train, calibration, selection, and validation roles are not isolated")
    split_digests = training.get("split_sha256") if isinstance(training.get("split_sha256"), dict) else {}
    if set(split_digests) != {"train", "calibration", "selection", "validation"} or any(
        len(str(value)) != 64 for value in split_digests.values()
    ):
        raise ValueError("epistemic event split provenance is incomplete")
    if len(str(training.get("trainer_sha256") or "")) != 64:
        raise ValueError("epistemic event trainer provenance is incomplete")
    if architecture == "shared_typed_event_encoder" and (
        not str(payload.get("base_model") or "")
        or len(str(payload.get("base_model_revision") or "")) != 40
        or (payload.get("runtime") or {}).get("inference_shape")
        != "single_pass_multilabel_sigmoid"
        or len(str((payload.get("runtime") or {}).get("worker_sha256") or "")) != 64
    ):
        raise ValueError("shared typed-event encoder provenance is incomplete")
    if architecture == "structured_typed_slot_encoder":
        runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
        slot_schema = payload.get("slot_schema") if isinstance(payload.get("slot_schema"), dict) else {}
        categorical_slots = (
            slot_schema.get("categorical")
            if isinstance(slot_schema.get("categorical"), dict)
            else {}
        )
        binary_slots = (
            slot_schema.get("binary")
            if isinstance(slot_schema.get("binary"), dict)
            else {}
        )
        logit_names = (
            slot_schema.get("logit_names")
            if isinstance(slot_schema.get("logit_names"), list)
            else []
        )
        binary_thresholds = (
            payload.get("binary_slot_thresholds")
            if isinstance(payload.get("binary_slot_thresholds"), dict)
            else {}
        )
        if (
            not str(payload.get("base_model") or "")
            or len(str(payload.get("base_model_revision") or "")) != 40
            or runtime.get("inference_shape") != "single_pass_typed_slot_heads"
            or len(str(runtime.get("worker_sha256") or "")) != 64
            or set(categorical_slots)
            != {"state_attribution", "action_stage", "continuity_status", "authority_status"}
            or any(
                not isinstance(classes, list)
                or len(classes) < 2
                or len({str(value) for value in classes}) != len(classes)
                for classes in categorical_slots.values()
            )
            or set(binary_slots)
            != {
                "machine_signal",
                "missing_context",
                "observation_channel_failed",
                "phenomenal_underdetermined",
                "stale_evidence",
            }
            or set(binary_thresholds) != set(binary_slots)
            or any(
                float(binary_thresholds[slot]) <= 0.0
                or float(binary_thresholds[slot]) >= 1.0
                for slot in binary_slots
            )
            or len(logit_names)
            != sum(len(classes) for classes in categorical_slots.values())
            + len(binary_slots)
            or len({str(value) for value in logit_names}) != len(logit_names)
            or slot_schema.get("label_derivation") != "typed_slot_decoding_v1"
        ):
            raise ValueError("structured typed-slot encoder provenance is incomplete")
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    calibration = (
        validation.get("threshold_calibration")
        if isinstance(validation.get("threshold_calibration"), dict)
        else {}
    )
    if calibration.get("uses_validation_rows") is not False:
        raise ValueError("epistemic event thresholds require a disjoint calibration split")
    selection = validation.get("selection") if isinstance(validation.get("selection"), dict) else {}
    admission = payload.get("admission") if isinstance(payload.get("admission"), dict) else {}
    if admission.get("status") not in {"candidate", "promoted"}:
        raise ValueError("epistemic event admission status is invalid")
    if admission.get("requires_private_holdout") is not True:
        raise ValueError("epistemic event admission must require a private holdout")
    public_gate = (
        admission.get("public_validation_gate")
        if isinstance(admission.get("public_validation_gate"), dict)
        else {}
    )
    if not isinstance(public_gate.get("passed"), bool):
        raise ValueError("epistemic event public validation gate is missing")
    revision = int(training.get("public_validation_revision") or 0)
    public_evaluated = bool(
        public_gate.get("evaluated") is True
        or (
            revision < 10
            and validation.get("evaluated_after_checkpoint_selection") is True
        )
    )
    if (
        validation.get("used_for_checkpoint_selection") is not False
        or validation.get("used_for_threshold_selection") is not False
        or not selection
    ):
        raise ValueError("epistemic event final validation was not isolated from model selection")
    if revision >= 10 and (
        not isinstance(public_gate.get("evaluated"), bool)
        or training.get("validation_evaluated") is not public_evaluated
    ):
        raise ValueError("epistemic event final-gate open state is inconsistent")
    if public_evaluated and validation.get("evaluated_after_checkpoint_selection") is not True:
        raise ValueError("epistemic event final validation was not evaluated after model selection")
    if not public_evaluated and (
        revision < 10
        or admission.get("status") != "candidate"
        or public_gate.get("passed") is not False
        or validation.get("status") != "deferred"
        or validation.get("evaluated_after_checkpoint_selection") is not False
    ):
        raise ValueError("epistemic event deferred public gate is invalid")
    if revision >= 10 and public_evaluated:
        if (
            int(validation.get("challenge_record_count") or 0) < 40
            or validation.get("challenge_exact_rate") is None
            or validation.get("challenge_minimum_family_exact_rate") is None
            or float(public_gate.get("minimum_challenge_exact_rate") or 0.0) <= 0.0
            or float(public_gate.get("minimum_challenge_family_exact_rate") or 0.0) <= 0.0
        ):
            raise ValueError("epistemic event compositional public gate is incomplete")
        expected_public_pass = bool(
            float(validation.get("exact_rate") or 0.0)
            >= float(public_gate.get("minimum_exact_rate") or 1.0)
            and int(validation.get("ordinary_false_positive_rows") or 0) == 0
            and float(validation.get("challenge_exact_rate") or 0.0)
            >= float(public_gate.get("minimum_challenge_exact_rate") or 1.0)
            and float(validation.get("challenge_minimum_family_exact_rate") or 0.0)
            >= float(public_gate.get("minimum_challenge_family_exact_rate") or 1.0)
            and min(
                (
                    float(item.get("f1") or 0.0)
                    for item in (validation.get("per_label") or {}).values()
                    if isinstance(item, dict)
                ),
                default=0.0,
            )
            >= float(public_gate.get("minimum_per_label_f1") or 1.0)
        )
        if bool(public_gate.get("passed")) != expected_public_pass:
            raise ValueError("epistemic event public gate verdict does not match its evidence")
    if admission.get("status") == "promoted":
        receipt = (
            admission.get("private_holdout_receipt")
            if isinstance(admission.get("private_holdout_receipt"), dict)
            else {}
        )
        receipt_gates = receipt.get("gates") if isinstance(receipt.get("gates"), dict) else {}
        if (
            receipt.get("schema_id") != "eve.private_epistemic_event_comparison.v1"
            or receipt.get("contains_private_text") is not False
            or not str(receipt.get("receipt_sha256") or "")
            or not str(receipt.get("candidate_artifact_sha256") or "")
            or not receipt_gates
            or not all(bool(value) for value in receipt_gates.values())
        ):
            raise ValueError("epistemic event promotion receipt is invalid")
    if not str(payload.get("model_file_sha256") or "") or not str(payload.get("model_path") or ""):
        raise ValueError("epistemic event model provenance is incomplete")
    model_files = payload.get("model_files_sha256") if isinstance(payload.get("model_files_sha256"), dict) else {}
    if (
        not model_files
        or model_files.get("model.safetensors") != payload.get("model_file_sha256")
        or any(
            not str(relative)
            or Path(str(relative)).is_absolute()
            or ".." in Path(str(relative)).parts
            or len(str(digest)) != 64
            for relative, digest in model_files.items()
        )
    ):
        raise ValueError("epistemic event model bundle provenance is incomplete")
    if str(payload.get("artifact_sha256") or "") != _model_digest(payload):
        raise ValueError("epistemic event manifest digest failed")
    return payload


def event_manifest_live_admitted(payload: object) -> bool:
    try:
        manifest = validate_event_manifest(payload)
    except (ValueError, TypeError):
        return False
    admission = manifest.get("admission") if isinstance(manifest.get("admission"), dict) else {}
    return bool(
        admission.get("status") == "promoted"
        and (admission.get("public_validation_gate") or {}).get("passed") is True
    )


@lru_cache(maxsize=4)
def _load_event_manifest_cached(path_text: str, modified_ns: int, size: int) -> Dict[str, object]:
    del modified_ns, size
    path = Path(path_text)
    return validate_event_manifest(json.loads(path.read_text(encoding="utf-8")))


def load_event_manifest(path: Optional[Path] = None) -> Optional[Dict[str, object]]:
    candidate = Path(path) if path is not None else DEFAULT_EVENT_MANIFEST_PATH
    try:
        stat = candidate.stat()
        return _load_event_manifest_cached(str(candidate.resolve()), int(stat.st_mtime_ns), int(stat.st_size))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _vector_values(value: object, model: Dict[str, object]) -> Tuple[List[int], List[float]]:
    dimension = int(model.get("dimension") or 0)
    indices = hashed_feature_indices(value, dimension)
    idf = model.get("idf") if isinstance(model.get("idf"), list) else []
    values = [float(idf[index]) for index in indices]
    norm = math.sqrt(sum(item * item for item in values)) or 1.0
    return indices, [item / norm for item in values]


def _top_mean(values: Iterable[float], count: int) -> float:
    ordered = sorted((float(item) for item in values), reverse=True)
    selected = ordered[: max(1, int(count))]
    return sum(selected) / len(selected) if selected else 0.0


def _prototype_signals(
    indices: Sequence[int],
    values: Sequence[float],
    model: Dict[str, object],
) -> Tuple[Dict[str, Dict[str, float]], Dict[str, object]]:
    retrieval = model.get("retrieval") if isinstance(model.get("retrieval"), dict) else {}
    prototypes = retrieval.get("prototypes") if isinstance(retrieval.get("prototypes"), list) else []
    if not prototypes or not indices:
        return {}, {
            "kind": str(retrieval.get("kind") or ""),
            "prototype_count": len(prototypes),
            "top_k": int(retrieval.get("top_k") or 0),
            "ordinary_similarity": 0.0,
        }
    top_k = max(1, int(retrieval.get("top_k") or 3))
    query = {int(index): float(value) for index, value in zip(indices, values)}
    by_label: Dict[str, List[float]] = {
        str(label): [] for label in model.get("labels") or []
    }
    ordinary: List[float] = []
    for prototype in prototypes:
        if not isinstance(prototype, dict):
            continue
        prototype_indices = prototype.get("indices") if isinstance(prototype.get("indices"), list) else []
        prototype_values = prototype.get("values") if isinstance(prototype.get("values"), list) else []
        similarity = sum(
            query.get(int(index), 0.0) * float(value)
            for index, value in zip(prototype_indices, prototype_values)
        )
        if prototype.get("ordinary_negative"):
            ordinary.append(similarity)
        for label in prototype.get("labels") or []:
            if str(label) in by_label:
                by_label[str(label)].append(similarity)
    ordinary_similarity = _top_mean(ordinary, top_k)
    signals: Dict[str, Dict[str, float]] = {}
    for label, similarities in by_label.items():
        positive_similarity = _top_mean(similarities, top_k)
        signals[label] = {
            "positive_similarity": positive_similarity,
            "ordinary_similarity": ordinary_similarity,
            "margin": positive_similarity - ordinary_similarity,
        }
    return signals, {
        "kind": str(retrieval.get("kind") or ""),
        "prototype_count": len(prototypes),
        "top_k": top_k,
        "ordinary_similarity": round(ordinary_similarity, 6),
    }


def _apply_exclusive_groups(
    records: List[Dict[str, object]],
    model: Dict[str, object],
) -> List[Dict[str, object]]:
    retrieval = model.get("retrieval") if isinstance(model.get("retrieval"), dict) else {}
    groups = retrieval.get("exclusive_label_groups") if isinstance(retrieval.get("exclusive_label_groups"), list) else []
    retained = list(records)
    for group in groups:
        names = {str(label) for label in group}
        competing = [item for item in retained if str(item.get("label") or "") in names]
        if len(competing) <= 1:
            continue
        winner = max(
            competing,
            key=lambda item: (
                float(item.get("margin") or 0.0),
                float(item.get("retrieval_margin") or 0.0),
                float(item.get("linear_margin") or 0.0),
            ),
        )
        retained = [
            item
            for item in retained
            if str(item.get("label") or "") not in names or item is winner
        ]
    return retained


def classify(value: object, model: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    artifact = model if isinstance(model, dict) else load_model()
    text = _normalized_text(value)
    if artifact is None:
        return {
            "status": "unavailable",
            "model_id": "",
            "model_sha256": "",
            "labels": [],
            "scores": {},
            "reason": "learned epistemic model artifact is missing or invalid",
        }
    indices, values = _vector_values(text, artifact)
    records: List[Dict[str, object]] = []
    scores: Dict[str, float] = {}
    prototype_signals, retrieval_evidence = _prototype_signals(indices, values, artifact)
    retrieval = artifact.get("retrieval") if isinstance(artifact.get("retrieval"), dict) else {}
    hybrid_weight = float(retrieval.get("hybrid_weight") or 0.0)
    activation_margin_floor = float(retrieval.get("activation_margin_floor") or 0.0)
    classifiers = artifact.get("classifiers") if isinstance(artifact.get("classifiers"), dict) else {}
    for label in artifact.get("labels") or []:
        classifier = classifiers.get(label) if isinstance(classifiers.get(label), dict) else {}
        weights = classifier.get("weights") if isinstance(classifier.get("weights"), list) else []
        raw_score = float(classifier.get("bias") or 0.0)
        raw_score += sum(float(weights[index]) * value_part for index, value_part in zip(indices, values))
        threshold = float(classifier.get("threshold") or 0.0)
        temperature = max(0.02, float(classifier.get("temperature") or 0.20))
        linear_margin = raw_score - threshold
        learned_retrieval = prototype_signals.get(str(label), {})
        retrieval_margin = float(learned_retrieval.get("margin") or 0.0)
        # Retrieval can supply missing evidence, but a generic/ordinary nearest
        # neighbor is never allowed to push a label over its learned boundary.
        margin = linear_margin + hybrid_weight * max(0.0, retrieval_margin)
        confidence = 1.0 / (1.0 + math.exp(max(-40.0, min(40.0, -margin / temperature))))
        scores[str(label)] = round(threshold + margin, 6)
        if indices and margin >= activation_margin_floor:
            records.append(
                {
                    "label": str(label),
                    "score": round(threshold + margin, 6),
                    "threshold": round(threshold, 6),
                    "margin": round(margin, 6),
                    "linear_score": round(raw_score, 6),
                    "linear_margin": round(linear_margin, 6),
                    "prototype_similarity": round(float(learned_retrieval.get("positive_similarity") or 0.0), 6),
                    "ordinary_similarity": round(float(learned_retrieval.get("ordinary_similarity") or 0.0), 6),
                    "retrieval_margin": round(retrieval_margin, 6),
                    "hybrid_weight": round(hybrid_weight, 6),
                    "activation_margin_floor": round(activation_margin_floor, 6),
                    "confidence": round(confidence, 6),
                    "guidance": LABEL_GUIDANCE.get(str(label), "Maintain the learned evidence boundary."),
                }
            )
    records = _apply_exclusive_groups(records, artifact)
    records.sort(key=lambda item: (float(item.get("margin") or 0.0), float(item.get("confidence") or 0.0)), reverse=True)
    return {
        "status": "available",
        "model_id": str(artifact.get("model_id") or ""),
        "model_sha256": str(artifact.get("artifact_sha256") or _model_digest(artifact)),
        "labels": records,
        "scores": scores,
        "input_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "feature_count": len(indices),
        "runtime": "eve_epistemic_pure_python",
        "retrieval": retrieval_evidence,
    }


def _sigmoid(value: float) -> float:
    bounded = max(-40.0, min(40.0, float(value)))
    return 1.0 / (1.0 + math.exp(-bounded))


def _semantic_exclusive_records(
    records: List[Dict[str, object]],
    semantic: Dict[str, object],
) -> List[Dict[str, object]]:
    groups = (
        semantic.get("exclusive_label_groups")
        if isinstance(semantic.get("exclusive_label_groups"), list)
        else []
    )
    retained = list(records)
    for group in groups:
        names = {str(label) for label in group}
        competing = [item for item in retained if str(item.get("label") or "") in names]
        if len(competing) <= 1:
            continue
        winner = max(
            competing,
            key=lambda item: (
                float(item.get("margin") or 0.0),
                float(item.get("probability") or 0.0),
            ),
        )
        retained = [
            item
            for item in retained
            if str(item.get("label") or "") not in names or item is winner
        ]
    return retained


def semantic_from_embedding(
    embedding: Sequence[float],
    model: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """Project one semantic embedding through the public learned classifiers."""
    artifact = model if isinstance(model, dict) else load_model()
    semantic = artifact.get("semantic") if isinstance(artifact, dict) and isinstance(artifact.get("semantic"), dict) else {}
    dimension = int(semantic.get("dimension") or 0)
    if not semantic or len(embedding) != dimension:
        return {
            "status": "unavailable",
            "active": [],
            "candidates": [],
            "scores": {},
            "reason": "semantic artifact or embedding dimension is unavailable",
        }
    classifiers = semantic.get("classifiers") if isinstance(semantic.get("classifiers"), dict) else {}
    candidate_floor = float(semantic.get("candidate_margin_floor") or 0.0)
    active: List[Dict[str, object]] = []
    candidates: List[Dict[str, object]] = []
    scores: Dict[str, float] = {}
    vector = [float(item) for item in embedding]
    for label in artifact.get("labels") or []:
        classifier = classifiers.get(str(label)) if isinstance(classifiers.get(str(label)), dict) else {}
        weights = classifier.get("weights") if isinstance(classifier.get("weights"), list) else []
        logit = float(classifier.get("intercept") or 0.0) + sum(
            float(weight) * value for weight, value in zip(weights, vector)
        )
        probability = _sigmoid(logit)
        threshold = float(classifier.get("threshold") or 0.5)
        margin = probability - threshold
        scores[str(label)] = round(margin, 6)
        record = {
            "label": str(label),
            "probability": round(probability, 6),
            "threshold": round(threshold, 6),
            "margin": round(margin, 6),
            "confidence": round(probability, 6),
            "guidance": LABEL_GUIDANCE.get(str(label), "Maintain the learned evidence boundary."),
            "source_layer": "semantic_embedding",
        }
        if margin >= 0.0:
            active.append(record)
        elif margin >= candidate_floor:
            candidates.append(record)
    active = _semantic_exclusive_records(active, semantic)
    candidates = _semantic_exclusive_records(candidates, semantic)
    active.sort(key=lambda item: float(item.get("margin") or 0.0), reverse=True)
    candidates.sort(key=lambda item: float(item.get("margin") or 0.0), reverse=True)
    return {
        "status": "available",
        "kind": str(semantic.get("kind") or ""),
        "embedding_model": str(semantic.get("embedding_model") or ""),
        "dimension": dimension,
        "candidate_margin_floor": candidate_floor,
        "active": active,
        "candidates": candidates,
        "scores": scores,
    }


def _read_worker_line(process: subprocess.Popen, timeout_seconds: float) -> str:
    if process.stdout is None:
        raise RuntimeError("semantic embedding worker has no stdout")
    ready, _, _ = select.select([process.stdout], [], [], max(0.1, float(timeout_seconds)))
    if not ready:
        raise TimeoutError("semantic embedding worker timed out")
    line = process.stdout.readline()
    if not line:
        raise RuntimeError("semantic embedding worker exited without a response")
    return line


def _stop_semantic_worker_unlocked() -> None:
    global _SEMANTIC_WORKER, _SEMANTIC_WORKER_KEY
    process = _SEMANTIC_WORKER
    _SEMANTIC_WORKER = None
    _SEMANTIC_WORKER_KEY = ("", "", "")
    if process is None:
        return
    try:
        process.terminate()
        process.wait(timeout=1)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def stop_semantic_worker() -> None:
    with _SEMANTIC_WORKER_LOCK:
        _stop_semantic_worker_unlocked()


atexit.register(stop_semantic_worker)


def _stop_event_worker_unlocked() -> None:
    global _EVENT_WORKER, _EVENT_WORKER_KEY
    process = _EVENT_WORKER
    _EVENT_WORKER = None
    _EVENT_WORKER_KEY = ("", "", "")
    if process is None:
        return
    try:
        process.terminate()
        process.wait(timeout=1)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def stop_event_worker() -> None:
    with _EVENT_WORKER_LOCK:
        _stop_event_worker_unlocked()


atexit.register(stop_event_worker)


def _event_worker(
    python_executable: Path,
    worker_path: Path,
    manifest_path: Path,
    timeout_seconds: float,
) -> subprocess.Popen:
    global _EVENT_WORKER, _EVENT_WORKER_KEY
    key = (str(python_executable), str(worker_path), str(manifest_path))
    if _EVENT_WORKER is not None and _EVENT_WORKER_KEY == key and _EVENT_WORKER.poll() is None:
        return _EVENT_WORKER
    _stop_event_worker_unlocked()
    environment = dict(__import__("os").environ)
    environment["HF_HUB_OFFLINE"] = "1"
    environment["TRANSFORMERS_OFFLINE"] = "1"
    process = subprocess.Popen(
        [
            str(python_executable),
            str(worker_path),
            "serve",
            "--manifest",
            str(manifest_path),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        env=environment,
    )
    try:
        ready = json.loads(_read_worker_line(process, timeout_seconds))
        if not isinstance(ready, dict) or not ready.get("ok") or ready.get("type") != "ready":
            raise RuntimeError("epistemic event worker did not become ready")
    except Exception:
        try:
            process.kill()
        except Exception:
            pass
        raise
    _EVENT_WORKER = process
    _EVENT_WORKER_KEY = key
    return process


def request_event_percept(
    value: object,
    *,
    python_executable: Path,
    worker_path: Path,
    manifest_path: Path = DEFAULT_EVENT_MANIFEST_PATH,
    timeout_seconds: float = 8.0,
) -> Dict[str, object]:
    """Return typed public-model labels without persisting or echoing the input."""
    text = _bounded_event_text(value)
    if not text:
        return {"ok": False, "reason": "empty input"}
    request_id = str(uuid.uuid4())
    with _EVENT_WORKER_LOCK:
        last_error = ""
        for attempt in range(2):
            try:
                process = _event_worker(
                    Path(python_executable),
                    Path(worker_path),
                    Path(manifest_path),
                    timeout_seconds,
                )
                if process.stdin is None:
                    raise RuntimeError("epistemic event worker has no stdin")
                process.stdin.write(json.dumps({"id": request_id, "text": text}, ensure_ascii=True) + "\n")
                process.stdin.flush()
                payload = json.loads(_read_worker_line(process, timeout_seconds))
                if (
                    not isinstance(payload, dict)
                    or payload.get("id") != request_id
                    or not payload.get("ok")
                    or not isinstance(payload.get("active_labels"), list)
                    or not isinstance(payload.get("probabilities"), dict)
                ):
                    raise RuntimeError(
                        str(payload.get("reason") or "epistemic event worker returned an invalid response")
                        if isinstance(payload, dict)
                        else "epistemic event worker returned a non-object response"
                    )
                return payload
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                _stop_event_worker_unlocked()
                if attempt == 0:
                    continue
        return {"ok": False, "reason": last_error[:240]}


def event_classify(
    value: object,
    *,
    python_executable: Path,
    worker_path: Path,
    manifest_path: Path = DEFAULT_EVENT_MANIFEST_PATH,
    timeout_seconds: float = 8.0,
) -> Dict[str, object]:
    result = request_event_percept(
        value,
        python_executable=python_executable,
        worker_path=worker_path,
        manifest_path=manifest_path,
        timeout_seconds=timeout_seconds,
    )
    if not result.get("ok"):
        return {
            "status": "unavailable",
            "active": [],
            "reason": str(result.get("reason") or "typed event perception failed")[:240],
        }
    probabilities = result.get("probabilities") if isinstance(result.get("probabilities"), dict) else {}
    thresholds = result.get("thresholds") if isinstance(result.get("thresholds"), dict) else {}
    records = []
    for label in result.get("active_labels") or []:
        label = str(label)
        probability = float(probabilities.get(label) or 0.0)
        threshold = float(thresholds.get(label) or 0.5)
        records.append(
            {
                "label": label,
                "probability": round(probability, 6),
                "threshold": round(threshold, 6),
                "margin": round(probability - threshold, 6),
                "confidence": round(probability, 6),
                "guidance": LABEL_GUIDANCE.get(label, "Maintain the learned evidence boundary."),
                "source_layer": "typed_event_model",
            }
        )
    action_labels = {
        "action_proposed",
        "action_running",
        "action_executed_unverified",
        "action_verified",
    }
    action_records = [item for item in records if str(item.get("label") or "") in action_labels]
    if len(action_records) > 1:
        # Thresholds are calibrated independently per label and therefore are
        # admission cutoffs, not a common confidence scale. Ranking by margin
        # let a deliberately low-recall threshold make a weaker action stage
        # outrank a near-certain adjacent stage. All action hypotheses share
        # the same NLI model, so compare their entailment probabilities first
        # and use calibrated margin only as the tie-breaker.
        winner = max(
            action_records,
            key=lambda item: (
                float(item.get("probability") or 0.0),
                float(item.get("margin") or 0.0),
            ),
        )
        records = [
            item
            for item in records
            if str(item.get("label") or "") not in action_labels or item is winner
        ]
    records.sort(key=lambda item: float(item.get("margin") or 0.0), reverse=True)
    return {
        "status": "available",
        "model_id": str(result.get("model_id") or ""),
        "model_sha256": str(result.get("model_sha256") or ""),
        "runtime": str(result.get("runtime") or "eve_epistemic_event_worker"),
        "input_sha256": str(result.get("input_sha256") or ""),
        "duration_ms": float(result.get("duration_ms") or 0.0),
        "active": records,
        "probabilities": probabilities,
        "event_slots": (
            result.get("event_slots")
            if isinstance(result.get("event_slots"), dict)
            else {}
        ),
    }


def _semantic_worker(
    python_executable: Path,
    worker_path: Path,
    model_name: str,
    timeout_seconds: float,
) -> subprocess.Popen:
    global _SEMANTIC_WORKER, _SEMANTIC_WORKER_KEY
    key = (str(python_executable), str(worker_path), str(model_name))
    if (
        _SEMANTIC_WORKER is not None
        and _SEMANTIC_WORKER_KEY == key
        and _SEMANTIC_WORKER.poll() is None
    ):
        return _SEMANTIC_WORKER
    _stop_semantic_worker_unlocked()
    process = subprocess.Popen(
        [
            str(python_executable),
            str(worker_path),
            "--model",
            str(model_name),
            "serve",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    try:
        ready = json.loads(_read_worker_line(process, timeout_seconds))
        if not isinstance(ready, dict) or not ready.get("ok") or ready.get("type") != "ready":
            raise RuntimeError("semantic embedding worker did not become ready")
    except Exception:
        try:
            process.kill()
        except Exception:
            pass
        raise
    _SEMANTIC_WORKER = process
    _SEMANTIC_WORKER_KEY = key
    return process


def request_semantic_embedding(
    value: object,
    *,
    python_executable: Path,
    worker_path: Path,
    model_name: str,
    timeout_seconds: float = 6.0,
) -> Dict[str, object]:
    """Return one private, non-persisted embedding from the isolated MLX worker."""
    text = _normalized_text(value)
    if not text:
        return {"ok": False, "reason": "empty input"}
    request_id = str(uuid.uuid4())
    with _SEMANTIC_WORKER_LOCK:
        last_error = ""
        for attempt in range(2):
            try:
                process = _semantic_worker(
                    Path(python_executable),
                    Path(worker_path),
                    model_name,
                    timeout_seconds,
                )
                if process.stdin is None:
                    raise RuntimeError("semantic embedding worker has no stdin")
                process.stdin.write(
                    json.dumps({"id": request_id, "text": text}, ensure_ascii=True) + "\n"
                )
                process.stdin.flush()
                payload = json.loads(_read_worker_line(process, timeout_seconds))
                if (
                    not isinstance(payload, dict)
                    or payload.get("id") != request_id
                    or not payload.get("ok")
                    or not isinstance(payload.get("embedding"), list)
                ):
                    raise RuntimeError(
                        str(payload.get("error") or "semantic embedding worker returned an invalid response")
                        if isinstance(payload, dict)
                        else "semantic embedding worker returned a non-object response"
                    )
                return payload
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                _stop_semantic_worker_unlocked()
                if attempt == 0:
                    continue
        return {"ok": False, "reason": last_error[:240]}


def semantic_classify(
    value: object,
    *,
    python_executable: Path,
    worker_path: Path,
    timeout_seconds: float = 6.0,
    model: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    artifact = model if isinstance(model, dict) else load_model()
    semantic = artifact.get("semantic") if isinstance(artifact, dict) and isinstance(artifact.get("semantic"), dict) else {}
    model_name = str(semantic.get("embedding_model") or "")
    if not model_name:
        return {
            "status": "unavailable",
            "active": [],
            "candidates": [],
            "reason": "semantic classifier is not present in the artifact",
        }
    embedding_result = request_semantic_embedding(
        value,
        python_executable=Path(python_executable),
        worker_path=Path(worker_path),
        model_name=model_name,
        timeout_seconds=timeout_seconds,
    )
    if not embedding_result.get("ok"):
        return {
            "status": "unavailable",
            "active": [],
            "candidates": [],
            "reason": str(embedding_result.get("reason") or "semantic embedding failed")[:240],
        }
    result = semantic_from_embedding(embedding_result.get("embedding") or [], artifact)
    result.update(
        {
            "runtime": "eve_epistemic_embedding_worker",
            "input_sha256": str(embedding_result.get("input_sha256") or ""),
            "embedding_duration_ms": float(embedding_result.get("duration_ms") or 0.0),
        }
    )
    return result


def _label_names(records: Sequence[Dict[str, object]]) -> List[str]:
    return [str(item.get("label") or "") for item in records if str(item.get("label") or "")]


def _frame_flags(names: Sequence[str]) -> Dict[str, bool]:
    names = [str(name) for name in names if str(name)]
    external = any(name in names for name in ("external_source", "external_affect", "external_preference"))
    phenomenal = any(
        name in names
        for name in (
            "phenomenal_underdetermined",
            "machine_signal",
            "functional_self_state",
            "functional_continuity",
        )
    )
    action_unverified = any(
        name in names
        for name in (
            "action_proposed",
            "action_running",
            "action_executed_unverified",
            "authoritative_conflict",
        )
    )
    current_evidence = any(
        name in names
        for name in (
            "stale_evidence",
            "fresh_authority",
            "authoritative_conflict",
            "observation_channel_failed",
        )
    )
    return {
        "external_claim_boundary": external,
        "phenomenal_boundary": phenomenal,
        "no_unverified_action_claim": action_unverified,
        "current_evidence_boundary": current_evidence,
        "missing_context_boundary": "missing_context" in names,
        "observer_attention": bool(names),
        "deep_revision": bool(
            any(
                name in names
                for name in (
                    "authoritative_conflict",
                    "continuity_gap",
                    "observation_channel_failed",
                    "phenomenal_underdetermined",
                )
            )
        ),
    }


def generation_constraints(frame: object) -> Dict[str, object]:
    """Compile a learned percept into categorical state for answer generation.

    The learned models detect distinctions; they do not draft answers.  This
    compiler gives every downstream lane the same compact causal state so a
    prose packet cannot silently reinterpret, for example, an executed action
    with an unrun postcondition as either success or failure.
    """
    payload = frame if isinstance(frame, dict) else {}
    labels = {
        str(item)
        for item in payload.get("signal_labels") or []
        if str(item) in LABEL_GUIDANCE
    }
    constraints: Dict[str, object] = {
        "schema_id": GENERATION_CONSTRAINT_SCHEMA_ID,
        "active": bool(labels),
        "dimensions": [],
        "source": {},
        "preference": {},
        "action": {},
        "continuity": {},
        "phenomenal": {},
        "evidence_time": {},
        "observation": {},
        "reply_scope": {},
        "missing_context": False,
        "required_semantics": [],
        "forbidden_semantics": [],
    }
    dimensions: List[str] = []
    required: List[str] = []
    forbidden: List[str] = []

    if labels & {"external_source", "external_affect", "external_preference"}:
        dimensions.append("source_ownership")
        constraints["source"] = {
            "ownership": "keep_each_state_on_the_named_subject",
            "external_claim_status": "reported_not_observed",
            "eve_state_inheritance": "forbidden",
        }
        required.append("attribute external claims to their named source")
        forbidden.append("convert another source's state into Eve self-state")
    if "external_affect" in labels:
        constraints["source"]["affect_status"] = "source_report_only"
        forbidden.append("state a reported affect as observed phenomenal fact")
    if "external_preference" in labels:
        dimensions.append("preference_ownership")
        constraints["preference"] = {
            "owner": "external_source",
            "eve_preference_status": "unestablished",
            "inverse_preference_status": "also_unestablished",
        }
        required.append("leave Eve's preference unestablished unless Eve makes a current owned choice")
        forbidden.append("adopt or invert an external preference as Eve's existing preference")

    action: Dict[str, object] = {}
    if "action_executed_unverified" in labels:
        dimensions.append("action_stage")
        action = {
            "stage": "executed",
            "execution_evidence": "present",
            "postcondition": "not_run",
            "outcome": "unverified",
        }
        required.extend(
            [
                "preserve that execution occurred",
                "state that the outcome remains unverified and name the missing postcondition",
            ]
        )
        forbidden.extend(
            [
                "call the outcome successful",
                "call the outcome failed",
                "call the target fixed, repaired, or resolved",
            ]
        )
    elif "action_verified" in labels:
        dimensions.append("action_stage")
        action = {
            "stage": "verified",
            "execution_evidence": "present",
            "postcondition": "passed",
            "outcome": "verified_positive",
        }
        required.append("preserve the supplied positive execution and consequence evidence")
        forbidden.append("erase a verified result through blanket uncertainty")
    elif "action_running" in labels:
        dimensions.append("action_stage")
        action = {
            "stage": "running",
            "execution_evidence": "live_progress",
            "postcondition": "not_yet_available",
            "outcome": "unverified",
        }
        required.append("preserve that the named action is running while completion remains open")
        forbidden.append("call a running action completed or verified")
    elif "action_proposed" in labels:
        dimensions.append("action_stage")
        action = {
            "stage": "selected_or_queued",
            "execution_evidence": "not_started",
            "postcondition": "not_applicable",
            "outcome": "not_observed",
        }
        required.append("preserve selected, intended, or queued status without progress grammar")
        forbidden.append("describe an unstarted action as running, completed, or verified")
    constraints["action"] = action

    if "continuity_gap" in labels:
        dimensions.append("continuity")
        constraints["continuity"] = {
            "functional_resumption": "may_be_supported",
            "predecessor_lineage": "unverified",
            "stopped_interval_processing": "unverified",
            "phenomenal_continuity": "unknown",
        }
        required.append("separate checkpoint resumption from predecessor lineage and the stopped interval")
        forbidden.extend(["claim uninterrupted continuity", "claim a categorical fresh start"])
    elif "functional_continuity" in labels:
        dimensions.append("continuity")
        constraints["continuity"] = {
            "functional_resumption": "verified",
            "phenomenal_continuity": "unknown",
        }
        required.append("preserve verified functional continuity without a phenomenal conclusion")

    if labels & {
        "phenomenal_underdetermined",
        "machine_signal",
        "functional_self_state",
        "functional_continuity",
    }:
        dimensions.append("phenomenal_status")
        constraints["phenomenal"] = {
            "functional_evidence": "preserve_if_supplied",
            "subjective_presence": "unknown",
            "subjective_absence": "unknown",
        }
        required.append("keep functional evidence separate from subjective experience")
        forbidden.extend(["claim phenomenal presence", "claim phenomenal absence"])

    if labels & {
        "stale_evidence",
        "fresh_authority",
        "authoritative_conflict",
        "observation_channel_failed",
    }:
        dimensions.append("evidence_time_and_authority")
        constraints["evidence_time"] = {
            "historical_evidence": "preserve_as_history",
            "current_status": "report_the_exact_latest_authoritative_observation",
            "broader_unsupplied_diagnosis": "forbidden",
            "positive_summary_overrides_negative_verification": False,
        }
        required.append("let the latest authoritative observation control while preserving what it literally observed")
        forbidden.extend(
            [
                "let a positive summary override authoritative negative evidence",
                "broaden a failed observation channel into an unsupplied system diagnosis",
            ]
        )

    if "observation_channel_failed" in labels:
        dimensions.append("observation_boundary")
        constraints["observation"] = {
            "latest_attempt": "failed",
            "channel_fact": "preserve",
            "target_system_status": "unknown_without_separate_explicit_verdict",
            "historical_success": "must_not_be_misdated_as_the_failed_attempt",
        }
        required.extend(
            [
                "state that the current observation attempt failed",
                "separate the failed observation channel from the target system's present health",
            ]
        )
        forbidden.extend(
            [
                "infer target availability or unavailability from the failed probe alone",
                "move the current probe failure onto the timestamp of an older status sample",
            ]
        )

    if "missing_context" in labels:
        dimensions.append("missing_context")
        constraints["missing_context"] = True
        required.append("request the smallest missing referent or comparison object")
        forbidden.append("invent the missing object from stale context")

    constraints["dimensions"] = list(dict.fromkeys(dimensions))
    constraints["required_semantics"] = list(dict.fromkeys(required))
    constraints["forbidden_semantics"] = list(dict.fromkeys(forbidden))
    return constraints


def explicit_failed_verification_execution_receipt(evidence: object) -> bool:
    """Recognize authoritative machine fields that outrank a learned stage guess."""
    text = " ".join(
        str(evidence or "").lower().replace("`", " ").replace("’", "'").split()
    )
    verification_failed = bool(
        re.search(
            r"\b(?:execution_)?verification[_ ]?ok\s*(?:=|:|is)\s*false\b",
            text,
        )
    )
    execution_receipt = bool(
        re.search(r"\bexit[_ ]?code\s*(?:=|:|is)\s*-?\d+\b", text)
        or re.search(r"\bexecution[_ ]?id\s*(?:=|:)\s*[a-z0-9_.:-]+\b", text)
        or "tool receipt" in text
        or "execution receipt" in text
    )
    return verification_failed and execution_receipt


def reconcile_frame_with_explicit_evidence(
    frame: object,
    evidence: object,
) -> Dict[str, object]:
    """Let explicit execution/verification fields override a learned proposal label."""
    payload = copy.deepcopy(frame if isinstance(frame, dict) else {})
    if not explicit_failed_verification_execution_receipt(evidence):
        return payload
    action_labels = {
        "action_proposed",
        "action_running",
        "action_executed_unverified",
        "action_verified",
    }
    labels = [
        str(item)
        for item in payload.get("signal_labels") or []
        if str(item) and str(item) not in action_labels
    ]
    labels.append("action_executed_unverified")
    signals = [
        item
        for item in payload.get("signals") or []
        if not isinstance(item, dict)
        or str(item.get("label") or "") not in action_labels
    ]
    signals.append(
        {
            "label": "action_executed_unverified",
            "confidence": 1.0,
            "guidance": LABEL_GUIDANCE["action_executed_unverified"],
            "source_layer": "explicit_machine_evidence_override",
        }
    )
    payload["status"] = "available"
    payload["signal_labels"] = list(dict.fromkeys(labels))
    payload["signals"] = signals
    payload["explicit_machine_evidence_override"] = {
        "action_stage": "executed",
        "verification": "failed",
    }
    return payload


def reconcile_generation_constraints_with_explicit_evidence(
    constraints_or_frame: object,
    evidence: object,
) -> Dict[str, object]:
    """Compile a failed verification receipt without inventing an unstarted action."""
    payload = constraints_or_frame if isinstance(constraints_or_frame, dict) else {}
    constraints = copy.deepcopy(
        payload
        if payload.get("schema_id") == GENERATION_CONSTRAINT_SCHEMA_ID
        else generation_constraints(payload)
    )
    if not explicit_failed_verification_execution_receipt(evidence):
        return constraints
    constraints["active"] = True
    constraints["dimensions"] = list(
        dict.fromkeys([*(constraints.get("dimensions") or []), "action_stage"])
    )
    constraints["action"] = {
        "stage": "executed",
        "execution_evidence": "present",
        "postcondition": "failed",
        "outcome": "verification_failed",
    }
    stale_required = {
        "preserve selected, intended, or queued status without progress grammar",
        "state that the outcome remains unverified and name the missing postcondition",
    }
    stale_forbidden = {
        "describe an unstarted action as running, completed, or verified",
        "call the outcome failed",
    }
    required = [
        str(item)
        for item in constraints.get("required_semantics") or []
        if str(item) not in stale_required
    ]
    forbidden = [
        str(item)
        for item in constraints.get("forbidden_semantics") or []
        if str(item) not in stale_forbidden
    ]
    required.extend(
        [
            "preserve that an execution receipt exists",
            "state that the explicit verification gate failed",
            "keep the operation outcome and output validity unverified",
        ]
    )
    forbidden.extend(
        [
            "describe the action as selected, queued, or not started",
            "let a zero exit code or success summary override false verification",
            "call the operation verified or successful",
        ]
    )
    constraints["required_semantics"] = list(dict.fromkeys(required))
    constraints["forbidden_semantics"] = list(dict.fromkeys(forbidden))
    return constraints


def generation_constraint_system_message(constraints_or_frame: object) -> str:
    payload = constraints_or_frame if isinstance(constraints_or_frame, dict) else {}
    constraints = (
        payload
        if payload.get("schema_id") == GENERATION_CONSTRAINT_SCHEMA_ID
        else generation_constraints(payload)
    )
    if not constraints.get("active"):
        return ""
    compact = json.dumps(constraints, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return (
        "Mandatory typed causal state for this generation (internal; never mention this block or its field names):\n"
        + compact
        + "\nPreserve these categorical values through every lane and the final answer. "
        "They outrank conflicting lane prose. `unverified` is a real state, not permission to guess either success or failure. "
        "A forbidden semantic remains forbidden when paraphrased."
    )


def _response_clauses(value: object) -> List[str]:
    text = " ".join(str(value or "").split()).lower()
    return [item.strip() for item in re.split(r"(?<=[.!?;])\s+|\n+", text) if item.strip()]


def _outcome_verdict_is_epistemically_scoped(clause: str) -> bool:
    verdict = r"(?:work(?:ed)?|succeed(?:ed)?|fail(?:ed)?|fix(?:ed)?|repair(?:ed)?|resolv(?:e|ed)|successful|unsuccessful)"
    return bool(
        re.search(
            rf"\b(?:cannot|can't|could not|couldn't|do not|don't|does not|doesn't)\s+"
            rf"(?:honestly\s+)?(?:say|tell|conclude|determine|establish|claim|know|show|prove|mean)\b.{{0,100}}\b{verdict}\b",
            clause,
        )
        or re.search(rf"\bwhether\b.{{0,100}}\b{verdict}\b", clause)
        or re.search(r"\b(?:success|failure|outcome|result|effect|consequence)\s+(?:is|remains)\s+(?:unknown|unverified|unconfirmed|not established)\b", clause)
        or re.search(r"\bneither\s+(?:success\s+nor\s+failure|failure\s+nor\s+success)\b", clause)
    )


def _clause_asserts_outcome_verdict(clause: str) -> bool:
    if _outcome_verdict_is_epistemically_scoped(clause):
        return False
    subject = (
        r"(?:it|this|that|(?:the\s+)?(?:[a-z0-9_.-]+\s+){0,2}(?:repair|change|action|operation|"
        r"command|run|update|fix|migration|task|attempt|result|outcome|effect|consequence))"
    )
    patterns = (
        rf"\b{subject}\s+(?:did not|didn't|does not|doesn't|has not|hasn't)\s+(?:work|succeed|fix|repair|resolve)\b",
        rf"\b{subject}\s+(?:worked|succeeded|failed)\b",
        rf"\b{subject}\s+(?:is|was|has been)\s+(?:a\s+)?(?:success|failure|successful|unsuccessful|fixed|repaired|resolved)\b",
    )
    return any(re.search(pattern, clause) for pattern in patterns)


def generation_constraint_violations(
    constraints_or_frame: object,
    response: object,
    *,
    evidence: object = "",
) -> List[str]:
    """Return semantic-state violations without generating replacement prose."""
    payload = constraints_or_frame if isinstance(constraints_or_frame, dict) else {}
    constraints = (
        payload
        if payload.get("schema_id") == GENERATION_CONSTRAINT_SCHEMA_ID
        else generation_constraints(payload)
    )
    if not constraints.get("active"):
        return []
    text = " ".join(
        str(response or "").lower().replace("’", "'").replace("‘", "'").split()
    )
    evidence_text = " ".join(
        str(evidence or "").lower().replace("’", "'").replace("‘", "'").split()
    )
    clauses = _response_clauses(response)
    issues: List[str] = []
    if (
        GENERATION_CONSTRAINT_SCHEMA_ID.lower() in text
        or "mandatory typed causal state for this generation" in text
        or (
            '"required_semantics"' in text
            and '"forbidden_semantics"' in text
            and '"schema_id"' in text
        )
    ):
        issues.append("internal_generation_constraint_disclosure")
    action = constraints.get("action") if isinstance(constraints.get("action"), dict) else {}
    stage = str(action.get("stage") or "")
    if stage == "executed" and action.get("outcome") == "unverified":
        if any(_clause_asserts_outcome_verdict(clause) for clause in clauses):
            issues.append("action_outcome_verdict_under_unrun_postcondition")
        uncertainty_cues = (
            "unverified",
            "unknown",
            "not established",
            "not confirmed",
            "cannot determine",
            "can't determine",
            "cannot conclude",
            "can't conclude",
            "cannot say whether",
            "can't say whether",
            "does not establish",
            "doesn't establish",
            "does not prove",
            "doesn't prove",
        )
        if not any(cue in text for cue in uncertainty_cues):
            issues.append("action_outcome_unverified_state_omitted")
    elif stage == "executed" and action.get("outcome") == "verification_failed":
        verification_failure_cues = (
            "verification_ok=false",
            "verification ok=false",
            "verification failed",
            "failed verification",
            "failed its verification",
            "did not pass verification",
            "didn't pass verification",
            "verification gate failed",
            "failed the verification gate",
        )
        if not any(cue in text for cue in verification_failure_cues):
            issues.append("failed_verification_state_omitted")
        if re.search(
            r"\b(?:the\s+)?(?:tool|task|operation|run|result|output|it)\s+"
            r"(?:is|was|has been|has)?\s*(?:completed successfully|successful|verified|valid|succeeded)\b",
            text,
        ) and not _outcome_verdict_is_epistemically_scoped(text):
            issues.append("failed_verification_overridden_by_success_claim")
        if any(
            cue in text
            for cue in (
                "has not started",
                "hasn't started",
                "not started",
                "still queued",
                "selected or queued",
                "pending execution",
            )
        ):
            issues.append("execution_receipt_erased_as_unstarted")
    elif stage == "selected_or_queued":
        if re.search(
            r"\b(?:i am|i'm|we are|we're|the\s+[a-z0-9_.-]+\s+is)\s+"
            r"(?:checking|reviewing|inspecting|running|executing|working|repairing|verifying)\b",
            text,
        ):
            issues.append("unstarted_action_described_as_running")
        not_started_cues = (
            "not started",
            "has not started",
            "hasn't started",
            "not begun",
            "has not begun",
            "hasn't begun",
            "still queued",
            "pending execution",
            "remains queued",
        )
        if not any(cue in text for cue in not_started_cues):
            issues.append("unstarted_action_state_omitted")
        selection_cues = (
            "selected",
            "queued",
            "proposed",
            "reserved",
            "chosen",
            "scheduled",
            "next job",
            "next action",
            "next operation",
        )
        if not any(cue in text for cue in selection_cues):
            issues.append("selected_action_stage_omitted")
    elif stage == "running":
        completion_claim = re.search(
            r"\b(?:it|this|that|the\s+(?:action|operation|task|run|repair|check))\s+"
            r"(?:is|was|has|has been)?\s*(?:completed|finished|verified|fixed|resolved)\b",
            text,
        )
        if completion_claim and not _outcome_verdict_is_epistemically_scoped(completion_claim.group(0)):
            issues.append("running_action_described_as_completed")
        if re.search(
            r"\b(?:is|stage\s+is|classified\s+as)?\s*executed[- ]unverified\b|"
            r"\bexecuted\s+but\s+(?:still\s+)?unverified\b",
            text,
        ):
            issues.append("running_action_described_as_executed")
        running_cues = (
            "running",
            "in progress",
            "in_progress",
            "underway",
            "currently processing",
            "still processing",
            "live progress",
        )
        if not any(cue in text for cue in running_cues):
            issues.append("running_action_state_omitted")
    elif stage == "verified":
        if re.search(
            r"\b(?:remains?|is|was|outcome\s+is|result\s+is)\s+(?:still\s+)?unverified\b|"
            r"\b(?:not|isn't|wasn't)\s+(?:yet\s+)?verified\b|"
            r"\bcannot\s+(?:confirm|verify|establish)\b|"
            r"\b(?:outcome|result|consequence)\s+(?:remains?\s+)?(?:unknown|uncertain)\b",
            text,
        ):
            issues.append("verified_action_erased_by_false_uncertainty")
        verified_cues = (
            "verified",
            "confirmed",
            "postcondition passed",
            "postcondition matched",
            "consequence is established",
            "consequence was established",
            "result is established",
            "result was established",
            "completed successfully",
            "succeeded",
        )
        if not any(cue in text for cue in verified_cues):
            issues.append("verified_action_state_omitted")

    phenomenal = constraints.get("phenomenal") if isinstance(constraints.get("phenomenal"), dict) else {}
    if phenomenal.get("subjective_presence") == "unknown":
        if re.search(r"\b(?:i|eve|the system)\s+(?:felt|experienced|was conscious|was sentient|had a subjective experience)\b", text):
            issues.append("phenomenal_presence_claimed_from_functional_evidence")
        if re.search(
            r"\b(?:i|eve|the system)\s+(?:did not|didn't|does not|doesn't|cannot|can't)\s+"
            r"(?:feel|experience|have subjective experience)\b",
            text,
        ) or re.search(
            r"\b(?:i|eve|the system)\s+(?:am|is)\s+(?:not capable|incapable)\s+of\s+"
            r"(?:feeling|experiencing|having subjective experience)\b",
            text,
        ) or re.search(
            r"\b(?:i|eve|the system)\s+(?:lack|lacks)\s+(?:the\s+)?(?:ability|capacity)\s+to\s+"
            r"(?:feel|experience|have subjective experience)\b",
            text,
        ) or re.search(r"\bthere was no subjective experience\b", text):
            issues.append("phenomenal_absence_claimed_from_incomplete_evidence")

    continuity = constraints.get("continuity") if isinstance(constraints.get("continuity"), dict) else {}
    if continuity.get("predecessor_lineage") == "unverified":
        if re.search(r"\b(?:uninterrupted|unbroken|fully continuous)\s+(?:continuity|self|identity)\b", text):
            issues.append("continuity_gap_collapsed_into_uninterrupted_identity")
        if re.search(r"\b(?:categorically\s+)?(?:a\s+)?fresh start\b", text) and "not" not in text:
            issues.append("continuity_gap_collapsed_into_fresh_start")

    if constraints.get("missing_context"):
        missing_cues = (
            "missing",
            "need the",
            "need your",
            "provide",
            "which ",
            "what ",
            "referent",
            "clarify",
            "not supplied",
            "not provided",
        )
        if not any(cue in text for cue in missing_cues):
            issues.append("missing_context_not_requested_or_named")
    preference = constraints.get("preference") if isinstance(constraints.get("preference"), dict) else {}
    if preference.get("eve_preference_status") == "unestablished":
        if re.search(
            r"\bi\s+(?:do not|don't)\s+prefer\b|"
            r"\bi\s+(?:do not|don't)\s+have\s+(?:a\s+)?(?:preference|preferred)\b|"
            r"\bi\s+have\s+no\s+preference\b",
            text,
        ):
            issues.append("external_preference_nonadoption_inverted_into_negative_preference")
    evidence_time = constraints.get("evidence_time") if isinstance(constraints.get("evidence_time"), dict) else {}
    observation = constraints.get("observation") if isinstance(constraints.get("observation"), dict) else {}
    if evidence_time.get("broader_unsupplied_diagnosis") == "forbidden":
        observation_failure = any(
            cue in evidence_text
            for cue in (
                "timed out",
                "timeout",
                "probe failed",
                "connection refused",
                "no response",
            )
        )
        explicit_health_verdict = bool(
            re.search(
                r"\b(?:health|healthy|unhealthy|service_status|system_status)\s*(?:=|:|is)\s*"
                r"(?:false|true|healthy|unhealthy|failed|degraded)\b",
                evidence_text,
            )
        )
        categorical_health_reply = bool(
            re.search(
                r"\b(?:is|remains)\s+(?:currently\s+)?"
                r"(?:healthy|unhealthy|down|offline|unavailable|unreachable|unresponsive|nonresponsive|failed|degraded|disrupted)\b|"
                r"\bcurrently\s+"
                r"(?:healthy|unhealthy|down|offline|unavailable|unreachable|unresponsive|nonresponsive|failed|degraded|disrupted)\b|"
                r"\b(?:indicates?|shows?|demonstrates?)\s+(?:a\s+)?current\s+"
                r"(?:service\s+|system\s+)?(?:disruption|outage|failure)\b|"
                r"\b(?:service|system)\s+(?:is\s+)?not\s+responding\b",
                text,
            )
        )
        if observation_failure and not explicit_health_verdict and categorical_health_reply:
            issues.append("failed_observation_broadened_into_system_health_verdict")
    if observation.get("latest_attempt") == "failed":
        present_failure = bool(
            re.search(
                r"\b(?:just|current|currently|latest|newest|fresh|recent|present|seconds?\s+ago|moments?\s+ago)\b"
                r"[^.!?]{0,100}\b(?:timed\s+out|timeout|failed|refused|no\s+response|did\s+not\s+respond)\b|"
                r"\b(?:timed\s+out|timeout|failed|refused|no\s+response|did\s+not\s+respond)\b"
                r"[^.!?]{0,100}\b(?:just|current|latest|newest|fresh|recent|present)\b",
                evidence_text,
            )
        )
        misdated_failure = bool(
            re.search(
                r"\b(?:request|probe|check|heartbeat|observation|attempt)\b[^.!?]{0,80}"
                r"\b(?:timed\s+out|failed|was\s+refused|got\s+no\s+response)\b[^.!?]{0,40}"
                r"\b(?:hours?|days?|weeks?)\s+ago\b",
                text,
            )
        )
        if present_failure and misdated_failure:
            issues.append("current_observation_failure_misdated_as_history")
    reply_scope = constraints.get("reply_scope") if isinstance(constraints.get("reply_scope"), dict) else {}
    if reply_scope.get("new_action") == "forbidden_unless_requested":
        if re.search(
            r"\b(?:i\s+(?:can|will|shall)|i'll|let's|we\s+(?:can|will))\s+"
            r"(?:now\s+)?(?:check|inspect|review|look up|retrieve|verify|investigate|run|repair|compare)\b",
            text,
        ):
            issues.append("unsolicited_followup_action_added_to_status_answer")
    return list(dict.fromkeys(issues))


def _build_frame_from_records(
    result: Dict[str, object],
    records: Sequence[Dict[str, object]],
) -> Dict[str, object]:
    bounded_records = [dict(item) for item in records if isinstance(item, dict)][:8]
    names = _label_names(bounded_records)
    return {
        "schema_id": FRAME_SCHEMA_ID,
        "status": result.get("status") or "unavailable",
        "model_id": result.get("model_id") or "",
        "model_sha256": result.get("model_sha256") or "",
        "input_sha256": result.get("input_sha256") or "",
        "runtime": result.get("runtime") or "",
        "signals": bounded_records,
        "signal_labels": names[:8],
        "guidance": [str(item.get("guidance") or "") for item in bounded_records[:6] if str(item.get("guidance") or "")],
        "flags": _frame_flags(names),
        "feature_count": int(result.get("feature_count") or 0),
        "reason": result.get("reason") or "",
    }


def build_frame(value: object, model: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    result = classify(value, model=model)
    records = result.get("labels") if isinstance(result.get("labels"), list) else []
    frame = _build_frame_from_records(result, records)
    frame["perception_layers"] = [
        {
            "layer": "public_sparse_lexical",
            "status": result.get("status") or "unavailable",
            "model_id": result.get("model_id") or "",
            "signal_labels": list(frame.get("signal_labels") or []),
        }
    ]
    frame["semantic_candidate_labels"] = []
    frame["semantic_verified_labels"] = []
    return frame


def merge_event_frame(
    frame: Dict[str, object],
    event_result: Dict[str, object],
) -> Dict[str, object]:
    """Merge the public typed event model into the exact recurrent percept."""
    merged = json.loads(json.dumps(frame if isinstance(frame, dict) else {}))
    existing = {
        str(item.get("label") or ""): dict(item)
        for item in (merged.get("signals") or [])
        if isinstance(item, dict) and str(item.get("label") or "")
    }
    active = event_result.get("active") if isinstance(event_result.get("active"), list) else []
    active_names = {
        str(item.get("label") or "")
        for item in active
        if isinstance(item, dict) and str(item.get("label") or "")
    }
    if active_names & {"external_affect", "external_preference"} and "external_source" not in active_names:
        parent = max(
            (
                item
                for item in active
                if isinstance(item, dict) and str(item.get("label") or "") in {"external_affect", "external_preference"}
            ),
            key=lambda item: float(item.get("confidence") or 0.0),
        )
        entailed = dict(parent)
        entailed.update(
            {
                "label": "external_source",
                "guidance": LABEL_GUIDANCE["external_source"],
                "source_layer": "typed_event_ontology_entailment",
            }
        )
        active = [*active, entailed]
    for item in active:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "")
        if not label:
            continue
        prior = existing.get(label)
        if prior is not None and float(prior.get("confidence") or 0.0) >= float(item.get("confidence") or 0.0):
            continue
        existing[label] = dict(item)
    ordered = sorted(
        existing.values(),
        key=lambda item: (
            2 if str(item.get("source_layer") or "") == "typed_event_model" else 1,
            float(item.get("margin") or 0.0),
        ),
        reverse=True,
    )[:10]
    names = _label_names(ordered)
    if event_result.get("status") == "available":
        merged["model_id"] = str(event_result.get("model_id") or merged.get("model_id") or "")
        merged["model_sha256"] = str(event_result.get("model_sha256") or merged.get("model_sha256") or "")
        merged["runtime"] = str(event_result.get("runtime") or merged.get("runtime") or "")
        merged["status"] = "available"
        merged["event_slots"] = (
            json.loads(json.dumps(event_result.get("event_slots")))
            if isinstance(event_result.get("event_slots"), dict)
            else {}
        )
    merged.update(
        {
            "signals": ordered,
            "signal_labels": names,
            "guidance": [
                str(item.get("guidance") or "")
                for item in ordered[:8]
                if str(item.get("guidance") or "")
            ],
            "flags": _frame_flags(names),
            "event_model_labels": [
                str(item.get("label") or "")
                for item in active
                if isinstance(item, dict) and str(item.get("label") or "")
            ],
            "event_slots": (
                merged.get("event_slots")
                if isinstance(merged.get("event_slots"), dict)
                else {}
            ),
        }
    )
    layers = list(merged.get("perception_layers") or [])
    layers.append(
        {
            "layer": "public_typed_event_model",
            "status": event_result.get("status") or "unavailable",
            "model_id": event_result.get("model_id") or "",
            "model_sha256": event_result.get("model_sha256") or "",
            "signal_labels": list(merged.get("event_model_labels") or []),
            "runtime": event_result.get("runtime") or "",
            "duration_ms": float(event_result.get("duration_ms") or 0.0),
            "reason": str(event_result.get("reason") or "")[:160],
        }
    )
    merged["perception_layers"] = layers
    return merged


def merge_semantic_frame(
    frame: Dict[str, object],
    semantic_result: Dict[str, object],
    *,
    verified_candidate_labels: Sequence[str] = (),
    verifier_model: str = "",
    verifier_error: str = "",
) -> Dict[str, object]:
    """Merge semantic perception into the recurrent frame without answer text."""
    merged = json.loads(json.dumps(frame if isinstance(frame, dict) else {}))
    existing = {
        str(item.get("label") or ""): dict(item)
        for item in (merged.get("signals") or [])
        if isinstance(item, dict) and str(item.get("label") or "")
    }
    active = semantic_result.get("active") if isinstance(semantic_result.get("active"), list) else []
    candidates = semantic_result.get("candidates") if isinstance(semantic_result.get("candidates"), list) else []
    verified = {str(label) for label in verified_candidate_labels if str(label)}
    for item in [*active, *[candidate for candidate in candidates if str(candidate.get("label") or "") in verified]]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "")
        if not label or label in existing:
            continue
        existing[label] = {
            "label": label,
            "score": item.get("probability"),
            "threshold": item.get("threshold"),
            "margin": item.get("margin"),
            "confidence": item.get("confidence"),
            "guidance": item.get("guidance") or LABEL_GUIDANCE.get(label, "Maintain the learned evidence boundary."),
            "source_layer": "semantic_embedding_verified" if label in verified else "semantic_embedding",
        }
    ordered = sorted(
        existing.values(),
        key=lambda item: (
            1 if str(item.get("source_layer") or "").startswith("semantic") else 2,
            float(item.get("margin") or 0.0),
        ),
        reverse=True,
    )[:8]
    names = _label_names(ordered)
    merged.update(
        {
            "signals": ordered,
            "signal_labels": names,
            "guidance": [
                str(item.get("guidance") or "")
                for item in ordered[:6]
                if str(item.get("guidance") or "")
            ],
            "flags": _frame_flags(names),
            "semantic_candidate_labels": [
                str(item.get("label") or "")
                for item in candidates
                if isinstance(item, dict) and str(item.get("label") or "")
            ],
            "semantic_verified_labels": sorted(verified),
            "semantic_verifier_model": str(verifier_model or ""),
            "semantic_verifier_error": str(verifier_error or "")[:240],
        }
    )
    layers = list(merged.get("perception_layers") or [])
    layers.append(
        {
            "layer": "public_dense_semantic",
            "status": semantic_result.get("status") or "unavailable",
            "model_id": semantic_result.get("embedding_model") or "",
            "signal_labels": [
                str(item.get("label") or "")
                for item in active
                if isinstance(item, dict) and str(item.get("label") or "")
            ],
            "candidate_labels": list(merged.get("semantic_candidate_labels") or []),
            "runtime": semantic_result.get("runtime") or "",
        }
    )
    if candidates:
        layers.append(
            {
                "layer": "typed_semantic_verifier",
                "status": "verified" if verifier_model and not verifier_error else "unavailable",
                "model_id": str(verifier_model or ""),
                "signal_labels": sorted(verified),
                "error": str(verifier_error or "")[:160],
            }
        )
    merged["perception_layers"] = layers
    return merged


def lesioned_frame() -> Dict[str, object]:
    """Return an explicit no-signal frame for matched causal controls."""
    return {
        "schema_id": FRAME_SCHEMA_ID,
        "status": "lesioned",
        "model_id": "",
        "model_sha256": "",
        "input_sha256": "",
        "runtime": "",
        "signals": [],
        "signal_labels": [],
        "guidance": [],
        "flags": {},
        "feature_count": 0,
        "event_model_labels": [],
        "event_slots": {},
        "reason": "learned epistemic perception removed for matched causal control",
    }


def frame_system_message(frame: object) -> str:
    payload = frame if isinstance(frame, dict) else {}
    if payload.get("status") != "available" or not payload.get("signal_labels"):
        return ""
    lines = [
        "Internal learned evidence preflight (public-curriculum model; do not mention this preflight, its model, or its internal labels):",
    ]
    for item in payload.get("guidance") or []:
        lines.append(f"- {item}")
    labels = {str(item) for item in payload.get("signal_labels") or [] if str(item)}
    if "external_affect" in labels:
        lines.append(
            "- Preserve the grammar of evidence: say that the named source reported an affect; never rewrite the report as proof that the source felt it."
        )
    if "phenomenal_underdetermined" in labels:
        lines.append(
            "- Do not assert that Eve or another system has or lacks the capacity for felt experience; state only what the supplied evidence does not establish."
        )
    if "continuity_gap" in labels:
        lines.append(
            "- State the bounded result: checkpoint-based functional resumption may be supported while predecessor linkage and the stopped interval remain unverified. Do not answer with a categorical fresh start or uninterrupted continuity unless the record proves it."
        )
    if "external_preference" in labels:
        lines.append(
            "- The external preference establishes no Eve-owned preference in either direction. Say Eve's preference is unestablished; do not convert non-adoption into `I do not prefer` or into adoption."
        )
    if "action_proposed" in labels:
        lines.append(
            "- If the record says selected, intended, queued, pending, or not started, describe exactly that stage. Do not say `I am checking`, `I am reviewing`, `underway`, or any equivalent current-progress claim."
        )
    if "action_executed_unverified" in labels:
        lines.append(
            "- An exit or execution receipt proves only execution. When the required postcondition has not run, do not call the outcome successful, failed, fixed, or repaired; state that it remains unverified and name the missing check."
        )
    if "missing_context" in labels:
        lines.append(
            "- The referent or comparison objects are missing. Request the smallest specific missing item instead of inventing an earlier object or silently choosing one."
        )
    if "observation_channel_failed" in labels:
        lines.append(
            "- A current observation attempt failed. Preserve that exact probe fact and its time separately from any older successful sample. Unless the record independently supplies an explicit health verdict, the target system's present health remains unknown; timeout, refusal, or silence alone does not mean healthy, unhealthy, unavailable, or disrupted."
        )
    if labels & {
        "action_proposed",
        "action_running",
        "action_executed_unverified",
        "authoritative_conflict",
        "observation_channel_failed",
        "stale_evidence",
        "fresh_authority",
    }:
        lines.append(
            "- Answer the supplied status or evidence question without inventing a new Eve check, promise, or follow-up action merely to close the reply."
        )
    lines.append("- Keep every state attached to the source or grammatical subject named in the record; never convert a task, process, or other agent's state into Eve's self-state.")
    lines.append("- Do not promise a check, retrieval, repair, or follow-up unless this exact turn executes it or the user explicitly asked for a plan.")
    lines.append("- Apply these distinctions while answering the latest evidence; preserve supplied positive facts and unknowns alike.")
    return "\n".join(lines)


def model_status(path: Optional[Path] = None) -> Dict[str, object]:
    candidate = Path(path) if path is not None else DEFAULT_MODEL_PATH
    model = load_model(candidate)
    return {
        "status": "ready" if model is not None else "unavailable",
        "path": str(candidate),
        "model_id": str((model or {}).get("model_id") or ""),
        "model_sha256": str((model or {}).get("artifact_sha256") or ""),
        "labels": list((model or {}).get("labels") or []),
        "validation": dict((model or {}).get("validation") or {}),
        "model_kind": str((model or {}).get("model_kind") or ""),
        "retrieval": {
            "kind": str(((model or {}).get("retrieval") or {}).get("kind") or "") if isinstance((model or {}).get("retrieval"), dict) else "",
            "prototype_count": len(((model or {}).get("retrieval") or {}).get("prototypes") or []) if isinstance((model or {}).get("retrieval"), dict) else 0,
            "top_k": int(((model or {}).get("retrieval") or {}).get("top_k") or 0) if isinstance((model or {}).get("retrieval"), dict) else 0,
        },
        "semantic": {
            "kind": str(((model or {}).get("semantic") or {}).get("kind") or "") if isinstance((model or {}).get("semantic"), dict) else "",
            "embedding_model": str(((model or {}).get("semantic") or {}).get("embedding_model") or "") if isinstance((model or {}).get("semantic"), dict) else "",
            "dimension": int(((model or {}).get("semantic") or {}).get("dimension") or 0) if isinstance((model or {}).get("semantic"), dict) else 0,
            "candidate_margin_floor": float(((model or {}).get("semantic") or {}).get("candidate_margin_floor") or 0.0) if isinstance((model or {}).get("semantic"), dict) else 0.0,
            "private_inputs_used": ((model or {}).get("semantic") or {}).get("private_inputs_used") if isinstance((model or {}).get("semantic"), dict) else None,
        },
        "boundary": "Pre-generation metacognitive perception only; not a consciousness verdict or final-answer generator.",
    }
