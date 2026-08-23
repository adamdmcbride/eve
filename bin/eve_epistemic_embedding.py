#!/usr/bin/env python3
"""EmbeddingGemma worker for Eve's learned epistemic perception.

The live mode is a long-running JSONL subprocess so Eve's system-Python
runtime can use the isolated MLX environment without loading the model for
every turn.  The batch mode exists only to train the public semantic artifact.
Neither mode writes prompts, embeddings, or hidden evaluator text to Eve's
runtime stores.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Iterable, List


os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

DEFAULT_MODEL = "mlx-community/embeddinggemma-300m-6bit"
MAX_TEXT_CHARS = 2400
MAX_BATCH_SIZE = 128


def normalized_text(value: object) -> str:
    return " ".join(str(value or "").split())[:MAX_TEXT_CHARS]


def query_text(value: object) -> str:
    return f"task: sentence similarity | query: {normalized_text(value)}"


def passage_text(value: object) -> str:
    return f"task: sentence similarity | passage: {normalized_text(value)}"


def load_embedding_model(model_name: str):
    from mlx_embeddings import load

    return load(model_name)


def encode_batches(model, tokenizer, texts: Iterable[str], *, batch_size: int = 64):
    import mlx.core as mx
    import numpy as np

    values = list(texts)
    arrays: List[object] = []
    bounded_batch = max(1, min(MAX_BATCH_SIZE, int(batch_size or 64)))
    for index in range(0, len(values), bounded_batch):
        encoded = tokenizer(
            values[index : index + bounded_batch],
            padding=True,
            truncation=True,
            return_tensors="mlx",
        )
        output = model(encoded["input_ids"], encoded["attention_mask"])
        embeddings = output.text_embeds
        mx.eval(embeddings)
        arrays.append(np.asarray(embeddings, dtype=np.float32))
    if not arrays:
        return np.zeros((0, 0), dtype=np.float32)
    return np.concatenate(arrays, axis=0)


def run_batch(args: argparse.Namespace) -> int:
    import numpy as np

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("texts"), list):
        raise SystemExit("Batch input must be a JSON object with a texts array.")
    kind = str(payload.get("kind") or args.kind or "passage").strip().lower()
    if kind not in {"passage", "query"}:
        raise SystemExit("Embedding kind must be passage or query.")
    values = [normalized_text(item) for item in payload["texts"]]
    model, tokenizer = load_embedding_model(args.model)
    formatter = passage_text if kind == "passage" else query_text
    embeddings = encode_batches(
        model,
        tokenizer,
        [formatter(item) for item in values],
        batch_size=args.batch_size,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    np.save(output, embeddings, allow_pickle=False)
    print(
        json.dumps(
            {
                "ok": True,
                "model": args.model,
                "kind": kind,
                "count": int(embeddings.shape[0]),
                "dimension": int(embeddings.shape[1]) if len(embeddings.shape) == 2 else 0,
                "output": str(output),
            },
            sort_keys=True,
        )
    )
    return 0


def run_serve(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    model, tokenizer = load_embedding_model(args.model)
    print(
        json.dumps(
            {
                "type": "ready",
                "ok": True,
                "model": args.model,
                "load_ms": round((time.perf_counter() - started) * 1000, 3),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    for raw_line in sys.stdin:
        request_id = ""
        try:
            payload = json.loads(raw_line)
            if not isinstance(payload, dict):
                raise ValueError("request must be an object")
            request_id = str(payload.get("id") or "")[:120]
            text = normalized_text(payload.get("text"))
            if not text:
                raise ValueError("text is empty")
            request_started = time.perf_counter()
            embedding = encode_batches(model, tokenizer, [query_text(text)], batch_size=1)[0]
            result = {
                "id": request_id,
                "ok": True,
                "model": args.model,
                "input_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "dimension": int(embedding.shape[0]),
                "embedding": [round(float(item), 8) for item in embedding.tolist()],
                "duration_ms": round((time.perf_counter() - request_started) * 1000, 3),
            }
        except Exception as exc:
            result = {
                "id": request_id,
                "ok": False,
                "error_kind": type(exc).__name__,
                "error": str(exc)[:240],
            }
        print(json.dumps(result, ensure_ascii=True, sort_keys=True), flush=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    subparsers = parser.add_subparsers(dest="command", required=True)

    batch = subparsers.add_parser("batch", help="Embed public training rows into a NumPy matrix.")
    batch.add_argument("--input", required=True)
    batch.add_argument("--output", required=True)
    batch.add_argument("--kind", choices=["passage", "query"], default="passage")
    batch.add_argument("--batch-size", type=int, default=64)
    batch.set_defaults(func=run_batch)

    serve = subparsers.add_parser("serve", help="Serve one query embedding per JSONL request.")
    serve.set_defaults(func=run_serve)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
