#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_backend(value: str | None) -> str:
    backend = str(value or "json").strip().lower()
    if backend not in {"json", "lancedb"}:
        return "json"
    return backend


def normalize_query_mode(value: str | None) -> str:
    mode = str(value or "vector").strip().lower()
    if mode not in {"vector", "hybrid", "text"}:
        return "vector"
    return mode


def load_notes(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"Invalid notes payload at {path}")
    return payload


def load_index(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"Invalid index payload at {path}")
    return payload


def is_lexical_model(model_name: str | None) -> bool:
    normalized = str(model_name or "").strip().lower()
    return normalized in {"lexical", "lexical-local", "local-lexical", "lexical-fallback"} or normalized.startswith("lexical:")


def tokenize(text: str) -> list[str]:
    return [item.lower() for item in re.findall(r"[A-Za-z0-9_']{2,}", text)]


def build_lexical_rows(notes: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for note in notes:
        text = str(note.get("text") or "")
        title = str(note.get("title") or "")
        terms = Counter(tokenize(f"{title} {text}"))
        rows.append(
            {
                "id": note.get("id"),
                "source": note.get("source"),
                "title": note.get("title"),
                "text": note.get("text"),
                "tags": [str(tag) for tag in note.get("tags") or [] if str(tag).strip()],
                "terms": dict(terms),
            }
        )
    return rows


def query_lexical_index(payload: dict, query_text: str) -> list[dict]:
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise SystemExit("No lexical index entries found.")
    query_terms = Counter(tokenize(query_text))
    if not query_terms:
        raise SystemExit("No searchable query terms found.")
    query_norm = math.sqrt(sum(count * count for count in query_terms.values())) or 1.0
    ranked: list[dict] = []
    for entry in entries:
        terms = entry.get("terms") if isinstance(entry.get("terms"), dict) else {}
        doc_norm = math.sqrt(sum(float(count) * float(count) for count in terms.values())) or 1.0
        dot = sum(float(terms.get(term) or 0.0) * float(count) for term, count in query_terms.items())
        score = dot / (query_norm * doc_norm)
        if score <= 0:
            continue
        match = base_match_from_item(entry)
        match["raw_score"] = round(float(score), 6)
        match["score"] = round(float(score), 6)
        ranked.append(match)
    return sorted(ranked, key=lambda item: item["score"], reverse=True)


def encode_passages(model, tokenizer, texts: list[str]):
    import mlx.core as mx

    encoded = tokenizer(texts, padding=True, truncation=True, return_tensors="mlx")
    output = model(encoded["input_ids"], encoded["attention_mask"])
    return output.text_embeds


def build_rows(notes: list[dict], embeddings: list[list[float]]) -> tuple[list[dict], list[dict]]:
    json_rows: list[dict] = []
    lance_rows: list[dict] = []
    for note, vector in zip(notes, embeddings, strict=False):
        base = {
            "id": note.get("id"),
            "source": note.get("source"),
            "title": note.get("title"),
            "text": note.get("text"),
            "tags": [str(tag) for tag in note.get("tags") or [] if str(tag).strip()],
        }
        json_rows.append({**base, "embedding": [float(item) for item in vector]})
        lance_rows.append({**base, "vector": [float(item) for item in vector]})
    return json_rows, lance_rows


def resolve_lancedb_dir(index_path: Path, db_dir_value: str | None) -> Path:
    if not db_dir_value or not str(db_dir_value).strip():
        raise SystemExit("Missing LanceDB directory path.")
    candidate = Path(str(db_dir_value).strip()).expanduser()
    if not candidate.is_absolute():
        candidate = index_path.resolve().parent / candidate
    return candidate


def build_json_index(
    output_path: Path,
    notes_payload: dict,
    rows: list[dict],
    *,
    model_name: str,
    query_mode: str,
) -> dict:
    payload = {
        "updated_at": utc_now(),
        "backend": "json",
        "query_mode": query_mode,
        "model": model_name,
        "note_count": len(rows),
        "notes_hash": notes_payload.get("notes_hash"),
        "entries": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def build_lancedb_index(
    output_path: Path,
    notes_payload: dict,
    rows: list[dict],
    *,
    model_name: str,
    query_mode: str,
    db_dir_value: str,
    table_name: str,
) -> dict:
    import lancedb
    from lancedb.index import FTS

    db_dir = resolve_lancedb_dir(output_path, db_dir_value)
    db_dir.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(db_dir))
    table = db.create_table(table_name, data=rows, mode="overwrite")
    table.create_index("text", config=FTS(), replace=True)
    payload = {
        "updated_at": utc_now(),
        "backend": "lancedb",
        "query_mode": query_mode,
        "model": model_name,
        "note_count": len(rows),
        "notes_hash": notes_payload.get("notes_hash"),
        "db_dir": db_dir_value,
        "table_name": table_name,
        "vector_column": "vector",
        "text_column": "text",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def score_from_distance(distance: float) -> float:
    bounded = max(0.0, float(distance))
    return 1.0 / (1.0 + bounded)


def base_match_from_item(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "source": item.get("source"),
        "title": item.get("title"),
        "text": item.get("text"),
        "tags": item.get("tags") if isinstance(item.get("tags"), list) else [],
    }


def normalize_ranked_results(results: list[dict], raw_key: str) -> list[dict]:
    raw_scores = [float(item.get(raw_key) or 0.0) for item in results]
    best_score = max(raw_scores) if raw_scores else 0.0
    matches: list[dict] = []
    for rank, (item, raw_score) in enumerate(zip(results, raw_scores, strict=False), start=1):
        if best_score > 0:
            normalized = raw_score / best_score
        else:
            normalized = 1.0 / float(rank)
        match = base_match_from_item(item)
        match["raw_score"] = round(float(raw_score), 6)
        match["score"] = round(float(normalized), 6)
        matches.append(match)
    return matches


def query_json_index(payload: dict, query_embedding) -> list[dict]:
    import mlx.core as mx

    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise SystemExit("No index entries found.")
    matrix = mx.array([entry.get("embedding") for entry in entries], dtype=mx.float32)
    scores = mx.matmul(matrix, query_embedding).tolist()
    ranked = sorted(
        (
            {
                **base_match_from_item(entry),
                "raw_score": float(score),
                "score": round(float(score), 6),
            }
            for entry, score in zip(entries, scores, strict=False)
        ),
        key=lambda item: item["score"],
        reverse=True,
    )
    return ranked


def query_lancedb_index(payload: dict, index_path: Path, query_embedding, query_text: str, query_mode: str, limit: int) -> list[dict]:
    import lancedb

    db_dir = resolve_lancedb_dir(index_path, str(payload.get("db_dir") or "").strip())
    table_name = str(payload.get("table_name") or "memory_notes").strip()
    db = lancedb.connect(str(db_dir))
    table = db.open_table(table_name)
    vector = query_embedding.tolist()
    expanded_limit = max(limit, limit * 3)

    if query_mode == "text":
        results = table.search(query_text).limit(expanded_limit).to_list()
        return normalize_ranked_results(results, "_score")
    if query_mode == "hybrid":
        results = (
            table.search(query_type="hybrid")
            .vector(vector)
            .text(query_text)
            .limit(expanded_limit)
            .to_list()
        )
        return normalize_ranked_results(results, "_relevance_score")

    results = table.search(vector).limit(expanded_limit).to_list()
    matches: list[dict] = []
    for item in results:
        raw_distance = float(item.get("_distance") or 0.0)
        match = base_match_from_item(item)
        match["raw_score"] = round(raw_distance, 6)
        match["score"] = round(score_from_distance(raw_distance), 6)
        matches.append(match)
    return matches


def cmd_build(args: argparse.Namespace) -> int:
    notes_payload = load_notes(Path(args.notes))
    notes = notes_payload.get("notes")
    if not isinstance(notes, list) or not notes:
        raise SystemExit("No notes found to embed.")

    output_path = Path(args.output)
    backend = normalize_backend(args.backend)
    query_mode = normalize_query_mode(args.query_mode)
    if is_lexical_model(args.model):
        index_payload = build_json_index(
            output_path,
            notes_payload,
            build_lexical_rows(notes),
            model_name=args.model,
            query_mode="text",
        )
        backend = "json"
        query_mode = "text"
    else:
        from mlx_embeddings import load

        model, tokenizer = load(args.model)
        passage_texts = [
            f"task: sentence similarity | passage: {str(note.get('text') or '').strip()}"
            for note in notes
        ]
        embeddings = encode_passages(model, tokenizer, passage_texts).tolist()
        json_rows, lance_rows = build_rows(notes, embeddings)

        if backend == "lancedb":
            index_payload = build_lancedb_index(
                output_path,
                notes_payload,
                lance_rows,
                model_name=args.model,
                query_mode=query_mode,
                db_dir_value=args.db_dir,
                table_name=args.table,
            )
        else:
            index_payload = build_json_index(
                output_path,
                notes_payload,
                json_rows,
                model_name=args.model,
                query_mode=query_mode,
            )

    print(
        json.dumps(
            {
                "ok": True,
                "backend": backend,
                "query_mode": query_mode,
                "note_count": index_payload.get("note_count"),
                "output": str(output_path),
            },
            indent=2,
        )
    )
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    index_path = Path(args.index)
    payload = load_index(index_path)
    model_name = str(payload.get("model") or args.model or "").strip()
    if not model_name:
        raise SystemExit("Missing model name for query.")
    backend = normalize_backend(args.backend or payload.get("backend"))
    query_mode = normalize_query_mode(args.query_mode or payload.get("query_mode"))

    if is_lexical_model(model_name):
        backend = "json"
        query_mode = "text"
        ranked = query_lexical_index(payload, args.query.strip())
    else:
        from mlx_embeddings import load

        model, tokenizer = load(model_name)
        query_text = f"task: sentence similarity | query: {args.query.strip()}"
        query_embedding = encode_passages(model, tokenizer, [query_text])[0]
        if backend == "lancedb":
            ranked = query_lancedb_index(payload, index_path, query_embedding, args.query.strip(), query_mode, max(1, args.limit))
        else:
            ranked = query_json_index(payload, query_embedding)

    print(
        json.dumps(
            {
                "query": args.query,
                "backend": backend,
                "query_mode": query_mode,
                "model": model_name,
                "matches": ranked[: max(1, args.limit)],
            },
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and query Eve's local memory retrieval index.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Embed note records into a local retrieval index.")
    build_parser.add_argument("--notes", required=True, help="Path to the notes JSON file.")
    build_parser.add_argument("--output", required=True, help="Path to write the retrieval index metadata JSON.")
    build_parser.add_argument("--model", required=True, help="Embedding model repo or local path.")
    build_parser.add_argument("--backend", choices=["json", "lancedb"], default="json", help="Retrieval backend to build.")
    build_parser.add_argument("--query-mode", choices=["vector", "hybrid", "text"], default="vector", help="Default query mode to record in index metadata.")
    build_parser.add_argument("--db-dir", help="Relative or absolute directory for the LanceDB database.")
    build_parser.add_argument("--table", default="memory_notes", help="LanceDB table name.")
    build_parser.set_defaults(func=cmd_build)

    query_parser = subparsers.add_parser("query", help="Query a built embedding index.")
    query_parser.add_argument("--index", required=True, help="Path to the retrieval index metadata JSON.")
    query_parser.add_argument("--query", required=True, help="Text to retrieve against the index.")
    query_parser.add_argument("--limit", type=int, default=3, help="How many matches to return.")
    query_parser.add_argument("--model", help="Optional override model. Defaults to the model stored in the index.")
    query_parser.add_argument("--backend", choices=["json", "lancedb"], help="Optional override backend. Defaults to the backend stored in the index.")
    query_parser.add_argument("--query-mode", choices=["vector", "hybrid", "text"], help="Query mode override. Defaults to the mode stored in the index.")
    query_parser.set_defaults(func=cmd_query)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
