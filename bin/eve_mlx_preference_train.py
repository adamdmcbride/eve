#!/usr/bin/env python3
"""Reference-anchored MLX LoRA preference training for Eve.

MLX-LM currently exposes supervised LoRA training but no DPO command.  This
trainer implements a small reference-anchored preference objective over public
chosen/rejected pairs.  It computes length-normalized unchanged-base margins,
then trains only LoRA weights to increase the chosen-vs-rejected margin while a
small chosen-answer NLL term preserves ordinary generation.  Gradient clipping
and public base-passing replay anchors protect behavior the unchanged model
already gets right.  Training pads examples to one static shape before using
compiled updates; this avoids the non-finite dynamic-shape path and the eager
Metal-memory blow-up observed on the resident 4B workload.  Every step checks
loss and gradient norm, checkpoint boundaries scan all trainable parameters,
and every abort writes a non-candidate failure manifest.  It writes a candidate
adapter and manifest only; it never changes Eve's live routing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple


SCHEMA_ID = "eve.mlx_reference_preference_training.v2"
THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "TOKENIZERS_PARALLELISM": "false",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_preferences(
    path: Path,
    *,
    split: str,
    allow_local_only: bool = False,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            if row.get("split") != split:
                continue
            privacy_tier = str(row.get("privacy_tier") or "")
            allowed_tiers = {"public", "local_only"} if allow_local_only else {"public"}
            if privacy_tier not in allowed_tiers or row.get("safe_for_training") is not True:
                raise ValueError(
                    f"{path}:{line_number}: preference rows must be in {sorted(allowed_tiers)!r} and safe_for_training"
                )
            if privacy_tier == "local_only" and row.get("exportable") is not False:
                raise ValueError(f"{path}:{line_number}: local-only rows must be marked nonexportable")
            if row.get("private_content_included") is not False:
                raise ValueError(f"{path}:{line_number}: private-content boundary missing")
            messages = row.get("messages")
            chosen = str(row.get("chosen") or "").strip()
            rejected = str(row.get("rejected") or "").strip()
            objective = str(row.get("training_objective") or "preference_correction")
            if objective not in {"preference_correction", "rehearsal_anchor"}:
                raise ValueError(f"{path}:{line_number}: unsupported training objective {objective!r}")
            if not isinstance(messages, list) or not messages or not chosen:
                raise ValueError(f"{path}:{line_number}: incomplete preference pair")
            if objective == "preference_correction" and (not rejected or chosen == rejected):
                raise ValueError(f"{path}:{line_number}: incomplete preference pair")
            if objective == "rehearsal_anchor" and rejected:
                raise ValueError(f"{path}:{line_number}: replay anchors must not carry a rejected answer")
            row["training_objective"] = objective
            rows.append(row)
    return rows


def build_plan(args: argparse.Namespace) -> Dict[str, object]:
    preference_path = Path(args.preferences).expanduser()
    base_model = Path(args.base_model).expanduser() if args.base_model else Path()
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else Path()
    train = (
        read_preferences(
            preference_path,
            split="train",
            allow_local_only=bool(args.allow_local_only),
        )
        if preference_path.exists()
        else []
    )
    validation = (
        read_preferences(
            preference_path,
            split="validation",
            allow_local_only=bool(args.allow_local_only),
        )
        if preference_path.exists()
        else []
    )
    missing = []
    if not preference_path.exists():
        missing.append("preferences")
    if not train:
        missing.append("train_preferences")
    if not validation:
        missing.append("validation_preferences")
    if not args.base_model or not base_model.exists():
        missing.append("base_model")
    if not args.output_dir:
        missing.append("output_dir")
    if (
        args.rank <= 0
        or args.num_layers == 0
        or args.beta <= 0
        or args.learning_rate <= 0
        or getattr(args, "adam_eps", 1e-6) <= 0
        or args.max_grad_norm <= 0
        or args.rehearsal_weight <= 0
        or args.anchor_logp_tolerance < 0
        or not 0 <= args.max_anchor_regression_rate <= 1
    ):
        missing.append("training_hyperparameters")
    return {
        "schema_id": SCHEMA_ID,
        "status": "ready" if not missing else "blocked",
        "run": bool(args.run),
        "preferences": str(preference_path),
        "preferences_sha256": file_sha256(preference_path) if preference_path.exists() else "",
        "train_pairs": len(train),
        "validation_pairs": len(validation),
        "train_preference_corrections": sum(
            row.get("training_objective") == "preference_correction" for row in train
        ),
        "train_rehearsal_anchors": sum(
            row.get("training_objective") == "rehearsal_anchor" for row in train
        ),
        "validation_preference_corrections": sum(
            row.get("training_objective") == "preference_correction" for row in validation
        ),
        "validation_rehearsal_anchors": sum(
            row.get("training_objective") == "rehearsal_anchor" for row in validation
        ),
        "privacy_tiers": sorted({str(row.get("privacy_tier") or "") for row in [*train, *validation]}),
        "local_only_pairs": sum(row.get("privacy_tier") == "local_only" for row in [*train, *validation]),
        "base_model": str(base_model) if args.base_model else "",
        "output_dir": str(output_dir) if args.output_dir else "",
        "rank": args.rank,
        "alpha": args.alpha,
        "num_layers": args.num_layers,
        "beta": args.beta,
        "sft_weight": args.sft_weight,
        "rehearsal_weight": args.rehearsal_weight,
        "anchor_logp_tolerance": args.anchor_logp_tolerance,
        "max_anchor_regression_rate": args.max_anchor_regression_rate,
        "learning_rate": args.learning_rate,
        "adam_eps": getattr(args, "adam_eps", 1e-6),
        "compile_steps": bool(getattr(args, "compile_steps", False)),
        "reference_cache": str(
            Path(args.reference_cache).expanduser()
            if getattr(args, "reference_cache", "")
            else ""
        ),
        "max_grad_norm": args.max_grad_norm,
        "iters": args.iters,
        "missing": missing,
        "boundary": (
            "Candidate training only; no adapter is fused, promoted, or routed by this command. "
            "Any artifact trained with local_only rows is nonexportable."
        ),
    }


def _token_list(value: object) -> List[int]:
    if isinstance(value, dict):
        value = value.get("input_ids")
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, list) and value and isinstance(value[0], list):
        value = value[0]
    if not isinstance(value, list):
        raise ValueError("tokenizer did not return a token list")
    return [int(item) for item in value]


def encode_pair(tokenizer, row: Mapping[str, object], *, max_seq_length: int) -> Dict[str, object]:
    messages = [
        {"role": str(item.get("role") or ""), "content": str(item.get("content") or "")}
        for item in row.get("messages") or []
        if isinstance(item, Mapping)
    ]
    prompt = _token_list(
        tokenizer.apply_chat_template(
            messages,
            add_generation_prompt=True,
            return_dict=False,
        )
    )
    objective = str(row.get("training_objective") or "preference_correction")
    encoded: Dict[str, object] = {
        "id": str(row.get("id") or ""),
        "category": str(row.get("category") or ""),
        "training_objective": objective,
        "prompt_length": len(prompt),
    }
    answer_keys = ("chosen", "rejected") if objective == "preference_correction" else ("chosen",)
    for key in answer_keys:
        answer = str(row.get(key) or "")
        tokens = _token_list(
            tokenizer.apply_chat_template(
                [*messages, {"role": "assistant", "content": answer}],
                return_dict=False,
            )
        )
        if len(tokens) > max_seq_length:
            tokens = tokens[:max_seq_length]
        if len(prompt) >= len(tokens):
            raise ValueError(f"{row.get('id')}: no assistant completion tokens after truncation")
        encoded[f"{key}_tokens"] = tokens
        encoded[f"{key}_offset"] = len(prompt)
    return encoded


def balanced_validation_subset(
    pairs: Sequence[Mapping[str, object]],
    limit: int,
) -> List[Mapping[str, object]]:
    """Select a deterministic round-robin sample across objective and category."""

    if limit <= 0 or limit >= len(pairs):
        return list(pairs)
    groups: Dict[Tuple[str, str], List[Mapping[str, object]]] = {}
    for pair in pairs:
        key = (
            str(pair.get("training_objective") or "preference_correction"),
            str(pair.get("category") or ""),
        )
        groups.setdefault(key, []).append(pair)
    for group in groups.values():
        group.sort(key=lambda row: str(row.get("id") or ""))
    selected: List[Mapping[str, object]] = []
    depth = 0
    while len(selected) < limit:
        added = False
        for key in sorted(groups):
            group = groups[key]
            if depth < len(group):
                selected.append(group[depth])
                added = True
                if len(selected) >= limit:
                    break
        if not added:
            break
        depth += 1
    return selected


def run_training(args: argparse.Namespace) -> Dict[str, object]:
    # Imports are intentionally confined to --run so ordinary repo tests do not
    # require the isolated Apple-Silicon trainer environment.
    import mlx.core as mx
    import mlx.nn as nn
    import mlx.optimizers as optim
    from mlx.utils import tree_flatten
    from mlx_lm.tuner.utils import linear_to_lora_layers, print_trainable_parameters
    from mlx_lm.utils import load, save_config

    preference_path = Path(args.preferences).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    adapter_dir = output_dir / "adapter"
    adapter_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_root = output_dir / "checkpoints"
    if args.save_eval_checkpoints:
        checkpoint_root.mkdir(parents=True, exist_ok=True)
    train_rows = read_preferences(
        preference_path,
        split="train",
        allow_local_only=bool(args.allow_local_only),
    )
    validation_rows = read_preferences(
        preference_path,
        split="validation",
        allow_local_only=bool(args.allow_local_only),
    )
    random.seed(args.seed)
    mx.random.seed(args.seed)
    if mx.metal.is_available():
        mx.set_wired_limit(mx.device_info()["max_recommended_working_set_size"])

    started_at = utc_now()
    started = time.monotonic()
    print("Loading unchanged reference model", flush=True)
    model, tokenizer = load(str(Path(args.base_model).expanduser()), tokenizer_config={"trust_remote_code": True})
    train_pairs = [encode_pair(tokenizer, row, max_seq_length=args.max_seq_length) for row in train_rows]
    validation_pairs = [encode_pair(tokenizer, row, max_seq_length=args.max_seq_length) for row in validation_rows]
    all_pairs = [*train_pairs, *validation_pairs]

    def sequence_stats(
        active_model,
        tokens: Sequence[int],
        offset: int,
        sequence_length: int | None = None,
    ):
        array = tokens if hasattr(tokens, "ndim") else mx.array([tokens])
        inputs = array[:, :-1]
        targets = array[:, 1:]
        logits = active_model(inputs)
        log_probs = logits - mx.logsumexp(logits, axis=-1, keepdims=True)
        selected = mx.take_along_axis(log_probs, targets[..., None], axis=-1).squeeze(-1)
        positions = mx.arange(1, targets.shape[1] + 1)
        mask = positions >= offset
        if sequence_length is not None:
            mask = mask & (positions < sequence_length)
        token_count = mask.sum()
        return (selected * mask).sum(), token_count

    def completion_mean_logp(
        active_model,
        tokens: Sequence[int],
        offset: int,
        sequence_length: int | None = None,
    ):
        logp, token_count = sequence_stats(
            active_model,
            tokens,
            offset,
            sequence_length,
        )
        return logp / token_count, token_count

    reference_key_payload = {
        "base_model": str(Path(args.base_model).expanduser().resolve()),
        "preferences_sha256": file_sha256(preference_path),
        "max_seq_length": int(args.max_seq_length),
        "record_ids": [str(pair.get("id") or "") for pair in all_pairs],
    }
    reference_key = hashlib.sha256(
        json.dumps(reference_key_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    reference_cache_path = (
        Path(args.reference_cache).expanduser().resolve()
        if args.reference_cache
        else None
    )
    cached_references: Dict[str, Dict[str, float]] = {}
    if reference_cache_path and reference_cache_path.exists():
        try:
            cache_payload = json.loads(reference_cache_path.read_text(encoding="utf-8"))
            candidate_records = cache_payload.get("records")
            if (
                cache_payload.get("schema_id") == "eve.mlx_reference_cache.v1"
                and cache_payload.get("reference_key") == reference_key
                and isinstance(candidate_records, dict)
            ):
                cached_references = {
                    str(key): dict(value)
                    for key, value in candidate_records.items()
                    if isinstance(value, dict)
                }
        except (OSError, ValueError, TypeError):
            cached_references = {}
    cache_complete = len(cached_references) == len(all_pairs) and all(
        str(pair.get("id") or "") in cached_references for pair in all_pairs
    )
    if cache_complete:
        print(
            f"Loaded {len(all_pairs)} unchanged-base references from {reference_cache_path}",
            flush=True,
        )
        for pair in all_pairs:
            values = cached_references[str(pair.get("id") or "")]
            pair["reference_chosen_logp"] = float(values["reference_chosen_logp"])
            if pair["training_objective"] == "preference_correction":
                pair["reference_margin"] = float(values["reference_margin"])
    else:
        print(
            f"Caching unchanged-base references for {len(all_pairs)} admitted records",
            flush=True,
        )
        model.eval()
        cached_references = {}
        for index, pair in enumerate(all_pairs, start=1):
            chosen_logp, _ = completion_mean_logp(
                model,
                pair["chosen_tokens"],
                int(pair["chosen_offset"]),
            )
            pair["reference_chosen_logp"] = float(chosen_logp.item())
            values = {
                "reference_chosen_logp": float(pair["reference_chosen_logp"]),
            }
            if pair["training_objective"] == "preference_correction":
                rejected_logp, _ = completion_mean_logp(
                    model,
                    pair["rejected_tokens"],
                    int(pair["rejected_offset"]),
                )
                pair["reference_margin"] = float((chosen_logp - rejected_logp).item())
                values["reference_margin"] = float(pair["reference_margin"])
            cached_references[str(pair.get("id") or "")] = values
            if index % 50 == 0:
                print(f"Cached {index} unchanged-base references", flush=True)
                mx.clear_cache()
        if reference_cache_path:
            reference_cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_payload = {
                "schema_id": "eve.mlx_reference_cache.v1",
                "reference_key": reference_key,
                "reference_key_payload": reference_key_payload,
                "records": cached_references,
                "private_content_included": False,
                "local_only_pairs": sum(
                    row.get("privacy_tier") == "local_only"
                    for row in [*train_rows, *validation_rows]
                ),
                "exportable": not any(
                    row.get("privacy_tier") == "local_only"
                    for row in [*train_rows, *validation_rows]
                ),
            }
            temporary = reference_cache_path.with_suffix(
                reference_cache_path.suffix + f".tmp-{os.getpid()}"
            )
            temporary.write_text(
                json.dumps(cache_payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, reference_cache_path)
            print(f"Saved unchanged-base reference cache to {reference_cache_path}", flush=True)

    model.freeze()
    lora_parameters = {
        "rank": int(args.rank),
        "dropout": 0.0,
        "scale": float(args.alpha) / float(args.rank),
    }
    linear_to_lora_layers(model, int(args.num_layers), lora_parameters)
    print_trainable_parameters(model)
    optimizer = optim.AdamW(
        learning_rate=float(args.learning_rate),
        eps=float(args.adam_eps),
        weight_decay=float(args.weight_decay),
        bias_correction=True,
    )
    training_sequence_length = max(
        len(pair[f"{answer}_tokens"])
        for pair in [*train_pairs, *validation_pairs]
        for answer in ("chosen", "rejected")
        if f"{answer}_tokens" in pair
    )
    pad_token_id = getattr(tokenizer, "pad_token_id", None)
    if pad_token_id is None:
        pad_token_id = getattr(tokenizer, "eos_token_id", None)
    if pad_token_id is None:
        raise ValueError("tokenizer requires a pad or EOS token for static-shape training")

    def padded_array(tokens: Sequence[int]):
        values = list(tokens)
        return mx.array(
            [values + [int(pad_token_id)] * (training_sequence_length - len(values))]
        )

    print(
        f"Using static training sequence length {training_sequence_length} tokens",
        flush=True,
    )
    for pair in [*train_pairs, *validation_pairs]:
        pair["chosen_length"] = len(pair["chosen_tokens"])
        pair["chosen_array"] = padded_array(pair["chosen_tokens"])
        if pair["training_objective"] == "preference_correction":
            pair["rejected_length"] = len(pair["rejected_tokens"])
            pair["rejected_array"] = padded_array(pair["rejected_tokens"])

    def preference_loss(
        active_model,
        chosen_tokens,
        chosen_offset,
        chosen_length,
        rejected_tokens,
        rejected_offset,
        rejected_length,
        reference_margin,
    ):
        chosen_logp, chosen_count = completion_mean_logp(
            active_model,
            chosen_tokens,
            chosen_offset,
            chosen_length,
        )
        rejected_logp, _ = completion_mean_logp(
            active_model,
            rejected_tokens,
            rejected_offset,
            rejected_length,
        )
        policy_margin = chosen_logp - rejected_logp
        relative_margin = policy_margin - reference_margin
        dpo_loss = mx.logaddexp(mx.array(0.0), -float(args.beta) * relative_margin)
        chosen_nll = -chosen_logp
        return dpo_loss + float(args.sft_weight) * chosen_nll

    def rehearsal_loss(active_model, chosen_tokens, chosen_offset, chosen_length):
        chosen_logp, _ = completion_mean_logp(
            active_model,
            chosen_tokens,
            chosen_offset,
            chosen_length,
        )
        return float(args.rehearsal_weight) * -chosen_logp

    loss_and_grad = nn.value_and_grad(model, preference_loss)
    rehearsal_loss_and_grad = nn.value_and_grad(model, rehearsal_loss)
    state = [model.state, optimizer.state, mx.random.state]

    def raw_optimization_step(
        chosen_tokens,
        chosen_offset,
        chosen_length,
        rejected_tokens,
        rejected_offset,
        rejected_length,
        reference_margin,
    ):
        loss, grads = loss_and_grad(
            model,
            chosen_tokens,
            chosen_offset,
            chosen_length,
            rejected_tokens,
            rejected_offset,
            rejected_length,
            reference_margin,
        )
        grads, grad_norm = optim.clip_grad_norm(grads, float(args.max_grad_norm))
        optimizer.update(model, grads)
        return loss, grad_norm

    def raw_rehearsal_optimization_step(chosen_tokens, chosen_offset, chosen_length):
        loss, grads = rehearsal_loss_and_grad(
            model,
            chosen_tokens,
            chosen_offset,
            chosen_length,
        )
        grads, grad_norm = optim.clip_grad_norm(grads, float(args.max_grad_norm))
        optimizer.update(model, grads)
        return loss, grad_norm

    def tree_is_finite(tree: object) -> bool:
        flags = [mx.all(mx.isfinite(value)) for _, value in tree_flatten(tree)]
        if not flags:
            return True
        mx.eval(*flags)
        return all(bool(flag.item()) for flag in flags)

    def eager_optimization_step(
        chosen_tokens,
        chosen_offset,
        chosen_length,
        rejected_tokens,
        rejected_offset,
        rejected_length,
        reference_margin,
    ):
        loss, grads = loss_and_grad(
            model,
            chosen_tokens,
            chosen_offset,
            chosen_length,
            rejected_tokens,
            rejected_offset,
            rejected_length,
            reference_margin,
        )
        mx.eval(loss, grads)
        if not bool(mx.isfinite(loss).item()) or not tree_is_finite(grads):
            return loss, mx.array(float("nan"))
        grads, grad_norm = optim.clip_grad_norm(grads, float(args.max_grad_norm))
        mx.eval(grad_norm, grads)
        if not bool(mx.isfinite(grad_norm).item()) or not tree_is_finite(grads):
            return loss, grad_norm
        optimizer.update(model, grads)
        mx.eval(state)
        if not tree_is_finite(model.trainable_parameters()):
            return mx.array(float("nan")), mx.array(float("nan"))
        mx.clear_cache()
        return loss, grad_norm

    def eager_rehearsal_optimization_step(chosen_tokens, chosen_offset, chosen_length):
        loss, grads = rehearsal_loss_and_grad(
            model,
            chosen_tokens,
            chosen_offset,
            chosen_length,
        )
        mx.eval(loss, grads)
        if not bool(mx.isfinite(loss).item()) or not tree_is_finite(grads):
            return loss, mx.array(float("nan"))
        grads, grad_norm = optim.clip_grad_norm(grads, float(args.max_grad_norm))
        mx.eval(grad_norm, grads)
        if not bool(mx.isfinite(grad_norm).item()) or not tree_is_finite(grads):
            return loss, grad_norm
        optimizer.update(model, grads)
        mx.eval(state)
        if not tree_is_finite(model.trainable_parameters()):
            return mx.array(float("nan")), mx.array(float("nan"))
        mx.clear_cache()
        return loss, grad_norm

    # Static padding gives compiled updates one graph shape. Eager remains an
    # explicit diagnostic path because the 4B workload can exceed Metal's
    # command-buffer memory before a second checked update.
    if args.compile_steps:
        optimization_step = mx.compile(raw_optimization_step, inputs=state, outputs=state)
        rehearsal_optimization_step = mx.compile(
            raw_rehearsal_optimization_step,
            inputs=state,
            outputs=state,
        )
    else:
        optimization_step = eager_optimization_step
        rehearsal_optimization_step = eager_rehearsal_optimization_step

    def pair_metrics(pairs: Sequence[Mapping[str, object]], limit: int) -> Dict[str, float]:
        model.eval()
        mx.clear_cache()
        selected_pairs = balanced_validation_subset(pairs, limit)
        preference_pairs = [
            pair for pair in selected_pairs if pair["training_objective"] == "preference_correction"
        ]
        anchor_pairs = [
            pair for pair in selected_pairs if pair["training_objective"] == "rehearsal_anchor"
        ]
        losses: List[float] = []
        wins = 0
        raw_wins = 0
        margin_gains: List[float] = []
        for pair in preference_pairs:
            chosen_logp, chosen_count = completion_mean_logp(model, pair["chosen_tokens"], int(pair["chosen_offset"]))
            rejected_logp, _ = completion_mean_logp(model, pair["rejected_tokens"], int(pair["rejected_offset"]))
            policy_margin = float((chosen_logp - rejected_logp).item())
            reference_margin = float(pair["reference_margin"])
            gain = policy_margin - reference_margin
            relative = float(args.beta) * gain
            losses.append(float(mx.logaddexp(mx.array(0.0), mx.array(-relative)).item()))
            wins += int(gain > 0.0)
            raw_wins += int(policy_margin > 0.0)
            margin_gains.append(gain)
            mx.eval(chosen_count)
            mx.clear_cache()
        anchor_deltas: List[float] = []
        anchor_regressions = 0
        for pair in anchor_pairs:
            chosen_logp, chosen_count = completion_mean_logp(
                model,
                pair["chosen_tokens"],
                int(pair["chosen_offset"]),
            )
            delta = float(chosen_logp.item()) - float(pair["reference_chosen_logp"])
            anchor_deltas.append(delta)
            anchor_regressions += int(delta < -float(args.anchor_logp_tolerance))
            mx.eval(chosen_count)
            mx.clear_cache()
        model.train()
        preference_count = max(1, len(preference_pairs))
        anchor_count = max(1, len(anchor_pairs))
        return {
            "pairs": len(selected_pairs),
            "preference_pairs": len(preference_pairs),
            "rehearsal_anchors": len(anchor_pairs),
            "preference_loss": round(sum(losses) / preference_count, 6),
            "reference_relative_win_rate": round(wins / preference_count, 6),
            "raw_chosen_win_rate": round(raw_wins / preference_count, 6),
            "mean_margin_gain": round(sum(margin_gains) / preference_count, 6),
            "mean_anchor_logp_delta": round(sum(anchor_deltas) / anchor_count, 6),
            "anchor_regression_rate": round(anchor_regressions / anchor_count, 6),
        }

    adapter_file = adapter_dir / "adapters.safetensors"
    best_file = adapter_dir / "best_adapters.safetensors"
    history: List[Dict[str, object]] = []
    best_key: Tuple[float, float, float, float] | None = None
    best_step = 0
    checkpoint_records: List[Dict[str, object]] = []

    def save_weights(path: Path) -> None:
        mx.save_safetensors(str(path), dict(tree_flatten(model.trainable_parameters())))

    def config_for_step(step: int) -> Dict[str, object]:
        return {
            "model": str(Path(args.base_model).expanduser().resolve()),
            "fine_tune_type": "lora",
            "num_layers": int(args.num_layers),
            "lora_parameters": lora_parameters,
            "training_objective": "length_normalized_reference_preference_plus_admitted_replay",
            "beta": float(args.beta),
            "sft_weight": float(args.sft_weight),
            "rehearsal_weight": float(args.rehearsal_weight),
            "checkpoint_step": step,
        }

    order = list(range(len(train_pairs)))
    model.train()
    for step in range(1, int(args.iters) + 1):
        if (step - 1) % len(order) == 0:
            random.shuffle(order)
        pair = train_pairs[order[(step - 1) % len(order)]]
        if pair["training_objective"] == "preference_correction":
            loss, grad_norm = optimization_step(
                pair["chosen_array"],
                mx.array(int(pair["chosen_offset"])),
                mx.array(int(pair["chosen_length"])),
                pair["rejected_array"],
                mx.array(int(pair["rejected_offset"])),
                mx.array(int(pair["rejected_length"])),
                mx.array(float(pair["reference_margin"])),
            )
        else:
            loss, grad_norm = rehearsal_optimization_step(
                pair["chosen_array"],
                mx.array(int(pair["chosen_offset"])),
                mx.array(int(pair["chosen_length"])),
            )
        mx.eval(state, loss, grad_norm)
        loss_value = float(loss.item())
        grad_norm_value = float(grad_norm.item())
        # A full tree scan after every compiled step retains enough Metal graph
        # state to exhaust the command-buffer budget on this 4B workload.  The
        # current loss/gradient is the fail-closed per-step signal; scan all
        # trainable parameters only at the checkpoint boundary after releasing
        # cached graph allocations.
        checkpoint_boundary = (
            step % int(args.steps_per_eval) == 0 or step == int(args.iters)
        )
        parameters_finite = True
        if checkpoint_boundary:
            mx.clear_cache()
            parameters_finite = tree_is_finite(model.trainable_parameters())
            mx.clear_cache()
        if not (
            loss_value == loss_value
            and grad_norm_value == grad_norm_value
            and parameters_finite
        ):
            raise FloatingPointError(
                f"non-finite optimization state at step {step}: "
                f"loss={loss_value} grad_norm={grad_norm_value} "
                f"parameters_finite={parameters_finite}"
            )
        if step % int(args.steps_per_report) == 0 or step == 1 or step == int(args.iters):
            print(
                f"Step {step}: loss={loss_value:.6f} grad_norm={grad_norm_value:.6f} "
                f"peak_memory_gb={mx.get_peak_memory() / 1e9:.3f}",
                flush=True,
            )
        if step % int(args.steps_per_eval) == 0 or step == int(args.iters):
            metrics = pair_metrics(validation_pairs, int(args.validation_limit))
            metrics["step"] = step
            history.append(metrics)
            if args.save_eval_checkpoints:
                checkpoint_dir = checkpoint_root / f"step-{step:04d}"
                checkpoint_dir.mkdir(parents=True, exist_ok=True)
                checkpoint_file = checkpoint_dir / "adapters.safetensors"
                save_weights(checkpoint_file)
                save_config(config_for_step(step), checkpoint_dir / "adapter_config.json")
                checkpoint_records.append(
                    {
                        "step": step,
                        "path": str(checkpoint_dir),
                        "adapter_sha256": file_sha256(checkpoint_file),
                        "selection_proxy": dict(metrics),
                    }
                )
            anchor_rate = float(metrics["anchor_regression_rate"])
            key = (
                float(anchor_rate <= float(args.max_anchor_regression_rate)),
                float(metrics["reference_relative_win_rate"]),
                -anchor_rate,
                -float(metrics["preference_loss"]),
            )
            print(f"Validation {json.dumps(metrics, sort_keys=True)}", flush=True)
            if best_key is None or key > best_key:
                best_key = key
                best_step = step
                save_weights(best_file)
                print(f"Saved best adapter at step {step}", flush=True)
            model.train()
            mx.clear_cache()

    save_weights(adapter_file)
    if best_file.exists():
        adapter_file.write_bytes(best_file.read_bytes())
    adapter_config = config_for_step(best_step)
    adapter_config["best_step"] = best_step
    save_config(adapter_config, adapter_dir / "adapter_config.json")
    manifest = {
        "schema_id": SCHEMA_ID,
        "status": "trained",
        "started_at": started_at,
        "completed_at": utc_now(),
        "duration_seconds": round(time.monotonic() - started, 3),
        "base_model": str(Path(args.base_model).expanduser().resolve()),
        "preferences": str(preference_path),
        "preferences_sha256": file_sha256(preference_path),
        "train_pairs": len(train_pairs),
        "validation_pairs": len(validation_pairs),
        "train_preference_corrections": sum(
            pair["training_objective"] == "preference_correction" for pair in train_pairs
        ),
        "train_rehearsal_anchors": sum(
            pair["training_objective"] == "rehearsal_anchor" for pair in train_pairs
        ),
        "validation_preference_corrections": sum(
            pair["training_objective"] == "preference_correction" for pair in validation_pairs
        ),
        "validation_rehearsal_anchors": sum(
            pair["training_objective"] == "rehearsal_anchor" for pair in validation_pairs
        ),
        "privacy_tiers": sorted(
            {str(row.get("privacy_tier") or "") for row in [*train_rows, *validation_rows]}
        ),
        "local_only_pairs": sum(
            row.get("privacy_tier") == "local_only" for row in [*train_rows, *validation_rows]
        ),
        "exportable": not any(
            row.get("privacy_tier") == "local_only" for row in [*train_rows, *validation_rows]
        ),
        "adapter_path": str(adapter_dir),
        "adapter_file": str(adapter_file),
        "adapter_sha256": file_sha256(adapter_file),
        "best_step": best_step,
        "training_sequence_length": training_sequence_length,
        "reference_cache": str(reference_cache_path) if reference_cache_path else "",
        "reference_key": reference_key,
        "validation_history": history,
        "evaluation_checkpoints": checkpoint_records,
        "hyperparameters": {
            "rank": int(args.rank),
            "alpha": int(args.alpha),
            "num_layers": int(args.num_layers),
            "beta": float(args.beta),
            "sft_weight": float(args.sft_weight),
            "rehearsal_weight": float(args.rehearsal_weight),
            "anchor_logp_tolerance": float(args.anchor_logp_tolerance),
            "max_anchor_regression_rate": float(args.max_anchor_regression_rate),
            "learning_rate": float(args.learning_rate),
            "adam_eps": float(args.adam_eps),
            "bias_correction": True,
            "compile_steps": bool(args.compile_steps),
            "weight_decay": float(args.weight_decay),
            "max_grad_norm": float(args.max_grad_norm),
            "iters": int(args.iters),
            "max_seq_length": int(args.max_seq_length),
            "seed": int(args.seed),
        },
        "private_content_included": False,
        "boundary": "Candidate artifact only; no live Eve lane changed.",
    }
    manifest_path = output_dir / "training_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--preferences", required=True)
    value.add_argument("--base-model", required=True)
    value.add_argument("--output-dir", required=True)
    value.add_argument("--run", action="store_true")
    value.add_argument(
        "--allow-local-only",
        action="store_true",
        help="Permit explicitly nonexportable local_only correction rows in this local candidate run.",
    )
    value.add_argument("--rank", type=int, default=8)
    value.add_argument("--alpha", type=int, default=8)
    value.add_argument("--num-layers", type=int, default=8)
    value.add_argument("--beta", type=float, default=0.1)
    value.add_argument("--sft-weight", type=float, default=0.05)
    value.add_argument("--rehearsal-weight", type=float, default=0.2)
    value.add_argument("--anchor-logp-tolerance", type=float, default=0.02)
    value.add_argument("--max-anchor-regression-rate", type=float, default=0.1)
    value.add_argument("--learning-rate", type=float, default=5e-7)
    value.add_argument(
        "--adam-eps",
        type=float,
        default=1e-6,
        help="AdamW stability epsilon; 1e-6 is the conservative mixed-precision default.",
    )
    value.add_argument(
        "--compile-steps",
        dest="compile_steps",
        action="store_true",
        help="Use static-shape compiled optimizer steps (default).",
    )
    value.add_argument(
        "--eager-steps",
        dest="compile_steps",
        action="store_false",
        help="Use checked eager updates for diagnosis; not recommended for the resident 4B workload.",
    )
    value.add_argument(
        "--reference-cache",
        default="",
        help="Optional local JSON cache for unchanged-base log probabilities across failed/retried runs.",
    )
    value.add_argument("--weight-decay", type=float, default=0.01)
    value.add_argument("--max-grad-norm", type=float, default=1.0)
    value.add_argument("--iters", type=int, default=160)
    value.add_argument("--max-seq-length", type=int, default=768)
    value.add_argument("--steps-per-report", type=int, default=10)
    value.add_argument("--steps-per-eval", type=int, default=40)
    value.add_argument(
        "--validation-limit",
        type=int,
        default=0,
        help="0 evaluates every public selection record; positive values use a balanced subset.",
    )
    value.add_argument("--seed", type=int, default=20260719)
    value.add_argument(
        "--no-save-eval-checkpoints",
        dest="save_eval_checkpoints",
        action="store_false",
        help="Disable intermediate candidate checkpoints. Default keeps them for exact public generation selection.",
    )
    value.set_defaults(save_eval_checkpoints=True, compile_steps=True)
    return value


def write_failure_manifest(args: argparse.Namespace, error: Exception) -> Path:
    """Leave an auditable non-candidate record when local training aborts."""

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    preferences = Path(args.preferences).expanduser().resolve()
    payload = {
        "schema_id": "eve.mlx_training_failure.v1",
        "status": "failed",
        "failed_at": utc_now(),
        "error_type": type(error).__name__,
        "error": str(error)[:1000],
        "base_model": str(Path(args.base_model).expanduser().resolve()),
        "preferences": str(preferences),
        "preferences_sha256": file_sha256(preferences) if preferences.exists() else "",
        "compile_steps": bool(args.compile_steps),
        "candidate_emitted": False,
        "live_route_changed": False,
        "private_content_included": False,
        "boundary": "Failed training is diagnostic evidence only and cannot be promoted.",
    }
    path = output_dir / "failure_manifest.json"
    temporary = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)
    return path


def main() -> int:
    args = parser().parse_args()
    plan = build_plan(args)
    if not args.run or plan["status"] != "ready":
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0 if plan["status"] == "ready" else 2
    for key, value in THREAD_ENV.items():
        os.environ.setdefault(key, value)
    try:
        report = run_training(args)
    except Exception as error:
        failure_path = write_failure_manifest(args, error)
        print(f"Training failed closed; failure manifest: {failure_path}", file=sys.stderr)
        raise
    return 0 if report.get("status") == "trained" else 3


if __name__ == "__main__":
    raise SystemExit(main())
