#!/usr/bin/env python3
"""Persistent local worker for Eve's typed epistemic-event percept.

The protocol returns labels, probabilities, timing, and an input digest.  It
never echoes, stores, or writes the input text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List

from eve_epistemic_event_model import (
    ARCHITECTURE as STRUCTURED_ARCHITECTURE,
    INFERENCE_SHAPE as STRUCTURED_INFERENCE_SHAPE,
    SLOT_LOGIT_NAMES,
    decode_logits,
    manifest_slot_schema,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "eve_epistemic_event_v1.json"
MAX_INPUT_CHARS = 4000


def canonical_digest(payload: Dict[str, object]) -> str:
    clean = dict(payload)
    clean.pop("artifact_sha256", None)
    raw = json.dumps(clean, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class EventPercept:
    def __init__(self, manifest_path: Path, model_dir: Path | None = None) -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if payload.get("artifact_sha256") != canonical_digest(payload):
            raise ValueError("epistemic event manifest digest mismatch")
        configured_path = Path(str(payload.get("model_path") or ""))
        model_candidates = []
        if model_dir is not None:
            model_candidates.append(model_dir)
        if configured_path.is_absolute():
            model_candidates.append(configured_path)
        else:
            model_candidates.append(ROOT / configured_path)
            for env_name in ("EVE_SOURCE_DIR", "EVE_PROJECT_ROOT"):
                if os.environ.get(env_name, "").strip():
                    model_candidates.append(Path(os.environ[env_name]).expanduser() / configured_path)
            model_candidates.append(Path.home() / "Documents" / "Finances" / "Eve" / configured_path)
        resolved_model_dir = next(
            (candidate for candidate in model_candidates if (candidate / "model.safetensors").exists()),
            model_candidates[0],
        )
        model_file = resolved_model_dir / "model.safetensors"
        if not model_file.exists():
            raise FileNotFoundError(f"epistemic event model is missing: {model_file}")
        if payload.get("model_file_sha256") != file_sha256(model_file):
            raise ValueError("epistemic event model digest mismatch")
        expected_files = (
            payload.get("model_files_sha256")
            if isinstance(payload.get("model_files_sha256"), dict)
            else {}
        )
        if not expected_files:
            raise ValueError("epistemic event model bundle digests are missing")
        for relative, expected in expected_files.items():
            relative_path = Path(str(relative))
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise ValueError("epistemic event model bundle path is invalid")
            candidate = resolved_model_dir / relative_path
            if not candidate.is_file() or file_sha256(candidate) != str(expected):
                raise ValueError(f"epistemic event model bundle digest mismatch: {relative}")

        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        torch.set_num_threads(max(1, min(6, torch.get_num_threads())))
        self.torch = torch
        self.payload = payload
        self.labels = [str(label) for label in payload.get("labels") or []]
        self.thresholds = {
            str(label): float(value)
            for label, value in (payload.get("thresholds") or {}).items()
        }
        self.hypotheses = {
            str(label): str(value)
            for label, value in (payload.get("hypotheses") or {}).items()
        }
        self.model_id = str(payload.get("model_id") or "")
        self.model_sha256 = str(payload.get("artifact_sha256") or "")
        self.architecture = str(payload.get("architecture") or "")
        if self.architecture not in {
            "label_aware_nli_cross_encoder",
            "shared_typed_event_encoder",
            STRUCTURED_ARCHITECTURE,
        }:
            raise ValueError("unsupported epistemic event architecture")
        expected_worker_sha256 = str(
            (payload.get("runtime") or {}).get("worker_sha256") or ""
        )
        if (
            self.architecture in {"shared_typed_event_encoder", STRUCTURED_ARCHITECTURE}
            and expected_worker_sha256 != file_sha256(Path(__file__).resolve())
        ):
            raise ValueError("epistemic event worker digest mismatch")
        runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
        self.max_length = max(64, min(512, int(runtime.get("max_length") or 192)))
        self.tokenizer = AutoTokenizer.from_pretrained(resolved_model_dir, local_files_only=True)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            resolved_model_dir,
            local_files_only=True,
        ).eval()
        if (
            self.architecture == "shared_typed_event_encoder"
            and int(self.model.config.num_labels) != len(self.labels)
        ):
            raise ValueError("shared typed-event classifier label count mismatch")
        self.binary_slot_thresholds = {
            str(slot): float(value)
            for slot, value in (payload.get("binary_slot_thresholds") or {}).items()
        }
        if self.architecture == STRUCTURED_ARCHITECTURE:
            if (runtime.get("inference_shape") or "") != STRUCTURED_INFERENCE_SHAPE:
                raise ValueError("structured typed-slot inference contract mismatch")
            if payload.get("slot_schema") != manifest_slot_schema():
                raise ValueError("structured typed-slot schema mismatch")
            if int(self.model.config.num_labels) != len(SLOT_LOGIT_NAMES):
                raise ValueError("structured typed-slot classifier logit count mismatch")
            configured_names = [
                str(self.model.config.id2label.get(index, ""))
                for index in range(len(SLOT_LOGIT_NAMES))
            ]
            if configured_names != list(SLOT_LOGIT_NAMES):
                raise ValueError("structured typed-slot classifier logit order mismatch")
        self.entailment_index = next(
            (
                int(index)
                for index, name in self.model.config.id2label.items()
                if str(name).lower() == "entailment"
            ),
            0,
        )

    def classify_many(self, texts: List[str]) -> List[Dict[str, object]]:
        clean = [" ".join(str(text or "")[:MAX_INPUT_CHARS].split()) for text in texts]
        started = time.perf_counter()
        if self.architecture in {"shared_typed_event_encoder", STRUCTURED_ARCHITECTURE}:
            encoded = self.tokenizer(
                clean,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            )
        else:
            premises = [text for text in clean for _label in self.labels]
            hypotheses = [self.hypotheses[label] for _text in clean for label in self.labels]
            encoded = self.tokenizer(
                premises,
                hypotheses,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            )
        with self.torch.inference_mode():
            logits = self.model(**encoded).logits
            if self.architecture == STRUCTURED_ARCHITECTURE:
                decoded_rows = decode_logits(
                    logits.float().cpu().numpy(),
                    binary_thresholds=self.binary_slot_thresholds,
                )
                probabilities = [
                    [float(row["probabilities"][label]) for label in self.labels]
                    for row in decoded_rows
                ]
            else:
                decoded_rows = []
                probabilities = (
                    self.torch.sigmoid(logits)
                    if self.architecture == "shared_typed_event_encoder"
                    else self.torch.softmax(logits, dim=-1)[:, self.entailment_index].reshape(
                        len(clean), len(self.labels)
                    )
                ).cpu().tolist()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        results: List[Dict[str, object]] = []
        for row_index, (text, row) in enumerate(zip(clean, probabilities)):
            by_label = {
                label: round(float(row[index]), 6)
                for index, label in enumerate(self.labels)
            }
            decoded = decoded_rows[row_index] if decoded_rows else {}
            active = (
                [str(label) for label in decoded.get("active_labels") or []]
                if decoded
                else [
                    label
                    for label in self.labels
                    if by_label.get(label, 0.0) >= self.thresholds.get(label, 0.5)
                ]
            )
            results.append(
                {
                    "ok": True,
                    "model_id": self.model_id,
                    "model_sha256": self.model_sha256,
                    "active_labels": active,
                    "probabilities": by_label,
                    "thresholds": self.thresholds,
                    "event_slots": decoded.get("slots") if decoded else {},
                    "input_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "duration_ms": round(elapsed_ms / max(1, len(clean)), 3),
                    "runtime": "eve_epistemic_event_worker",
                }
            )
        return results


def response_for(worker: EventPercept, request: object) -> Dict[str, object]:
    if not isinstance(request, dict):
        return {"ok": False, "reason": "request must be a JSON object"}
    request_id = str(request.get("id") or "")
    text = str(request.get("text") or "")
    if not text.strip():
        return {"id": request_id, "ok": False, "reason": "text is empty"}
    result = worker.classify_many([text])[0]
    result["id"] = request_id
    return result


def serve(worker: EventPercept) -> int:
    sys.stdout.write(
        json.dumps(
            {
                "ok": True,
                "type": "ready",
                "model_id": worker.model_id,
                "model_sha256": worker.model_sha256,
                "architecture": worker.architecture,
            },
            ensure_ascii=True,
            sort_keys=True,
        )
        + "\n"
    )
    sys.stdout.flush()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            result = response_for(worker, request)
        except Exception as exc:
            result = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"[:300]}
        sys.stdout.write(json.dumps(result, ensure_ascii=True, sort_keys=True) + "\n")
        sys.stdout.flush()
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("command", choices=["serve", "once"])
    result.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    result.add_argument("--model-dir", type=Path)
    result.add_argument("--text", default="")
    return result


def main() -> int:
    args = parser().parse_args()
    worker = EventPercept(args.manifest, args.model_dir)
    if args.command == "serve":
        return serve(worker)
    print(json.dumps(response_for(worker, {"id": "once", "text": args.text}), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
