#!/usr/bin/env python3
"""Collect and evaluate a preregistered read-only lived feature stream."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eve_lived_feature_stream as lived  # noqa: E402
import eve_predictive_dynamics as dynamics  # noqa: E402


EVAL_SCHEMA = "eve.lived_predictive_transfer_evaluation.v1"
PROTOCOL_TRIAL_ID = "pp1-lived-readonly-feature-transfer-v1"
BOUNDARY = (
    "Read-only lived aggregate forecast evidence; not subjective experience "
    "and not proof of consciousness."
)


def collect_samples(contract: Mapping[str, object]) -> List[Dict[str, object]]:
    # Importing Eve here is deliberate: the evaluator reads the canonical
    # snapshots but never writes state or invokes a daemon cycle.
    import eve  # noqa: WPS433

    count = int(contract.get("sample_count") or 0)
    interval = float(contract.get("interval_seconds") or 0.0)
    if count < 2 or interval < 0:
        raise ValueError("invalid lived sampling contract")
    samples: List[Dict[str, object]] = []
    for index in range(count):
        observed_at = datetime.now(timezone.utc).isoformat()
        samples.append(
            lived.collect_local_snapshot(
                eve.load_system_snapshot(prefer_runtime=True),
                eve.load_homeostasis(prefer_runtime=True),
                observed_at=observed_at,
            )
        )
        if index + 1 < count:
            time.sleep(interval)
    return samples


def _feature_contract(contract: Mapping[str, object]) -> Dict[str, Dict[str, object]]:
    records = contract.get("features") if isinstance(contract.get("features"), list) else []
    return {
        str(item.get("id") or ""): dict(item)
        for item in records
        if isinstance(item, Mapping) and item.get("id")
    }


def evaluate_samples(
    contract: Mapping[str, object],
    samples: Sequence[Mapping[str, object]],
    *,
    evaluated_at: str | None = None,
    protocol_trial_id: str = PROTOCOL_TRIAL_ID,
) -> Dict[str, object]:
    timestamp = evaluated_at or datetime.now(timezone.utc).isoformat()
    minimum_history = int(contract.get("minimum_history") or 0)
    minimum_comparisons = int(contract.get("minimum_comparisons_per_arm") or 0)
    feature_contract = _feature_contract(contract)
    if minimum_history < 2 or not feature_contract:
        raise ValueError("lived feature evaluation contract is incomplete")
    projected_samples: List[Dict[str, object]] = []
    for sample in samples:
        source_features = (
            sample.get("features") if isinstance(sample.get("features"), Mapping) else {}
        )
        projected_samples.append(
            {
                "schema_version": sample.get("schema_version"),
                "observed_at": sample.get("observed_at"),
                "features": {
                    feature_id: dict(record)
                    for feature_id, record in source_features.items()
                    if feature_id in feature_contract and isinstance(record, Mapping)
                },
                "read_only": bool(sample.get("read_only")),
                "raw_media_retained": bool(sample.get("raw_media_retained")),
                "user_content_retained": bool(sample.get("user_content_retained")),
                "process_identity_retained": bool(sample.get("process_identity_retained")),
                "action_authority": bool(sample.get("action_authority")),
            }
        )
    sample_times = [
        datetime.fromisoformat(str(sample.get("observed_at") or "").replace("Z", "+00:00"))
        for sample in projected_samples
    ]
    temporal_order = all(later > earlier for earlier, later in zip(sample_times, sample_times[1:]))
    arms: Dict[str, List[Dict[str, object]]] = {"intact": [], "lesion": []}
    for feature_id, spec in feature_contract.items():
        values: List[tuple[int, float, str]] = []
        last_source_time = None
        for index, sample in enumerate(projected_samples):
            features = sample.get("features") if isinstance(sample.get("features"), Mapping) else {}
            record = features.get(feature_id) if isinstance(features.get(feature_id), Mapping) else {}
            value = record.get("value")
            source_observed_at = str(record.get("source_observed_at") or "")
            try:
                source_time = datetime.fromisoformat(source_observed_at.replace("Z", "+00:00"))
            except ValueError:
                source_time = None
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and source_time is not None
                and (last_source_time is None or source_time > last_source_time)
            ):
                values.append((index, float(value), source_observed_at))
                last_source_time = source_time
        if len(values) <= minimum_history:
            continue
        # Missing a sample breaks the prospective history for this fixed
        # contract; never silently bridge an unobserved interval.
        if [item[0] for item in values] != list(range(len(projected_samples))):
            continue
        limit = float(spec.get("limit") or 0.0)
        precision = float(spec.get("precision") or 0.0)
        series = [item[1] for item in values]
        for index in range(minimum_history, len(series)):
            history = series[:index]
            actual = series[index]
            observed_at = values[index][2]
            for arm, experts in (
                ("intact", dynamics.NUMERIC_EXPERTS),
                ("lesion", ("velocity",)),
            ):
                forecast = dynamics.forecast_numeric(
                    history,
                    limit=limit,
                    source_precision=precision,
                    enabled_experts=experts,
                )
                result = dynamics.evaluate_observation(actual, forecast)
                raw_error = float(result.get("raw_error_percent") or 0.0)
                arms[arm].append(
                    {
                        "feature_id": feature_id,
                        "sample_index": index,
                        "observed_at": observed_at,
                        "selected_expert": forecast.get("selected_expert"),
                        "forecast_precision": forecast.get("forecast_precision"),
                        "prediction": forecast.get("prediction"),
                        "actual": actual,
                        "raw_error_percent": round(raw_error, 6),
                        "accuracy_percent": round(max(0.0, 100.0 - raw_error), 6),
                        "action_authority": bool(forecast.get("action_authority")),
                    }
                )
    means = {
        arm: round(
            sum(float(record["accuracy_percent"]) for record in records) / len(records),
            6,
        )
        if records
        else None
        for arm, records in arms.items()
    }
    paired = min(len(arms["intact"]), len(arms["lesion"]))
    effect = (
        round(float(means["intact"]) - float(means["lesion"]), 6)
        if means["intact"] is not None and means["lesion"] is not None
        else None
    )
    privacy_ok = all(
        isinstance(sample.get("features"), Mapping)
        and set(sample["features"]).issubset(feature_contract)
        and not sample.get("raw_media_retained")
        and not sample.get("user_content_retained")
        and not sample.get("process_identity_retained")
        for sample in projected_samples
    )
    checks = {
        "minimum_paired_comparisons_met": paired >= minimum_comparisons,
        "temporal_order_verified": temporal_order,
        "privacy_boundary_verified": privacy_ok,
        "read_only_contract_preserved": all(bool(sample.get("read_only")) for sample in samples),
        "no_forecast_has_action_authority": not any(
            record["action_authority"] for records in arms.values() for record in records
        ),
    }
    evidence: List[Dict[str, object]] = []
    for arm, records in arms.items():
        for index, record in enumerate(records):
            evidence.append(
                {
                    "evidence_id": f"pp1-lived-{arm}-{index + 1}",
                    "trial_id": protocol_trial_id,
                    "arm": arm,
                    "value": record["accuracy_percent"],
                    "observed_at": record["observed_at"],
                    "source": "read-only-lived-feature-transfer-runner",
                    "evidence_class": "lived",
                    "feature_id": record["feature_id"],
                    "sample_index": record["sample_index"],
                }
            )
    return {
        "schema_version": EVAL_SCHEMA,
        "evaluated_at": timestamp,
        "status": "evidence_ready" if all(checks.values()) else "invalid_evidence",
        "indicator_id": "PP-1",
        "protocol_trial_id": protocol_trial_id,
        "contract_digest": contract.get("contract_digest"),
        "sample_count": len(projected_samples),
        "observed_feature_ids": sorted(
            {record["feature_id"] for record in arms["intact"]}
        ),
        "paired_comparison_count": paired,
        "intact_mean_accuracy_percent": means["intact"],
        "lesion_mean_accuracy_percent": means["lesion"],
        "directional_effect": effect,
        "checks": checks,
        "samples": projected_samples,
        "arms": arms,
        "protocol_evidence": evidence,
        "runtime_mutated": False,
        "consciousness_proven": False,
        "subjective_experience_inferred": False,
        "boundary": BOUNDARY,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect and evaluate Eve's preregistered read-only lived feature stream."
    )
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    parser.add_argument("--protocol-trial-id", default=PROTOCOL_TRIAL_ID)
    args = parser.parse_args()
    contract = lived.validate_contract(json.loads(args.contract.read_text(encoding="utf-8")))
    report = evaluate_samples(
        contract,
        collect_samples(contract),
        protocol_trial_id=args.protocol_trial_id,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_output.write_text(
        json.dumps(report["protocol_evidence"], ensure_ascii=True, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    sys.stdout.write(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n")
    return 0 if report["status"] == "evidence_ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
