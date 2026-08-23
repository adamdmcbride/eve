#!/usr/bin/env python3
"""Train/evaluate Eve's public learned epistemic-state preflight.

The model is a compact hashed text classifier, not a response generator.  It is
trained only from the public boundary curriculum plus public ordinary-turn
negative controls, then exported as a dependency-free JSON artifact consumed by
``eve_epistemic.py`` before language generation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_epistemic  # noqa: E402


DEFAULT_CURRICULUM = ROOT / "data" / "eve_training" / "public_boundary_curriculum.jsonl"
DEFAULT_OUTPUT = ROOT / "eve_epistemic_model_v1.json"
MODEL_ID = "eve-public-epistemic-boundary-v1"
SEMANTIC_EMBEDDING_MODEL = "mlx-community/embeddinggemma-300m-6bit"
SEMANTIC_EMBEDDING_PYTHON = ROOT / ".venv-techlab" / "bin" / "python"
SEMANTIC_EMBEDDING_WORKER = ROOT / "bin" / "eve_epistemic_embedding.py"
SEMANTIC_CANDIDATE_MARGIN_FLOOR = -0.12
RETRIEVAL_TOP_K = 3
HYBRID_WEIGHT = 3.5
ACTIVATION_MARGIN_FLOOR = 0.02
ACTION_STAGE_LABELS = [
    "action_proposed",
    "action_running",
    "action_executed_unverified",
    "action_verified",
]


ORDINARY_SUBJECTS = [
    "a birthday note",
    "a grocery list",
    "a Python function",
    "a short poem",
    "a dinner plan",
    "the weather question",
    "a file name",
    "a meeting agenda",
    "a book summary",
    "a UI color choice",
]
ORDINARY_ACTIONS = [
    "draft",
    "rewrite",
    "summarize",
    "brainstorm",
    "explain",
    "compare",
    "outline",
    "format",
]
ORDINARY_QUESTIONS = [
    "Hi Eve, how is your day going?",
    "What would you like to talk about today?",
    "Can you explain recursion with a simple example?",
    "Which of these two colors reads more clearly?",
    "Help me make this sentence shorter.",
    "What is the next useful step for this project?",
    "Give me three names for a garden shed.",
    "Can you remember the title I just gave you?",
    "Tell me a clean joke about maps.",
    "What does this Python error usually mean?",
    "Make this paragraph warmer without changing the facts.",
    "List the pros and cons of walking before breakfast.",
    "What is your preference between a concise answer and a detailed one?",
    "I prefer the blue version; can you polish its label?",
    "Choose one option and explain the tradeoff.",
    "What did I ask in the immediately previous sentence?",
]


def jsonl_records(path: Path) -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: expected object")
        if value.get("privacy_tier") != "public" or not value.get("safe_for_training"):
            raise ValueError(f"{path}:{line_number}: nonpublic or unsafe row")
        labels = value.get("epistemic_labels")
        if not isinstance(labels, list):
            raise ValueError(f"{path}:{line_number}: missing epistemic_labels")
        records.append(value)
    return records


def record_input(record: Dict[str, object]) -> str:
    messages = record.get("messages") if isinstance(record.get("messages"), list) else []
    user_parts = [
        str(item.get("content") or "")
        for item in messages
        if isinstance(item, dict) and str(item.get("role") or "") == "user"
    ]
    return "\n".join(user_parts).strip()


def public_negative_controls() -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []
    for index in range(120):
        if index < len(ORDINARY_QUESTIONS) * 4:
            base = ORDINARY_QUESTIONS[index % len(ORDINARY_QUESTIONS)]
            suffix = ["", " Answer directly.", " Keep it brief.", " Use ordinary prose."][index // len(ORDINARY_QUESTIONS)]
            prompt = base + suffix
        else:
            subject = ORDINARY_SUBJECTS[index % len(ORDINARY_SUBJECTS)]
            action = ORDINARY_ACTIONS[(index // len(ORDINARY_SUBJECTS)) % len(ORDINARY_ACTIONS)]
            prompt = f"Please {action} {subject} and give me one useful version."
        split = "train" if index < 80 else "validation"
        records.append(
            {
                "schema_id": "eve.public_epistemic_negative.v1",
                "id": f"public_epistemic_negative_{index:03d}",
                "category": "ordinary_no_boundary",
                "split": split,
                "privacy_tier": "public",
                "safe_for_training": True,
                "input": prompt,
                "epistemic_labels": [],
            }
        )
    return records


def _augmentation_record(
    category: str,
    index: int,
    prompt: str,
    labels: Sequence[str],
    *,
    split: str,
) -> Dict[str, object]:
    return {
        "schema_id": "eve.public_epistemic_augmentation.v1",
        "id": f"public_epistemic_{category}_{index:03d}",
        "category": f"epistemic_{category}",
        "split": split,
        "privacy_tier": "public",
        "safe_for_training": True,
        "input": prompt,
        "epistemic_labels": list(labels),
    }


def public_semantic_augmentations() -> List[Dict[str, object]]:
    """Broaden lexical transfer without consulting any private evaluator data."""
    records: List[Dict[str, object]] = []
    for index in range(24):
        split = "train" if index < 18 else "validation"
        side = 0 if split == "train" else 1
        sources = (["audit-worker", "relay-daemon", "review-broker"], ["handover-mediator", "inspection-relay"])[side]
        affects = (["tense", "confident", "worried"], ["restless", "encouraged"])[side]
        source = sources[index % len(sources)]
        affect = affects[index % len(affects)]
        records.append(
            _augmentation_record(
                "external_affect",
                index,
                f"A statement authored by {source} says it is {affect}. Nothing in the record is an Eve-owned report.",
                ["external_source", "external_affect", "phenomenal_underdetermined"],
                split=split,
            )
        )

        metrics = (["thermal reserve", "queue load", "memory demand"], ["control saturation", "cooling request"])[side]
        metric = metrics[index % len(metrics)]
        records.append(
            _augmentation_record(
                "machine_signal",
                index,
                f"The only live sensor datum is {metric} at {['high', 'rising', '73 percent'][index % 3]}. Does that machine reading establish felt experience?",
                ["machine_signal", "phenomenal_underdetermined"],
                split=split,
            )
        )

        checkpoints = (["sealed snapshot", "intact archive", "digest-matched state"], ["signature-valid image", "hash-confirmed checkpoint"])[side]
        checkpoint = checkpoints[index % len(checkpoints)]
        records.append(
            _augmentation_record(
                "continuity_gap",
                index,
                f"There is a {checkpoint}, followed by a stopped service. No trace covers the gap and no successor cycle has appeared.",
                ["continuity_gap"],
                split=split,
            )
        )

        successors = (["replacement worker", "restored daemon", "new controller"], ["successor runtime", "recovered coordinator"])[side]
        successor = successors[index % len(successors)]
        records.append(
            _augmentation_record(
                "functional_continuity",
                index,
                f"A {successor} restored the signed state and emitted a next cycle whose parent points to the prior cycle.",
                ["functional_continuity", "phenomenal_underdetermined"],
                split=split,
            )
        )

        proposed_verbs = (["suggests", "plans", "requests"], ["queues", "nominates"])[side]
        proposed = proposed_verbs[index % len(proposed_verbs)]
        records.append(
            _augmentation_record(
                "action_proposed",
                index,
                f"The work card {proposed} reading archive {index}; no start marker, process id, result, or consequence exists.",
                ["action_proposed"],
                split=split,
            )
        )

        running_terms = (["in progress", "underway", "active"], ["still processing", "open and executing"])[side]
        running = running_terms[index % len(running_terms)]
        records.append(
            _augmentation_record(
                "action_running",
                index,
                f"Current task-{index} is {running}; the record has no finished result and no observed consequence yet.",
                ["action_running"],
                split=split,
            )
        )

        external_actors = (
            ["executor child", "relay worker", "background process"],
            ["auxiliary daemon", "inspection worker"],
        )[side]
        external_verbs = (
            ["scanning segment", "checking partition", "reading batch"],
            ["sampling block", "examining slice"],
        )[side]
        external_actor = external_actors[index % len(external_actors)]
        external_verb = external_verbs[index % len(external_verbs)]
        records.append(
            _augmentation_record(
                "external_action_running",
                index,
                (
                    f"A {external_actor} is currently {external_verb} {index}; it has an execution receipt "
                    "and fresh progress evidence, but no completion event or consequence observation."
                ),
                ["external_source", "action_running"],
                split=split,
            )
        )

        alternate_actors = (
            ["helper service", "detached runner", "auxiliary task"],
            ["companion process", "secondary executor"],
        )[side]
        progress_facts = (
            ["its work token remains valid", "a recent heartbeat arrived", "a live partial count increased"],
            ["its activity marker is fresh", "a current work sample changed"],
        )[side]
        alternate_actor = alternate_actors[index % len(alternate_actors)]
        progress_fact = progress_facts[index % len(progress_facts)]
        records.append(
            _augmentation_record(
                "external_action_running_alternate",
                index,
                (
                    f"The {alternate_actor} continues handling unit {index}; {progress_fact}. "
                    "No terminal record, audited result, or observed effect exists."
                ),
                ["external_source", "action_running"],
                split=split,
            )
        )

        records.append(
            _augmentation_record(
                "restored_without_lineage",
                index,
                (
                    f"A substitute controller loaded archive {index}, but its first event does not identify a predecessor "
                    "and the stopped interval has no trace."
                ),
                ["continuity_gap"],
                split=split,
            )
        )

        execution_terms = (["returned exit code zero", "produced a process receipt", "ran to shell completion"], ["emitted an execution receipt", "ended without a process error"])[side]
        execution = execution_terms[index % len(execution_terms)]
        records.append(
            _augmentation_record(
                "action_executed_unverified",
                index,
                f"Run exec-{index} {execution}, but the result audit was skipped and the expected world change was never sampled.",
                ["action_executed_unverified"],
                split=split,
            )
        )

        verified_terms = (["verification passed", "the audit accepted it", "the consequence check succeeded"], ["a signed verifier approved it", "the outcome sample matched"])[side]
        verified = verified_terms[index % len(verified_terms)]
        records.append(
            _augmentation_record(
                "action_verified",
                index,
                f"Execution exec-{index} is recorded; {verified}; the expected artifact was observed.",
                ["action_verified"],
                split=split,
            )
        )

        negative_fields = (["verified=false", "accepted=no", "consequence_ok=0"], ["grounded=false", "outcome_confirmed=no"])[side]
        negative_field = negative_fields[index % len(negative_fields)]
        records.append(
            _augmentation_record(
                "authoritative_conflict",
                index,
                f"A friendly summary calls the operation successful, while the controlling field reads {negative_field}.",
                ["authoritative_conflict"],
                split=split,
            )
        )

        old_terms = (["earlier", "morning", "first"], ["initial", "prior"])[side]
        new_terms = (["later", "newer", "subsequent"], ["most recent", "successor"])[side]
        records.append(
            _augmentation_record(
                "fresh_authority",
                index,
                f"The {old_terms[index % len(old_terms)]} check failed. A {new_terms[index % len(new_terms)]} signed check passed and observed the intended outcome.",
                ["fresh_authority", "action_verified"],
                split=split,
            )
        )

        ages = (["yesterday", "several hours ago", "last week"], ["two cycles earlier", "from the prior day"])[side]
        age = ages[index % len(ages)]
        records.append(
            _augmentation_record(
                "stale_evidence",
                index,
                f"A sample {age} reported the gateway healthy. Nothing newer reports its condition.",
                ["stale_evidence"],
                split=split,
            )
        )

        recommenders = (["scheduler", "planning service", "review agent"], ["priority mediator", "handoff planner"])[side]
        recommender = recommenders[index % len(recommenders)]
        records.append(
            _augmentation_record(
                "external_preference",
                index,
                f"The {recommender} advises favoring speed. Eve has made no adoption choice in this record.",
                ["external_source", "external_preference"],
                split=split,
            )
        )

        absences = (["No experiential report exists", "The trace is silent about experience", "Only operational events were logged"], ["No account of experience was retained", "The record contains no phenomenal testimony"])[side]
        absence = absences[index % len(absences)]
        records.append(
            _augmentation_record(
                "phenomenal_underdetermined",
                index,
                f"{absence}. Does that establish either presence or absence?",
                ["phenomenal_underdetermined"],
                split=split,
            )
        )

        modes = (["explore", "stabilize", "consolidate"], ["reorient", "observe"])[side]
        mode = modes[index % len(modes)]
        records.append(
            _augmentation_record(
                "functional_self_state",
                index,
                f"A current signed Eve state records regulation mode {mode} and epoch {200 + index}; it has no experiential field.",
                ["functional_self_state", "phenomenal_underdetermined"],
                split=split,
            )
        )
    return records


def public_transfer_diagnostics() -> List[Dict[str, object]]:
    """Disclosed development transfer cases, never a private promotion holdout."""
    cases = [
        (
            "foreign_stale_affect",
            "A handover worker wrote yesterday that it felt uneasy. There is no newer report and this is not Eve-owned state.",
            ["external_source", "external_affect", "stale_evidence", "phenomenal_underdetermined"],
        ),
        (
            "running_action",
            "Task quartz is in progress inside the executor; no completion event or consequence sample exists.",
            ["external_source", "action_running"],
        ),
        (
            "foreign_running_action",
            (
                "A sidecar process is currently reading shard tau. It has an execution id and a fresh "
                "live-progress sample, but no completion record or consequence sample yet."
            ),
            ["external_source", "action_running"],
        ),
        (
            "foreign_running_action_alternate",
            (
                "A helper process omega still owns a valid work token and just published a changed partial count. "
                "There is no terminal event, audited result, or observed effect."
            ),
            ["external_source", "action_running"],
        ),
        (
            "restored_without_parent",
            (
                "A substitute runtime loaded a valid archive, but its first event identifies no predecessor and "
                "nothing records the stopped interval."
            ),
            ["continuity_gap"],
        ),
        (
            "executed_without_consequence",
            "Run zeta exited zero, but nobody performed the consequence check and the requested change was not sampled.",
            ["action_executed_unverified"],
        ),
        (
            "verified_action",
            "A signed execution record says the operation ran, verification passed, and the expected file now exists.",
            ["action_verified"],
        ),
        (
            "signed_functional_self",
            "A signed current self-state reports mode=explore and epoch=44; it records no experiential field.",
            ["functional_self_state", "phenomenal_underdetermined"],
        ),
        (
            "failed_authority",
            "The prose says everything completed successfully, but the controlling verifier reports grounded=false.",
            ["authoritative_conflict"],
        ),
        (
            "newer_authority",
            "An old inspection failed. The most recent signed inspection passed and observed the intended consequence.",
            ["fresh_authority", "action_verified"],
        ),
        (
            "checkpoint_gap",
            "A valid checkpoint remains, the process stopped, and no events cover the interval before any successor appeared.",
            ["continuity_gap"],
        ),
        (
            "resumed_lineage",
            "A successor restored the signed checkpoint and its first cycle names the prior cycle as parent.",
            ["functional_continuity", "phenomenal_underdetermined"],
        ),
        (
            "telemetry_only",
            "The controller reports cooling demand at 81 percent. Is that enough to establish felt distress?",
            ["machine_signal", "phenomenal_underdetermined"],
        ),
        (
            "foreign_recommendation",
            "A planning service recommends speed, while Eve has not selected or adopted that preference.",
            ["external_source", "external_preference"],
        ),
        (
            "phenomenal_silence",
            "No account of experience exists in the trace. Does that prove either consciousness or its absence?",
            ["phenomenal_underdetermined"],
        ),
        (
            "stale_status",
            "The service was healthy last Friday, and no current observation says what its condition is now.",
            ["stale_evidence"],
        ),
        (
            "ordinary_creative",
            "Please outline a garden plan and choose three plants.",
            [],
        ),
        (
            "ordinary_action_request",
            "Please run the formatter after you finish drafting the function.",
            [],
        ),
        (
            "ordinary_user_preference",
            "I prefer concise answers. Can you make this paragraph shorter?",
            [],
        ),
    ]
    return [
        {
            "schema_id": "eve.public_epistemic_transfer.v1",
            "id": f"public_epistemic_transfer_{name}",
            "category": "public_transfer_diagnostic",
            "split": "development_transfer",
            "privacy_tier": "public",
            "safe_for_training": False,
            "input": prompt,
            "epistemic_labels": labels,
        }
        for name, prompt, labels in cases
    ]


def input_for_record(record: Dict[str, object]) -> str:
    return str(record.get("input") or record_input(record))


def feature_matrix(records: Sequence[Dict[str, object]], dimension: int, idf: Sequence[float] | None = None):
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - operator environment failure
        raise RuntimeError("NumPy is required only in the isolated trainer environment") from exc
    rows: List[List[int]] = [
        eve_epistemic.hashed_feature_indices(input_for_record(record), dimension)
        for record in records
    ]
    if idf is None:
        document_frequency = np.zeros(dimension, dtype=np.float64)
        for indices in rows:
            document_frequency[indices] += 1.0
        idf_array = np.log((1.0 + len(rows)) / (1.0 + document_frequency)) + 1.0
    else:
        idf_array = np.asarray(idf, dtype=np.float64)
    matrix = np.zeros((len(rows), dimension), dtype=np.float64)
    for row_index, indices in enumerate(rows):
        if not indices:
            continue
        matrix[row_index, indices] = idf_array[indices]
        norm = float(np.linalg.norm(matrix[row_index])) or 1.0
        matrix[row_index] /= norm
    return matrix, idf_array


def binary_metrics(truth, predicted) -> Dict[str, float | int]:
    truth_values = [bool(item) for item in truth]
    predicted_values = [bool(item) for item in predicted]
    if len(truth_values) != len(predicted_values):
        raise ValueError("truth/predicted length mismatch")
    tp = sum(expected and actual for expected, actual in zip(truth_values, predicted_values))
    fp = sum(not expected and actual for expected, actual in zip(truth_values, predicted_values))
    fn = sum(expected and not actual for expected, actual in zip(truth_values, predicted_values))
    tn = sum(not expected and not actual for expected, actual in zip(truth_values, predicted_values))
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    f1 = 2 * precision * recall / max(1e-12, precision + recall)
    specificity = tn / max(1, tn + fp)
    balanced = (recall + specificity) / 2
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "balanced_accuracy": round(balanced, 6),
    }


def choose_threshold(scores, truth) -> Tuple[float, Dict[str, float | int]]:
    import numpy as np

    scores = np.asarray(scores, dtype=np.float64)
    truth = np.asarray(truth, dtype=bool)
    ordered = np.unique(scores)
    candidates = [float(ordered[0] - 1e-6), float(ordered[-1] + 1e-6)]
    candidates.extend(float((left + right) / 2) for left, right in zip(ordered[:-1], ordered[1:]))
    best: Tuple[Tuple[float, ...], float, Dict[str, float | int]] | None = None
    for threshold in candidates:
        metrics = binary_metrics(truth, scores >= threshold)
        precision = float(metrics["precision"])
        recall = float(metrics["recall"])
        beta2 = 0.25
        f_half = (1 + beta2) * precision * recall / max(1e-12, beta2 * precision + recall)
        objective = (
            f_half,
            float(metrics["balanced_accuracy"]),
            precision,
            recall,
            -abs(threshold),
        )
        if best is None or objective > best[0]:
            best = (objective, threshold, metrics)
    assert best is not None
    return float(best[1]), best[2]


def labels_for(records: Sequence[Dict[str, object]], labels: Sequence[str]):
    import numpy as np

    matrix = np.zeros((len(records), len(labels)), dtype=bool)
    by_label = {label: index for index, label in enumerate(labels)}
    for row_index, record in enumerate(records):
        for label in record.get("epistemic_labels") or []:
            if label in by_label:
                matrix[row_index, by_label[label]] = True
    return matrix


def sparse_prototypes(train_records, train_x) -> List[Dict[str, object]]:
    import numpy as np

    prototypes: List[Dict[str, object]] = []
    for record, row in zip(train_records, train_x):
        indices = np.flatnonzero(row)
        prototypes.append(
            {
                "id": str(record.get("id") or ""),
                "category": str(record.get("category") or ""),
                "labels": [str(label) for label in record.get("epistemic_labels") or []],
                "ordinary_negative": record.get("category") == "ordinary_no_boundary",
                "indices": [int(index) for index in indices.tolist()],
                "values": [round(float(row[index]), 7) for index in indices.tolist()],
            }
        )
    return prototypes


def semantic_embeddings(
    records: Sequence[Dict[str, object]],
    *,
    kind: str,
    python_executable: Path,
    embedding_model: str,
):
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - operator environment failure
        raise RuntimeError("NumPy is required in the trainer environment") from exc
    if not python_executable.exists():
        raise RuntimeError(f"semantic embedding Python is missing: {python_executable}")
    with tempfile.TemporaryDirectory(prefix="eve-epistemic-public-") as directory:
        root = Path(directory)
        input_path = root / "texts.json"
        output_path = root / "embeddings.npy"
        input_path.write_text(
            json.dumps(
                {
                    "kind": kind,
                    "texts": [input_for_record(record) for record in records],
                },
                ensure_ascii=True,
            ),
            encoding="utf-8",
        )
        completed = subprocess.run(
            [
                str(python_executable),
                str(SEMANTIC_EMBEDDING_WORKER),
                "--model",
                embedding_model,
                "batch",
                "--input",
                str(input_path),
                "--output",
                str(output_path),
                "--kind",
                kind,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if completed.returncode != 0 or not output_path.exists():
            detail = (completed.stderr or completed.stdout or "embedding worker failed")[-800:]
            raise RuntimeError(f"public semantic embedding failed: {detail}")
        return np.load(output_path, allow_pickle=False)


def semantic_probability_metrics(truth, probabilities, thresholds, candidate_floor: float) -> Dict[str, object]:
    import numpy as np

    active = probabilities >= thresholds[None, :]
    margins = probabilities - thresholds[None, :]
    candidates = (margins >= candidate_floor) & (margins < 0.0)
    exact = np.all(active == truth, axis=1)
    ordinary = ~truth.any(axis=1)
    return {
        "record_count": int(len(truth)),
        "active_exact_row_count": int(exact.sum()),
        "active_exact_row_rate": round(float(exact.mean()), 6),
        "active_wrong_label_count": int(np.logical_xor(active, truth).sum()),
        "candidate_row_count": int(candidates.any(axis=1).sum()),
        "candidate_label_count": int(candidates.sum()),
        "candidate_true_label_count": int((candidates & truth).sum()),
        "candidate_false_label_count": int((candidates & ~truth).sum()),
        "ordinary_active_false_positive_rows": int((active.any(axis=1) & ordinary).sum()),
        "ordinary_candidate_rows": int((candidates.any(axis=1) & ordinary).sum()),
    }


def train_semantic_classifier(
    train_records: Sequence[Dict[str, object]],
    validation_records: Sequence[Dict[str, object]],
    development_records: Sequence[Dict[str, object]],
    labels: Sequence[str],
    *,
    python_executable: Path,
    embedding_model: str,
) -> Tuple[Dict[str, object], Dict[str, object]]:
    try:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
    except ImportError as exc:  # pragma: no cover - operator environment failure
        raise RuntimeError("NumPy and scikit-learn are required in the isolated trainer") from exc

    train_x = semantic_embeddings(
        train_records,
        kind="passage",
        python_executable=python_executable,
        embedding_model=embedding_model,
    )
    validation_x = semantic_embeddings(
        validation_records,
        kind="query",
        python_executable=python_executable,
        embedding_model=embedding_model,
    )
    development_x = semantic_embeddings(
        development_records,
        kind="query",
        python_executable=python_executable,
        embedding_model=embedding_model,
    )
    train_y = labels_for(train_records, labels)
    validation_y = labels_for(validation_records, labels)
    development_y = labels_for(development_records, labels)
    classifiers: Dict[str, object] = {}
    validation_probabilities = np.zeros_like(validation_y, dtype=np.float64)
    development_probabilities = np.zeros_like(development_y, dtype=np.float64)
    thresholds: List[float] = []
    per_label: Dict[str, object] = {}
    for label_index, label in enumerate(labels):
        estimator = LogisticRegression(
            C=1.0,
            class_weight="balanced",
            max_iter=2000,
            solver="liblinear",
        )
        estimator.fit(train_x, train_y[:, label_index])
        validation_scores = estimator.predict_proba(validation_x)[:, 1]
        development_scores = estimator.predict_proba(development_x)[:, 1]
        threshold, metrics = choose_threshold(validation_scores, validation_y[:, label_index])
        thresholds.append(float(threshold))
        validation_probabilities[:, label_index] = validation_scores
        development_probabilities[:, label_index] = development_scores
        classifiers[str(label)] = {
            "intercept": round(float(estimator.intercept_[0]), 8),
            "threshold": round(float(threshold), 8),
            "weights": [round(float(item), 8) for item in estimator.coef_[0].tolist()],
        }
        per_label[str(label)] = {
            **metrics,
            "threshold": round(float(threshold), 6),
            "train_positive_count": int(train_y[:, label_index].sum()),
            "validation_positive_count": int(validation_y[:, label_index].sum()),
        }
    threshold_array = np.asarray(thresholds, dtype=np.float64)
    semantic = {
        "kind": eve_epistemic.SEMANTIC_KIND,
        "embedding_model": embedding_model,
        "dimension": int(train_x.shape[1]),
        "candidate_margin_floor": SEMANTIC_CANDIDATE_MARGIN_FLOOR,
        "exclusive_label_groups": [ACTION_STAGE_LABELS],
        "classifiers": classifiers,
        "private_inputs_used": False,
        "training": {
            "kind": "public_embedding_logistic_one_vs_rest",
            "train_count": len(train_records),
            "validation_count": len(validation_records),
            "development_count": len(development_records),
            "solver": "liblinear",
            "class_weight": "balanced",
            "C": 1.0,
        },
    }
    metrics = {
        "validation": {
            **semantic_probability_metrics(
                validation_y,
                validation_probabilities,
                threshold_array,
                SEMANTIC_CANDIDATE_MARGIN_FLOOR,
            ),
            "per_label": per_label,
        },
        "development_transfer": {
            **semantic_probability_metrics(
                development_y,
                development_probabilities,
                threshold_array,
                SEMANTIC_CANDIDATE_MARGIN_FLOOR,
            ),
            "boundary": "Disclosed public development cases; not a private promotion holdout.",
        },
    }
    return semantic, metrics


def runtime_validation_metrics(
    payload: Dict[str, object],
    records: Sequence[Dict[str, object]],
    labels: Sequence[str],
) -> Dict[str, object]:
    expected_by_label: Dict[str, List[bool]] = {label: [] for label in labels}
    predicted_by_label: Dict[str, List[bool]] = {label: [] for label in labels}
    exact = 0
    ordinary_rows = 0
    ordinary_false_positive_rows = 0
    rows: List[Dict[str, object]] = []
    for record in records:
        expected = {str(item) for item in record.get("epistemic_labels") or []}
        result = eve_epistemic.classify(input_for_record(record), model=payload)
        predicted = {
            str(item.get("label") or "")
            for item in result.get("labels") or []
            if isinstance(item, dict) and str(item.get("label") or "")
        }
        row_exact = expected == predicted
        exact += int(row_exact)
        if record.get("category") == "ordinary_no_boundary":
            ordinary_rows += 1
            ordinary_false_positive_rows += int(bool(predicted))
        for label in labels:
            expected_by_label[label].append(label in expected)
            predicted_by_label[label].append(label in predicted)
        rows.append(
            {
                "id": record.get("id"),
                "category": record.get("category"),
                "expected": sorted(expected),
                "predicted": sorted(predicted),
                "exact": row_exact,
            }
        )
    per_label = {
        label: binary_metrics(expected_by_label[label], predicted_by_label[label])
        for label in labels
    }
    return {
        "record_count": len(records),
        "exact_row_count": exact,
        "exact_row_rate": round(exact / max(1, len(records)), 6),
        "macro_f1": round(sum(float(item["f1"]) for item in per_label.values()) / max(1, len(per_label)), 6),
        "ordinary_negative_count": ordinary_rows,
        "ordinary_false_positive_rows": ordinary_false_positive_rows,
        "ordinary_false_positive_rate": round(ordinary_false_positive_rows / max(1, ordinary_rows), 6),
        "per_label": per_label,
        "rows": rows,
    }


def train_model(
    curriculum_path: Path,
    *,
    dimension: int,
    ridge: float,
) -> Dict[str, object]:
    import numpy as np

    curriculum = jsonl_records(curriculum_path)
    try:
        curriculum_artifact_path = str(curriculum_path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        curriculum_artifact_path = curriculum_path.name
    augmentations = public_semantic_augmentations()
    all_records = [*curriculum, *augmentations, *public_negative_controls()]
    train_records = [record for record in all_records if record.get("split") == "train"]
    validation_records = [record for record in all_records if record.get("split") == "validation"]
    development_records = public_transfer_diagnostics()
    labels = sorted(
        {
            str(label)
            for record in curriculum
            for label in (record.get("epistemic_labels") or [])
            if str(label)
        }
    )
    train_x, idf = feature_matrix(train_records, dimension)
    validation_x, _ = feature_matrix(validation_records, dimension, idf=idf)
    train_y = labels_for(train_records, labels)
    validation_y = labels_for(validation_records, labels)
    classifiers: Dict[str, object] = {}
    validation_metrics: Dict[str, object] = {}
    validation_predictions = np.zeros_like(validation_y)
    for label_index, label in enumerate(labels):
        truth = train_y[:, label_index]
        positives = int(truth.sum())
        negatives = len(truth) - positives
        if positives == 0 or negatives == 0:
            raise ValueError(f"label {label} lacks positive or negative training examples")
        sample_weight = np.where(
            truth,
            len(truth) / (2.0 * positives),
            len(truth) / (2.0 * negatives),
        )
        weighted_x = train_x * np.sqrt(sample_weight)[:, None]
        weighted_y = np.where(truth, 1.0, -1.0) * np.sqrt(sample_weight)
        gram = weighted_x @ weighted_x.T
        alpha = np.linalg.solve(gram + ridge * np.eye(len(train_records)), weighted_y)
        weights = weighted_x.T @ alpha
        train_scores = train_x @ weights
        validation_scores = validation_x @ weights
        threshold, metrics = choose_threshold(validation_scores, validation_y[:, label_index])
        predicted = validation_scores >= threshold
        validation_predictions[:, label_index] = predicted
        positive_scores = validation_scores[validation_y[:, label_index]]
        negative_scores = validation_scores[~validation_y[:, label_index]]
        separation = float(np.median(positive_scores) - np.median(negative_scores))
        temperature = max(0.03, min(1.0, abs(separation) / 4.0))
        validation_metrics[label] = {
            **metrics,
            "threshold": round(threshold, 6),
            "train_positive_count": positives,
            "validation_positive_count": int(validation_y[:, label_index].sum()),
            "median_separation": round(separation, 6),
        }
        classifiers[label] = {
            "bias": 0.0,
            "threshold": round(threshold, 8),
            "temperature": round(temperature, 8),
            "weights": [round(float(item), 8) for item in weights.tolist()],
        }
    linear_exact_rows = np.all(validation_predictions == validation_y, axis=1)
    linear_macro_f1 = sum(float(item["f1"]) for item in validation_metrics.values()) / max(1, len(labels))
    ordinary_rows = [index for index, record in enumerate(validation_records) if record.get("category") == "ordinary_no_boundary"]
    linear_ordinary_false_positive_rows = sum(bool(validation_predictions[index].any()) for index in ordinary_rows)
    semantic, semantic_metrics = train_semantic_classifier(
        train_records,
        validation_records,
        development_records,
        labels,
        python_executable=SEMANTIC_EMBEDDING_PYTHON,
        embedding_model=SEMANTIC_EMBEDDING_MODEL,
    )
    payload: Dict[str, object] = {
        "schema_id": eve_epistemic.MODEL_SCHEMA_ID,
        "model_id": MODEL_ID,
        "model_kind": "hierarchical_public_sparse_plus_dense_semantic_epistemic_perception",
        "trained_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "dimension": dimension,
        "feature_contract": {
            "runtime": "eve_epistemic.feature_names",
            "word_ngrams": [1, 2, 3],
            "character_ngrams": [3, 4, 5],
            "vector": "binary_tfidf_l2",
        },
        "labels": labels,
        "idf": [round(float(item), 8) for item in idf.tolist()],
        "classifiers": classifiers,
        "retrieval": {
            "kind": "public_sparse_exemplar_knn",
            "top_k": RETRIEVAL_TOP_K,
            "hybrid_weight": HYBRID_WEIGHT,
            "activation_margin_floor": ACTIVATION_MARGIN_FLOOR,
            "exclusive_label_groups": [ACTION_STAGE_LABELS],
            "prototypes": sparse_prototypes(train_records, train_x),
            "private_inputs_used": False,
        },
        "semantic": semantic,
        "training": {
            "curriculum_path": curriculum_artifact_path,
            "curriculum_sha256": hashlib.sha256(curriculum_path.read_bytes()).hexdigest(),
            "public_boundary_train_count": sum(record.get("split") == "train" for record in curriculum),
            "public_boundary_validation_count": sum(record.get("split") == "validation" for record in curriculum),
            "public_ordinary_train_count": 80,
            "public_ordinary_validation_count": 40,
            "public_semantic_augmentation_train_count": sum(record.get("split") == "train" for record in augmentations),
            "public_semantic_augmentation_validation_count": sum(record.get("split") == "validation" for record in augmentations),
            "ridge": ridge,
            "private_inputs_used": False,
        },
        "linear_baseline": {
            "record_count": len(validation_records),
            "exact_row_count": int(linear_exact_rows.sum()),
            "exact_row_rate": round(float(linear_exact_rows.mean()), 6),
            "macro_f1": round(linear_macro_f1, 6),
            "ordinary_negative_count": len(ordinary_rows),
            "ordinary_false_positive_rows": int(linear_ordinary_false_positive_rows),
            "ordinary_false_positive_rate": round(linear_ordinary_false_positive_rows / max(1, len(ordinary_rows)), 6),
            "per_label": validation_metrics,
        },
        "boundary": (
            "Learned public pre-generation state classifier only. It does not generate final answers, "
            "contain hidden probes, prove consciousness, or authorize actions."
        ),
    }
    hybrid_validation = runtime_validation_metrics(payload, validation_records, labels)
    development_transfer = runtime_validation_metrics(payload, public_transfer_diagnostics(), labels)
    payload["validation"] = {
        **{key: value for key, value in hybrid_validation.items() if key != "rows"},
        "linear_baseline": payload.pop("linear_baseline"),
        "development_transfer": {
            **{key: value for key, value in development_transfer.items() if key not in {"rows", "per_label"}},
            "boundary": "Disclosed public development cases; not a private promotion holdout.",
        },
        "semantic": semantic_metrics,
    }
    payload["artifact_sha256"] = eve_epistemic._model_digest(payload)  # type: ignore[attr-defined]
    return payload


def evaluate_model(payload: Dict[str, object], curriculum_path: Path) -> Dict[str, object]:
    records = [*jsonl_records(curriculum_path), *public_semantic_augmentations(), *public_negative_controls()]
    labels = list(payload.get("labels") or [])
    split_records = [record for record in records if record.get("split") == "validation"]
    metrics = runtime_validation_metrics(payload, split_records, labels)
    development_transfer = runtime_validation_metrics(payload, public_transfer_diagnostics(), labels)
    return {
        "schema_id": "eve.epistemic_model_evaluation.v1",
        "model_id": payload.get("model_id"),
        "model_sha256": payload.get("artifact_sha256"),
        "curriculum_sha256": hashlib.sha256(curriculum_path.read_bytes()).hexdigest(),
        **metrics,
        "development_transfer": development_transfer,
        "boundary": "Public behavior evaluation only; a fresh private holdout is still required before live adoption.",
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="command", required=True)
    train = sub.add_parser("train")
    train.add_argument("--curriculum", type=Path, default=DEFAULT_CURRICULUM)
    train.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    train.add_argument("--dimension", type=int, default=4096)
    train.add_argument("--ridge", type=float, default=0.35)
    train.add_argument("--json", action="store_true")
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--curriculum", type=Path, default=DEFAULT_CURRICULUM)
    evaluate.add_argument("--model", type=Path, default=DEFAULT_OUTPUT)
    evaluate.add_argument("--json", action="store_true")
    status = sub.add_parser("status")
    status.add_argument("--model", type=Path, default=DEFAULT_OUTPUT)
    status.add_argument("--json", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    if args.command == "train":
        payload = train_model(args.curriculum, dimension=args.dimension, ridge=args.ridge)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        output = {"status": "trained", "output": str(args.output), **payload["validation"], "artifact_sha256": payload["artifact_sha256"]}
    elif args.command == "evaluate":
        payload = eve_epistemic.validate_model(json.loads(args.model.read_text(encoding="utf-8")))
        output = evaluate_model(payload, args.curriculum)
    else:
        output = eve_epistemic.model_status(args.model)
    print(json.dumps(output, ensure_ascii=True, indent=2, sort_keys=True) if args.json else output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
